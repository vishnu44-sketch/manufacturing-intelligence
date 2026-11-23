"""Question notes: short facts the app works out BEFORE an AI call and adds to its request ("For this question:").

20-Nov-2026 (the company's local model, 95 golden questions): "this financial year" / "this year" questions were
answered for the PREVIOUS financial year (c.financial_year = '2526' on 20-Nov-2026, when FY 2026-27 = '2627' is
running) although the business rule says "this year" = the financial year of CURDATE() (docs/business_rules.md,
"Growth and comparisons") and the request says "Today is ...". The model does not do the step today -> FY -> code.
Now our code does it and gives the result as a fact line, only for the questions that need it:

- SQL request (the block goes right before "Question:", at the end of {earlier}):
  - "this year" / "this financial year" / "current year" / "last year" / "so far" / "YTD" -> the FY of today with its
    dates and code, and the FY before it; a split by month -> the sales_year code of that FY (business rule 6);
  - "last N months" / "past months" / "last month" / "this month" / "last quarter" / "this quarter" -> the sales months
    (quarter) meant, worked out from today and the invoice data end (MAX(invoice_date)): the last N COMPLETE sales
    months up to the data end; a period the data end cuts -> "has data only up to <data end> (incomplete)";
  - a sales month named with its year that the data end cuts (only today's sales month and the one before it are
    looked at - an older one needs no data query: agent.data_coverage_notes tells the answer its real dates);
  - a list or ranking of products -> select each product's code next to its name;
  - (23-Nov) stock held (stock / inventory / on hand, not "run out of stock") -> from a stock report, with its
    report_date selected (never dim_products.in_stock_qty);
  - (23-Nov) a profit / margin of one period (not a profit % between two periods) -> not in ss_gold: NO_DATA when the
    question asks only for that;
  - (23-Nov) active customers -> dim_customers.is_active; items with no sales -> every item of the master;
    exact calendar dates named (01-May-2026) -> used as given, never widened to sales periods.
- Answer request (the block goes at the very end, after the rows):
  - a forecast (forecast words, or SQL on ml_sales_forecast) -> forecast amounts rounded in Cr (the sentence of
    agent.ML_RESULTS_NOTE, with an example worked out from the result's own first row);
  - rows with a product_code column -> name each product with its code (the example: the result's first row);
  - (23-Nov) a split by period ("quarter by quarter", "each month") with 2-8 rows -> every period with its amount.

No line applies -> nothing is added and the request is exactly as before (no tokens). Nothing here is fixed: every
date, code and month comes from today (agent.today()) and the data (agent.invoice_data_dates, kept a while).
lc.calls.LcRequest.inputs() is the one hook: every SQL / answer request goes through it, also the backup model's
cut requests (lc.calls.for_backup) and the retries. A failure here never stops a question: the request goes as it was.
"""
import datetime
import logging
import re
import threading
import time

from . import period_check
from .rag import agent

log = logging.getLogger(__name__)

HEADING = "For this question (worked out by the app):"
ANSWER_HEADING = "For this answer (worked out by the app):"

# ------------------------------------------------------------------ the question's words
# ("this year" / "so far" / "last year" and a year the user names himself: period_check's, the same as its send-back)
# a split by month: the FY's sales months (business rule 6: c.sales_year)
_MONTH_SPLIT = re.compile(r"\b(?:each|every|per|by)\s+(?:sales\s+)?month\b|\bmonth(?:ly|[\s-]*wise|\s+by\s+month)\b"
                          r"|\bmonths?\s+of\s+(?:this|the)\b", re.I)
_NUMBERS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "eleven": 11, "twelve": 12, "few": 3, "couple of": 2}
_LAST_MONTHS = re.compile(r"\b(?:last|past|previous|recent|latest|prior)\s+(?:(\d{1,2}|two|three|four|five|six|seven|eight|"
                          r"nine|ten|eleven|twelve|few|couple\s+of)\s+)?(?:complete\s+|full\s+)?(?:sales\s+)?months\b",
                          re.I)
