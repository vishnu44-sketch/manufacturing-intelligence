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
3. (19-Nov) a percent that is 100 x a value of a *_pct column of the rows ("support 48.16 %" for support_pct 0.4816):
   a *_pct column is already a percent, so 0.4816 is 0.48 %. The rewritten answer is checked for it WITHOUT the
   correction's text (the correction itself quotes the wrong "48.16 %", which would make a still-wrong rewrite pass);
4. (19-Nov) a fact_stock_ledger answer that never names the stock report date of its rows (a report_date column):
   "most stock right now" listed quantities without saying they are the stock report of 31-Oct-2026;
5. (20-Nov) a list cut at the 500-row limit (result.truncated) told as the total ("there were 500 active customers",
   "all 500") - the rewrite says the list has more than 500 rows;
6. (20-Nov) a month of the rows that ends after the invoice data's last date ("Nov 2026" with data up to 31-Oct-2026)
   while the answer neither calls it incomplete nor names that last date;
7. (20-Nov) a forecast amount (a forecast column of an ml_sales_forecast query) written in full rupees and never in
   Cr ("INR 534,887,655.19") - the answer rule says forecast amounts are written rounded in Cr;
8. (20-Nov) a list of two or more products with a code column (product_code ...) whose answer names products of the
   rows but gives none of their codes;
9. (20-Nov) an amount called a total / "in all" that is one row's value of a money / quantity column whose values
   differ between the rows ("a total stock value of INR 466,320.00" = the first of 29 items) - the correction gives
   the real total, worked out by our code.
