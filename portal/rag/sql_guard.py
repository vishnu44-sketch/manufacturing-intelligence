"""The SQL guard: decides whether a SQL written by the AI may run on ai_gold.

check_sql(sql) returns the cleaned SQL, or raises GuardError with the reason in plain English.

What may run - and nothing else:
- exactly ONE statement: SELECT, WITH ... SELECT, or SELECTs joined by UNION / INTERSECT / EXCEPT;
- only ai_gold tables (names read from information_schema) and the query's own CTE names;
  no other database in front of a table (information_schema, mysql, sys, nop_gold ...);
- no SELECT ... INTO (files or variables), no FOR UPDATE / LOCK IN SHARE MODE,
  no MySQL variables (@x, @@x), no optimizer hints or special /*! */ comments,
  no dangerous functions (SLEEP, BENCHMARK, LOAD_FILE, GET_LOCK ...);
- at most 500 rows: LIMIT 500 is added when there is no LIMIT or a bigger one.

The SQL is parsed with sqlglot (MySQL dialect) and WRITTEN AGAIN from the parsed tree with every
comment left out, so the text that runs is exactly the text that was checked.
(The read-only MySQL user and the READ ONLY session are a second safety net - see warehouse.py.)
"""
import logging
import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

MAX_ROWS = 500
ALLOWED_DATABASE = "ai_gold"

# functions that wait, read files, take locks or touch replication - never allowed
BLOCKED_FUNCTIONS = {
    "SLEEP", "BENCHMARK", "LOAD_FILE", "GET_LOCK", "RELEASE_LOCK", "RELEASE_ALL_LOCKS",
    "IS_FREE_LOCK", "IS_USED_LOCK", "MASTER_POS_WAIT", "SOURCE_POS_WAIT",
    "WAIT_FOR_EXECUTED_GTID_SET", "WAIT_UNTIL_SQL_THREAD_AFTER_GTIDS", "SYS_EXEC", "SYS_EVAL",
}

# statement kinds that must never appear anywhere in the query
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter,
    exp.TruncateTable, exp.Command, exp.Set, exp.LoadData, exp.Grant, exp.Revoke, exp.Use,
    exp.Transaction, exp.Commit, exp.Rollback, exp.Copy, exp.Kill, exp.Pragma, exp.Describe,
    exp.Show, exp.Analyze, exp.Cache, exp.Uncache, exp.Refresh,
)

# sqlglot prints a warning when it meets a statement it does not know; the guard refuses those anyway
logging.getLogger("sqlglot").setLevel(logging.ERROR)


class GuardError(ValueError):
    """The SQL may not run. str(error) says why, in plain English."""


def strip_fences(text):
    """The SQL inside a ```sql ... ``` block (the AI often adds one); else the text itself."""
    text = (text or "").strip()
    match = re.search(r"```[ \t]*(?:sql|mysql)?[ \t]*\n?(.*?)```", text, flags=re.S | re.I)
    if match:
        return match.group(1).strip()
    # an opening fence without a closing one (e.g. the answer was cut off)
    return re.sub(r"^```[ \t]*(?:sql|mysql)?", "", text, flags=re.I).strip()


