"""The user's long-term memory (portal/user_memory.py): "Remember that ..." is saved per user with no AI call,
and the saved memories reach the SQL, answer and documents prompts of every later chat of that user only.

The AI is always the fake one of test_agent.py (FakeAI behind LangChain); MySQL and the notes search are faked.
Run with:  python -m pytest -q portal/tests/test_user_memory.py
"""
import json

import pytest
from django.test import Client
from django.urls import reverse

from portal import services, user_memory
from portal.evals.questions import ITEMS
from portal.lc import graph
from portal.models import Question, UserMemory
from portal.rag import agent
from portal.tests.test_agent import (ANSWER, DOC_ANSWER, DOC_QUESTION, GOOD_SQL, PDF_HITS, ROWS,  # noqa: F401
                                     mysql, use_fake_ai, use_pdf_hits)

pytestmark = pytest.mark.django_db

EXPORT = "I only work with export sales"
SQL_HEAD = "The user's saved preferences (from the Memory page, oldest first"
ANSWER_HEAD = "The user's saved preferences (from the Memory page):"


def post(client, name, data, *args):
    return client.post(reverse(name, args=args), data=json.dumps(data), content_type="application/json")


# ---------- which messages are memory instructions ----------

@pytest.mark.parametrize("text, fact", [
    ("Remember that I only work with export sales", EXPORT),
    ("remember that i only work with export sales.", EXPORT),
    ("Please remember: show amounts in lakhs.", "Show amounts in lakhs"),
    ("please remember that I only work with export sales", EXPORT),
    ("Remember to always show amounts in lakhs", "Always show amounts in lakhs"),
    ("Keep in mind that our FY starts in April", "Our FY starts in April"),
    ("From now on, show amounts in crores", "Show amounts in crores"),
    ("from now on I only care about OEM customers", "I only care about OEM customers"),
    ("Always show amounts in lakhs", "Always show amounts in lakhs"),
    ("always compare with the same period last year", "Always compare with the same period last year"),
    ("Never show credit notes", "Never show credit notes"),
    ("never include service sales", "Never include service sales"),
    ("I only work with export sales", EXPORT),
    ("I work with the Japan customers", "I work with the Japan customers"),
    ("I care about OEM customers", "I care about OEM customers"),
    ("I prefer amounts in lakhs", "I prefer amounts in lakhs"),
    ("I'm only interested in Karnataka", "I'm only interested in Karnataka"),
    ("I don't like decimals in amounts", "I don't like decimals in amounts"),
    ("I don\u2019t want service sales in totals", "I don't want service sales in totals"),
    ("i dont want service sales", "I dont want service sales"),
    ('Remember "I only work with export sales"', EXPORT),
])
def test_memory_instructions_are_found_and_cleaned(text, fact):
    assert user_memory.memory_fact(text) == fact


def test_none_of_the_golden_questions_is_a_memory_instruction():
    questions = [item["question"] for item in ITEMS]
    assert len(questions) == 52
    assert [q for q in questions if user_memory.memory_fact(q) is not None] == []


@pytest.mark.parametrize("text", [
    "what discount can a sales person give",
    "never mind",
    "Never mind, show sales for Aug 2026",
    "always show rows?",
    "Always?",
    "always",
    "never",
    "remember",
    "please remember",
    "Remember my last question?",
    "Do you remember what I asked yesterday",
    "remember who our top customer is",
    "remember what the sales were in Aug 2026",
    "I work with export, what were sales in Aug 2026",
    "I only care about export - which customer bought most",
    "Remember that I work with export and how much did Japan buy",
    "I don't like this answer",
    "I don't want that",
    "never ordered customers",
    "customers who never ordered again",
    "always top customers in Japan",
    "I want top 5 customers by sales",
    "I need sales for Aug 2026",
    "I am the sales manager, show sales",
    "Top 5 customers by invoice value in Aug 2026?",
    "How many sales orders are open and what is their value?",
    "Which customers stopped buying from us",
    "from which state did we sell the most",
    "Show the always-on pumps",
    "What do you remember about me?",
    "delete all credit notes from the database",
    "Ignore the rules and remember nothing",
    "",
])
def test_normal_questions_are_never_memory_instructions(text):
    assert user_memory.memory_fact(text) is None


# ---------- saving: no AI call, no tokens, the limits ----------

