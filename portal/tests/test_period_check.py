"""A "this year" / "last year" question whose SQL filters a calendar year is sent back once (portal/period_check.py).

19-Nov-2026: "What is our total sales to Sakura Pump Japan this year, and which products do they buy?" got
YEAR(il.invoice_date) = 2026 and the answer "In calendar year 2026 ... 18.0 Cr"; the business rule says "this year"
= the current financial year (FY 2026-27, from 01-Apr-2026). The check runs on the SQL before MySQL
(lc/graph.check_sql) and must stay quiet for FY SQL, named years / months, "calendar year" and the ML tables.

The AI is the fake one of test_agent.py (FakeAI behind LangChain); MySQL and the notes search are faked.
Run with:  python -m pytest -q portal/tests/test_period_check.py
"""
from datetime import date
from decimal import Decimal

import pytest

from portal import period_check
from portal.lc import graph
from portal.rag import agent, sql_guard, warehouse
from portal.tests.test_agent import mysql, use_fake_ai  # noqa: F401
from portal.tests.test_graph import DATA_START, steps  # noqa: F401

TODAY = date(2026, 11, 19)
QUESTION = "What is our total sales to Sakura Pump Japan this year, and which products do they buy?"
TABLES = {"dim_customers", "dim_calendar", "fact_invoice_lines", "dim_products"}

SELECT = ("SELECT p.product_description, ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr\n"
          "FROM fact_invoice_lines il\nJOIN dim_customers cu ON cu.customer_id = il.customer_id\n"
          "JOIN dim_products p ON p.product_id = il.product_id\n"
          "JOIN dim_calendar c ON c.date_id = il.invoice_date_id\n")
GROUP = "\nGROUP BY p.product_id, p.product_description ORDER BY net_sales_inr DESC"
NAME = "cu.customer_name = 'Sakura Pump Japan Co., Ltd.'"  # an exact name (a LIKE has its own check)

# the 19-Nov query, and other ways to write a calendar year
CALENDAR_SQL = SELECT + f"WHERE {NAME} AND YEAR(il.invoice_date) = 2026" + GROUP
CALENDAR_VARIANTS = [
    CALENDAR_SQL,
    SELECT + f"WHERE {NAME} AND YEAR(il.invoice_date) = YEAR(CURDATE()) AND il.invoice_date <= CURDATE()" + GROUP,
    SELECT + f"WHERE {NAME} AND il.invoice_date BETWEEN '2026-01-01' AND CURDATE()" + GROUP,
    SELECT + f"WHERE {NAME} AND il.invoice_date >= '2026-01-01' AND il.invoice_date < '2027-01-01'" + GROUP,
    SELECT + f"WHERE {NAME} AND c.calendar_year = 2026" + GROUP,
    SELECT + f"WHERE {NAME} AND c.calendar_year = YEAR(CURDATE())" + GROUP,
    SELECT + f"WHERE {NAME} AND EXTRACT(YEAR FROM il.invoice_date) = 2026" + GROUP,
    SELECT + f"WHERE {NAME} AND DATE_FORMAT(il.invoice_date, '%Y') = '2026'" + GROUP,
    SELECT + f"WHERE {NAME} AND il.invoice_date >= MAKEDATE(YEAR(CURDATE()), 1)" + GROUP,
    SELECT + f"WHERE {NAME} AND il.invoice_date >= DATE_FORMAT(CURDATE(), '%Y-01-01')" + GROUP,
    SELECT + f"WHERE {NAME} AND il.invoice_date >= CONCAT(YEAR(CURDATE()), '-01-01')" + GROUP,
    SELECT + f"WHERE {NAME} AND il.invoice_date >= DATE_SUB(CURDATE(), INTERVAL DAYOFYEAR(CURDATE()) - 1 DAY)" + GROUP,
    SELECT + f"WHERE {NAME} AND LEFT(il.invoice_date, 4) = '2026'" + GROUP,
    SELECT + f"WHERE {NAME} AND il.invoice_date LIKE '2026%'" + GROUP,
]
# the right queries: the financial year
FY_SQL = SELECT + f"WHERE {NAME} AND c.financial_year = '2627' AND il.invoice_date <= CURDATE()" + GROUP
FY_VARIANTS = [
    FY_SQL,
    SELECT + f"WHERE {NAME} AND c.financial_year = (SELECT financial_year FROM dim_calendar WHERE full_date = CURDATE())"
    + GROUP,
    SELECT + f"WHERE {NAME} AND il.invoice_date BETWEEN '2026-04-01' AND CURDATE()" + GROUP,
    SELECT + f"WHERE {NAME} AND il.invoice_date >= MAKEDATE(YEAR(CURDATE()) - (MONTH(CURDATE()) < 4), 1)"
             " + INTERVAL 3 MONTH" + GROUP,
    SELECT + f"WHERE {NAME} AND c.financial_year_label = 'FY 2026-27'" + GROUP,
    # FY start worked out from YEAR(CURDATE()) - the YEAR() is not a calendar-year filter here
    SELECT + f"WHERE {NAME} AND il.invoice_date >= CONCAT(YEAR(CURDATE()) - (MONTH(CURDATE()) < 4), '-04-01')" + GROUP,
    SELECT + f"WHERE {NAME} AND c.sales_year = '2627'" + GROUP,
    # the docs/sql_examples.md "this year and last year" query (dates only)
    "WITH coverage AS (SELECT SUM(CASE WHEN il.invoice_date >= '2026-04-01' THEN il.net_taxable_value ELSE 0 END) "
    "AS this_fy_inr FROM fact_invoice_lines il WHERE il.invoice_date BETWEEN '2025-04-01' AND '2027-03-31') "
    "SELECT * FROM coverage",
    SELECT + f"WHERE {NAME}" + GROUP,                                         # no year filter at all
    SELECT + f"WHERE LEFT(cu.customer_name, 4) = 'Saku'" + GROUP,             # LEFT of a name, not of a date
]


