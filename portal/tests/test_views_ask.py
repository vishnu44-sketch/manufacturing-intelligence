"""Page checks for Ask NOP, the result page, the Excel download and History.

agent.ask() is replaced by a fake (no AI), and MySQL by a fake run_select (no database).
Asking works Post/Redirect/Get: POST /ask/ answers and saves the question in a NEW chat, then
sends the browser to that chat at /ask/c/<chat>/#q-<id>, which only SHOWS saved answers - a refresh
never asks the AI again. /ask/<id>/ shows one saved answer on its own. The chats: test_chat.py.
Run with:  python -m pytest -q portal/tests/test_views_ask.py
"""
import datetime
import io
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

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


# ---------- asking: Post/Redirect/Get ----------

def test_ask_saves_the_question_and_redirects_to_it_in_the_chat(client, user, fake_ask, mysql):
    client.force_login(user)

    r = client.post(reverse("ask"), {"question": QUESTION})

    saved = Question.objects.get()
    chat = Conversation.objects.get()                            # a new chat, titled by the question
    assert r.status_code == 302
    assert r.url == f"{reverse('ask_chat', args=[chat.pk])}#q-{saved.pk}"
    assert saved.conversation == chat and chat.title == QUESTION
    assert fake_ask == [QUESTION]


def test_after_asking_the_chat_shows_answer_table_sql_and_sources(client, user, fake_ask, mysql):
    client.force_login(user)

    r = client.post(reverse("ask"), {"question": QUESTION}, follow=True)

    assert r.status_code == 200
    page = r.content.decode()
    saved = Question.objects.get()
    assert f'id="q-{saved.pk}"' in page                          # the redirect target is in the page
    assert "ANSWERED" in page
    assert ANSWER in page                                        # the answer
    assert "Aurora Fluid Power Limited" in page and "1,730,000.00" in page  # the rows table
    assert "Show SQL" in page and "FROM fact_invoice_lines" in page         # the SQL (folded)
    assert "Sources used (2)" in page and "NOP sales month" in page         # the sources (folded)
    assert "2 rows" in page
    assert reverse("ask_excel", args=[saved.pk]) in page          # Download Excel
    assert "></textarea>" in page                                 # the question box is empty again
    assert 'href="/ask/" class="active"' in page                  # "Ask NOP" stays lit in the menu


def test_result_page_shows_answer_table_sql_and_sources(client, user, mysql):
    saved = saved_question(user)
    client.force_login(user)

    r = client.get(reverse("ask_result", args=[saved.pk]))

    assert r.status_code == 200
    page = r.content.decode()
    assert "ANSWERED" in page
    assert ANSWER in page                                        # the answer
    assert "Aurora Fluid Power Limited" in page and "1,730,000.00" in page  # the rows table
    assert "Show SQL" in page and "FROM fact_invoice_lines" in page         # the SQL
    assert "Sources used" in page and "NOP sales month" in page             # the sources
    assert "2 rows" in page
    assert reverse("ask_excel", args=[saved.pk]) in page          # Download Excel
    assert f">{QUESTION}</textarea>" in page                     # question box filled in again
    assert 'href="/ask/" class="active"' in page                  # "Ask NOP" stays lit in the menu