def check_sql(sql, allowed_tables=None):
    """Return the cleaned SQL that may run, or raise GuardError.

    allowed_tables: the table names that may be read (lower case). When not given they are
    read from ai_gold's information_schema (warehouse.allowed_tables()).
    """
    text = strip_fences(sql)
    if not text:
        raise GuardError("No SQL was given.")

    # 1. tricks hidden in special comments: MySQL RUNS the code in /*! ... */, and /*+ ... */
    #    hints could change the time limit. Plain comments are simply dropped (step 5).
    if "/*!" in text or "/*+" in text:
        raise GuardError("Special MySQL comments (/*! ... */ or /*+ ... */) are not allowed.")
    if re.search(r"\bINTO\s+(OUTFILE|DUMPFILE)\b", text, flags=re.I):
        raise GuardError("Writing to a file (INTO OUTFILE / DUMPFILE) is not allowed.")

    # 2. parse - exactly one statement
    try:
        statements = [s for s in sqlglot.parse(text, read="mysql") if s is not None]
    except (ParseError, TokenError) as exc:
        first_line = str(exc).splitlines()[0] if str(exc) else "syntax error"
        raise GuardError(f"The SQL could not be read (syntax error): {first_line}") from None
    if not statements:
        raise GuardError("No SQL was given.")
    if len(statements) > 1:
        raise GuardError("Only one SQL statement is allowed (found more than one).")
    tree = statements[0]

    # 3. it must be a query: SELECT / WITH ... SELECT / UNION
    if not isinstance(tree, (exp.Select, exp.SetOperation)):
        if isinstance(tree, FORBIDDEN_NODES):
            raise GuardError(f"Only SELECT queries are allowed - {_statement_name(tree)} is not.")
        raise GuardError("This is not a SELECT query - only SELECT queries are allowed.")

    # 4. look at every part of the query
    if allowed_tables is None:
        from .warehouse import allowed_tables as read_allowed_tables  # needs MySQL
        allowed_tables = read_allowed_tables()
    allowed = {name.lower() for name in allowed_tables}
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for node in tree.walk():
        _check_node(node, allowed, cte_names)

    # 5. at most MAX_ROWS rows
    tree = _cap_limit(tree)

    # 6. write the SQL again from the checked tree, without any comment
    cleaned = tree.sql(dialect="mysql", comments=False, pretty=True)
    found = re.search(r"\b(" + "|".join(BLOCKED_FUNCTIONS) + r")\s*\(", cleaned, flags=re.I)
    if found:  # second check on the final text (e.g. a function sqlglot did not recognise)
        raise GuardError(f"The function {found.group(1).upper()}() is not allowed.")
    return cleaned


def _check_node(node, allowed, cte_names):
    """Raise GuardError if this one part of the parsed query is not allowed."""
    if isinstance(node, FORBIDDEN_NODES):
        raise GuardError(f"Only SELECT queries are allowed - {_statement_name(node)} is not.")
    if isinstance(node, exp.Into):
        raise GuardError("SELECT ... INTO (a file or a variable) is not allowed.")
    if isinstance(node, exp.Lock):
        raise GuardError("Locking reads (FOR UPDATE / LOCK IN SHARE MODE) are not allowed.")
    if isinstance(node, exp.Hint):
        raise GuardError("Optimizer hints (/*+ ... */) are not allowed.")
    if isinstance(node, (exp.Parameter, exp.SessionParameter, exp.Placeholder)):
        raise GuardError("MySQL variables (@name, @@name) are not allowed.")
    if isinstance(node, exp.Func):
        name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).upper()
        if name in BLOCKED_FUNCTIONS:
            raise GuardError(f"The function {name}() is not allowed.")
    if isinstance(node, exp.Table):
        _check_table(node, allowed, cte_names)


def _check_table(table, allowed, cte_names):
    """Only ai_gold tables (or the query's own CTE names) may be read."""
    name = (table.name or "").lower()
    database = (table.db or "").lower()
    if table.catalog:
        raise GuardError(f"Only the {ALLOWED_DATABASE} database may be read.")
    if database and database != ALLOWED_DATABASE:
        raise GuardError(f"Only the {ALLOWED_DATABASE} database may be read - not '{table.db}'.")
    if not name:
        raise GuardError("Table functions (such as JSON_TABLE) are not allowed - read ai_gold tables.")
    if not database and name in cte_names:
        return  # a WITH name defined inside this query
    if name not in allowed:
        raise GuardError(f"Unknown table '{table.name}' - only {ALLOWED_DATABASE} tables may be used.")


def _cap_limit(tree):
    """Add LIMIT 500 when there is no LIMIT, or lower a LIMIT above 500 to 500."""
    limit = tree.args.get("limit")
    if limit is None:
        return tree.limit(MAX_ROWS)
    count = limit.args.get("expression")
    if not (isinstance(count, exp.Literal) and not count.is_string and count.this.isdigit()):
        raise GuardError("LIMIT must be a plain whole number.")
    if int(count.this) > MAX_ROWS:
        limit.set("expression", exp.Literal.number(MAX_ROWS))
    return tree


def _statement_name(node):
    """A readable name for a statement, e.g. 'INSERT', 'DROP', 'CALL'."""
    if isinstance(node, exp.Command):
        return str(node.this or "this command").upper()
    if isinstance(node, exp.TruncateTable):
        return "TRUNCATE"
    return node.key.upper()
