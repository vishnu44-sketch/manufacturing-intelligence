"""A line chart / trend question whose SQL gave only 1 row (portal/lc/graph.py: run_sql, keep_first_answer).

05-Nov: "for that above answer create one line chart" got a query of one month's total - one row, so the Ask page
could draw no chart. Such a question is sent back to the SQL step ONCE (ONE_ROW_LINE_CHART_PROBLEM); when that
try gives no better rows (again 1 row, no rows, NO_SQL, an error) the first answer is kept - never an error.

The AI is the fake one of test_agent.py (FakeAI behind LangChain); MySQL and the notes search are faked.
Run with:  python -m pytest -q portal/tests/test_one_row_chart.py
"""
from decimal import Decimal

import pytest

from portal.lc import graph
from portal.lc.memory import ChatHistory
from portal.models import Question
from portal.rag import agent, warehouse
from portal.tests.test_agent import ANSWER, mysql, use_fake_ai  # noqa: F401
from portal.tests.test_graph import (DATA_START, TREND_ANSWER, TREND_ROWS, TREND_SQL, sales_chat,  # noqa: F401
                                     steps)

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question

ONE_MONTH_SQL = ("```sql\nSELECT c.nop_sales_month, ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr\n"
                 "FROM fact_invoice_lines il\nJOIN dim_calendar c ON c.date_id = il.invoice_date_id\n"
                 "WHERE c.nop_sales_month = 'Oct 2026'\nGROUP BY c.nop_sales_month\n```")
ONE_ROW = {"columns": ["nop_sales_month", "net_sales_inr"], "rows": [["Oct 2026", Decimal("2367096647.50")]],
           "truncated": False}
NO_ROWS = {"columns": ["nop_sales_month", "net_sales_inr"], "rows": [], "truncated": False}
ONE_ROW_ANSWER = "In NOP sales month Oct 2026 net sales were INR 2,367,096,647.50."
LINE_QUESTION = "Net sales of Oct 2026 as a line chart"
SENT_BACK = "That did not work: " + graph.ONE_ROW_LINE_CHART_PROBLEM


# ---------- the words ----------

@pytest.mark.parametrize("text", [
    "for that above answer create one line chart", "Net sales as a line graph", "sales linechart",
    "show the line-chart of sales", "sales trend of FY 2026-27", "what are the trends in exports",
    "net sales over time",
])
def test_a_line_chart_or_a_trend_is_found(text):
    assert graph.line_chart_request(text)


@pytest.mark.parametrize("text", [
    "Net sales of Oct 2026 as a bar chart", "show a pie chart of sales by state", "top customers in Oct 2026",
    "sales of the product line Pumps", "", None,
])
def test_other_charts_and_questions_are_not_a_line_chart(text):
    assert not graph.line_chart_request(text)


# ---------- sent back once ----------

def test_one_row_for_a_line_chart_is_sent_back_once_and_the_second_rows_are_used(monkeypatch, mysql, user, steps):
    mysql.results = [ONE_ROW, TREND_ROWS]
    fake = use_fake_ai(monkeypatch, [(ONE_MONTH_SQL, 3000), (TREND_SQL, 3200), (TREND_ANSWER, 800)])

    result = agent.ask(LINE_QUESTION, user)

    assert steps == DATA_START + ["write_sql", "check_sql", "run_sql", "retry",
                                  "write_sql", "check_sql", "run_sql", "explain"]
    assert result.status == "ok" and result.answer == TREND_ANSWER
    assert result.rows == TREND_ROWS["rows"] and "'May 2026'" in result.sql
    second = fake.calls[1]
    assert second[-2] == {"role": "assistant", "content": ONE_MONTH_SQL}   # the 1-row query ...
    assert second[-1]["content"].startswith(SENT_BACK)                     # ... and why it went back
    assert "use SELECT DISTINCT for the period list" in second[-1]["content"]
    assert len(fake.calls) == 3 and len(mysql.calls) == 2
    # both SQL calls are counted: 2 tries, their tokens added up
    assert result.tries == 2
    assert (result.sql_tokens, result.answer_tokens, result.total_tokens) == (6200, 800, 7000)
    saved = Question.objects.get()
    assert (saved.tries, saved.rows_count, saved.sql_tokens, saved.total_tokens) == (2, 6, 6200, 7000)