def test_result_page_says_when_the_backup_model_answered(client, user, mysql, monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    by_backup = saved_question(user, model="qwen/qwen3.8-27b")
    by_main = saved_question(user, model="openai/gpt-oss-120b")
    client.force_login(user)

    backup_page = client.get(reverse("ask_result", args=[by_backup.pk])).content.decode()
    main_page = client.get(reverse("ask_result", args=[by_main.pk])).content.decode()
    history = client.get(reverse("history")).content.decode()

    note = "Answered by the backup model (qwen/qwen3.8-27b) - the main model's daily limit was reached."
    assert note in backup_page
    assert "Answered by the backup model" not in main_page
    assert history.count("backup model</div>") == 1


def test_refreshing_the_chat_does_not_ask_the_ai_again(client, user, fake_ask, mysql):
    """The chat re-runs the newest saved SQL (guard + read-only MySQL) but never calls the AI."""
    client.force_login(user)
    chat_url = client.post(reverse("ask"), {"question": QUESTION}).url

    client.get(chat_url)
    client.get(chat_url)  # the browser refresh

    assert fake_ask == [QUESTION]   # the AI was asked once
    assert len(mysql) == 2          # the rows were loaded once per page view
    assert mysql[0].rstrip().endswith("LIMIT 5")


@pytest.mark.parametrize("question, message", [
    ("   ", "Type a question first."),
    ("x" * 1001, "Please keep the question under 1000 characters."),
])
def test_empty_or_too_long_question_is_not_sent_to_the_ai(client, user, fake_ask, question, message):
    client.force_login(user)

    r = client.post(reverse("ask"), {"question": question})

    assert r.status_code == 200
    assert message in r.content.decode()
    assert fake_ask == []
    assert not Question.objects.exists() and not Conversation.objects.exists()


def test_refused_question_shows_no_sql_and_runs_nothing(client, user, mysql):
    saved = saved_question(user, text="What is the capital of France?", status="refused",
                           sql="", answer=agent.REFUSAL_ANSWER, rows_count=None, sources=[])
    client.force_login(user)

    r = client.get(reverse("ask_result", args=[saved.pk]))

    page = r.content.decode()
    assert "NOT A NOP DATA QUESTION" in page
    assert agent.REFUSAL_ANSWER in page
    assert "Show SQL" not in page and "Download Excel" not in page
    assert mysql == []


def test_result_page_still_shows_the_answer_when_the_rows_cannot_be_loaded(client, user, monkeypatch):
    def mysql_refuses(sql):
        raise warehouse.QueryError("(1146) Table 'ai_gold.dim_customers' doesn't exist")
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: TABLES)
    monkeypatch.setattr(warehouse, "run_select", mysql_refuses)
    saved = saved_question(user)
    client.force_login(user)

    r = client.get(reverse("ask_result", args=[saved.pk]))

    page = r.content.decode()
    assert r.status_code == 200
    assert ANSWER in page
    assert "The rows could not be loaded again" in page
    assert "returned no rows" not in page


# ---------- who may see what ----------

def test_ask_pages_need_a_login(client, user, fake_ask):
    saved = saved_question(user)
    for url in [reverse("ask"), reverse("ask_result", args=[saved.pk]),
                reverse("ask_excel", args=[saved.pk])]:
        r = client.get(url)
        assert r.status_code == 302 and r.url.startswith(reverse("login")), url
    r = client.post(reverse("ask"), {"question": QUESTION})
    assert r.status_code == 302 and r.url.startswith(reverse("login"))
    assert fake_ask == []  # a stranger never reaches the AI


def test_another_user_cannot_open_my_result_or_excel(client, user, other, mysql):
    saved = saved_question(user)
    client.force_login(other)

    assert client.get(reverse("ask_result", args=[saved.pk])).status_code == 404
    assert client.get(reverse("ask_excel", args=[saved.pk])).status_code == 404
    assert mysql == []  # nothing was run for them


def test_staff_can_open_anyones_result_and_excel(client, user, staff, mysql):
    saved = saved_question(user)
    client.force_login(staff)

    assert client.get(reverse("ask_result", args=[saved.pk])).status_code == 200
    assert client.get(reverse("ask_excel", args=[saved.pk])).status_code == 200


# ---------- Excel download ----------

def test_owner_downloads_an_excel_file_with_result_and_question_sheets(client, user, mysql):
    saved = saved_question(user)
    client.force_login(user)

    r = client.get(reverse("ask_excel", args=[saved.pk]))

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

    assert client.get(reverse("ask_excel", args=[saved.pk])).status_code == 404


# ---------- History ----------

def test_history_shows_only_my_questions_25_per_page(client, user, other):
    start = timezone.now() - datetime.timedelta(days=1)
    for n in range(1, 31):  # 30 questions, one minute apart: number 30 is the newest
        q = saved_question(user, text=f"My question {n:02d}")
        Question.objects.filter(pk=q.pk).update(created_at=start + datetime.timedelta(minutes=n))
    saved_question(other, text="Ravi's private question")
    client.force_login(user)

    page1 = client.get(reverse("history")).content.decode()
    page2 = client.get(reverse("history") + "?page=2").content.decode()

    assert page1.count("Ask again") == 25
    assert page2.count("Ask again") == 5
    assert "My question 30" in page1 and "My question 06" in page1   # newest first
    assert "My question 05" in page2 and "My question 01" in page2
    assert "My question 05" not in page1
    assert "Page 2 of 2" in page2 and "30 questions" in page2
    assert "Ravi" not in page1 + page2                             # never someone else's


# ---------- Groq tokens ----------

MAIN, BACKUP = "openai/gpt-oss-120b", "qwen/qwen3.8-27b"


