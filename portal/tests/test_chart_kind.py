"""The chart the question asked for, as the SQL call names it: "CHART: <kind>" (portal/rag/agent.py: chart_kind_line,
SQL_SYSTEM_PROMPT; portal/lc/graph.py: write_sql, keep_first_answer).

17-Nov: "can you create plot bar chat last 6 months sales" (typo: "chat") got a LINE chart - the Ask page picked the
chart from fixed words. Now the SQL call that runs anyway may write one line "CHART: bar" next to the SQL (no extra AI
call); our code turns it into the page's chart key, saves it on the Question (chart_kind) and sends it in the card.

The AI is the fake one of test_agent.py (FakeAI behind LangChain); MySQL and the notes search are faked.
Run with:  python -m pytest -q portal/tests/test_chart_kind.py
"""
import json

import pytest
from django.urls import reverse

from portal import mcp_server, services
from portal.lc.memory import ChatHistory
from portal.models import Conversation, Question
from portal.rag import agent
from portal.tests.test_agent import mysql, use_fake_ai  # noqa: F401
from portal.tests.test_answer_check import BAR_ROWS, BAR_SQL, bar_chat, no_ai
from portal.tests.test_chat import make_chat
from portal.tests.test_graph import TREND_ANSWER, TREND_ROWS, TREND_SQL, steps  # noqa: F401
from portal.tests.test_one_row_chart import ONE_MONTH_SQL, ONE_ROW, ONE_ROW_ANSWER
from portal.tests.test_stream import fake_ai as streaming_ai
from portal.tests.test_stream import signed_in, stream  # noqa: F401
from portal.tests.test_views_ask import QUESTION

pytestmark = pytest.mark.django_db

TYPO_QUESTION = "can you create plot bar chat last 6 months sales"
BAR_REPLY = "CHART: bar\n" + TREND_SQL
KEYS = {"bar", "column", "hbar", "line", "area", "stackedArea", "stacked", "grouped", "pie", "scatter", "heatmap", "treemap",
        "waterfall", "funnel", "radar"}  # the Ask page's chart keys (frontend/src/charts: the contract)


# ---------- the words of the CHART line ----------

@pytest.mark.parametrize("line, key", [
    ("CHART: bar", "bar"), ("chart: Bar", "bar"), ("CHART: bar chart", "bar"), ("CHART: columns", "column"),
    ("CHART: column", "column"), ("CHART: column graph", "column"), ("CHART: vertical bar", "column"),
    ("CHART: upright bars", "column"),
    ("CHART: horizontal bar", "hbar"), ("CHART: Horizontal Bar", "hbar"), ("CHART: horizontal-bar chart", "hbar"),
    ("CHART: line", "line"), ("CHART: line graph", "line"), ("CHART: area", "area"),
    ("CHART: stacked area", "stackedArea"), ("CHART: Stacked-Area", "stackedArea"),
    ("CHART: stacked bar", "stacked"), ("CHART: stacked-bar", "stacked"), ("CHART: grouped bar", "grouped"),
    ("CHART: pie", "pie"), ("CHART: donut", "pie"), ("CHART: doughnut chart", "pie"),
    ("CHART: scatter", "scatter"), ("CHART: heatmap", "heatmap"), ("CHART: heat map", "heatmap"),
    ("CHART: treemap", "treemap"), ("CHART: waterfall", "waterfall"), ("CHART: funnel", "funnel"),
    ("CHART: radar", "radar"), ("**CHART:** bar", "bar"), ("CHART: bar - net sales of the last 6 months", "bar"),
    ("CHART: pie (sales by state)", "pie"),
])
def test_the_ai_words_become_the_chart_keys_of_the_page(line, key):
    assert agent.chart_kind_line(f"{line}\n{TREND_SQL}") == key
    assert key in KEYS


