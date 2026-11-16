"""The SQL page (staff only): a tree of the ai_gold tables and columns, a SQL box and the rows - like MySQL
Workbench, inside the app. The views are in api.py (/api/sql/schema, /api/sql, /api/sql/excel).

The safety rules, never skipped:
- every SQL typed here goes through the SQL guard (sql_guard.check_sql) with the ai_gold tables as the only
  allowed ones: exactly one SELECT, no other database (the app's own mi_app with its users and chats,
  information_schema, mysql ...), no writes, at most 500 rows;
- it runs only as the read-only MySQL user (warehouse.run_select): a READ ONLY session, stopped after 30 s.
No AI call and no tokens. Every run is written to the audit log by the views.

schema()     {"database", "tables": [{name, rows, columns: [{name, type}]}]} - tables A to Z, kept CACHE_SECONDS
run(sql)     {sql, columns, headers, rows, row_count, truncated, max_rows, secs} of one checked SELECT,
             or SqlProblem with the HTTP status and a plain message
saved_fields(data, creating)  the checked fields of a saved query (models.SavedQuery) - only text, never run
"""
import datetime
import decimal
import logging
import math
import threading
import time

import sqlglot
from sqlglot import exp

from . import services
from .models import SavedQuery
from .rag import agent, warehouse
from .rag.sql_guard import GuardError, check_sql, strip_fences

log = logging.getLogger(__name__)

MAX_SQL_CHARS = 20_000   # a longer SQL is refused before anything runs
CACHE_SECONDS = 300      # the tree (columns, types, row counts) is kept 5 minutes
MYSQL_DOWN = "The company data (MySQL) can't be read right now - please try again in a minute."
TIME_LIMIT_CODE = 3024   # MySQL: "maximum statement execution time exceeded"

# the column types of ai_gold, read with the read-only user (fixed SQL written here, the database name a parameter)
COLUMNS_SQL = ("SELECT table_name, column_name, column_type FROM information_schema.columns "
               "WHERE table_schema = %s ORDER BY table_name, ordinal_position")


