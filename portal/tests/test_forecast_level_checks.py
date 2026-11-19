"""A question about the company's forecast is never answered from the product forecast rows.

18-Nov 17:07: "What is the sales forecast for August 2027?" - a weak model read ml_sales_forecast with level = 'PRODUCT'
for sales month 'Aug 2027', got 0 rows and answered "there was no sales forecast for August 2027". The TOTAL row is
there (about 53.7 Cr, 46.8 - 60.7 Cr): product forecasts exist only for the top 10 products, Nov 2026 - Jan 2027.
Two checks in our code (agent.forecast_level_problem, wired in lc/graph.py) send such a query back once:
- before running (check_sql): the WHERE picks product rows (level 'PRODUCT' or a product column) while the question
  names no product -> agent.FORECAST_LEVEL_PROBLEM with the real forecast months;
- after running (run_sql): no rows, the WHERE does not pick level 'TOTAL' and a month the question / SQL names IS a TOTAL
  forecast month -> agent.FORECAST_TOTAL_MONTH_PROBLEM (the 0-row answer is kept when the next try finds nothing).
A month beyond the forecast (Nov 2027) keeps its 0-row answer, and the answer step gets the forecast months note.
The MCP server (no question there) flags level 'PRODUCT' with no product named for a month only TOTAL has.

The AI is the fake one of test_agent.py (FakeAI behind LangChain); MySQL and the notes search are faked.
Run with:  python -m pytest -q portal/tests/test_forecast_level_checks.py
"""
import datetime
import re
from decimal import Decimal

import pytest

from portal import mcp_server
from portal.rag import agent, warehouse
from portal.rag.sql_guard import check_sql, strip_fences
from portal.tests.test_agent import mysql, use_fake_ai  # noqa: F401
from portal.tests.test_forecast_checks import (DATA_TO, NOTE, NOTE_ROWS, _note_router, forecast_examples,  # noqa: F401
                                               sales_month)
from portal.tests.test_graph import DATA_START, steps  # noqa: F401
from portal.tests.test_ml_questions import ALLOWED, TODAY

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question

REAL_FORECAST_LEVELS = agent.forecast_levels  # the mysql fixture replaces it
QUESTION = "What is the sales forecast for August 2027?"

# what MySQL has (18-Nov): TOTAL Nov 2026 - Oct 2027 (12 months), PRODUCT the top 10 products for Nov 2026 - Jan 2027
TOTAL_MONTHS = [sales_month(2026 + (m > 12), (m - 1) % 12 + 1)[0] for m in range(11, 23)]
PRODUCT_MONTHS = TOTAL_MONTHS[:3]
PRODUCTS = ["FG01484 GCI TX-675-3A 0.4kW (415V 50Hz)", "FG01656 Trochoid pump GX-280-1B 7.5kW (415V 50Hz)",
            "FG01116 Procon Pump PR-317-3A 7.5kW (415V 50Hz)", "FG00542 YTH-PARTS TX-325-3A 2.2kW (415V 50Hz)",
            "FG02304 GCI VT-380-1B 0.75kW (415V 50Hz)", "FG02005 Coolant Unit VT-253-2C 0.4kW (415V 50Hz)",
            "FG03012 Hydraulic motor VT-529-1B 3.7kW (415V 50Hz)", "FG02131 GCI VT-881-3A 0.75kW (415V 50Hz)",
            "FG02540 GCI VT-544-1B 0.4kW (415V 50Hz)", "FG00179 Hydraulic motor VT-151-1B 1.5kW (415V 50Hz)"]
LEVELS = {"TOTAL": TOTAL_MONTHS, "PRODUCT": PRODUCT_MONTHS, "products": PRODUCTS}
# the rows of agent.FORECAST_LEVELS_SQL: level, sales_month, period_start, product_code, product_description
LEVEL_ROWS = {"columns": ["level", "sales_month", "period_start", "product_code", "product_description"],
              "rows": [["TOTAL", month, None, None, None] for month in TOTAL_MONTHS]
                      + [["PRODUCT", month, None, *name.split(" ", 1)] for month in PRODUCT_MONTHS for name in PRODUCTS],
              "truncated": False}

