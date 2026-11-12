"""Asking, saved answers, the Excel download and History - through the JSON API (/api/...).

agent.ask() is replaced by a fake (no AI), and MySQL by a fake run_select (no database).
POST /api/ask answers and saves the question (a new chat when chat_id is null); showing a chat or a
saved answer (/api/chats/<id>, /api/questions/<id>) never asks the AI again, and only the rows call
(/api/questions/<id>/rows) runs the saved SQL again. The chats: test_chat.py.
Run with:  python -m pytest -q portal/tests/test_views_ask.py
"""
import datetime
import io
import json
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from portal import services
from portal.models import Conversation, Question
from portal.rag import agent, warehouse
from portal.rag.sql_guard import check_sql

pytestmark = pytest.mark.django_db

TABLES = {"dim_customers", "fact_invoice_lines"}
SQL = check_sql("SELECT cu.customer_name, ROUND(SUM(il.net_taxable_value), 2) AS invoice_value_inr "
                "FROM fact_invoice_lines il JOIN dim_customers cu ON cu.customer_id = il.customer_id "
                "GROUP BY cu.customer_name ORDER BY invoice_value_inr DESC LIMIT 5", TABLES)
ROWS = {"columns": ["customer_name", "invoice_value_inr"],
        "rows": [["Aurora Fluid Power Limited", Decimal("1730000.00")],
                 ["Meridian Hydraulics Limited", Decimal("747750.00")]],
        "truncated": False}
ANSWER = "Aurora Fluid Power Limited had the highest invoice value, INR 1,730,000.00."
SOURCES = [{"heading": "Q: Who were the top 5 customers by invoice value in Aug 2026?", "kind": "example"},
           {"heading": "NOP sales month", "kind": "rule"}]
QUESTION = "Top 5 customers by invoice value?"


@pytest.fixture
def mysql(monkeypatch):
    """Fake MySQL: the table list for the guard, and run_select returning ROWS.
    mysql.calls = every SQL that was run."""
    calls = []

    def run_select(sql):
        calls.append(sql)
        return ROWS

    monkeypatch.setattr(warehouse, "allowed_tables", lambda: TABLES)
    monkeypatch.setattr(warehouse, "run_select", run_select)
    return calls


class Asked(list):
    """The questions the fake agent was asked, plus .contexts (the chat context of each)."""

    def __init__(self):
        super().__init__()
        self.contexts = []


@pytest.fixture
def fake_ask(monkeypatch):
    """Fake agent.ask(): saves an answered Question like the real one, but without the AI.
    fake_ask (the list) = every question it was asked; fake_ask.contexts = the earlier questions
    (chat context) passed with each one."""
    asked = Asked()

    def ask(question, user, context=None):
        asked.append(question)
        asked.contexts.append([q.text for q in (context or [])])
        saved = Question.objects.create(user=user, text=question, sql=SQL, answer=ANSWER,
                                        rows_count=2, secs=1.5, status="ok", sources=SOURCES, tries=1)
        return agent.AskResult(text=question, status="ok", answer=ANSWER, sql=SQL,
                               columns=ROWS["columns"], rows=ROWS["rows"], sources=SOURCES,
                               secs=1.5, tries=1, question=saved)

    monkeypatch.setattr(agent, "ask", ask)
    return asked


def saved_question(user, **fields):
    """An answered question in the test database (like one agent.ask() saved)."""
    values = dict(text=QUESTION, sql=SQL, answer=ANSWER, rows_count=2, secs=1.5,
                  status="ok", sources=SOURCES, tries=1)
    values.update(fields)
    return Question.objects.create(user=user, **values)


def api_get(client, name, *args, data=None):
    """GET an API address by its URL name."""
    return client.get(reverse(name, args=args), data or {})


def api_post(client, name, data=None, *args):
    """POST JSON to an API address by its URL name."""
    return client.post(reverse(name, args=args), data=json.dumps(data or {}), content_type="application/json")


def ask(client, question, chat_id=None):
    return api_post(client, "api_ask", {"question": question, "chat_id": chat_id})


