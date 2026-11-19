"""Our own check of a data answer's TEXT against the rows and the facts the app already gave the AI - once, right
after the answer is written (agent.explain). No AI call, no tokens - unless it finds a problem: then the answer is
sent back to the AI ONCE with the exact correction (the AI rewrites it); a second answer that still fails is kept
and logged - never a loop.

18-Nov: "What is the sales forecast for August 2027?" got "there was no sales forecast for August 2027" - the SQL
read only the PRODUCT level (0 rows) although the TOTAL forecast for Aug 2027 is in ml_sales_forecast (53.7 Cr).
Earlier answers also stated amounts that were not in the data.

What it flags:
1. a "no data / no forecast / not available" claim about a month (e.g. "no forecast for Aug 2027") while that month
   IS in the rows, or - for a query of ml_sales_forecast - in the forecast table's months (TOTAL; PRODUCT when the
   question or the SQL is about products); and a "the query returned no rows / no data was found" claim while the
   result has real rows;
2. big amounts (1,000 or more) that match NO value of the rows, of the request the AI was sent (the facts the app
   worked out, the question, the SQL ...) and of the simple sums an answer makes from the rows (a column's total
   or average, a run of months added up, two values added / taken away, quantity x price in one row) - roundings
   such as "53.5 Cr", "18.9 lakh", "INR 534,887,655.19" or "about 54 Cr" all count as found.
What it never flags: percentages, counts and amounts under 1,000, dates, years, FY labels, "no actual sales yet"
(actual sales of a forecast month), claims with "beyond / after / only / other ..." ("no forecast beyond Oct 2027"),
a month with no row ("no export sales in Sep 2026" - the missing-months note asks for that), a claim about a name
that has no row in that month ("Meridian had no sales in Sep 2026" while other customers did).
Only the answer of a data question is checked (agent.explain) - never a general answer, a documents answer
(also not the 'both' answer that has PDF pieces), a memory reply or an answer-check reply.
"""
import bisect
import decimal
import logging
import re

from . import answer_check
from .rag import agent, warehouse
from .rag.sql_guard import check_sql

log = logging.getLogger(__name__)

MIN_AMOUNT = 1000        # only amounts of 1,000 or more are checked (counts, days and scores are smaller)
TOLERANCE = 0.005        # an amount within 0.5 % of a known value counts as found (the AI's own rounding)
MAX_DERIVED_ROWS = 60    # sums of runs of rows and of two rows are made for up to this many rows
MOST_ROWS_SHOWN = 3      # rows of a month quoted in the correction

_MONTHS = {"jan": "Jan", "feb": "Feb", "mar": "Mar", "apr": "Apr", "may": "May", "jun": "Jun", "jul": "Jul",
           "aug": "Aug", "sep": "Sep", "oct": "Oct", "nov": "Nov", "dec": "Dec"}
_MONTH_WORD = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
               r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
