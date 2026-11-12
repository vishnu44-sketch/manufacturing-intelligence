"""The JSON API of the website (/api/...) - the React app's only way to the data.

agent.ask() and MySQL are fakes (see test_views_ask.py) - no AI call, no database outside the tests.
Checks: sign in / out, 401 (never a redirect) without a sign-in, CSRF on POST, own chats and questions
only, asking with the Ask page's own rules, the answer card fields, the rows, and that the admin-only
error details never leave the server.
Run with:  python -m pytest -q portal/tests/test_api.py
"""
import json

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from portal import services, views
from portal.models import Conversation, Question
from portal.rag import agent, warehouse
from portal.tests.test_chat import make_chat
from portal.tests.test_views_ask import ANSWER, QUESTION, SQL, fake_ask, mysql, saved_question  # noqa: F401

pytestmark = pytest.mark.django_db

PDF_SOURCES = [{"heading": "Quality manual, page 4", "kind": "pdf"},
               {"heading": "Quality manual, page 5", "kind": "pdf"}]


def post(client, name, data, *args):
    return client.post(reverse(name, args=args), data=json.dumps(data), content_type="application/json")


def get(client, name, *args):
    return client.get(reverse(name, args=args))


# ---------- sign in / out ----------

def test_csrf_sets_the_cookie(client):
    r = get(client, "api_csrf")

    assert r.status_code == 200
    assert r.json()["csrfToken"]
    assert settings.CSRF_COOKIE_NAME in r.cookies


def test_sign_in_me_and_sign_out(client, user):
    r = post(client, "api_login", {"username": "asha", "password": "Test-pass-123"})
    assert r.status_code == 200
    assert r.json()["username"] == "asha" and r.json()["is_staff"] is False

    me = get(client, "api_me").json()
    assert me["username"] == "asha"
    assert me["max_question_chars"] == agent.MAX_QUESTION_CHARS and me["examples"] == services.EXAMPLES

    assert post(client, "api_logout", {}).status_code == 200
    assert get(client, "api_me").status_code == 401


def test_a_wrong_password_is_a_400_with_a_friendly_message(client, user):
    r = post(client, "api_login", {"username": "asha", "password": "wrong"})

    assert r.status_code == 400
    assert "did not match" in r.json()["detail"]
    assert get(client, "api_me").status_code == 401


def test_staff_shows_in_me(client, staff):
    client.force_login(staff)

    assert get(client, "api_me").json()["is_staff"] is True


def test_every_endpoint_needs_a_sign_in_and_answers_401_json_not_a_redirect(client, user, fake_ask):
    chat = make_chat(user, QUESTION)
    saved = chat.questions.get()
    for r in [get(client, "api_me"), get(client, "api_chats"), get(client, "api_chat", chat.pk),
              get(client, "api_rows", saved.pk), post(client, "api_ask", {"question": QUESTION, "chat_id": None})]:
        assert r.status_code == 401
        assert r["Content-Type"] == "application/json"
        assert r.json()["detail"] == "Please sign in."
    assert fake_ask == []


def test_a_wrong_method_is_405(client, user):
    client.force_login(user)

    assert get(client, "api_ask").status_code == 405
    assert post(client, "api_chats", {}).status_code == 405


def test_post_needs_the_csrf_token(user, fake_ask, mysql):
    client = Client(enforce_csrf_checks=True)

    assert post(client, "api_login", {"username": "asha", "password": "Test-pass-123"}).status_code == 403
    token = get(client, "api_csrf").json()["csrfToken"]
    r = client.post(reverse("api_login"), data=json.dumps({"username": "asha", "password": "Test-pass-123"}),
                    content_type="application/json", HTTP_X_CSRFTOKEN=token)
    assert r.status_code == 200

    no_token = post(client, "api_ask", {"question": QUESTION, "chat_id": None})
    assert no_token.status_code == 403 and "CSRF" in no_token.json()["detail"]
    assert fake_ask == []

    token = client.cookies[settings.CSRF_COOKIE_NAME].value   # a new token after the sign-in
    ok = client.post(reverse("api_ask"), data=json.dumps({"question": QUESTION, "chat_id": None}),
                     content_type="application/json", HTTP_X_CSRFTOKEN=token)
    assert ok.status_code == 200 and fake_ask == [QUESTION]