LEVEL_PROBLEM = ("The question names no product: use level = 'TOTAL' (company total, 12 sales months Nov 2026 - "
                 "Oct 2027); product forecasts (level 'PRODUCT') exist only for the top 10 products, Nov 2026 - Jan 2027.")
MONTH_PROBLEM = ("Aug 2027 has a TOTAL forecast row (level = 'TOTAL'); product forecasts (level 'PRODUCT') exist only "
                 "for the top 10 products, Nov 2026 - Jan 2027 - query level = 'TOTAL'.")

# the query of 18-Nov 17:07: the product rows of Aug 2027 for a question that names no product
PRODUCT_SQL = """SELECT f.sales_month, f.period_start, f.period_end, f.forecast_inr, f.low_inr, f.high_inr, f.mape_pct
FROM ml_sales_forecast f
WHERE f.level = 'PRODUCT' AND f.sales_month = 'Aug 2027'"""
# no level filter, but the JOIN to dim_products drops the TOTAL row (its product_id is NULL): 0 rows
JOINED_SQL = """SELECT f.sales_month, p.product_code, f.forecast_inr, f.low_inr, f.high_inr
FROM ml_sales_forecast f JOIN dim_products p ON p.product_id = f.product_id
WHERE f.sales_month = 'Aug 2027'"""
# the right one (docs/sql_examples.md "What is the sales forecast for August 2027?")
TOTAL_SQL = """SELECT f.sales_month, f.period_start, f.period_end, ROUND(f.forecast_inr, 2) AS forecast_inr,
  ROUND(f.low_inr, 2) AS low_inr, ROUND(f.high_inr, 2) AS high_inr, f.mape_pct, f.horizon_months, f.data_to
FROM ml_sales_forecast f
WHERE f.level = 'TOTAL' AND f.sales_month = 'Aug 2027'
ORDER BY f.period_start"""
AUG_ROWS = {"columns": ["sales_month", "period_start", "period_end", "forecast_inr", "low_inr", "high_inr", "mape_pct",
                        "horizon_months", "data_to"],
            "rows": [[*sales_month(2027, 8), Decimal("537112731.17"), Decimal("467665000.80"), Decimal("606560461.54"),
                      Decimal("4.16"), 10, DATA_TO]],
            "truncated": False}
AUG_ANSWER = ("The forecast for sales month Aug 2027 (21-Jul-2027 to 20-Aug-2027) is about INR 53.7 Cr (range 46.8 - "
              "60.7 Cr), average error 4.16 %.")
NO_ROWS = {"columns": ["sales_month", "product_code", "forecast_inr", "low_inr", "high_inr"], "rows": [],
           "truncated": False}
# the product example of docs/sql_examples.md
GCI_SQL = """SELECT f.product_code, f.product_description, f.sales_month, f.forecast_inr, f.low_inr, f.high_inr,
  COUNT(*) OVER () AS matches
FROM ml_sales_forecast f
WHERE f.level = 'PRODUCT' AND f.horizon_months = 1
  AND (f.product_description LIKE '%GCI TX-675%' OR f.product_code LIKE '%GCI TX-675%')
ORDER BY f.forecast_inr DESC"""


def sql_of(sql):
    """The SQL as the graph runs it (after the guard)."""
    return check_sql(sql, allowed_tables=ALLOWED)


# ---------- the checks on their own ----------

