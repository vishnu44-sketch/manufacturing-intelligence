"""db.py - the shared database and file helpers of the ML step.

- MlTable      one result table: name, comment, columns (name, MySQL type, comment) and its primary key.
               Every table and column gets a COMMENT, so get_schema / the data dictionary can explain it.
- mysql_engine the ADMIN login of .env (MYSQL_HOST / PORT / USER / PASSWORD) - the same settings as
               loader/load_gold.py. It is a copy of the loader's 8 lines, not an import, because the Docker
               image holds ml/ but not loader/ (the loader folder is only mounted into the loader service).
- check_target the safety rule of every write: only tables named ml_* and only inside ss_gold.
- write_results DROP + CREATE + INSERT of the result tables, then one line per scenario in ml_run_log
               (ml_run_log keeps the history of the runs: it is created once and never dropped; a column added
               to it later is added to the existing table by add_missing_columns).
- read_frame   one SELECT into a pandas DataFrame (DECIMAL columns become float).
- save_csv     the training data (the ML's input) of a scenario as a CSV file in ml_inputdata/.

Passwords are never printed.
"""
import math
import os
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

REPO_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(__file__).resolve().parent.parent / "ml_inputdata"   # the ML input files (17-Nov: own folder next to inputdata/)
load_dotenv(REPO_DIR / ".env")

GOLD_DB = "ss_gold"                     # the ONLY database the ML step writes to
ML_TABLE_NAME = re.compile(r"ml_[a-z0-9_]+")   # the ONLY tables it writes (created, dropped, filled)


class WriteRefused(Exception):
    """A write to a table that is not ml_* or to a database that is not ss_gold was stopped."""


def check_target(database, table_name):
    """Raise WriteRefused unless the write goes to ss_gold and to a table named ml_<lower-case letters,
    digits, _>. Every create, drop and insert of the ML step passes here first."""
    if database != GOLD_DB:
        raise WriteRefused(f"The ML step writes only into the database '{GOLD_DB}', not '{database}'.")
    if not isinstance(table_name, str) or not ML_TABLE_NAME.fullmatch(table_name):
        raise WriteRefused(f"The ML step writes only ml_* tables, not '{table_name}'.")


class MlTable:
    """One ML result table. columns: list of (column name, MySQL type, plain-English comment).
    primary_key: the column(s) of the primary key. indexes: columns with an index."""

    def __init__(self, name, comment, columns, primary_key, indexes=()):
        check_target(GOLD_DB, name)          # a wrong name fails at import time already
        self.name = name
        self.comment = comment
        self.columns = columns
        self.primary_key = list(primary_key)
        self.indexes = list(indexes)

    @property
    def column_names(self):
        return [c[0] for c in self.columns]

    def create_sql(self, if_not_exists=False):
        lines = [f"  `{name}` {sql_type} COMMENT {sql_text(comment)}" for name, sql_type, comment in self.columns]
        lines.append("  PRIMARY KEY (" + ", ".join(f"`{c}`" for c in self.primary_key) + ")")
        for column in self.indexes:
            lines.append(f"  KEY `ix_{self.name}_{column}` (`{column}`)")
        exists = "IF NOT EXISTS " if if_not_exists else ""
        return (f"CREATE TABLE {exists}`{GOLD_DB}`.`{self.name}` (\n" + ",\n".join(lines) + "\n) ENGINE=InnoDB "
                f"DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT={sql_text(self.comment)}")