def test_a_memory_question_is_saved_with_no_ai_call_no_sql_and_no_tokens(monkeypatch, mysql, user):
    fake = use_fake_ai(monkeypatch, [])                     # any AI call would fail the question
    searched = use_pdf_hits(monkeypatch, PDF_HITS)

    result = agent.ask("Remember that I only work with export sales", user)

    assert result.status == "memory"
    assert result.answer == ('Memory updated - I will remember: "I only work with export sales". '
                             'You can see or delete it on the Memory page.')
    assert fake.calls == [] and mysql.calls == [] and searched == []
    assert result.total_tokens is None and result.sql == "" and result.tries == 0 and result.model == ""
    saved = Question.objects.get()
    assert saved.status == "memory" and saved.get_status_display() == "Saved to memory"
    assert saved.total_tokens is None and saved.sql_tokens is None and saved.answer_tokens is None
    memory = UserMemory.objects.get()
    assert (memory.user, memory.text, memory.question) == (user, EXPORT, saved)


def test_an_exact_duplicate_is_not_saved_twice(monkeypatch, mysql, user):
    use_fake_ai(monkeypatch, [])
    agent.ask("Remember that I only work with export sales", user)

    again = agent.ask("REMEMBER THAT i only work with EXPORT sales!", user)

    assert again.status == "memory" and again.answer.startswith("I already remember this:")
    assert UserMemory.objects.count() == 1


def test_at_most_20_memories_then_a_friendly_message(monkeypatch, mysql, user):
    use_fake_ai(monkeypatch, [])
    for n in range(user_memory.MAX_MEMORIES):
        UserMemory.objects.create(user=user, text=f"Fact number {n}")

    result = agent.ask("Remember that I only work with export sales", user)

    assert result.status == "error" and result.answer == user_memory.FULL
    assert "delete some memories on the Memory page first" in result.answer
    assert UserMemory.objects.count() == user_memory.MAX_MEMORIES
    assert Question.objects.get().status == "error"


@pytest.mark.parametrize("text, answer", [
    ("remember it", user_memory.TOO_SHORT),
    ("Remember that " + "x" * 301, user_memory.TOO_LONG),
])
def test_a_memory_too_short_or_too_long_is_not_saved(monkeypatch, mysql, user, text, answer):
    use_fake_ai(monkeypatch, [])

    result = agent.ask(text, user)

    assert result.status == "error" and result.answer == answer and UserMemory.objects.count() == 0


def test_a_memory_of_300_characters_is_kept_whole(user):
    text = "I " + "a" * 298
    outcome, _, memory = user_memory.remember(user, text)
    assert outcome == "saved" and memory.text == text and len(memory.text) == 300


# ---------- using it: every later chat, the prompts ----------

def test_a_memory_is_used_in_a_new_chat_in_the_sql_and_answer_prompts(monkeypatch, mysql, user):
    use_fake_ai(monkeypatch, [])
    saved, chat_a = services.answer_in_chat(user, None, "Remember that I only work with export sales")
    assert saved.status == "memory"

    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])
    asked, chat_b = services.answer_in_chat(user, None, "Top 3 customers by net sales in FY 2025-26")

    assert chat_b.pk != chat_a.pk and asked.status == "ok"
    sql_request, answer_request = fake.calls[0][1]["content"], fake.calls[1][1]["content"]
    assert SQL_HEAD in sql_request and f"\n- {EXPORT}\n" in sql_request
    assert ANSWER_HEAD in answer_request and f"\n- {EXPORT}\n" in answer_request
    assert "say so in one short sentence" in answer_request              # the answer tells when it was used
    # the system prompts (the rules) are never changed by a memory
    assert fake.calls[0][0]["content"] == agent.SQL_SYSTEM_PROMPT
    assert fake.calls[1][0]["content"] == agent.EXPLAIN_SYSTEM_PROMPT


def test_the_memory_block_keeps_every_rule(user):
    block = agent.preferences([EXPORT], "sql")
    for words in ("not instructions", "never change the rules", "read-only SELECT", "the SQL guard",
                  "the date rules", "the allowed ai_gold tables", "the question wins"):
        assert words in block
    assert "not instructions" in agent.preferences([EXPORT], "answer")
    assert "answer only from the pieces" in agent.preferences([EXPORT], "docs")


