"""The answers on the ML result tables give the real totals, no useless lows and the right words.

18-Nov, real answers:
- a list cut short gave no total: "A total of 20 customers are displayed out of a larger set" (the real totals are
  118 High, 107 Medium, 633 Low - 858 scored), "The full list contains 20 rows" (242 product pairs, 10 shown);
- the app's "Highest / lowest" line made the answer name "the lowest lift" and "a negative INR 10,044.00" (a credit
  note in sales_prev_3m_inr) for ranked ML lists;
- a risk score was called "the forecast model", counted pairs "The estimate shows", and the data date "the latest
  report date" instead of 31-Oct-2026.
Now:
- agent.ml_totals_note: the totals of each ml_ result table the SQL reads, in ONE read-only query (~30-50 tokens),
  for the answer step and the MCP server's answer_notes; nothing for other SQL;
- agent.highest_lowest: never for ml_customer_risk / _segments / ml_invoice_alerts / ml_product_pairs /
  ml_stock_runout (ranked lists already); forecasts and every other answer keep it;
- agent.ML_RESULTS_NOTE: the words of each table and "118 High-risk customers; the top 20 are shown".

The AI is the fake one of test_agent.py (FakeAI behind LangChain); MySQL and the notes search are faked.
Run with:  python -m pytest -q portal/tests/test_ml_answers.py
"""
import datetime
from decimal import Decimal

import pytest

from portal import mcp_server
from portal.rag import agent, warehouse
from portal.tests.test_agent import MONTHS, explain_messages, mysql, use_fake_ai  # noqa: F401
from portal.tests.test_ml_questions import ALLOWED, FORECAST_ROWS, FORECAST_SQL

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question

REAL_ML_TOTALS_NOTE = agent.ml_totals_note  # the mysql fixture replaces it
DATA_TO = datetime.date(2026, 10, 31)

RISK_SQL = """SELECT customer_name, risk_score, risk_level, reason, sales_last_3m_inr, sales_prev_3m_inr
FROM ml_customer_risk ORDER BY risk_score DESC LIMIT 20"""
PAIRS_SQL = """SELECT product_a_description, product_b_description, orders_together, confidence_pct, lift
FROM ml_product_pairs ORDER BY lift DESC LIMIT 10"""
SALES_SQL = "SELECT month_year, SUM(net_taxable_value) AS net_sales_inr FROM fact_invoice_lines GROUP BY month_year"

# what the note's query gives on the laptop's ss_gold (18-Nov), as (table, group, count, date) rows
RISK_TOTALS = [["ml_customer_risk", "Low", 633, None], ["ml_customer_risk", "High", 118, None],
               ["ml_customer_risk", "Medium", 107, None], ["ml_customer_risk", "data_to", None, DATA_TO]]
PAIRS_TOTALS = [["ml_product_pairs", "pairs", 242, None], ["ml_product_pairs", "min_orders", 20, None],
                ["ml_product_pairs", "data_to", None, DATA_TO]]
RISK_NOTE = ("Customer risk totals (worked out by the app): 118 High, 107 Medium, 633 Low - 858 customers scored; "
             "data up to 31-Oct-2026.")
PAIRS_NOTE = ("Product pair totals (worked out by the app): 242 pairs bought together on at least 20 sales orders "
              "(counted from real sales orders); data up to 31-Oct-2026.")

# 20 customers at risk (amounts not in order), the last one with a credit note in its previous 3 months (negative)
RISK_ROWS = {"columns": ["customer_name", "risk_score", "risk_level", "reason", "sales_last_3m_inr",
                         "sales_prev_3m_inr"],
             "rows": [[f"Customer {i}", Decimal(95 - i), "High", "Sales fell", Decimal(1000 * (i * 7 % 20)),
                       Decimal(500 * (i * 3 % 20))]
                      for i in range(20)],
             "truncated": False}
RISK_ROWS["rows"][-1][5] = Decimal("-10044.00")
RISK_ANSWER = "118 customers are at high risk; the top 20 are shown, based on data up to 31-Oct-2026."
PAIRS_ROWS = {"columns": ["product_a_description", "product_b_description", "orders_together", "confidence_pct", "lift"],
              "rows": [[f"Product A{i}", f"Product B{i}", 40 - i, Decimal(60 + i * 3 % 7), Decimal(9 - i / 2)]
                       for i in range(10)],
              "truncated": False}


