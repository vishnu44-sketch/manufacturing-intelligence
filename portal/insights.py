"""The Insights page (/api/insights, every signed-in user): the results of the ML step in one read-only reply.

The ML step (ml/run_ml.py) writes its results into ss_gold as ml_* tables; this module only READS them, with
fixed SQL through warehouse.run_select_params as the read-only user (no AI call, nothing written):

ready      True when every ml_* table is there and ml_run_log has a run
run_at     when the latest run wrote its results ('2026-11-17T16:00:00'); data_to = the newest invoice date
           the models used ('2026-10-31') - the results are 'as of' that date, not today
forecast   the model, its backtest MAPE %, the last 12 complete sales months (actual net sales), the forecast of
           the next 12 sales months with an 80 % range (12 'months' rows), and the next 3 months of the top 10
           products (one 'products' row per product and month)
risk       customers per risk level, and the 25 with the highest risk score
segments   the customer groups: customers, sales, average recency and invoices
alerts     alerts per type, and 30 of them: the strongest of each type in turn (scores compare only within one
           type), shown by type and score
pairs      the 20 product pairs with the highest lift
stockout   items per status, and the 30 that run out soonest (items with no recent sales left out)

Before the first ML run (no ml_* tables) the reply is {"ready": false, "run_at": null, "data_to": null} with
empty parts - never a 500. A part that cannot be read stays empty and "error" says so. It does not use
warehouse.schema() (cached per process, so it would not see tables made after the site started).
"""
import datetime
import decimal
import logging

from .rag import warehouse

log = logging.getLogger(__name__)

ML_TABLES = ("ml_run_log", "ml_sales_forecast", "ml_customer_risk", "ml_customer_segments", "ml_invoice_alerts",
             "ml_product_pairs", "ml_stock_runout")
RISK_LEVELS = ("High", "Medium", "Low")
ALERT_TYPES = ("Unusual price", "Unusual quantity", "Large credit note")
STOCK_STATUSES = ("Out of stock", "Under 30 days", "Under 90 days", "OK", "No recent sales")
MYSQL_DOWN = "The company data (MySQL) can't be read right now - please try again in a minute."
PART_FAILED = "Some insights can't be read right now."


def empty():
    """The reply before the first ML run: ready false and every part empty."""
    return {
        "ready": False, "run_at": None, "data_to": None, "error": None,
        "forecast": {"model": None, "mape_pct": None, "history": [], "months": [], "products": []},
        "risk": {"counts": {level: 0 for level in RISK_LEVELS}, "customers": []},
        "segments": [],
        "alerts": {"counts": {kind: 0 for kind in ALERT_TYPES}, "items": []},
        "pairs": [],
        "stockout": {"counts": {status: 0 for status in STOCK_STATUSES}, "items": []},
    }


def _value(value):
    """A MySQL value as JSON: Decimal -> number, date -> 'YYYY-MM-DD', datetime -> 'YYYY-MM-DDTHH:MM:SS'."""
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, datetime.datetime):
        return value.replace(microsecond=0).isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    return value


def _rows(sql, params=(), max_rows=500):
    """[{column: value}, ...] of one fixed SELECT, read-only."""
    result = warehouse.run_select_params(sql, params, max_rows)
    return [{c: _value(v) for c, v in zip(result["columns"], row)} for row in result["rows"]]


def _ml_tables():
    """The ml_* tables of ss_gold this user can see (information_schema, read fresh each time)."""
    rows = _rows("SELECT table_name AS name FROM information_schema.tables "
                 "WHERE table_schema = %s AND LEFT(table_name, 3) = 'ml_'", (warehouse.database_name(),))
    return {str(r["name"]).lower() for r in rows}


def _counts(sql, keys):
    counts = {key: 0 for key in keys}
    for row in _rows(sql):
        counts[row["k"]] = int(row["n"])
    return counts


def _forecast(data_to):
    months = _rows("SELECT sales_month AS month, period_start, period_end, forecast_inr AS forecast, "
                   "low_inr AS low, high_inr AS high, model_name, mape_pct FROM ml_sales_forecast "
                   "WHERE level = 'TOTAL' ORDER BY period_start")
    products = _rows("SELECT product_code, product_description, sales_month AS month, forecast_inr AS forecast, "
                     "low_inr AS low, high_inr AS high FROM ml_sales_forecast "
                     "WHERE level = 'PRODUCT' ORDER BY forecast_inr DESC")
    history = []
    if data_to:
        # the last 12 complete sales months up to data_to (only the last ~13 months of invoices are read)
        since = datetime.date.fromisoformat(data_to) - datetime.timedelta(days=400)
        history = _rows(
            "SELECT c.sales_month AS month, SUM(il.net_taxable_value) AS actual "
            "FROM fact_invoice_lines il JOIN dim_calendar c ON c.date_id = il.invoice_date_id "
            "WHERE il.invoice_date >= %s AND il.invoice_date <= %s AND c.sales_period_end <= %s "
            "GROUP BY c.sales_month, c.sales_period_start ORDER BY c.sales_period_start DESC LIMIT 12",
            (since.isoformat(), data_to, data_to))[::-1]
    first = months[0] if months else {}
    return {"model": first.get("model_name"), "mape_pct": first.get("mape_pct"),
            "history": [{"month": h["month"], "actual": h["actual"]} for h in history],
            "months": [{k: m[k] for k in ("month", "period_start", "period_end", "forecast", "low", "high")}
                       for m in months],
            "products": products}


