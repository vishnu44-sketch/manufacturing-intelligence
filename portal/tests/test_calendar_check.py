"""A period list of LIMIT n calendar DAYS is never run, and a chart of several periods with one row is sent back.

16-Nov (office PC): "can you plot a bar graph for the last 6 month of sales" got LIMIT 6 of dim_calendar (one row
per DAY): 6 days of Oct 2026, the sales joined to them counted 6 times - Oct 2026 shown as INR 14,202,579,885.00
(6 x 2,367,096,647.50) in one row, so no bar chart either. The prompt rule 17 of 05-Nov was not followed, so it is
now also a check in our own code (agent.calendar_limit_periods, lc/graph.check_sql), and the 1-row retry covers
every chart of several periods (lc/graph.several_periods_chart_request), not only a line chart.

The AI is the fake one of test_agent.py (FakeAI behind LangChain); MySQL and the notes search are faked.
Run with:  python -m pytest -q portal/tests/test_calendar_check.py
"""
from decimal import Decimal

import pytest

from portal.lc import graph
from portal.rag import agent
from portal.tests.test_agent import mysql, use_fake_ai  # noqa: F401
from portal.tests.test_graph import DATA_START, TREND_ANSWER, TREND_ROWS, TREND_SQL, steps  # noqa: F401

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question

QUESTION = "can you plot a bar graph for the last 6 month of sales"

# the query of 16-Nov, as the AI wrote it: the list of "6 months" is LIMIT 6 of calendar DAYS
SIX_DAYS_SQL = ("```sql\nWITH recent_months AS (\n  SELECT c.nop_sales_month, c.nop_sales_period_start, c.nop_sales_period_end\n"
                "  FROM dim_calendar AS c\n  WHERE c.nop_sales_period_end <= CURRENT_DATE\n"
                "  ORDER BY c.nop_sales_period_end DESC\n  LIMIT 6\n)\n"
                "SELECT rm.nop_sales_month, rm.nop_sales_period_start AS period_start, rm.nop_sales_period_end AS period_end,\n"
                "  ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr\nFROM recent_months AS rm\n"
                "JOIN dim_calendar AS c ON c.nop_sales_month = rm.nop_sales_month\n"
                "JOIN fact_invoice_lines AS il ON il.invoice_date_id = c.date_id\n"
                "GROUP BY rm.nop_sales_month, rm.nop_sales_period_start, rm.nop_sales_period_end\n```")
ONE_MONTH_SQL = ("```sql\nSELECT c.nop_sales_month, ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr\n"
                 "FROM fact_invoice_lines il\nJOIN dim_calendar c ON c.date_id = il.invoice_date_id\n"
                 "WHERE c.nop_sales_month = 'Oct 2026'\nGROUP BY c.nop_sales_month\n```")
ONE_ROW = {"columns": ["nop_sales_month", "net_sales_inr"], "rows": [["Oct 2026", Decimal("2367096647.50")]],
           "truncated": False}


# ---------- the check ----------

def sql_of(reply):
    return agent.strip_fences(reply)


@pytest.mark.parametrize("sql, expected", [
    (sql_of(SIX_DAYS_SQL), ("nop_sales_month", 6)),                                   # 16-Nov
    ("SELECT c.nop_sales_month FROM dim_calendar AS c WHERE c.nop_sales_period_end <= CURRENT_DATE "
     "ORDER BY c.nop_sales_period_end DESC LIMIT 3", ("nop_sales_month", 3)),          # 05-Nov
    ("SELECT x.m FROM (SELECT c.month_year AS m FROM dim_calendar c ORDER BY c.full_date DESC LIMIT 12) x",
     ("month_year", 12)),                                                               # in a subquery
    ("SELECT c.financial_year, c.fiscal_quarter FROM dim_calendar c JOIN fact_invoice_lines il "
     "ON il.invoice_date_id = c.date_id ORDER BY c.full_date DESC LIMIT 4", ("financial_year", 4)),
])
def test_a_limit_of_calendar_days_used_as_periods_is_found(sql, expected):
    assert agent.calendar_limit_periods(sql) == expected


