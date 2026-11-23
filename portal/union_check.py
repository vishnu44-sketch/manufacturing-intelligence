"""A UNION whose last part's ORDER BY / LIMIT is read by MySQL as the ORDER BY / LIMIT of the WHOLE union.

20-Nov (local model): "Which month had our highest sales ever, and which had the lowest?" was written as
    (SELECT ... ORDER BY net_sales_inr DESC LIMIT 1) UNION ALL SELECT ... ORDER BY net_sales_inr ASC LIMIT 1
In MySQL the last ORDER BY / LIMIT, outside parentheses, sorts and cuts the whole union: one row came back (the
highest month sorted ASC = the smaller of the two) and the answer called the lowest month the highest.
lc/graph.py check_sql sends such a query back (every try but the last) with UNION_PROBLEM.

Flagged only when BOTH are true (so a union sorted / limited as a whole is never sent back):
- the last part is not in parentheses and the union has a LIMIT (not the guard's LIMIT 500; an ORDER BY alone only
  sorts the whole union, no row is lost);
- an earlier part has its own ORDER BY or LIMIT (in parentheses) - each part was meant to be cut on its own.
SQL that sqlglot cannot read is never flagged.
"""
import sqlglot
from sqlglot import exp

from .rag.sql_guard import MAX_ROWS

UNION_PROBLEM = ("the query is a UNION whose last part is not in parentheses, so MySQL applies its ORDER BY / LIMIT "
                 "to the WHOLE union, not to that part (only {rows} of all the parts came back). Wrap each part in "
                 "parentheses so its ORDER BY / LIMIT applies to that part only: (SELECT ... ORDER BY ... LIMIT 1) "
                 "UNION ALL (SELECT ... ORDER BY ... LIMIT 1).")
_SET_OPERATION = getattr(exp, "SetOperation", exp.Union)  # UNION / INTERSECT / EXCEPT


def _parts(node):
    """The parts of a chain of unions, left to right: (a) UNION (b) UNION c -> [a, b, c]."""
    if isinstance(node, _SET_OPERATION):
        return _parts(node.this) + _parts(node.expression)
    return [node]


def _own_cut(part):
    """True when one part has its own ORDER BY or LIMIT ((SELECT ... LIMIT 1) or a bare SELECT ... LIMIT 1)."""
    while isinstance(part, (exp.Subquery, exp.Paren)):
        part = part.this
    return isinstance(part, exp.Select) and bool(part.args.get("order") or part.args.get("limit"))


def _union_cut(node):
    """The whole union's LIMIT as text for the problem ('1 row(s)'); '' when it has none or only the guard's LIMIT
    500 (an ORDER BY alone only sorts the whole union - no row is lost)."""
    limit = node.args.get("limit")
    count = limit.args.get("expression") if limit is not None else None
    if count is None or (isinstance(count, exp.Literal) and count.this == str(MAX_ROWS)):
        return ""
    return f"{count.sql(dialect='mysql')} row(s)"


def last_part_cuts_the_union(sql):
    """The text for UNION_PROBLEM's {rows} when the SQL has such a union; else '' (also for SQL that cannot be read)."""
    if "union" not in (sql or "").lower():
        return ""
    try:
        tree = sqlglot.parse_one(sql, read="mysql")
    except (sqlglot.errors.ParseError, sqlglot.errors.TokenError):
        return ""
    if tree is None:
        return ""
    for node in tree.find_all(_SET_OPERATION):
        if isinstance(node.parent, _SET_OPERATION) and node.parent.this is node:
            continue  # an inner link of a chain: its whole chain is checked once, from the top
        parts = _parts(node)
        if isinstance(parts[-1], (exp.Subquery, exp.Paren)):
            continue  # the last part is in parentheses: the trailing ORDER BY / LIMIT is meant for the whole union
        rows = _union_cut(node)
        if rows and any(_own_cut(part) for part in parts[:-1]):
            return rows
    return ""