MONTH_YEAR = re.compile(rf"\b({_MONTH_WORD})[\s-]+(20\d\d)\b", re.I)
# a date (21-Jul-2027, 2027-07-21, 21/07/2027) is not a month the answer talks about: taken out first
_DATE = re.compile(rf"\b\d{{1,2}}[-/ ]{_MONTH_WORD}[-/ ,]+\d{{2,4}}\b|\b\d{{4}}-\d{{1,2}}-\d{{1,2}}\b|"
                   r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", re.I)
# "no forecast", "no sales forecast records", "not available", "does not have" ...
_ABSENT = re.compile(r"\bno\s+(?:[\w-]+\s+){0,3}?(?:forecasts?|data|sales|records?|rows?|figures?|values?|"
                     r"predictions?|results?|numbers?|information|entries|estimates?)\b|"
                     r"\bnot\s+(?:yet\s+)?(?:available|forecast(?:ed)?|predicted|included|covered|present|"
                     r"in\s+the\s+(?:data|forecast|table|result|rows))\b|"
                     r"\b(?:does|do|did)\s*(?:not|n't)\s+(?:have|include|contain|cover|show)\b|"
                     r"\b(?:is|are|was|were)\s*(?:not|n't)\s+(?:any|available)\b|\bunavailable\b|\bmissing\b", re.I)
# a claim with these words is about something else: actual sales of a forecast month, the months beyond the
# forecast, a comparison ... - never flagged
_NOT_A_CLAIM = re.compile(r"\bactual|\byet\b|\bso\s+far\b|\brecorded\b|\bthan\b|\bbeyond\b|\bafter\b|\bbefore\b|"
                          r"\blater\b|\bearlier\b|\buntil\b|\btill\b|\bup\s+to\b|\bonly\b|\boutside\b|\bother\b|"
                          r"\bexcept\b|\bsince\b|\bonwards?\b|\bprior\b|\bgrowth\b|\bchange\b", re.I)
# "the query returned no rows", "no data was found", "there is no data for this question" - about the whole result
_NO_RESULT = re.compile(
    r"\b(?:the\s+)?(?:query|data|result|table|search)\s+(?:returned|returns|has|have|had|shows?|showed|contains?|"
    r"found|gave)\s+no\s+(?:matching\s+)?(?:data|rows|records|results)\b|"
    r"\bno\s+(?:matching\s+)?(?:data|rows|records|results)\s+(?:was|were|is|are)\s+(?:found|returned|available)\b|"
    r"\bthere\s+(?:is|are|was|were)\s+no\s+(?:matching\s+)?(?:data|rows|records|results)\s*(?:available\s*)?"
    r"(?:for\s+(?:this|that|your|the)\s+(?:question|query|request|period)\s*)?$|"
    r"\b(?:could|did)\s*(?:not|n't)\s+find\s+any\s+(?:data|rows|records|results)\b", re.I)
_CLAUSE_BREAK = re.compile(r"[;:,()]|\s+(?:but|while|whereas|although|though|however)\s+", re.I)
_PERCENT = re.compile(r"-?\d[\d,]*(?:\.\d+)?\s*(?:%|percent\b|per\s+cent\b)", re.I)
_NUMBER_IN_TEXT = re.compile(r"\d[\d,]*(?:\.\d+)?")
_PRODUCT_FILTER = re.compile(r"\b(?:product_code|product_description|product_name|item_code)\s*(?:=|like\b|in\b)",
                             re.I)
_ABOUT_PRODUCTS = re.compile(r"\bproducts?\b|\bitems?\b|\bproduct[-\s]wise\b", re.I)
_FORECAST_TABLE = re.compile(r"\bml_sales_forecast\b", re.I)
# the forecast table's months per level with the TOTAL amounts (a few rows; read only when a claim needs it)
FORECAST_SQL = ("SELECT level, sales_month, MIN(period_start) AS period_start, SUM(forecast_inr) AS forecast_inr, "
                "SUM(low_inr) AS low_inr, SUM(high_inr) AS high_inr FROM ml_sales_forecast "
                "GROUP BY level, sales_month ORDER BY level DESC, MIN(period_start)")
_STOP_WORDS = {"the", "and", "for", "was", "were", "there", "this", "that", "with", "sales", "forecast", "month",
               "months", "data", "not", "any", "records", "record", "rows", "row", "available", "have", "has", "had",
               "does", "did", "missing", "values", "value", "figures", "results", "result", "information", "total"}

CORRECTION_END = "Rewrite the whole answer using only the rows and the facts{extra} - in the same plain style."


# ------------------------------------------------------------------ helpers
def month_label(word, year):
    """'August', '2027' -> 'Aug 2027' (the way the data names a sales month)."""
    return f"{_MONTHS[word[:3].lower()]} {year}"


def months_in(text):
    """The months with their year named in a text ('Aug 2027', 'August 2027') - dates left out - in order, once."""
    return list(dict.fromkeys(month_label(*m) for m in MONTH_YEAR.findall(_DATE.sub(" ", text or ""))))


def _clauses(text):
    """The answer's clauses: sentences cut at , ; : ( ) and 'but / while / however ...' - dates taken out first
    (their commas and months must not split or count)."""
    text = _DATE.sub(" ", text or "")
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        for clause in _CLAUSE_BREAK.split(sentence):
            clause = clause.strip(" .!?-")
            if clause:
                yield clause


def _number(value):
    return isinstance(value, (int, float, decimal.Decimal)) and not isinstance(value, bool)


def short_amount(value):
    """537123456.7 -> 'about 53.7 Cr'; 1890000 -> 'about 18.9 lakh'; '' below a lakh."""
    value = float(value)
    if abs(value) >= 10 ** 7:
        return f"about {value / 10 ** 7:,.1f} Cr"
    if abs(value) >= 10 ** 5:
        return f"about {value / 10 ** 5:,.1f} lakh"
    return ""


def _shown(value, column=""):
    text = agent.format_value(value, column)[0]
    short = short_amount(value) if _number(value) and abs(value) >= 10 ** 5 else ""
    return f"{text} ({short})" if short else text


def _row_text(columns, row):
    return ", ".join(f"{column} {_shown(value, column)}" for column, value in zip(columns, row) if value is not None)


def _cells_text(row):
    return " ".join(str(value).lower() for value in row if isinstance(value, str))


def _rows_of_month(rows, month):
    """The rows with a text cell that names this month ('Aug 2027', 'August 2027')."""
    return [row for row in rows if any(isinstance(v, str) and month in months_in(v) for v in row)]


def _qualified(clause, rows, month_rows):
    """True when the clause names something of the rows (a customer, a segment ...) that has no row in this month:
    "Meridian had no sales in Sep 2026" while other customers did - that claim can be right."""
    all_text = " ".join(_cells_text(row) for row in rows)
    month_text = " ".join(_cells_text(row) for row in month_rows)
    for word in set(re.findall(r"[a-z][a-z0-9&.-]{2,}", clause.lower())) - _STOP_WORDS:
        if MONTH_YEAR.fullmatch(word) or re.fullmatch(_MONTH_WORD, word):
            continue
        pattern = rf"\b{re.escape(word)}\b"
        if re.search(pattern, all_text) and not re.search(pattern, month_text):
            return True
    return False


# ------------------------------------------------------------------ check 1: "no data" claims
def _month_claims(answer):
    """[(clause, [months])]: the clauses that say a month has no data / no forecast."""
    claims = []
    for clause in _clauses(answer):
        months = months_in(clause)
        if months and _ABSENT.search(clause) and not _NOT_A_CLAIM.search(clause):
            claims.append((clause, months))
    return claims


def _forecast_months(result):
    """{'TOTAL': {month: (forecast, low, high)}, 'PRODUCT': {...}} of ml_sales_forecast - the table
    agent.forecast_months_note reads; {} on any error."""
    try:
        rows = warehouse.run_select(check_sql(FORECAST_SQL, warehouse.allowed_tables()))["rows"]
    except Exception:  # noqa: BLE001 - a check is extra: any failure leaves it out
        log.warning("Answer check: the forecast months were not read", exc_info=True)
        return {}
    levels = {}
    for level, month, _start, forecast, low, high in ((list(row) + [None] * 6)[:6] for row in rows):
        if month:
            levels.setdefault(str(level).upper(), {})[str(month)] = (forecast, low, high)
    return levels


def _gives_amounts(answer, amounts):
    """True when the answer states every one of these amounts (in any rounding)."""
    wanted = [float(a) for a in amounts if a is not None]
    if not wanted:
        return False
    numbers = answer_check.answer_numbers(_PERCENT.sub(" ", answer or ""))
    return all(any(_found(float(value), scale, max(0, -value.as_tuple().exponent), [amount])
                   for _written, value, scale in numbers) for amount in wanted)


def _forecast_span(months):
    names = list(months)
    if not names:
        return ""
    return names[0] if len(names) == 1 else f"{names[0]} to {names[-1]}"


def no_data_problems(result, answer):
    """The correction sentences of check 1 ([] when nothing is wrong) and the numbers they give the AI."""
    problems, facts = [], []
    real_rows = not agent.found_nothing(result.rows)
    if real_rows:
        for clause in _clauses(answer):
            if _NO_RESULT.search(clause) and not months_in(clause) and not _NOT_A_CLAIM.search(clause):
                problems.append(f'Your answer says "{clause}", but the query returned {len(result.rows):,} '
                                "row(s) with data.")
                break
    forecast_sql = bool(_FORECAST_TABLE.search(result.sql or ""))
    levels = None
    asked = f"{result.text} {result.understood_as or ''}"
    about_products = bool(_PRODUCT_FILTER.search(result.sql or "") or _ABOUT_PRODUCTS.search(asked))
    for clause, months in _month_claims(answer):
        month_rows = {month: _rows_of_month(result.rows, month) for month in months} if real_rows else {}
        if real_rows and all(month_rows[m] for m in months):
            if any(_qualified(clause, result.rows, month_rows[m]) for m in months):
                continue
            shown = "; ".join(_row_text(result.columns, row) for m in months for row in month_rows[m][:MOST_ROWS_SHOWN])
            problems.append(f'Your answer says "{clause}", but the rows show: {shown}.')
            continue
        if not forecast_sql:
            continue
        if levels is None:
            levels = _forecast_months(result)
        total, products = levels.get("TOTAL", {}), levels.get("PRODUCT", {})
        if about_products:
            if not all(m in products for m in months):
                continue
            problems.append(f'Your answer says "{clause}", but ml_sales_forecast has a product forecast for '
                            f"{', '.join(months)} (products are forecast for {_forecast_span(products)}).")
            continue
        if not all(m in total for m in months):
            continue
        if _gives_amounts(answer, [total[m][0] for m in months]):
            continue  # "no product forecast for Aug 2027; the total is about 53.7 Cr" - the total is told
        parts = []
        for month in months:
            forecast, low, high = total[month]
            part = f"TOTAL {month} forecast {_shown(forecast)}" if forecast is not None else f"TOTAL {month}"
            if low is not None and high is not None:
                part += f", range {_shown(low)} to {_shown(high)}"
            parts.append(part)
            facts.append(" ".join(str(v) for v in (forecast, low, high) if v is not None))
        note = f" Products are forecast only for {_forecast_span(products)}." if products else ""
        problems.append(f'Your answer says "{clause}", but the forecast table ml_sales_forecast has the total sales '
                        f"forecast (all products together) for {', '.join(months)}: {'; '.join(parts)}.{note}")
    return list(dict.fromkeys(problems)), " ".join(facts)


# ------------------------------------------------------------------ check 2: amounts not in the data
def _numbers_in(text):
    found = set()
    for written in _NUMBER_IN_TEXT.findall(text or ""):
        try:
            found.add(abs(float(written.replace(",", ""))))
        except ValueError:
            continue
    return found


def known_values(result, sent_text=""):
    """Every amount an answer may give: the rows' values (also numbers inside text cells), the numbers of the
    request the AI was sent (the facts, the question, the SQL ...), the row count, and the simple sums an answer
    makes from the rows - a sorted list of floats."""
    values = {float(v) for v in answer_check._row_values(result.rows)} | _numbers_in(sent_text)
    values |= {float(len(result.rows))}
    rows = result.rows
    columns = [i for i in range(len(result.columns))
               if any(_number(row[i]) for row in rows) and all(_number(row[i]) or row[i] is None for row in rows)]
    for i in columns:
        column = [float(row[i]) for row in rows if row[i] is not None]
        if not column:
            continue
        values.update((abs(sum(column)), abs(sum(column) / len(column))))
        if len(column) <= MAX_DERIVED_ROWS:
            for start in range(len(column)):  # runs of rows added up (a quarter, the next 6 months ...), averaged
                running = 0.0
                for end in range(start, len(column)):
                    running += column[end]
                    values.update((abs(running), abs(running / (end - start + 1))))
                for other in column[start + 1:]:  # two rows taken away (how much more) or added
                    values.update((abs(column[start] - other), abs(column[start] + other)))
    for row in rows[:500]:  # one row: high - low, sales - target, quantity x price ...
        cells = [float(row[i]) for i in columns if row[i] is not None]
        for n, first in enumerate(cells):
            for second in cells[n + 1:]:
                values.update((abs(first - second), abs(first + second), abs(first * second)))
    return sorted(values)


def _found(value, scale, places, known):
    """True when a known value, shown in the answer's unit and decimals (rounded or cut), or within 0.5 %, is the
    answer's number."""
    step = 10.0 ** -places
    target = value * scale
    low = min((value - step / 2) * scale, target * (1 - TOLERANCE))
    high = max((value + step) * scale, target * (1 + TOLERANCE))
    at = bisect.bisect_left(known, low)
    return at < len(known) and known[at] <= high


def unknown_amounts(result, answer, sent_text=""):
    """The amounts of 1,000 or more in the answer that match nothing of the rows, the request or their simple
    sums - as written in the answer, each once. [] when every amount is found."""
    known = None
    missing = []
    for written, value, scale in answer_check.answer_numbers(_PERCENT.sub(" ", answer or "")):
        if float(value) * scale < MIN_AMOUNT:
            continue
        if known is None:
            known = known_values(result, sent_text)
        places = max(0, -value.as_tuple().exponent)
        if not _found(float(value), scale, places, known):
            missing.append(written)
    return list(dict.fromkeys(missing))


# ------------------------------------------------------------------ the check and the correction
def problems(result, answer, sent_text="", extra_facts=""):
    """(the correction message for the AI, the numbers it adds) - ('', '') when the answer is fine.
    The check is extra: any failure of its own leaves the answer as it is."""
    try:
        return _problems(result, answer, sent_text, extra_facts)
    except Exception:  # noqa: BLE001
        log.warning("Answer check failed - the answer is kept as it is", exc_info=True)
        return "", ""


def _problems(result, answer, sent_text, extra_facts):
    found, facts = no_data_problems(result, answer)
    missing = unknown_amounts(result, answer, f"{sent_text} {facts} {extra_facts}")
    if missing:
        one = len(missing) == 1
        found.append(f"{'This amount' if one else 'These amounts'} in your answer {'is' if one else 'are'} not in the "
                     f"rows or the facts: {', '.join(missing)}. Give only amounts from the rows and the facts "
                     "(rounded is fine, e.g. about 53.7 Cr).")
    if not found:
        return "", ""
    extra = " and the numbers in this message" if facts else ""
    return " ".join(found) + " " + CORRECTION_END.format(extra=extra), facts


def applies(result, pdf_hits=()):
    """Only the answer of a data question is checked: not when it also answers from the documents (PDF pieces)."""
    return not pdf_hits and result.status == "ok"