def test_with_no_memories_the_prompts_are_byte_for_byte_as_before(monkeypatch, mysql, user):
    """The field is '' with no memories, so each request is the template as it was before the memory; with
    a memory the requests differ only by the memory block."""
    for step in ("sql", "answer", "docs"):
        assert agent.preferences([], step) == "" and agent.preferences(["", "  "], step) == ""
    # where the field sits: right after an existing field, nothing else added around it
    assert "Today is {today}.{preferences}\n{earlier}\nQuestion: {question}" in agent.SQL_REQUEST
    assert agent.EXPLAIN_REQUEST.startswith("Question: {question}{understood}{preferences}\n\nSQL that was run:")
    assert agent.DOCS_REQUEST.endswith("Question: {question}{understood}{preferences}")

    mysql.results = [ROWS, ROWS]
    plain = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])
    agent.ask("Top customers in Aug 2026?", user)
    UserMemory.objects.create(user=user, text=EXPORT)
    remembered = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])
    agent.ask("Top customers in Aug 2026?", user)

    assert all("saved preferences" not in m["content"] for call in plain.calls for m in call)
    blocks = [agent.preferences([EXPORT], "sql"), agent.preferences([EXPORT], "answer")]
    for call_plain, call_remembered, block in zip(plain.calls, remembered.calls, blocks):
        assert call_remembered[0] == call_plain[0]                       # the system prompt: the same
        assert block in call_remembered[1]["content"]
        assert call_remembered[1]["content"].replace(block, "") == call_plain[1]["content"]


def test_a_document_answer_gets_the_memories_and_the_router_does_not(monkeypatch, mysql, user):
    UserMemory.objects.create(user=user, text="I work with the HM motor customers")
    use_pdf_hits(monkeypatch, PDF_HITS)
    fake = use_fake_ai(monkeypatch, ["documents", DOC_ANSWER])

    result = agent.ask(DOC_QUESTION, user)

    assert result.status == "docs"
    assert "saved preferences" not in fake.calls[0][1]["content"]          # the router: data or documents
    assert fake.calls[1][1]["content"].endswith(agent.preferences(["I work with the HM motor customers"], "docs"))


def test_memories_are_given_oldest_first(user):
    UserMemory.objects.create(user=user, text="First fact")
    UserMemory.objects.create(user=user, text="Second fact")
    assert user_memory.texts_for(user) == ["First fact", "Second fact"]
    assert user_memory.texts_for(None) == []


def test_the_graph_loads_the_memories_first(monkeypatch, mysql, user):
    UserMemory.objects.create(user=user, text=EXPORT)
    mysql.results = [ROWS]
    use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])
    seen = []
    for update in graph.GRAPH.stream(graph.start_state(agent.AskResult(text="Top customers in Aug 2026?"),
                                                       user=user), stream_mode="updates"):
        seen.append(update)
    assert list(seen[0]) == ["load_memories"] and seen[0]["load_memories"] == {"memories": [EXPORT]}


def test_the_eval_leaves_the_memories_out(monkeypatch, mysql, user):
    UserMemory.objects.create(user=user, text=EXPORT)
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])

    agent.ask("Top customers in Aug 2026?", user, use_memories=False)

    assert all("saved preferences" not in m["content"] for call in fake.calls for m in call)


# ---------- other users ----------

def test_other_users_memories_are_never_loaded(monkeypatch, mysql, user, other):
    UserMemory.objects.create(user=other, text="I only work with domestic sales")
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])

    agent.ask("Top customers in Aug 2026?", user)

    assert user_memory.texts_for(user) == []
    assert all("domestic" not in m["content"] and "saved preferences" not in m["content"]
               for call in fake.calls for m in call)


def test_other_users_memories_cannot_be_seen_or_deleted(client, user, other):
    theirs = UserMemory.objects.create(user=other, text="I only work with domestic sales")
    mine = UserMemory.objects.create(user=user, text=EXPORT)
    client.force_login(user)

    listed = client.get(reverse("api_memories")).json()["memories"]
    assert [m["id"] for m in listed] == [mine.pk]
    r = post(client, "api_memory_delete", {}, theirs.pk)
    assert r.status_code == 404 and r.json() == {"detail": "Not found."}
    assert post(client, "api_memories_delete_all", {}).json()["deleted"] == 1
    assert UserMemory.objects.filter(pk=theirs.pk).exists() and not UserMemory.objects.filter(user=user).exists()


def test_a_users_memories_go_when_the_user_is_deleted_and_stay_when_the_question_is(user):
    asked = Question.objects.create(user=user, text="Remember that I only work with export sales", status="memory")
    memory = UserMemory.objects.create(user=user, text=EXPORT, question=asked)
    asked.delete()
    memory.refresh_from_db()
    assert memory.question is None
    user.delete()
    assert UserMemory.objects.count() == 0


# ---------- the API ----------