What it never flags: other percentages, counts and amounts under 1,000, dates, years, FY labels, "no actual sales yet"
(actual sales of a forecast month), claims with "beyond / after / only / other ..." ("no forecast beyond Oct 2027"),
a month with no row ("no export sales in Sep 2026" - the missing-months note asks for that), a claim about a name
that has no row in that month ("Meridian had no sales in Sep 2026" while other customers did).
Only the answer of a data question is checked (agent.explain) - never a general answer, a documents answer
(also not the 'both' answer that has PDF pieces), a memory reply or an answer-check reply.
"""
import bisect
import datetime
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


# ------------------------------------------------------------------ check 3: a percent column taken x 100 again
# 19-Nov: "Which products are bought together? Can we sell them as a bundle?" got "Coolant Unit (FG00580) with Procon
# Pump (FG01116), appearing in 146 orders (support 48.16 %)" - ml_product_pairs.support_pct 0.4816 is ALREADY a
# percent (146 of 30,317 orders x 100 = 0.48 %); the AI multiplied it by 100 again. A *_pct column holds a percent
# (the x 100 is done by the SQL or by the ML run: growth_pct, mape_pct, confidence_pct ...), so a percent in the answer
# that is 100 x such a value is flagged - unless that percent is itself a value of the rows or of the request
# (confidence 60.98 % for confidence_pct 60.98, a real 48.16 in another column).
_PCT_COLUMN = re.compile(r"(?:^|_)(?:pct|percent|percentage)$", re.I)
_PERCENT_NUMBER = re.compile(r"(?<![\w.])(-?\d[\d,]*(?:\.\d+)?)\s*(?:%|percent\b|per\s+cent\b)", re.I)


def _as_percent(value):
    """0.4816 -> '0.48', 0.475 -> '0.48'; a very small value keeps its own decimals (0.0012 -> '0.0012')."""
    value = decimal.Decimal(str(value))
    if abs(value) < decimal.Decimal("0.01"):
        return format(value.normalize(), "f")
    return f"{value.quantize(decimal.Decimal('0.01'), rounding=decimal.ROUND_HALF_UP):,}"


def percent_problems(result, answer, sent_text=""):
    """The correction sentences of check 3 ([] when nothing is wrong): one per *_pct column whose value the answer
    gives x 100, with up to MOST_ROWS_SHOWN examples."""
    pct_columns = [(i, str(name)) for i, name in enumerate(result.columns or []) if _PCT_COLUMN.search(str(name))]
    times_100 = []  # (100 x the value, column, value) of every *_pct cell that is not 0
    for row in result.rows or []:
        for i, name in pct_columns:
            if i < len(row) and _number(row[i]) and row[i]:
                times_100.append((abs(float(row[i])) * 100, name, row[i]))
    if not times_100:
        return []
    known = sorted({float(v) for v in answer_check._row_values(result.rows)} | _numbers_in(sent_text))
    wrong = {}  # column -> ["support_pct 0.4816 ... not 48.16 %"]
    for match in _PERCENT_NUMBER.finditer(answer or ""):
        written = match.group(1)
        try:
            value = decimal.Decimal(written.replace(",", ""))
        except decimal.InvalidOperation:
            continue
        number, places = abs(float(value)), max(0, -value.as_tuple().exponent)
        if not number or _found(number, 1, places, known):
            continue  # the percent is a value of the rows or of the request: it is right as it is
        for hundred, name, cell in times_100:
            if _found(number, 1, places, [hundred]):
                cell_text = format(decimal.Decimal(str(cell)).normalize(), "f")  # 0.4816 as stored, never rounded
                wrong.setdefault(name, []).append(f"{name} {cell_text} is already a percent: write "
                                                  f"{_as_percent(cell)} %, not {written} %")
                break
    return [("; ".join(list(dict.fromkeys(examples))[:MOST_ROWS_SHOWN]) +
             f". Never multiply {name} by 100.") for name, examples in wrong.items()]


# ------------------------------------------------------------------ check 4: the stock report date not said
# 19-Nov: "Which products have the most stock right now?" listed the quantities of the newest stock report but never
# said which report they are from (31-Oct-2026) - "right now" is the newest stock report, not today. When the rows of
# a fact_stock_ledger query have a report_date column (docs/business_rules.md: stock queries return it), the answer
# must name that date. Only a few dates (one report, or two compared); more are a list, not checked.
_STOCK_TABLE = re.compile(r"\bfact_stock_ledger\b", re.I)
_REPORT_DATE_COLUMN = re.compile(r"(?:^|_)report_date$", re.I)
MOST_REPORT_DATES = 3


def _says_date(answer, day):
    """True when the answer names this day: 31-Oct-2026, 31 October 2026, October 31, 2026, 2026-10-31, 31/10/2026."""
    month, day_number = rf"{day:%b}[a-z]*\.?", rf"0?{day.day}(?:st|nd|rd|th)?"
    patterns = (rf"\b{day_number}(?:\s+of)?[\s/.,-]*{month}[\s/.,-]*{day.year}\b",
                rf"\b{month}\s*{day_number},?\s*{day.year}\b",
                rf"\b{day.year}-0?{day.month}-0?{day.day}\b",
                rf"\b0?{day.day}[/.-]0?{day.month}[/.-]{day.year}\b")
    return any(re.search(pattern, answer or "", re.I) for pattern in patterns)


def report_date_problems(result, answer):
    """The correction sentence of check 4 ([] when nothing is wrong): the stock report dates of the rows that the
    answer does not name."""
    if not _STOCK_TABLE.search(result.sql or "") or agent.found_nothing(result.rows):
        return []
    columns = [i for i, name in enumerate(result.columns or []) if _REPORT_DATE_COLUMN.search(str(name))]
    days = set()
    for row in result.rows or []:
        for i in columns:
            value = row[i] if i < len(row) else None
            if isinstance(value, datetime.date):
                days.add(value.date() if isinstance(value, datetime.datetime) else value)
    if not days or len(days) > MOST_REPORT_DATES:
        return []
    missing = [day for day in sorted(days) if not _says_date(answer, day)]
    if not missing:
        return []
    names = " and ".join(f"{day:%d-%b-%Y}" for day in missing)
    return [f"Your answer does not say which stock report the numbers are from: the rows are from the stock report "
            f"of {names}. Say it, e.g. \"As of the stock report {missing[0]:%d-%b-%Y}, ...\" (\"right now\" / "
            "\"current\" stock = the newest stock report, not today)."]


# ------------------------------------------------------------------ check 5: the 500-row cap told as the total
# 20-Nov: "Active customers in Oct 2026" listed customers, the SQL guard cut the list at 500 rows (707 were active),
# and the answer said "there were 500 active customers ... the full table contains all 500". When the result was cut
# (result.truncated), a sentence that gives the row count as a count is flagged - not one that says "more than 500",
# "the first 500", "500+", "the 500-row limit", "the list was cut ..." (or 500 as an amount / a percent).
_BEFORE_THE_CAP = re.compile(r"(?:first|top|only|INR|Rs\.?|JPY|USD|\$)\s*$", re.I)
_AFTER_THE_CAP = re.compile(r"^\s*(?:\+|-?\s*rows?\s+(?:limit|cap|maximum)|%|percent)", re.I)
_MORE_SAID = re.compile(r"\bmore\s+than\b|\bor\s+more\b|\bover\s+\d|\babove\s+\d|\bat\s+least\b|\bexceed|\bbeyond\b|"
                        r"\blimit|\bcapped\b|\bcut\b|\bstopped\b|\btruncated\b", re.I)


def row_limit_problems(result, answer):
    """The correction sentence of check 5 ([] when nothing is wrong): the answer gives the number of rows of a list
    the SQL guard cut (500) as the count of the things listed."""
    if not result.truncated or not result.rows:
        return []
    cap = len(result.rows)
    told = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", answer or ""):
        if _MORE_SAID.search(sentence):
            continue
        for found in re.finditer(rf"(?<![\d.,]){cap:,}(?![\d.,]*\d)", sentence):
            if not (_BEFORE_THE_CAP.search(sentence[:found.start()]) or _AFTER_THE_CAP.search(sentence[found.end():])):
                told.append(sentence.strip().rstrip("."))
                break
    if not told:
        return []
    return [f'Your answer says "{told[0]}", but the query stopped at the {cap}-row limit: the data has MORE than {cap} '
            f"rows, so {cap} is not the total (the table shows only the first {cap}). Say the list has more than "
            f"{cap} rows and that the exact number needs a count question (e.g. \"How many ... ?\") - never say there "
            f"are {cap} or \"all {cap}\"."]


# ------------------------------------------------------------------ check 6: a month after the data end
# 20-Nov: "Credit note value as a percent of sales, by month, for the last 6 months" listed the sales month Nov 2026
# (21-Oct to 20-Nov-2026) while the invoice data ends on 31-Oct-2026 (MAX(invoice_date)): 11 of its 31 days, and the
# answer called it the month with the lowest invoices. A month of the rows that ends after the invoice data's last
# date must be told as incomplete. Only for a query of fact_invoice_lines (not of the ml_ tables: a forecast month is
# after the data on purpose). A column with "month_year" / "calendar" in its name is a calendar month (1st to the
# last day); any other month is taken as a sales month (21st to the 20th) - its end is the earlier one, so a complete
# month is never flagged; a date column of the row named like *_end (sales_period_end) is used when there is one.
_INVOICE_TABLE = re.compile(r"\bfact_invoice_lines\b", re.I)
_ML_TABLE = re.compile(r"\bml_\w+", re.I)
_MONTH_CELL = re.compile(r"^\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s-]+(20\d\d)\s*$", re.I)
_END_COLUMN = re.compile(r"(?:^|_)end$", re.I)
_CALENDAR_MONTH_COLUMN = re.compile(r"month_year|calendar", re.I)
_PART_WORDS = re.compile(r"\bincomplete|\bpartial|\bpart(?:ly)?\s+(?:of\s+(?:the|a|its)\s+)?month|\bnot\s+(?:yet\s+)?"
                         r"(?:complete|over|full|finished)|\bnot\s+a\s+(?:full|complete)|\bso\s+far\b|\bto\s+date\b|"
                         r"\bonly\s+(?:up\s+)?(?:to|till|until)\b|\bdata\s+(?:only\s+)?(?:ends|stops|runs)|"
                         r"\bonly\s+\d+\s+days|\bin\s+progress\b|\bstill\s+(?:running|open|going)", re.I)
MOST_PART_MONTHS = 2


_MONTH_INDEX = {name: n for n, name in enumerate(_MONTHS, start=1)}  # 'jan' -> 1 ...


def _month_dates(word, year, calendar):
    """(first day, last day) of a sales month (21st of the month before to the 20th) or a calendar month."""
    month, year = _MONTH_INDEX[word[:3].lower()], int(year)
    if calendar:
        start = datetime.date(year, month, 1)
        return start, datetime.date(year + month // 12, month % 12 + 1, 1) - datetime.timedelta(days=1)
    return datetime.date(year - (month == 1), (month - 2) % 12 + 1, 21), datetime.date(year, month, 20)


def _row_months(result):
    """{'Nov 2026': (first day, last day)} of the month cells of the rows."""
    months = {}
    ends = [i for i, name in enumerate(result.columns or []) if _END_COLUMN.search(str(name))]
    for i, name in enumerate(result.columns or []):
        calendar = bool(_CALENDAR_MONTH_COLUMN.search(str(name)))
        for row in result.rows or []:
            found = _MONTH_CELL.match(row[i]) if i < len(row) and isinstance(row[i], str) else None
            if not found:
                continue
            start, end = _month_dates(found.group(1), found.group(2), calendar)
            for j in ends:  # the row's own end date (sales_period_end) is the truth
                value = row[j] if j < len(row) else None
                if isinstance(value, datetime.date):
                    end = value.date() if isinstance(value, datetime.datetime) else value
                    break
            months[month_label(found.group(1), found.group(2))] = (start, end)
    return months


def part_month_problems(result, answer):
    """The correction sentence of check 6 ([] when nothing is wrong): the months of the rows that end after the
    invoice data's last date and that the answer does not call incomplete."""
    sql = result.sql or ""
    if not _INVOICE_TABLE.search(sql) or _ML_TABLE.search(sql) or agent.found_nothing(result.rows):
        return []
    months = _row_months(result)
    if not months:
        return []
    try:
        dates = agent.invoice_data_dates()
    except Exception:  # noqa: BLE001 - this check is extra: any failure leaves it out (the other checks still run)
        log.warning("Answer check: the invoice data dates were not read", exc_info=True)
        return []
    if not dates:
        return []
    last = dates[1]
    late = {month: span for month, span in months.items() if span[1] > last}
    if not late or len(late) > MOST_PART_MONTHS:
        return []  # more months after the data end are a forecast-like list, not one part month
    # told: the answer names the data's last date ("data up to 31-Oct-2026"), or calls the month incomplete
    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n+", answer or "") if s.strip()]
    if _says_date(answer, last):
        return []
    told = [month for month in late if any(_PART_WORDS.search(s) and month in months_in(s) for s in sentences)]
    parts = []
    for month, (start, end) in late.items():
        if month in told:
            continue
        if start > last:
            parts.append(f"{month} ({start:%d-%b-%Y} to {end:%d-%b-%Y}) is after the invoice data, which ends on "
                         f"{last:%d-%b-%Y}: it has no data yet")
        else:
            parts.append(f"{month} ({start:%d-%b-%Y} to {end:%d-%b-%Y}) has data only up to {last:%d-%b-%Y} - the "
                         f"invoice data ends there, so it is an incomplete month ({(last - start).days + 1} of its "
                         f"{(end - start).days + 1} days)")
    if not parts:
        return []
    first = next(month for month in late if month not in told)
    return ["The rows include a month the data does not fully cover: " + "; ".join(parts) + ". Say so in the answer, "
            f"e.g. \"{first} has data only up to {last:%d-%b-%Y} (incomplete month)\", and never compare it with the "
            "full months as the lowest / highest."]


