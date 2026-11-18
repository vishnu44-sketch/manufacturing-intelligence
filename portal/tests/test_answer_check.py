"""Questions about the previous answer (portal/answer_check.py): "is that correct?", "how did you get this?" in a
chat are answered by our own code - the earlier SQL runs again, no AI call, 0 tokens.

16-Nov: "is that above answer is correct" after a right bar chart answer went to the SQL step, got NO_SQL and
"NOT A COMPANY DATA QUESTION" for 6,735 tokens.

The AI is the fake one of test_agent.py with NO replies: any AI call would fail the test. MySQL is faked.
Run with:  python -m pytest -q portal/tests/test_answer_check.py
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from portal import answer_check, services
from portal.evals.questions import ITEMS
from portal.lc.memory import ChatHistory
from portal.models import Conversation, Question
from portal.rag import agent, warehouse
from portal.rag.sql_guard import check_sql
from portal.tests.test_agent import ANSWER, GOOD_SQL, ROWS, mysql, use_fake_ai  # noqa: F401

pytestmark = pytest.mark.django_db

BAR_QUESTION = "can you create one plot bar chart last 5 month sales"
BAR_SQL = ("SELECT c.sales_month, ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr\n"
           "FROM fact_invoice_lines il\nJOIN dim_calendar c ON c.date_id = il.invoice_date_id\n"
           "WHERE c.sales_period_end <= CURRENT_DATE\n"
           "GROUP BY c.sales_year, c.sales_period_no, c.sales_month\n"
           "ORDER BY c.sales_year DESC, c.sales_period_no DESC\nLIMIT 5")
BAR_ROWS = {"columns": ["sales_month", "net_sales_inr"],
            "rows": [["Oct 2026", Decimal("2367096647.50")], ["Sep 2026", Decimal("1955500.00")],
                     ["Aug 2026", Decimal("747750.00")], ["Jul 2026", Decimal("1730000.00")],
                     ["Jun 2026", Decimal("12767485.00")]],
            "truncated": False}
BAR_ANSWER = ("Over the last 5 sales months (Jun 2026 to Oct 2026, 21-May-2026 to 20-Oct-2026), net sales were highest "
              "in Oct 2026 at INR 2,367,096,647.50 and lowest in Aug 2026 at INR 747,750.00; Jun 2026 had "
              "INR 12,767,485.00. The full list is in the table.")
CHECKED_OK = ("I ran the same query again on the database: 5 rows, the same as before, and every number in my answer "
              "is in the rows. The numbers come straight from the database - the AI only wrote the query and the "
              "words. You can open Show SQL to see the query.")


def bar_chat(user, answer=BAR_ANSWER, rows_count=5):
    """The chat of 16-Nov: one answered data question (a bar chart of the last 5 months' sales)."""
    chat = Conversation.objects.create(user=user, title="chat")
    Question.objects.create(user=user, conversation=chat, text=BAR_QUESTION, sql=BAR_SQL, answer=answer,
                            rows_count=rows_count, status="ok", model="openai/gpt-oss-120b", total_tokens=6000)
    return chat


def no_ai(monkeypatch):
    """A fake AI with no replies: a call would fail the question (and the test checks fake.calls == [])."""
    return use_fake_ai(monkeypatch, [])


# ---------- the 16-Nov case ----------

def test_is_that_above_answer_is_correct_runs_the_same_sql_again_with_no_ai_call(monkeypatch, mysql, user):
    chat = bar_chat(user)
    mysql.results = [BAR_ROWS]
    fake = no_ai(monkeypatch)

    saved, chat_after = services.answer_in_chat(user, chat, "is that above answer is correct")

    assert fake.calls == []                                                     # no AI call at all
    assert mysql.calls == [check_sql(BAR_SQL)]                                  # the saved SQL, read-only, once
    assert saved.answer == CHECKED_OK
    assert saved.status == "ok" and saved.sql == BAR_SQL and saved.rows_count == 5
    assert (saved.sql_tokens, saved.answer_tokens, saved.total_tokens, saved.model) == (0, 0, 0, "")
    assert saved.conversation == chat_after == chat                             # saved in the chat, like every message
    assert saved.understood_as == f"Check of the answer to: {BAR_QUESTION}"     # "bar chart" draws the chart again
    assert set(saved.step_secs) == {"mysql", "other"}


def test_the_rows_come_back_with_the_reply(monkeypatch, mysql, user):
    mysql.results = [BAR_ROWS]
    no_ai(monkeypatch)

    result = agent.ask("is that correct?", user, context=ChatHistory.for_chat(bar_chat(user)))

    assert result.status == "ok" and result.columns == BAR_ROWS["columns"] and result.rows == BAR_ROWS["rows"]
    assert result.total_tokens == 0 and result.tries == 0


def test_the_streamed_ask_page_shows_one_step_and_no_ai_call(monkeypatch, mysql, user):
    chat = bar_chat(user)
    mysql.results = [BAR_ROWS]
    fake = no_ai(monkeypatch)
    events = services.answer_in_chat_streamed(user, chat, "Are you sure?")
    seen = []
    while True:
        try:
            seen.append(next(events))
        except StopIteration as done:
            saved, _ = done.value
            break

    assert seen == [{"type": "step", "label": answer_check.STEP_LABEL}]
    assert saved.answer == CHECKED_OK and fake.calls == []


# ---------- an honest check ----------

def test_a_number_of_the_answer_that_is_not_in_the_rows_is_named(monkeypatch, mysql, user):
    wrong = BAR_ANSWER.replace("747,750.00", "747,000.00")
    mysql.results = [BAR_ROWS]
    no_ai(monkeypatch)

    result = agent.ask("is it correct", user, context=ChatHistory.for_chat(bar_chat(user, answer=wrong)))

    assert result.answer == ("I ran the same query again on the database: 5 rows, the same as before. But this number "
                             "of my answer is not in the rows: 747,000.00. The rows below come straight from the "
                             "database - please go by them. You can open Show SQL to see the query.")
    assert "every number" not in result.answer and result.status == "ok" and result.rows == BAR_ROWS["rows"]


def test_a_changed_rows_count_is_said(monkeypatch, mysql, user):
    six = dict(BAR_ROWS, rows=BAR_ROWS["rows"] + [["May 2026", Decimal("5.00")]])
    mysql.results = [six]
    no_ai(monkeypatch)

    result = agent.ask("double check", user, context=ChatHistory.for_chat(bar_chat(user)))

    assert result.answer.startswith("I ran the same query again on the database: it now gives 6 rows, before it gave "
                                    "5 rows - the data changed since my answer. Every number in my answer is still "
                                    "in the rows.")
    assert len(result.rows) == 6


def test_a_changed_count_and_a_missing_number_are_both_said(monkeypatch, mysql, user):
    changed = dict(BAR_ROWS, rows=BAR_ROWS["rows"][:4])                       # Jun 2026 is gone
    mysql.results = [changed]
    no_ai(monkeypatch)

    result = agent.ask("verify this", user, context=ChatHistory.for_chat(bar_chat(user)))

    assert "it now gives 4 rows, before it gave 5 rows - the data changed" in result.answer
    assert "This number of my answer is not in the rows now: 12,767,485.00." in result.answer


def test_an_answer_without_amounts_says_so(monkeypatch, mysql, user):
    mysql.results = [BAR_ROWS]
    no_ai(monkeypatch)

    result = agent.ask("is this right", user,
                       context=ChatHistory.for_chat(bar_chat(user, answer=agent.ROWS_ONLY_ANSWER)))

    assert result.answer.startswith("I ran the same query again on the database: 5 rows, the same as before. My "
                                    "answer has no amounts to compare with the rows.")


def test_the_saved_sql_that_does_not_run_again_is_said(monkeypatch, mysql, user):
    mysql.results = [warehouse.QueryError("(1146) Table 'ss_gold.fact_invoice_lines' doesn't exist")]
    fake = no_ai(monkeypatch)

    result = agent.ask("can you confirm", user, context=ChatHistory.for_chat(bar_chat(user)))

    assert result.status == "error" and result.sql == "" and result.rows == [] and fake.calls == []
    assert result.answer.startswith("I tried to run the same query again, but it did not run this time ((1146) Table")
    assert "cannot check my answer" in result.answer


def test_mysql_down_gives_the_database_message(monkeypatch, mysql, user):
    mysql.results = [warehouse.WarehouseUnavailable("Cannot connect to MySQL")]
    no_ai(monkeypatch)

    result = agent.ask("is that accurate", user, context=ChatHistory.for_chat(bar_chat(user)))

    assert result.status == "error" and result.answer == agent.DB_DOWN


@pytest.mark.parametrize("answer, rows, missing", [
    ("Sales were INR 1,955,500.00.", [[Decimal("1955500.00")]], []),
    ("Sales were INR 1,955,500.", [[Decimal("1955500.40")]], []),               # rounded to the shown decimals
    ("Sales were 2.37 crore.", [[Decimal("23670966.50")]], []),                 # in crore
    ("A credit of INR 12,000.00.", [[Decimal("-12000.00")]], []),               # the sign is in the words
    ("4,097 items, 12.5% growth.", [[4097, 12.5]], []),
    ("HP-700 sold 23 units.", [["HP-700", 23]], []),
    ("On 21-May-2026 in FY 2025-26 (Aug 2026) the top 5 had 1,000.00.", [["x", Decimal("999.00")]], ["1,000.00"]),
    ("The list has more than 500 rows; 77 is not there.", [[1]], ["77"]),
])
def test_the_numbers_of_an_answer_are_found_in_the_rows(answer, rows, missing):
    assert answer_check.numbers_not_in_rows(answer, rows)[1] == missing


def test_numbers_of_the_question_and_the_sql_are_not_checked():
    checked, missing = answer_check.numbers_not_in_rows("The top 12 customers above INR 100,000.00 ...", [[1]],
                                                        "top 12 customers ... HAVING SUM(x) > 100000 LIMIT 12")
    assert checked == [] and missing == []


# ---------- no earlier answer ----------

def test_no_earlier_answer_gets_a_short_reply(monkeypatch, mysql, user):
    chat = Conversation.objects.create(user=user, title="chat")
    Question.objects.create(user=user, conversation=chat, text="Weather?", status="refused")
    fake = no_ai(monkeypatch)

    saved, _ = services.answer_in_chat(user, chat, "is that correct")

    assert saved.answer == answer_check.NO_EARLIER and saved.status == "error"
    assert fake.calls == [] and mysql.calls == [] and saved.total_tokens == 0 and saved.sql == ""


def test_an_earlier_documents_answer_is_pointed_to_its_pages(monkeypatch, mysql, user):
    chat = Conversation.objects.create(user=user, title="chat")
    sources = [{"heading": "Warranty and Returns Policy, page 1", "kind": "pdf"}]
    Question.objects.create(user=user, conversation=chat, text="warranty of gear pumps?", status="docs",
                            answer="18 months.", sources=sources)
    fake = no_ai(monkeypatch)

    saved, _ = services.answer_in_chat(user, chat, "are you sure?")

    assert saved.status == "docs" and saved.answer == answer_check.FROM_DOCUMENTS and saved.sources == sources
    assert fake.calls == [] and mysql.calls == []


def test_an_earlier_no_data_answer_has_nothing_to_check(monkeypatch, mysql, user):
    chat = Conversation.objects.create(user=user, title="chat")
    Question.objects.create(user=user, conversation=chat, text="profit in Aug?", status="nodata",
                            answer="The SS Manufacturing data does not have this: profit.")
    no_ai(monkeypatch)

    result = agent.ask("is that right?", user, context=ChatHistory.for_chat(chat))

    assert result.status == "nodata" and result.answer == answer_check.NOT_FROM_QUERY and mysql.calls == []


# ---------- how did you get this ----------

STEPS = ["Took the invoice lines (fact_invoice_lines).", "Added up net_taxable_value (net sales).",
         "Grouped by sales month.", "Kept the 5 newest months up to today."]


def test_how_did_you_get_this_gives_the_sql_in_plain_words(monkeypatch, mysql, user):
    asked = []
    monkeypatch.setattr(answer_check, "describe", lambda sql: asked.append(sql) or STEPS)
    mysql.results = [BAR_ROWS]
    fake = no_ai(monkeypatch)

    saved, _ = services.answer_in_chat(user, bar_chat(user), "how did you get this?")

    assert asked == [BAR_SQL] and fake.calls == []
    assert saved.answer == (f'This is how I found my answer to "{BAR_QUESTION}": ' + " ".join(STEPS)
                            + " Every number comes from running this query on the database.")
    assert saved.status == "ok" and saved.sql == BAR_SQL and saved.rows_count == 5 and saved.total_tokens == 0
    assert saved.understood_as == f"How the answer was found to: {BAR_QUESTION}"


def test_how_without_plain_words_points_to_show_sql(monkeypatch, mysql, user):
    monkeypatch.setattr(answer_check, "describe", lambda sql: [])
    mysql.results = [BAR_ROWS]
    no_ai(monkeypatch)

    result = agent.ask("where does this number come from", user, context=ChatHistory.for_chat(bar_chat(user)))

    assert result.answer == (f'This is how I found my answer to "{BAR_QUESTION}": the AI wrote one read-only database '
                             "query for your question and the app ran it on the database. You can open Show SQL to "
                             "see the query. Every number comes from running this query on the database.")


def test_the_plain_words_come_from_sql_words_when_it_is_there():
    """describe() uses portal/sql_words.describe_sql (the other half of this work); [] without it."""
    try:
        from portal import sql_words
    except ImportError:
        assert answer_check.describe(BAR_SQL) == []
        return
    assert answer_check.describe(BAR_SQL) == [" ".join(line.split()) for line in sql_words.describe_sql(BAR_SQL)]


def test_plain_words_that_fail_give_the_short_reply(monkeypatch):
    import sys
    broken = SimpleNamespace(describe_sql=lambda sql: 1 / 0)
    monkeypatch.setitem(sys.modules, "portal.sql_words", broken)
    assert answer_check.describe(BAR_SQL) == []


# ---------- the rules: what is a question about the previous answer ----------

CHECKS = [
    "is that correct", "is the above answer correct", "is this right", "are you sure", "is it true", "double check",
    "check it again", "verify this", "can you confirm", "is that accurate", "is that above answer is correct",
    "r u sure", "correct or not", "Is that correct?", "is it correct?", "Are these numbers right?",
    "is your answer correct or not", "this is correct?", "correct?", "please double check the numbers",
    "can you check again pls", "could you verify the answer", "is the previous answer right", "Is it really correct?",
    "are you 100% sure", "u sure?", "that answer is wrong", "I think this is wrong", "the numbers look wrong",
    "did you check it", "check this answer is correct or not", "can you confirm if this is correct",
    "is that the right answer", "how sure are you", "how accurate is this answer", "Ok, but is that correct?",
    "recheck", "cross check the above answer", "is it corect", "is that currect", "are you sure? check again",
    "is everything correct", "please confirm whether the answer is right", "That doesn’t look right",
    "i want to know if this is correct", "right or wrong", "Is that right??",
]
HOWS = [
    "how did you get this", "how did you calculate it", "where does this number come from", "explain how you got it",
    "what did you do", "How did you get these numbers?", "how do you know", "where did you get this from",
    "where do these numbers come from", "how was this calculated", "can you explain this", "explain the calculation",
    "show me how you got it", "which query did you use", "what is the logic behind this", "how you got this answer",
    "how did u calculate", "is that correct? how did you get it", "tell me the steps",
]
DATA_QUESTIONS = [
    "is Allied Castings our top customer?", "are sales in Oct correct for export?", "is it true that sales grew in Oct?",
    "are you sure sales in Oct were 5 crore", "can you check sales of Oct 2026", "verify the stock value on 20-Mar-2027",
    "how did sales do in Oct", "how do you calculate net sales", "how is net sales calculated",
    "is the data correct for export", "check the same for Sep", "confirm the order 1234", "explain the drop in sales",
    "what is the logic of new customers", "how many customers are correct", "how did you count new customers",
    "is this customer active", "correct the sales of Aug", "that is correct", "correct", "right", "ok", "thanks",
    "and for Sep?", "show above as line chart", "Top 5 customers by invoice value in Aug 2026?",
    "Remember that I only work with export sales", "is that all", "really?", "ok?", "sure",
    "which is the right product", "what is the correct price of HP-700", "is the total sales of Aug 2026 correct",
    "how are you", "explain sales in Oct", "check stock", "Are the Oct invoices correct?", "is Q1 correct", "",
    "is that correct? and what were sales in Sep", "is that correct " + "and " * 60,
]


@pytest.mark.parametrize("text", CHECKS)
def test_check_phrasings_are_found(text):
    assert answer_check.kind(text) == answer_check.CHECK


@pytest.mark.parametrize("text", HOWS)
def test_how_phrasings_are_found(text):
    assert answer_check.kind(text) == answer_check.HOW


@pytest.mark.parametrize("text", DATA_QUESTIONS)
def test_real_data_questions_are_never_taken_for_a_check(text):
    assert answer_check.kind(text) is None


def test_none_of_the_golden_questions_is_a_check():
    assert [item["question"] for item in ITEMS if answer_check.kind(item["question"]) is not None] == []


def test_a_real_data_question_in_the_chat_still_goes_to_the_ai(monkeypatch, mysql, user):
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, ["NEW", GOOD_SQL, ANSWER])

    result = agent.ask("is Allied Castings our top customer?", user, context=ChatHistory.for_chat(bar_chat(user)))

    assert len(fake.calls) == 3 and result.answer == ANSWER