_LAST_MONTH = re.compile(r"\b(?:last|previous|prior)\s+(?:sales\s+)?month\b(?!s)", re.I)
_THIS_MONTH = re.compile(r"\b(?:this|current)\s+(?:sales\s+)?month\b(?!s)", re.I)
_LAST_QUARTER = re.compile(r"\b(?:last|previous|prior)\s+quarter\b(?!s)", re.I)
_THIS_QUARTER = re.compile(r"\b(?:this|current)\s+quarter\b(?!s)", re.I)
MOST_MONTHS = 36

# a list / ranking of products (not of product categories / groups)
_PRODUCT_GROUPS = re.compile(r"\b(?:product|item)[\s-]*(?:categor\w*|groups?|types?|lines?|famil\w*|wise)\b", re.I)
_PRODUCTS = re.compile(r"\b(?:products?|items?|skus?)\b", re.I)
_PAIRS = re.compile(r"\b(?:together|pairs?)\b", re.I)  # products bought together: ml_product_pairs has its own columns
_RANKING = re.compile(r"\b(?:top|which|list|show|rank\w*|most|least|best|worst|highest|lowest|biggest|smallest|"
                      r"each|every|bottom)\b|\bwhat\s+are\b", re.I)

# 23-Nov: stock held (not "run out of stock soon": ml_stock_runout) and profit / margin (not in ss_gold)
_STOCK = re.compile(r"\b(?:stocks?|inventor(?:y|ies)|on[\s-]hand)\b", re.I)
_RUN_OUT = re.compile(r"\brun(?:s|ning)?[\s-]*out\b|\brunout\b", re.I)
# the last N stock reports (23-Nov: "between the last two stock reports" took ORDER BY report_date LIMIT 2 of the
# ledger rows - the same newest date twice)
_LAST_REPORTS = re.compile(r"\b(?:last|latest|recent|newest|previous|past|two|three|four|\d+)\s+(?:(?:two|three|four|"
                           r"five|\d+)\s+)?(?:stock\s+|inventory\s+)?reports\b", re.I)
_PROFIT = re.compile(r"\bprofit\w*|\bproft\w*|\bmargins?\b|\bmark[\s-]?ups?\b", re.I)
# 23-Nov: "active customers" = the master's is_active flag (not "customers with invoices")
_ACTIVE = re.compile(r"\b(?:in)?active\s+(?:customers?|clients?|buyers?|accounts?)\b", re.I)
# 23-Nov: items with no sales (not "in stock but no sales"): every item of the master, not only the ones in stock
_NO_SALES = re.compile(r"\b(?:no|zero|without)\s+(?:sales|invoices?|orders?)\b|\b(?:not|never)\s+(?:been\s+)?"
                       r"(?:sold|invoiced|ordered)\b|\b(?:did\s+not|didn'?t|have\s+not|haven'?t|has\s+not|hasn'?t)\s+"
                       r"(?:sell|sold|been\s+sold)\b|\bunsold\b|\bnon[\s-]?moving\b", re.I)
_ITEMS = re.compile(r"\b(?:products?|items?|skus?|finished\s+goods?|raw\s+materials?|materials?|parts?)\b", re.I)
# 23-Nov: a split by period ("quarter by quarter") - the answer gives each period, not only the highest and lowest
_EACH_PERIOD = re.compile(r"\b(quarter|month|year)s?[\s-]*(?:by|on|to)[\s-]*(?:quarter|month|year)\b"
                          r"|\b(?:each|every|per)\s+(?:sales\s+|fiscal\s+|financial\s+|calendar\s+)?(quarter|month|year)\b"
                          r"|\b(quarter|month)(?:ly|[\s-]*wise)\b", re.I)
# 23-Nov: exact calendar dates named in the question (01-May-2026, 1 May 2026, 2026-05-01)
_DAY_DATE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[-\s/.]*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
                       r"[-\s/.,]*(\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b", re.I)
MOST_PERIOD_ROWS = 8    # more rows than this: the highest and the lowest (the answer rule), the rest in the table

