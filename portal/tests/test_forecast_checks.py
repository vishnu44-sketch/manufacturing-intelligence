"""A forecast is never added up into a longer period's total.

18-Nov: "what is my 2027 total sales" got SELECT SUM(forecast_inr) ... FROM ml_sales_forecast (one row, no month) and
the answer "the forecast for total sales in 2027 is about INR 54.6 Cr" - only sales month Jan 2027 is forecast in 2027.
The rules (agent.ML_RESULTS_NOTE, the SQL prompt, docs/) were not followed every time, so two safety nets in our code:
- agent.summed_forecast_months: a SUM / AVG of forecast_inr / low_inr / high_inr not grouped by the forecast month is
  sent back once (lc/graph.check_sql) with agent.FORECAST_SUM_PROBLEM; the MCP server's run_sql flags it too;
- agent.forecast_months_note: the answer step of a query on ml_sales_forecast is told which months are forecast at
  all and which past months the model was trained on (read from MySQL by the app, ~70 tokens); other answers are
  unchanged.

The AI is the fake one of test_agent.py (FakeAI behind LangChain); MySQL and the notes search are faked.
Run with:  python -m pytest -q portal/tests/test_forecast_checks.py
"""
import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from portal import mcp_server
from portal.lc.docs import load_docs
from portal.rag import agent, warehouse
from portal.rag.sql_guard import check_sql, strip_fences
from portal.tests.test_agent import mysql, use_fake_ai  # noqa: F401
from portal.tests.test_graph import DATA_START, steps  # noqa: F401
from portal.tests.test_ml_questions import ALLOWED, FORECAST_ANSWER, FORECAST_ROWS, FORECAST_SQL, TODAY

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question

REAL_FORECAST_MONTHS_NOTE = agent.forecast_months_note  # the mysql fixture replaces it
DOCS = Path(__file__).resolve().parents[2] / "docs"
QUESTION = "what is my 2027 total sales"

# the query of 18-Nov, as the AI wrote it: the 2027 forecast months added into one row
SUMMED_SQL = """SELECT SUM(forecast_inr) AS forecast_total_inr, SUM(low_inr) AS low_total_inr,
  SUM(high_inr) AS high_total_inr, AVG(mape_pct) AS avg_mape_pct, data_to
FROM ml_sales_forecast
WHERE level = 'TOTAL' AND period_end >= '2027-01-01' AND period_start <= '2027-12-31'
GROUP BY data_to"""
# the right one (docs/sql_examples.md "What will our total sales be in 2027?"): one row per forecast month
PER_MONTH_SQL = """SELECT f.sales_month, f.period_start, f.period_end, ROUND(f.forecast_inr, 2) AS forecast_inr,
  ROUND(f.low_inr, 2) AS low_inr, ROUND(f.high_inr, 2) AS high_inr, f.mape_pct, f.data_to,
  COUNT(*) OVER () AS forecast_months_in_period
FROM ml_sales_forecast f
WHERE f.level = 'TOTAL' AND f.period_end >= '2027-01-01' AND f.period_start <= '2027-12-31'
ORDER BY f.period_start"""
DATA_TO = datetime.date(2026, 10, 31)


def sales_month(year, month):
    """(name, first day, last day) of a sales month: 'Jan 2027' = 21-Dec-2026 to 20-Jan-2027."""
    end = datetime.date(year, month, 20)
    start = datetime.date(year - (month == 1), month - 1 or 12, 21)
    return end.strftime("%b %Y"), start, end


