"""The ML step (ml/) and the Insights API - on tiny fake frames, never a real MySQL write.

- each scenario's core function: the forecast, the risk score, the customer groups, the unusual invoices,
  the bought-together pairs and the stock run-out
- the runner writes only ml_* tables inside ss_gold (anything else is refused before a statement runs)
- /api/insights: sign-in needed, ready=false before the first run, the full shape with fake rows
"""
import datetime
from contextlib import contextmanager
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from ml import customer_risk, db, forecast, invoice_alerts, product_pairs, segments, stock_runout
from portal import insights
from portal.rag import warehouse
from portal.tests.test_views_ask import api_get, api_post

DATA_TO = datetime.date(2026, 10, 31)


# ------------------------------------------------------------------ forecast
def test_forecast_gives_twelve_months_inside_their_range():
    months = np.arange(30)
    season = 1 + 0.15 * (months % 12 == 10) - 0.08 * (months % 12 == 2)      # a March peak, a July dip
    values = 100_000_000 * (1.17 ** (months / 12)) * season
    result = forecast.forecast_total(values)
    assert forecast.HORIZON == 12 and forecast.PRODUCT_HORIZON == 3
    assert len(result["forecast"]) == len(result["low"]) == len(result["high"]) == 12
    for low, value, high in zip(result["low"], result["forecast"], result["high"]):
        assert 0 <= low <= value <= high
    widths = [(high - low) / value for low, value, high in zip(result["low"], result["forecast"], result["high"])]
    assert all(a < b for a, b in zip(widths, widths[1:]))                       # wider for each month further ahead
    assert result["mape_pct"] < 10
    assert result["model"] in {name for name, _, _ in forecast.MODELS}
    assert len(result["backtest"]["actual"]) == len(result["backtest"]["error_pct_by_horizon"]) == 6


def test_forecast_months_come_from_the_calendar_and_go_on_past_its_end():
    calendar = pd.DataFrame({"full_date": [datetime.date(2026, 11, 1)], "sales_month": ["Nov 2026"],
                             "sales_period_start": [datetime.date(2026, 10, 21)],
                             "sales_period_end": [datetime.date(2026, 11, 20)]})
    months = forecast.next_months(calendar, pd.Timestamp("2026-10-20"))
    assert [m[0] for m in months] == ["Nov 2026", "Dec 2026", "Jan 2027", "Feb 2027", "Mar 2027", "Apr 2027",
                                      "May 2027", "Jun 2027", "Jul 2027", "Aug 2027", "Sep 2027", "Oct 2027"]
    assert months[1][1] == pd.Timestamp("2026-11-21") and months[2][2] == pd.Timestamp("2027-01-20")
    assert months[-1][1:] == (pd.Timestamp("2027-09-21"), pd.Timestamp("2027-10-20"))
    assert [m[0] for m in forecast.next_months(calendar, pd.Timestamp("2026-10-20"), 3)] == [
        "Nov 2026", "Dec 2026", "Jan 2027"]