# ---------- the chat memory: the next follow-up builds on the data question ----------

def test_the_next_follow_up_after_a_check_builds_on_the_data_question(monkeypatch, mysql, user):
    chat = bar_chat(user)
    mysql.results = [BAR_ROWS]
    no_ai(monkeypatch)
    services.answer_in_chat(user, chat, "is that above answer is correct")
    services.answer_in_chat(user, chat, "how did you get it")
    assert chat.questions.count() == 3

    assert [q.text for q in ChatHistory.for_chat(chat).questions] == [BAR_QUESTION]   # the checks are left out
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, ["Net sales of the last 5 sales months in Japan", GOOD_SQL, ANSWER])
    saved, _ = services.answer_in_chat(user, chat, "and for Japan?")

    rewrite = fake.calls[0][-1]["content"]
    assert f"1. {BAR_QUESTION} (latest)\n\nNew question: and for Japan?" in rewrite and "correct" not in rewrite
    sql_request = fake.calls[1][1]["content"]
    assert "Earlier in this chat" in sql_request and "1. Question: " + BAR_QUESTION in sql_request
    assert "2. Question:" not in sql_request and "I ran the same query" not in sql_request
    assert saved.understood_as == "Net sales of the last 5 sales months in Japan" and saved.answer == ANSWER