@pytest.mark.parametrize("reply", [
    "CHART: none", "CHART: None.", "CHART: n/a", "CHART: sankey", "CHART: gauge", "CHART: banana", "CHART:", "",
    None, TREND_SQL, "MISSING: profit - not in the data\n" + TREND_SQL,
])
def test_no_chart_none_or_unknown_words_are_empty(reply):
    assert agent.chart_kind_line(reply) == ""


def test_the_chart_line_never_ends_up_in_the_sql():
    kind, sql = agent.read_sql_reply("CHART: bar\nMISSING: profit - not in the data\n" + TREND_SQL)

    assert kind == "sql" and "CHART" not in sql and "MISSING" not in sql
    assert sql.startswith("SELECT c.sales_month")
    # also when the model puts it inside the code block
    kind, sql = agent.read_sql_reply("```sql\nCHART: pie\n" + TREND_SQL.split("```sql\n", 1)[1])
    assert kind == "sql" and "CHART" not in sql and sql.startswith("SELECT")


def test_a_chart_line_with_no_data_or_no_sql_is_still_read_as_that():
    assert agent.read_sql_reply("CHART: bar\nNO_DATA: profit is not in the SS Manufacturing data")[0] == "no_data"
    assert agent.read_sql_reply("CHART: bar\nNO_SQL")[0] == "no_sql"


def test_the_prompt_asks_for_the_chart_line_but_the_mcp_rules_do_not():
    prompt = agent.SQL_SYSTEM_PROMPT
    assert 'write first one line "CHART: <kind>"' in prompt
    assert '"bar chat", "barchrt", "show as columns", "pie"' in prompt
    assert ("bar, column (upright bars), horizontal bar, line, area, stacked area, stacked bar, grouped bar, pie, scatter, heatmap, treemap, "
            "waterfall, funnel, radar") in prompt
    assert "CHART" in agent.RETRY_PROMPT
    assert "CHART" not in mcp_server.SQL_RULES  # the MCP caller's LLM gets the SQL rules only, as before


# ---------- kept on the result and saved ----------

def test_the_17_nov_typo_question_gets_a_bar_chart(monkeypatch, mysql, user, steps):
    mysql.results = [TREND_ROWS]
    fake = use_fake_ai(monkeypatch, [BAR_REPLY, TREND_ANSWER])

    result = agent.ask(TYPO_QUESTION, user)

    assert result.status == "ok" and result.chart_kind == "bar"
    assert "CHART" not in result.sql and "CHART" not in mysql.calls[0]
    assert len(fake.calls) == 2                                              # no extra AI call
    assert Question.objects.get().chart_kind == "bar"


def test_no_chart_line_is_empty(monkeypatch, mysql, user, steps):
    mysql.results = [TREND_ROWS]
    use_fake_ai(monkeypatch, [TREND_SQL, TREND_ANSWER])

    result = agent.ask("net sales of the last 6 sales months", user)

    assert result.status == "ok" and result.chart_kind == ""
    assert Question.objects.get().chart_kind == ""


def test_a_question_without_rows_saves_no_chart(monkeypatch, mysql, user, steps):
    use_fake_ai(monkeypatch, ["CHART: bar\nNO_DATA: profit is not in the SS Manufacturing data"])

    result = agent.ask("profit by month as a bar chart", user)

    assert result.status == "nodata" and result.chart_kind == ""
    assert Question.objects.get().chart_kind == ""


def test_a_retry_without_a_chart_line_keeps_the_chart_of_the_first_try(monkeypatch, mysql, user, steps):
    mysql.results = [ONE_ROW, TREND_ROWS]
    use_fake_ai(monkeypatch, ["CHART: bar\n" + ONE_MONTH_SQL, TREND_SQL, TREND_ANSWER])

    result = agent.ask(TYPO_QUESTION, user)

    assert result.tries == 2 and len(result.rows) == 6 and result.chart_kind == "bar"