def test_the_run_gives_12_total_months_and_3_months_of_the_top_products():
    """30 complete sales months (May 2024 .. Oct 2026) of 12 products: 12 TOTAL rows (horizon 1-12), then the
    top 10 products for the first 3 months only (horizon 1-3), month by month."""
    days = pd.date_range("2024-04-21", "2026-10-20")
    rng = np.random.default_rng(7)
    lines = pd.DataFrame({"invoice_date": np.repeat(days, 12), "product_id": np.tile(np.arange(1, 13), len(days)),
                          "net_taxable_value": rng.uniform(900, 1100, len(days) * 12)})
    start = [pd.Timestamp(d.year, d.month, 21) - pd.DateOffset(months=0 if d.day >= 21 else 1) for d in days]
    calendar = pd.DataFrame({"full_date": days, "sales_period_start": start})
    calendar["sales_period_end"] = [s + pd.DateOffset(months=1) - pd.Timedelta(days=1) for s in start]
    calendar["sales_month"] = calendar["sales_period_end"].dt.strftime("%b %Y")
    products = pd.DataFrame({"product_id": range(1, 13), "product_code": [f"FG{i:05d}" for i in range(1, 13)],
                             "product_description": [f"Item {i}" for i in range(1, 13)]})
    inputs = {"lines": lines, "calendar": calendar, "products": products, "data_from": datetime.date(2024, 4, 21)}

    rows, metric, summary = forecast.run(inputs, datetime.date(2026, 10, 31), datetime.datetime(2026, 11, 18),
                                         lambda frame, name: None)

    total = [r for r in rows if r["level"] == "TOTAL"]
    product = [r for r in rows if r["level"] == "PRODUCT"]
    assert [r["horizon_months"] for r in total] == list(range(1, 13))
    assert (total[0]["sales_month"], total[-1]["sales_month"]) == ("Nov 2026", "Oct 2027")
    assert all(0 <= r["low_inr"] <= r["forecast_inr"] <= r["high_inr"] for r in rows)
    assert len(product) == 30 and len({r["product_id"] for r in product}) == 10
    assert [r["horizon_months"] for r in product] == [1] * 10 + [2] * 10 + [3] * 10
    assert [r["sales_month"] for r in product[::10]] == ["Nov 2026", "Dec 2026", "Jan 2027"]
    assert [r["forecast_id"] for r in rows] == list(range(1, 43))
    assert metric[0] == "backtest MAPE % (last 6 months)" and "Oct 2027" in summary[-1]
    # the training period is written on every row (18-Nov, "is that trained for 12 months?" - no: 30 months)
    assert {(r["train_from_month"], r["train_to_month"], r["train_months"]) for r in rows} == {
        ("May 2024", "Oct 2026", 30)}
    assert summary[0].startswith("trained on 30 complete sales months (May 2024 .. Oct 2026)")
    assert forecast.trained_on(inputs, DATA_TO, rows) == (
        "30 complete sales months May 2024 - Oct 2026 (net sales per sales month)")
    assert set(rows[0]) <= set(forecast.TABLE.column_names)               # every value has its column


def test_only_complete_sales_months_are_used():
    days = pd.date_range("2024-04-02", "2024-07-31")
    lines = pd.DataFrame({"invoice_date": days, "net_taxable_value": 1.0})
    calendar = pd.DataFrame({"full_date": days})
    # the sales month of a day starts on the 21st of its month (from the 21st on) or of the month before
    start = [pd.Timestamp(d.year, d.month, 21) - pd.DateOffset(months=0 if d.day >= 21 else 1) for d in days]
    calendar["sales_period_start"] = start
    calendar["sales_period_end"] = [s + pd.DateOffset(months=1) - pd.Timedelta(days=1) for s in start]
    calendar["sales_month"] = calendar["sales_period_end"].dt.strftime("%b %Y")
    months = forecast.monthly_sales(lines, calendar, datetime.date(2024, 4, 2), datetime.date(2024, 7, 31))
    complete = dict(zip(months["sales_month"], months["complete"]))
    assert complete == {"Apr 2024": False, "May 2024": True, "Jun 2024": True, "Jul 2024": True, "Aug 2024": False}


# ------------------------------------------------------------------ customers at risk
def _customer(customer_id, last_day, every=10, amount=10_000.0, first_day="2024-06-01"):
    days = pd.date_range(first_day, last_day, freq=f"{every}D")
    lines = pd.DataFrame({"customer_id": customer_id, "invoice_date": days, "document_type": "INVOICE",
                          "invoice_number": [f"I{customer_id}-{i}" for i in range(len(days))],
                          "net_taxable_value": amount})
    orders = pd.DataFrame({"customer_id": customer_id, "so_number": range(len(days)), "order_date": days,
                           "status": "Closed"})
    return lines, orders


