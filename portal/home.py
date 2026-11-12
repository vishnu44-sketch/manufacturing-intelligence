"""The Home page (/api/home, every signed-in user): everything the first page shows, in one read-only reply.

calendar     today, the NOP sales month we are in (21st of the previous month to the 20th, named after the
             month it ends in) and the financial year
kpis         net sales of the last complete NOP sales month (against the month before), net sales, active
             customers and products sold this FY so far, open sales orders, and the stock value of the latest
             stock report, then the top customer and the top product of the last complete NOP month (these
             two also have "name"; active customers also has "total", all customers). Each card also has "trend" (a small line: the last 6 complete NOP months,
             oldest first; null for open orders, stock and the top cards), "ask" (the question a click on it asks
             on the Ask page) and "facts" (1-3 short chips such as '14 lines' or '2.7% of Oct 2026 sales';
             null for the cards without them)
tables       the main ai_gold tables with their records and the dates they hold
connections  MySQL ai_gold, the app's own database, the Qdrant collections mi_docs / mi_pdfs and Groq - only
             names and a green / red status, never a host, a port, a user name, a password or a key. Groq is
             never called: only "key set" / "not set" and the model name.
usage        the user's own questions today, and the AI tokens of today's period against the daily limit
             (usage.ai_usage, the same counting as the box on History)
recent       the user's own last 5 questions (as History shows them), each with a link to its answer

The rules of the data (docs/business_rules.md): sales = SUM(net_taxable_value) (credit notes are negative
already); nothing dated after today counts - the data also has test rows dated in the future; open orders =
status 'Open' and dated up to today; stock = the 'Closing balance' rows of the latest report up to today; the
top customer / product never counts the Unknown row (-1).
Fixed SQL written here, run read-only through warehouse.run_select_params. No AI call (0 tokens) and
nothing is written. The numbers are kept 10 minutes, the connection checks 1 minute. A part that cannot be
read says so in its own error field, and the rest of the reply still comes.
"""
import datetime
import decimal
import logging
import os
import threading
import time

from django.conf import settings
from django.db import connection
from django.db.models import Count, Sum
from django.utils import dateformat, timezone

from . import services
from .models import Question
from .rag import agent, store, warehouse
from .usage import ai_usage

log = logging.getLogger(__name__)

CACHE_SECONDS = 600   # the numbers and the tables are kept 10 minutes
CHECK_SECONDS = 60    # the connection checks are kept 1 minute
MYSQL_DOWN = "The company data (MySQL) can't be read right now - please try again in a minute."
NOT_IN_CALENDAR = "Today is not in the calendar of the data (dim_calendar)."
PART_FAILED = "This part can't be read right now."


class Missing(Exception):
    """Something the page needs is not there (today not in the calendar, a collection never built).
    The message is safe to show."""

# the main ai_gold tables on the page: (table, name, date column, what it holds)
MAIN_TABLES = (
    ("fact_invoice_lines", "Sales invoices", "invoice_date", "Invoice, credit and debit note lines"),
    ("fact_sales_order_lines", "Sales orders", "order_date", "Sales order lines"),
    ("fact_stock_ledger", "Stock", "report_date", "Stock reports: balances and movements"),
    ("dim_customers", "Customers", "", "The customer master"),
    ("dim_products", "Products", "", "The item master"),
    ("dim_calendar", "Calendar", "full_date", "One row per day, with the FY and the NOP sales months"),
)

CALENDAR_SQL = """
SELECT CURDATE(), t.nop_sales_month, t.nop_sales_period_start, t.nop_sales_period_end,
       t.financial_year, t.financial_year_label,
       p.nop_sales_month, p.nop_sales_period_start, p.nop_sales_period_end,
       pp.nop_sales_month, pp.nop_sales_period_start, pp.nop_sales_period_end,
       (SELECT MIN(y.full_date) FROM dim_calendar y WHERE y.financial_year = t.financial_year AND y.date_id <> -1)
FROM dim_calendar t
LEFT JOIN dim_calendar p ON p.full_date = t.nop_sales_period_start - INTERVAL 1 DAY
LEFT JOIN dim_calendar pp ON pp.full_date = p.nop_sales_period_start - INTERVAL 1 DAY
WHERE t.full_date = CURDATE()"""