@pytest.mark.parametrize("sql, found", [
    (PRODUCT_SQL, {"PRODUCT"}),
    ("SELECT * FROM ml_sales_forecast WHERE level IN ('PRODUCT') AND sales_month = 'Aug 2027'", {"PRODUCT"}),
    ("SELECT * FROM ml_sales_forecast WHERE level <> 'TOTAL'", {"PRODUCT"}),
    ("SELECT * FROM ml_sales_forecast WHERE product_code IS NOT NULL", {"product columns"}),
    ("SELECT * FROM ml_sales_forecast f WHERE f.product_description LIKE '%pump%'", {"product columns"}),
    (TOTAL_SQL, {"TOTAL"}),
    ("SELECT * FROM ml_sales_forecast WHERE product_id IS NULL", {"TOTAL"}),     # only TOTAL rows have no product
    ("SELECT * FROM ml_sales_forecast WHERE level = 'TOTAL' OR level = 'PRODUCT'", {"TOTAL", "PRODUCT"}),
    (JOINED_SQL, set()),
    # the product columns of another table are not the forecast's
    ("SELECT f.sales_month FROM ml_sales_forecast f JOIN dim_products p ON p.product_id = f.product_id "
     "WHERE p.product_code = 'FG01484' AND f.level = 'TOTAL'", {"TOTAL"}),
    ("SELECT product_code FROM dim_products WHERE product_code = 'FG01484'", set()),
    ("SELECT * FROM ml_sales_forecast WHERE", set()), ("", set()), (None, set()),
])
def test_the_level_filter_of_a_query(sql, found):
    assert agent.forecast_level_filter(sql) == found


def test_the_months_a_question_names():
    assert agent.forecast_months_asked(QUESTION) == ["Aug 2027"]
    assert agent.forecast_months_asked("sales in sept-2027, Jan, 2027 and 'Aug 2027' or Sep 2027") == [
        "Sep 2027", "Jan 2027", "Aug 2027"]
    assert agent.forecast_months_asked("what will our sales be next month?") == []


@pytest.mark.parametrize("question", [QUESTION, "predict sales for Aug 2027", "expected sales in Sep 2027",
                                      "forecast of total company sales next month", "what is the forecast"])
def test_questions_that_name_no_product(question):
    assert agent.names_a_product(question, LEVELS) is False


@pytest.mark.parametrize("question", ["forecast for GCI TX-675 next month", "forecast for product FG01484",
                                      "which products will sell the most next month", "product-wise sales forecast",
                                      "item wise forecast for Aug 2027", "forecast of the Trochoid pump for Aug 2027",
                                      "how much hydraulic motor will we sell next month"])
def test_questions_that_name_a_product(question):
    assert agent.names_a_product(question, LEVELS) is True


def test_the_17_07_query_is_found_before_it_runs():
    assert agent.forecast_level_problem(QUESTION, sql_of(PRODUCT_SQL), LEVELS) == (LEVEL_PROBLEM, LEVELS)


def test_the_problem_text_is_built_from_the_table(monkeypatch):
    """The months and the product count come from MySQL, read once, only for such a query."""
    calls = []
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: ALLOWED)
    monkeypatch.setattr(warehouse, "run_select", lambda sql: calls.append(sql) or LEVEL_ROWS)
    assert agent.forecast_levels() == LEVELS
    assert len(calls) == 1 and "ml_sales_forecast" in calls[0]
    problem, levels = agent.forecast_level_problem(QUESTION, sql_of(PRODUCT_SQL))
    assert problem == LEVEL_PROBLEM and levels == LEVELS and len(calls) == 2
    shorter = {"columns": LEVEL_ROWS["columns"],
               "rows": [r for r in LEVEL_ROWS["rows"] if r[0] == "TOTAL" and r[1] != "Oct 2027"
                        or r[0] == "PRODUCT" and r[3] in ("FG01484", "FG01656") and r[1] == "Nov 2026"],
               "truncated": False}
    monkeypatch.setattr(warehouse, "run_select", lambda sql: shorter)
    assert agent.forecast_level_problem(QUESTION, sql_of(PRODUCT_SQL))[0] == (
        "The question names no product: use level = 'TOTAL' (company total, 11 sales months Nov 2026 - Sep 2027); "
        "product forecasts (level 'PRODUCT') exist only for the top 2 products, Nov 2026.")