_FORECAST_WORDS = re.compile(r"\b(?:fore?ca?st\w*|predict\w*|projection\w*|outlook)\b", re.I)
_FORECAST_TABLE = re.compile(r"\bml_sales_forecast\b", re.I)
# the sentence of agent.ML_RESULTS_NOTE about Cr (kept there; its example is swapped for one from the rows)
_CR_SENTENCE = re.compile(r"Write forecast amounts rounded in Cr.*?the exact numbers are in the table\.")
_CR_EXAMPLE = re.compile(r"\(e\.g\.[^)]*\)")
_FORECAST_COLUMN = re.compile(r"^(?:\w+_)?forecast_inr$", re.I)   # forecast_inr, total_forecast_inr ...
CRORE = 10 ** 7


# ------------------------------------------------------------------ dates
def fy_text(first):
    """2026 -> ('FY 2026-27', '2627', first day, last day)."""
    label, code, _, _ = period_check._fy(first)
    return label, code, datetime.date(first, 4, 1), datetime.date(first + 1, 3, 31)


def _day(value):
    return f"{value:%d-%b-%Y}"


def sales_month_of(day):
    """The sales month a date belongs to (the 21st of the previous month to the 20th, named after the month it ends
    in) -> (year, month)."""
    if day.day <= 20:
        return day.year, day.month
    return (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)


def _shift(year, month, months):
    """(year, month) moved by a number of months."""
    index = year * 12 + month - 1 + months
    return index // 12, index % 12 + 1


def sales_month_dates(year, month):
    """(first day, last day) of sales month (year, month): 21st of the previous month to the 20th."""
    before = _shift(year, month, -1)
    return datetime.date(before[0], before[1], 21), datetime.date(year, month, 20)


def month_name(year, month):
    return f"{datetime.date(year, month, 1):%b %Y}"


def last_complete_sales_month(limit):
    """The newest sales month that is over on `limit` (its 20th is on or before it) -> (year, month)."""
    year, month = sales_month_of(limit)
    return (year, month) if limit >= sales_month_dates(year, month)[1] else _shift(year, month, -1)


def fiscal_quarter(day):
    """(first year of the FY, quarter 1-4, first day, last day) of the FY quarter (calendar dates) a date is in."""
    first = period_check.financial_year(day)
    quarter = (day.month - 4) % 12 // 3 + 1
    start_month = (quarter - 1) * 3 + 4
    start = datetime.date(first + (start_month > 12), (start_month - 1) % 12 + 1, 1)
    after = _shift(start.year, start.month, 3)
    return first, quarter, start, datetime.date(after[0], after[1], 1) - datetime.timedelta(days=1)


# ------------------------------------------------------------------ the data end (kept a while)
DATA_END_SECONDS = 600       # like the Home page's numbers (home.CACHE_SECONDS): a new data load shows within 10 min
_kept = {}
_kept_lock = threading.Lock()


def data_end(today):
    """The newest invoice date (MAX(invoice_date), agent.invoice_data_dates) - kept DATA_END_SECONDS per day; None when
    MySQL cannot say (then nothing is kept and it is asked again next time). A test that sets its own data dates (another
    agent.invoice_data_dates) never gets another test's value."""
    source = agent.invoice_data_dates
    key = (today, id(source))
    now = time.monotonic()
    with _kept_lock:
        hit = _kept.get(key)
    if hit and now - hit[0] < DATA_END_SECONDS:
        return hit[1]
    dates = source()
    last = dates[1] if dates else None
    if last is not None:
        with _kept_lock:
            _kept.clear()
            _kept[key] = (now, last)
    return last


def clear_cache():
    """Forget the kept data end (tests; a new data load)."""
    with _kept_lock:
        _kept.clear()


