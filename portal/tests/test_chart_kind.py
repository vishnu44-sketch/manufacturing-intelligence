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
    # 19-Nov: a kind the AI suggests itself (no chart asked) is the same key
    ("CHART: line (suggested)", "line"), ("CHART: bar (Suggested)", "bar"), ("CHART: suggested line", "line"),
])
def test_the_ai_words_become_the_chart_keys_of_the_page(line, key):
    assert agent.chart_kind_line(f"{line}\n{TREND_SQL}") == key
    assert key in KEYS


@pytest.mark.parametrize("reply", [
    "CHART: sankey", "CHART: gauge", "CHART: banana", "CHART:", "",
    None, TREND_SQL, "MISSING: profit - not in the data\n" + TREND_SQL,
])
def test_no_chart_line_or_unknown_words_are_empty(reply):
    assert agent.chart_kind_line(reply) == ""
    assert agent.chart_asked(reply) is False


# 19-Nov: "CHART: none" = the AI decided no chart makes the answer clearer - kept apart from '' (no line)
@pytest.mark.parametrize("line", [
    "CHART: none", "CHART: None.", "CHART: n/a", "CHART: no chart", "**CHART:** none", "CHART: none (one number)",
    "CHART: none - a list of invoices", "CHART: table",
])
def test_chart_none_is_none(line):
    assert agent.chart_kind_line(f"{line}\n{TREND_SQL}") == "none"
    assert agent.chart_asked(f"{line}\n{TREND_SQL}") is False


@pytest.mark.parametrize("line, asked", [
    ("CHART: bar", True), ("CHART: column graph", True), ("CHART: pie (sales by state)", True),
    ("CHART: line (suggested)", False), ("CHART: bar (Suggested)", False), ("CHART: suggested line", False),
    ("CHART: none", False),
])
def test_an_asked_chart_is_told_apart_from_a_suggested_one(line, asked):
    assert agent.chart_asked(f"{line}\n{TREND_SQL}") is asked


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
    assert 'write first one line "CHART: <kind>' in prompt
    # 19-Nov: always a CHART line - the AI decides whether a chart helps when none was asked
    assert 'With every SQL block, always write first one line "CHART: <kind>' in prompt
    assert '"CHART: <kind> (suggested)' in prompt and '"CHART: none"' in prompt
    assert "waterfall, funnel, radar, or none" in prompt
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


@pytest.mark.parametrize("line, saved", [("CHART: none", "none"), ("CHART: line (suggested)", "line")])
def test_the_ai_s_own_chart_choice_is_saved(monkeypatch, mysql, user, steps, line, saved):
    mysql.results = [TREND_ROWS]
    fake = use_fake_ai(monkeypatch, [f"{line}\n{TREND_SQL}", TREND_ANSWER])

    result = agent.ask("net sales of the last 6 sales months", user)

    assert result.status == "ok" and result.chart_kind == saved
    assert Question.objects.get().chart_kind == saved
    assert len(fake.calls) == 2                                              # no extra AI call


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

def test_the_card_sends_chart_none(client, user, mysql):
    chat = make_chat(user, QUESTION, chart_kind="none")
    client.force_login(user)

    card = client.get(reverse("api_chat", args=[chat.pk])).json()["cards"][0]
    assert card["chart_kind"] == "none"                                      # the page shows the table first


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


# ---------- 19-Nov: the columns to draw, named on the same CHART line ----------
# "Which products have the most stock right now?" drew the stock VALUE with long, alike descriptions as the bar names:
# the page chose the columns by fixed rules. Now the AI names them: "CHART: bar | value: stock_qty | label: product_code".

STOCK_LINE = "CHART: bar (suggested) | value: stock_qty | label: product_code"
STOCK_COLUMNS = {"value": "stock_qty", "label": "product_code"}


