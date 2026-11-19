"""18-Nov: a question about an earlier answer's own result - one of its columns, or "this column" / "previous answer" /
"why did you add ..." - gets that answer's query and columns in the AI requests (lc.memory.previous_query,
agent.PREVIOUS_QUERY_*). The 18-Nov chat: an answer with the columns horizon_months | forecast_count (its SQL:
COUNT(*) AS forecast_count), then "forecast_count what it mean this coloums" got DATA NOT AVAILABLE (the SQL writer
looked for forecast_count in the tables) and "then prevous anwer why you add this forecast_count?" got "I added it by
mistake" (the general answer saw the earlier answers without their SQL).

Any other question gets nothing more (no extra tokens). The AI is always the fake one of test_agent.py; MySQL and the
notes search are faked. Run with:  python -m pytest -q portal/tests/test_previous_answer_columns.py
"""
import datetime
import json

import pytest
from django.utils import timezone

from portal import answer_check
from portal.lc import memory
from portal.lc.memory import ChatHistory
from portal.rag import agent
from portal.tests.test_agent import ANSWER, GOOD_SQL, ROWS, mysql, use_fake_ai  # noqa: F401
from portal.tests.test_chat import make_chat
from portal.tests.test_graph import steps  # noqa: F401
from portal.tests.test_views_ask import saved_question

pytestmark = pytest.mark.django_db

FORECAST_SQL = ("SELECT\n  horizon_months,\n  COUNT(*) AS forecast_count\nFROM ml_sales_forecast\nGROUP BY\n"
                "  horizon_months\nORDER BY\n  horizon_months\nLIMIT 500")
ONE_LINE_SQL = ("SELECT horizon_months, COUNT(*) AS forecast_count FROM ml_sales_forecast GROUP BY horizon_months "
                "ORDER BY horizon_months LIMIT 500")
FORECAST_ANSWER = ("Based on the data up to 31-Oct-2026, the model gives forecasts for each horizon month from 1 "
                   "through 12, so it forecasts a full 12-month horizon.")
NODATA_ANSWER = ('The SS Manufacturing data does not have this: "forecast_count" is not a column in the SS '
                 "Manufacturing data.")
COLUMN_QUESTION = "forecast_count what it mean this coloums"
WHY_QUESTION = "then prevous anwer why you add this forecast_count?"
MEANING = ("forecast_count was made by the previous query: COUNT(*) of the forecast rows for each horizon month - "
           "11 for months 1-3 (1 total + 10 products), 1 for months 4-12.")
QUERY_HEAD = "Previous answer's query (columns: horizon_months, forecast_count):"


def forecast_chat(user, *, nodata_after=False):
    """The 18-Nov chat: the answer whose query made forecast_count (and, with nodata_after, the DATA NOT AVAILABLE
    answer to the column question after it)."""
    chat = make_chat(user, "is that trined for 12 months ?", sql=FORECAST_SQL, answer=FORECAST_ANSWER, rows_count=12)
    if nodata_after:
        later = saved_question(user, text=COLUMN_QUESTION, conversation=chat, status="nodata", sql="",
                               answer=NODATA_ANSWER, rows_count=None)
        later.created_at = timezone.now()
        later.save(update_fields=["created_at"])
    return chat


def user_text(call):
    """The last user message of one AI call."""
    return call[-1]["content"]


# ---------- the 18-Nov chat ----------