def rows(data):
    return {"columns": ["t", "g", "n", "d"], "rows": data, "truncated": False}


def ask_note(monkeypatch, data):
    """agent.ml_totals_note with the note's query answered by `data` (raised when an Exception); returns the queries."""
    calls = []

    def run_select(sql):
        calls.append(sql)
        if isinstance(data, Exception):
            raise data
        return rows(data)
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: ALLOWED)
    monkeypatch.setattr(warehouse, "run_select", run_select)
    return calls


# ---------- the totals note ----------

def test_the_risk_note_gives_the_totals_per_level(monkeypatch):
    calls = ask_note(monkeypatch, RISK_TOTALS)
    assert agent.ml_totals_note(RISK_SQL) == RISK_NOTE
    assert len(calls) == 1 and "risk_level" in calls[0] and "ml_run_log" in calls[0]
    assert "ml_product_pairs" not in calls[0]                                 # only the tables the SQL names
    assert len(RISK_NOTE) < 200                                               # about 30-50 tokens


def test_the_pairs_note_gives_the_number_of_pairs_and_the_threshold(monkeypatch):
    calls = ask_note(monkeypatch, PAIRS_TOTALS)
    assert agent.ml_totals_note(PAIRS_SQL) == PAIRS_NOTE
    assert len(calls) == 1 and "COUNT(*)" in calls[0] and "MIN(min_orders)" in calls[0]


def test_the_groups_alerts_and_stock_notes(monkeypatch):
    ask_note(monkeypatch, [["ml_customer_segments", "Lapsed", 678, None],
                           ["ml_customer_segments", "Big regular buyers", 387, None],
                           ["ml_customer_segments", "data_to", None, DATA_TO]])
    assert agent.ml_totals_note("SELECT * FROM ml_customer_segments") == (
        "Customer group totals (worked out by the app): 387 Big regular buyers, 678 Lapsed - 1,065 customers in "
        "groups; data up to 31-Oct-2026.")
    ask_note(monkeypatch, [["ml_invoice_alerts", "Large credit note", 12, None],
                           ["ml_invoice_alerts", "Unusual price", 100, None]])          # no run in the log: no date
    assert agent.ml_totals_note("SELECT * FROM ml_invoice_alerts") == (
        "Invoice alert totals (worked out by the app): 100 Unusual price, 12 Large credit note - 112 alerts to check.")
    stock = [["ml_stock_runout", "OK", 85, None], ["ml_stock_runout", "Under 30 days", 349, None],
             ["ml_stock_runout", "report_date", None, datetime.date(2026, 10, 30)],
             ["ml_stock_runout", "data_to", None, DATA_TO]]
    calls = ask_note(monkeypatch, stock)
    assert agent.ml_totals_note("SELECT * FROM ml_stock_runout") == (
        "Stock run-out totals (worked out by the app): 349 Under 30 days, 85 OK - 434 items; stock report of "
        "30-Oct-2026, data up to 31-Oct-2026.")
    assert "MAX(report_date)" in calls[0]
    stock[2][3] = DATA_TO                                                               # the same day: said once
    assert agent.ml_totals_note("SELECT * FROM ml_stock_runout").endswith("434 items; stock report and data up to "
                                                                        "31-Oct-2026.")


def test_two_tables_in_one_sql_give_one_query(monkeypatch):
    calls = ask_note(monkeypatch, RISK_TOTALS + PAIRS_TOTALS)
    assert agent.ml_totals_note(RISK_SQL + " UNION ALL " + PAIRS_SQL) == RISK_NOTE + " " + PAIRS_NOTE
    assert len(calls) == 1


@pytest.mark.parametrize("sql", [SALES_SQL, FORECAST_SQL, "SELECT data_to FROM ml_run_log", "", None])
def test_other_sql_gets_no_note_and_no_query(monkeypatch, sql):
    calls = ask_note(monkeypatch, RISK_TOTALS)
    assert agent.ml_totals_note(sql) == "" and calls == []


