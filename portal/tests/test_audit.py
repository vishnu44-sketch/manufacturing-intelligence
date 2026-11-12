"""The audit log (portal/audit.py, models.AuditLog) and the soft delete of chats.

Every recorded action writes the right line - and no line ever holds a password or a password hash; a
failed sign-in is recorded with the name tried; a line that cannot be written never breaks the request; the
Audit API is staff-only, read-only (405 for any other method), filtered and paged; the admin only shows the
lines; MCP run_sql is recorded with its SQL and row count. A deleted chat is hidden from its owner everywhere
(list, removed list, History, chat memory, the API) but its rows stay, and staff still open its questions.
Run with:  python -m pytest -q portal/tests/test_audit.py
"""
import asyncio
import datetime
import json
import logging

import pytest
from django.contrib import admin
from django.urls import reverse
from django.utils import timezone

from portal import audit, mcp_server, usage
from portal.lc.memory import chat_questions
from portal.models import AuditLog, Conversation, Question
from portal.tests.test_chat import make_chat
from portal.tests.test_mcp import mysql as mcp_mysql  # noqa: F401
from portal.tests.test_views_ask import QUESTION, api_get, api_post, fake_ask, history, mysql  # noqa: F401

pytestmark = pytest.mark.django_db

PASSWORD = "Test-pass-123"          # the test people's password (conftest.py)
NEW_PASSWORD = "Plant-visit-2026!"


@pytest.fixture
def root(django_user_model):
    return django_user_model.objects.create_superuser("root", password=PASSWORD)


def lines(action=None):
    """The audit lines (oldest first), optionally of one action."""
    found = AuditLog.objects.order_by("created_at", "pk")
    return list(found.filter(action=action) if action else found)


def only(action):
    """The one audit line of this action."""
    found = lines(action)
    assert len(found) == 1, [line.action for line in lines()]
    return found[0]


def assert_no_secrets(*passwords):
    """No audit line holds a password, a password hash or a word for one in its details."""
    text = json.dumps([[line.username, line.target, line.details, line.user_agent] for line in lines()])
    for password in (PASSWORD, NEW_PASSWORD, *passwords):
        assert password not in text
    for hash_start in ("md5$", "pbkdf2_", "argon2", "bcrypt"):
        assert hash_start not in text
    assert "password1" not in text and "password2" not in text


# ---------- sign in / out ----------

def test_sign_in_failed_sign_in_and_sign_out_are_recorded(client, user):
    api_post(client, "api_login", {"username": "asha", "password": "wrong-guess-77"})
    client.post(reverse("api_login"), json.dumps({"username": "asha", "password": PASSWORD}),
                content_type="application/json", HTTP_USER_AGENT="Firefox/140 " + "x" * 300)
    api_post(client, "api_logout")

    failed, ok, out = only("login_failed"), only("login_ok"), only("logout")
    assert failed.user is None and failed.username == "asha" and failed.ip_address == "127.0.0.1"
    assert ok.user == user and ok.username == "asha" and ok.target == f"user {user.pk}"
    assert ok.user_agent.startswith("Firefox/140") and len(ok.user_agent) == AuditLog.USER_AGENT_CHARS
    assert out.user == user
    assert_no_secrets("wrong-guess-77")


def test_a_failed_sign_in_of_an_unknown_name_is_recorded_with_that_name(client):
    r = api_post(client, "api_login", {"username": "nobody-here", "password": "secret-try-1"})

    assert r.status_code == 400
    line = only("login_failed")
    assert line.username == "nobody-here" and line.user is None and line.details == {}
    assert_no_secrets("secret-try-1")


def test_signing_out_without_a_sign_in_writes_nothing(client):
    api_post(client, "api_logout")
    assert lines() == []


# ---------- people ----------