def _risk():
    customers = _rows(
        "SELECT customer_name, risk_score, risk_level, reason, last_invoice_date, sales_last_3m_inr AS sales_last_3m, "
        "sales_prev_3m_inr AS sales_prev_3m, change_pct FROM ml_customer_risk "
        "ORDER BY risk_score DESC, normal_3m_inr DESC LIMIT 25")
    counts = _counts("SELECT risk_level AS k, COUNT(*) AS n FROM ml_customer_risk GROUP BY risk_level", RISK_LEVELS)
    return {"counts": counts, "customers": customers}


def _segments():
    rows = _rows("SELECT segment_name, COUNT(*) AS customers, SUM(sales_inr) AS sales_inr, "
                 "AVG(recency_days) AS avg_recency_days, AVG(invoices) AS avg_invoices "
                 "FROM ml_customer_segments GROUP BY segment_no, segment_name ORDER BY segment_no")
    for row in rows:
        row["customers"] = int(row["customers"])
        row["avg_recency_days"] = round(row["avg_recency_days"], 1) if row["avg_recency_days"] is not None else None
        row["avg_invoices"] = round(row["avg_invoices"], 1) if row["avg_invoices"] is not None else None
    return rows


def _alerts():
    counts = _counts("SELECT alert_type AS k, COUNT(*) AS n FROM ml_invoice_alerts GROUP BY alert_type", ALERT_TYPES)
    # the strongest of each type in turn (1st price, 1st quantity, 1st credit note, 2nd price, ...), 30 in all
    items = _rows(
        "SELECT alert_type, invoice_number, invoice_date, customer_name, product_code, value_inr, typical_inr, "
        "reason FROM (SELECT a.*, ROW_NUMBER() OVER (PARTITION BY alert_type ORDER BY score DESC, alert_id) AS turn "
        "FROM ml_invoice_alerts a) x ORDER BY turn, alert_id LIMIT 30")
    order = {kind: i for i, kind in enumerate(ALERT_TYPES)}
    items.sort(key=lambda item: order.get(item["alert_type"], len(order)))   # stable: score order stays
    return {"counts": counts, "items": items}


def _pairs():
    return _rows("SELECT product_a_code, product_a_description, product_b_code, product_b_description, "
                 "orders_together, confidence_pct, lift FROM ml_product_pairs "
                 "ORDER BY lift DESC, orders_together DESC LIMIT 20")


def _stockout():
    counts = _counts("SELECT status AS k, COUNT(*) AS n FROM ml_stock_runout GROUP BY status", STOCK_STATUSES)
    items = _rows(
        "SELECT product_code, product_description, stock_qty, avg_daily_sales_qty, days_left, runout_date, status "
        "FROM ml_stock_runout WHERE status <> 'No recent sales' "
        "ORDER BY status = 'Out of stock' DESC, days_left IS NULL, days_left, product_code LIMIT 30")
    return {"counts": counts, "items": items}


def build():
    """The whole Insights reply (see the module text). Never raises for a MySQL problem."""
    reply = empty()
    try:
        tables = _ml_tables()
        if "ml_run_log" not in tables:
            return reply
        runs = _rows("SELECT run_at, data_to FROM ml_run_log WHERE run_id = (SELECT MAX(run_id) FROM ml_run_log) "
                     "ORDER BY run_at DESC LIMIT 1")
    except (warehouse.WarehouseUnavailable, warehouse.QueryError) as exc:
        log.warning("Insights: the ML results could not be read: %s", exc)
        reply["error"] = MYSQL_DOWN
        return reply
    if not runs:
        return reply
    reply["run_at"], reply["data_to"] = runs[0]["run_at"], runs[0]["data_to"]
    reply["ready"] = all(name in tables for name in ML_TABLES)
    parts = [("forecast", "ml_sales_forecast", lambda: _forecast(reply["data_to"])),
             ("risk", "ml_customer_risk", _risk), ("segments", "ml_customer_segments", _segments),
             ("alerts", "ml_invoice_alerts", _alerts), ("pairs", "ml_product_pairs", _pairs),
             ("stockout", "ml_stock_runout", _stockout)]
    for key, table, make in parts:
        if table not in tables:
            continue
        try:
            reply[key] = make()
        except (warehouse.WarehouseUnavailable, warehouse.QueryError) as exc:
            log.warning("Insights: %s could not be read: %s", key, exc)
            reply["error"] = PART_FAILED
        except Exception:   # a bug or a surprise in one part: logged, the page still shows the rest
            log.exception("Insights: the part %s failed", key)
            reply["error"] = PART_FAILED
    return reply