# ---------- chats ----------

def test_chats_lists_only_mine_newest_first_without_removed_ones(client, user, other):
    older = make_chat(user, "Older question", minutes_ago=600)
    newer = make_chat(user, "Newer question", minutes_ago=30)
    make_chat(user, "Removed one", archived=True)
    make_chat(other, "Ravi's question")
    client.force_login(user)

    chats = get(client, "api_chats").json()["chats"]

    assert [c["id"] for c in chats] == [newer.pk, older.pk]
    assert chats[0]["title"] == "Newer question" and chats[0]["questions"] == 1 and chats[0]["group"]


def test_a_chat_has_its_cards_in_chat_order(client, user, mysql):
    chat = make_chat(user, "First question", "Second question")
    client.force_login(user)

    data = get(client, "api_chat", chat.pk).json()

    assert data["chat"]["id"] == chat.pk and data["total"] == 2 and data["earlier"] == 0
    assert [c["text"] for c in data["cards"]] == ["First question", "Second question"]
    assert mysql == []                                       # showing a chat runs no SQL


def test_nobody_else_reaches_my_chat_or_my_question_rows(client, user, other, staff, mysql):
    chat = make_chat(user, QUESTION)
    saved = chat.questions.get()

    client.force_login(other)
    assert get(client, "api_chat", chat.pk).status_code == 404
    assert get(client, "api_rows", saved.pk).status_code == 404
    assert post(client, "api_ask", {"question": "and for Sep?", "chat_id": chat.pk}).status_code == 404

    client.force_login(staff)                                # as on the pages: chats are private,
    assert get(client, "api_chat", chat.pk).status_code == 404
    assert get(client, "api_rows", saved.pk).status_code == 200   # a saved question may be opened by staff
    assert get(client, "api_chat", 999999).json() == {"detail": "Not found."}


# ---------- asking ----------

def test_ask_starts_a_new_chat_and_returns_its_card(client, user, fake_ask, mysql):
    client.force_login(user)

    r = post(client, "api_ask", {"question": f"  {QUESTION}  ", "chat_id": None})

    assert r.status_code == 200
    saved, chat = Question.objects.get(), Conversation.objects.get()
    body = r.json()
    assert body["chat"] == {**body["chat"], "id": chat.pk, "title": QUESTION}
    assert saved.conversation == chat
    card = body["card"]
    assert card["id"] == saved.pk and card["status"] == "ok" and card["answer"] == ANSWER
    assert card["sql"] == SQL and card["has_rows"] is True
    assert card["excel_url"] == reverse("api_excel", args=[saved.pk])
    assert card["rows_url"] == reverse("api_rows", args=[saved.pk])
    assert fake_ask == [QUESTION] and fake_ask.contexts == [[]]
    assert mysql == []                                       # the rows come from their own call


def test_a_follow_up_goes_into_the_same_chat_with_its_context(client, user, fake_ask, mysql):
    client.force_login(user)
    chat_id = post(client, "api_ask", {"question": QUESTION, "chat_id": None}).json()["chat"]["id"]

    r = post(client, "api_ask", {"question": "and for Sep?", "chat_id": chat_id})

    assert r.status_code == 200 and r.json()["chat"]["id"] == chat_id
    assert Conversation.objects.count() == 1
    assert Conversation.objects.get().questions.count() == 2
    assert fake_ask.contexts[-1] == [QUESTION]               # the follow-up sees the chat so far


def test_asking_in_a_removed_chat_brings_it_back(client, user, fake_ask, mysql):
    chat = make_chat(user, QUESTION, archived=True)
    client.force_login(user)

    post(client, "api_ask", {"question": "and for Sep?", "chat_id": chat.pk})

    chat.refresh_from_db()
    assert chat.archived is False


@pytest.mark.parametrize("question, message", [
    ("", "Type a question first."),
    ("   ", "Type a question first."),
    ("x" * (agent.MAX_QUESTION_CHARS + 1), f"under {agent.MAX_QUESTION_CHARS} characters"),
])
def test_an_empty_or_too_long_question_is_a_400_and_asks_nothing(client, user, fake_ask, question, message):
    client.force_login(user)

    r = post(client, "api_ask", {"question": question, "chat_id": None})

    assert r.status_code == 400 and message in r.json()["detail"]
    assert fake_ask == [] and Conversation.objects.count() == 0


