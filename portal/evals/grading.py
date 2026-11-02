"""Grade one saved answer of the golden set: PASS, PARTIAL or FAIL, with the reasons.

The truth always comes from the question's own SQL, run now on ai_gold (never from the AI being tested):
  must      values that MUST appear in the answer (wrong / missing -> FAIL)
  should    values that should appear too, e.g. the report date (missing -> PARTIAL)
  must_have / must_not   phrases (case-insensitive); by default no "profit" and no vague data-date sentence
  expect    the status the answer must have (default 'ok'; e.g. 'nodata', 'refused')
  format    dates like 20-Mar-2027 and FY 2025-26 (2027-03-20 or "FY 2526" -> PARTIAL)
"""
import re
from datetime import date, datetime
from decimal import Decimal

from ..rag import sql_guard, warehouse

DEFAULT_MUST_NOT = ["profit", "earliest date", "first invoice in this period", "based on data from"]
VERDICTS = ("PASS", "PARTIAL", "FAIL")


def truth_values(sql):
    """Every value of every row the truth SQL returns (through the same guard as the AI's SQL)."""
    if not sql:
        return []
    result = warehouse.run_select(sql_guard.check_sql(sql, warehouse.allowed_tables()))
    return [v for row in result["rows"] for v in row if v is not None]


def spellings(value):
    """How a value may be written in a correct answer."""
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        day, mon, month = str(value.day), value.strftime("%b"), value.strftime("%B")
        return [f"{d}{sep}{m}{sep}{value.year}" for d in (day, f"{value.day:02d}") for m in (mon, month)
                for sep in ("-", " ")]
    if isinstance(value, Decimal) and value.as_tuple().exponent < 0:   # e.g. 33851075.00 -> 33,851,075.00
        return [f"{value:,.{-value.as_tuple().exponent}f}"]
    if isinstance(value, (int, Decimal)):
        return [f"{int(value):,}"]
    return [str(value)]


def found(value, answer):
    """True when the answer writes the value (a number only as a whole number, not inside a bigger one)."""
    for spelling in spellings(value):
        if isinstance(value, (int, Decimal, float)):
            if re.search(r"(?<![\d.,])" + re.escape(spelling) + r"(?!\d|[.,]\d|-[A-Za-z])", answer):
                return True
        elif spelling.lower() in answer.lower():
            return True
    return False


def grade(item, saved):
    """(verdict, [reasons]) for one golden item and its saved answer {status, answer, ...}."""
    answer = " ".join((saved.get("answer") or "").replace(" ", " ").split())
    expected = item.get("expect", "ok")
    if saved.get("status") != expected:
        return "FAIL", [f"status {saved.get('status')} (expected {expected})"]
    missing = [f"missing {spellings(v)[0]}" for v in truth_values(item.get("must")) if not found(v, answer)]
    if missing:
        return "FAIL", missing
    partial = [f"should say {spellings(v)[0]}" for v in truth_values(item.get("should")) if not found(v, answer)]
    partial += [f"should mention '{p}'" for p in item.get("must_have", []) if p not in answer.lower()]
    partial += [f"says '{p}'" for p in DEFAULT_MUST_NOT + item.get("must_not", [])
                if p not in item.get("allow", []) and p in answer.lower()]
    if re.search(r"\b20\d\d-\d\d-\d\d\b", answer):
        partial.append("date written as yyyy-mm-dd")
    if re.search(r"\bFY ?\d{4}\b(?!-)", answer):   # "FY 2526" - not "FY 2025-26"
        partial.append("FY written as 4 digits")
    return ("PARTIAL", partial) if partial else ("PASS", [])


def grade_results(items, results):
    """Grade every item that has a saved answer -> ([(item, saved, verdict, reasons)], {verdict: count})."""
    graded, counts = [], dict.fromkeys(VERDICTS, 0)
    for item in items:
        saved = results.get(item["id"])
        if saved:
            verdict, why = grade(item, saved)
            counts[verdict] += 1
            graded.append((item, saved, verdict, why))
    return graded, counts