# ------------------------------------------------------------------ the SQL request's notes
def fy_line(question, today):
    """The FY line for "this year" / "last year" / "so far" questions ('' = none)."""
    text = question or ""
    if not (period_check.this_year_words(text) or period_check.last_year_said(text)):
        return ""  # also "this month so far" (the month's), "calendar year", "sales in 2026"
    first = period_check.financial_year(today)
    label, code, start, end = fy_text(first)
    last_label, last_code, last_start, last_end = fy_text(first - 1)
    line = (f"- this year / this financial year = {label} ({_day(start)} to {_day(end)}; so far = up to today, "
            f"CURDATE()): c.financial_year = '{code}'. Last year = {last_label} ({_day(last_start)} to "
            f"{_day(last_end)}): c.financial_year = '{last_code}' - never use '{last_code}' for this year.")
    if _MONTH_SPLIT.search(text):
        line += (f" Split by sales month: c.sales_year = '{code}' (sales months Apr {first} to Mar {first + 1}), "
                 f"ORDER BY c.sales_period_no.")
    return line


def _cut(name, start, end, last):
    """' - it has data only up to 31-Oct-2026 (incomplete)' when the data end cuts the period, ' - no invoice data
    yet (the data ends ...)' when it ends before it, '' otherwise (or when the data end is not known)."""
    if last is None or last >= end:
        return ""
    if last < start:
        return f"; {name} has no invoice data yet (the invoice data ends {_day(last)})"
    return f"; {name} has data only up to {_day(last)} (incomplete)"


def month_lines(question, today, end_of_data):
    """The lines for "last N months", "last / this month", "last / this quarter" and named months the data end cuts.
    end_of_data = a function giving the newest invoice date (asked only when a line needs it)."""
    text = question or ""
    lines = []
    wants_months = _LAST_MONTHS.search(text)
    this_year, this_month = sales_month_of(today)
    # a named month: only today's sales month and the one before it (the months a data load can still be cutting) -
    # an older month needs no data query here (the answer is told its real dates by agent.data_coverage_notes)
    recent = {month_name(this_year, this_month), month_name(*_shift(this_year, this_month, -1))}
    named = [] if re.search(r"calendar", text, re.I) else [
        name for name in agent.forecast_months_asked(text)[:3] if name in recent]
    if not (wants_months or _LAST_MONTH.search(text) or _THIS_MONTH.search(text) or _LAST_QUARTER.search(text)
            or _THIS_QUARTER.search(text) or named):
        return lines
    last = end_of_data()
    if wants_months:
        word = (wants_months.group(1) or "").lower()
        count = int(word) if word.isdigit() else _NUMBERS.get(re.sub(r"\s+", " ", word), 3)
        if 1 <= count <= MOST_MONTHS:
            limit = min(today, last) if last else today
            year, month = last_complete_sales_month(limit)
            first_year, first_month = _shift(year, month, -(count - 1))
            start, end = sales_month_dates(first_year, first_month)[0], sales_month_dates(year, month)[1]
            names = [month_name(*_shift(first_year, first_month, n)) for n in range(count)]
            span = names[0] if count == 1 else f"{names[0]} to {names[-1]}"
            data = f"; the invoice data ends {_day(last)}" if last else ""
            line = (f"- the last {count} months = the last {count} complete sales months up to "
                    f"{'the data end' if last and last < today else 'today'}: {span} ({_day(start)} to {_day(end)}"
                    f"{data})")
            if count <= 6:
                line += ": c.sales_month IN (" + ", ".join(f"'{n}'" for n in names) + ")"
            lines.append(line + ".")
    if _THIS_MONTH.search(text):
        start, end = sales_month_dates(this_year, this_month)
        name = month_name(this_year, this_month)
        lines.append(f"- this month = sales month {name} ({_day(start)} to {_day(end)}), so far = up to today"
                     f"{_cut(name, start, end, last)}.")
    if _LAST_MONTH.search(text):
        year, month = _shift(this_year, this_month, -1)
        start, end = sales_month_dates(year, month)
        name = month_name(year, month)
        lines.append(f"- last month = sales month {name} ({_day(start)} to {_day(end)}){_cut(name, start, end, last)}.")
    first, quarter, start, end = fiscal_quarter(today)
    if _THIS_QUARTER.search(text):
        label = f"Q{quarter} of {fy_text(first)[0]}"
        lines.append(f"- this quarter = {label} ({_day(start)} to {_day(end)}; calendar dates): c.financial_year = "
                     f"'{fy_text(first)[1]}' AND c.fiscal_quarter = {quarter}, so far = up to today"
                     f"{_cut(label, start, end, last)}.")
    if _LAST_QUARTER.search(text):
        first, quarter, start, end = fiscal_quarter(start - datetime.timedelta(days=1))
        label = f"Q{quarter} of {fy_text(first)[0]}"
        lines.append(f"- last quarter = {label} ({_day(start)} to {_day(end)}; calendar dates): c.financial_year = "
                     f"'{fy_text(first)[1]}' AND c.fiscal_quarter = {quarter}{_cut(label, start, end, last)}.")
    for name in named:
        try:
            month = datetime.datetime.strptime(name, "%b %Y").date()
        except ValueError:
            continue
        start, end = sales_month_dates(month.year, month.month)
        if last and start <= last < end:  # only a month the data end cuts
            lines.append(f"- {name} = sales month {_day(start)} to {_day(end)}{_cut(name, start, end, last)}.")
    return lines