RUN_LOG = MlTable("ml_run_log", (
    "ML run history: one row per scenario per run of ml/run_ml.py (the models are trained again on every run). "
    "The latest run = MAX(run_id). data_to = the newest invoice date the models saw (they work 'as of the "
    "newest data', not as of today). The ml_* result tables always hold the LATEST run only."), [
    ("run_id", "INT NOT NULL", "Run number: 1 = the first run of ml/run_ml.py, +1 on every run. The latest run = MAX(run_id)."),
    ("scenario", "VARCHAR(30) NOT NULL", "Scenario: 'sales_forecast', 'customer_risk', 'customer_segments', 'invoice_alerts', 'product_pairs' or 'stock_runout'."),
    ("result_table", "VARCHAR(64)", "The ml_* table this scenario wrote, e.g. 'ml_sales_forecast'."),
    ("rows_written", "INT", "Rows the scenario wrote into its result table in this run."),
    ("metric_name", "VARCHAR(60)", "Name of the scenario's key number, e.g. 'backtest MAPE % (last 6 months)' for the forecast."),
    ("metric_value", "DECIMAL(18,2)", "Value of that key number (e.g. 3.85 = a 3.85 % average error)."),
    ("seconds", "DECIMAL(9,2)", "Seconds the scenario took (reading, training and preparing; not the writing)."),
    ("data_to", "DATE", "Newest invoice date in ss_gold the models used (e.g. 2026-10-31). Results are 'as of' this date."),
    ("run_at", "DATETIME NOT NULL", "When this run wrote its results."),
    ("trained_on", "VARCHAR(255)", "The data this scenario was trained on / built from, in plain English, e.g. '30 complete sales months May 2024 - Oct 2026 (net sales per sales month)' for the forecast, 'invoices 02-Apr-2024 - 31-Oct-2026' for the customer groups, 'stock report 31-Oct-2026 + invoices 03-Aug-2026 - 31-Oct-2026 (the last 90 days)' for the stock run-out. NULL for runs before 18-Nov-2026."),
], primary_key=["run_id", "scenario"])


def mysql_engine(database=None):
    """Engine for the admin login in .env (same settings as loader/load_gold.py; password never printed)."""
    url = URL.create("mysql+pymysql",
                     username=os.getenv("MYSQL_USER"), password=os.getenv("MYSQL_PASSWORD"),
                     host=os.getenv("MYSQL_HOST", "localhost"),
                     port=int(os.getenv("MYSQL_PORT", "3306")),
                     database=database, query={"charset": "utf8mb4"})
    # hide_parameters: SQL errors never show the values
    return create_engine(url, hide_parameters=True)


def gold_engine():
    """The admin engine on ss_gold, after the same check as the loader: AI_GOLD_DATABASE must be ss_gold."""
    if os.getenv("AI_GOLD_DATABASE", GOLD_DB) != GOLD_DB:
        raise WriteRefused(f"AI_GOLD_DATABASE in .env must be '{GOLD_DB}' - the ML step writes nowhere else.")
    return mysql_engine(GOLD_DB)


def sql_text(value):
    """A Python string as a MySQL string literal (for COMMENT '...')."""
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def run_ddl(conn, statement):
    """Run one DDL statement exactly as written (no %-parameter handling)."""
    cursor = conn.connection.cursor()
    try:
        cursor.execute(statement)
    finally:
        cursor.close()