# ------------------------------------------------------------------ check 7: a forecast amount in full rupees
# 20-Nov (local model): "What will our sales be next month?" got "the forecast ... is INR 534,887,655.19, with a range
# between INR 498,487,638.37 and INR 571,287,672.01" - the answer rule (agent.ML_RESULTS_NOTE) says "Write forecast
# amounts rounded in Cr (e.g. 123,456,789.00 = about INR 12.3 Cr, range 11.1 - 13.6 Cr)". For a query of ml_sales_forecast, an amount
# of the answer written in full rupees that is a value of a forecast column (forecast_inr, total_forecast_inr, low_inr,
# high_inr ...) is flagged - unless the answer also gives that same amount in Cr / lakh ("INR 537,112,731.17 (about
# 53.7 Cr)"). Actual sales and other amounts are never checked here.
_FORECAST_COLUMN = re.compile(r"forecast|(?:^|_)(?:low|high)(?:_|$)", re.I)
FULL_RUPEES_FROM = 10 ** 5  # smaller amounts have no Cr / lakh form worth writing


def _in_cr(value):
    """534887655.19 -> 'about INR 53.5 Cr'; under 1 Cr two decimals (9123456 -> 'about INR 0.91 Cr')."""
    value = float(value)
    return f"about INR {value / 10 ** 7:,.{1 if abs(value) >= 10 ** 7 else 2}f} Cr"


