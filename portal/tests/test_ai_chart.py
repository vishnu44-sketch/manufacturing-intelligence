"""The AI chart: POST /api/questions/<id>/chart (api.question_chart, charts.py) - a chart the React app cannot
draw itself (a sankey, a gauge ...), made by the AI from an answer's rows.

The AI is a FAKE (test_agent.FakeAI, installed as portal.lc.llm.make_llm) and MySQL is a fake (test_views_ask's
mysql fixture) - no Groq call, no database outside the tests.
Checks: sign-in, CSRF, own question only, the rows run again like /rows, what the AI is sent, the JSON checks
(functions, unknown keys, HTML, web addresses, not JSON ...), the friendly errors and the token count.
Run with:  python -m pytest -q portal/tests/test_ai_chart.py
"""
import json
from decimal import Decimal

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from portal import charts
from portal.models import Question
from portal.rag import agent, warehouse
from portal.tests.test_agent import BACKUP, MAIN, CutOff, daily_limit_error, rate_limit_error, use_fake_ai
from portal.tests.test_views_ask import QUESTION, ROWS, TABLES, mysql, saved_question  # noqa: F401

pytestmark = pytest.mark.django_db

KIND = "sankey diagram"
SANKEY = {
    "tooltip": {"trigger": "item", "formatter": "{b}: {c}"},
    "series": [{"type": "sankey",
                "data": [{"name": "Aurora Fluid Power Limited"}, {"name": "Meridian Hydraulics Limited"}, {"name": "All"}],
                "links": [{"source": "Aurora Fluid Power Limited", "target": "All", "value": 1730000.0},
                          {"source": "Meridian Hydraulics Limited", "target": "All", "value": 747750.0}]}],
}


def chart(client, pk, data=None, **extra):
    """POST the chart request as the React app does (JSON)."""
    body = data if isinstance(data, str) else json.dumps({"kind": KIND} if data is None else data)
    return client.post(reverse("api_chart", args=[pk]), data=body, content_type="application/json", **extra)


@pytest.fixture
def main_model(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", MAIN)
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", BACKUP)


# ---------- the chart ----------

def test_the_ai_chart_is_made_from_the_rows_run_again(client, user, monkeypatch, mysql, main_model):
    saved = saved_question(user, model=MAIN, sql_tokens=3_000, answer_tokens=500, total_tokens=3_500)
    fake = use_fake_ai(monkeypatch, [(json.dumps(SANKEY), 1_200)])
    client.force_login(user)

    r = chart(client, saved.pk)

    assert r.status_code == 200, r.content
    body = r.json()
    assert body == {"option": SANKEY, "tokens": 1_200, "model": MAIN, "recorded": True}
    assert mysql == [saved.sql]                                   # the saved SQL ran again, like /rows
    assert fake.models == [MAIN] and fake.max_tokens == [charts.MAX_TOKENS]   # one call, the main model
    system, human = fake.calls[0]
    assert system["role"] == "system" and "ONLY one JSON object" in system["content"]
    assert "visualMap" in system["content"] and "sankey" in system["content"]
    assert f"Question: {QUESTION}" in human["content"]
    assert f"Chart wanted: {KIND}" in human["content"]
    assert "Columns: customer_name, invoice_value_inr" in human["content"]
    assert '["Aurora Fluid Power Limited", 1730000.0]' in human["content"]   # numbers as plain JSON numbers
    assert "Rows (all 2)" in human["content"]
    saved.refresh_from_db()
    assert saved.total_tokens == 4_700                            # the chart's tokens are counted
    assert saved.sql_tokens == 3_000 and saved.answer_tokens == 500


def test_tokens_of_a_question_answered_by_another_model_are_only_shown(client, user, monkeypatch, mysql, main_model):
    saved = saved_question(user, model=BACKUP, total_tokens=900)
    use_fake_ai(monkeypatch, [(json.dumps(SANKEY), 1_200)])
    client.force_login(user)

    body = chart(client, saved.pk).json()

    assert body["tokens"] == 1_200 and body["recorded"] is False
    saved.refresh_from_db()
    assert saved.total_tokens == 900                              # the usage box counts per model


def test_a_reply_in_code_fences_with_words_around_it_is_accepted(client, user, monkeypatch, mysql, main_model):
    saved = saved_question(user)
    use_fake_ai(monkeypatch, [f"Here is the chart:\n```json\n{json.dumps(SANKEY)}\n```"])
    client.force_login(user)

    r = chart(client, saved.pk)

    assert r.status_code == 200 and r.json()["option"] == SANKEY
    assert r.json()["tokens"] is None and r.json()["recorded"] is False


def test_the_ai_gets_at_most_50_rows(client, user, monkeypatch, main_model):
    rows = [[f"Customer {i}", Decimal(f"{1000 - i}.00")] for i in range(1, 61)]
    sent = []
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: TABLES)
    monkeypatch.setattr(warehouse, "run_select",
                        lambda sql: sent.append(sql) or {"columns": ROWS["columns"], "rows": rows, "truncated": False})
    saved = saved_question(user)
    fake = use_fake_ai(monkeypatch, [json.dumps(SANKEY)])
    client.force_login(user)

    assert chart(client, saved.pk).status_code == 200

    human = fake.calls[0][1]["content"]
    assert "Rows (the first 50 of 60)" in human
    assert '"Customer 50"' in human and '"Customer 51"' not in human
    assert sent == [saved.sql]