def test_the_column_question_gets_the_previous_query_and_is_explained_not_no_data(monkeypatch, mysql, user, steps):
    chat = forecast_chat(user)
    understood = ("What does forecast_count (the COUNT of forecast rows per horizon_months in the previous answer's "
                  "query) mean?")
    fake = use_fake_ai(monkeypatch, [understood, "GENERAL", MEANING])

    result = agent.ask(COLUMN_QUESTION, user, context=ChatHistory.for_chat(chat))

    assert steps == ["load_memories", "rewrite", "route", "search_notes", "pick_schema", "write_sql", "general_answer"]
    assert result.status == "general" and result.answer == MEANING and mysql.calls == []
    rewrite, sql, general = fake.calls
    # the rewrite sees the query, so it can write the column out
    assert QUERY_HEAD in user_text(rewrite) and ONE_LINE_SQL in user_text(rewrite)
    assert "In plain words: Took the ml sales forecast table. Counted the rows" in user_text(rewrite)
    assert "builds on it: write it out naming the column" in user_text(rewrite)
    # the SQL writer: the rule, and the query by its number ('Earlier in this chat' lists its SQL already)
    asked = user_text(sql)
    assert "reply GENERAL, never NO_DATA" in asked
    assert "the SQL of earlier question 1 above (columns: horizon_months, forecast_count)" in asked
    assert asked.count("COUNT(*) AS forecast_count") == 1                    # once, in 'Earlier in this chat'
    # the general answer explains it from the query
    assert QUERY_HEAD in user_text(general) and ONE_LINE_SQL in user_text(general)
    assert "Never say such a column was added by mistake" in user_text(general)


def test_the_column_question_gets_the_query_also_when_the_rewrite_says_new(monkeypatch, mysql, user):
    # what happened on 18-Nov: the rewrite said NEW, so the SQL writer saw no earlier answer at all
    chat = forecast_chat(user)
    fake = use_fake_ai(monkeypatch, ["NEW", "GENERAL", MEANING])

    result = agent.ask(COLUMN_QUESTION, user, context=ChatHistory.for_chat(chat))

    assert result.status == "general" and "DATA NOT AVAILABLE" not in result.answer.upper()
    _rewrite, sql, general = fake.calls
    asked = user_text(sql)
    assert "Earlier in this chat" not in asked                                # the chat is not shown ...
    assert QUERY_HEAD in asked and ONE_LINE_SQL in asked                     # ... but the query is
    assert "reply GENERAL, never NO_DATA" in asked
    assert ONE_LINE_SQL in user_text(general)


def test_why_did_you_add_this_column_gets_the_query_in_the_general_request(monkeypatch, mysql, user):
    chat = forecast_chat(user, nodata_after=True)                            # the latest answer has no SQL
    fake = use_fake_ai(monkeypatch, ["Why did you add the forecast_count column in the previous answer?",
                                     "GENERAL", MEANING])

    result = agent.ask(WHY_QUESTION, user, context=ChatHistory.for_chat(chat))

    assert result.status == "general" and result.answer == MEANING
    general = user_text(fake.calls[-1])
    assert general.startswith(WHY_QUESTION + "\n(Understood as: Why did you add the forecast_count column")
    assert QUERY_HEAD in general and ONE_LINE_SQL in general
    # the earlier answers are still the chat history, before the request
    assert [m["content"] for m in fake.calls[-1][1:-1]][-1] == NODATA_ANSWER


def test_a_message_the_router_sends_to_the_general_answer_gets_the_query_too(monkeypatch, mysql, user):
    chat = forecast_chat(user)
    # the router runs only when a PDF piece scores high enough
    monkeypatch.setattr(agent, "route_question", lambda result, asked: ("general", []))
    fake = use_fake_ai(monkeypatch, ["What does forecast_count in the previous answer mean?", MEANING])

    result = agent.ask(COLUMN_QUESTION, user, context=ChatHistory.for_chat(chat))

    assert result.status == "general" and len(fake.calls) == 2
    assert ONE_LINE_SQL in user_text(fake.calls[-1])


# ---------- other questions get nothing more ----------

def test_an_unrelated_follow_up_gets_no_previous_query(monkeypatch, mysql, user):
    chat = forecast_chat(user)
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, ["NEW", GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user, context=ChatHistory.for_chat(chat))

    assert result.status == "ok"
    assert "Previous answer's query" not in json.dumps(fake.calls)
    assert user_text(fake.calls[0]).endswith(agent.REWRITE_REQUEST.split("{earlier}", 1)[1].format(
        question="Top customers in Aug 2026?"))
    assert user_text(fake.calls[0]).startswith("Earlier questions in this chat (oldest first):\n"
                                               "1. is that trined for 12 months ? (latest)\n\nNew question:")
    assert user_text(fake.calls[1]).endswith("Question: Top customers in Aug 2026?")