def forecast_rupee_problems(result, answer):
    """The correction sentence of check 7 ([] when nothing is wrong): the forecast amounts the answer writes in full
    rupees instead of rounded in Cr."""
    if not _FORECAST_TABLE.search(result.sql or "") or agent.found_nothing(result.rows):
        return []
    columns = [i for i, name in enumerate(result.columns or []) if _FORECAST_COLUMN.search(str(name))]
    forecasts = sorted({abs(float(row[i])) for row in result.rows or [] for i in columns
                        if i < len(row) and _number(row[i]) and abs(row[i]) >= FULL_RUPEES_FROM})
    if not forecasts:
        return []
    numbers = answer_check.answer_numbers(_PERCENT.sub(" ", answer or ""))
    rounded = [(float(value), scale, max(0, -value.as_tuple().exponent)) for _w, value, scale in numbers if scale != 1]
    full = []  # (as written, the forecast value)
    for written, value, scale in numbers:
        if scale != 1 or float(value) < FULL_RUPEES_FROM:
            continue
        places = max(0, -value.as_tuple().exponent)
        match = next((f for f in forecasts if _found(float(value), 1, places, [f])), None)
        if match is None or any(_found(number, unit, decimals, [match]) for number, unit, decimals in rounded):
            continue  # not a forecast amount, or the answer also gives it in Cr / lakh
        full.append((written, match))
    if not full:
        return []
    written = ", ".join(dict.fromkeys(f"INR {w}" for w, _m in full))
    examples = "; ".join(dict.fromkeys(f"INR {w} -> {_in_cr(m)}" for w, m in full[:MOST_ROWS_SHOWN]))
    return [f"Your answer writes forecast amounts in full rupees ({written}). Write forecast amounts rounded in Cr as "
            f"the answer rule says (e.g. 123,456,789.00 = about INR 12.3 Cr, range 11.1 - 13.6 Cr): {examples} - the exact numbers are "
            "in the table."]