def history(client, page=None):
    return api_get(client, "api_history", data={"page": page} if page else None).json()


# ---------- asking ----------

def test_ask_saves_the_question_in_a_new_chat_titled_by_it(client, user, fake_ask, mysql):
    client.force_login(user)

    r = ask(client, QUESTION)

    saved = Question.objects.get()
    chat = Conversation.objects.get()                            # a new chat, titled by the question
    assert r.status_code == 200
    assert r.json()["chat"]["id"] == chat.pk and r.json()["card"]["id"] == saved.pk
    assert saved.conversation == chat and chat.title == QUESTION
    assert fake_ask == [QUESTION]


def test_after_asking_the_chat_has_the_answer_rows_sql_and_sources(client, user, fake_ask, mysql):
    client.force_login(user)
    chat_id = ask(client, QUESTION).json()["chat"]["id"]

    card = api_get(client, "api_chat", chat_id).json()["cards"][-1]
    rows = client.get(card["rows_url"]).json()

    saved = Question.objects.get()
    assert card["id"] == saved.pk and card["status"] == "ok"
    assert card["answer"] == ANSWER
    assert "FROM fact_invoice_lines" in card["sql"]                          # the SQL
    assert [s["heading"] for s in card["sources"]] == [s["heading"] for s in SOURCES]   # the 2 sources
    assert rows["rows"][0][0]["text"] == "Aurora Fluid Power Limited" and rows["rows"][0][1]["text"] == "1,730,000.00"
    assert rows["row_count"] == 2 and card["row_count"] == 2
    assert card["excel_url"] == reverse("api_excel", args=[saved.pk])       # Download Excel


def test_a_saved_answer_has_its_answer_rows_sql_and_sources(client, user, mysql):
    saved = saved_question(user)
    client.force_login(user)

    body = api_get(client, "api_question", saved.pk).json()
    rows = api_get(client, "api_rows", saved.pk).json()

    card = body["card"]
    assert card["status"] == "ok" and card["answer"] == ANSWER and card["text"] == QUESTION
    assert "FROM fact_invoice_lines" in card["sql"] and card["sources"][1]["heading"] == "NOP sales month"
    assert "1,730,000.00" in json.dumps(rows) and rows["row_count"] == 2
    assert card["excel_url"] == reverse("api_excel", args=[saved.pk])
    assert body["chat"] is None                                              # this one is in no chat


def test_a_saved_answer_says_when_the_backup_model_answered(client, user, mysql, monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    by_backup = saved_question(user, model="qwen/qwen3.8-27b")
    by_main = saved_question(user, model="openai/gpt-oss-120b")
    client.force_login(user)

    backup = api_get(client, "api_question", by_backup.pk).json()["card"]
    main = api_get(client, "api_question", by_main.pk).json()["card"]
    rows = history(client)["questions"]

    assert backup["backup_model"] == "qwen/qwen3.8-27b"
    assert main["backup_model"] == ""
    assert [r["backup"] for r in rows].count(True) == 1


def test_showing_a_chat_again_does_not_ask_the_ai_again(client, user, fake_ask, mysql):
    """Showing a chat never calls the AI; only the rows call re-runs the saved SQL (guard + read-only MySQL)."""
    client.force_login(user)
    body = ask(client, QUESTION).json()

    for _ in range(2):                                           # the browser refresh
        api_get(client, "api_chat", body["chat"]["id"])
        client.get(body["card"]["rows_url"])

    assert fake_ask == [QUESTION]   # the AI was asked once
    assert len(mysql) == 2          # the rows were loaded once per view
    assert mysql[0].rstrip().endswith("LIMIT 5")


@pytest.mark.parametrize("question, message", [
    ("   ", "Type a question first."),
    ("x" * 1001, "Please keep the question under 1000 characters."),
])
def test_empty_or_too_long_question_is_not_sent_to_the_ai(client, user, fake_ask, question, message):
    client.force_login(user)

    r = ask(client, question)

    assert r.status_code == 400
    assert r.json()["detail"] == message
    assert fake_ask == []
    assert not Question.objects.exists() and not Conversation.objects.exists()


def test_refused_question_has_no_sql_and_runs_nothing(client, user, mysql):
    saved = saved_question(user, text="What is the capital of France?", status="refused",
                           sql="", answer=agent.REFUSAL_ANSWER, rows_count=None, sources=[])
    client.force_login(user)

    card = api_get(client, "api_question", saved.pk).json()["card"]

    assert card["status"] == "refused"                           # NOT A NOP DATA QUESTION
    assert card["answer"] == agent.REFUSAL_ANSWER
    assert card["sql"] == "" and card["excel_url"] == "" and card["has_rows"] is False
    assert api_get(client, "api_rows", saved.pk).status_code == 404
    assert mysql == []


def test_a_saved_answer_still_shows_when_the_rows_cannot_be_loaded(client, user, monkeypatch):
    def mysql_refuses(sql):
        raise warehouse.QueryError("(1146) Table 'ai_gold.dim_customers' doesn't exist")
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: TABLES)
    monkeypatch.setattr(warehouse, "run_select", mysql_refuses)
    saved = saved_question(user)
    client.force_login(user)

    card = api_get(client, "api_question", saved.pk).json()["card"]
    rows = api_get(client, "api_rows", saved.pk).json()

    assert card["answer"] == ANSWER
    assert rows["rows_error"].startswith("The rows could not be loaded again")
    assert rows["rows"] == []