# the 2027 rows of the run of 18-Nov-2026 (the forecast goes 12 sales months ahead: Nov 2026 to Oct 2027):
# Jan 2027 to Oct 2027 are in 2027, one row per month
YEAR_ROWS = {"columns": ["sales_month", "period_start", "period_end", "forecast_inr", "low_inr", "high_inr",
                         "mape_pct", "data_to", "forecast_months_in_period"],
             "rows": [[*sales_month(2027, m), Decimal(f), Decimal(lo), Decimal(hi), Decimal("4.16"), DATA_TO, 10]
                      for m, f, lo, hi in [
                          (1, "546371110.54", "501753327.90", "590988893.18"),
                          (2, "539681152.25", "491937063.04", "587425241.46"),
                          (3, "628187472.03", "568338552.25", "688036391.81"),
                          (4, "575648914.60", "516888079.58", "634409749.63"),
                          (5, "546336541.32", "486849928.45", "605823154.19"),
                          (6, "563422243.17", "498241108.06", "628603378.27"),
                          (7, "499992489.90", "438746875.50", "561238104.30"),
                          (8, "537112731.17", "467665000.80", "606560461.54"),
                          (9, "562931379.32", "486314499.20", "639548259.44"),
                          (10, "583165655.29", "499826279.52", "666505031.06")]],
             "truncated": False}
YEAR_ANSWER = ("Sales months Jan 2027 to Oct 2027 (21-Dec-2026 to 20-Oct-2027) of 2027 are forecast, month by month: "
               "Jan 2027 about INR 54.6 Cr (range 50.2 - 59.1 Cr) ... Oct 2027 about INR 58.3 Cr (range 50.0 - 66.7 Cr), "
               "average error 4.16 %; Nov and Dec 2027 are not forecast and have no actual sales yet.")
# what MySQL has (18-Nov, laptop): TOTAL Nov 2026 - Oct 2027 (12 months), PRODUCT Nov 2026 - Jan 2027 (3 months)
# + the training months of every row (18-Nov, "is that trained for 12 months?": trained on 30, forecasts 12)
TRAINED = ["May 2024", "Oct 2026", 30]
NOTE_ROWS = {"columns": ["level", "sales_month", "period_start", "period_end", "data_to", "train_from_month",
                         "train_to_month", "train_months"],
             "rows": [["TOTAL", *sales_month(2026 + (m > 12), (m - 1) % 12 + 1), DATA_TO, *TRAINED]
                      for m in range(11, 23)]
                     + [["PRODUCT", *sales_month(2026 + (m > 12), (m - 1) % 12 + 1), DATA_TO, *TRAINED]
                        for m in range(11, 14)],
             "truncated": False}
NOTE = ("total - Nov 2026 to Oct 2027 (12 sales months, 21-Oct-2026 to 20-Oct-2027); products - Nov 2026 to "
        "Jan 2027 (3 sales months); trained on May 2024 to Oct 2026 (30 complete sales months); data up to "
        "31-Oct-2026. No other month is forecast - never give these as a longer period's total.")


def forecast_examples():
    """The example SQL of docs/sql_examples.md that reads ml_sales_forecast."""
    return [c for c in load_docs(DOCS) if c["kind"] == "example" and "ml_sales_forecast" in strip_fences(c["text"])]


# ---------- the check ----------

@pytest.mark.parametrize("sql", [
    SUMMED_SQL,                                                                          # 18-Nov
    SUMMED_SQL.replace("GROUP BY data_to", "").replace(", data_to\n", "\n"),            # no GROUP BY at all
    "SELECT AVG(forecast_inr) AS avg_month FROM ml_sales_forecast WHERE level = 'TOTAL'",
    "SELECT ROUND(SUM(f.forecast_inr) / 1e7, 1) AS cr FROM ml_sales_forecast f WHERE f.level = 'TOTAL' "
    "AND YEAR(f.period_end) = 2027",                                                    # inside ROUND, a year filter
    "SELECT (SELECT SUM(high_inr) FROM ml_sales_forecast WHERE level = 'TOTAL') AS q4_high",   # in a subquery
    "WITH m AS (SELECT sales_month, forecast_inr FROM ml_sales_forecast WHERE level = 'TOTAL') "
    "SELECT SUM(m.forecast_inr) AS total FROM m",                                      # added up after a CTE
    "SELECT level, SUM(forecast_inr) FROM ml_sales_forecast GROUP BY level",          # grouped, but not by month
])
def test_forecast_months_added_into_one_number_are_found(sql):
    assert agent.summed_forecast_months(sql) is True