@pytest.mark.parametrize("sql", [
    # the right way: one row per period first, then the limit
    "SELECT DISTINCT c.nop_sales_month, c.nop_sales_period_end FROM dim_calendar c "
    "WHERE c.nop_sales_period_end <= CURRENT_DATE ORDER BY c.nop_sales_period_end DESC LIMIT 6",
    "SELECT c.nop_sales_month FROM dim_calendar c WHERE c.nop_sales_period_end <= CURRENT_DATE "
    "GROUP BY c.nop_sales_month, c.nop_sales_period_end ORDER BY c.nop_sales_period_end DESC LIMIT 6",
    # LIMIT 1: one value, e.g. the last complete month
    "SELECT SUM(il.net_taxable_value) FROM fact_invoice_lines il JOIN dim_calendar c ON c.date_id = il.invoice_date_id "
    "WHERE c.nop_sales_month = (SELECT c2.nop_sales_month FROM dim_calendar c2 WHERE c2.nop_sales_period_end <= "
    "CURRENT_DATE ORDER BY c2.nop_sales_period_end DESC LIMIT 1)",
    # days asked as days
    "SELECT c.full_date FROM dim_calendar c ORDER BY c.full_date DESC LIMIT 7",
    # a top 10 of something else
    "SELECT cu.customer_name, SUM(il.net_taxable_value) AS s FROM fact_invoice_lines il JOIN dim_customers cu "
    "ON cu.customer_id = il.customer_id GROUP BY cu.customer_name ORDER BY s DESC LIMIT 10",
    "not sql at all (",
])
def test_the_right_period_lists_and_other_limits_are_fine(sql):
    assert agent.calendar_limit_periods(sql) is None


def test_the_problem_says_how_to_build_the_list():
    text = agent.CALENDAR_LIMIT_PROBLEM.format(column="nop_sales_month", limit=6)
    assert "ONE ROW PER DAY" in text and "6 DAYS" in text and "counts the sales 6 times" in text
    assert "SELECT DISTINCT nop_sales_month" in text and "LIMIT 6" in text


# ---------- in the graph: sent back before it runs ----------

def test_the_16_nov_query_is_sent_back_before_it_runs_and_the_fixed_one_is_answered(monkeypatch, mysql, user, steps):
    mysql.results = [TREND_ROWS]
    fake = use_fake_ai(monkeypatch, [(SIX_DAYS_SQL, 3000), (TREND_SQL, 3100), (TREND_ANSWER, 800)])

    result = agent.ask(QUESTION, user)

    assert steps == DATA_START + ["write_sql", "check_sql", "retry", "write_sql", "check_sql", "run_sql", "explain"]
    assert len(mysql.calls) == 1                                       # the 6-days query never ran
    second = fake.calls[1][-1]["content"]
    assert "dim_calendar has ONE ROW PER DAY" in second and "LIMIT 6" in second
    assert result.status == "ok" and result.rows == TREND_ROWS["rows"] and result.tries == 2


def test_it_is_never_run_also_on_the_last_try(monkeypatch, mysql, user):
    use_fake_ai(monkeypatch, [(SIX_DAYS_SQL, 3000)] * agent.MAX_TRIES)

    result = agent.ask(QUESTION, user)

    assert mysql.calls == []                                           # no number 6 times too big, ever
    assert result.status == "error" and result.rows == []


# ---------- a chart of several periods with one row ----------

@pytest.mark.parametrize("text", [
    QUESTION, "monthly sales as a pie chart", "sales by month bar chart",
    "sales of the last 3 nop months as a donut chart", "show a graph of each month's sales",
    "net sales line chart",                                            # a line chart, as before
])
def test_a_chart_of_several_periods_is_found(text):
    assert graph.several_periods_chart_request(text)


@pytest.mark.parametrize("text", [
    "net sales of Oct 2026 as a bar chart",                            # one period: one bar is right
    "top customers last 6 months",                                     # no chart asked
    "pie chart of sales by state", "", None,
])
def test_one_period_or_no_chart_is_not(text):
    assert not graph.several_periods_chart_request(text)


def test_a_bar_chart_of_6_months_with_one_row_is_sent_back_once(monkeypatch, mysql, user, steps):
    mysql.results = [ONE_ROW, TREND_ROWS]
    fake = use_fake_ai(monkeypatch, [(ONE_MONTH_SQL, 3000), (TREND_SQL, 3100), (TREND_ANSWER, 800)])

    result = agent.ask(QUESTION, user)

    assert steps == DATA_START + ["write_sql", "check_sql", "run_sql", "retry",
                                  "write_sql", "check_sql", "run_sql", "explain"]
    assert fake.calls[1][-1]["content"].startswith("That did not work: " + graph.ONE_ROW_LINE_CHART_PROBLEM)
    assert result.status == "ok" and result.rows == TREND_ROWS["rows"]


def test_a_bar_chart_of_one_month_with_one_row_is_answered_as_it_is(monkeypatch, mysql, user):
    mysql.results = [ONE_ROW]
    fake = use_fake_ai(monkeypatch, [(ONE_MONTH_SQL, 3000), ("Net sales of Oct 2026 were INR 2,367,096,647.50.", 700)])

    result = agent.ask("net sales of Oct 2026 as a bar chart", user)

    assert result.status == "ok" and len(result.rows) == 1 and len(fake.calls) == 2