# ------------------------------------------------------------------ check 8: products named without their codes
# 20-Nov (local model): "What were our top 5 products by sales value?" got "the top product was GCI TX-675-3A 0.4kW
# (415V 50Hz) with INR 106,617,050.00 ..." - the rows have product_code FG01484, but no code was given (descriptions
# repeat across products; the code is how the business finds an item). When the rows list two or more products with
# a code column (product_code, product_a_code, item_code ...) and its description / name column, and the answer names
# products of the rows but gives none of their codes, it is flagged.
_CODE_COLUMN = re.compile(r"^(\w*(?:product|item|sku|material|part)\w*?)_code$", re.I)
_CODE_VALUE = re.compile(r"^(?=[^\s]*\d)[A-Za-z0-9][A-Za-z0-9._/-]{2,19}$")
_NAME_ENDINGS = ("_description", "_name", "_desc")
MIN_NAME_CHARS = 4


def _name_core(text):
    """'GCI TX-675-3A 0.4kW (415V 50Hz)' -> 'gci tx-675-3a 0.4kw' (the part an answer repeats, lower case)."""
    return re.sub(r"\s+", " ", str(text).split("(")[0]).strip().lower()


def _code_columns(columns):
    """[(code column index, name column index)] - product_a_code with product_a_description ..."""
    names = {str(name).lower(): i for i, name in enumerate(columns or [])}
    pairs = []
    for i, name in enumerate(columns or []):
        found = _CODE_COLUMN.match(str(name))
        if found:
            stem = found.group(1).lower()
            j = next((names[stem + end] for end in _NAME_ENDINGS if stem + end in names), None)
            if j is not None:
                pairs.append((i, j))
    return pairs