# one sum / count per period (the periods are dates, given as parameters)
SALES_PART = "ROUND(SUM(CASE WHEN f.invoice_date BETWEEN %s AND %s THEN f.net_taxable_value ELSE 0 END), 2)"
CUSTOMERS_PART = ("COUNT(DISTINCT CASE WHEN f.invoice_date BETWEEN %s AND %s AND f.customer_id <> -1 "
                  "THEN f.customer_id END)")
PRODUCTS_PART = ("COUNT(DISTINCT CASE WHEN f.invoice_date BETWEEN %s AND %s AND f.product_id <> -1 "
                 "THEN f.product_id END)")
SALES_FROM = """
FROM fact_invoice_lines f
WHERE f.invoice_date BETWEEN %s AND %s AND f.invoice_date <= CURDATE()"""

# the small line under four KPI cards: per NOP month of the last 6 complete ones, net sales, active customers,
# products invoiced and the FY running total at the month's end. dim_calendar has one row per DAY, so the month
# list is DISTINCT months first (6 rows), and only then joined to the invoices - a month without a sale gives 0.
# A month of this FY also takes the lines from the FY start (the 1st %s), so its running total is in the same
# pass: no query per month (invoice_date has no index, a sub-query per month would read the table each time).
TREND_SQL = """
SELECT m.nop_sales_month, m.nop_sales_period_end,
       ROUND(COALESCE(SUM(CASE WHEN i.invoice_date >= m.nop_sales_period_start THEN i.net_taxable_value END), 0), 2),
       COUNT(DISTINCT CASE WHEN i.invoice_date >= m.nop_sales_period_start AND i.customer_id <> -1
                           THEN i.customer_id END),
       COUNT(DISTINCT CASE WHEN i.invoice_date >= m.nop_sales_period_start AND i.product_id <> -1
                           THEN i.product_id END),
       ROUND(COALESCE(SUM(CASE WHEN i.invoice_date >= %s THEN i.net_taxable_value END), 0), 2)
FROM (SELECT DISTINCT nop_sales_month, nop_sales_period_start, nop_sales_period_end
      FROM dim_calendar
      WHERE date_id <> -1 AND nop_sales_period_end <= %s AND nop_sales_period_end <= CURDATE()
      ORDER BY nop_sales_period_end DESC
      LIMIT 6) m
LEFT JOIN fact_invoice_lines i
       ON i.invoice_date BETWEEN LEAST(m.nop_sales_period_start, %s) AND m.nop_sales_period_end
      AND i.invoice_date <= CURDATE()
GROUP BY m.nop_sales_month, m.nop_sales_period_start, m.nop_sales_period_end
ORDER BY m.nop_sales_period_end"""

# what a click on a KPI card asks on the Ask page ({fy} = 'FY 2026-27')
KPI_ASK = {
    "month_sales": "Net sales of the last 6 NOP months as a line chart",
    "fy_sales": "Net sales by NOP month of {fy} so far as a line chart",
    "customers": "Active customers in each of the last 6 NOP months",
    "products": "Number of products sold in each of the last 6 NOP months",
    "open_orders": "List the open sales orders up to today",
    "stock": "Stock value by item group on the latest stock report",
    "top_customer": "Top 10 customers of the last NOP month by net sales",
    "top_product": "Top 10 products of the last NOP month by net sales",
}
RECENT_QUESTIONS = 5   # the user's last questions on Home

# docs/sql_examples.md "How many sales orders are open and what is their value?"
OPEN_ORDERS_SQL = """
SELECT COUNT(DISTINCT s.so_number, c.financial_year), COUNT(*),
       ROUND(SUM(s.total_amount), 2), ROUND(SUM(s.total_amount + s.tax_total), 2)
FROM fact_sales_order_lines s
JOIN dim_calendar c ON c.date_id = s.order_date_id
WHERE s.status = 'Open' AND s.order_date <= CURDATE()"""