def test_the_chat_follow_up_of_05_nov_gets_the_rows_of_its_second_try(monkeypatch, mysql, user, steps):
    """The typed question has the chart words; the rewrite wrote it out with the period."""
    mysql.results = [ONE_ROW, TREND_ROWS]
    understood = "Net sales of NOP month Oct 2026 as a line chart"
    fake = use_fake_ai(monkeypatch, [understood, ONE_MONTH_SQL, TREND_SQL, TREND_ANSWER])

    result = agent.ask("for that above answer create one line chart", user,
                       context=ChatHistory.for_chat(sales_chat(user)))

    assert steps == ["load_memories", "rewrite"] + DATA_START[1:] + [
        "write_sql", "check_sql", "run_sql", "retry", "write_sql", "check_sql", "run_sql", "explain"]
    assert result.status == "ok" and len(result.rows) == 6 and result.understood_as == understood
    assert fake.calls[2][-1]["content"].startswith(SENT_BACK)


def test_a_trend_found_only_in_the_understood_question_is_sent_back_too(monkeypatch, mysql, user, steps):
    mysql.results = [ONE_ROW, TREND_ROWS]
    fake = use_fake_ai(monkeypatch, ["Net sales trend of the last 6 NOP months up to Oct 2026",
                                     ONE_MONTH_SQL, TREND_SQL, TREND_ANSWER])

    result = agent.ask("and how did that move?", user, context=ChatHistory.for_chat(sales_chat(user)))

    assert result.status == "ok" and len(result.rows) == 6 and result.tries == 2
    assert fake.calls[2][-1]["content"].startswith(SENT_BACK)


# ---------- the retry gives nothing better: the first answer is kept ----------

def test_one_row_again_keeps_the_first_answer_and_never_loops(monkeypatch, mysql, user, steps):
    other_row = {"columns": ["nop_sales_month", "net_sales_inr"], "rows": [["Oct 2026", Decimal("1.00")]],
                 "truncated": False}
    mysql.results = [ONE_ROW, other_row]
    fake = use_fake_ai(monkeypatch, [(ONE_MONTH_SQL, 3000), (ONE_MONTH_SQL, 3100), (ONE_ROW_ANSWER, 700)])

    result = agent.ask(LINE_QUESTION, user)

    assert steps == DATA_START + ["write_sql", "check_sql", "run_sql", "retry",
                                  "write_sql", "check_sql", "run_sql", "keep_first_answer", "explain"]
    assert result.status == "ok" and result.answer == ONE_ROW_ANSWER
    assert result.rows == ONE_ROW["rows"] and "'Oct 2026'" in result.sql       # the FIRST rows, not the second
    assert "Oct 2026 | 2,367,096,647.50" in fake.calls[2][-1]["content"]       # the answer call saw them
    assert len(fake.calls) == 3 and len(mysql.calls) == 2                      # no third SQL try
    assert result.tries == 2 and (result.sql_tokens, result.total_tokens) == (6100, 6800)
    saved = Question.objects.get()
    assert (saved.status, saved.rows_count, saved.tries) == ("ok", 1, 2)