def test_adding_and_changing_people_is_recorded_without_any_password(client, root, user):
    client.force_login(root)
    api_post(client, "api_users", {"username": "kiran", "email": "k@example.com", "password1": NEW_PASSWORD,
                                   "password2": NEW_PASSWORD, "is_staff": True})
    api_post(client, "api_user", {"first_name": "Asha", "email": "asha@example.com"}, user.pk)
    api_post(client, "api_user", {"is_staff": True}, user.pk)
    api_post(client, "api_user_active", {"active": False}, user.pk)
    api_post(client, "api_user_active", {"active": True}, user.pk)
    api_post(client, "api_user_password", {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD}, user.pk)

    created = only("user_created")
    assert created.user == root and created.details == {"person": "kiran", "is_staff": True, "is_superuser": False}
    changed = only("user_changed")
    assert changed.target == f"user {user.pk}" and sorted(changed.details["fields"]) == ["email", "first_name"]
    assert only("user_roles_changed").details == {"person": "asha", "is_staff": [False, True]}
    assert only("user_deactivated").target == only("user_activated").target == f"user {user.pk}"
    assert only("password_reset").details == {"person": "asha", "own": False}
    assert_no_secrets()


def test_a_change_that_changes_nothing_writes_no_line(client, root, user):
    client.force_login(root)
    api_post(client, "api_user", {"first_name": user.first_name}, user.pk)
    assert lines("user_changed") == [] and lines("user_roles_changed") == []


def test_a_refused_change_writes_no_line(client, staff, user):
    client.force_login(staff)                                   # staff without the 'change user' permission
    assert api_post(client, "api_user_active", {"active": False}, user.pk).status_code == 403
    assert lines() == []


# ---------- chats and questions ----------

def test_chat_actions_are_recorded(client, user, fake_ask, mysql):
    chat = make_chat(user, "Sales in Aug?", "And Sep?")
    first = chat.questions.order_by("pk").first()
    client.force_login(user)

    api_post(client, "api_chat_rename", {"title": "Sales"}, chat.pk)
    api_post(client, "api_chat_remove", None, chat.pk)
    api_post(client, "api_chat_restore", None, chat.pk)
    edited = api_post(client, "api_edit", {"question": "Sales in Jul?"}, first.pk).json()
    api_post(client, "api_chat_delete", None, chat.pk)

    assert only("chat_renamed").details == {"old_title": "Sales in Aug?", "new_title": "Sales"}
    assert only("chat_removed").target == only("chat_restored").target == f"chat {chat.pk}"
    edit_line = only("question_edited")
    assert edit_line.target == f"question {first.pk}"
    assert edit_line.details == {"new_question": edited["card"]["id"], "chat": chat.pk}
    deleted = only("chat_deleted")
    assert deleted.details["title"] == "Sales" and deleted.details["questions"] == 3
    assert sorted(deleted.details["question_ids"]) == sorted(chat.questions.values_list("pk", flat=True))
    assert all(line.user == user and line.ip_address == "127.0.0.1" for line in lines())
    assert "Sales in" not in json.dumps([line.details for line in lines("question_edited")])  # no question text


def test_ask_again_is_recorded_and_a_plain_question_is_not(client, user, fake_ask, mysql):
    client.force_login(user)
    card = api_post(client, "api_ask", {"question": QUESTION, "chat_id": None}).json()["card"]
    assert lines() == []                                    # the Question table is the questions' audit trail

    reply = api_post(client, "api_again", None, card["id"]).json()

    line = only("ask_again")
    assert line.target == f"question {card['id']}"
    assert line.details == {"new_question": reply["card"]["id"], "chat": reply["chat"]["id"]}


def test_an_excel_download_is_recorded(client, user, mysql):
    chat = make_chat(user, QUESTION)
    saved = chat.questions.get()
    client.force_login(user)

    assert api_get(client, "api_excel", saved.pk).status_code == 200

    line = only("excel_downloaded")
    assert line.target == f"question {saved.pk}" and line.details == {"rows": 2}


# ---------- memories ----------

def test_memory_actions_are_recorded(client, user):
    client.force_login(user)
    first = api_post(client, "api_memories", {"text": "I only work with export sales"}).json()["memory"]
    api_post(client, "api_memories", {"text": "Always round to whole rupees"})
    api_post(client, "api_memory_delete", None, first["id"])
    api_post(client, "api_memories_delete_all")
    api_post(client, "api_memories_delete_all")             # nothing left: no line

    added = lines("memory_added")
    assert [line.details["text"] for line in added] == ["I only work with export sales", "Always round to whole rupees"]
    assert only("memory_deleted").target == f"memory {first['id']}"
    assert only("memory_delete_all").details == {"deleted": 1}