@pytest.mark.parametrize("sql", [
    FORECAST_SQL, PER_MONTH_SQL,
    # a product forecast, one row per product and month
    "SELECT f.product_code, f.sales_month, f.forecast_inr, f.low_inr, f.high_inr FROM ml_sales_forecast f "
    "WHERE f.level = 'PRODUCT' ORDER BY f.forecast_inr DESC",
    "SELECT f.product_code, f.sales_month, SUM(f.forecast_inr) FROM ml_sales_forecast f WHERE f.level = 'PRODUCT' "
    "GROUP BY f.product_code, f.sales_month",
    # the top 10 products of ONE month added up, grouped by the month / filtered to one month
    "SELECT sales_month, SUM(forecast_inr) AS top10_inr, SUM(low_inr), SUM(high_inr) FROM ml_sales_forecast "
    "WHERE level = 'PRODUCT' GROUP BY sales_month",
    "SELECT sales_month, SUM(forecast_inr) FROM ml_sales_forecast WHERE level = 'PRODUCT' GROUP BY 1",
    "SELECT SUM(forecast_inr) FROM ml_sales_forecast WHERE level = 'PRODUCT' AND sales_month = 'Nov 2026'",
    "SELECT SUM(forecast_inr) FROM ml_sales_forecast WHERE level = 'PRODUCT' AND sales_month IN ('Nov 2026')",
    "SELECT SUM(forecast_inr) FROM ml_sales_forecast WHERE level = 'PRODUCT' "
    "AND period_start = (SELECT MIN(period_start) FROM ml_sales_forecast)",
    # the actual sales per forecast month - a SUM of the invoices, not of the forecast
    "SELECT f.sales_month, f.forecast_inr, ROUND(SUM(il.net_taxable_value), 2) AS actual_inr FROM ml_sales_forecast f "
    "JOIN fact_invoice_lines il ON il.invoice_date BETWEEN f.period_start AND f.period_end "
    "WHERE f.level = 'TOTAL' GROUP BY f.sales_month, f.forecast_inr",
    # a window total next to each month's row; the highest month by MAX
    "SELECT sales_month, forecast_inr, SUM(forecast_inr) OVER () AS all_months FROM ml_sales_forecast "
    "WHERE level = 'TOTAL'",
    "SELECT sales_month, forecast_inr FROM ml_sales_forecast WHERE level = 'TOTAL' "
    "AND forecast_inr = (SELECT MAX(forecast_inr) FROM ml_sales_forecast WHERE level = 'TOTAL')",
    # no forecast table, unreadable SQL, nothing
    "SELECT SUM(il.net_taxable_value) FROM fact_invoice_lines il",
    "SELECT SUM(forecast_inr FROM ml_sales_forecast (", "", None,
])
def test_per_month_and_other_queries_are_fine(sql):
    assert agent.summed_forecast_months(sql) is False


@pytest.mark.parametrize("chunk", forecast_examples(), ids=lambda c: c["heading"])
def test_every_forecast_example_of_the_docs_passes(chunk):
    sql = strip_fences(chunk["text"])
    assert agent.summed_forecast_months(sql) is False
    assert agent.summed_forecast_months(check_sql(sql, allowed_tables=ALLOWED)) is False


def test_there_are_forecast_examples():
    assert len(forecast_examples()) >= 4


def test_the_problem_says_one_row_per_month():
    assert agent.FORECAST_SUM_PROBLEM.startswith("ml_sales_forecast.forecast_inr is per sales month - never add months")
    assert "one row per forecast month" in agent.FORECAST_SUM_PROBLEM
    assert "a period longer than the forecast months is not forecast" in agent.FORECAST_SUM_PROBLEM


def test_the_mcp_server_flags_it_too():
    assert agent.FORECAST_SUM_PROBLEM in mcp_server.looks_wrong(check_sql(SUMMED_SQL, allowed_tables=ALLOWED))
    assert agent.FORECAST_SUM_PROBLEM not in mcp_server.looks_wrong(check_sql(PER_MONTH_SQL, allowed_tables=ALLOWED))


