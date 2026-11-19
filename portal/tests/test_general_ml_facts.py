"""A general question about THIS app's ML gets the app's own facts, not a textbook answer.

18-Nov, real chat: "have you used holt winters model separately for forecast monthly sales csv data" went to the
general answer and got "I've worked with the Holt-Winters ... method for forecasting monthly sales data in CSV
files ... Typical steps: Load the CSV ...". The right answer is about this app: yes - its sales forecast is
Holt-Winters (multiplicative season) on ml_inputdata/forecast_monthly_sales.csv, ~4.16 % backtest MAPE, the best of
5 models. Now:
- agent.about_app_ml: a cheap word check on the question (model, ML, forecast, csv, Holt, KMeans ...). It only
  decides whether facts are ADDED; the AI still chose the route (router / SQL writer) and writes the answer.
- agent.ml_facts_note: a short "This app's ML" block from ONE read-only query of ml_run_log + ml_sales_forecast:
  per scenario the model and its input file (fixed text) with the latest run's key number. '' on any error.
  18-Nov, "is that trained for 12 months?": the forecast line also says the TRAINING months (ml_sales_forecast
  train_from_month / train_to_month / train_months: 30 months, May 2024 - Oct 2026) apart from the 12 forecast
  months, and every other scenario what it was built from (ml_run_log.trained_on).
- GENERAL_SYSTEM_PROMPT: questions about the app's own ML are answered from those facts, never "I've worked with".
Other general questions are unchanged: no query, no extra tokens.

The AI is the fake one of test_agent.py; MySQL (warehouse.run_select) and the notes search are faked.
Run with:  python -m pytest -q portal/tests/test_general_ml_facts.py
"""
import datetime
from decimal import Decimal

import pytest

from portal.rag import agent, warehouse
from portal.tests.test_agent import PDF_HITS, TABLES, mysql, use_fake_ai, use_pdf_hits  # noqa: F401

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question

HOLT_QUESTION = "have you used holt winters model separately for forecast monthly sales csv data"
PARIS = "The capital of France is Paris."
HOLT_ANSWER = ("Yes - the app's sales forecast uses Holt-Winters with a multiplicative 12-month season, trained on "
               "ml_inputdata/forecast_monthly_sales.csv.")
DATA_TO = datetime.date(2026, 10, 31)
RUN_AT = datetime.datetime(2026, 11, 17, 20, 19, 30)
MODEL = "Holt-Winters (trend + multiplicative 12-month season)"

INVOICES = "invoices 02-Apr-2024 - 31-Oct-2026"
FORECAST_MONTHS = ", ".join(["Nov 2026", "Dec 2026", "Jan 2027", "Feb 2027", "Mar 2027", "Apr 2027", "May 2027",
                             "Jun 2027", "Jul 2027", "Aug 2027", "Sep 2027", "Oct 2027"])


def run_row(scenario, metric, value, trained_on):
    """One ml_run_log row of agent.ML_FACTS_SQL: 7 columns + 5 NULLs (the forecast's columns)."""
    return [scenario, f"ml_{scenario}", metric, Decimal(value), DATA_TO, RUN_AT, trained_on,
            None, None, None, None, None]


