"""17-Nov: the ML Insights page has its own question box. Its questions run the same flow as the Assistant in
ML mode (a chat with Conversation.mode 'ml'):
- the SQL request gets agent.ML_MODE_NOTE after the question (never the system prompt: the Assistant's questions
  pay nothing for it);
- the schema step always shows the ml_ tables (agent.tables_for_question with ml_mode);
- the notes search looks a little wider and swaps in the best ML example and the 'ML results' rules when they are
  not among the TOP_K notes (agent.ml_notes) - still TOP_K notes are sent;
- /api/ask and /api/ask/stream take "mode": "ml" for a NEW chat; a follow-up always keeps its chat's mode;
  every chat JSON says its mode.

The AI is the fake one of test_agent.py; MySQL and the notes search are faked.
Run with:  python -m pytest -q portal/tests/test_ml_mode.py
"""
import json

import pytest
from django.urls import reverse

from portal import services
from portal.models import Conversation, Question
from portal.rag import agent, warehouse
from portal.tests.test_agent import ANSWER, GOOD_SQL, HITS, ROWS, mysql, use_fake_ai  # noqa: F401
from portal.tests.test_graph import DATA_START, steps  # noqa: F401
from portal.tests.test_ml_questions import ALLOWED, ML_TABLES
from portal.tests.test_stream import fake_ai

pytestmark = pytest.mark.django_db

QUESTION = "Top customers by sales in Aug 2026?"  # its words pick fact_invoice_lines (not the whole schema)
SCHEMA = "\n".join(f"{table}: {table}_key, name" for table in sorted(ALLOWED))


@pytest.fixture
def gold(monkeypatch, mysql):
    """The fake MySQL with every ss_gold table, the ml_ tables too."""
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: ALLOWED)
    monkeypatch.setattr(warehouse, "schema_text", lambda: SCHEMA)
    return mysql


def sql_request(fake):
    """The user message of the (first) SQL call."""
    call = next(c for c in fake.calls if c[0]["content"] == agent.SQL_SYSTEM_PROMPT)
    return call[-1]["content"]


def ml_columns_shown(request):
    """The ml_ tables whose columns the SQL request shows."""
    return {table for table in ML_TABLES if f"{table}: {table}_key" in request}


def ask_api(client, question, chat_id=None, **extra):
    return client.post(reverse("api_ask"), data=json.dumps({"question": question, "chat_id": chat_id, **extra}),
                       content_type="application/json")


# ---------- what ML mode changes in the SQL request ----------

def test_an_ml_mode_question_gets_the_ml_note_and_every_ml_table(monkeypatch, gold, user, steps):
    gold.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])

    result = agent.ask(QUESTION, user, mode="ml")

    assert steps == DATA_START + ["write_sql", "check_sql", "run_sql", "explain"]   # the same flow
    assert result.status == "ok" and result.answer == ANSWER and result.mode == "ml"
    request = sql_request(fake)
    assert request.endswith(f"Question: {QUESTION}{agent.ML_MODE_NOTE}")
    assert ml_columns_shown(request) == ML_TABLES
    assert "fact_invoice_lines: fact_invoice_lines_key" in request                  # plus what the question needs
    assert agent.ML_MODE_NOTE not in fake.calls[0][0]["content"]                    # never in the system prompt


def test_a_normal_question_pays_nothing_for_ml_mode(monkeypatch, gold, user):
    gold.results = [ROWS, ROWS]
    normal = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])
    agent.ask(QUESTION, user)
    normal_request = sql_request(normal)

    assert agent.ML_MODE_NOTE not in normal_request and "ML Insights" not in normal_request
    assert ml_columns_shown(normal_request) == set()
    assert normal_request.endswith(f"Question: {QUESTION}")
    assert normal.calls[0][0]["content"] == agent.SQL_SYSTEM_PROMPT                 # the same system prompt

    ml = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])
    agent.ask(QUESTION, user, mode="ml")
    assert len(sql_request(ml)) > len(normal_request)                               # only ML mode pays for it


def test_an_unsure_question_still_sees_the_whole_schema_in_ml_mode(monkeypatch, gold, user):
    fake = use_fake_ai(monkeypatch, ["GENERAL", "Hello!"])

    agent.ask("anything interesting?", user, mode="ml")

    request = sql_request(fake)
    assert SCHEMA in request and "Other ss_gold tables" not in request              # ML mode never shows less