@pytest.mark.parametrize("line, kind, columns", [
    (STOCK_LINE, "bar", STOCK_COLUMNS),
    ("CHART: bar | value: stock_qty | label: product_code", "bar", STOCK_COLUMNS),
    ("chart: Grouped Bar | Value: net_sales_inr | LABEL: sales_month | series: customer_name", "grouped",
     {"value": "net_sales_inr", "label": "sales_month", "series": "customer_name"}),
    ("CHART: line|value:`net_sales_inr`|label:`sales_month`", "line", {"value": "net_sales_inr", "label": "sales_month"}),
    ("**CHART:** pie | value: **revenue_inr** | label: 'state_name'", "pie", {"value": "revenue_inr", "label": "state_name"}),
    ("CHART: bar | value: s.stock_qty | label: p.product_code", "bar", STOCK_COLUMNS),
    ("CHART: bar, value = stock_qty, label = product_code", "bar", STOCK_COLUMNS),
    ("CHART: bar value: stock_qty label: product_code", "bar", STOCK_COLUMNS),
    ("CHART: column | value: net_sales_inr", "column", {"value": "net_sales_inr"}),          # a part left out
    ("CHART: bar | label: product_code | series: none", "bar", {"label": "product_code"}),  # "none" is no column
    ("CHART: bar", "bar", {}),                                                              # an older reply
    ("CHART: none", "none", {}),
    ("CHART: banana | value: stock_qty | label: product_code", "", STOCK_COLUMNS),           # an unknown kind
    ("", "", {}),
])
def test_the_chart_line_names_the_columns(line, kind, columns):
    reply = f"{line}\n{TREND_SQL}"
    assert agent.chart_kind_line(reply) == kind
    assert agent.chart_columns_line(reply) == columns


def test_a_column_name_is_not_read_as_suggested_or_as_the_kind():
    assert agent.chart_asked(f"CHART: bar | value: suggested_qty | label: product_code\n{TREND_SQL}") is True
    assert agent.chart_asked(f"{STOCK_LINE}\n{TREND_SQL}") is False
    assert agent.chart_kind_line(f"CHART: line | value: pie_count\n{TREND_SQL}") == "line"


def test_the_column_line_is_not_sql():
    kind, sql = agent.read_sql_reply(f"{STOCK_LINE}\n{TREND_SQL}")
    assert kind == "sql" and "CHART" not in sql and "stock_qty |" not in sql


def test_the_prompt_asks_for_the_columns_to_draw():
    prompt = agent.SQL_SYSTEM_PROMPT
    assert '"CHART: <kind> | value: <column> | label: <column>"' in prompt
    assert '("most stock" -> stock quantity, not value)' in prompt
    assert "(codes when names are long and alike)" in prompt
    assert '"| series: <column>" only for a grouped / stacked / multi-line split' in prompt
    assert '"CHART: <kind> (suggested) | ..."' in prompt
    assert "pairs of items such as products bought together)" in prompt   # a table, "CHART: none"


def test_the_named_columns_are_saved(monkeypatch, mysql, user, steps):
    mysql.results = [TREND_ROWS]
    fake = use_fake_ai(monkeypatch, [f"{STOCK_LINE}\n{TREND_SQL}", TREND_ANSWER])

    result = agent.ask("net sales of the last 6 sales months", user)  # (the rows are faked: TREND_ROWS)

    assert result.status == "ok" and result.chart_kind == "bar" and result.chart_columns == STOCK_COLUMNS
    saved = Question.objects.get()
    assert saved.chart_kind == "bar" and saved.chart_columns == STOCK_COLUMNS
    assert len(fake.calls) == 2                                              # no extra AI call


def test_no_named_columns_save_nothing(monkeypatch, mysql, user, steps):
    mysql.results = [TREND_ROWS]
    use_fake_ai(monkeypatch, [BAR_REPLY, TREND_ANSWER])

    result = agent.ask(TYPO_QUESTION, user)

    assert result.chart_kind == "bar" and result.chart_columns == {}
    assert Question.objects.get().chart_columns is None