# what agent.ML_FACTS_SQL gives on the laptop's ss_gold (18-Nov, run 5): the latest run of each scenario (with the
# data it was built from, ml_run_log.trained_on), then the forecast: model, its 12 TOTAL months, MAPE, data_to,
# NULL, NULL, the training months (May 2024 - Oct 2026, 30) and the PRODUCT months / products (3, 10)
ML_ROWS = [
    run_row("stock_runout", "items under 30 days", "349.00",
            "stock report 31-Oct-2026 + invoices 03-Aug-2026 - 31-Oct-2026 (the last 90 days)"),
    run_row("sales_forecast", "backtest MAPE % (last 6 months)", "4.16",
            "30 complete sales months May 2024 - Oct 2026 (net sales per sales month)"),
    run_row("product_pairs", "pairs kept", "242.00", "sales orders 01-Apr-2024 - 31-Oct-2026"),
    run_row("invoice_alerts", "alerts", "172.00", INVOICES),
    run_row("customer_segments", "customer groups", "5.00", INVOICES),
    run_row("customer_risk", "customers High risk", "118.00", INVOICES + " + sales orders up to 31-Oct-2026"),
    ["forecast_model", MODEL, FORECAST_MONTHS, Decimal("4.16"), DATA_TO, None, None, "May 2024", "Oct 2026", 30, 3,
     10],
]
ML_BLOCK = (
    "This app's ML (ml/run_ml.py, input files in ml_inputdata/; latest run 17-Nov-2026, data up to 31-Oct-2026):\n"
    "- Sales forecast: Holt-Winters (trend + multiplicative 12-month season), best of 5 models in a backtest "
    "(lowest MAPE on the last 6 complete months held back; tried: Holt-Winters multiplicative / additive, SARIMAX, "
    "last year x growth, 3-month average); "
    "forecast_monthly_sales.csv (complete sales months); trained on 30 complete sales months (May 2024 - Oct 2026); "
    "forecasts 12 sales months ahead (Nov 2026 - Oct 2027) total, 3 for the top 10 products; "
    "backtest MAPE % (last 6 months) = 4.16\n"
    "- Customer risk: 0-100 points score: 40 % how far sales dropped (last 3 months vs the customer's normal 3 "
    "months), 40 % fewer sales orders than normal, 20 % days overdue (days since the last invoice vs the customer's "
    "usual gap between invoices - not unpaid amounts); lowered for customers who order less than about once a month; "
    "customer_features.csv; "
    "built from invoices 02-Apr-2024 - 31-Oct-2026 + sales orders up to 31-Oct-2026; customers High risk = 118\n"
    "- Customer groups: KMeans, 5 groups, on recency (days since the last invoice), frequency (invoices), money "
    "(net sales), tenure (days since the first invoice); customer_rfm.csv; "
    "built from invoices 02-Apr-2024 - 31-Oct-2026; customer groups = 5\n"
    "- Unusual invoices: robust z-scores: unit price and quantity vs that product's median, credit-note size vs the "
    "usual credit note; invoice_lines_for_alerts.csv; "
    "built from invoices 02-Apr-2024 - 31-Oct-2026; alerts = 172\n"
    "- Bought together: support, confidence, lift of product pairs on the same sales order; order_baskets.csv; "
    "built from sales orders 01-Apr-2024 - 31-Oct-2026; pairs kept = 242\n"
    "- Stock run-out: days left = stock quantity / average daily sales quantity of the last 90 days of invoices; "
    "stock_speed.csv; built from stock report "
    "31-Oct-2026 + invoices 03-Aug-2026 - 31-Oct-2026 (the last 90 days); items under 30 days = 349")


def fake_ml_db(monkeypatch, data):
    """warehouse.run_select answers the facts query with `data` (raised when an Exception); returns the queries."""
    calls = []

    def run_select(sql):
        calls.append(sql)
        if isinstance(data, Exception):
            raise data
        return {"columns": ["scenario", "result_table", "metric_name", "metric_value", "data_to", "run_at",
                            "trained_on", "train_from_month", "train_to_month", "train_months", "product_months",
                            "products"],
                "rows": data, "truncated": False}
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: TABLES | {"ml_run_log", "ml_sales_forecast"})
    monkeypatch.setattr(warehouse, "run_select", run_select)
    return calls


def general_request(fake):
    """The human message of the general answer call (the last call)."""
    return fake.calls[-1][-1]["content"]


# ---------- the block builder ----------

def test_the_block_on_the_real_rows_of_18_nov(monkeypatch):
    calls = fake_ml_db(monkeypatch, ML_ROWS)

    assert agent.ml_facts_note() == ML_BLOCK
    assert len(calls) == 1 and "ml_run_log" in calls[0] and "ml_sales_forecast" in calls[0]   # ONE query


def test_the_block_follows_the_data_not_fixed_numbers(monkeypatch):
    rows = [run_row("sales_forecast", "backtest MAPE % (last 6 months)", "6.50", None),
            ["forecast_model", "Average of the last 3 months", ", ".join(f"M{i}" for i in range(1, 13)),
             Decimal("6.50"), DATA_TO, None, None, "Jan 2025", "Oct 2026", 22, 2, 5]]
    fake_ml_db(monkeypatch, rows)

    block = agent.ml_facts_note()

    assert "- Sales forecast: Average of the last 3 months, best of 5 models" in block
    assert ("trained on 22 complete sales months (Jan 2025 - Oct 2026); forecasts 12 sales months ahead (M1 - M12) "
            "total, 2 for the top 5 products; backtest MAPE % (last 6 months) = 6.5") in block
    assert "Customer risk" not in block                                  # a scenario not run is not claimed


def test_is_that_trained_for_12_months_gets_the_training_period_not_the_forecast_months(monkeypatch):
    """18-Nov: "is that trained for 12 months?" - trained on 30 months (May 2024 - Oct 2026), forecasts 12."""
    fake_ml_db(monkeypatch, ML_ROWS)

    assert agent.about_app_ml("is that trained for 12 months?")
    block = agent.ml_facts_note()
    assert "trained on 30 complete sales months (May 2024 - Oct 2026); forecasts 12 sales months ahead" in block