def test_the_after_run_check():
    assert agent.forecast_level_problem(QUESTION, sql_of(JOINED_SQL), LEVELS, []) == (MONTH_PROBLEM, LEVELS)
    assert agent.forecast_level_problem(QUESTION, sql_of(PRODUCT_SQL), LEVELS, [])[0] == MONTH_PROBLEM
    two = agent.forecast_level_problem("forecast for Aug 2027 and Sep 2027", sql_of(JOINED_SQL), LEVELS, [])[0]
    assert two.startswith("Aug 2027 and Sep 2027 have a TOTAL forecast row")
    # rows came back, a month beyond the forecast, a TOTAL query, a product named: nothing
    assert agent.forecast_level_problem(QUESTION, sql_of(JOINED_SQL), LEVELS, AUG_ROWS["rows"])[0] == ""
    assert agent.forecast_level_problem("sales forecast for November 2027", sql_of(JOINED_SQL).replace(
        "Aug 2027", "Nov 2027"), LEVELS, [])[0] == ""
    assert agent.forecast_level_problem(QUESTION, sql_of(TOTAL_SQL), LEVELS, [])[0] == ""
    assert agent.forecast_level_problem("forecast for GCI TX-675 in Aug 2027", sql_of(GCI_SQL), LEVELS, [])[0] == ""


@pytest.mark.parametrize("question, sql", [
    ("forecast for GCI TX-675 next month", GCI_SQL),                          # a product named
    ("which products will sell the most next month",                         # products asked for
     "SELECT product_code, forecast_inr FROM ml_sales_forecast WHERE level = 'PRODUCT' AND horizon_months = 1"),
    (QUESTION, TOTAL_SQL),                                                    # the right query
    (QUESTION, "SELECT sales_month, forecast_inr FROM ml_sales_forecast WHERE sales_month = 'Aug 2027'"),  # no filter
    ("net sales in Oct 2026", "SELECT SUM(il.net_taxable_value) FROM fact_invoice_lines il "
                              "JOIN dim_products p ON p.product_id = il.product_id WHERE p.product_code = 'FG01484'"),
])
def test_queries_that_are_let_through_before_running(question, sql):
    assert agent.forecast_level_problem(question, sql_of(sql), LEVELS)[0] == ""


def test_an_unknown_forecast_lets_every_query_through(monkeypatch):
    """An empty table or a failing read: no check, the query runs as it is."""
    assert agent.forecast_level_problem(QUESTION, sql_of(PRODUCT_SQL), {}) == ("", {})
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: ALLOWED)

    def run_select(sql):
        raise warehouse.QueryError("Table 'ml_sales_forecast' doesn't exist")
    monkeypatch.setattr(warehouse, "run_select", run_select)
    assert agent.forecast_levels() == {}
    assert agent.forecast_level_problem(QUESTION, sql_of(PRODUCT_SQL))[0] == ""


def test_other_queries_read_nothing(monkeypatch):
    monkeypatch.setattr(warehouse, "run_select", lambda sql: pytest.fail("no read for these queries"))
    for sql in (TOTAL_SQL, "SELECT SUM(il.net_taxable_value) FROM fact_invoice_lines il", JOINED_SQL):
        assert agent.forecast_level_problem(QUESTION, sql_of(sql))[0] == ""         # before running: no read
    assert agent.forecast_level_problem("which products will sell the most", sql_of(PRODUCT_SQL))[0] == ""
    assert agent.forecast_level_problem("sales forecast next month", sql_of(JOINED_SQL).replace(
        "f.sales_month = 'Aug 2027'", "f.horizon_months = 1"), None, [])[0] == ""    # 0 rows, no month named


def _example_questions(chunk):
    """The question of a docs example and its "Also asked as" questions."""
    questions = [chunk["heading"].removeprefix("Q: ")]
    also = re.search(r"Also asked as: (.*)", chunk["text"])
    return questions + ([q.strip() for q in also.group(1).rstrip(".").split(";")] if also else [])


