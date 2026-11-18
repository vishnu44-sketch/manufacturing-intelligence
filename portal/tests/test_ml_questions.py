"""The ML questions (forecast, customers at risk, customer groups, unusual invoices, products bought together, stock
run-out) are answered from the ml_* tables that run_ml writes into ss_gold - never refused as "not in the data".

17-Nov: the SQL prompt listed "budgets and forecasts" as NOT in ss_gold, and the "period not over yet" check
(agent.periods_not_over) would have sent back a forecast of sales month Nov 2026 (today 17-Nov-2026) because the
month is not over - a forecast IS about months not over yet. Now:
- the prompt (and the MCP server's sql_rules, made from it) says these are in the ml_ tables;
- the schema step (agent.tables_for_question) shows the ml_ table the question needs;
- agent.without_ml_periods() leaves the period filters on ml_ tables out of the "not over" check;
- the answer step gets agent.ML_RESULTS_NOTE (forecast / estimate, range, accuracy) only for SQL on ml_ tables;
- docs/: a data dictionary section per ml_ table, the business rule 'ML results' and 8 example questions.

The AI is the fake one of test_agent.py (FakeAI behind LangChain); MySQL and the notes search are faked.
Run with:  python -m pytest -q portal/tests/test_ml_questions.py
"""
import datetime
from decimal import Decimal
from pathlib import Path

import pytest
import sqlglot

from portal import mcp_server
from portal.lc.docs import load_docs
from portal.rag import agent, warehouse
from portal.rag.sql_guard import check_sql, strip_fences
from portal.tests.test_agent import mysql, use_fake_ai  # noqa: F401
from portal.tests.test_graph import DATA_START, steps  # noqa: F401

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question

TODAY = datetime.date(2026, 11, 17)  # sales month Nov 2026 (21-Oct-2026 to 20-Nov-2026) is not over
ML_TABLES = {"ml_run_log", "ml_sales_forecast", "ml_customer_risk", "ml_customer_segments", "ml_invoice_alerts",
             "ml_product_pairs", "ml_stock_runout"}
GOLD_TABLES = {"dim_calendar", "dim_customers", "dim_fx_rates", "dim_products", "dim_sales_people",
               "dim_stock_movement_types", "dim_tax_codes", "fact_invoice_lines", "fact_sales_order_lines",
               "fact_stock_ledger", "load_log"}
ALLOWED = GOLD_TABLES | ML_TABLES
DOCS = Path(__file__).resolve().parents[2] / "docs"

FORECAST_SQL = """SELECT f.sales_month, f.period_start, f.period_end, f.forecast_inr, f.low_inr, f.high_inr, f.mape_pct,
  f.data_to
FROM ml_sales_forecast f
WHERE f.level = 'TOTAL' AND f.sales_month = 'Nov 2026'"""
FORECAST_ROWS = {"columns": ["sales_month", "period_start", "period_end", "forecast_inr", "low_inr", "high_inr",
                             "mape_pct", "data_to"],
                 "rows": [["Nov 2026", datetime.date(2026, 10, 21), datetime.date(2026, 11, 20),
                           Decimal("480000000.00"), Decimal("440000000.00"), Decimal("520000000.00"),
                           Decimal("6.20"), datetime.date(2026, 10, 31)]],
                 "truncated": False}
FORECAST_ANSWER = ("The forecast for sales month Nov 2026 (21-Oct-2026 to 20-Nov-2026) is INR 480,000,000.00, likely "
                   "between INR 440,000,000.00 and INR 520,000,000.00 (average error 6.20 %).")
# the actual sales of the same month from the invoices, NOT cut at today: this one must still be sent back
ACTUAL_NOV_SQL = """SELECT ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr
FROM fact_invoice_lines il JOIN dim_calendar c ON c.date_id = il.invoice_date_id
WHERE c.sales_month = 'Nov 2026'"""


def ml_examples():
    """The example chunks of docs/sql_examples.md whose SQL reads an ml_ table."""
    return [c for c in load_docs(DOCS) if c["kind"] == "example" and "ml_" in strip_fences(c["text"])]


# ---------- the prompt and the rules ----------

