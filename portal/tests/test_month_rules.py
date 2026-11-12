"""The "past months" rules of the prompts (05-Nov): dim_calendar has one row per DAY.

"who is our most valable customer past months" got LIMIT 3 of plain dim_calendar rows - 3 DAYS, all in Oct 2026 -
and its line chart joined the sales to those 3 days of one month, so every Oct sale counted 3 times and only one
row came back (no chart). SQL rule 17 + the end of rule 16, the rewrite's chart bullet and one answer sentence
are checked here. The AI is always the fake one of test_agent.py; MySQL and the docs search are faked.
Run with:  python -m pytest -q portal/tests/test_month_rules.py
"""
import re

import pytest

from portal import mcp_server
from portal.lc import prompts
from portal.lc.memory import ChatHistory
from portal.models import Conversation, Question
from portal.rag import agent
from portal.rag.sql_guard import check_sql
from portal.tests.test_agent import TABLES, mysql, use_fake_ai  # noqa: F401

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question

# the period list of rule 17: one row per NOP month (checked on the real data: Oct, Sep, Aug 2026)
MONTHS = ("SELECT DISTINCT nop_sales_month, nop_sales_period_start, nop_sales_period_end FROM dim_calendar "
          "WHERE nop_sales_period_end <= CURRENT_DATE ORDER BY nop_sales_period_end DESC LIMIT 3")
TOP_SQL = (f"WITH m AS ({MONTHS}) SELECT cu.customer_name, ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr, "
           "(SELECT MIN(nop_sales_period_start) FROM m) AS period_from, (SELECT MAX(nop_sales_period_end) FROM m) "
           "AS period_to FROM fact_invoice_lines il JOIN dim_calendar c ON c.date_id = il.invoice_date_id "
           "JOIN m ON m.nop_sales_month = c.nop_sales_month JOIN dim_customers cu ON cu.customer_id = il.customer_id "
           "GROUP BY cu.customer_name ORDER BY net_sales_inr DESC LIMIT 1")
TOP_ANSWER = ("In the last 3 NOP months (Aug 2026 to Oct 2026) the most valuable customer was Allied Castings Limited "
              "with INR 63,648,019.00.")
# the line chart: the period list LEFT JOIN that customer's sales summed per month, 0 for a month without sales
CHART_SQL = ("```sql\n"
             f"WITH m AS ({MONTHS}),\n"
             "s AS (SELECT c.nop_sales_month, SUM(il.net_taxable_value) AS v FROM fact_invoice_lines il\n"
             "      JOIN dim_calendar c ON c.date_id = il.invoice_date_id\n"
             "      JOIN dim_customers cu ON cu.customer_id = il.customer_id\n"
             "      WHERE cu.customer_name LIKE '%Allied Castings%' GROUP BY c.nop_sales_month)\n"
             "SELECT m.nop_sales_month, ROUND(COALESCE(s.v, 0), 2) AS net_sales_inr\n"
             "FROM m LEFT JOIN s ON s.nop_sales_month = m.nop_sales_month\n"
             "ORDER BY m.nop_sales_period_end\n```")
CHART_ROWS = {"columns": ["nop_sales_month", "net_sales_inr"],  # the real numbers of 05-Nov
              "rows": [["Aug 2026", "0.00"], ["Sep 2026", "0.00"], ["Oct 2026", "63,648,019.00"]],
              "truncated": False}
CHART_UNDERSTOOD = "Monthly net sales of the top customer of the last 3 NOP months as a line chart"
CHART_ANSWER = ("In the last 3 NOP months (Aug 2026 to Oct 2026) Allied Castings Limited bought nothing in Aug 2026 "
                "and Sep 2026 and INR 63,648,019.00 in Oct 2026.")


# ---------- the prompt texts ----------

def test_rule_17_says_dim_calendar_has_one_row_per_day_and_how_to_list_periods():
    prompt = agent.SQL_SYSTEM_PROMPT
    assert "17. dim_calendar has ONE ROW PER DAY." in prompt
    assert "A list of the last N NOP months (or months, quarters) must have one row per period" in prompt
    assert ("SELECT DISTINCT nop_sales_month, nop_sales_period_start, nop_sales_period_end FROM dim_calendar "
            "WHERE nop_sales_period_end <= CURRENT_DATE ORDER BY nop_sales_period_end DESC LIMIT N") in prompt
    assert "Never LIMIT plain dim_calendar rows to get periods" in prompt
    assert ("never JOIN fact rows to a period list with more than one row per period (it counts the sales 2-3 times)"
            in prompt)