def test_the_schema_choice_with_and_without_ml_mode():
    assert not (agent.tables_for_question(QUESTION, [], ALLOWED) or set()) & ML_TABLES
    chosen = agent.tables_for_question(QUESTION, [], ALLOWED, ml_mode=True)
    assert ML_TABLES <= chosen and "fact_invoice_lines" in chosen
    # no ml_ tables in ss_gold yet (run_ml never ran): ML mode changes nothing
    gold_only = ALLOWED - ML_TABLES
    assert agent.tables_for_question(QUESTION, [], gold_only, ml_mode=True) == \
        agent.tables_for_question(QUESTION, [], gold_only)


def test_everything_else_is_unchanged_in_ml_mode(monkeypatch, gold, user, steps):
    fake = use_fake_ai(monkeypatch, [("GENERAL", 500), ("The capital of France is Paris.", 300)])

    result = agent.ask("what is the capital of France", user, mode="ml")

    assert steps == DATA_START + ["write_sql", "general_answer"]                     # a general answer as usual
    assert result.status == "general" and gold.calls == []
    assert fake.calls[-1][-1]["content"] == "what is the capital of France"          # no ML note in the answer


# ---------- the notes: the ML example and the ML rules are among those sent ----------

def note(n, kind="rule", heading=None, text="plain rule"):
    return {"text": text, "source": "x.md", "kind": kind, "heading": heading or f"note {n}", "score": 1 - n / 100}


ML_EXAMPLE = note(9, "example", "Q: Which customers might stop buying from us?",
                  "Example: ...\n```sql\nSELECT customer_name FROM ml_customer_risk\n```")
ML_RULES = note(12, "rule", "ML results (forecast, risk, groups, alerts, pairs, run-out) - estimates from the ml_ tables",
                "Rule: ML results ... ml_sales_forecast ...")
PLAIN = [note(n) for n in range(8)]


def test_ml_notes_swaps_in_the_ml_example_and_the_ml_rules_for_the_weakest_notes():
    hits = PLAIN[:5] + [PLAIN[5], ML_EXAMPLE, PLAIN[6], PLAIN[7], ML_RULES]

    chosen = agent.ml_notes(hits)

    assert len(chosen) == agent.TOP_K
    assert chosen == PLAIN[:3] + [ML_RULES, ML_EXAMPLE]


def test_ml_notes_keeps_the_top_notes_when_they_have_the_ml_notes_already():
    hits = [ML_EXAMPLE, ML_RULES] + PLAIN
    assert agent.ml_notes(hits) == hits[:agent.TOP_K]


def test_ml_notes_never_drops_an_ml_note_for_another():
    table_notes = [note(n, "table", f"ml_table_{n} - ...", f"ml_table_{n} columns") for n in range(5)]
    assert agent.ml_notes(table_notes + [ML_EXAMPLE]) == table_notes               # all 5 already name ml_ tables
    assert agent.ml_notes(PLAIN[:2] + [ML_EXAMPLE]) == PLAIN[:2] + [ML_EXAMPLE]      # fewer notes than TOP_K


def test_the_ml_search_looks_wider_and_sends_the_ml_notes(monkeypatch, gold, user):
    searched = []
    wide = PLAIN[:5] + [ML_EXAMPLE, ML_RULES]
    monkeypatch.setattr(agent, "search", lambda question, top_k=5: searched.append(top_k) or wide[:top_k])
    fake = use_fake_ai(monkeypatch, ["GENERAL", "Hello!", "GENERAL", "Hello!"])

    result = agent.ask("customers at risk", user, mode="ml")
    request = sql_request(fake)
    assert searched == [agent.ML_SEARCH_K]
    assert "ml_customer_risk\n```" in request and "Rule: ML results" in request
    assert "Documents (the 5 pieces" in request                                     # still TOP_K notes
    assert result.status == "general"

    fake.calls.clear()
    agent.ask("customers at risk", user)                                             # the Assistant: as before
    assert searched[-1] == agent.TOP_K
    assert "Rule: ML results" not in sql_request(fake)


# ---------- the chat's mode: saved with the first question, kept for every follow-up ----------

def test_a_new_ml_chat_is_saved_with_its_mode_and_a_follow_up_keeps_it(client, monkeypatch, gold, user):
    client.force_login(user)
    gold.results = [ROWS, ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER, "NEW", GOOD_SQL, ANSWER])

    first = ask_api(client, QUESTION, mode="ml")
    assert first.status_code == 200 and first.json()["chat"]["mode"] == "ml"
    chat = Conversation.objects.get()
    assert chat.mode == "ml"
    assert agent.ML_MODE_NOTE in sql_request(fake)

    fake.calls.clear()
    follow_up = ask_api(client, "Top customers in Sep 2026?", chat.pk)                # no mode posted
    assert follow_up.status_code == 200 and follow_up.json()["chat"]["mode"] == "ml"
    assert agent.ML_MODE_NOTE in sql_request(fake)
    assert Conversation.objects.count() == 1 and Question.objects.filter(conversation=chat).count() == 2