def test_a_bad_chat_id_or_body_is_a_400(client, user, fake_ask):
    client.force_login(user)

    assert post(client, "api_ask", {"question": QUESTION, "chat_id": "abc"}).status_code == 400
    assert post(client, "api_ask", {"question": QUESTION, "chat_id": True}).status_code == 400
    assert client.post(reverse("api_ask"), data="not json", content_type="application/json").status_code == 400
    assert fake_ask == []


def test_the_token_notice_comes_only_with_the_answer_just_asked(client, user, monkeypatch, mysql):
    def ask(question, user, context=None):
        saved = saved_question(user, text=question, model="openai/gpt-oss-120b",
                               sql_tokens=3_483, answer_tokens=861, total_tokens=4_344)
        return agent.AskResult(text=question, status="ok", answer=ANSWER, question=saved)

    monkeypatch.setattr(agent, "ask", ask)
    client.force_login(user)

    body = post(client, "api_ask", {"question": QUESTION, "chat_id": None}).json()

    assert body["card"]["token_notice"] == \
        "This question used 4,344 tokens (SQL 3,483 + answer 861) - openai/gpt-oss-120b"
    cards = get(client, "api_chat", body["chat"]["id"]).json()["cards"]
    assert cards[0]["token_notice"] == ""


# ---------- the answer card ----------

def test_an_answered_card_has_what_the_page_shows(client, user, monkeypatch, mysql):
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    chat = make_chat(user, QUESTION, model="qwen/qwen3.8-27b", understood_as="Top 5 customers in Aug 2026",
                     step_secs={"sql_ai": 1.2, "mysql": 0.05, "answer_ai": 0.2})
    client.force_login(user)

    card = get(client, "api_chat", chat.pk).json()["cards"][0]

    assert card["status"] == "ok" and card["row_count"] == 2 and card["secs"] == 1.5 and card["tries"] == 1
    assert card["understood_as"] == "Top 5 customers in Aug 2026"
    assert card["backup_model"] == "qwen/qwen3.8-27b"
    assert card["sql"] == SQL and card["has_rows"] is True
    assert card["sources"] == [{"kind": "example", "heading": "Q: Who were the top 5 customers by invoice value in Aug 2026?"},
                               {"kind": "rule", "heading": "NOP sales month"}]
    assert [s["label"] for s in card["time_steps"]][:2] == ["Write the SQL (AI)", "Run the SQL on MySQL"]
    assert card["created_text"] and card["created_at"] and card["edited"] is False


def test_a_documents_card_has_its_pdf_sources_and_no_sql_rows_or_excel(client, user, mysql):
    chat = make_chat(user, "What does the quality manual say about audits?", status="docs", sql="",
                     rows_count=None, sources=PDF_SOURCES, answer="Audits are made twice a year.")
    client.force_login(user)

    card = get(client, "api_chat", chat.pk).json()["cards"][0]

    assert card["status"] == "docs" and card["answer"] == "Audits are made twice a year."
    assert card["sources"] == [{"kind": "pdf", "heading": "Quality manual, page 4"},
                               {"kind": "pdf", "heading": "Quality manual, page 5"}]
    assert card["sql"] == "" and card["has_rows"] is False and card["excel_url"] == "" and card["rows_url"] == ""
    assert get(client, "api_rows", card["id"]).status_code == 404


def test_a_refused_card_never_shows_sql_even_when_some_was_saved(client, user, mysql):
    chat = make_chat(user, "Tell me a joke", status="refused", sql=SQL, answer="Not a NOP data question.")
    client.force_login(user)

    card = get(client, "api_chat", chat.pk).json()["cards"][0]

    assert card["sql"] == "" and card["has_rows"] is False