def product_code_problems(result, answer):
    """The correction sentence of check 8 ([] when nothing is wrong): the answer names products of the rows but
    gives none of their codes."""
    rows = result.rows or []
    if len(rows) < 2 or agent.found_nothing(rows):
        return []
    text = re.sub(r"\s+", " ", (answer or "").lower())
    codes, named = set(), []  # every code of the rows; (name as in the rows, its code, the code column) named
    for i, j in _code_columns(result.columns):
        for row in rows:
            code, name = (row[i], row[j]) if max(i, j) < len(row) else (None, None)
            if not isinstance(code, str) or not _CODE_VALUE.match(code.strip()):
                continue
            codes.add(code.strip().lower())
            core = _name_core(name) if isinstance(name, str) else ""
            if len(core) >= MIN_NAME_CHARS and core in text:
                named.append((str(name).split("(")[0].strip(), code.strip(), result.columns[i]))
    if len(codes) < 2 or not named:
        return []
    if any(re.search(rf"(?<![\w-]){re.escape(code)}(?![\w-])", text) for code in codes):
        return []  # codes are given (also when only some products have one)
    name, code, column = named[0]
    shown = ", ".join(dict.fromkeys(n for n, _c, _col in named[:MOST_ROWS_SHOWN]))
    return [f"Your answer names the products without their codes ({shown}): give each product's code with its name, "
            f"e.g. \"{name} ({code})\" - the codes are in the {column} column of the rows."]


# ------------------------------------------------------------------ check 9: one row's value called the total
# 20-Nov (local model): "Which finished goods have stock but no sales in the last 90 days, and what is that stock
# worth?" listed 29 items (one row per product) and the answer said "a total stock value of INR 466,320.00" - the value
# of the first row; the real total is 2,811,795.75 (the sum of the 29 rows). A sentence that calls an amount a total /
# "in all" / "altogether" / "combined", where that amount is one row's value of a money or quantity column whose
# values differ between the rows, is flagged with the real total (worked out here). Never flagged: a sentence that
# names that row (its customer, product, month ... - "Sakura's total sales were ..."), that ranks ("the highest total
# ..."), a total row of the rows (a cell 'Total' / 'All' / 'Grand total'), the column's real total, a list cut at the
# row limit (the shown rows are not all), rates / prices / averages / percents / running totals.
_TOTAL_WORD = re.compile(r"\btotal(?:s|l?ed|l?ing)?\b|\bin\s+all\b|\baltogether\b|\bcombined\b|"
                         r"\ball\s+together\b", re.I)
_RANKED = re.compile(r"\b(?:highest|lowest|largest|smallest|biggest|top|bottom|most|least|leading|leads|maximum|"
                     r"minimum|max|min|peak|best|worst|first|second|third|each|per|every|individual(?:ly)?|"
                     r"respectively|alone|single|only|one\s+of)\b", re.I)
_SUMMABLE = re.compile(r"_inr$|value|amount|sales|revenue|turnover|qty|quantity|units|cost|stock|spend|purchase",
                       re.I)
_NOT_SUMMABLE = re.compile(r"pct|percent|rate|price|avg|average|mean|median|ratio|lift|score|days|share|cumulative|"
                           r"running|ytd|to_date|so_far|_per_|margin", re.I)
_TOTAL_ROW = re.compile(r"^\s*(?:grand\s+)?(?:total|all|overall)\b", re.I)
_ROW_WORD = re.compile(r"[a-z0-9][a-z0-9&.-]*[a-z0-9]")


def _row_words(row):
    """The words of a row's text cells and its dates as the answers write them (lower case)."""
    words = set()
    for cell in row:
        if isinstance(cell, datetime.date):
            words |= set(_ROW_WORD.findall(agent.format_value(cell)[0].lower()))
        elif isinstance(cell, str):
            words |= {w for w in _ROW_WORD.findall(cell.lower()) if re.search(r"[a-z]", w)}
    return {w for w in words if len(w) >= 3} - _STOP_WORDS