# ---------- who may see what ----------

def test_asking_and_saved_answers_need_a_sign_in(client, user, fake_ask):
    saved = saved_question(user)
    for name in ("api_question", "api_rows", "api_excel"):
        r = api_get(client, name, saved.pk)
        assert r.status_code == 401 and r.json()["detail"] == "Please sign in.", name
    assert ask(client, QUESTION).status_code == 401
    assert fake_ask == []  # a stranger never reaches the AI


def test_another_user_cannot_open_my_answer_or_excel(client, user, other, mysql):
    saved = saved_question(user)
    client.force_login(other)

    assert api_get(client, "api_question", saved.pk).status_code == 404
    assert api_get(client, "api_excel", saved.pk).status_code == 404
    assert mysql == []  # nothing was run for them


def test_staff_can_open_anyones_answer_and_excel(client, user, staff, mysql):
    saved = saved_question(user)
    client.force_login(staff)

    assert api_get(client, "api_question", saved.pk).status_code == 200
    assert api_get(client, "api_excel", saved.pk).status_code == 200


# ---------- Excel download ----------

def test_owner_downloads_an_excel_file_with_result_and_question_sheets(client, user, mysql):
    saved = saved_question(user)
    client.force_login(user)

    r = api_get(client, "api_excel", saved.pk)

    assert r.status_code == 200
    assert r["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert f'filename="ask_nop_{saved.pk}.xlsx"' in r["Content-Disposition"]
    book = load_workbook(io.BytesIO(r.content))  # openpyxl can open it
    assert book.sheetnames == ["Result", "Question"]
    result_rows = list(book["Result"].iter_rows(values_only=True))
    assert result_rows == [("customer_name", "invoice_value_inr"),
                           ("Aurora Fluid Power Limited", 1730000),
                           ("Meridian Hydraulics Limited", 747750)]
    info = {row[0]: row[1] for row in book["Question"].iter_rows(values_only=True)}
    assert info["Question"] == QUESTION
    assert info["Answer"] == ANSWER
    assert info["Asked by"] == "asha"
    assert info["Rows"] == 2


def test_no_excel_for_a_question_without_rows(client, user, mysql):
    saved = saved_question(user, status="refused", sql="", answer=agent.REFUSAL_ANSWER)
    client.force_login(user)

    r = api_get(client, "api_excel", saved.pk)

    assert r.status_code == 404 and r["Content-Type"] == "application/json"


def test_excel_when_mysql_cannot_run_the_sql_says_why(client, user, monkeypatch):
    def down(sql):
        raise warehouse.WarehouseUnavailable("MySQL is not running")
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: TABLES)
    monkeypatch.setattr(warehouse, "run_select", down)
    saved = saved_question(user)
    client.force_login(user)

    r = api_get(client, "api_excel", saved.pk)

    assert r.status_code == 503
    assert r.json()["detail"] == "The Excel file could not be made: MySQL is not running"