def test_a_memory_saved_by_a_question_is_recorded_with_the_question(client, user):
    client.force_login(user)                                # the real agent: a memory needs no AI call
    card = api_post(client, "api_ask", {"question": "Remember that I only work with export sales",
                                        "chat_id": None}).json()["card"]

    line = only("memory_added")
    assert line.details == {"text": "I only work with export sales", "question": card["id"]}


# ---------- the helper itself ----------

def test_a_line_that_cannot_be_written_never_breaks_the_request(client, user, monkeypatch, caplog):
    def broken(**fields):
        raise RuntimeError("the audit table is locked")
    monkeypatch.setattr(AuditLog.objects, "create", broken)

    with caplog.at_level(logging.WARNING, logger="portal.audit"):
        r = api_post(client, "api_login", {"username": "asha", "password": PASSWORD})

    assert r.status_code == 200 and r.json()["username"] == "asha"
    assert "could not be written" in caplog.text and "the audit table is locked" in caplog.text


def test_secret_looking_details_are_left_out_and_long_texts_cut():
    audit.record(None, "mcp_run_sql", "mcp", password="x1", api_key="x2", token="x3",
                 nested={"password_hash": "x4", "ok": "y"}, sql="S" * 5000, ids=list(range(80)))

    details = only("mcp_run_sql").details
    assert details["nested"] == {"ok": "y"} and not {"password", "api_key", "token"} & details.keys()
    assert len(details["sql"]) == audit.TEXT_CHARS and len(details["ids"]) == audit.LIST_ITEMS


def test_the_ip_behind_the_https_proxy_is_the_one_the_proxy_added(rf, settings, user):
    request = rf.get("/", HTTP_X_FORWARDED_FOR="10.9.9.9, 203.0.113.7", REMOTE_ADDR="127.0.0.1")
    assert audit.client_ip(request) == "127.0.0.1"           # not behind a proxy: the header is ignored
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    assert audit.client_ip(request) == "203.0.113.7"
    assert audit.client_ip(rf.get("/", REMOTE_ADDR="not an address")) is None


def test_a_saved_line_cannot_be_changed_or_deleted():
    audit.record(None, "mcp_get_schema", "mcp")
    line = only("mcp_get_schema")
    line.target = "changed"
    with pytest.raises(PermissionError):
        line.save()
    with pytest.raises(PermissionError):
        line.delete()
    assert only("mcp_get_schema").target == "mcp"


# ---------- the Audit API ----------

def make_lines(n, action="login_ok", username="asha", minutes_ago=0, **details):
    """n audit lines at a time in the past (one minute apart, the last is the newest)."""
    start = timezone.now() - datetime.timedelta(minutes=minutes_ago + n)
    AuditLog.objects.bulk_create([AuditLog(created_at=start + datetime.timedelta(minutes=i), username=username,
                                           action=action, target=f"user {i}", details=details) for i in range(n)])


def test_the_audit_api_is_for_staff_only(client, user):
    assert api_get(client, "api_audit").status_code == 401
    client.force_login(user)
    r = api_get(client, "api_audit")
    assert r.status_code == 403 and r.json()["detail"].startswith("Only administrators")


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_the_audit_api_has_no_way_to_write(client, staff, method):
    make_lines(1)
    client.force_login(staff)

    r = getattr(client, method)(reverse("api_audit"), data="{}", content_type="application/json")

    assert r.status_code == 405 and AuditLog.objects.count() == 1