# the latest stock report up to today (the data also has a test report dated in the future)
STOCK_SQL = """
SELECT sl.report_date, ROUND(SUM(sl.cumulative_value), 2), COUNT(*)
FROM fact_stock_ledger sl
JOIN dim_stock_movement_types m ON m.movement_type_id = sl.movement_type_id
WHERE m.movement_type = 'Closing balance'
  AND sl.report_date = (SELECT MAX(report_date) FROM fact_stock_ledger WHERE report_date <= CURDATE())
GROUP BY sl.report_date"""

# the customer and the product with the highest net sales in the last complete NOP month (its first and last day
# are the parameters, twice) - one row each, none when the month had no sale. The dates are filtered on the
# invoice itself, so no calendar join (dim_calendar has one row per day). Ties go to the lower id, so the card
# does not change between two reads. A product without a description shows its item number.
TOP_SQL = """
SELECT 'customer', t.id, cu.customer_name, t.sales
FROM (SELECT il.customer_id AS id, ROUND(SUM(il.net_taxable_value), 2) AS sales
      FROM fact_invoice_lines il
      WHERE il.invoice_date BETWEEN %s AND %s AND il.invoice_date <= CURDATE() AND il.customer_id <> -1
      GROUP BY il.customer_id
      ORDER BY sales DESC, il.customer_id
      LIMIT 1) t
JOIN dim_customers cu ON cu.customer_id = t.id
UNION ALL
SELECT 'product', t.id, COALESCE(NULLIF(p.product_description, ''), p.product_code), t.sales
FROM (SELECT il.product_id AS id, ROUND(SUM(il.net_taxable_value), 2) AS sales
      FROM fact_invoice_lines il
      WHERE il.invoice_date BETWEEN %s AND %s AND il.invoice_date <= CURDATE() AND il.product_id <> -1
      GROUP BY il.product_id
      ORDER BY sales DESC, il.product_id
      LIMIT 1) t
JOIN dim_products p ON p.product_id = t.id"""


# ------------------------------------------------------------------ keeping values a while
_cache = {}
_cache_lock = threading.Lock()


def _cached(key, seconds, make):
    """make() once per key for `seconds`. Only a value is kept: a failure is tried again next time."""
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
    if hit and now - hit[0] < seconds:
        return hit[1]
    value = make()
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def clear_cache():
    """Forget the kept values (tests; a new data load shows at once)."""
    with _cache_lock:
        _cache.clear()


# ------------------------------------------------------------------ small helpers
def _day(value):
    """A date as the answers write it: 21-Dec-2025 ('' for none)."""
    return value.strftime("%d-%b-%Y") if isinstance(value, datetime.date) else ""


def _money(value):
    """An amount as the Ask page's tables write it: 16,547,240.00 (agent.format_value)."""
    return agent.format_value(decimal.Decimal(value or 0).quantize(decimal.Decimal("0.01")))[0]


def _number(value):
    return float(value or 0)


def _short_money(value):
    """An amount in short Indian words, as the charts write it (shortIndian): 6.4 Cr, 60.6 L, 12.5 K, 950.
    Cr = 1,00,00,000, L = 1,00,000, K = 1,000; at most 1 decimal, none from 100 up, a '.0' is dropped."""
    amount = decimal.Decimal(str(value or 0))
    size, unit = next((s, u) for s, u in ((10 ** 7, " Cr"), (10 ** 5, " L"), (10 ** 3, " K"), (1, ""))
                      if abs(amount) >= s or s == 1)
    scaled = amount / size
    places = decimal.Decimal("1") if abs(scaled) >= 100 else decimal.Decimal("0.1")
    scaled = scaled.quantize(places, rounding=decimal.ROUND_HALF_UP)
    text = f"{scaled:,f}"
    if text.endswith(".0"):
        text = text[:-2]
    return text + unit


def _plural(count, word):
    """'1 order', '10 orders'."""
    return f"{count:,} {word}{'' if count == 1 else 's'}"


def _a_year_before(day):
    """The same day one year before (29-Feb -> 28-Feb)."""
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


def _change(now, before, against):
    """{pct, direction, text} of now against before ('12.5% vs Sep 2026'); None when before is 0."""
    now, before = _number(now), _number(before)
    if not before:
        return None
    pct = round((now - before) * 100 / abs(before), 1)
    direction = "up" if pct > 0 else "down" if pct < 0 else "flat"
    # a very big jump reads better as "1,210x" than as "120,948.2%"
    size = f"{now / before:,.0f}x" if pct >= 1000 and before > 0 else f"{abs(pct):,.1f}%"
    return {"pct": pct, "direction": direction, "text": f"{size} vs {against}"}