def test_the_sql_prompt_answers_forecasts_from_the_ml_tables_and_no_longer_lists_them_as_missing():
    not_line = next(line for line in agent.SQL_SYSTEM_PROMPT.splitlines() if line.startswith("NOT in ss_gold"))
    assert "budgets and forecasts" not in not_line
    assert "ml_ tables" in not_line and "never NO_DATA / MISSING" in not_line
    for topic in ("sales forecasts", "might stop buying", "customer groups", "unusual invoices",
                  "bought together", "stock run-out"):
        assert topic in not_line
    assert "profit" in agent.SQL_SYSTEM_PROMPT  # the rest of the NOT list is still there


def test_the_mcp_rules_say_the_same():
    assert "ml_ tables" in mcp_server.SQL_RULES and "budgets and forecasts" not in mcp_server.SQL_RULES
    assert "sales forecasts" in mcp_server.INSTRUCTIONS and "sales forecasts" in mcp_server.INSTRUCTIONS_OUR_LLM


def test_the_docs_describe_every_ml_table():
    chunks = load_docs(DOCS)
    tables = {c["heading"].split(" - ", 1)[0] for c in chunks if c["kind"] == "table"}
    assert ML_TABLES <= tables
    rules = [c for c in chunks if c["kind"] == "rule" and c["heading"].startswith("ML results")]
    assert len(rules) == 1
    rule = rules[0]["text"]
    for table in ML_TABLES - {"ml_run_log"}:
        assert table in rule
    for words in ("ESTIMATES", "low_inr", "mape_pct", "never NO_DATA", "Never sum forecast_inr", "run_ml",
                  "report_date"):
        assert words in rule
    not_available = next(c["text"] for c in chunks if c["heading"].startswith("What is NOT in"))
    assert "budgets, forecasts" not in not_available


# ---------- the schema step picks the ml_ table ----------

@pytest.mark.parametrize("question, table", [
    ("What will our sales be next month?", "ml_sales_forecast"),
    ("sales forecast for the next 3 months", "ml_sales_forecast"),
    ("What is the forecast for Coolant pump?", "ml_sales_forecast"),
    ("Which customers might stop buying?", "ml_customer_risk"),
    ("customers at risk of churn", "ml_customer_risk"),
    ("What customer groups do we have?", "ml_customer_segments"),
    ("Any unusual invoices?", "ml_invoice_alerts"),
    ("Which products are bought together?", "ml_product_pairs"),
    ("what do customers buy with FG00040", "ml_product_pairs"),
    ("Which items will run out of stock soon?", "ml_stock_runout"),
])
def test_the_question_words_pick_the_ml_table(question, table):
    chosen = agent.tables_for_question(question, [], ALLOWED)
    assert chosen is not None and table in chosen


@pytest.mark.parametrize("question", [
    "What were net sales in Aug 2026?", "How many sales orders are open?", "What is our stock value now?",
    "Top 5 products by sales value in Nov 2026?", "When was the data last loaded?",
    "Which customers stopped buying from us?",
])
def test_other_questions_do_not_get_the_ml_tables(question):
    assert not (agent.tables_for_question(question, [], ALLOWED) or set()) & ML_TABLES


def test_the_ml_table_of_a_retrieved_example_or_dictionary_piece_is_shown():
    example = next(c for c in ml_examples() if "ml_customer_segments" in c["text"])
    piece = {"kind": "table", "heading": "ml_stock_runout - items that will run out of stock", "text": "..."}
    chosen = agent.tables_for_question("how do we split our buyers", [example, piece], ALLOWED)
    assert {"ml_customer_segments", "ml_stock_runout"} <= chosen


def test_the_schema_text_of_a_forecast_question_has_the_forecast_columns(monkeypatch):
    schema = "\n".join([f"{t}: id, name" for t in sorted(GOLD_TABLES)]
                       + ["ml_sales_forecast: forecast_id, level, sales_month, forecast_inr, low_inr, high_inr",
                          "ml_customer_risk: customer_id, risk_score"])
    monkeypatch.setattr(warehouse, "schema_text", lambda: schema)
    text, full = agent.schema_for_prompt("What will our sales be next month?", [])
    assert full is False
    assert "ml_sales_forecast: forecast_id, level, sales_month, forecast_inr" in text
    assert "ml_customer_risk: customer_id" not in text  # named under "Other ss_gold tables" only
    assert "ml_customer_risk" in text