def test_the_admin_error_details_never_leave_the_server(client, user, mysql):
    secret = "OperationalError: (1045) access denied for user 'mi_reader'@'10.0.0.5'"
    chat = make_chat(user, QUESTION, status="error", sql="", error=secret, answer="Something went wrong.")
    client.force_login(user)

    r = get(client, "api_chat", chat.pk)

    assert "error" not in r.json()["cards"][0]
    assert "mi_reader" not in r.content.decode() and "OperationalError" not in r.content.decode()
    assert r.json()["cards"][0]["answer"] == "Something went wrong."


# ---------- rows ----------

def test_rows_are_formatted_like_the_page_table(client, user, mysql):
    saved = saved_question(user)
    client.force_login(user)

    data = get(client, "api_rows", saved.pk).json()

    assert data["headers"] == [{"name": "customer_name", "num": False}, {"name": "invoice_value_inr", "num": True}]
    assert data["rows"][0] == [{"text": "Aurora Fluid Power Limited", "num": False},
                               {"text": "1,730,000.00", "num": True}]
    assert data["row_count"] == 2 and data["truncated"] is False and data["rows_error"] == ""
    assert mysql == [saved.sql]                              # the saved SQL ran again (no AI call)


def test_rows_that_cannot_be_loaded_give_a_friendly_message(client, user, monkeypatch):
    def down(sql):
        raise warehouse.WarehouseUnavailable("MySQL is not running")

    monkeypatch.setattr(warehouse, "allowed_tables", lambda: {"dim_customers", "fact_invoice_lines"})
    monkeypatch.setattr(warehouse, "run_select", down)
    saved = saved_question(user)
    client.force_login(user)

    data = get(client, "api_rows", saved.pk).json()

    assert data["rows"] == [] and data["rows_error"].startswith("The rows could not be loaded again")


# ---------- CSRF on every changing call ----------

def test_every_changing_call_needs_the_csrf_token(user, staff, fake_ask, mysql):
    chat = make_chat(user, QUESTION)
    saved = chat.questions.get()
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    calls = [("api_chat_rename", chat.pk, {"title": "New"}), ("api_chat_remove", chat.pk, {}),
             ("api_chat_restore", chat.pk, {}), ("api_chat_delete", chat.pk, {}),
             ("api_edit", saved.pk, {"question": "Edited"}), ("api_again", saved.pk, {})]
    for name, pk, data in calls:
        r = post(client, name, data, pk)
        assert r.status_code == 403 and "CSRF" in r.json()["detail"], name

    client.force_login(staff)
    for name, args, data in [("api_users", (), {"username": "new", "password1": "x", "password2": "x"}),
                             ("api_user", (user.pk,), {"first_name": "A"}),
                             ("api_user_active", (user.pk,), {"active": False}),
                             ("api_user_password", (user.pk,), {"password1": "x", "password2": "x"})]:
        r = post(client, name, data, *args)
        assert r.status_code == 403 and "CSRF" in r.json()["detail"], name

    chat.refresh_from_db(); user.refresh_from_db()
    assert chat.title == QUESTION and not chat.archived and fake_ask == [] and user.is_active


# ---------- the React page ----------

def test_the_react_page_is_served_with_the_csrf_cookie(client, tmp_path, monkeypatch):
    index = tmp_path / "index.html"
    index.write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    monkeypatch.setattr(views, "REACT_INDEX", index)

    for url in ("/", "/c/12", "/new", "/app/", "/app/c/12"):          # also the old /app/ addresses
        r = client.get(url)
        assert r.status_code == 200 and b'<div id=root>' in r.content, url
    assert settings.CSRF_COOKIE_NAME in r.cookies


def test_the_old_django_pages_are_gone(client, user, tmp_path, monkeypatch):
    """The old page addresses only open the React page now: no Django template, no form posts."""
    index = tmp_path / "index.html"
    index.write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    monkeypatch.setattr(views, "REACT_INDEX", index)
    client.force_login(user)

    for url in ("/ask/", "/ask/new/", "/history/", "/users/", "/documents/", "/data/", "/login/"):
        r = client.get(url)
        assert r.status_code == 200 and r.content == b"<!doctype html><div id=root></div>", url
        assert not getattr(r, "templates", None), url                     # no Django template was rendered
    assert client.post("/ask/", {"question": QUESTION}).status_code == 405   # the old form post asks nothing
    assert not Question.objects.exists()
