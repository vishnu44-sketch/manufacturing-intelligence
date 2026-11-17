"""The AI's ASKS_FOR / PERIODS lines (portal/ai_hints.py) and the two checks of lc/graph.run_sql that use them.

17-Nov: the entity check ("top customers of X" answered with X's total) and the 1-row chart retry ("a bar chart of
the last 6 months" answered with one row) decided only from fixed words, so typos slipped past them. The SQL call
now may write "ASKS_FOR: customers" and "PERIODS: 6" before its SQL; the checks use those first and the old word
rules as the fallback. No line = exactly as before (test_entity_check.py / test_one_row_chart.py still hold).

The AI is the fake one of test_agent.py (FakeAI behind LangChain); MySQL and the notes search are faked.
Run with:  python -m pytest -q portal/tests/test_ai_hints.py
"""
import pytest

from portal import ai_hints
from portal.lc import graph
from portal.rag import agent
from portal.tests.test_agent import mysql, use_fake_ai  # noqa: F401
from portal.tests.test_entity_check import (PER_CUSTOMER, PER_CUSTOMER_SQL, PRODUCT_TOTAL, PRODUCT_TOTAL_SQL,
                                            RIGHT_ANSWER, SENT_BACK as ENTITY_SENT_BACK, WRONG_ANSWER,
                                            tables)  # noqa: F401
from portal.tests.test_graph import DATA_START, TREND_ANSWER, TREND_ROWS, TREND_SQL, steps  # noqa: F401
from portal.tests.test_one_row_chart import ONE_MONTH_SQL, ONE_ROW, ONE_ROW_ANSWER, SENT_BACK as ONE_ROW_SENT_BACK

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question


def with_lines(sql_reply, *lines):
    """The SQL reply with the AI's note lines before it."""
    return "\n".join(lines) + "\n" + sql_reply


# ---------- the readers ----------

@pytest.mark.parametrize("reply, expected", [
    ("ASKS_FOR: customers\n```sql\nSELECT 1\n```", "customer"),
    ("ASKS_FOR: customer", "customer"),
    ("asks_for: Customers", "customer"),
    ("**ASKS_FOR:** customers (by net sales)", "customer"),
    ("ASKS_FOR: clients", "customer"),
    ("ASKS_FOR: products", "product"),
    ("ASKS_FOR: items", "product"),
    ("ASKS_FOR: sales people", "sales_person"),
    ("ASKS_FOR: Sales Person", "sales_person"),
    ("ASKS_FOR: sales-persons", "sales_person"),
    ("ASKS_FOR: salesmen", "sales_person"),
    ("ASKS_FOR: sales_people", "sales_person"),
    ("ASKS_FOR: states", "state"),
    ("ASKS_FOR: countries.", "country"),
    ("ASKS_FOR: Country", "country"),
    ("<think>ASKS_FOR: products</think>\nASKS_FOR: states", "state"),
    ("ASKS_FOR: none", ""),
    ("ASKS_FOR: months", ""),
    ("ASKS_FOR:", ""),
    ("```sql\nSELECT 1\n```", ""),
    ("", ""), (None, ""),
])
def test_asks_for_reads_the_line(reply, expected):
    assert ai_hints.asks_for(reply) == expected


@pytest.mark.parametrize("reply, expected", [
    ("PERIODS: 6\n```sql\nSELECT 1\n```", 6),
    ("periods: 12", 12),
    ("PERIODS: 3 months", 3),
    ("**PERIODS:** 4", 4),
    ("PERIODS: 1", 1),
    ("PERIODS: 120", 120),
    ("PERIODS: 121", None),
    ("PERIODS: 0", None),
    ("PERIODS: -2", None),
    ("PERIODS: six", None),
    ("PERIODS: 2.5", None),
    ("PERIODS:", None),
    ("```sql\nSELECT 1\n```", None),
    ("", None), (None, None),
])
def test_periods_reads_the_line(reply, expected):
    assert ai_hints.periods(reply) == expected


@pytest.mark.parametrize("reply", [
    "ASKS_FOR: customers\nPERIODS: 6\n```sql\nSELECT 1 AS x\n```",
    "CHART: bar\nASKS_FOR: products\nPERIODS: 3\nUNDERSTOOD: x\n```sql\nSELECT 1 AS x\n```",
    "PERIODS: 6\nSELECT 1 AS x",
])
def test_the_lines_never_reach_the_sql(reply):
    kind, sql = agent.read_sql_reply(reply)
    assert kind == "sql" and "ASKS_FOR" not in sql and "PERIODS" not in sql and "SELECT 1 AS x" in sql