def product_line(question):
    """The product-code line for a list / ranking of products ('' = none)."""
    text = _PRODUCT_GROUPS.sub(" ", question or "")
    if _PRODUCTS.search(text) and _RANKING.search(text) and not _PAIRS.search(text):
        return ("- a list of products: SELECT p.product_code next to p.product_description, so the answer can give "
                "each product's code with its name.")
    return ""


def stock_line(question):
    """The stock-report line for a question about stock held ('' = none). 23-Nov (local model): "how much stock do we
    have of each?" and "how much of FG00542 do we have in stock?" gave the right quantities but never said which stock
    report they are from - one read dim_products.in_stock_qty (the item master export), the other selected no
    report_date (so answer_verify check 4 could not ask for it)."""
    text = question or ""
    if not _STOCK.search(text) or _RUN_OUT.search(text):
        return ""
    line = ("- stock numbers come from a stock report (fact_stock_ledger; right now / current = the newest report_date), "
            "never from dim_products.in_stock_qty (an old item master export): SELECT sl.report_date with them, so the "
            "answer can say which stock report they are from.")
    if _LAST_REPORTS.search(text):
        line += (" The last N stock reports = SELECT DISTINCT report_date FROM fact_stock_ledger ORDER BY report_date "
                 "DESC LIMIT N (without DISTINCT the ledger's rows give the newest date N times); select each "
                 "report's date as a column (e.g. older_report_date, newer_report_date) so the answer names them.")
    return line


def profit_line(question):
    """The 'profit is not in the data' line for a profit / margin of ONE period ('' = none; a profit % between two
    periods is answered with the revenue growth, agent.profit_comparison). 23-Nov (local model): "what is our profit
    margin this year" got a revenue query (status ok) instead of the NO_DATA reply the SQL rules ask for."""
    text = question or ""
    if not _PROFIT.search(text) or agent.profit_comparison(text):
        return ""
    return ("- profit / margin is not in ss_gold (selling prices only, not the cost of the items sold): if the question "
            "asks only for a profit or margin, reply with the NO_DATA line (and a TRY line) - never a revenue query; "
            "anything else it asks for gets its SQL and the MISSING line for profit.")


def active_line(question):
    """The 'active = is_active' line for active / inactive customers ('' = none). 23-Nov (local model): "How many of
    our active customers have not bought anything from us this financial year?" counted every customer with an
    invoice ever (4,074) instead of the customer master's active customers (4,885) - and counted credit notes as
    buying."""
    if not _ACTIVE.search(question or ""):
        return ""
    return ("- active customers = dim_customers.is_active = 'Y' (the customer master: every active customer, bought or "
            "not; CHAR 'Y' / 'N'), never 'customers with invoices'; bought = document_type = 'INVOICE' rows (a credit "
            "note is no purchase); the Unknown customer (-1) is no customer.")