def test_the_audit_api_pages_newest_first_with_the_action_list(client, staff):
    make_lines(120)
    client.force_login(staff)

    first = api_get(client, "api_audit").json()
    last = api_get(client, "api_audit", data={"page": 3}).json()

    assert len(first["lines"]) == 50 and first["count"] == 120 and first["pages"] == 3
    assert first["lines"][0]["target"] == "user 119" and first["has_next"] and not first["has_previous"]
    assert len(last["lines"]) == 20 and last["lines"][-1]["target"] == "user 0" and not last["has_next"]
    assert {"code": "chat_deleted", "text": "Chat deleted"} in first["actions"]
    line = first["lines"][0]
    assert line["action_text"] == "Signed in" and line["username"] == "asha" and line["created_text"]


def test_the_audit_api_filters_by_user_action_dates_and_words(client, staff):
    make_lines(3, username="asha")
    make_lines(2, action="chat_deleted", username="ravi", title="Old sales chat", question_ids=[7, 8])
    make_lines(1, username="asha", minutes_ago=3 * 24 * 60)               # three days ago
    client.force_login(staff)

    def count(**params):
        return api_get(client, "api_audit", data=params).json()["count"]

    today = timezone.localdate()
    assert count(user="ASH") == 4 and count(user="ravi") == 2
    assert count(action="chat_deleted") == 2 and count(action="login_ok", user="ravi") == 0
    assert count(**{"from": today.isoformat()}) == 5
    assert count(to=(today - datetime.timedelta(days=1)).isoformat()) == 1
    assert count(q="old sales") == 2 and count(q="user 1") == 2
    deleted = api_get(client, "api_audit", data={"action": "chat_deleted"}).json()["lines"][0]
    assert deleted["questions"] == [7, 8] and "title: Old sales chat" in deleted["summary"]
    assert api_get(client, "api_audit", data={"from": "03-11-2026"}).status_code == 400
    assert api_get(client, "api_audit", data={"action": "drop_tables"}).status_code == 400


# ---------- the admin ----------

def test_the_admin_only_shows_the_audit_log(client, root):
    audit.record(None, "mcp_get_schema", "mcp")
    line = only("mcp_get_schema")
    model_admin = admin.site._registry[AuditLog]
    client.force_login(root)

    assert client.get(reverse("admin:portal_auditlog_changelist")).status_code == 200
    assert client.get(reverse("admin:portal_auditlog_add")).status_code == 403
    assert client.post(reverse("admin:portal_auditlog_delete", args=[line.pk]), {"post": "yes"}).status_code == 403
    request = type("Request", (), {"user": root})()
    assert not model_admin.has_add_permission(request)
    assert not model_admin.has_change_permission(request, line)
    assert not model_admin.has_delete_permission(request, line)
    assert AuditLog.objects.filter(pk=line.pk).exists()


# ---------- MCP ----------

def test_mcp_run_sql_is_recorded_with_its_sql_rows_and_the_callers_address(mcp_mysql):
    sql = ("SELECT cu.state, ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr FROM fact_invoice_lines il "
           "JOIN dim_customers cu ON cu.customer_id = il.customer_id GROUP BY cu.state")
    token = audit.mcp_client_ip.set("192.0.2.10")
    try:
        mcp_server.run_sql(sql)
        with pytest.raises(Exception):
            mcp_server.run_sql("DELETE FROM fact_invoice_lines")
    finally:
        audit.mcp_client_ip.reset(token)

    ran, refused = lines("mcp_run_sql")
    assert ran.user is None and ran.username == "" and ran.ip_address == "192.0.2.10"
    assert ran.details == {"sql": sql, "checked": False, "row_count": 2}
    assert refused.details["error"] == "refused by the SQL guard" and "row_count" not in refused.details


def test_mcp_searches_and_the_schema_are_recorded(mcp_mysql, monkeypatch):
    monkeypatch.setattr(mcp_server, "search", lambda question, top_k: [])
    mcp_server.search_notes("net sales by state")
    mcp_server.get_schema(["dim_customers"])

    assert only("mcp_search_notes").details == {"question": "net sales by state", "notes": 0}
    assert only("mcp_get_schema").details == {"tables": ["dim_customers"], "tables_shown": 1}


