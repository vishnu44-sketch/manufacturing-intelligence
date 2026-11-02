"""Read-only access to the NOP data: the MySQL database ai_gold.

The app connects ONLY as the read-only user from .env (AI_DB_USER / AI_DB_PASSWORD,
SELECT on ai_gold only) - never as the admin user the loader uses.
Every query gets its own connection:
    SET SESSION TRANSACTION READ ONLY      -> MySQL itself refuses any change
    SET SESSION MAX_EXECUTION_TIME=30000   -> a SELECT is stopped after 30 seconds
then the query runs, at most 500 rows are kept, and the connection is closed.

run_select(sql)   {columns, rows, truncated} of one SELECT (the SQL guard checks it first)
schema()          {table: [columns]} of ai_gold, read once from information_schema
allowed_tables()  the ai_gold table names (the SQL guard allows only these)
schema_text()     the same as short text lines 'table: col1, col2, ...' for the AI prompt
"""
import os
from functools import lru_cache
from pathlib import Path

import pymysql
from dotenv import load_dotenv

REPO_DIR = Path(__file__).resolve().parents[2]  # the folder that holds manage.py
load_dotenv(REPO_DIR / ".env")  # does nothing if Django already read .env

MAX_ROWS = 500           # never more rows than this from one query
TIME_LIMIT_MS = 30_000   # MySQL stops a SELECT after 30 seconds


class WarehouseUnavailable(Exception):
    """MySQL could not be reached or the login failed (asking the AI again will not help)."""


class QueryError(Exception):
    """MySQL refused or stopped the query; the message is MySQL's own words."""


def database_name():
    """The NOP data database (from .env, normally 'ai_gold')."""
    return os.getenv("AI_GOLD_DATABASE", "").strip() or "ai_gold"


def connect():
    """A new connection as the read-only user. The password is never printed."""
    user = os.getenv("AI_DB_USER", "").strip()
    if not user:
        raise WarehouseUnavailable("AI_DB_USER is missing in .env (the read-only MySQL user).")
    try:
        return pymysql.connect(
            host=os.getenv("MYSQL_HOST", "localhost").strip() or "localhost",
            port=int(os.getenv("MYSQL_PORT", "3306") or 3306),
            user=user,
            password=os.getenv("AI_DB_PASSWORD", ""),
            database=database_name(),
            charset="utf8mb4",
            connect_timeout=10,
            read_timeout=60,   # a little longer than the 30 s MySQL limit
            autocommit=True,
        )
    except pymysql.err.MySQLError as exc:
        # keep only MySQL's message (code + text), never the connection settings
        raise WarehouseUnavailable(f"Cannot connect to MySQL as {user}: {_mysql_message(exc)}") from None


def run_select(sql, max_rows=MAX_ROWS):
    """Run ONE checked SELECT in a read-only, time-limited session.

    Returns {"columns": [...], "rows": [[...], ...], "truncated": True if more than max_rows}.
    Raises QueryError with MySQL's message when the query fails.
    """
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
            cur.execute(f"SET SESSION MAX_EXECUTION_TIME = {int(TIME_LIMIT_MS)}")
            try:
                cur.execute(sql)  # no parameters, so pymysql leaves '%' in the SQL alone
            except pymysql.err.MySQLError as exc:
                raise QueryError(_mysql_message(exc)) from None
            columns = [d[0] for d in (cur.description or [])]
            rows = cur.fetchmany(max_rows + 1)  # one extra row tells us there were more
    finally:
        conn.close()
    return {
        "columns": columns,
        "rows": [list(r) for r in rows[:max_rows]],
        "truncated": len(rows) > max_rows,
    }


@lru_cache(maxsize=1)
def schema():
    """{table: [column, ...]} of every ai_gold table, in column order.
    Read once from information_schema, then kept for the life of the process."""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = %s ORDER BY table_name, ordinal_position",
                (database_name(),),
            )
            tables = {}
            for table, column in cur.fetchall():
                tables.setdefault(table, []).append(column)
    finally:
        conn.close()
    if not tables:
        raise WarehouseUnavailable(f"No tables found in {database_name()} for this MySQL user.")
    return tables


def allowed_tables():
    """The ai_gold table names in lower case - the only tables the AI may read."""
    return {name.lower() for name in schema()}


def schema_text():
    """Compact schema for the AI prompt: one line per table, 'table: col1, col2, ...'."""
    return "\n".join(f"{table}: {', '.join(columns)}" for table, columns in schema().items())


def _mysql_message(exc):
    """'(1054) Unknown column ...' from a pymysql error."""
    if len(exc.args) >= 2:
        return f"({exc.args[0]}) {exc.args[1]}"
    return str(exc)