def test_a_customer_who_stopped_is_riskier_than_a_steady_one():
    steady = _customer(1, "2026-10-30")
    stopped = _customer(2, "2026-05-31")
    unknown = _customer(-1, "2026-10-30")
    lines = pd.concat([steady[0], stopped[0], unknown[0]])
    orders = pd.concat([steady[1], stopped[1], unknown[1]])
    scored = customer_risk.score_risk(customer_risk.customer_features(lines, orders, DATA_TO)).set_index("customer_id")
    assert -1 not in scored.index
    assert scored.loc[2, "risk_score"] > scored.loc[1, "risk_score"]
    assert scored.loc[2, "risk_level"] == "High" and scored.loc[1, "risk_level"] == "Low"
    assert "No sales in the last 3 months" in scored.loc[2, "reason"]
    assert scored.loc[1, "reason"] == "Buying as usual"


def test_a_short_history_is_not_scored():
    few = _customer(3, "2026-10-30", every=60, first_day="2026-08-01")   # 2 invoices only
    scored = customer_risk.score_risk(customer_risk.customer_features(few[0], few[1], DATA_TO))
    assert scored.empty


# ------------------------------------------------------------------ customer groups
def test_segments_give_named_groups():
    rng = np.random.default_rng(1)
    groups = [(10, 200, 50_000_000, 900), (30, 30, 5_000_000, 700), (200, 3, 300_000, 600),
              (40, 2, 200_000, 60), (600, 2, 100_000, 800)]   # recency, invoices, sales, tenure
    rows = []
    for g, (rec, inv, sales, ten) in enumerate(groups):
        for i in range(12):
            rows.append({"customer_id": g * 100 + i, "recency_days": rec * rng.uniform(0.9, 1.1),
                         "invoices": max(1, int(inv * rng.uniform(0.9, 1.1))), "sales_inr": sales * rng.uniform(0.9, 1.1),
                         "tenure_days": ten * rng.uniform(0.95, 1.05)})
    grouped = segments.segment_customers(pd.DataFrame(rows))
    names = set(grouped["segment_name"])
    assert 4 <= len(names) <= 5 and names <= set(segments.NAME_ORDER)
    by_id = grouped.set_index("customer_id")["segment_name"]
    assert by_id[0] == "Big regular buyers" and by_id[400] == "Lapsed" and by_id[300] == "New customers"
    assert set(grouped["segment_no"]) <= {1, 2, 3, 4, 5}


# ------------------------------------------------------------------ unusual invoices
def _line(i, product_id=7, price=100.0, quantity=2.0, document_type="INVOICE", note=None, invoice=None):
    return {"invoice_line_id": i, "document_type": document_type, "invoice_number": invoice or f"INV{i}",
            "note_number": note, "invoice_date": datetime.date(2026, 5, 1), "customer_id": 1,
            "product_id": product_id, "quantity": quantity, "unit_price": price,
            "taxable_value": price * quantity, "net_taxable_value": price * quantity, "issue_reason": None}


def test_an_obvious_price_outlier_is_flagged():
    lines = pd.DataFrame([_line(i, price=100.0 + (i % 3)) for i in range(12)] + [_line(99, price=300.0)])
    alerts = invoice_alerts.find_alerts(lines)
    prices = [a for a in alerts if a["alert_type"] == "Unusual price"]
    assert len(prices) == 1 and prices[0]["row"].invoice_number == "INV99"
    assert prices[0]["value_inr"] == 300.0 and abs(prices[0]["typical_inr"] - 101) < 1
    assert "above" in prices[0]["reason"]


def test_a_huge_quantity_and_a_large_credit_note_are_flagged():
    lines = [_line(i, quantity=2.0) for i in range(12)] + [_line(50, quantity=40.0)]
    lines += [_line(60 + i, document_type="CREDIT_NOTE", note=f"CN{i}", price=10.0, quantity=1.0) for i in range(10)]
    lines += [_line(80, document_type="CREDIT_NOTE", note="CN-BIG", price=150.0, quantity=1.0, invoice="INV3")]
    kinds = {a["alert_type"]: a for a in invoice_alerts.find_alerts(pd.DataFrame(lines))}
    assert kinds["Unusual quantity"]["row"].invoice_number == "INV50"
    assert kinds["Large credit note"]["note_number"] == "CN-BIG"
    assert "takes back" in kinds["Large credit note"]["reason"]