def _rows(sql, params=(), max_rows=10):
    return warehouse.run_select_params(sql, params, max_rows)["rows"]


# ------------------------------------------------------------------ the numbers (KPI cards)
def _calendar():
    """Today in the data's calendar: the NOP sales month we are in, the last two complete ones and the FY."""
    rows = _rows(CALENDAR_SQL)
    if not rows:
        raise Missing(NOT_IN_CALENDAR)
    (today, month, month_start, month_end, fy, fy_label,
     last, last_start, last_end, before, before_start, before_end, fy_start) = rows[0]
    return {
        "today": today, "month": month, "month_start": month_start, "month_end": month_end,
        "fy": fy, "fy_label": fy_label, "fy_start": fy_start or today,
        "last": last, "last_start": last_start, "last_end": last_end,
        "before": before, "before_start": before_start, "before_end": before_end,
    }


def _sales(cal):
    """Net sales of the last two complete NOP months, and net sales / customers / products this FY so far and on
    the same dates a year before - one query, never a line after today."""
    today = cal["today"]
    fy = (cal["fy_start"], today)
    fy_before = (_a_year_before(cal["fy_start"]), _a_year_before(today))
    last = (cal["last_start"], cal["last_end"])
    before = (cal["before_start"], cal["before_end"])
    parts, params = [], []
    for template, period in ((SALES_PART, last), (SALES_PART, before), (SALES_PART, fy), (SALES_PART, fy_before),
                             (CUSTOMERS_PART, fy), (CUSTOMERS_PART, fy_before),
                             (PRODUCTS_PART, fy), (PRODUCTS_PART, fy_before)):
        parts.append(template)
        params += list(period)
    parts.append("(SELECT MIN(invoice_date) FROM fact_invoice_lines)")
    parts.append("(SELECT COUNT(*) FROM dim_customers WHERE customer_id <> -1)")
    starts = [day for day in (before[0], fy_before[0], last[0], fy[0]) if day]
    sql = "SELECT " + ",\n       ".join(parts) + SALES_FROM
    values = _rows(sql, params + [min(starts), today])[0]
    keys = ("last", "before", "fy", "fy_before", "customers", "customers_before", "products", "products_before",
            "data_from", "all_customers")
    return dict(zip(keys, values))


def _trends(cal):
    """{kpi key: [{label, value}, ...] oldest first, or None} for the last 6 complete NOP months up to the KPI's
    last complete month - one query, never a line after today. fy_sales is the running total of this FY at the
    end of each of those months that ends in this FY. Fewer than 2 points is no line: None."""
    if not cal["last_end"]:
        return {}
    rows = _rows(TREND_SQL, [cal["fy_start"], cal["last_end"], cal["fy_start"]])
    points = {"month_sales": [], "fy_sales": [], "customers": [], "products": []}
    for month, month_end, sales, customers, products, fy_total in rows:
        points["month_sales"].append({"label": month, "value": _number(sales)})
        points["customers"].append({"label": month, "value": _number(customers)})
        points["products"].append({"label": month, "value": _number(products)})
        if cal["fy_start"] and month_end and month_end >= cal["fy_start"]:
            points["fy_sales"].append({"label": month, "value": _number(fy_total)})
    return {key: line if len(line) >= 2 else None for key, line in points.items()}


def _top(cal):
    """{'customer': (name, sales), 'product': (name, sales)} of the last complete NOP month - one query; a kind
    without a sale in that month is not in it."""
    if not cal["last_start"]:
        return {}
    month = [cal["last_start"], cal["last_end"]]
    return {kind: (name or "", sales) for kind, _, name, sales in _rows(TOP_SQL, month + month)}