# ---------- the period checks leave forecasts alone ----------

def test_a_forecast_of_a_month_not_over_yet_is_not_sent_back():
    assert agent.periods_not_over(FORECAST_SQL, TODAY) == []
    assert agent.periods_not_over(FORECAST_SQL.replace("f.sales_month", "sales_month").replace("f.", ""), TODAY) == []
    picked_by_today = FORECAST_SQL.replace(
        "'Nov 2026'", "(SELECT sales_month FROM dim_calendar WHERE full_date = CURDATE())")
    assert agent.periods_not_over(picked_by_today, TODAY) == []


def test_the_actual_sales_of_that_month_are_still_checked():
    assert agent.periods_not_over(ACTUAL_NOV_SQL, TODAY) == ["sales month Nov 2026"]
    # forecast + actual in one query: the filter on the forecast is fine, the uncut actual is not
    mixed = f"""WITH a AS ({ACTUAL_NOV_SQL})
SELECT f.forecast_inr, a.net_sales_inr FROM ml_sales_forecast f CROSS JOIN a
WHERE f.level = 'TOTAL' AND f.sales_month = 'Nov 2026'"""
    assert agent.periods_not_over(mixed, TODAY) == ["sales month Nov 2026"]
    assert agent.periods_not_over(mixed.replace("WHERE c.sales_month = 'Nov 2026'",
                                                "WHERE c.sales_month = 'Nov 2026' AND il.invoice_date <= CURDATE()"),
                                  TODAY) == []
    joined_on_dates = """SELECT f.sales_month, f.forecast_inr, ROUND(SUM(il.net_taxable_value), 2) AS actual_inr
FROM ml_sales_forecast f JOIN fact_invoice_lines il ON il.invoice_date BETWEEN f.period_start AND f.period_end
WHERE f.level = 'TOTAL' AND f.sales_month = 'Nov 2026' GROUP BY f.sales_month, f.forecast_inr"""
    assert agent.periods_not_over(joined_on_dates, TODAY) == []


def test_without_ml_periods_keeps_sql_without_ml_tables_as_it_was():
    assert agent.without_ml_periods(ACTUAL_NOV_SQL) == ACTUAL_NOV_SQL
    assert agent.without_ml_periods(FORECAST_SQL) == ""


def test_the_answer_notes_of_a_forecast_name_the_month_but_not_so_far():
    sql = FORECAST_SQL.replace("f.sales_month = 'Nov 2026'",
                               "f.sales_month = 'Nov 2026' AND f.period_start <= CURDATE()")
    notes = agent.period_notes(sql, TODAY)
    assert notes == ["sales month Nov 2026 = 21-Oct-2026 to 20-Nov-2026"]


def test_a_forecast_question_runs_first_time_and_the_answer_step_is_told_it_is_an_estimate(
        monkeypatch, mysql, user, steps):
    monkeypatch.setattr(agent, "today", lambda: TODAY)
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: ALLOWED)
    mysql.results = [FORECAST_ROWS]
    fake = use_fake_ai(monkeypatch, [(f"```sql\n{FORECAST_SQL}\n```", 3000), (FORECAST_ANSWER, 800)])

    result = agent.ask("What will our sales be next month?", user)

    assert steps == DATA_START + ["write_sql", "check_sql", "run_sql", "explain"]  # not sent back
    assert len(mysql.calls) == 1 and "ml_sales_forecast" in mysql.calls[0]
    assert result.status == "ok" and result.answer == FORECAST_ANSWER and result.tries == 1
    answer_request = fake.calls[1][-1]["content"]
    assert "ML results: " + agent.ML_RESULTS_NOTE in answer_request
    assert "sales month Nov 2026 = 21-Oct-2026 to 20-Nov-2026" in answer_request
    assert "dated after today" not in answer_request  # no AFTER_TODAY_NOTE for a forecast


def test_other_answers_get_no_ml_note(monkeypatch, mysql, user):
    mysql.results = [{"columns": ["net_sales_inr"], "rows": [[Decimal("1.00")]], "truncated": False}]
    fake = use_fake_ai(monkeypatch, [(f"```sql\n{ACTUAL_NOV_SQL.replace('Nov 2026', 'Oct 2026')}\n```", 3000),
                                     ("Net sales were INR 1.00.", 800)])
    agent.ask("net sales in Oct 2026", user)
    assert "ML results" not in fake.calls[1][-1]["content"]