# ------------------------------------------------------------------ bought together
def test_pairs_support_confidence_and_lift():
    baskets = pd.DataFrame([("o1", 1), ("o1", 2), ("o2", 1), ("o2", 2), ("o3", 1), ("o3", 3), ("o4", 2), ("o5", 3)],
                           columns=["order_key", "product_id"])
    pairs, n = product_pairs.pair_stats(baskets, min_orders=1)
    assert n == 1 and len(pairs) == 1          # 1+3 is bought together less than by chance (lift < 1)
    pair = pairs.iloc[0]
    assert (pair.product_a_id, pair.product_b_id, pair.orders_together) == (1, 2, 2)
    assert pair.support_pct == pytest.approx(40.0)
    assert pair.confidence_pct == pytest.approx(200 / 3)
    assert pair.lift == pytest.approx(2 * 5 / 9)


def test_an_order_is_its_number_and_financial_year():
    orders = pd.DataFrame({"so_number": [1, 1, 1, 2], "product_id": [5, 6, 7, 8], "status": ["Closed", "Closed", "Open", "Canceled"],
                           "order_date": [datetime.date(2025, 5, 1), datetime.date(2025, 6, 1), datetime.date(2026, 5, 1),
                                          datetime.date(2025, 5, 1)]})
    baskets = product_pairs.order_baskets(orders)
    assert sorted(baskets["order_key"].unique()) == ["1/2025", "1/2026"]      # SO 2 was cancelled
    assert sorted(baskets[baskets["order_key"] == "1/2025"]["product_id"]) == [5, 6]


# ------------------------------------------------------------------ stock running out
def test_runout_days_left_and_status():
    report = datetime.date(2026, 10, 31)
    stock = pd.DataFrame({"report_date": report, "product_id": [1, 2, 3, 4, 5],
                          "src_product_code": ["A", "B", "C", "D", "E"], "item_description": "x",
                          "stock_qty": [Decimal("0"), Decimal("30"), Decimal("50"), Decimal("100"), Decimal("9")]})
    sold = {1: 90, 2: 180, 3: 90, 4: 90}       # quantity sold in the last 90 days; item 5 sold nothing
    lines = pd.DataFrame([{"product_id": p, "invoice_date": datetime.date(2026, 10, 1), "net_quantity": q}
                          for p, q in sold.items()]
                         + [{"product_id": 5, "invoice_date": datetime.date(2026, 6, 1), "net_quantity": 50}])
    result = stock_runout.runout(stock_runout.stock_speed(stock, lines, report)).set_index("product_id")
    assert list(result["status"]) == ["Out of stock", "Under 30 days", "Under 90 days", "OK", "No recent sales"]
    assert result.loc[2, "days_left"] == 15.0 and result.loc[2, "avg_daily_sales_qty"] == 2.0
    assert result.loc[2, "runout_date"] == pd.Timestamp("2026-11-15")
    assert pd.isna(result.loc[5, "days_left"]) and pd.isna(result.loc[5, "runout_date"])


# ------------------------------------------------------------------ the runner writes only ml_* in ss_gold
@pytest.mark.parametrize("database, table", [
    ("ss_gold", "fact_invoice_lines"), ("ss_gold", "dim_customers"), ("other_db", "ml_sales_forecast"),
    ("ss_gold", "ml_x`; DROP TABLE fact_invoice_lines; --"), ("ss_gold", "ML_UPPER"), (None, "ml_x")])
def test_the_runner_refuses_other_tables_and_databases(database, table):
    with pytest.raises(db.WriteRefused):
        db.check_target(database, table)