def _top_card(key, what, cal, top, month_sales):
    """The 'Top customer' / 'Top product' card: who sold most in the last complete NOP month, and its share of
    that month's net sales."""
    month = cal["last"] or "last month"
    card = {"key": key, "label": f"Top {what} {month}", "money": True, "change": None}
    if not top:
        return {**card, "name": "", "value": 0.0, "text": "-", "note": f"No sales in {month}", "facts": None}
    name, value = top
    share = _number(value) * 100 / _number(month_sales) if _number(month_sales) > 0 else None
    return {**card, "name": name, "value": _number(value), "text": f"INR {_money(value)}",
            "note": f"{_day(cal['last_start'])} to {_day(cal['last_end'])} (last complete NOP sales month)",
            "facts": [f"{share:,.1f}% of {month} sales"] if share is not None else None}


def _kpis():
    """The calendar and the eight KPI cards: {calendar, kpis}."""
    cal = _calendar()
    sales = _sales(cal)
    trends = _trends(cal)
    top = _top(cal)
    orders = _rows(OPEN_ORDERS_SQL)[0]
    stock = _rows(STOCK_SQL)
    today, data_from = cal["today"], sales["data_from"]

    def covered(start):
        """True when the data reaches back to this day (else a change against it would mislead)."""
        return bool(start and data_from and data_from <= start)

    fy_words = f"{cal['fy_label']} so far"
    fy_dates = f"{_day(cal['fy_start'])} to {_day(today)}"
    # '2627' -> the same dates of FY 2025-26
    same_dates = f"the same dates of FY 20{int(cal['fy'][:2]) - 1:02d}-{cal['fy'][:2]}" if cal["fy"] else "last year"
    fy_comparable = covered(_a_year_before(cal["fy_start"]))

    def fy_change(now, before):
        return _change(now, before, same_dates) if fy_comparable else None

    kpis = [
        {"key": "month_sales", "label": f"Net sales {cal['last'] or 'last month'}", "money": True,
         "value": _number(sales["last"]), "text": f"INR {_money(sales['last'])}",
         "note": f"{_day(cal['last_start'])} to {_day(cal['last_end'])} (last complete NOP sales month)",
         "change": _change(sales["last"], sales["before"], cal["before"]) if covered(cal["before_start"]) else None},
        {"key": "fy_sales", "label": f"Net sales {fy_words}", "money": True,
         "value": _number(sales["fy"]), "text": f"INR {_money(sales['fy'])}", "note": fy_dates,
         "change": fy_change(sales["fy"], sales["fy_before"])},
        # "total": all customers (never the Unknown row), so the card can draw active of all as a ring
        {"key": "customers", "label": "Active customers", "money": False,
         "value": sales["customers"], "text": f"{sales['customers']:,}", "total": int(sales["all_customers"] or 0),
         "note": f"of {sales['all_customers']:,} customers bought in {fy_words}",
         "change": fy_change(sales["customers"], sales["customers_before"])},
        {"key": "products", "label": "Products sold", "money": False,
         "value": sales["products"], "text": f"{sales['products']:,}",
         "note": f"different products invoiced in {fy_words}",
         "change": fy_change(sales["products"], sales["products_before"])},
        {"key": "open_orders", "label": "Open sales orders", "money": True,
         "value": _number(orders[2]), "text": f"INR {_money(orders[2])}",
         "note": f"{orders[0]:,} {'order' if orders[0] == 1 else 'orders'} ({orders[1]:,} lines) before GST, "
                 f"as of {_day(today)}",
         "change": None,
         "facts": [_plural(orders[0], "order"), _plural(orders[1], "line"),
                   f"INR {_short_money(orders[3])} incl. GST"]},
    ]
    if stock:
        report_date, value, items = stock[0]
        kpis.append({"key": "stock", "label": "Stock value", "money": True, "value": _number(value),
                     "text": f"INR {_money(value)}",
                     "note": f"Stock report of {_day(report_date)} ({items:,} items)", "change": None,
                     "facts": [_plural(items, "item"), f"Report {_day(report_date)}"]})
    else:
        kpis.append({"key": "stock", "label": "Stock value", "money": True, "value": 0.0, "text": "-",
                     "note": "No stock report dated up to today", "change": None, "facts": None})
    kpis.append(_top_card("top_customer", "customer", cal, top.get("customer"), sales["last"]))
    kpis.append(_top_card("top_product", "product", cal, top.get("product"), sales["last"]))
    for card in kpis:   # open orders, stock and the two top cards have no line (a count of today, one report)
        card["trend"] = trends.get(card["key"])
        card["ask"] = KPI_ASK[card["key"]].format(fy=cal["fy_label"] or "this FY")
        card.setdefault("facts", None)   # the small chips: only some cards have them
    calendar ={"today": _day(today), "month": cal["month"], "month_from": _day(cal["month_start"]),
                "month_to": _day(cal["month_end"]), "fy": cal["fy"], "fy_label": cal["fy_label"]}
    return {"calendar": calendar, "kpis": kpis}