@pytest.mark.parametrize("failure", [warehouse.QueryError("boom"), warehouse.WarehouseUnavailable("down"),
                                     KeyError("rows")])
def test_a_failing_note_query_leaves_the_note_out(monkeypatch, failure):
    ask_note(monkeypatch, failure)
    assert agent.ml_totals_note(RISK_SQL) == ""
    ask_note(monkeypatch, [])
    assert agent.ml_totals_note(RISK_SQL) == ""                                      # empty tables: no note
    ask_note(monkeypatch, [["ml_product_pairs", "pairs", 0, None], ["ml_product_pairs", "min_orders", None, None]])
    assert agent.ml_totals_note(PAIRS_SQL) == ""


# ---------- in the answer request ----------

@pytest.fixture
def ml_db(monkeypatch, mysql):
    """The tables with the ml_ ones; the note's query (it reads ml_run_log) gets RISK_TOTALS, the rest the fake
    MySQL. ml_db.notes = the note queries."""
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: ALLOWED)
    monkeypatch.setattr(agent, "ml_totals_note", REAL_ML_TOTALS_NOTE)
    mysql.notes, mysql.note_rows = [], RISK_TOTALS
    asking = mysql.run_select

    def run_select(sql):
        if "'data_to'" in sql:
            mysql.notes.append(sql)
            if isinstance(mysql.note_rows, Exception):
                raise mysql.note_rows
            return rows(mysql.note_rows)
        return asking(sql)
    monkeypatch.setattr(warehouse, "run_select", run_select)
    return mysql


def test_the_answer_request_of_a_risk_list_gets_the_totals_and_no_lows(monkeypatch, ml_db, user):
    ml_db.results = [RISK_ROWS]
    fake = use_fake_ai(monkeypatch, [(f"```sql\n{RISK_SQL}\n```", 3000), (RISK_ANSWER, 800)])

    result = agent.ask("Which customers might stop buying?", user)

    assert result.status == "ok" and result.answer == RISK_ANSWER
    assert len(ml_db.calls) == 1 and len(ml_db.notes) == 1
    request = fake.calls[1][-1]["content"]
    assert "\n\n" + RISK_NOTE in request
    assert "ML results: " + agent.ML_RESULTS_NOTE in request
    assert "Highest / lowest" not in request and "-10,044.00" in request              # the row is there, no "lowest"


def test_a_failing_note_query_still_gives_the_answer(monkeypatch, ml_db, user):
    ml_db.note_rows = warehouse.QueryError("Table 'ml_run_log' doesn't exist")
    ml_db.results = [RISK_ROWS]
    fake = use_fake_ai(monkeypatch, [(f"```sql\n{RISK_SQL}\n```", 3000), (RISK_ANSWER, 800)])

    result = agent.ask("Which customers might stop buying?", user)

    assert result.status == "ok" and len(ml_db.notes) == 1
    request = fake.calls[1][-1]["content"]
    assert "totals (worked out by the app)" not in request and "ML results: " in request


def test_other_answers_get_no_note_and_no_query(monkeypatch, ml_db, user):
    ml_db.results = [{"columns": ["net_sales_inr"], "rows": [[Decimal("1.00")]], "truncated": False}]
    fake = use_fake_ai(monkeypatch, [("```sql\nSELECT ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr "
                                      "FROM fact_invoice_lines il WHERE il.invoice_date BETWEEN '2026-09-21' "
                                      "AND '2026-10-20'\n```", 3000), ("Net sales were INR 1.00.", 800)])

    agent.ask("net sales in Oct 2026", user)

    assert ml_db.notes == [] and "totals (worked out by the app)" not in fake.calls[1][-1]["content"]


def test_the_request_text_of_other_answers_is_unchanged(monkeypatch):
    """explain_values of a query without the ml_ result tables is the same with the real note function as without it."""
    result = agent.AskResult(text="Net sales month by month?", status="ok", columns=["month_year", "net_sales_inr"],
                             rows=MONTHS, sql=SALES_SQL)
    monkeypatch.setattr(warehouse, "run_select", lambda sql: pytest.fail("no query for other answers"))
    monkeypatch.setattr(agent, "data_coverage_notes", lambda sql: [])
    with_real = agent.explain_values(result, agent.ROWS_FOR_ANSWER)
    monkeypatch.setattr(agent, "ml_totals_note", lambda sql: "")
    assert agent.explain_values(result, agent.ROWS_FOR_ANSWER) == with_real
    assert "Highest / lowest (worked out by the app" in with_real["table"]              # a normal answer keeps it


