"""17-Nov, like ChatGPT: a message that is not about SS Manufacturing's data or documents ("what is the capital of
France", "who are you", "what is GST?") is no longer answered with the fixed REFUSAL_ANSWER. The AI decides: the
router says 'general' (when it runs), or the SQL writer replies GENERAL - then the general_answer step (graph.py)
lets the AI answer it itself, with the chat's earlier questions and answers and the user's memories. Status
'general', no SQL, no rows. NO_SQL (a request to change data or to bend the rules) still gets the fixed refusal.

The AI is always the fake one of test_agent.py; MySQL and the notes search are faked.
Run with:  python -m pytest -q portal/tests/test_general_answer.py
"""
import json

import pytest
from django.urls import reverse

from portal.lc import graph
from portal.lc.memory import ChatHistory
from portal.models import Question, UserMemory
from portal.rag import agent
from portal.tests.test_agent import ANSWER, GOOD_SQL, PDF_HITS, ROWS, mysql, use_fake_ai, use_pdf_hits  # noqa: F401
from portal.tests.test_chat import make_chat
from portal.tests.test_graph import DATA_START, steps  # noqa: F401
from portal.tests.test_stream import fake_ai, stream

pytestmark = pytest.mark.django_db

PARIS = "The capital of France is Paris."
GST = "GST (Goods and Services Tax) is India's tax on the supply of goods and services."
SIMPLER = "GST is the tax added to the price when something is sold in India."


def general_call(fake):
    """The messages of the general answer call (the last call), as {role, content} dicts."""
    return fake.calls[-1]


# ---------- the AI decides: the SQL writer's GENERAL, or the router's 'general' ----------

def test_an_off_topic_question_gets_a_general_answer_and_no_sql_runs(monkeypatch, mysql, user, steps):
    fake = use_fake_ai(monkeypatch, [("GENERAL", 5000), (PARIS, 400)])

    result = agent.ask("what is the capital of France", user)

    assert steps == DATA_START + ["write_sql", "general_answer"]
    assert result.status == "general" and result.answer == PARIS
    assert result.sql == "" and result.rows == [] and result.sources == [] and mysql.calls == []
    call = general_call(fake)
    assert call[0] == {"role": "system", "content": agent.GENERAL_SYSTEM_PROMPT}
    assert call[-1] == {"role": "user", "content": "what is the capital of France"}
    assert (result.sql_tokens, result.answer_tokens) == (5000, 400)
    assert result.tokens_text == "Tokens used: 5,400 (SQL 5,000 + answer 400)"
    saved = Question.objects.get()
    assert saved.status == "general" and saved.answer == PARIS and saved.sql == "" and saved.rows_count is None
    assert saved.get_status_display() == "General answer"
    assert "Write a general answer (AI)" in [step["label"] for step in result.time_steps]


def test_the_router_can_send_a_question_to_the_general_answer_without_the_sql_call(monkeypatch, mysql, user, steps):
    use_pdf_hits(monkeypatch, PDF_HITS)  # the router runs only when a PDF piece scores high enough
    fake = use_fake_ai(monkeypatch, [("general", 300), (GST, 600)])

    result = agent.ask("what is GST?", user)

    assert steps == ["load_memories", "route", "general_answer"]
    assert result.status == "general" and result.answer == GST and mysql.calls == []
    assert len(fake.calls) == 2 and "general" in fake.calls[0][0]["content"]       # the router knows 'general'
    assert result.tokens_text == "Tokens used: 900 (route 300 + answer 600)"        # no SQL was written


def test_who_are_you_gets_the_app_description_in_the_prompt(monkeypatch, mysql, user):
    about = "I am Manufacturing Intelligence, the assistant of SS Manufacturing."
    fake = use_fake_ai(monkeypatch, ["GENERAL", about])

    result = agent.ask("who are you", user)

    assert result.status == "general" and result.answer == about
    system = general_call(fake)[0]["content"]
    for words in ("SS Manufacturing", "Intelligence Platform", "sales, invoices", "company documents",
                  "ML insights", "sales forecasts", "customers at risk", "customer groups", "unusual invoices",
                  "bought together", "stock run-out", "charts and Excel", "SQL page"):
        assert words in system
    assert "Never invent numbers or facts about SS Manufacturing" in system


def test_a_follow_up_after_a_general_answer_gets_the_earlier_question_and_answer(monkeypatch, mysql, user):
    chat = make_chat(user, "what is GST?", status="general", sql="", answer=GST, rows_count=None)
    # the rewrite says NEW: the SQL step gets no chat, but the general answer still follows the conversation
    fake = use_fake_ai(monkeypatch, ["NEW", "GENERAL", SIMPLER])

    result = agent.ask("explain it simpler", user, context=ChatHistory.for_chat(chat))

    assert result.status == "general" and result.answer == SIMPLER
    assert general_call(fake)[1:] == [{"role": "user", "content": "what is GST?"},
                                      {"role": "assistant", "content": GST},
                                      {"role": "user", "content": "explain it simpler"}]


def test_a_follow_up_written_out_by_the_rewrite_is_named_in_the_general_prompt(monkeypatch, mysql, user):
    chat = make_chat(user, "what is GST?", status="general", sql="", answer=GST, rows_count=None)
    fake = use_fake_ai(monkeypatch, ["Explain GST in simpler words", "GENERAL", SIMPLER])

    result = agent.ask("explain it simpler", user, context=ChatHistory.for_chat(chat))

    assert result.status == "general" and result.understood_as == "Explain GST in simpler words"
    assert general_call(fake)[-1]["content"] == "explain it simpler\n(Understood as: Explain GST in simpler words)"
    assert "what is GST?" in fake.calls[0][-1]["content"]          # the rewrite saw the general question too