# ------------------------------------------------------------------ the tables ("Our data")
def _tables():
    """The main ai_gold tables that exist: records (services.table_counts, the Data page's count) and dates."""
    counts = {t["name"]: t["rows"] for t in services.table_counts()}
    shown = [t for t in MAIN_TABLES if t[0] in counts]
    parts = []
    for name, _, column, _ in shown:
        if column:
            # the names are fixed here in the code, never typed by a person
            parts += [f"(SELECT MIN({column}) FROM {name})", f"(SELECT MAX({column}) FROM {name})"]
    if "fact_stock_ledger" in counts:
        parts.append("(SELECT COUNT(DISTINCT report_date) FROM fact_stock_ledger)")
    parts.append("CURDATE()")
    values = list(_rows("SELECT " + ", ".join(parts))[0])
    today = values.pop()
    reports = values.pop() if "fact_stock_ledger" in counts else 0
    tables = []
    for name, title, column, note in shown:
        first = last = None
        if column:
            first, last = values.pop(0), values.pop(0)
        if name == "fact_stock_ledger" and reports:
            note = f"{reports} stock {'report' if reports == 1 else 'reports'}: balances and movements"
        tables.append({"table": name, "name": title, "note": note, "rows": counts[name],
                       "rows_text": f"{counts[name]:,}", "from": _day(first), "to": _day(last),
                       "after_today": bool(last and today and last > today)})
    return tables


# ------------------------------------------------------------------ the connections
def _app_database():
    """The app's own database by name only: 'MySQL mi_app' (SQLite when there is no MySQL)."""
    db = settings.DATABASES["default"]
    if "mysql" in db.get("ENGINE", ""):
        return f"MySQL {db.get('NAME') or 'app database'}"
    return "SQLite (app database)"


def _check_ai_gold():
    warehouse.run_select("SELECT 1", max_rows=1)
    return "Reachable"


def _check_app_db():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return "Reachable"


def _check_collection(name):
    """'1,234 pieces' of one of our Qdrant collections; Missing when it was never built."""
    with store._qdrant_errors():
        client = store._client()
        if not client.collection_exists(name):
            raise Missing("Not built yet")
        points = client.count(name, exact=True).count
    if not points:
        raise Missing("Empty - not built yet")
    return f"{points:,} pieces"


def _collections():
    """[(key, name, what it holds, check)] of our two Qdrant collections - never the main project's nop_docs
    (collection_name() refuses it)."""
    from .lc import pdfs, vectorstore  # imported here: LangChain's import is slow

    found = []
    for key, module, what in (("docs", vectorstore, "SQL notes for the AI (RAG)"),
                              ("pdfs", pdfs, "Company PDFs for the AI (RAG)")):
        try:
            name = module.collection_name()
        except vectorstore.WrongCollection:
            found.append((key, "Qdrant", what, None))
            continue
        found.append((key, f"Qdrant {name}", what, name))
    return found


def _status(key, name, what, check):
    """One line of "Connected": {key, name, what, ok, note}. A failure's own words go to the log only."""
    try:
        note = check()
        ok = True
    except Missing as exc:
        note, ok = str(exc), False
    except Exception as exc:  # any failure: red, with a safe note (never a host, user or message)
        log.warning("Home: the check of %s failed: %s", name, type(exc).__name__)
        note, ok = "Not reachable right now", False
    return {"key": key, "name": name, "what": what, "ok": ok, "note": note}