def test_result_page_has_no_permanent_token_line(client, user, mysql):
    """The tokens show once, right after asking (test_chat.py), and in History - not on re-opened answers."""
    saved = saved_question(user, model=MAIN, sql_tokens=3717, answer_tokens=800, total_tokens=4517)
    client.force_login(user)

    page = client.get(reverse("ask_result", args=[saved.pk])).content.decode()

    assert ANSWER in page
    assert "Tokens used" not in page and "This question used" not in page
    assert "4,517" not in page


def test_old_question_without_tokens_shows_no_token_line(client, user, mysql):
    saved = saved_question(user, model=MAIN)  # saved before tokens were counted
    client.force_login(user)

    r = client.get(reverse("ask_result", args=[saved.pk]))
    history = client.get(reverse("history")).content.decode()

    assert r.status_code == 200 and ANSWER in r.content.decode()
    assert "Tokens used" not in r.content.decode()
    assert '<td class="num">-</td>' in history


def test_result_page_shows_the_time_of_each_step(client, user, mysql):
    saved = saved_question(user, secs=58.4, tries=2, step_secs={
        "embed": 0.05, "search": 0.02, "sql_ai": 6.5, "mysql": 0.8, "answer_ai": 3.1, "wait": 45.0, "other": 2.93})
    old = saved_question(user)                                       # saved before the steps were timed
    client.force_login(user)

    page = client.get(reverse("ask_result", args=[saved.pk])).content.decode()
    old_page = client.get(reverse("ask_result", args=[old.pk])).content.decode()

    assert "Time taken: 58.4 s" in page
    assert "Wait for Groq&#x27;s per-minute limit" in page and "45.0 s" in page
    assert "Write the SQL (AI) <span class=\"mut\">(2 tries)</span>" in page
    assert "Embed the question (text to numbers)" in page and "0.05 s" in page
    assert "Time taken" not in old_page


def test_history_has_a_tokens_column(client, user):
    saved_question(user, model=MAIN, sql_tokens=3717, answer_tokens=800, total_tokens=4517)
    client.force_login(user)

    page = client.get(reverse("history")).content.decode()

    assert '<th class="num">Tokens</th>' in page
    assert '<td class="num">4,517</td>' in page


def test_history_shows_the_ai_usage_box_for_all_users(client, user, other, monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", MAIN)
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", BACKUP)
    monkeypatch.delenv("GROQ_DAILY_TOKEN_LIMIT", raising=False)
    saved_question(user, model=MAIN, total_tokens=10_000)
    saved_question(other, model=MAIN, total_tokens=8_240)                 # another user counts too
    old = saved_question(user, model=MAIN, total_tokens=50_000)           # an earlier, ended period
    Question.objects.filter(pk=old.pk).update(created_at=timezone.now() - datetime.timedelta(hours=25))
    saved_question(user, model=MAIN)                                      # no tokens saved: 0
    client.force_login(user)

    page = client.get(reverse("history")).content.decode()

    assert "AI usage (this app)" in page
    assert "Daily period since " in page
    assert "18,240 of 200,000 tokens (9 %)" in page                        # main model, this period
    assert "0 of 200,000 tokens (0 %)" in page                             # backup model, unused
    assert page.index(MAIN) < page.index(BACKUP)
    assert "Groq's real count (rolling last 24 h, this app)" in page
    assert "This week (since " in page
    assert "Tests and other tools that use the same" in page
    assert page.count("Ask again") == 3                                    # the rows are still only mine


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


def test_ask_pages_do_not_show_the_usage_box(client, user, mysql, two_models):
    """The usage box is on History only; the Ask page shows a one-time notice instead."""
    saved = saved_question(user, model=MAIN, sql_tokens=3_500, answer_tokens=1_000, total_tokens=4_500)
    client.force_login(user)

    for url in (reverse("ask"), reverse("ask_new"), reverse("ask_result", args=[saved.pk])):
        page = client.get(url, follow=True).content.decode()
        assert "AI usage (this app)" not in page, url
        assert "questions left" not in page and "This week (since" not in page, url


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


def test_history_box_shows_questions_left_and_the_reset_time(client, user, two_models):
    saved_question(user, model=MAIN, total_tokens=4_000)
    client.force_login(user)

    page = client.get(reverse("history")).content.decode()

    assert "about 49 questions left - resets " in page                     # (200,000 - 4,000) // 4,000


def test_history_ask_again_sends_the_same_question_to_ask(client, user):
    saved_question(user, text="Open sales orders?")
    client.force_login(user)

    page = client.get(reverse("history")).content.decode()

    assert f'action="{reverse("ask")}"' in page
    assert 'name="question" value="Open sales orders?"' in page
    assert reverse("ask_excel", args=[Question.objects.get().pk]) in page