def no_sales_line(question):
    """The 'every item of the master' line for items with no sales ('' = none; not when the question is about stock
    held - "in stock but no sales" starts from the stock report). 23-Nov (local model): "Which finished goods had no
    sales between 01-May-2026 and 31-Oct-2026?" counted only the finished goods in stock (12) instead of all of the
    product master's (730)."""
    text = question or ""
    if not (_NO_SALES.search(text) and _ITEMS.search(text)) or _STOCK.search(text):
        return ""
    return ("- items with no sales = every item of the product master (dim_products, its item_group when one is named) "
            "with NOT EXISTS an invoice line in the period - not only the items in stock (the question does not ask "
            "about stock); give their count with COUNT(*) OVER () (a list stops at 500 rows).")


def exact_dates_line(question):
    """The 'use the dates as given' line when the question names calendar days ('' = none). 23-Nov (local model):
    "... between 01-May-2026 and 31-Oct-2026?" was widened to the sales periods around those days (21-Apr-2026 to
    20-Nov-2026: 697 finished goods instead of 730)."""
    days = []
    for found in _DAY_DATE.finditer(question or ""):
        try:
            if found.group(1):
                day = datetime.datetime.strptime(f"{found.group(1)} {found.group(2)[:3]} {found.group(3)}",
                                                 "%d %b %Y").date()
            else:
                day = datetime.date(int(found.group(4)), int(found.group(5)), int(found.group(6)))
        except ValueError:
            continue
        if day not in days:
            days.append(day)
    if not days:
        return ""
    named = " and ".join(_day(day) for day in days[:4])
    given = ", ".join(f"'{day:%Y-%m-%d}'" for day in days[:4])
    one = len(days) == 1
    return (f"- {named} {'is an exact calendar date' if one else 'are exact calendar dates'}: use "
            f"{'it' if one else 'them'} as given ({given} on invoice_date / report_date / order_date) - never "
            f"widen {'it to the sales period around it' if one else 'them to the sales periods around them'} "
            "(sales_period_start / sales_period_end).")


def sql_notes(question, today, end_of_data=None):
    """The lines of the SQL request's "For this question:" block ([] = none)."""
    end_of_data = end_of_data or (lambda: data_end(today))
    lines = ([fy_line(question, today)] + month_lines(question, today, end_of_data)
             + [product_line(question), stock_line(question), profit_line(question), active_line(question),
                no_sales_line(question), exact_dates_line(question)])
    return [line for line in lines if line]


# ------------------------------------------------------------------ the answer request's notes
def _table(text):
    """(columns, first row) of the answer request's table text ('a | b' lines); ([], []) when there is none."""
    lines = (text or "").split("\n")
    if len(lines) < 2 or not lines[1].strip():
        return [], []
    columns = [c.strip() for c in lines[0].split(" | ")]
    row = [v.strip() for v in lines[1].split(" | ")]
    return (columns, row) if len(row) == len(columns) else (columns, [])


def _crore(value):
    """'534,887,655.19' -> '53.5' (Cr), None when it is not a number."""
    try:
        return f"{float(value.replace(',', '')) / CRORE:,.1f}"
    except (AttributeError, ValueError):
        return None


def forecast_line(question, sql, columns, row):
    """The Cr line of a forecast answer ('' = none): agent.ML_RESULTS_NOTE's sentence, its example from the rows."""
    if not (_FORECAST_WORDS.search(question or "") or _FORECAST_TABLE.search(sql or "")):
        return ""
    found = _CR_SENTENCE.search(agent.ML_RESULTS_NOTE)
    sentence = found.group(0) if found else "Write forecast amounts rounded in Cr - the exact numbers are in the table."
    values = dict(zip(columns, row))
    # 23-Nov: the forecast column may be named otherwise (total_forecast_inr in the "top customer in a future month"
    # example) - without it the rule's own example amount was copied into the answer ("about INR 53.5 Cr" for 53.7)
    column = next((c for c in ("forecast_inr", *columns) if _FORECAST_COLUMN.search(c or "") and values.get(c)), None)
    amount = _crore(values.get(column)) if column else None
    if amount:
        low = _crore(next((values[c] for c in columns if c.endswith("low_inr") and values.get(c)), None))
        high = _crore(next((values[c] for c in columns if c.endswith("high_inr") and values.get(c)), None))
        example = f"(e.g. {values[column]} = about INR {amount} Cr" + (f", range {low} - {high} Cr)"
                                                                      if low and high else ")")
        sentence = _CR_EXAMPLE.sub(lambda _: example, sentence, count=1)
    return "- " + sentence