# ---------- who may ask ----------

def test_it_needs_a_sign_in(client, user, monkeypatch, mysql):
    saved = saved_question(user)
    fake = use_fake_ai(monkeypatch, [json.dumps(SANKEY)])

    r = chart(client, saved.pk)

    assert r.status_code == 401 and r.json()["detail"] == "Please sign in."
    assert fake.calls == [] and mysql == []


def test_it_needs_the_csrf_token(user, monkeypatch, mysql, main_model):
    saved = saved_question(user)
    fake = use_fake_ai(monkeypatch, [json.dumps(SANKEY)])
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)

    no_token = chart(client, saved.pk)
    assert no_token.status_code == 403 and "CSRF" in no_token.json()["detail"]
    assert fake.calls == [] and mysql == []

    token = client.get(reverse("api_csrf")).json()["csrfToken"]
    assert settings.CSRF_COOKIE_NAME in client.cookies
    ok = chart(client, saved.pk, HTTP_X_CSRFTOKEN=token)
    assert ok.status_code == 200 and len(fake.calls) == 1


def test_only_my_own_question_staff_any(client, user, other, staff, monkeypatch, mysql, main_model):
    saved = saved_question(user)
    fake = use_fake_ai(monkeypatch, [json.dumps(SANKEY)])

    client.force_login(other)
    r = chart(client, saved.pk)
    assert r.status_code == 404 and r.json() == {"detail": "Not found."}
    assert chart(client, 999_999).status_code == 404
    assert fake.calls == [] and mysql == []

    client.force_login(staff)                                     # as for /rows: staff may open any question
    assert chart(client, saved.pk).status_code == 200


def test_only_post(client, user, mysql):
    saved = saved_question(user)
    client.force_login(user)

    r = client.get(reverse("api_chart", args=[saved.pk]))

    assert r.status_code == 405 and r["Content-Type"] == "application/json"


def test_a_question_without_rows_has_no_chart(client, user, monkeypatch, mysql):
    refused = saved_question(user, status="refused", sql="")
    fake = use_fake_ai(monkeypatch, [json.dumps(SANKEY)])
    client.force_login(user)

    r = chart(client, refused.pk)

    assert r.status_code == 404 and r.json()["detail"] == charts.NOT_ANSWERED
    assert fake.calls == [] and mysql == []


@pytest.mark.parametrize("data, message", [
    ({"kind": ""}, "Say which chart to make."),
    ({}, "Say which chart to make."),
    ({"kind": "x" * 61}, "under 60 characters"),
    ({"kind": "<script>alert(1)</script>"}, "only have letters"),
    ("not json", "Send a JSON object."),
    ("[1, 2]", "Send a JSON object."),
])
def test_a_bad_chart_name_or_body_is_a_400_and_asks_no_ai(client, user, monkeypatch, mysql, data, message):
    saved = saved_question(user)
    fake = use_fake_ai(monkeypatch, [json.dumps(SANKEY)])
    client.force_login(user)

    r = chart(client, saved.pk, data)

    assert r.status_code == 400 and message in r.json()["detail"]
    assert fake.calls == [] and mysql == []


# ---------- the JSON checks ----------

BAD_REPLIES = [
    ("not json at all", "it is not JSON"),
    ('{"series": [{"type": "bar", "data": [1, 2]}', "it is not valid JSON"),
    ('{"series": [{"type": "bar", "data": [1, 2,]}]}', "it is not valid JSON"),
    ('{"series": [{"type": "bar", "data": [NaN]}]}', "it is not valid JSON"),
    ('{"series": [{"type": "bar"}], "graphic": [{"type": "text"}]}', "the key 'graphic' is not allowed"),
    ('{"series": [{"type": "bar"}], "toolbox": {}}', "the key 'toolbox' is not allowed"),
    ('{"series": [{"type": "custom"}]}', "the series type 'custom' is not allowed"),
    ('{"series": [{"type": "bar", "label": {"formatter": "function (p) { return p.name }"}}]}', "code, HTML"),
    ('{"series": [{"type": "bar", "label": {"formatter": "(p) => p.name"}}]}', "code, HTML"),
    ('{"series": [{"type": "bar", "name": "javascript:alert(1)"}]}', "code, HTML"),
    ('{"series": [{"type": "bar", "name": "<img src=x onerror=alert(1)>"}]}', "code, HTML"),
    ('{"series": [{"type": "bar", "symbol": "image://https://example.com/x.png"}]}', "code, HTML"),
    ('{"title": {"text": "Sales", "link": "https://example.com"}, "series": [{"type": "bar"}]}', "the key 'link'"),
    ('{"series": [{"type": "bar", "__proto__": {"polluted": true}}]}', "the key '__proto__'"),
    ('{"series": []}', "it has no series"),
    ('{"title": {"text": "no series"}}', "it has no series"),
]