# ---------- History ----------

def test_history_shows_only_my_questions_25_per_page(client, user, other):
    start = timezone.now() - datetime.timedelta(days=1)
    for n in range(1, 31):  # 30 questions, one minute apart: number 30 is the newest
        q = saved_question(user, text=f"My question {n:02d}")
        Question.objects.filter(pk=q.pk).update(created_at=start + datetime.timedelta(minutes=n))
    saved_question(other, text="Ravi's private question")
    client.force_login(user)

    page1, page2 = history(client), history(client, 2)

    texts1 = [q["text"] for q in page1["questions"]]
    texts2 = [q["text"] for q in page2["questions"]]
    assert len(texts1) == 25 and len(texts2) == 5
    assert texts1[0] == "My question 30" and texts1[-1] == "My question 06"   # newest first
    assert texts2 == [f"My question {n:02d}" for n in range(5, 0, -1)]
    assert (page2["page"], page2["pages"], page2["count"]) == (2, 2, 30)
    assert page1["has_next"] and not page1["has_previous"] and page2["has_previous"] and not page2["has_next"]
    assert "Ravi" not in json.dumps(page1) + json.dumps(page2)               # never someone else's


def test_staff_also_see_only_their_own_questions_in_history(client, user, staff):
    saved_question(user, text="Asha's question")
    saved_question(staff, text="The boss's question")
    client.force_login(staff)

    assert [q["text"] for q in history(client)["questions"]] == ["The boss's question"]


def test_a_history_line_has_the_columns_of_the_page(client, user):
    saved = saved_question(user, secs=12.345, understood_as="Top 5 customers in Aug 2026",
                           answer="A" * 200, total_tokens=4_517)
    client.force_login(user)

    line = history(client)["questions"][0]

    assert line["id"] == saved.pk and line["created_text"]
    assert line["answer"] == "A" * 139 + "…"                                  # cut at 140 characters
    assert line["rows_count"] == 2 and line["secs_text"] == "12.3" and line["tokens_text"] == "4,517"
    assert line["status"] == "ok" and line["edited"] is False
    assert line["understood_as"] == "Top 5 customers in Aug 2026"
    assert "sql" not in line and "error" not in line


# ---------- Groq tokens ----------

MAIN, BACKUP = "openai/gpt-oss-120b", "qwen/qwen3.8-27b"


def test_a_saved_answer_has_no_permanent_token_line(client, user, mysql):
    """The tokens show once, right after asking (test_chat.py), and in History - not on re-opened answers."""
    saved = saved_question(user, model=MAIN, sql_tokens=3717, answer_tokens=800, total_tokens=4517)
    client.force_login(user)

    r = api_get(client, "api_question", saved.pk)

    assert r.json()["card"]["token_notice"] == ""
    assert "4,517" not in r.content.decode()


def test_old_question_without_tokens_shows_no_token_line(client, user, mysql):
    saved = saved_question(user, model=MAIN)  # saved before tokens were counted
    client.force_login(user)

    card = api_get(client, "api_question", saved.pk).json()["card"]

    assert card["answer"] == ANSWER and card["token_notice"] == ""
    assert history(client)["questions"][0]["tokens_text"] == "-"


def test_a_saved_answer_has_the_time_of_each_step(client, user, mysql):
    saved = saved_question(user, secs=58.4, tries=2, step_secs={
        "embed": 0.05, "search": 0.02, "sql_ai": 6.5, "mysql": 0.8, "answer_ai": 3.1, "wait": 45.0, "other": 2.93})
    old = saved_question(user)                                       # saved before the steps were timed
    client.force_login(user)

    card = api_get(client, "api_question", saved.pk).json()["card"]
    old_card = api_get(client, "api_question", old.pk).json()["card"]

    steps = {s["label"]: s for s in card["time_steps"]}
    assert card["secs"] == 58.4
    assert steps["Wait for Groq's per-minute limit"]["secs"] == 45.0
    assert steps["Write the SQL (AI)"]["note"] == "2 tries"
    assert steps["Embed the question (text to numbers)"]["secs"] == 0.05
    assert old_card["time_steps"] == []