def test_a_check_after_a_check_still_checks_the_data_question(monkeypatch, mysql, user):
    chat = bar_chat(user)
    mysql.results = [BAR_ROWS, BAR_ROWS]
    no_ai(monkeypatch)
    services.answer_in_chat(user, chat, "is that correct")

    saved, _ = services.answer_in_chat(user, chat, "are you sure?")

    assert saved.answer == CHECKED_OK and mysql.calls == [check_sql(BAR_SQL)] * 2


# ---------- the MCP server and the eval: nothing changes ----------

def test_with_no_chat_the_question_takes_the_normal_path(monkeypatch, mysql, user):
    """The MCP server asks with no context: "is that correct" goes to the AI as before."""
    fake = use_fake_ai(monkeypatch, ["NO_SQL"])

    result = agent.ask("is that correct", user)

    assert len(fake.calls) == 1 and result.status == "refused" and result.answer == agent.REFUSAL_ANSWER


def test_the_eval_context_list_takes_the_normal_path(monkeypatch, mysql, user):
    """The eval gives its earlier questions as a plain list (no chat): the normal path, with the AI."""
    fake = use_fake_ai(monkeypatch, ["NEW", "NO_SQL"])
    context = [SimpleNamespace(text=BAR_QUESTION, sql=BAR_SQL, answer=BAR_ANSWER, understood_as="")]

    result = agent.ask("is that correct", user, context=context, use_memories=False)

    assert len(fake.calls) == 2 and result.status == "refused" and mysql.calls == []


def test_is_that_correct_after_a_general_answer_says_it_was_general(monkeypatch):
    """17-Nov: after a general answer (not company data) the check says so, not "the data does not have it"."""
    from types import SimpleNamespace
    from portal import answer_check
    from portal.rag import agent
    earlier = SimpleNamespace(status="general", sql="", sources=[])
    monkeypatch.setattr(answer_check, "earlier_answer", lambda context: earlier)
    result = answer_check.answer(agent.AskResult(text="is that correct?"), "check", None)
    assert result.status == "general" and result.answer == answer_check.FROM_GENERAL