@pytest.mark.parametrize("second_reply, second_run, last_step", [
    ("NO_SQL", None, "write_sql"),                                              # the AI gave up
    ("NO_DATA: not available", None, "write_sql"),
    ("", None, "write_sql"),                                                    # a reply without SQL
    ("```sql\nDELETE FROM fact_invoice_lines\n```", None, "check_sql"),        # the guard refuses it
    (TREND_SQL, warehouse.QueryError("(1054) Unknown column 'c.nop_sales_period_no'"), "run_sql"),
    (TREND_SQL, NO_ROWS, "run_sql"),                                            # no rows at all
])
def test_a_retry_that_fails_keeps_the_first_answer(monkeypatch, mysql, user, steps, second_reply, second_run,
                                                     last_step):
    mysql.results = [ONE_ROW] + ([second_run] if second_run is not None else [])
    fake = use_fake_ai(monkeypatch, [ONE_MONTH_SQL, second_reply, ONE_ROW_ANSWER])

    result = agent.ask(LINE_QUESTION, user)

    assert steps[-3:] == [last_step, "keep_first_answer", "explain"]
    assert steps.count("write_sql") == 2 and "failed" not in steps
    assert result.status == "ok" and result.answer == ONE_ROW_ANSWER and result.error == ""
    assert result.rows == ONE_ROW["rows"] and "'Oct 2026'" in result.sql
    assert len(fake.calls) == 3 and result.tries == 2


def test_the_first_answer_on_the_last_try_is_not_sent_back(monkeypatch, mysql, user, steps):
    """No tries left: the 1-row answer is answered as it is."""
    error = warehouse.QueryError("(1054) Unknown column 'il.amount'")
    mysql.results = [error, error, ONE_ROW]
    fake = use_fake_ai(monkeypatch, [ONE_MONTH_SQL] * agent.MAX_TRIES + [ONE_ROW_ANSWER])

    result = agent.ask(LINE_QUESTION, user)

    assert steps[-2:] == ["run_sql", "explain"] and "keep_first_answer" not in steps
    assert result.status == "ok" and result.rows == ONE_ROW["rows"] and result.tries == agent.MAX_TRIES
    assert len(fake.calls) == agent.MAX_TRIES + 1


# ---------- not sent back ----------

@pytest.mark.parametrize("question", [
    "Net sales of Oct 2026",                          # not a chart question
    "Net sales of Oct 2026 as a bar chart",           # a bar chart of one row: the Ask page says why no chart
    "Net sales of Oct 2026 as a pie chart",
])
def test_one_row_without_a_line_chart_is_not_sent_back(monkeypatch, mysql, user, steps, question):
    mysql.results = [ONE_ROW]
    fake = use_fake_ai(monkeypatch, [(ONE_MONTH_SQL, 3000), (ONE_ROW_ANSWER, 700)])

    result = agent.ask(question, user)

    assert steps == DATA_START + ["write_sql", "check_sql", "run_sql", "explain"]
    assert result.status == "ok" and result.rows == ONE_ROW["rows"] and result.tries == 1
    assert len(fake.calls) == 2 and len(mysql.calls) == 1
    assert (result.sql_tokens, result.total_tokens) == (3000, 3700)


def test_a_line_chart_with_many_rows_is_not_sent_back(monkeypatch, mysql, user, steps):
    mysql.results = [TREND_ROWS]
    fake = use_fake_ai(monkeypatch, [TREND_SQL, TREND_ANSWER])

    result = agent.ask(LINE_QUESTION, user)

    assert steps == DATA_START + ["write_sql", "check_sql", "run_sql", "explain"]
    assert result.status == "ok" and len(result.rows) == 6 and len(fake.calls) == 2


def test_the_streamed_ask_page_gets_the_same_answer(monkeypatch, mysql, user):
    """run_events (the Ask page) takes the same path: the retry is announced as try 2."""
    mysql.results = [ONE_ROW, TREND_ROWS]
    use_fake_ai(monkeypatch, [ONE_MONTH_SQL, TREND_SQL, TREND_ANSWER])

    events = []
    stream = agent.ask_events(LINE_QUESTION, user)
    while True:
        try:
            events.append(next(stream))
        except StopIteration as done:
            result = done.value
            break

    labels = [e["label"] for e in events if e["type"] == "step"]
    assert any(label.endswith(" - try 2") for label in labels)
    assert result.status == "ok" and len(result.rows) == 6 and result.tries == 2