def test_the_posted_mode_is_ignored_for_an_existing_chat(client, monkeypatch, gold, user):
    client.force_login(user)
    gold.results = [ROWS, ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER, "NEW", GOOD_SQL, ANSWER])

    ask_api(client, QUESTION)                                                         # an Assistant chat
    chat = Conversation.objects.get()
    assert chat.mode == ""
    fake.calls.clear()
    reply = ask_api(client, "Top customers in Sep 2026?", chat.pk, mode="ml")

    assert reply.json()["chat"]["mode"] == ""
    assert agent.ML_MODE_NOTE not in sql_request(fake)
    chat.refresh_from_db()
    assert chat.mode == ""


def test_an_empty_mode_is_the_assistant(client, monkeypatch, gold, user):
    client.force_login(user)
    gold.results = [ROWS]
    use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])

    reply = ask_api(client, QUESTION, mode="")

    assert reply.status_code == 200 and reply.json()["chat"]["mode"] == ""
    assert Conversation.objects.get().mode == ""


@pytest.mark.parametrize("mode", ["xyz", "ML", 1, ["ml"]])
@pytest.mark.parametrize("url", ["api_ask", "api_ask_stream"])
def test_any_other_mode_is_refused(client, monkeypatch, gold, user, mode, url):
    client.force_login(user)
    fake = use_fake_ai(monkeypatch, [])

    r = client.post(reverse(url), data=json.dumps({"question": QUESTION, "chat_id": None, "mode": mode}),
                    content_type="application/json")

    assert r.status_code == 400 and r.json() == {"detail": "mode must be 'ml' or empty."}
    assert fake.calls == [] and Question.objects.count() == 0 and Conversation.objects.count() == 0


def test_every_chat_json_has_the_mode(client, monkeypatch, gold, user):
    client.force_login(user)
    ml_chat = Conversation.objects.create(user=user, title="Forecasts", mode="ml")
    plain = Conversation.objects.create(user=user, title="Sales")
    Question.objects.create(user=user, text="Forecast?", conversation=ml_chat, status="ok")
    removed = Conversation.objects.create(user=user, title="Old ML", mode="ml", archived=True)

    listed = client.get(reverse("api_chats")).json()
    assert {c["title"]: c["mode"] for c in listed["chats"]} == {"Forecasts": "ml", "Sales": ""}
    assert [c["mode"] for c in listed["removed"]] == ["ml"]
    assert client.get(reverse("api_chat", args=[ml_chat.pk])).json()["chat"]["mode"] == "ml"
    assert client.get(reverse("api_chat", args=[plain.pk])).json()["chat"]["mode"] == ""
    renamed = client.post(reverse("api_chat_rename", args=[ml_chat.pk]), data=json.dumps({"title": "ML"}),
                          content_type="application/json").json()
    assert renamed["chat"]["mode"] == "ml"
    restored = client.post(reverse("api_chat_restore", args=[removed.pk])).json()
    assert restored["chat"]["mode"] == "ml"


def test_editing_a_question_of_an_ml_chat_stays_in_ml_mode(monkeypatch, gold, user):
    gold.results = [ROWS, ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER, GOOD_SQL, ANSWER])
    old, chat = services.answer_in_chat(user, None, QUESTION, mode="ml")

    fake.calls.clear()
    services.edit_question(user, old, "Top customers in Sep 2026?")

    assert agent.ML_MODE_NOTE in sql_request(fake)


# ---------- the stream ----------

def test_the_stream_takes_the_mode_and_its_done_event_has_the_ml_chat(client, monkeypatch, gold, user):
    client.force_login(user)
    gold.results = [ROWS]
    fake = fake_ai(monkeypatch, [(GOOD_SQL, 3000), (ANSWER, 800)])

    r = client.post(reverse("api_ask_stream"), data=json.dumps({"question": QUESTION, "chat_id": None, "mode": "ml"}),
                    content_type="application/json")
    events = [json.loads(line) for line in b"".join(r.streaming_content).decode("utf-8").splitlines()]

    assert r.status_code == 200 and events[-1]["type"] == "done"
    assert events[-1]["chat"]["mode"] == "ml" and events[-1]["card"]["status"] == "ok"
    assert "".join(e["text"] for e in events if e["type"] == "token") == ANSWER     # the same events as before
    assert agent.ML_MODE_NOTE in sql_request(fake)
    assert Conversation.objects.get().mode == "ml"