def test_a_retry_with_its_own_chart_line_wins(monkeypatch, mysql, user, steps):
    mysql.results = [ONE_ROW, TREND_ROWS]
    use_fake_ai(monkeypatch, ["CHART: line\n" + ONE_MONTH_SQL, BAR_REPLY, TREND_ANSWER])

    result = agent.ask(TYPO_QUESTION, user)

    assert result.tries == 2 and result.chart_kind == "bar"
    assert Question.objects.get().chart_kind == "bar"


def test_a_kept_first_answer_keeps_the_chart_of_its_own_try(monkeypatch, mysql, user, steps):
    """The 1-row retry gives 1 row again: the FIRST rows are used, so the FIRST try's chart too."""
    mysql.results = [ONE_ROW, ONE_ROW]
    use_fake_ai(monkeypatch, ["CHART: bar\n" + ONE_MONTH_SQL, "CHART: pie\n" + ONE_MONTH_SQL, ONE_ROW_ANSWER])

    result = agent.ask("Net sales of Oct 2026 as a line chart", user)

    assert "keep_first_answer" in steps
    assert result.rows == ONE_ROW["rows"] and result.chart_kind == "bar"


# ---------- sent in the answer card ----------

def test_the_card_has_the_chart_kind(client, user, mysql):
    chat = make_chat(user, QUESTION, chart_kind="hbar")
    client.force_login(user)

    card = client.get(reverse("api_chat", args=[chat.pk])).json()["cards"][0]
    assert card["chart_kind"] == "hbar"
    saved = client.get(reverse("api_question", args=[card["id"]])).json()["card"]   # the saved answer /q/<id>
    assert saved["chart_kind"] == "hbar"


def test_an_old_question_or_a_documents_answer_has_an_empty_chart_kind(client, user, mysql):
    old = make_chat(user, QUESTION)                                            # saved before 17-Nov
    docs = make_chat(user, "What does the quality manual say?", status="docs", sql="", rows_count=None,
                     chart_kind="bar")
    client.force_login(user)

    assert client.get(reverse("api_chat", args=[old.pk])).json()["cards"][0]["chart_kind"] == ""
    assert client.get(reverse("api_chat", args=[docs.pk])).json()["cards"][0]["chart_kind"] == ""


def test_api_ask_sends_the_chart_kind(monkeypatch, mysql, user, client):
    mysql.results = [TREND_ROWS]
    use_fake_ai(monkeypatch, [BAR_REPLY, TREND_ANSWER])
    client.force_login(user)

    r = client.post(reverse("api_ask"), data=json.dumps({"question": TYPO_QUESTION, "chat_id": None}),
                    content_type="application/json")

    assert r.status_code == 200 and r.json()["card"]["chart_kind"] == "bar"


def test_the_streamed_done_card_sends_the_chart_kind(monkeypatch, mysql, signed_in):
    mysql.results = [TREND_ROWS]
    streaming_ai(monkeypatch, [BAR_REPLY, TREND_ANSWER])

    r, events = stream(signed_in, question=TYPO_QUESTION)

    assert events[-1]["type"] == "done" and events[-1]["card"]["chart_kind"] == "bar"


# ---------- the answer check draws the same chart again ----------

def test_the_answer_check_copies_the_chart_kind(monkeypatch, mysql, user):
    chat = bar_chat(user)
    Question.objects.filter(conversation=chat).update(chart_kind="bar")
    mysql.results = [BAR_ROWS]
    no_ai(monkeypatch)

    saved, _ = services.answer_in_chat(user, chat, "is that correct")

    assert saved.status == "ok" and saved.sql == BAR_SQL and saved.chart_kind == "bar"


def test_the_answer_check_of_an_old_question_has_no_chart_kind(monkeypatch, mysql, user):
    mysql.results = [BAR_ROWS]
    no_ai(monkeypatch)

    result = agent.ask("is that correct?", user, context=ChatHistory.for_chat(bar_chat(user)))

    assert result.status == "ok" and result.chart_kind == ""
    assert Conversation.objects.count() == 1