def test_the_mcp_app_passes_the_callers_address_to_the_tools():
    seen = []

    async def inner(scope, receive, send):
        seen.append(audit.mcp_client_ip.get())

    app = mcp_server.RememberClientAddress(inner)
    asyncio.run(app({"type": "http", "client": ("198.51.100.4", 50123)}, None, None))
    asyncio.run(app({"type": "http"}, None, None))

    assert seen == ["198.51.100.4", None] and audit.mcp_client_ip.get() is None


# ---------- soft delete of a chat ----------

def test_a_deleted_chat_is_hidden_from_its_owner_everywhere(client, user, fake_ask, mysql):
    keep = make_chat(user, "Chat I keep", minutes_ago=300)
    gone = make_chat(user, "Secret plan one", "Secret plan two", minutes_ago=100)
    removed = make_chat(user, "Removed then deleted", archived=True, minutes_ago=50)
    question = gone.questions.order_by("pk").first()
    client.force_login(user)

    api_post(client, "api_chat_delete", None, gone.pk)
    api_post(client, "api_chat_delete", None, removed.pk)
    gone.refresh_from_db()

    listed = api_get(client, "api_chats").json()
    assert [c["id"] for c in listed["chats"]] == [keep.pk] and listed["removed"] == []
    assert [q["text"] for q in history(client)["questions"]] == ["Chat I keep"]
    assert api_get(client, "api_chat", gone.pk).status_code == 404
    for name in ("api_question", "api_rows", "api_excel"):
        assert api_get(client, name, question.pk).status_code == 404, name
    for name, data in (("api_chat_rename", {"title": "x"}), ("api_chat_restore", None), ("api_chat_remove", None),
                       ("api_chat_delete", None), ("api_edit", {"question": "x"}), ("api_again", None)):
        target = question.pk if name in ("api_edit", "api_again") else gone.pk
        assert api_post(client, name, data, target).status_code == 404, name
    assert api_post(client, "api_ask", {"question": QUESTION, "chat_id": gone.pk}).status_code == 404
    assert chat_questions(gone) == [] and fake_ask == []                 # no chat memory, nothing asked
    assert Conversation.objects.filter(pk=gone.pk).exists() and gone.questions.count() == 2  # rows kept
    assert len(lines("chat_deleted")) == 2


def test_staff_still_open_a_question_of_a_deleted_chat(client, user, staff, mysql):
    gone = make_chat(user, "Deleted question")
    question = gone.questions.get()
    client.force_login(user)
    api_post(client, "api_chat_delete", None, gone.pk)

    client.force_login(staff)
    r = api_get(client, "api_question", question.pk)

    assert r.status_code == 200 and r.json()["card"]["text"] == "Deleted question" and r.json()["chat"] is None
    audit_line = api_get(client, "api_audit", data={"action": "chat_deleted"}).json()["lines"][0]
    assert audit_line["questions"] == [question.pk] and audit_line["username"] == "asha"


def test_a_deleted_chat_is_hidden_also_when_its_owner_is_staff(client, staff, mysql):
    gone = make_chat(staff, "Boss's deleted chat")
    question = gone.questions.get()
    client.force_login(staff)
    api_post(client, "api_chat_delete", None, gone.pk)

    assert api_get(client, "api_chats").json()["chats"] == []
    assert history(client)["questions"] == []
    assert api_get(client, "api_chat", gone.pk).status_code == 404
    assert api_get(client, "api_question", question.pk).json()["chat"] is None   # opens only as staff, no chat


def test_the_tokens_of_a_deleted_chat_still_count_as_used(client, user, monkeypatch, mysql):
    monkeypatch.setattr(usage.agent, "model_name", lambda: "main-model")
    monkeypatch.setattr(usage.agent, "fallback_model_name", lambda: "")
    gone = make_chat(user, "Expensive question", model="main-model", total_tokens=4000)
    Question.objects.filter(conversation=gone).update(created_at=timezone.now() - datetime.timedelta(minutes=5))
    client.force_login(user)
    api_post(client, "api_chat_delete", None, gone.pk)

    rows = usage.ai_usage()["rows"]

    assert rows[0]["model"] == "main-model" and rows[0]["rolling"] == "4,000"