def test_past_months_with_no_number_are_the_last_3_complete_nop_months_and_are_named():
    prompt = agent.SQL_SYSTEM_PROMPT
    assert '"Past / last / recent months" with no number = the last 3 complete NOP sales months up to today' in prompt
    assert "period_from / period_to" in prompt
    assert 'For "past / last months" name the months used' in agent.EXPLAIN_SYSTEM_PROMPT
    assert '"In the last 3 NOP months (Aug 2026 to Oct 2026) ..."' in agent.EXPLAIN_SYSTEM_PROMPT


def test_a_line_chart_over_several_periods_is_one_row_per_period_with_0_for_no_sales():
    prompt = agent.SQL_SYSTEM_PROMPT
    assert ("A line chart or trend of an earlier answer over several periods (e.g. the top customer of the last 3 "
            "NOP months) = one row per period for that same customer / item, ordered by period, with 0 for a period "
            "without sales") in prompt
    assert "LEFT JOIN that customer's sales summed per period, COALESCE(..., 0)" in prompt
    # rule 16 itself is unchanged
    assert "A bar, pie or KPI of one period, or a line chart of several periods, stays as asked." in prompt


def test_the_sql_rules_are_numbered_1_to_17_and_17_is_the_last():
    rules = agent.SQL_SYSTEM_PROMPT.split("Rules for the SQL:\n", 1)[1]
    numbers = [int(n) for n in re.findall(r"^(\d+)\. ", rules, re.M)]
    assert numbers == list(range(1, 18))


def test_the_rewrite_keeps_the_number_of_periods_and_the_customer_of_a_chart_follow_up():
    prompt = agent.REWRITE_SYSTEM_PROMPT
    assert "A chart of an answer over several periods keeps their number and the customer / item" in prompt
    assert '("past months" with no number = the last 3 NOP months)' in prompt
    assert '"Monthly net sales of the top customer of the last 3 NOP months as a line chart"' in prompt
    # the earlier chart examples are still there
    assert '"Net sales of the last 6 NOP months up to Oct 2026 as a line chart"' in prompt


def test_the_new_rules_reach_langchain_and_the_mcp_server():
    system = prompts.SQL_PROMPT.format_messages(schema="s", count=1, documents="d", today="05-Nov-2026",
                                                preferences="", earlier="", question="q")[0].content
    assert "17. dim_calendar has ONE ROW PER DAY." in system
    assert "17. dim_calendar has ONE ROW PER DAY." in mcp_server.SQL_RULES
    assert 'For "past / last months" name the months used' in mcp_server.ANSWER_RULES


def test_the_period_list_and_the_chart_sql_pass_the_guard():
    assert "SELECT DISTINCT" in check_sql(MONTHS, TABLES).upper()
    assert "LEFT JOIN" in check_sql(CHART_SQL, TABLES).upper()
    assert check_sql(TOP_SQL, TABLES)


# ---------- the 05-Nov chat with a fake AI ----------

def past_months_chat(user):
    """The 05-Nov chat: the most valuable customer of the past months, answered with the period list of rule 17."""
    chat = Conversation.objects.create(user=user, title="chat")
    Question.objects.create(user=user, conversation=chat, text="who is our most valable customer past months",
                            answer=TOP_ANSWER, sql=TOP_SQL, status="ok")
    return chat


def test_a_line_chart_of_the_past_months_answer_gives_one_row_per_month(monkeypatch, mysql, user):
    mysql.results = [CHART_ROWS]
    fake = use_fake_ai(monkeypatch, [CHART_UNDERSTOOD, CHART_SQL, CHART_ANSWER])

    result = agent.ask("for that above answer create one line chart", user,
                       context=ChatHistory.for_chat(past_months_chat(user)))

    assert result.status == "ok" and result.answer == CHART_ANSWER
    assert result.understood_as == CHART_UNDERSTOOD
    assert [row[0] for row in result.rows] == ["Aug 2026", "Sep 2026", "Oct 2026"]   # one row per month, 0s kept
    rewrite, sql_call = fake.calls[0], fake.calls[1]
    assert rewrite[0]["content"] == agent.REWRITE_SYSTEM_PROMPT
    assert "who is our most valable customer past months (latest)" in rewrite[-1]["content"]
    assert sql_call[0]["content"] == agent.SQL_SYSTEM_PROMPT                         # with rule 17
    request = sql_call[-1]["content"]
    assert CHART_UNDERSTOOD in request
    assert "Allied Castings Limited" in request and "SELECT DISTINCT nop_sales_month" in request  # the earlier answer
    assert len(mysql.calls) == 1 and "LEFT JOIN" in mysql.calls[0].upper() and "DISTINCT" in mysql.calls[0].upper()