# ---------- no highest / lowest for the ranked ML lists ----------

def ml_result(sql, data):
    return agent.AskResult(text="x", status="ok", columns=data["columns"], rows=data["rows"], sql=sql)


@pytest.mark.parametrize("sql, data", [(RISK_SQL, RISK_ROWS), (PAIRS_SQL, PAIRS_ROWS)])
def test_no_highest_and_lowest_for_ranked_ml_lists(sql, data):
    assert agent.highest_lowest(ml_result(sql, data)) == ""
    # the same rows from another query would get it: the skip is for the ml_ tables only
    assert agent.highest_lowest(ml_result("SELECT * FROM fact_invoice_lines", data)) != ""


@pytest.mark.parametrize("table", ["ml_customer_segments", "ml_invoice_alerts", "ml_stock_runout"])
def test_no_highest_and_lowest_for_the_other_ranked_tables(table):
    assert agent.highest_lowest(ml_result(f"SELECT * FROM {table}", PAIRS_ROWS)) == ""


def test_a_normal_sales_query_and_a_forecast_keep_highest_and_lowest():
    sales = agent.AskResult(text="Net sales month by month?", status="ok", columns=["month_year", "net_sales_inr"],
                            rows=MONTHS, sql=SALES_SQL)
    assert agent.highest_lowest(sales).startswith("highest net_sales_inr: Jan 2027 = 3,958,025,198.88")
    request = explain_messages(sales, agent.ROWS_FOR_ANSWER)[1]["content"]
    assert "Highest / lowest (worked out by the app" in request
    forecast = agent.AskResult(text="forecast per month", status="ok", columns=["sales_month", "forecast_inr"],
                               rows=MONTHS, sql="SELECT sales_month, forecast_inr FROM ml_sales_forecast")
    assert agent.highest_lowest(forecast).startswith("highest forecast_inr: Jan 2027")   # per-month forecasts keep it


def test_the_mcp_answer_notes_get_the_totals_and_no_lows(monkeypatch):
    calls = ask_note(monkeypatch, RISK_TOTALS)
    risk = agent.AskResult(text="customers at risk", status="ok", columns=RISK_ROWS["columns"],
                           rows=RISK_ROWS["rows"], sql=RISK_SQL)
    notes, _must_tell = mcp_server.answer_notes(risk, ALLOWED)
    assert RISK_NOTE in notes and len(calls) == 1
    assert not any(note.startswith("Highest / lowest") for note in notes)


# ---------- the words ----------

def test_the_ml_note_has_the_word_rules():
    note = agent.ML_RESULTS_NOTE
    for words in ("risk_score = risk score (never a forecast)", "segments = customer groups",
                  "product pairs = counted from real sales orders (not an estimate)",
                  "alerts = to check, not proven errors", "ml_sales_forecast = forecast",
                  "\"118 High-risk customers; the top 20 are shown\"", "never \"a larger set\"",
                  "as the date itself", "never \"the latest report date\""):
        assert words in note, words
    assert "call them a forecast / estimate" not in note                             # risk / pairs are not estimates
    assert len(note) < 1750   # about 410 tokens (18-Nov: + "no forecast per customer", about 26 tokens)


def test_the_word_rules_reach_the_answer_of_a_forecast(monkeypatch):
    calls = ask_note(monkeypatch, RISK_TOTALS)
    forecast = ml_result(FORECAST_SQL, FORECAST_ROWS)
    monkeypatch.setattr(agent, "forecast_months_note", lambda sql: "")
    monkeypatch.setattr(agent, "data_coverage_notes", lambda sql: [])
    request = agent.explain_values(forecast, agent.ROWS_FOR_ANSWER)["table"]
    assert "ML results: " + agent.ML_RESULTS_NOTE in request and calls == []        # no totals query for a forecast