# ---------- the example SQL of the docs ----------

def test_there_is_an_example_per_ml_question():
    headings = [c["heading"] for c in ml_examples()]
    assert len(headings) >= 8
    for table in ML_TABLES - {"ml_run_log"}:
        assert any(table in strip_fences(c["text"]) for c in ml_examples()), table


@pytest.mark.parametrize("chunk", ml_examples(), ids=lambda c: c["heading"])
def test_every_ml_example_parses_passes_the_guard_and_the_checks(chunk):
    sql = strip_fences(chunk["text"])
    assert sqlglot.parse_one(sql, read="mysql") is not None
    cleaned = check_sql(sql, allowed_tables=ALLOWED)
    assert agent.periods_not_over(cleaned, TODAY) == []
    assert agent.calendar_limit_periods(cleaned) is None and agent.month_text_ranges(cleaned) is None
    assert agent.parts_without_year(cleaned) is None and agent.summed_name_matches(cleaned) is None
    assert "Also asked as:" in chunk["text"] and "Why:" in chunk["text"] and "Expected:" in chunk["text"]
    # the schema step shows the ml_ table of the example for its own question
    question = chunk["heading"].removeprefix("Q: ")
    tables = {t for t in ML_TABLES if t in sql}
    assert tables <= (agent.tables_for_question(question, [], ALLOWED) or set()) | {"ml_run_log"}


def test_the_ml_note_asks_for_rounded_crore_amounts_and_no_filler():
    """17-Nov: the forecast answer gave 534,887,655.19 and ended with "should be monitored for any risk alerts"."""
    assert "rounded in Cr (e.g. about INR 53.5 Cr, range 49.8 - 57.1 Cr)" in agent.ML_RESULTS_NOTE
    assert "no advice, no filler and no bare date at the end" in agent.ML_RESULTS_NOTE


def test_run_out_dates_are_told_against_today_and_a_cut_list_gives_its_total():
    """17-Nov: "which items will run out of stock soon?" said "run out within the next two weeks" for 06-Nov-2026 (11 days
    before today) and called 50 of 349 items "the full list"."""
    note = agent.ML_RESULTS_NOTE
    assert "a run-out date before today = would have run out by then (before today) unless new stock arrived" in note
    assert "never call it the full list" in note


def test_past_run_out_dates_become_a_fact_line_for_the_answer():
    """17-Nov: 06-Nov-2026 was told as a future run-out on 17-Nov-2026 - the app now counts the past dates itself."""
    import datetime as dt
    result = agent.AskResult(text="which items will run out of stock soon?",
                             columns=["product_code", "runout_date", "days_left"],
                             rows=[["FG00966", dt.date(2026, 11, 6), 6.7], ["FG03877", dt.date(2026, 11, 7), 7.1],
                                   ["FG09999", dt.date(2026, 12, 1), 31.0]], status="ok")
    note = agent.past_runout_note(result, today=dt.date(2026, 11, 17))
    assert note.startswith("2 of the 3 items shown have a run-out date before today (17-Nov-2026), the earliest 06-Nov-2026")
    assert "never that they will run out on that date" in note
    assert agent.past_runout_note(result, today=dt.date(2026, 11, 1)) == ""          # none past yet
    other = agent.AskResult(text="x", columns=["sales_month"], rows=[["Oct 2026"]], status="ok")
    assert agent.past_runout_note(other) == ""                                        # no run-out column: nothing


def test_a_forecast_is_never_a_year_total_and_comes_with_its_range():
    """18-Nov: "what is my 2027 total sales" gave the Jan 2027 forecast as the 2027 total, data date 20-Jan-2027, no range."""
    assert "with a forecast always SELECT low_inr, high_inr, mape_pct and data_to too" in agent.SQL_SYSTEM_PROMPT
    assert "never give them as the period's total" in agent.ML_RESULTS_NOTE
    assert "The data date is data_to / report_date, never a period end." in agent.ML_RESULTS_NOTE