# ---------- in the graph: sent back once before it runs ----------

@pytest.fixture
def forecast_db(monkeypatch, mysql):
    """The tables with the ml_ ones, today 17-Nov-2026."""
    monkeypatch.setattr(agent, "today", lambda: TODAY)
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: ALLOWED)
    return mysql


def test_the_18_nov_query_is_sent_back_once_and_the_per_month_one_is_answered(monkeypatch, forecast_db, user, steps):
    forecast_db.results = [YEAR_ROWS]
    fake = use_fake_ai(monkeypatch, [(f"```sql\n{SUMMED_SQL}\n```", 3000), (f"```sql\n{PER_MONTH_SQL}\n```", 3100),
                                     (YEAR_ANSWER, 800)])

    result = agent.ask(QUESTION, user)

    assert steps == DATA_START + ["write_sql", "check_sql", "retry", "write_sql", "check_sql", "run_sql", "explain"]
    assert len(forecast_db.calls) == 1 and "SUM(forecast_inr)" not in forecast_db.calls[0]   # the sum never ran
    assert agent.FORECAST_SUM_PROBLEM in fake.calls[1][-1]["content"]
    assert result.status == "ok" and result.rows == YEAR_ROWS["rows"] and result.tries == 2
    assert result.answer == YEAR_ANSWER


def test_it_is_sent_back_only_once(monkeypatch, forecast_db, user):
    one_row = {"columns": ["forecast_total_inr", "low_total_inr", "high_total_inr", "avg_mape_pct", "data_to"],
               "rows": [[Decimal("546371110.54"), Decimal("501753327.90"), Decimal("590988893.18"), Decimal("4.16"),
                         datetime.date(2026, 10, 31)]], "truncated": False}
    forecast_db.results = [one_row]
    fake = use_fake_ai(monkeypatch, [(f"```sql\n{SUMMED_SQL}\n```", 3000)] * 2 + [(YEAR_ANSWER, 800)])

    result = agent.ask(QUESTION, user)

    assert len(forecast_db.calls) == 1 and result.status == "ok" and result.tries == 2   # the model insisted: it runs
    assert len(fake.calls) == 3


# ---------- the fact note for the answer step ----------

def test_the_note_names_the_forecast_months(monkeypatch):
    calls = []
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: ALLOWED)
    monkeypatch.setattr(warehouse, "run_select", lambda sql: calls.append(sql) or NOTE_ROWS)
    assert agent.forecast_months_note(FORECAST_SQL) == NOTE
    assert len(calls) == 1 and "GROUP BY" in calls[0] and "ml_sales_forecast" in calls[0]
    assert agent.forecast_months_note("SELECT 1 FROM fact_invoice_lines") == ""     # other SQL: no query at all
    assert agent.forecast_months_note(None) == "" and len(calls) == 1
    assert len(NOTE) < 360                                                           # about 70 tokens


def test_a_forecast_table_without_training_columns_gives_the_note_without_them(monkeypatch):
    """An ml_sales_forecast made before 18-Nov (train_* NULL) - the months are still said, the training part left out."""
    old = {**NOTE_ROWS, "rows": [row[:5] + [None, None, None] for row in NOTE_ROWS["rows"]]}
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: ALLOWED)
    monkeypatch.setattr(warehouse, "run_select", lambda sql: old)
    assert agent.forecast_months_note(FORECAST_SQL) == NOTE.replace(
        "trained on May 2024 to Oct 2026 (30 complete sales months); ", "")


@pytest.mark.parametrize("failure", [warehouse.QueryError("boom"), warehouse.WarehouseUnavailable("down"),
                                     KeyError("rows")])