def test_the_prompt_asks_for_the_lines_in_a_short_sentence_of_its_own():
    prompt = agent.SQL_SYSTEM_PROMPT
    assert ('"ASKS_FOR: <customers / products / sales people / states / countries>" when it asks for a ranking or '
            "list of those (not a name filter, not a count)") in prompt
    assert '"PERIODS: <n>" when it asks for several periods ("last 6 months" = 6)' in prompt
    assert "ASKS_FOR / PERIODS" in agent.RETRY_PROMPT


def test_graph_state_starts_without_hints():
    state = graph.start_state(agent.AskResult(text="x"))
    assert state["asks_for"] == "" and state["periods"] is None


# ---------- the entity check: the AI first, the words as the fallback ----------

def test_a_typo_the_words_miss_is_sent_back_when_the_ai_names_the_customers(monkeypatch, tables, user, steps):
    question = "top clints of Coolant pump"
    assert agent.ranked_entities(question) == []                  # the word rules see nothing
    tables.results = [PRODUCT_TOTAL, PER_CUSTOMER]
    fake = use_fake_ai(monkeypatch, [with_lines(PRODUCT_TOTAL_SQL, "ASKS_FOR: customers"), PER_CUSTOMER_SQL,
                                     RIGHT_ANSWER])

    result = agent.ask(question, user)

    assert steps == DATA_START + ["write_sql", "check_sql", "run_sql", "retry",
                                  "write_sql", "check_sql", "run_sql", "explain"]
    second = fake.calls[1][-1]["content"]
    assert second.startswith(ENTITY_SENT_BACK) and f'("{question}")' in second
    assert result.status == "ok" and result.rows == PER_CUSTOMER["rows"] and result.tries == 2
    assert all("ASKS_FOR" not in sql for sql in tables.calls)    # the line never ran as SQL


def test_the_typo_question_with_the_ai_line_is_sent_back_once(monkeypatch, tables, user, steps):
    tables.results = [PRODUCT_TOTAL, PRODUCT_TOTAL]
    fake = use_fake_ai(monkeypatch, [with_lines(PRODUCT_TOTAL_SQL, "ASKS_FOR: customers"),
                                     with_lines(PRODUCT_TOTAL_SQL, "ASKS_FOR: customers"), WRONG_ANSWER])

    result = agent.ask("top custmers of Coolant pump", user)

    assert fake.calls[1][-1]["content"].startswith(ENTITY_SENT_BACK)
    assert steps.count("retry") == 1 and steps[-2:] == ["keep_first_answer", "explain"]   # once, never a loop
    assert result.status == "ok" and result.rows == PRODUCT_TOTAL["rows"] and len(fake.calls) == 3


def test_without_an_ai_line_a_typo_the_words_miss_is_answered_as_today(monkeypatch, tables, user, steps):
    tables.results = [PRODUCT_TOTAL]
    fake = use_fake_ai(monkeypatch, [PRODUCT_TOTAL_SQL, WRONG_ANSWER])

    result = agent.ask("top clints of Coolant pump", user)

    assert "retry" not in steps and result.status == "ok" and len(fake.calls) == 2


def test_without_an_ai_line_the_word_rules_still_send_it_back(monkeypatch, tables, user, steps):
    tables.results = [PRODUCT_TOTAL, PER_CUSTOMER]
    fake = use_fake_ai(monkeypatch, [PRODUCT_TOTAL_SQL, PER_CUSTOMER_SQL, RIGHT_ANSWER])

    agent.ask("top custmers of Coolant pump", user)

    assert fake.calls[1][-1]["content"].startswith(ENTITY_SENT_BACK)


def test_the_ai_line_names_a_thing_the_rows_show_is_not_sent_back(monkeypatch, tables, user, steps):
    tables.results = [PER_CUSTOMER]
    fake = use_fake_ai(monkeypatch, [with_lines(PER_CUSTOMER_SQL, "ASKS_FOR: customers"), RIGHT_ANSWER])

    result = agent.ask("top clints of Coolant pump", user)

    assert "retry" not in steps and result.status == "ok" and len(fake.calls) == 2


def test_the_ai_line_for_sales_people_uses_their_problem_text(monkeypatch, tables, user, steps):
    tables.results = [PRODUCT_TOTAL, PER_CUSTOMER]
    fake = use_fake_ai(monkeypatch, [with_lines(PRODUCT_TOTAL_SQL, "ASKS_FOR: sales people"), PER_CUSTOMER_SQL,
                                     RIGHT_ANSWER])

    agent.ask("best sellng guys for coolant pump", user)

    second = fake.calls[1][-1]["content"]
    assert second.startswith("That did not work: the question asks for a ranking / list of sales people")
    assert "dim_sales_people.sales_person_name" in second