def test_a_result_table_must_be_an_ml_table():
    with pytest.raises(db.WriteRefused):
        db.MlTable("fact_invoice_lines", "x", [("a", "INT", "x")], primary_key=["a"])
    assert db.check_target("ss_gold", "ml_sales_forecast") is None


class FakeEngine:
    """Records every statement; SELECT DATABASE() answers `database`."""

    def __init__(self, database):
        self.database, self.statements = database, []

    @contextmanager
    def begin(self):
        engine = self

        class Cursor:
            def execute(self, statement):
                engine.statements.append(statement)

            def close(self):
                pass

        class Conn:
            connection = type("Raw", (), {"cursor": lambda self: Cursor()})()

            def execute(self, statement, *args):
                engine.statements.append(str(statement))
                return type("R", (), {"scalar": lambda self: engine.database})()

            def exec_driver_sql(self, statement, data):
                engine.statements.append(statement)

        yield Conn()


def test_nothing_is_dropped_on_another_database():
    engine = FakeEngine("company_erp")
    with pytest.raises(db.WriteRefused):
        db.write_results([(forecast.TABLE, [])], [], engine)
    assert not any("DROP" in s or "CREATE" in s for s in engine.statements)


def test_a_non_ml_table_is_refused_before_anything_runs():
    engine = FakeEngine("ss_gold")
    table = type("T", (), {"name": "fact_invoice_lines"})()
    with pytest.raises(db.WriteRefused):
        db.write_results([(table, [])], [], engine)
    assert engine.statements == []


def test_another_gold_database_in_env_is_refused(monkeypatch):
    monkeypatch.setenv("AI_GOLD_DATABASE", "other_db")
    with pytest.raises(db.WriteRefused):
        db.gold_engine()


def test_every_ml_table_and_column_has_a_comment():
    for table in [db.RUN_LOG, forecast.TABLE, customer_risk.TABLE, segments.TABLE, invoice_alerts.TABLE,
                  product_pairs.TABLE, stock_runout.TABLE]:
        assert table.name.startswith("ml_") and table.comment
        assert all(comment for _, _, comment in table.columns)
        assert "COMMENT=" in table.create_sql() and "`ss_gold`." in table.create_sql()
    contract = {"ml_run_log": ["run_id", "scenario", "rows_written", "metric_name", "metric_value", "seconds", "data_to", "run_at",
                               "trained_on"],
                "ml_sales_forecast": ["forecast_id", "level", "product_id", "product_code", "product_description", "sales_month",
                                      "period_start", "period_end", "forecast_inr", "low_inr", "high_inr", "model_name",
                                      "mape_pct", "train_from_month", "train_to_month", "train_months", "data_to", "run_at"],
                "ml_customer_risk": ["customer_id", "customer_name", "risk_score", "risk_level", "reason", "last_invoice_date",
                                     "days_since_last_invoice", "sales_last_3m_inr", "sales_prev_3m_inr", "change_pct",
                                     "invoices_last_12m", "lifetime_sales_inr", "run_at"],
                "ml_customer_segments": ["customer_id", "customer_name", "segment_no", "segment_name", "recency_days",
                                         "invoices", "sales_inr", "first_invoice_date", "last_invoice_date", "run_at"],
                "ml_invoice_alerts": ["alert_id", "alert_type", "invoice_number", "invoice_date", "customer_id",
                                      "customer_name", "product_code", "product_description", "value_inr", "typical_inr",
                                      "score", "reason", "run_at"],
                "ml_product_pairs": ["product_a_code", "product_a_description", "product_b_code", "product_b_description",
                                     "orders_together", "support_pct", "confidence_pct", "lift", "run_at"],
                "ml_stock_runout": ["product_id", "product_code", "product_description", "report_date", "stock_qty",
                                    "avg_daily_sales_qty", "days_left", "runout_date", "status", "run_at"]}
    tables = {t.name: t for t in [db.RUN_LOG, forecast.TABLE, customer_risk.TABLE, segments.TABLE,
                                  invoice_alerts.TABLE, product_pairs.TABLE, stock_runout.TABLE]}
    for name, columns in contract.items():
        assert set(columns) <= set(tables[name].column_names), name