@pytest.mark.parametrize("reply, why", BAD_REPLIES)
def test_an_unsafe_or_broken_reply_is_refused_with_a_friendly_message(client, user, monkeypatch, mysql, reply, why):
    saved = saved_question(user)
    use_fake_ai(monkeypatch, [reply])
    client.force_login(user)

    r = chart(client, saved.pk)

    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail.startswith("The AI did not give a chart that can be drawn safely") and why in detail
    assert "option" not in r.json()


def test_check_option_limits_the_size_and_the_depth():
    deep = {"series": [{"type": "bar", "data": [[[[[[[[[[[[[1]]]]]]]]]]]]]}]}
    with pytest.raises(charts.OptionRejected, match="nested too deep"):
        charts.check_option(deep)
    big = {"series": [{"type": "bar", "data": list(range(charts.MAX_NODES + 10))}]}
    with pytest.raises(charts.OptionRejected, match="too big"):
        charts.check_option(big)
    with pytest.raises(charts.OptionRejected, match="too big"):
        charts.parse_reply('{"series": [{"type": "bar", "name": "' + "x" * charts.MAX_OPTION_CHARS + '"}]}')
    with pytest.raises(charts.OptionRejected, match="too many series"):
        charts.check_option({"series": [{"type": "bar"}] * (charts.MAX_SERIES + 1)})
    # one series as an object is made a list; a "< 30 days" label is not HTML
    option = charts.check_option({"series": {"type": "pie", "data": [{"name": "< 30 days", "value": 3}]}})
    assert option["series"] == [{"type": "pie", "data": [{"name": "< 30 days", "value": 3}]}]


# ---------- friendly errors ----------

def test_a_cut_off_reply_is_a_friendly_message(client, user, monkeypatch, mysql, main_model):
    saved = saved_question(user, model=MAIN, total_tokens=100)
    use_fake_ai(monkeypatch, [(CutOff('{"series": [{"type": "sankey", "data": ['), 1_600)])
    client.force_login(user)

    r = chart(client, saved.pk)

    assert r.status_code == 502 and r.json()["detail"] == charts.CUT_OFF
    saved.refresh_from_db()
    assert saved.total_tokens == 1_700                            # the tokens were used all the same


def test_a_busy_ai_is_a_friendly_503(client, user, monkeypatch, mysql, main_model):
    saved = saved_question(user)
    use_fake_ai(monkeypatch, [rate_limit_error(retry_after=600)])   # longer than the app waits
    client.force_login(user)

    r = chart(client, saved.pk)

    assert r.status_code == 503 and r.json()["detail"] == agent.AI_BUSY


def test_a_daily_limit_is_a_friendly_503(client, user, monkeypatch, mysql, main_model):
    saved = saved_question(user)
    fake = use_fake_ai(monkeypatch, [daily_limit_error(MAIN)])
    client.force_login(user)

    r = chart(client, saved.pk)

    assert r.status_code == 503 and r.json()["detail"] == charts.DAILY_LIMIT
    assert fake.models == [MAIN]                                  # no backup model for a chart


def test_rows_that_cannot_run_again_ask_no_ai(client, user, monkeypatch):
    def down(sql):
        raise warehouse.WarehouseUnavailable("MySQL is not running")

    monkeypatch.setattr(warehouse, "allowed_tables", lambda: TABLES)
    monkeypatch.setattr(warehouse, "run_select", down)
    saved = saved_question(user)
    fake = use_fake_ai(monkeypatch, [json.dumps(SANKEY)])
    client.force_login(user)

    r = chart(client, saved.pk)

    assert r.status_code == 503 and r.json()["detail"].startswith("The rows could not be loaded again")
    assert fake.calls == []


def test_no_rows_no_chart(client, user, monkeypatch):
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: TABLES)
    monkeypatch.setattr(warehouse, "run_select", lambda sql: {"columns": ROWS["columns"], "rows": [], "truncated": False})
    saved = saved_question(user)
    fake = use_fake_ai(monkeypatch, [json.dumps(SANKEY)])
    client.force_login(user)

    r = chart(client, saved.pk)

    assert r.status_code == 400 and r.json()["detail"] == charts.NO_ROWS
    assert fake.calls == []
    assert Question.objects.get(pk=saved.pk).total_tokens is None