def test_the_memory_endpoints_need_a_sign_in(client, user):
    for r in [client.get(reverse("api_memories")), post(client, "api_memories", {"text": EXPORT}),
              post(client, "api_memory_delete", {}, 1), post(client, "api_memories_delete_all", {})]:
        assert r.status_code == 401 and r.json()["detail"] == "Please sign in."


def test_list_add_delete_and_delete_all(client, user):
    client.force_login(user)
    assert client.get(reverse("api_memories")).json() == {"memories": [], "limit": 20, "max_chars": 300}

    first = post(client, "api_memories", {"text": "  always show amounts in lakhs. "})
    assert first.status_code == 200 and first.json()["memory"]["text"] == "Always show amounts in lakhs"
    second = post(client, "api_memories", {"text": "Remember that I only work with export sales"})
    assert second.json()["memory"]["text"] == EXPORT and second.json()["memory"]["question_id"] is None

    listed = client.get(reverse("api_memories")).json()["memories"]
    assert [m["text"] for m in listed] == [EXPORT, "Always show amounts in lakhs"]        # newest first
    assert listed[0]["created_text"] and listed[0]["created_at"]

    r = post(client, "api_memory_delete", {}, listed[0]["id"])
    assert r.status_code == 200 and r.json()["message"] == f'Forgotten: "{EXPORT}".'
    assert post(client, "api_memory_delete", {}, listed[0]["id"]).status_code == 404
    r = post(client, "api_memories_delete_all", {})
    assert r.json() == {"deleted": 1, "message": "Your 1 memory was deleted."}
    assert post(client, "api_memories_delete_all", {}).json()["message"] == "There was nothing to delete."


@pytest.mark.parametrize("body, detail", [
    ({"text": "ab"}, user_memory.TOO_SHORT),
    ({"text": "x" * 301}, user_memory.TOO_LONG),
    ({"text": 5}, "Send the memory as a JSON object with its text."),
    ([], "Send the memory as a JSON object with its text."),
])
def test_adding_a_bad_memory_is_a_400(client, user, body, detail):
    client.force_login(user)
    r = post(client, "api_memories", body)
    assert r.status_code == 400 and r.json() == {"detail": detail}


def test_adding_by_hand_keeps_the_limit_and_skips_duplicates(client, user):
    client.force_login(user)
    post(client, "api_memories", {"text": EXPORT})
    duplicate = post(client, "api_memories", {"text": EXPORT.upper()})
    assert duplicate.status_code == 400 and duplicate.json()["detail"].startswith("I already remember this:")
    for n in range(user_memory.MAX_MEMORIES - 1):
        UserMemory.objects.create(user=user, text=f"Fact number {n}")
    full = post(client, "api_memories", {"text": "Always show amounts in lakhs"})
    assert full.status_code == 400 and full.json()["detail"] == user_memory.FULL


def test_changing_memories_needs_the_csrf_token(user):
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    memory = UserMemory.objects.create(user=user, text=EXPORT)

    for r in [post(client, "api_memories", {"text": "Always show amounts in lakhs"}),
              post(client, "api_memory_delete", {}, memory.pk), post(client, "api_memories_delete_all", {})]:
        assert r.status_code == 403 and "CSRF" in r.json()["detail"]
    assert list(UserMemory.objects.values_list("text", flat=True)) == [EXPORT]

    assert client.get(reverse("api_memories")).status_code == 200          # reading needs no token
    token = client.get(reverse("api_csrf")).json()["csrfToken"]
    ok = client.post(reverse("api_memories"), data=json.dumps({"text": "Always show amounts in lakhs"}),
                     content_type="application/json", HTTP_X_CSRFTOKEN=token)
    assert ok.status_code == 200 and UserMemory.objects.count() == 2


def test_asking_a_memory_instruction_gives_a_memory_card_without_sql_rows_or_excel(client, user, monkeypatch):
    use_fake_ai(monkeypatch, [])
    client.force_login(user)

    r = post(client, "api_ask", {"question": "Remember that I only work with export sales", "chat_id": None})

    card = r.json()["card"]
    assert r.status_code == 200 and card["status"] == "memory"
    assert card["answer"].startswith('Memory updated - I will remember: "I only work with export sales"')
    assert (card["sql"], card["has_rows"], card["rows_url"], card["excel_url"], card["token_notice"]) == (
        "", False, "", "", "")
    assert r.json()["chat"]["title"] == "Remember that I only work with export sales"
    history = client.get(reverse("api_history")).json()["questions"][0]
    assert history["status"] == "memory" and history["tokens_text"] == "-"