def test_an_unrelated_general_follow_up_gets_no_previous_query(monkeypatch, mysql, user):
    chat = forecast_chat(user)
    fake = use_fake_ai(monkeypatch, ["NEW", "GENERAL", "The capital of France is Paris."])

    agent.ask("what is the capital of France", user, context=ChatHistory.for_chat(chat))

    assert "Previous answer's query" not in json.dumps(fake.calls)
    assert user_text(fake.calls[-1]) == "what is the capital of France"
    assert "SELECT" not in json.dumps(fake.calls[-1])


def test_the_checks_of_an_earlier_answer_are_not_changed():
    # "is that correct?" / "how did you get this?" are answered by answer_check.py (0 tokens), before any AI step
    assert answer_check.kind("is that correct?") is not None
    assert answer_check.kind("how did you get this?") is not None
    assert answer_check.kind(COLUMN_QUESTION) is None and answer_check.kind(WHY_QUESTION) is None


# ---------- the word rules ----------

@pytest.mark.parametrize("text", ["forecast_count", "what is forecast count?", "FORECAST_COUNT", "Forecast-Count ?"])
def test_the_column_name_is_found_in_any_case_with_underscores_or_spaces(text):
    assert memory.names_column("forecast_count", text)


@pytest.mark.parametrize("text", ["forecast", "count", "forecastcount", "forecast_counts", ""])
def test_a_part_of_the_column_name_is_not_the_column(text):
    assert not memory.names_column("forecast_count", text)


def test_the_columns_of_a_query_and_the_ones_it_made_itself():
    assert memory.query_columns(FORECAST_SQL) == [("horizon_months", False), ("forecast_count", True)]
    assert memory.query_columns("SELECT c.customer_name AS customer, c.state FROM dim_customers c") == [
        ("customer", True), ("state", False)]
    assert memory.query_columns("not a query (") == [] and memory.query_columns("") == []


def history(*answers):
    """Chat messages: one earlier question per (sql, answer)."""
    from types import SimpleNamespace
    return ChatHistory([SimpleNamespace(text=f"question {n}", understood_as="", sql=sql, answer=answer)
                        for n, (sql, answer) in enumerate(answers, start=1)]).messages


@pytest.mark.parametrize("text", [
    COLUMN_QUESTION, WHY_QUESTION, "FORECAST COUNT?", "what does horizon_months mean", "explain that column",
    "why did you add months?", "what was in your last answer", "explain the previous result",
])
def test_questions_about_the_previous_answer(text):
    found = memory.previous_query(history((FORECAST_SQL, FORECAST_ANSWER), ("", NODATA_ANSWER)), text)
    found.pop("facts", None)  # horizon_months is a stored column: its data dictionary line (tested below)
    assert found == {"n": 1, "sql": FORECAST_SQL, "columns": ["horizon_months", "forecast_count"]}


@pytest.mark.parametrize("text", [
    "Top customers in Aug 2026?", "what is GST", "horizon months by product", "is that correct?",
    "show above as line chart", "and for Sep 2026?", "net sales by state for last month", "what does GST mean?",
])
def test_other_questions_are_not_about_the_previous_answer(text):
    assert memory.previous_query(history((FORECAST_SQL, FORECAST_ANSWER)), text) is None


def test_without_an_earlier_query_nothing_is_added():
    assert memory.previous_query(history(("", "GST is a tax.")), "why did you add that column?") is None
    assert memory.previous_query([], COLUMN_QUESTION) is None


def test_the_latest_answer_with_the_named_column_wins():
    other = "SELECT customer_name, SUM(net_value) AS net_sales FROM fact_invoice_lines GROUP BY customer_name"
    messages = history((FORECAST_SQL, FORECAST_ANSWER), (other, "Aurora ..."))
    assert memory.previous_query(messages, COLUMN_QUESTION)["n"] == 1        # named: the older answer
    assert memory.previous_query(messages, "why did you add that column?")["n"] == 2   # not named: the latest