def test_a_failing_note_query_leaves_the_note_out(monkeypatch, failure):
    def run_select(sql):
        raise failure
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: ALLOWED)
    monkeypatch.setattr(warehouse, "run_select", run_select)
    assert agent.forecast_months_note(FORECAST_SQL) == ""
    monkeypatch.setattr(warehouse, "run_select", lambda sql: {"columns": [], "rows": [], "truncated": False})
    assert agent.forecast_months_note(FORECAST_SQL) == ""                            # no forecast rows: no note


def _note_router(monkeypatch, mysql, note):
    """warehouse.run_select: the note's query gets `note` (raised when an Exception), every other SQL goes to the
    fake MySQL; returns the list of note queries."""
    asked = []

    def run_select(sql):
        if "MAX(data_to) AS data_to" in sql and "GROUP BY" in sql:
            asked.append(sql)
            if isinstance(note, Exception):
                raise note
            return note
        return mysql.run_select(sql)
    monkeypatch.setattr(warehouse, "run_select", run_select)
    monkeypatch.setattr(agent, "forecast_months_note", REAL_FORECAST_MONTHS_NOTE)
    return asked


def test_the_answer_request_of_a_forecast_query_gets_the_note(monkeypatch, forecast_db, user):
    asked = _note_router(monkeypatch, forecast_db, NOTE_ROWS)
    forecast_db.results = [FORECAST_ROWS]
    fake = use_fake_ai(monkeypatch, [(f"```sql\n{FORECAST_SQL}\n```", 3000), (FORECAST_ANSWER, 800)])

    result = agent.ask("What will our sales be next month?", user)

    assert result.status == "ok" and result.answer == FORECAST_ANSWER
    assert len(forecast_db.calls) == 1 and len(asked) == 1
    assert "Forecast months available (worked out by the app): " + NOTE in fake.calls[1][-1]["content"]


def test_other_answers_get_no_note_and_no_query(monkeypatch, forecast_db, user):
    asked = _note_router(monkeypatch, forecast_db, NOTE_ROWS)
    forecast_db.results = [{"columns": ["net_sales_inr"], "rows": [[Decimal("1.00")]], "truncated": False}]
    fake = use_fake_ai(monkeypatch, [("```sql\nSELECT ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr "
                                      "FROM fact_invoice_lines il WHERE il.invoice_date BETWEEN '2026-09-21' "
                                      "AND '2026-10-20'\n```", 3000), ("Net sales were INR 1.00.", 800)])

    agent.ask("net sales in Oct 2026", user)

    assert asked == [] and "Forecast months" not in fake.calls[1][-1]["content"]


def test_the_request_text_of_other_answers_is_unchanged(monkeypatch):
    """explain_values of a query without ml_sales_forecast is the same with the real note function as without it."""
    result = agent.AskResult(text="net sales in Oct 2026", status="ok", columns=["net_sales_inr"],
                             rows=[[Decimal("1.00")]],
                             sql="SELECT SUM(net_taxable_value) AS net_sales_inr FROM fact_invoice_lines")
    monkeypatch.setattr(warehouse, "run_select", lambda sql: pytest.fail("no query for other answers"))
    monkeypatch.setattr(agent, "data_coverage_notes", lambda sql: [])
    with_real = agent.explain_values(result, agent.ROWS_FOR_ANSWER)
    monkeypatch.setattr(agent, "forecast_months_note", lambda sql: "")
    assert agent.explain_values(result, agent.ROWS_FOR_ANSWER) == with_real


def test_a_failing_note_query_still_gives_the_answer_without_the_note(monkeypatch, forecast_db, user):
    asked = _note_router(monkeypatch, forecast_db, warehouse.QueryError("Table 'ml_sales_forecast' doesn't exist"))
    forecast_db.results = [FORECAST_ROWS]
    fake = use_fake_ai(monkeypatch, [(f"```sql\n{FORECAST_SQL}\n```", 3000), (FORECAST_ANSWER, 800)])

    result = agent.ask("What will our sales be next month?", user)

    assert len(asked) == 1 and result.status == "ok" and result.answer == FORECAST_ANSWER
    request = fake.calls[1][-1]["content"]
    assert "Forecast months available" not in request and "ML results: " in request