class SqlProblem(Exception):
    """The SQL could not be run. status = the HTTP status (400 the SQL, 503 MySQL is down);
    str(problem) = the plain message for the page."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ the tree on the left
_cache = {}
_cache_lock = threading.Lock()


def clear_cache():
    """Forget the kept tree (tests; a new data load shows at once)."""
    with _cache_lock:
        _cache.clear()


def schema():
    """The ai_gold tables A to Z with their row counts and their columns (name + MySQL type) in table order.
    Kept CACHE_SECONDS; a failure is not kept (tried again next time). Only names, types and counts - never a
    host, a user name or a password. Raises WarehouseUnavailable / QueryError when MySQL cannot be read."""
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get("schema")
    if hit and now - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = _read_schema()
    with _cache_lock:
        _cache["schema"] = (now, value)
    return value


def _read_schema():
    """schema() read now: the columns from information_schema, the row counts as the Data page counts them."""
    allowed = warehouse.allowed_tables()
    found = warehouse.run_select_params(COLUMNS_SQL, (warehouse.database_name(),), max_rows=20_000)
    columns = {}
    for table, column, kind in found["rows"]:
        if str(table).lower() in allowed:  # only the tables the guard lets run
            columns.setdefault(str(table), []).append({"name": str(column), "type": _text(kind)})
    counts = {t["name"]: t["rows"] for t in services.table_counts()}
    tables = [{"name": name, "rows": int(counts.get(name.lower(), counts.get(name, 0)) or 0),
               "columns": columns[name]}
              for name in sorted(columns, key=str.lower)]
    return {"database": warehouse.database_name(), "tables": tables}


# ------------------------------------------------------------------ running one SELECT
def sql_problem(sql):
    """Why this SQL text cannot even be checked ('' = fine): empty or too long."""
    if not sql.strip():
        return "Type a SELECT query first."
    if len(sql) > MAX_SQL_CHARS:
        return f"Please keep the SQL under {MAX_SQL_CHARS:,} characters."
    return ""


def checked(sql):
    """The SQL the guard lets run (one SELECT, only ai_gold tables, at most 500 rows) - or SqlProblem."""
    problem = sql_problem(sql)
    if problem:
        raise SqlProblem(400, problem)
    try:
        allowed = warehouse.allowed_tables()
    except (warehouse.WarehouseUnavailable, warehouse.QueryError) as exc:
        log.warning("SQL page: the ai_gold tables could not be read: %s", exc)
        raise SqlProblem(503, MYSQL_DOWN) from None
    try:
        return check_sql(sql, allowed)
    except GuardError as exc:
        raise SqlProblem(400, f"This SQL cannot run: {exc}") from None


def fetch(cleaned):
    """(rows of warehouse.run_select, secs) of a SQL the guard already let through - or SqlProblem."""
    started = time.perf_counter()
    try:
        data = warehouse.run_select(cleaned)
    except warehouse.WarehouseUnavailable as exc:
        log.warning("SQL page: MySQL cannot be reached: %s", exc)  # the details (user name, host) stay in the log
        raise SqlProblem(503, MYSQL_DOWN) from None
    except warehouse.QueryError as exc:
        raise SqlProblem(400, _mysql_words(str(exc))) from None
    return data, round(time.perf_counter() - started, 3)


def run(sql):
    """Check and run one SELECT typed on the SQL page -> the reply of POST /api/sql (or SqlProblem)."""
    cleaned = checked(sql)
    data, secs = fetch(cleaned)
    columns, rows = data["columns"], data["rows"]
    # the guard caps the rows at 500, so a capped query never reads a 501st row: it may have had more
    truncated = bool(data["truncated"]) or (len(rows) >= warehouse.MAX_ROWS and _was_capped(sql))
    return {
        "sql": cleaned,
        "columns": [str(c) for c in columns],
        "headers": agent.table_headers(columns, rows),  # [{name, num}]: num = a column of numbers (right-align)
        "rows": [[json_value(v) for v in row] for row in rows],
        "row_count": len(rows),
        "truncated": truncated,
        "max_rows": warehouse.MAX_ROWS,
        "secs": secs,
    }


def _was_capped(sql):
    """True when the typed SQL had no LIMIT or one above 500 (so the guard put LIMIT 500 on it)."""
    try:
        tree = sqlglot.parse_one(strip_fences(sql), read="mysql")
    except Exception:
        return True
    limit = tree.args.get("limit") if tree is not None else None
    count = limit.args.get("expression") if limit is not None else None
    if not (isinstance(count, exp.Literal) and not count.is_string and count.this.isdigit()):
        return True
    return int(count.this) > warehouse.MAX_ROWS


def _mysql_words(message):
    """MySQL's error in plain words: '(1054) Unknown column ...' -> 'MySQL could not run the query: (1054) ...'."""
    if message.startswith(f"({TIME_LIMIT_CODE})"):
        return f"The query took longer than {warehouse.TIME_LIMIT_MS // 1000} seconds and was stopped - " \
               "add a WHERE filter or read fewer rows."
    return f"MySQL could not run the query: {message}"


def json_value(value):
    """One value of a row as plain JSON: whole numbers and floats as numbers, Decimals as text (every digit
    kept), dates and times as ISO text, bytes as text, anything else as text; NULL stays null."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, decimal.Decimal):
        return str(value) if value.is_finite() else None
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):  # a MySQL TIME column
        return str(value)
    return _text(value)


def _text(value):
    """bytes (some information_schema columns come as bytes) or anything else as text."""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", "replace")
    return str(value)


# ------------------------------------------------------------------ saved queries (only text)
def saved_fields(data, creating):
    """The fields of a saved query posted as JSON ({name, sql, shared}), checked as text only: the SQL is never
    run and never checked by the guard here - that happens only when someone presses Run. creating = a new query
    (name and SQL needed); else only the fields that were sent. -> {name?, sql?, shared?} or SqlProblem(400).
    The name is trimmed (spaces tidied); the SQL is kept as typed."""
    fields = {}
    if creating or "name" in data:
        name = data.get("name")
        if not isinstance(name, str):
            raise SqlProblem(400, "Give the query a name.")
        name = " ".join(name.split())
        if not name:
            raise SqlProblem(400, "Give the query a name.")
        if len(name) > SavedQuery.MAX_NAME_CHARS:
            raise SqlProblem(400, f"Please keep the name to {SavedQuery.MAX_NAME_CHARS} characters or fewer.")
        fields["name"] = name
    if creating or "sql" in data:
        sql = data.get("sql")
        if not isinstance(sql, str) or not sql.strip():
            raise SqlProblem(400, "Type the SQL to save first.")
        if len(sql) > MAX_SQL_CHARS:
            raise SqlProblem(400, f"Please keep the SQL under {MAX_SQL_CHARS:,} characters.")
        fields["sql"] = sql
    if "shared" in data:
        if not isinstance(data["shared"], bool):
            raise SqlProblem(400, "shared must be true or false.")
        fields["shared"] = data["shared"]
    elif creating:
        fields["shared"] = False
    return fields