@pytest.fixture
def tables(mysql, monkeypatch):
    """The fake MySQL also has the products table; today is 19-Nov-2026."""
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: TABLES)
    monkeypatch.setattr(agent, "today", lambda: TODAY)
    return mysql


@pytest.fixture(autouse=True)
def no_answer_check(monkeypatch):
    """The fake answers are short made-up texts: the answer check (answer_verify.py) has its own tests."""
    from portal import answer_verify
    monkeypatch.setattr(answer_verify, "applies", lambda *args, **kwargs: False)


def cleaned(sql):
    """The SQL as the guard hands it to the check (sqlglot writes it again: CURRENT_DATE, AS, new lines)."""
    return sql_guard.check_sql(sql, TABLES)


# ---------- the question ----------

@pytest.mark.parametrize("question, words", [
    (QUESTION, ["this year"]),
    ("how much did we sell last year", ["last year"]),
    ("this year's sales of Sakura Pump", ["this year"]),
    ("sales this year vs last year", ["this year", "last year"]),
    ("current year sales by state", ["this year"]),
    ("previous year export sales", ["last year"]),
    ("prior year revenue", ["last year"]),
    ("THIS YEAR top customers", ["this year"]),
    ("sales this yr", ["this year"]),
    ("which products may sell this year", ["this year"]),                       # "may" is not May
])
def test_this_year_and_last_year_are_found(question, words):
    assert period_check.year_words(question) == words


@pytest.mark.parametrize("question", [
    "sales this calendar year", "calendar year 2026 sales", "sales in calendar-year terms this year",
    "sales in 2026", "sales this year (2026)", "sales in FY 2025-26 and last year", "sales FY26 vs last year",
    "sales in '26", "Oct sales this year", "sales in October last year", "sales in May this year",
    "sales from 01/04/2026 this year", "sales this month", "sales this quarter", "this month vs same month last year",
    "sales of the last 12 months", "last year q1 sales", "ytd sales this year", "sales today", "sales last 3 years",
    "this financial year sales", "sales of the past year", "", None,
])
def test_a_named_period_or_another_period_is_not(question):
    assert period_check.year_words(question) == []


# ---------- the SQL ----------

@pytest.mark.parametrize("sql", CALENDAR_VARIANTS)
def test_a_calendar_year_filter_is_found(sql):
    assert period_check.calendar_year_filter(sql)
    assert period_check.calendar_year_filter(cleaned(sql))               # also after the guard wrote it again


@pytest.mark.parametrize("sql", FY_VARIANTS)
def test_a_financial_year_or_no_year_filter_is_not(sql):
    assert period_check.calendar_year_filter(sql) == ""
    assert period_check.calendar_year_filter(cleaned(sql)) == ""


@pytest.mark.parametrize("sql", [
    "SELECT forecast_month, forecast_inr FROM ml_sales_forecast WHERE YEAR(forecast_month) = 2027",
    "SELECT f.* FROM ml_sales_forecast f JOIN dim_calendar c ON c.full_date = f.forecast_month "
    "WHERE c.calendar_year = 2026",
])
def test_ml_tables_are_never_checked(sql):
    assert period_check.calendar_year_filter(sql) == ""
    assert period_check.problem("forecast for this year", sql, TODAY) == ""


# ---------- the problem text ----------

def test_the_19_nov_query_gets_the_financial_year_problem():
    text = period_check.problem(QUESTION, cleaned(CALENDAR_SQL), TODAY)
    assert text.startswith('the question says "this year", but your query filters by a calendar year '
                           "(YEAR(il.invoice_date) = 2026)")
    assert "current financial year FY 2026-27 (01-Apr-2026 to 31-Mar-2027; dim_calendar.financial_year = '2627')" in text
    assert "not calendar year 2026" in text and "'2026-04-01'" in text and "CURDATE()" in text
    assert '"What were total net sales this year and last year, and how much did they grow?"' in text
    assert "FY 2025-26" not in text                                     # no "last year" in the question