def test_an_old_forecast_table_without_training_columns_says_the_run_logs_text(monkeypatch):
    """An ml_sales_forecast made before 18-Nov (no train_* values) - ml_run_log.trained_on is said instead; an old
    run log row without trained_on (6 columns) still gives its line."""
    rows = [run_row("sales_forecast", "backtest MAPE % (last 6 months)", "4.16", "30 complete sales months May "
                    "2024 - Oct 2026 (net sales per sales month)"),
            ["customer_risk", "ml_customer_risk", "customers High risk", Decimal("118.00"), DATA_TO, RUN_AT],
            ["forecast_model", MODEL, "Nov 2026, Dec 2026", Decimal("4.16"), DATA_TO, None, None, None, None, None,
             0, 0]]
    fake_ml_db(monkeypatch, rows)

    block = agent.ml_facts_note()

    assert ("trained on 30 complete sales months May 2024 - Oct 2026 (net sales per sales month); forecasts 2 sales "
            "months ahead (Nov 2026 - Dec 2026) total; backtest MAPE") in block
    assert "- Customer risk: 0-100 points score: 40 % how far sales dropped" in block
    assert "about once a month; customer_features.csv; customers High risk = 118" in block


def test_a_new_scenario_still_gets_its_line(monkeypatch):
    fake_ml_db(monkeypatch, [run_row("churn_v2", "rows", "10", None)])

    assert agent.ml_facts_note().endswith("\n- churn_v2 (ml_churn_v2): rows = 10")


@pytest.mark.parametrize("data", [warehouse.QueryError("Table 'ml_run_log' doesn't exist"), RuntimeError("down"), []])
def test_a_failing_or_empty_query_gives_no_block(monkeypatch, data):
    fake_ml_db(monkeypatch, data)

    assert agent.ml_facts_note() == ""


@pytest.mark.parametrize("question, about_ml", [
    (HOLT_QUESTION, True),
    ("how accurate is the sales forecast model?", True),
    ("which algorithm makes the customer groups", True),
    ("what data was the ML trained on", True),
    ("is KMeans used here?", True),
    ("is that trained for 12 months?", True),
    ("what is the capital of France", False),
    ("who are you", False),
    ("what is GST?", False),
    ("hello", False),
])
def test_the_word_check(question, about_ml):
    assert agent.about_app_ml(question) is about_ml


# ---------- the general answer ----------

def test_the_18_nov_question_gets_the_ml_facts_in_the_general_prompt(monkeypatch, mysql, user):
    calls = fake_ml_db(monkeypatch, ML_ROWS)
    fake = use_fake_ai(monkeypatch, ["GENERAL", HOLT_ANSWER])

    result = agent.ask(HOLT_QUESTION, user)

    assert result.status == "general" and result.answer == HOLT_ANSWER
    assert general_request(fake) == f"{HOLT_QUESTION}\n\n{ML_BLOCK}"
    for words in (MODEL, "forecast_monthly_sales.csv", "backtest MAPE % (last 6 months) = 4.16", "SARIMAX"):
        assert words in general_request(fake)
    assert len(calls) == 1                                               # the facts query only, no SQL ran
    system = fake.calls[-1][0]["content"]
    assert system == agent.GENERAL_SYSTEM_PROMPT and '"This app\'s ML" facts' in system
    assert "never as your own experience (\"I've worked with ...\")" in system


def test_the_routers_general_also_gets_the_facts(monkeypatch, mysql, user):
    use_pdf_hits(monkeypatch, PDF_HITS)  # the router runs only when a PDF piece scores high enough
    fake_ml_db(monkeypatch, ML_ROWS)
    fake = use_fake_ai(monkeypatch, ["general", HOLT_ANSWER])

    result = agent.ask("which ML model does the sales forecast use?", user)

    assert result.status == "general" and ML_BLOCK in general_request(fake)


def test_a_non_ml_general_question_gets_no_block_and_no_query(monkeypatch, mysql, user):
    calls = fake_ml_db(monkeypatch, ML_ROWS)
    fake = use_fake_ai(monkeypatch, ["GENERAL", PARIS])

    result = agent.ask("what is the capital of France", user)

    assert result.status == "general" and result.answer == PARIS
    assert calls == []                                                   # no query, no extra tokens
    assert fake.calls[-1] == [{"role": "system", "content": agent.GENERAL_SYSTEM_PROMPT},
                              {"role": "user", "content": "what is the capital of France"}]


def test_a_failing_facts_query_leaves_the_block_out_and_the_answer_still_comes(monkeypatch, mysql, user):
    calls = fake_ml_db(monkeypatch, warehouse.QueryError("Table 'ml_run_log' doesn't exist"))
    fake = use_fake_ai(monkeypatch, ["GENERAL", HOLT_ANSWER])

    result = agent.ask(HOLT_QUESTION, user)

    assert result.status == "general" and result.answer == HOLT_ANSWER
    assert len(calls) == 1 and general_request(fake) == HOLT_QUESTION