def _connections():
    lines = [
        _status("ai_gold", f"MySQL {warehouse.database_name()}", "Company data (read-only)", _check_ai_gold),
        _status("app_db", _app_database(), "The app's chats, history and users", _check_app_db),
    ]
    for key, name, what, collection in _collections():
        if collection is None:
            lines.append({"key": key, "name": name, "what": what, "ok": False, "note": "Wrong collection setting"})
        else:
            lines.append(_status(key, name, what, lambda c=collection: _check_collection(c)))
    key_set = bool(os.getenv("GROQ_API_KEY", "").strip())  # only whether it is there - never the key itself
    backup = agent.fallback_model_name()
    lines.append({"key": "groq", "name": "Groq AI", "ok": key_set,
                  "what": agent.model_name() + (f" (backup {backup})" if backup else ""),
                  "note": "Key set" if key_set else "Key not set"})
    return lines


# ------------------------------------------------------------------ the user's usage
def usage(user, now=None):
    """The user's own questions and tokens today (India time), and the app's AI tokens against the daily limit of
    the main model (usage.ai_usage - the same counting as History's usage box): the bar is Groq's own count, the
    rolling last 24 hours of the whole app; the daily period (it resets 24 hours after it started) is named too."""
    now = now or timezone.now()
    midnight = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    mine = Question.objects.filter(user=user, created_at__gte=midnight, created_at__lte=now)         .aggregate(n=Count("id"), tokens=Sum("total_tokens"))
    box = ai_usage(now)
    main = next((row for row in box["rows"] if row["model"] == agent.model_name()), box["rows"][0])
    limit = agent.daily_token_limit()
    rolling = int(main["rolling"].replace(",", ""))  # ai_usage writes it as text: '143,064'
    return {
        "questions_today": mine["n"] or 0,
        "my_tokens_today": mine["tokens"] or 0,
        "my_tokens_text": f"{mine['tokens'] or 0:,}",
        "model": main["model"],
        "tokens_24h": main["rolling"], "limit": main["limit"], "pct": round(rolling * 100 / limit),
        "period_tokens": main["tokens"], "period_pct": main["pct"], "questions_left": main["questions_left"],
        "period_end": dateformat.format(timezone.localtime(box["period_end"]), "D d-M g:i A") if box["period_end"] else "",
    }


def recent(user):
    """The user's own last 5 questions, newest first, as History and the chat list show them: not in a deleted
    chat (visible()) and not an edited one (replaced by its newer version). Only this user's - never kept."""
    questions = (user.questions.visible().filter(replaced_by__isnull=True)
                 .order_by("-created_at", "-pk")[:RECENT_QUESTIONS])
    return [{"id": saved.pk, "text": saved.text, "status": saved.status,
             "when": dateformat.format(timezone.localtime(saved.created_at), "d-M g:i A"),
             "url": f"/q/{saved.pk}"}
            for saved in questions]


# ------------------------------------------------------------------ the whole reply
def _part(make, failed=PART_FAILED):
    """(value, '') or (None, a safe message) - one part failing never stops the others."""
    try:
        return make(), ""
    except (warehouse.WarehouseUnavailable, warehouse.QueryError) as exc:
        log.warning("Home: the NOP data could not be read: %s", exc)
        return None, MYSQL_DOWN
    except Missing as exc:
        return None, str(exc)
    except Exception:  # a bug or a surprise in one part: logged, the page still shows the rest
        log.exception("Home: a part failed")
        return None, failed


def home(user):
    """Everything the Home page shows (see the top of this file)."""
    today = datetime.date.today()
    numbers, kpi_error = _part(lambda: _cached(("kpis", today), CACHE_SECONDS, _kpis))
    tables, tables_error = _part(lambda: _cached(("tables", today), CACHE_SECONDS, _tables))
    connections, connections_error = _part(lambda: _cached(("connections",), CHECK_SECONDS, _connections))
    mine, usage_error = _part(lambda: usage(user))
    asked, recent_error = _part(lambda: recent(user))
    return {
        "first_name": user.first_name.strip() or user.get_username(),
        "today": _day(timezone.localdate()),
        "calendar": numbers["calendar"] if numbers else None,
        "kpis": numbers["kpis"] if numbers else [], "kpi_error": kpi_error,
        "tables": tables or [], "tables_error": tables_error,
        "connections": connections or [], "connections_error": connections_error,
        "usage": mine, "usage_error": usage_error,
        "recent": asked or [], "recent_error": recent_error,
        "model": agent.model_name(),
    }