def test_missing_entity_uses_the_word_phrase_when_the_words_see_it_too():
    words = agent.ranked_entities("top custmers of Coolant pump")[0]        # ("customer", "top customer")
    assert ai_hints.missing_entity("top custmers of Coolant pump", PRODUCT_TOTAL["columns"], "customer") == words
    assert ai_hints.missing_entity("top clints", PRODUCT_TOTAL["columns"], "") is None
    assert ai_hints.missing_entity("top clints", PER_CUSTOMER["columns"], "customer") is None


# ---------- the 1-row chart retry: the AI first, the words as the fallback ----------

def test_periods_and_a_bar_chart_typo_question_with_one_row_is_sent_back_once(monkeypatch, mysql, user, steps):
    mysql.results = [ONE_ROW, TREND_ROWS]
    fake = use_fake_ai(monkeypatch, [with_lines(ONE_MONTH_SQL, "CHART: bar", "PERIODS: 6"), TREND_SQL,
                                     TREND_ANSWER])

    result = agent.ask("plot bar chat last 6 month sales", user)

    assert steps == DATA_START + ["write_sql", "check_sql", "run_sql", "retry",
                                  "write_sql", "check_sql", "run_sql", "explain"]
    assert fake.calls[1][-1]["content"].startswith(ONE_ROW_SENT_BACK)
    assert result.status == "ok" and len(result.rows) == 6 and result.tries == 2
    assert all("PERIODS" not in sql and "CHART" not in sql for sql in mysql.calls)


def test_a_typo_the_words_miss_is_sent_back_when_the_ai_names_the_periods(monkeypatch, mysql, user, steps):
    question = "bar chat of sales of the lst six mnths"
    assert not graph.several_periods_chart_request(question)        # the word rules see nothing
    mysql.results = [ONE_ROW, TREND_ROWS]
    fake = use_fake_ai(monkeypatch, [with_lines(ONE_MONTH_SQL, "CHART: bar", "PERIODS: 6"), TREND_SQL,
                                     TREND_ANSWER])

    result = agent.ask(question, user)

    assert fake.calls[1][-1]["content"].startswith(ONE_ROW_SENT_BACK)
    assert result.status == "ok" and len(result.rows) == 6 and result.tries == 2


def test_periods_again_one_row_keeps_the_first_answer(monkeypatch, mysql, user, steps):
    mysql.results = [ONE_ROW, ONE_ROW]
    reply = with_lines(ONE_MONTH_SQL, "CHART: bar", "PERIODS: 6")
    fake = use_fake_ai(monkeypatch, [reply, reply, ONE_ROW_ANSWER])

    result = agent.ask("bar chat of sales of the lst six mnths", user)

    assert steps.count("retry") == 1 and steps[-2:] == ["keep_first_answer", "explain"]
    assert result.status == "ok" and result.rows == ONE_ROW["rows"] and len(fake.calls) == 3


@pytest.mark.parametrize("lines", [
    (),                                   # no lines at all: as today
    ("CHART: bar",),                      # a chart, but no periods named
    ("PERIODS: 6",),                      # periods, but no chart wish
    ("CHART: bar", "PERIODS: 1"),         # a chart of one period
])
def test_without_periods_and_a_chart_wish_a_typo_question_is_answered_as_today(monkeypatch, mysql, user, steps,
                                                                               lines):
    mysql.results = [ONE_ROW]
    fake = use_fake_ai(monkeypatch, [with_lines(ONE_MONTH_SQL, *lines) if lines else ONE_MONTH_SQL,
                                     ONE_ROW_ANSWER])

    result = agent.ask("bar chat of sales of the lst six mnths", user)

    assert steps == DATA_START + ["write_sql", "check_sql", "run_sql", "explain"]
    assert result.status == "ok" and result.rows == ONE_ROW["rows"] and len(fake.calls) == 2


def test_without_periods_the_word_rules_still_send_it_back(monkeypatch, mysql, user, steps):
    mysql.results = [ONE_ROW, TREND_ROWS]
    fake = use_fake_ai(monkeypatch, [ONE_MONTH_SQL, TREND_SQL, TREND_ANSWER])

    agent.ask("plot bar chat last 6 month sales", user)

    assert fake.calls[1][-1]["content"].startswith(ONE_ROW_SENT_BACK)


@pytest.mark.parametrize("question, periods, chart_kind, expected", [
    ("bar chat of the lst six mnths", 6, "bar", True),
    ("sales of the lst six mnths as a graph", 6, "", True),    # the chart words count as a chart wish
    ("bar chat of the lst six mnths", 6, "", False),           # no chart wish
    ("bar chat of Oct", 1, "bar", False),
    ("bar chat of Oct", None, "bar", False),
])
def test_several_periods_chart(question, periods, chart_kind, expected):
    assert ai_hints.several_periods_chart(question, periods, chart_kind) is expected