def test_history_has_a_tokens_column(client, user):
    saved_question(user, model=MAIN, sql_tokens=3717, answer_tokens=800, total_tokens=4517)
    client.force_login(user)

    assert history(client)["questions"][0]["tokens_text"] == "4,517"


def test_history_has_the_ai_usage_box_for_all_users(client, user, other, monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", MAIN)
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", BACKUP)
    monkeypatch.delenv("GROQ_DAILY_TOKEN_LIMIT", raising=False)
    saved_question(user, model=MAIN, total_tokens=10_000)
    saved_question(other, model=MAIN, total_tokens=8_240)                 # another user counts too
    old = saved_question(user, model=MAIN, total_tokens=50_000)           # an earlier, ended period
    Question.objects.filter(pk=old.pk).update(created_at=timezone.now() - datetime.timedelta(hours=25))
    saved_question(user, model=MAIN)                                      # no tokens saved: 0
    client.force_login(user)

    body = history(client)

    usage = body["usage"]
    main, backup = usage["rows"]
    assert usage["period_start"] and usage["period_end"]                  # "Daily period since ..."
    assert (main["model"], main["tokens"], main["limit"], main["pct"]) == (MAIN, "18,240", "200,000", 9)
    assert (backup["model"], backup["tokens"], backup["pct"]) == (BACKUP, "0", 0)   # backup model, unused
    assert main["rolling"] == "18,240"                                    # Groq's real count, last 24 h
    assert usage["week_start"] and usage["week_end"]                      # "This week (since ..."
    assert len(body["questions"]) == 3                                    # the rows are still only mine


def test_ai_usage_lists_other_models_and_uses_the_limit_setting(user, monkeypatch):
    from portal.usage import ai_usage
    monkeypatch.setenv("GROQ_MODEL", MAIN)
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", "")
    monkeypatch.setenv("GROQ_DAILY_TOKEN_LIMIT", "100000")
    saved_question(user, model="openai/gpt-oss-20b", total_tokens=25_000)  # e.g. an older main model

    rows = ai_usage()["rows"]

    # questions left = (limit - used) // average tokens per question in the last 24 h (25,000 here)
    assert [(r["model"], r["tokens"], r["limit"], r["pct"], r["questions_left"]) for r in rows] == [
        (MAIN, "0", "100,000", 0, 4), ("openai/gpt-oss-20b", "25,000", "100,000", 25, 3)]


# ---------- the usage box is on History only ----------

@pytest.fixture
def two_models(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", MAIN)
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", BACKUP)
    monkeypatch.delenv("GROQ_DAILY_TOKEN_LIMIT", raising=False)


def test_the_ask_screens_do_not_get_the_usage_box(client, user, mysql, two_models):
    """The usage box is on History only; asking gives a one-time notice instead."""
    saved = saved_question(user, model=MAIN, sql_tokens=3_500, answer_tokens=1_000, total_tokens=4_500)
    client.force_login(user)

    for r in (api_get(client, "api_chats"), api_get(client, "api_question", saved.pk), api_get(client, "api_me")):
        assert "usage" not in r.json() and "questions_left" not in r.content.decode()


def test_questions_left_uses_4500_tokens_per_question_until_there_is_data(user, two_models):
    from portal.usage import ai_usage
    saved_question(user, model=MAIN)                                      # no tokens saved: ignored

    main = ai_usage()["rows"][0]

    assert main["model"] == MAIN and main["tokens"] == "0"
    assert main["questions_left"] == 44                                   # 200,000 // 4,500


def test_questions_left_is_never_negative(user, two_models):
    from portal.usage import ai_usage
    saved_question(user, model=MAIN, total_tokens=250_000)                # over the daily limit

    main = ai_usage()["rows"][0]

    assert main["model"] == MAIN and main["pct"] == 125
    assert main["questions_left"] == 0


def test_history_box_has_questions_left_and_the_reset_time(client, user, two_models):
    saved_question(user, model=MAIN, total_tokens=4_000)
    client.force_login(user)

    usage = history(client)["usage"]

    assert usage["rows"][0]["questions_left"] == 49                       # (200,000 - 4,000) // 4,000
    assert usage["period_end"]                                            # "- resets <time>"


def test_history_ask_again_asks_the_same_question_in_a_new_chat(client, user, fake_ask, mysql):
    saved = saved_question(user, text="Open sales orders?")
    client.force_login(user)

    line = history(client)["questions"][0]
    r = api_post(client, "api_again", None, saved.pk)

    assert line["ask_again"] == "Open sales orders?"
    assert line["excel_url"] == reverse("api_excel", args=[saved.pk])
    assert r.status_code == 200 and fake_ask == ["Open sales orders?"] and fake_ask.contexts == [[]]
    new_chat = Conversation.objects.get()
    assert r.json()["chat"]["id"] == new_chat.pk and new_chat.title == "Open sales orders?"


def test_ask_again_is_only_for_my_own_questions(client, user, other, fake_ask):
    saved = saved_question(user)

    assert api_post(client, "api_again", None, saved.pk).status_code == 401
    client.force_login(other)
    assert api_post(client, "api_again", None, saved.pk).status_code == 404
    assert api_get(client, "api_again", saved.pk).status_code == 405
    assert fake_ask == []


# ---------- step H: answers from the company documents ----------

DOC_SOURCES = [{"heading": "Warranty and Returns Policy, page 1", "kind": "pdf"},
               {"heading": "Product Catalogue, page 2", "kind": "pdf"}]


def docs_question(user, **fields):
    """A question answered from the PDFs, as agent.ask() saves it: no SQL, no rows, the pages as sources."""
    return saved_question(user, **{"text": "How long is the warranty on hydraulic motors?", "sql": "",
                                   "answer": "Hydraulic motors have a warranty of 24 months.", "rows_count": None,
                                   "status": "docs", "sources": DOC_SOURCES, "tries": 0, **fields})


def test_a_documents_answer_has_its_status_and_pages_with_no_sql_or_excel(client, user, mysql):
    saved = docs_question(user)
    client.force_login(user)

    card = api_get(client, "api_question", saved.pk).json()["card"]

    assert card["status"] == "docs"                                          # FROM DOCUMENTS
    assert card["answer"] == "Hydraulic motors have a warranty of 24 months."
    assert card["sources"] == DOC_SOURCES                                    # the PDF pages, in order
    assert card["sql"] == "" and card["excel_url"] == "" and card["has_rows"] is False
    assert mysql == []                                                       # nothing ran


def test_a_documents_answer_in_a_chat_has_the_pages(client, user, mysql):
    chat = Conversation.objects.create(user=user, title="Warranty")
    docs_question(user, conversation=chat)
    client.force_login(user)

    card = api_get(client, "api_chat", chat.pk).json()["cards"][0]

    assert card["status"] == "docs" and card["sources"][0] == {"kind": "pdf", "heading": "Warranty and Returns Policy, page 1"}
    assert card["sql"] == "" and card["excel_url"] == "" and mysql == []


def test_excel_for_a_documents_answer_is_not_found(client, user, mysql):
    saved = docs_question(user)
    client.force_login(user)

    assert api_get(client, "api_excel", saved.pk).status_code == 404
    assert mysql == []


def test_history_has_a_documents_answer_without_an_excel_link(client, user):
    docs_question(user)
    client.force_login(user)

    line = history(client)["questions"][0]

    assert line["status"] == "docs" and line["excel_url"] == ""


def test_the_token_notice_of_a_documents_answer_names_the_route_call(user):
    saved = docs_question(user, model=MAIN, sql_tokens=300, answer_tokens=900, total_tokens=1200)
    assert services.token_notice(saved) == f"This question used 1,200 tokens (route 300 + answer 900) - {MAIN}"