def test_a_general_answer_is_part_of_the_chat_memory(user):
    chat = make_chat(user, "what is GST?", status="general", sql="", answer=GST, rows_count=None)

    assert [m.content for m in ChatHistory.for_chat(chat).messages] == ["what is GST?", GST]


def test_long_earlier_answers_are_cut_for_the_general_prompt(monkeypatch, mysql, user):
    long_answer = "word " * 600
    chat = make_chat(user, "Top customers in Aug 2026?", answer=long_answer)
    fake = use_fake_ai(monkeypatch, ["NEW", "GENERAL", PARIS])

    agent.ask("what is the capital of France", user, context=ChatHistory.for_chat(chat))

    earlier = general_call(fake)[2]["content"]
    assert earlier.endswith(" ...") and len(earlier) <= agent.GENERAL_HISTORY_ANSWER_CHARS + 4
    assert "SELECT" not in json.dumps(general_call(fake)[1:])       # a general answer never sees the SQL


def test_the_users_memories_reach_the_general_prompt(monkeypatch, mysql, user):
    UserMemory.objects.create(user=user, text="Always answer in short bullet points")
    fake = use_fake_ai(monkeypatch, ["GENERAL", "- Paris"])

    result = agent.ask("what is the capital of France", user)

    assert result.status == "general"
    asked = general_call(fake)[-1]["content"]
    assert asked.startswith("what is the capital of France\n\nThe user's saved preferences")
    assert "- Always answer in short bullet points" in asked


def test_without_memories_the_general_request_is_only_the_question(monkeypatch, mysql, user):
    fake = use_fake_ai(monkeypatch, ["GENERAL", PARIS])

    agent.ask("what is the capital of France", user)

    assert general_call(fake) == [{"role": "system", "content": agent.GENERAL_SYSTEM_PROMPT},
                                  {"role": "user", "content": "what is the capital of France"}]


# ---------- what stays as it was ----------

def test_a_request_to_delete_data_is_still_refused_with_the_fixed_sentence(monkeypatch, mysql, user, steps):
    fake = use_fake_ai(monkeypatch, ["NO_SQL"])

    result = agent.ask("delete all credit notes from the database", user)

    assert steps == DATA_START + ["write_sql"]
    assert result.status == "refused" and result.answer == agent.REFUSAL_ANSWER
    assert len(fake.calls) == 1 and mysql.calls == []                # no general answer call


def test_a_data_question_still_goes_the_sql_way(monkeypatch, mysql, user, steps):
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert steps == DATA_START + ["write_sql", "check_sql", "run_sql", "explain"]
    assert result.status == "ok" and result.answer == ANSWER and len(mysql.calls) == 1
    assert all(call[0]["content"] != agent.GENERAL_SYSTEM_PROMPT for call in fake.calls)


@pytest.mark.parametrize("reply, kind", [
    ("GENERAL", "general"),
    ("general", "general"),
    ("`GENERAL`", "general"),
    ("<think>not about the business</think>\nGENERAL", "general"),
    ("NO_SQL", "no_sql"),
    ("GENERAL or NO_SQL", "no_sql"),                                 # unsure: the safe refusal wins
    ("```sql\nSELECT 'GENERAL' AS x FROM dim_customers\n```", "sql"),
])
def test_the_sql_writers_general_reply_is_read(reply, kind):
    assert agent.read_sql_reply(reply)[0] == kind


@pytest.mark.parametrize("reply, route", [("general", "general"), ("General.", "general"), ("data", "data"),
                                          ("documents", "documents"), ("", "data")])
def test_the_routers_general_reply_is_read(reply, route):
    assert agent.read_route_reply(reply) == route


def test_the_prompts_know_the_general_kind():
    assert "C) the single word GENERAL" in agent.SQL_SYSTEM_PROMPT
    assert "NO_DATA / GENERAL / NO_SQL" in agent.RETRY_PROMPT
    assert "- general:" in agent.ROUTE_SYSTEM_PROMPT and "both or general" in agent.ROUTE_REQUEST


# ---------- the card, the stream and the step label ----------

def test_the_step_label_exists():
    assert ("general", "Write a general answer (AI)") in agent.STEP_NAMES
    assert graph.NODE_LABELS["general_answer"] == "Write a general answer (AI)"


def test_the_card_of_a_general_answer(client, monkeypatch, mysql, user):
    client.force_login(user)
    use_fake_ai(monkeypatch, [("GENERAL", 5000), (PARIS, 400)])

    r = client.post(reverse("api_ask"), data=json.dumps({"question": "what is the capital of France", "chat_id": None}),
                    content_type="application/json")

    card = r.json()["card"]
    assert card["status"] == "general" and card["answer"] == PARIS
    assert card["has_rows"] is False and card["sql"] == "" and card["rows_url"] == "" and card["chart_kind"] == ""
    assert card["sources"] == []
    assert card["token_notice"].startswith("This question used 5,400 tokens (SQL 5,000 + answer 400)")


def test_a_general_answer_is_streamed_with_its_own_step(client, monkeypatch, mysql, user):
    client.force_login(user)
    fake = fake_ai(monkeypatch, [("GENERAL", 5000), (PARIS, 400)])

    _, events = stream(client, "what is the capital of France")

    labels = [e["label"] for e in events if e["type"] == "step"]
    assert labels[-2:] == ["Write the SQL (AI)", "Write a general answer (AI)"]
    assert "".join(e["text"] for e in events if e["type"] == "token") == PARIS
    assert fake.streamed == [2]                                    # only the general answer is streamed
    assert events[-1]["card"]["status"] == "general"
    assert Question.objects.get().status == "general"