# ------------------------------------------------------------------ /api/insights
class FakeWarehouse:
    """Answers the fixed SQL of insights.py from fake rows; `tables` = the ml_* tables that exist."""

    def __init__(self, tables=()):
        self.tables, self.calls = list(tables), []

    def __call__(self, sql, params=(), max_rows=500):
        self.calls.append(sql)
        answers = [
            ("information_schema.tables", ["name"], [[t] for t in self.tables]),
            ("FROM ml_run_log", ["run_at", "data_to"], [[datetime.datetime(2026, 11, 17, 16, 0), datetime.date(2026, 10, 31)]]),
            ("level = 'TOTAL'", ["month", "period_start", "period_end", "forecast", "low", "high", "model_name", "mape_pct"],
             [["Nov 2026", datetime.date(2026, 10, 21), datetime.date(2026, 11, 20), Decimal("535000000.00"),
               Decimal("498000000.00"), Decimal("571000000.00"), "Holt-Winters", Decimal("4.16")],
              ["Dec 2026", datetime.date(2026, 11, 21), datetime.date(2026, 12, 20), Decimal("520000000.00"),
               Decimal("481000000.00"), Decimal("559000000.00"), "Holt-Winters", Decimal("4.16")]]),
            ("level = 'PRODUCT'", ["product_code", "product_description", "month", "forecast", "low", "high"],
             [["FG01484", "Pump", "Nov 2026", Decimal("16500000.00"), Decimal("14300000.00"), Decimal("18800000.00")]]),
            ("FROM fact_invoice_lines", ["month", "actual"],
             [["Oct 2026", Decimal("517494500.00")], ["Sep 2026", Decimal("472683500.00")]]),
            ("GROUP BY risk_level", ["k", "n"], [["High", 118], ["Medium", 107], ["Low", 633]]),
            ("FROM ml_customer_risk", ["customer_name", "risk_score", "risk_level", "reason", "last_invoice_date",
                                       "sales_last_3m", "sales_prev_3m", "change_pct"],
             [["Aurora Fluid Power Limited", Decimal("100.00"), "High", "No sales in the last 3 months",
               datetime.date(2026, 7, 17), Decimal("0.00"), Decimal("1200000.00"), Decimal("-100.00")]]),
            ("FROM ml_customer_segments", ["segment_name", "customers", "sales_inr", "avg_recency_days", "avg_invoices"],
             [["Big regular buyers", 387, Decimal("8698526133.00"), Decimal("41.2345"), Decimal("33.1000")]]),
            ("GROUP BY alert_type", ["k", "n"], [["Unusual price", 100], ["Large credit note", 12]]),
            ("FROM ml_invoice_alerts", ["alert_type", "invoice_number", "invoice_date", "customer_name", "product_code",
                                        "value_inr", "typical_inr", "reason"],
             [["Large credit note", "SSMI/D/2627/5090", datetime.date(2026, 6, 1), "X", "FG01849", Decimal("462000.00"),
               Decimal("13500.00"), "big"],
              ["Unusual price", "SSMI/D/2425/3672", datetime.date(2024, 9, 1), "Y", "FG02665", Decimal("26827.50"),
               Decimal("38880.00"), "low price"]]),
            ("FROM ml_product_pairs", ["product_a_code", "product_a_description", "product_b_code", "product_b_description",
                                       "orders_together", "confidence_pct", "lift"],
             [["FG01289", "A", "FG02171", "B", 25, Decimal("60.98"), Decimal("196.66")]]),
            ("GROUP BY status", ["k", "n"], [["Under 30 days", 349], ["No recent sales", 822]]),
            ("FROM ml_stock_runout", ["product_code", "product_description", "stock_qty", "avg_daily_sales_qty", "days_left",
                                      "runout_date", "status"],
             [["FG00001", "Pump", Decimal("3.000"), Decimal("1.500"), Decimal("2.0"), datetime.date(2026, 11, 2),
               "Under 30 days"]]),
        ]
        for marker, columns, rows in answers:
            if marker in sql:
                return {"columns": columns, "rows": rows, "truncated": False}
        raise AssertionError(f"unexpected SQL: {sql}")