def test_a_long_query_is_cut_for_the_requests():
    long_sql = "SELECT horizon_months, COUNT(*) AS forecast_count FROM ml_sales_forecast WHERE " + " OR ".join(
        f"product_id = {n}" for n in range(400))
    text = memory.previous_query_text({"n": 1, "sql": long_sql, "columns": ["horizon_months", "forecast_count"]})
    sql_line = text.splitlines()[1]
    assert sql_line.endswith(" ...") and len(sql_line) == agent.PREVIOUS_QUERY_CHARS + 4


# ---------- 18-Nov: a stored column of an answer older than the questions the memory keeps ----------
# An ML Insights chat of 14 questions: the forecast answers showed low_inr; many questions later, after a few general
# answers, "what does low_inr mean?" got "The meaning of low_inr is not in the SS Manufacturing data".

LOW_SQL = ("SELECT\n  sales_month,\n  forecast_inr,\n  low_inr,\n  high_inr\nFROM ml_sales_forecast\n"
           "WHERE\n  level = 'TOTAL'\nORDER BY\n  horizon_months\nLIMIT 500")
LOW_ONE_LINE_SQL = ("SELECT sales_month, forecast_inr, low_inr, high_inr FROM ml_sales_forecast WHERE level = 'TOTAL' "
                    "ORDER BY horizon_months LIMIT 500")
LOW_FACT = ("low_inr (ml_sales_forecast): Low end of the 80 % range in INR: the actual is expected to be above this "
            "9 times in 10.")
LOW_QUESTION = "what does low_inr mean?"
LOW_MEANING = ("low_inr is the low end of the forecast's likely (80 %) range for that month: actual sales are "
               "expected to be above it 9 times in 10.")


def long_chat(user):
    """Question 1 general, question 2 the forecast answer with low_inr, questions 3-8 general (no SQL)."""
    chat = make_chat(user, "hi, what can you do?", sql="", answer="I answer questions about the data.",
                     status="general", rows_count=None)
    start = timezone.now() - datetime.timedelta(minutes=30)
    texts = ["sales forecast for the next 12 months"] + [f"general question {n}" for n in range(3, 9)]
    for n, text in enumerate(texts):
        data = n == 0
        question = saved_question(user, text=text, conversation=chat, status="ok" if data else "general",
                                  sql=LOW_SQL if data else "", answer="The forecast ..." if data else f"Answer {n}.",
                                  rows_count=12 if data else None)
        question.created_at = start + datetime.timedelta(minutes=n)
        question.save(update_fields=["created_at"])
    return chat


def test_a_stored_column_of_an_older_answer_gets_its_query_and_the_data_dictionary_line(monkeypatch, mysql, user):
    chat = long_chat(user)
    context = ChatHistory.for_chat(chat)
    assert [q.text for q in context] == ["general question 6", "general question 7", "general question 8"]
    fake = use_fake_ai(monkeypatch, ["What does low_inr in the earlier forecast answer mean?", "GENERAL", LOW_MEANING])

    result = agent.ask(LOW_QUESTION, user, context=context)

    assert result.status == "general" and result.answer == LOW_MEANING and mysql.calls == []
    rewrite, sql, general = fake.calls
    for call in (rewrite, sql, general):
        asked = user_text(call)
        assert LOW_ONE_LINE_SQL in asked and LOW_FACT in asked                # question 2's query + the dictionary
        assert "columns: sales_month, forecast_inr, low_inr, high_inr" in asked
    # the SQL request writes that query out: 'Earlier in this chat' has only questions 6-8 (no SQL)
    assert "the SQL of earlier question" not in user_text(sql)
    assert "never say such a column was added by mistake".lower() in user_text(general).lower()


def test_the_older_answers_are_read_once_and_only_from_this_chat(user, django_assert_num_queries):
    chat = long_chat(user)
    make_chat(user, "another chat", sql="SELECT low_inr FROM ml_sales_forecast")
    context = ChatHistory.for_chat(chat)
    with django_assert_num_queries(1):
        assert context.older_answers() == [LOW_SQL]
        assert context.older_answers() == [LOW_SQL]                           # read once per question