def plain(value):
    """A value MySQL can store: numpy numbers -> int / float, NaN / NaT / inf -> None, Timestamp -> date."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.to_pydatetime()
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def insert_rows(conn, table, rows, chunk=2000):
    """INSERT the rows (list of dicts) into the table, in chunks. A key not in the table is an error."""
    check_target(GOLD_DB, table.name)
    columns = table.column_names
    unknown = set().union(*(r.keys() for r in rows)) - set(columns) if rows else set()
    if unknown:
        raise ValueError(f"{table.name}: values for columns not in the table: {sorted(unknown)}")
    statement = (f"INSERT INTO `{GOLD_DB}`.`{table.name}` ({', '.join(f'`{c}`' for c in columns)}) "
                 f"VALUES ({', '.join(['%s'] * len(columns))})")
    for start in range(0, len(rows), chunk):
        data = [tuple(plain(row.get(c)) for c in columns) for row in rows[start:start + chunk]]
        conn.exec_driver_sql(statement, data)


def add_missing_columns(conn, table):
    """ml_run_log is created once and never dropped, so a column added to RUN_LOG later is missing in an existing
    table: ALTER TABLE ... ADD COLUMN (with its COMMENT, after the column before it) for each one that is missing.
    Nothing is changed when all columns are there. Returns the names of the columns added."""
    check_target(GOLD_DB, table.name)
    have = {str(row[0]).lower() for row in conn.execute(text(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = :db AND TABLE_NAME = :t"),
        {"db": GOLD_DB, "t": table.name}).fetchall()}
    added = []
    for i, (name, sql_type, comment) in enumerate(table.columns):
        if name.lower() in have:
            continue
        after = f" AFTER `{table.columns[i - 1][0]}`" if i else " FIRST"
        run_ddl(conn, f"ALTER TABLE `{GOLD_DB}`.`{table.name}` ADD COLUMN `{name}` {sql_type} "
                      f"COMMENT {sql_text(comment)}{after}")
        added.append(name)
    return added


def write_results(results, log_rows, engine=None):
    """Write the ML results into ss_gold.

    results  : list of (MlTable, rows) - each table is DROPPED, CREATED and filled (the latest run only)
    log_rows : one dict per scenario for ml_run_log (run_id is added here: last run + 1)
    Every table passes check_target first, and the connection must really be on ss_gold, before anything is
    dropped. Returns {table name: rows in the table after the write} and the run_id."""
    for table, _ in results:
        check_target(GOLD_DB, table.name)
    engine = engine or gold_engine()
    with engine.begin() as conn:
        current = conn.execute(text("SELECT DATABASE()")).scalar()
        check_target(current, RUN_LOG.name)     # safety: never drop or create a table anywhere else
        for table, rows in results:
            run_ddl(conn, f"DROP TABLE IF EXISTS `{GOLD_DB}`.`{table.name}`")
            run_ddl(conn, table.create_sql())
            insert_rows(conn, table, rows)
        run_ddl(conn, RUN_LOG.create_sql(if_not_exists=True))
        add_missing_columns(conn, RUN_LOG)     # an ml_run_log made before a column was added gets it now
        run_id = (conn.execute(text(f"SELECT MAX(run_id) FROM `{GOLD_DB}`.`{RUN_LOG.name}`")).scalar() or 0) + 1
        insert_rows(conn, RUN_LOG, [{**row, "run_id": run_id} for row in log_rows])
        counts = {table.name: conn.execute(text(f"SELECT COUNT(*) FROM `{GOLD_DB}`.`{table.name}`")).scalar()
                  for table, _ in results}
    return counts, run_id


def read_frame(engine, sql, params=None):
    """One SELECT into a DataFrame. DECIMAL values (Python Decimal) become float, so pandas can compute."""
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        frame = pd.DataFrame(result.fetchall(), columns=list(result.keys()))
    for column in frame.columns:
        sample = frame[column].dropna()
        if len(sample) and isinstance(sample.iloc[0], Decimal):
            frame[column] = frame[column].astype(float)
    return frame


def save_csv(frame, file_name):
    """Write a scenario's training data to ml_inputdata/<file_name> (UTF-8, no index). Returns the path."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / file_name
    frame.to_csv(path, index=False, lineterminator="\n")
    return path


def money(value):
    """A money value rounded to 2 decimals (None stays None)."""
    value = plain(value)
    return None if value is None else round(float(value), 2)


def as_date(value):
    """A date from a date / datetime / Timestamp / 'YYYY-MM-DD' (None stays None)."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def day_text(value):
    """A date as the run log writes it, e.g. '02-Apr-2024' (None stays None)."""
    value = as_date(value)
    return None if value is None else value.strftime("%d-%b-%Y")


def invoice_period(inputs, data_to):
    """The invoice dates a scenario used, for ml_run_log.trained_on: 'invoices 02-Apr-2024 - 31-Oct-2026'."""
    data_from = day_text(inputs.get("data_from"))
    return f"invoices {data_from} - {day_text(data_to)}" if data_from else f"invoices up to {day_text(data_to)}"