@pytest.fixture
def fake_mysql(monkeypatch):
    def install(tables=()):
        fake = FakeWarehouse(tables)
        monkeypatch.setattr(warehouse, "run_select_params", fake)
        monkeypatch.setattr(warehouse, "schema", lambda: pytest.fail("insights must not use warehouse.schema()"))
        return fake
    return install


def test_a_stranger_must_sign_in(client, fake_mysql):
    fake_mysql()
    assert api_get(client, "api_insights").status_code == 401


def test_get_only(client, user, fake_mysql):
    fake_mysql()
    client.force_login(user)
    assert api_post(client, "api_insights", {}).status_code == 405


def test_before_the_first_run_it_is_not_ready(client, user, fake_mysql):
    fake_mysql(tables=())
    client.force_login(user)
    r = api_get(client, "api_insights")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is False and body["run_at"] is None and body["data_to"] is None
    assert body["forecast"]["months"] == [] and body["risk"]["customers"] == [] and body["pairs"] == []
    assert body["risk"]["counts"] == {"High": 0, "Medium": 0, "Low": 0}
    assert set(body["stockout"]["counts"]) == set(insights.STOCK_STATUSES)


def test_mysql_down_is_not_a_500(client, user, monkeypatch):
    def down(*args, **kwargs):
        raise warehouse.WarehouseUnavailable("no MySQL")
    monkeypatch.setattr(warehouse, "run_select_params", down)
    client.force_login(user)
    r = api_get(client, "api_insights")
    assert r.status_code == 200 and r.json()["ready"] is False and r.json()["error"]


def test_the_full_reply_with_fake_rows(client, user, fake_mysql):
    fake_mysql(tables=insights.ML_TABLES)
    client.force_login(user)
    body = api_get(client, "api_insights").json()
    assert body["ready"] is True and body["error"] is None
    assert body["run_at"] == "2026-11-17T16:00:00" and body["data_to"] == "2026-10-31"
    fc = body["forecast"]
    assert fc["model"] == "Holt-Winters" and fc["mape_pct"] == 4.16
    assert fc["history"] == [{"month": "Sep 2026", "actual": 472683500.0}, {"month": "Oct 2026", "actual": 517494500.0}]
    assert fc["months"][0] == {"month": "Nov 2026", "period_start": "2026-10-21", "period_end": "2026-11-20",
                               "forecast": 535000000.0, "low": 498000000.0, "high": 571000000.0}
    assert fc["products"][0]["product_code"] == "FG01484" and fc["products"][0]["forecast"] == 16500000.0
    assert body["risk"]["counts"] == {"High": 118, "Medium": 107, "Low": 633}
    assert body["risk"]["customers"][0]["risk_score"] == 100.0
    assert body["risk"]["customers"][0]["last_invoice_date"] == "2026-07-17"
    assert body["segments"][0] == {"segment_name": "Big regular buyers", "customers": 387, "sales_inr": 8698526133.0,
                                   "avg_recency_days": 41.2, "avg_invoices": 33.1}
    assert body["alerts"]["counts"] == {"Unusual price": 100, "Unusual quantity": 0, "Large credit note": 12}
    assert [a["alert_type"] for a in body["alerts"]["items"]] == ["Unusual price", "Large credit note"]
    assert body["pairs"][0]["lift"] == 196.66
    assert body["stockout"]["counts"]["Under 30 days"] == 349 and body["stockout"]["counts"]["OK"] == 0
    assert body["stockout"]["items"][0]["days_left"] == 2.0
    assert body["stockout"]["items"][0]["runout_date"] == "2026-11-02"