def test_a_question_without_rows_saves_no_columns(monkeypatch, mysql, user, steps):
    use_fake_ai(monkeypatch, ["CHART: bar | value: profit | label: month\nNO_DATA: profit is not in the data"])

    result = agent.ask("profit by month as a bar chart", user)

    assert result.status == "nodata" and result.chart_columns == {}
    assert Question.objects.get().chart_columns is None


def test_a_kept_first_answer_keeps_the_columns_of_its_own_try(monkeypatch, mysql, user, steps):
    mysql.results = [ONE_ROW, ONE_ROW]
    use_fake_ai(monkeypatch, ["CHART: bar | value: net_sales_inr | label: sales_month\n" + ONE_MONTH_SQL,
                              "CHART: pie | value: other_inr | label: other\n" + ONE_MONTH_SQL, ONE_ROW_ANSWER])

    result = agent.ask("Net sales of Oct 2026 as a line chart", user)

    assert "keep_first_answer" in steps
    assert result.chart_kind == "bar" and result.chart_columns == {"value": "net_sales_inr", "label": "sales_month"}


def test_the_card_has_the_named_columns(client, user, mysql):
    columns = {"value": "stock_qty", "label": "product_code", "series": "item_group"}
    chat = make_chat(user, QUESTION, chart_kind="bar", chart_columns=columns)
    client.force_login(user)

    card = client.get(reverse("api_chat", args=[chat.pk])).json()["cards"][0]
    assert card["chart_columns"] == columns and card["chart_kind"] == "bar"
    saved = client.get(reverse("api_question", args=[card["id"]])).json()["card"]
    assert saved["chart_columns"] == columns


@pytest.mark.parametrize("stored, sent", [
    (None, {}), ({}, {}), (["stock_qty"], {}),                                 # none, or not a dict
    ({"value": 5, "colour": "red", "label": "product_code"}, {"label": "product_code"}),  # only clean names
])
def test_the_card_sends_only_clean_column_names(client, user, mysql, stored, sent):
    chat = make_chat(user, QUESTION, chart_columns=stored)
    client.force_login(user)

    assert client.get(reverse("api_chat", args=[chat.pk])).json()["cards"][0]["chart_columns"] == sent


def test_a_documents_answer_sends_no_columns(client, user, mysql):
    docs = make_chat(user, "What does the quality manual say?", status="docs", sql="", rows_count=None,
                     chart_columns={"value": "stock_qty"})
    client.force_login(user)

    assert client.get(reverse("api_chat", args=[docs.pk])).json()["cards"][0]["chart_columns"] == {}


def test_api_ask_sends_the_named_columns(monkeypatch, mysql, user, client):
    mysql.results = [TREND_ROWS]
    use_fake_ai(monkeypatch, [f"{STOCK_LINE}\n{TREND_SQL}", TREND_ANSWER])
    client.force_login(user)

    r = client.post(reverse("api_ask"), data=json.dumps({"question": TYPO_QUESTION, "chat_id": None}),
                    content_type="application/json")

    assert r.status_code == 200 and r.json()["card"]["chart_columns"] == STOCK_COLUMNS


def test_the_streamed_done_card_sends_the_named_columns(monkeypatch, mysql, signed_in):
    mysql.results = [TREND_ROWS]
    streaming_ai(monkeypatch, [f"{STOCK_LINE}\n{TREND_SQL}", TREND_ANSWER])

    r, events = stream(signed_in, question=TYPO_QUESTION)

    assert events[-1]["type"] == "done" and events[-1]["card"]["chart_columns"] == STOCK_COLUMNS


def test_the_answer_check_copies_the_named_columns(monkeypatch, mysql, user):
    chat = bar_chat(user)
    Question.objects.filter(conversation=chat).update(chart_kind="bar",
                                                      chart_columns={"value": "net_sales_inr", "label": "customer"})
    mysql.results = [BAR_ROWS]
    no_ai(monkeypatch)

    saved, _ = services.answer_in_chat(user, chat, "is that correct")

    assert saved.status == "ok" and saved.chart_columns == {"value": "net_sales_inr", "label": "customer"}