@pytest.mark.parametrize("chunk", forecast_examples(), ids=lambda c: c["heading"])
def test_every_forecast_example_of_the_docs_passes_both_checks(chunk):
    sql = strip_fences(chunk["text"])
    for question in _example_questions(chunk):
        for each in (sql, sql_of(sql)):
            assert agent.forecast_level_problem(question, each, LEVELS)[0] == "", question
            assert agent.forecast_level_problem(question, each, LEVELS, [])[0] == "", question
    assert agent.product_forecast_months(sql_of(sql), LEVELS) == ""


def test_the_mcp_server_flags_the_17_07_query(monkeypatch):
    monkeypatch.setattr(agent, "forecast_levels", lambda: LEVELS)
    problems = mcp_server.looks_wrong(sql_of(PRODUCT_SQL))
    assert ("Aug 2027 has no product forecast, only a TOTAL one: for the company total use level = 'TOTAL' (12 sales "
            "months Nov 2026 - Oct 2027); product forecasts (level 'PRODUCT') exist only for the top 10 products, "
            "Nov 2026 - Jan 2027.") in problems
    for sql in (TOTAL_SQL, GCI_SQL, PRODUCT_SQL.replace("Aug 2027", "Dec 2026"),     # a product month: fine
                PRODUCT_SQL.replace("Aug 2027", "Nov 2027")):                         # not forecast at all
        assert not any("no product forecast" in p for p in mcp_server.looks_wrong(sql_of(sql)))


def test_the_mcp_server_reads_nothing_for_other_queries(monkeypatch):
    monkeypatch.setattr(agent, "forecast_levels", lambda: pytest.fail("no read for these queries"))
    for sql in (TOTAL_SQL, GCI_SQL, "SELECT SUM(il.net_taxable_value) FROM fact_invoice_lines il"):
        mcp_server.looks_wrong(sql_of(sql))


# ---------- in the graph ----------

@pytest.fixture
def forecast_db(monkeypatch, mysql):
    """The tables with the ml_ ones, today 17-Nov-2026, and the forecast levels of 18-Nov (counted reads)."""
    monkeypatch.setattr(agent, "today", lambda: TODAY)
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: ALLOWED)
    mysql.level_reads = []
    monkeypatch.setattr(agent, "forecast_levels", lambda: mysql.level_reads.append(1) or LEVELS)
    return mysql


def test_the_17_07_query_is_sent_back_and_the_total_query_is_answered(monkeypatch, forecast_db, user, steps):
    forecast_db.results = [AUG_ROWS]
    fake = use_fake_ai(monkeypatch, [(f"```sql\n{PRODUCT_SQL}\n```", 3000), (f"```sql\n{TOTAL_SQL}\n```", 3100),
                                     (AUG_ANSWER, 800)])

    result = agent.ask(QUESTION, user)

    assert steps == DATA_START + ["write_sql", "check_sql", "retry", "write_sql", "check_sql", "run_sql", "explain"]
    assert len(forecast_db.calls) == 1 and "'TOTAL'" in forecast_db.calls[0]          # the PRODUCT query never ran
    assert LEVEL_PROBLEM in fake.calls[1][-1]["content"]
    assert result.status == "ok" and result.rows == AUG_ROWS["rows"] and result.tries == 2
    assert result.answer == AUG_ANSWER
    assert len(forecast_db.level_reads) == 1                                          # read once per question


def test_it_is_sent_back_only_once(monkeypatch, forecast_db, user, steps):
    forecast_db.results = [NO_ROWS]
    fake = use_fake_ai(monkeypatch, [(f"```sql\n{PRODUCT_SQL}\n```", 3000)] * 2 + [("No rows came back.", 800)])

    result = agent.ask(QUESTION, user)

    # the model insisted: it runs, and its 0 rows are not sent back a second time
    assert steps == DATA_START + ["write_sql", "check_sql", "retry", "write_sql", "check_sql", "run_sql",
                                  "check_names", "explain"]
    assert len(forecast_db.calls) == 1 and result.status == "ok" and result.tries == 2 and len(fake.calls) == 3