def test_a_name_the_query_made_with_as_is_still_explained_from_the_query():
    found = memory.previous_query(history((FORECAST_SQL, FORECAST_ANSWER)), COLUMN_QUESTION)
    assert "facts" not in found                                              # forecast_count is in no table
    assert "data dictionary" not in memory.previous_query_text(found)
    # also from an older answer: the query, no dictionary line
    older = type("History", (), {"older_answers": lambda self: [FORECAST_SQL]})()
    found = memory.previous_query(history(("", "GST is a tax.")), COLUMN_QUESTION, older)
    assert found == {"n": None, "sql": FORECAST_SQL, "columns": ["horizon_months", "forecast_count"]}
    assert ONE_LINE_SQL in memory.previous_query_text(found, shown=True)     # not in 'Earlier in this chat'


def test_an_older_answer_is_found_and_the_latest_with_the_column_wins():
    other = "SELECT sales_month, forecast_inr FROM ml_sales_forecast"
    older = type("History", (), {"older_answers": lambda self: [LOW_SQL, other]})()
    found = memory.previous_query(history(("", "GST is a tax."), ("", "Hello.")), LOW_QUESTION, older)
    assert found == {"n": None, "sql": LOW_SQL, "columns": ["sales_month", "forecast_inr", "low_inr", "high_inr"],
                     "facts": [LOW_FACT]}
    assert LOW_FACT in memory.previous_query_text(found)
    # an answer the memory keeps comes first
    found = memory.previous_query(history((LOW_SQL, "The forecast ...")), LOW_QUESTION, older)
    assert found["n"] == 1 and found["facts"] == [LOW_FACT]
    assert memory.previous_query_text(found, shown=True).endswith(LOW_FACT)


@pytest.mark.parametrize("text", ["Top customers in Aug 2026?", "what does GST mean?", "and for Sep 2026?",
                                  "explain the previous result", "show above as line chart"])
def test_a_question_that_names_no_column_reads_no_older_answers(text):
    def no_reading(self):
        raise AssertionError("older answers read")
    older = type("History", (), {"older_answers": no_reading})()
    assert not memory.may_name_column(text)
    assert memory.previous_query(history(("", "GST is a tax.")), text, older) is None


def test_an_unrelated_question_in_the_long_chat_is_unchanged(monkeypatch, mysql, user):
    chat = long_chat(user)
    read = []
    monkeypatch.setattr(ChatHistory, "older_answers", lambda self: read.append(1) or [])
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, ["NEW", GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user, context=ChatHistory.for_chat(chat))

    assert result.status == "ok" and read == []                               # no extra query
    assert "Previous answer's query" not in json.dumps(fake.calls)            # no extra tokens
    assert "data dictionary" not in json.dumps(fake.calls)


def test_the_data_dictionary_is_read_from_the_real_docs():
    dictionary = memory.data_dictionary()
    assert dictionary["ml_sales_forecast"]["low_inr"] == (
        "Low end of the 80 % range in INR: the actual is expected to be above this 9 times in 10.")
    assert dictionary["ml_sales_forecast"]["horizon_months"].startswith("How far ahead")
    assert "forecast_id" in dictionary["ml_sales_forecast"] and "full_date" in dictionary["dim_calendar"]
    assert "load_log" not in dictionary.get("ss_gold", {})                    # the overview's table list is no column
    assert memory.data_dictionary() is dictionary                              # parsed once per process


def test_the_dictionary_line_is_for_the_column_s_own_table():
    sql = ("SELECT f.sales_month, f.low_inr, c.customer_name AS low_inr_name, SUM(f.forecast_inr) AS total "
           "FROM ml_sales_forecast f JOIN dim_customers c ON 1 = 1 GROUP BY f.sales_month, f.low_inr, c.customer_name")
    assert memory.column_facts(sql, ["low_inr"]) == [LOW_FACT]
    assert memory.column_facts(sql, ["low_inr_name", "total"]) == []           # made by the query
    assert memory.column_facts(sql, ["no_such_column"]) == [] and memory.column_facts("not sql (", ["low_inr"]) == []