def product_answer_line(columns, row):
    """The 'name each product with its code' line when the rows have product codes ('' = none)."""
    if "product_code" not in columns:
        return ""
    values = dict(zip(columns, row))
    name = next((values[c] for c in ("product_description", "product_name", "product") if values.get(c)), "")
    example = f", e.g. {name} ({values['product_code']})" if name and values.get("product_code") else ""
    return f"- name each product with its code{example}."


def _row_count(note, table):
    """The number of rows of the result: the answer request's note ("7 row(s)"), else the table's lines."""
    found = re.match(r"\s*(\d+) row", note or "")
    if found:
        return int(found.group(1))
    lines = (table or "").split("\n\n")[0].split("\n")
    return max(0, len([line for line in lines if line.strip()]) - 1)


def each_period_line(question, count):
    """The 'give every period' line when the question asks for a split by period and the rows are few ('' = none).
    23-Nov (local model): "How did our sales grow quarter by quarter over the last two financial years?" got the
    highest and the lowest quarter only (the rule for more than 4 rows), not the 7 quarters asked for."""
    found = _EACH_PERIOD.search(question or "")
    if not found or not 2 <= count <= MOST_PERIOD_ROWS:
        return ""
    period = next(word for word in found.groups() if word).lower()
    return (f"- the question asks for each {period}: give every row's {period} with its amount as in the rows (all "
            f"{count} rows, short) - not only the highest and the lowest; this replaces the 'more than 4 rows' rule.")


def answer_notes(question, sql, table, note=""):
    """The lines of the answer request's "For this answer:" block ([] = none)."""
    columns, row = _table(table)
    lines = [forecast_line(question, sql, columns, row), product_answer_line(columns, row),
             each_period_line(question, _row_count(note, table))]
    return [line for line in lines if line]


# ------------------------------------------------------------------ the hook (lc.calls.LcRequest.inputs)
_WRITTEN_OUT = re.compile(r"^Written out in full: (.*)\)\s*$", re.S)


def asked_text(question_value):
    """The user's question (and the full one it was written out as) from the SQL request's {question} value: graph
    pick_schema adds the app's own notes after it, each starting with "\\n(" - those are not the user's words."""
    parts = str(question_value or "").split("\n(")
    asked = [parts[0]]
    for part in parts[1:]:
        found = _WRITTEN_OUT.match(part)
        if found:
            asked.append(found.group(1))
    return " ".join(asked)


def with_notes(chain, values):
    """The values of an SQL / answer request with this question's notes added ('earlier' ends with the SQL block,
    right before "Question:"; 'documents' ends with the answer block). Other requests, or no note: as they are."""
    try:
        if chain == "sql" and "question" in values and "earlier" in values:
            lines = sql_notes(asked_text(values["question"]), agent.today())
            if lines:
                return {**values, "earlier": f"{values['earlier']}{HEADING}\n" + "\n".join(lines) + "\n"}
        elif chain == "answer" and "question" in values and "documents" in values:
            question = f"{values['question']} {values.get('understood') or ''}"
            lines = answer_notes(question, values.get("sql"), values.get("table"), values.get("note"))
            if lines:
                return {**values, "documents": f"{values['documents']}\n\n{ANSWER_HEADING}\n" + "\n".join(lines)}
    except Exception:  # a note is a help, never a reason to fail the question
        log.warning("Question notes could not be worked out - the request goes without them", exc_info=True)
    return values