def test_0_rows_for_a_total_forecast_month_are_sent_back_once(monkeypatch, forecast_db, user, steps):
    forecast_db.results = [NO_ROWS, AUG_ROWS]
    fake = use_fake_ai(monkeypatch, [(f"```sql\n{JOINED_SQL}\n```", 3000), (f"```sql\n{TOTAL_SQL}\n```", 3100),
                                     (AUG_ANSWER, 800)])

    result = agent.ask(QUESTION, user)

    assert steps == DATA_START + ["write_sql", "check_sql", "run_sql", "retry", "write_sql", "check_sql", "run_sql",
                                  "explain"]
    assert len(forecast_db.calls) == 2 and "dim_products" in forecast_db.calls[0]
    assert MONTH_PROBLEM in fake.calls[1][-1]["content"]
    assert result.status == "ok" and result.rows == AUG_ROWS["rows"] and result.tries == 2
    assert result.answer == AUG_ANSWER and len(forecast_db.level_reads) == 1


def test_when_the_next_try_finds_nothing_either_the_first_answer_is_kept(monkeypatch, forecast_db, user, steps):
    forecast_db.results = [NO_ROWS, {**NO_ROWS, "columns": ["sales_month"]}]
    fake = use_fake_ai(monkeypatch, [(f"```sql\n{JOINED_SQL}\n```", 3000), (f"```sql\n{JOINED_SQL} \n```", 3100),
                                     ("There is no product forecast for Aug 2027.", 800)])

    result = agent.ask(QUESTION, user)

    assert steps[-3:] == ["run_sql", "keep_first_answer", "explain"] and steps.count("retry") == 1
    assert result.status == "ok" and result.rows == [] and result.columns == NO_ROWS["columns"]
    assert len(fake.calls) == 3


def test_a_product_question_is_not_flagged(monkeypatch, forecast_db, user, steps):
    gci = {"columns": ["product_code", "product_description", "sales_month", "forecast_inr", "low_inr", "high_inr",
                       "matches"],
           "rows": [["FG01484", PRODUCTS[0].split(" ", 1)[1], "Nov 2026", Decimal("16517213.63"),
                     Decimal("14327784.52"), Decimal("18862236.33"), 1]], "truncated": False}
    forecast_db.results = [gci]
    answer = "The forecast for FG01484 GCI TX-675-3A in sales month Nov 2026 is about INR 1.65 Cr."
    use_fake_ai(monkeypatch, [(f"```sql\n{GCI_SQL}\n```", 3000), (answer, 800)])

    result = agent.ask("forecast for GCI TX-675 next month", user)

    assert steps == DATA_START + ["write_sql", "check_sql", "run_sql", "explain"]
    assert result.status == "ok" and result.answer == answer and result.tries == 1


def test_a_month_beyond_the_forecast_keeps_its_0_row_answer_with_the_forecast_months(monkeypatch, forecast_db, user,
                                                                                    steps):
    asked = _note_router(monkeypatch, forecast_db, NOTE_ROWS)   # the real forecast months note
    forecast_db.results = [NO_ROWS]
    answer = "Sales month Nov 2027 is not forecast: the forecast covers Nov 2026 to Oct 2027."
    fake = use_fake_ai(monkeypatch, [(f"```sql\n{JOINED_SQL.replace('Aug 2027', 'Nov 2027')}\n```", 3000),
                                     (answer, 800)])

    result = agent.ask("What is the sales forecast for November 2027?", user)

    assert steps == DATA_START + ["write_sql", "check_sql", "run_sql", "check_names", "explain"]
    assert result.status == "ok" and result.rows == [] and result.answer == answer and result.tries == 1
    assert len(asked) == 1
    assert "Forecast months available (worked out by the app): " + NOTE in fake.calls[1][-1]["content"]