def one_row_total_problems(result, answer):
    """The correction sentence of check 9 ([] when nothing is wrong): an amount called a total that is one row's
    value of a column, with that column's real total over all the rows."""
    rows = result.rows or []
    if len(rows) < 2 or result.truncated or agent.found_nothing(rows):
        return []
    columns = []  # (index, name, [values]) of the money / quantity columns whose values differ between the rows
    for i, name in enumerate(result.columns or []):
        name = str(name)
        if not _SUMMABLE.search(name) or _NOT_SUMMABLE.search(name) or agent._NOT_AN_AMOUNT.search(name) \
                or agent._PLAIN_INT.search(name):
            continue
        values = [row[i] if i < len(row) else None for row in rows]
        if all(_number(v) or v is None for v in values) and len({v for v in values if v is not None}) > 1:
            columns.append((i, name, values))
    if not columns:
        return []
    totals = {i: sum(decimal.Decimal(str(v)) for v in values if v is not None) for i, _name, values in columns}
    every_row = set.intersection(*(_row_words(row) for row in rows))  # words of every row name nothing
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", answer or ""):
        if not _TOTAL_WORD.search(sentence) or _RANKED.search(sentence):
            continue
        said = set(_ROW_WORD.findall(sentence.lower())) | {m.split()[0].lower() for m in months_in(sentence)}
        for written, value, scale in answer_check.answer_numbers(_PERCENT.sub(" ", sentence)):
            number, places = float(value) * scale, max(0, -value.as_tuple().exponent)
            if number < MIN_AMOUNT:
                continue
            if _found(float(value), scale, places, sorted(abs(float(t)) for t in totals.values())):
                continue  # the real total of a column: right
            for i, name, values in columns:
                total = totals[i]
                hits = [row for row, v in zip(rows, values) if v is not None
                        and _found(float(value), scale, places, [abs(float(v))])]
                if not hits or any(any(isinstance(c, str) and _TOTAL_ROW.match(c) for c in row) for row in hits):
                    continue
                if any((_row_words(row) - every_row) & said for row in hits):
                    continue  # the sentence names that row: its own total ("Sakura's total sales ...")
                label = next((c for c in hits[0] if isinstance(c, str) and c.strip()), "")
                label = f" (the row {label.split('(')[0].strip()})" if label else ""
                shown, short = agent.format_value(total, name)[0], short_amount(total)
                return [f'Your answer calls {written} a total ("{sentence.strip()}"), but that is one row\'s value of '
                        f"{name}{label}; the real total of {name} over all {len(rows):,} rows (worked out by our "
                        f"code) is {shown}{f' ({short})' if short else ''}. Give that total, or say plainly that "
                        f"{written} is the value of one row."]
    return []


# ------------------------------------------------------------------ the check and the correction
def problems(result, answer, sent_text="", extra_facts="", correction=""):
    """(the correction message for the AI, the numbers it adds) - ('', '') when the answer is fine.
    correction = the correction the AI was sent (the check of the rewritten answer, agent.explain): its amounts
    count as known for check 2, but never for check 3 - it quotes the wrong percent ("not 48.16 %").
    The check is extra: any failure of its own leaves the answer as it is."""
    try:
        return _problems(result, answer, sent_text, extra_facts, correction)
    except Exception:  # noqa: BLE001
        log.warning("Answer check failed - the answer is kept as it is", exc_info=True)
        return "", ""


def _problems(result, answer, sent_text, extra_facts, correction=""):
    found, facts = no_data_problems(result, answer)
    found += percent_problems(result, answer, f"{sent_text} {extra_facts}")
    found += report_date_problems(result, answer)
    found += row_limit_problems(result, answer)
    found += part_month_problems(result, answer)
    found += forecast_rupee_problems(result, answer)
    found += product_code_problems(result, answer)
    found += one_row_total_problems(result, answer)
    missing = unknown_amounts(result, answer, f"{sent_text} {facts} {extra_facts} {correction}")
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