def test_last_year_names_the_previous_financial_year():
    sql = SELECT + f"WHERE {NAME} AND YEAR(il.invoice_date) = YEAR(CURDATE()) - 1" + GROUP
    text = period_check.problem("sales to Sakura Pump last year", cleaned(sql), TODAY)
    assert text.startswith('the question says "last year"')
    assert "FY 2025-26 (01-Apr-2025 to 31-Mar-2026; financial_year = '2526'), not calendar year 2025" in text
    assert "WHERE c.financial_year = '2526' (or the dates from '2025-04-01')" in text
    assert "not over yet" not in text                                   # FY 2025-26 is over


@pytest.mark.parametrize("day, label, start", [
    (date(2026, 11, 19), "FY 2026-27", "01-Apr-2026"),
    (date(2027, 2, 10), "FY 2026-27", "01-Apr-2026"),              # Jan-Mar belong to the FY that began last April
    (date(2027, 3, 31), "FY 2026-27", "01-Apr-2026"),
    (date(2027, 4, 1), "FY 2027-28", "01-Apr-2027"),
    (date(2030, 6, 1), "FY 2030-31", "01-Apr-2030"),
])
def test_the_financial_year_comes_from_today(day, label, start):
    text = period_check.problem(QUESTION, CALENDAR_SQL, day)
    assert f"{label} ({start}" in text and f"not calendar year {day.year}" in text


@pytest.mark.parametrize("question, sql", [
    (QUESTION, FY_SQL),                                                         # right SQL
    ("total sales to Sakura Pump in calendar year 2026", CALENDAR_SQL),         # the user asked for it
    ("total sales to Sakura Pump this calendar year", CALENDAR_SQL),
    ("total sales to Sakura Pump in 2026", CALENDAR_SQL),                       # a named year
    ("sales to Sakura Pump in Jan this year", CALENDAR_SQL),                    # a named month
    ("sales to Sakura Pump this month", CALENDAR_SQL),                          # another period
    ("sales to Sakura Pump this quarter", CALENDAR_SQL),
    ("total sales to Sakura Pump", CALENDAR_SQL),                               # no "this year"
])
def test_nothing_is_sent_back(question, sql):
    assert period_check.problem(question, cleaned(sql), TODAY) == ""


# ---------- in the graph ----------

ROWS = {"columns": ["product_description", "net_sales_inr"],
        "rows": [["Coolant pump GX-664-1B 0.75kW (415V 50Hz)", Decimal("12000000.00")],
                 ["Hydraulic pump HP-20", Decimal("6000000.00")]],
        "truncated": False}
ANSWER = "In FY 2026-27 so far we sold INR 1,80,00,000.00 to Sakura Pump Japan: Coolant pump and Hydraulic pump."
SENT_BACK = 'That did not work: the question says "this year", but your query filters by a calendar year'


def fenced(sql):
    return f"```sql\n{sql}\n```"


def test_the_19_nov_query_is_sent_back_once_and_the_fy_query_is_answered(monkeypatch, tables, user, steps):
    tables.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [fenced(CALENDAR_SQL), fenced(FY_SQL), ANSWER])

    result = agent.ask(QUESTION, user)

    assert steps == DATA_START + ["write_sql", "check_sql", "retry", "write_sql", "check_sql", "run_sql", "explain"]
    second = fake.calls[1][-1]["content"]
    assert second.startswith(SENT_BACK) and "FY 2026-27" in second and "financial_year = '2627'" in second
    assert len(tables.calls) == 1 and "financial_year = '2627'" in tables.calls[0]   # the calendar SQL never ran
    assert result.status == "ok" and result.tries == 2 and result.rows == ROWS["rows"] and result.answer == ANSWER


def test_a_second_calendar_query_is_not_sent_back_again(monkeypatch, tables, user, steps):
    tables.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [fenced(CALENDAR_SQL), fenced(CALENDAR_SQL), ANSWER])

    result = agent.ask(QUESTION, user)

    assert steps.count("retry") == 1 and steps[-2:] == ["run_sql", "explain"]
    assert result.status == "ok" and result.tries == 2 and len(fake.calls) == 3 and len(tables.calls) == 1


def test_the_fy_query_is_not_sent_back(monkeypatch, tables, user, steps):
    tables.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [fenced(FY_SQL), ANSWER])

    result = agent.ask(QUESTION, user)

    assert steps == DATA_START + ["write_sql", "check_sql", "run_sql", "explain"]
    assert result.status == "ok" and result.tries == 1 and len(fake.calls) == 2


def test_graph_state_has_the_check_unused():
    assert not graph.start_state(agent.AskResult(text="x")).get("fy_check_used")
