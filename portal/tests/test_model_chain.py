"""The model chain (18-Nov): Groq main -> Gemini Flash -> Gemini Flash-Lite -> the Groq backup (lc/llm.py).

Every AI call tries the models in turn (agent._ask_models): a daily limit, a busy or unreachable model, a request too
large even when cut, or any other error moves the call on; a model at its daily limit (or busy) rests a while and is
passed over. Groq main and Gemini Flash get the full request, Flash-Lite and the Groq backup the cut one
(calls.for_backup). Flash-Lite only does the small calls (rewrite, route - llm.ALLOWED_CALLS): never the SQL, an answer
or an AI chart. The answer card names the model (model_label) and says why it was not the first (model_note, saved
with the question). Staff may choose a model (POST /api/ask "model", GET /api/models): then ONLY that model is asked
and its failure is a clear error card; anyone else's choice is ignored.

The AI is the FAKE of test_agent.py (FakeAI behind LangChain): no Groq call and no Gemini call, ever.
Run with:  python -m pytest -q portal/tests/test_model_chain.py
"""
import json

import httpx
import openai
import pytest
from django.urls import reverse

from django.test import RequestFactory

from portal import api
from portal.lc import llm
from portal.models import Question
from portal.rag import agent, warehouse
from portal.tests.test_agent import (ANSWER, BACKUP, GOOD_SQL, MAIN, ROWS, api_error, connection_error,  # noqa: F401
                                     daily_limit_error, mysql, rate_limit_error, use_fake_ai)
from portal.tests.test_backup_model import five_notes, sql_request, too_large_error  # noqa: F401

pytestmark = pytest.mark.django_db

FLASH, LITE = "gemini-flash-latest", "gemini-flash-lite-latest"
GEMINI_CHAT_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


@pytest.fixture
def chain(monkeypatch):
    """The four models of the chain: Groq main, Gemini Flash, Gemini Flash-Lite, the Groq backup (a test key)."""
    monkeypatch.setenv("GROQ_MODEL", MAIN)
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", BACKUP)
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")


def gemini_error(status, message):
    """An HTTP error of Gemini's OpenAI-compatible address, as ChatOpenAI raises it."""
    response = httpx.Response(status, request=httpx.Request("POST", GEMINI_CHAT_URL))
    kinds = {429: openai.RateLimitError, 401: openai.AuthenticationError, 404: openai.NotFoundError}
    kind = kinds.get(status, openai.InternalServerError if status >= 500 else openai.APIStatusError)
    return kind(message, response=response, body=None)


def gemini_busy():
    return gemini_error(503, "Error code: 503 - The model is overloaded due to high demand. Please try again later.")


def gemini_daily_limit():
    return gemini_error(429, "Error code: 429 - You exceeded your current quota. Quota exceeded for metric: "
                             "generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 250, "
                             "quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier. RESOURCE_EXHAUSTED")


def gemini_minute_limit():
    return gemini_error(429, "Error code: 429 - Quota exceeded, quotaId: GenerateRequestsPerMinutePerProjectPerModel-"
                             "FreeTier. Please retry in 21s. RESOURCE_EXHAUSTED")


def ids():
    return [entry.id for entry in llm.chain_models()]


# ---------- the chain from the settings ----------

def test_the_chain_order_comes_from_the_settings(monkeypatch, chain):
    assert ids() == ["groq-main", "gemini-flash", "gemini-flash-lite", "groq-backup"]
    assert [entry.model for entry in llm.chain_models()] == [MAIN, FLASH, LITE, BACKUP]
    assert [entry.full_request for entry in llm.chain_models()] == [True, True, False, False]
    assert [entry.label for entry in llm.chain_models()] == [
        "Groq gpt-oss-120b", f"Gemini Flash ({FLASH})", f"Gemini Flash-Lite ({LITE})", f"Groq qwen ({BACKUP})"]

    monkeypatch.setenv("AI_MODEL_CHAIN", "gemini-flash, groq-main,unknown-model")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3-flash-preview")
    assert ids() == ["gemini-flash", "groq-main"]                        # only these, in this order
    assert llm.chain_models()[0].model == "gemini-3-flash-preview"


def test_without_the_gemini_key_gemini_is_left_out(monkeypatch, chain):
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setenv("AI_MODEL_CHAIN", "gemini-flash,groq-main,gemini-flash-lite,groq-backup")

    assert ids() == ["groq-main", "groq-backup"]


def test_a_gemini_model_is_made_with_its_own_address_key_and_timeout(monkeypatch, chain):
    model = llm.make_llm(FLASH, agent.ANSWER_MAX_TOKENS, "low")

    assert model.model_name == FLASH and model.openai_api_base == llm.GEMINI_OPENAI_URL
    assert model.request_timeout == llm.GEMINI_TIMEOUT_SECS == 45 and model.max_retries == 0
    assert model.max_tokens == agent.ANSWER_MAX_TOKENS + llm.GEMINI_THINKING_ROOM
    assert model.extra_body == {"reasoning_effort": "low"}
    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(agent.AIUnavailable, match="GEMINI_API_KEY is missing"):
        llm.make_llm(FLASH, agent.ANSWER_MAX_TOKENS, "low")


# ---------- moving on ----------

def test_groqs_daily_limit_moves_the_question_to_gemini_flash_with_the_full_request(monkeypatch, five_notes, user,
                                                                                     chain):
    waits = []
    monkeypatch.setattr(agent.time, "sleep", waits.append)
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), (GOOD_SQL, 4000), (ANSWER, 900)])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and result.answer == ANSWER and waits == []
    assert fake.models == [MAIN, FLASH, FLASH]
    assert fake.calls[1] == fake.calls[0]                                # Gemini Flash: the full request
    assert fake.max_tokens[1:] == [agent.SQL_MAX_TOKENS, agent.ANSWER_MAX_TOKENS]
    assert result.model == FLASH and Question.objects.get().model == FLASH  # counted under its own name
    card = api._card(result.question)
    assert card["backup_model"] == "gemini-flash"
    assert card["model_label"] == f"Gemini Flash ({FLASH})"
    assert card["model_note"] == "Groq's daily limit was reached"


def test_a_resting_model_is_passed_over(monkeypatch, five_notes, user, chain):
    five_notes.results = [ROWS, ROWS]
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), GOOD_SQL, ANSWER, GOOD_SQL, ANSWER])

    agent.ask("Top customers in Aug 2026?", user)
    second = agent.ask("Top customers in Jul 2026?", user)

    assert fake.models == [MAIN, FLASH, FLASH, FLASH, FLASH]               # the next question starts with Flash
    assert second.model == FLASH and second.model_note == "Groq's daily limit was reached"
    assert agent.resting("groq-main")[1] == "Groq's daily limit was reached"


BACKUP_NOTE = ("the backup model qwen answered - Groq and Gemini Flash were not available (Groq's daily limit was "
               "reached; Gemini Flash was busy); answers may be less exact")


def test_a_busy_gemini_flash_never_gives_the_sql_to_flash_lite(monkeypatch, five_notes, user, chain):
    # 18-Nov 17:05: Gemini Flash was busy and Flash-Lite wrote wrong SQL ("no forecast for Aug 2027") - now the SQL
    # and the answer go to the Groq backup, and its card says so plainly
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), gemini_busy(), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and result.model == BACKUP
    assert fake.models == [MAIN, FLASH, BACKUP, BACKUP] and LITE not in fake.models
    backup_request = sql_request(fake.calls[2])
    assert "note piece 2" in backup_request and "note piece 3" not in backup_request  # the cut request
    assert fake.max_tokens[2:] == [agent.FALLBACK_MAX_TOKENS, agent.FALLBACK_MAX_TOKENS]
    assert result.model_note == BACKUP_NOTE
    assert agent.resting("gemini-flash")[0] <= agent.BUSY_RESTING_SECS
    assert not agent.resting("gemini-flash-lite")                        # never asked, so not resting either


def test_flash_lite_still_does_the_small_calls(monkeypatch, chain):
    from portal.lc.calls import LcRequest
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), gemini_busy(), "Top customers in Sep 2026?"])
    result = agent.AskResult(text="and for Sep?")

    reply = agent._ask_ai(LcRequest("rewrite", {"earlier": "1. Top customers in Aug 2026 (latest)",
                                                 "question": "and for Sep?"}), 100, "low", result, timed_as="rewrite")

    assert reply == "Top customers in Sep 2026?" and fake.models == [MAIN, FLASH, LITE]
    assert result.model == LITE and result.model_note == "Groq's daily limit was reached; Gemini Flash was busy"


@pytest.mark.parametrize("call", ["sql", "answer", "docs", "general", "chart"])
def test_flash_lite_may_do_only_the_small_calls(chain, call):
    lite = llm.known_models()["gemini-flash-lite"]
    assert not llm.may_do(lite, call)
    assert llm.may_do(lite, "rewrite") and llm.may_do(lite, "route")
    for model_id in ("groq-main", "gemini-flash", "groq-backup"):          # the backup: the last resort everywhere
        assert llm.may_do(llm.known_models()[model_id], call)


def test_only_flash_lite_left_for_the_sql_gives_the_error_message(monkeypatch, five_notes, user, chain):
    monkeypatch.setenv("AI_MODEL_CHAIN", "gemini-flash,gemini-flash-lite")
    fake = use_fake_ai(monkeypatch, [gemini_busy()])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "error" and result.answer == agent.AI_BUSY and fake.models == [FLASH]


def test_the_backup_too_large_gets_the_smallest_request_once(monkeypatch, five_notes, user, chain):
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), gemini_busy(), too_large_error(BACKUP), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and result.model == BACKUP
    assert fake.models == [MAIN, FLASH, BACKUP, BACKUP, BACKUP]
    assert "the 2 pieces" in sql_request(fake.calls[2])                  # the backup starts with its cut request
    assert "the 1 pieces" in sql_request(fake.calls[3])                  # then once its smallest one


@pytest.mark.parametrize("error", [connection_error, lambda: gemini_error(401, "Error code: 401 - API key not valid"),
                                   lambda: gemini_error(404, "Error code: 404 - model not found"),
                                   gemini_minute_limit],
                         ids=["timeout-or-network", "auth", "not-found", "per-minute"])
def test_other_gemini_errors_move_on_without_waiting(monkeypatch, five_notes, user, chain, error, caplog):
    waits = []
    monkeypatch.setattr(agent.time, "sleep", waits.append)
    monkeypatch.setenv("AI_MODEL_CHAIN", "gemini-flash,groq-main")
    five_notes.results = [ROWS]
    failures = [error(), error()] if error is connection_error else [error()]  # a network error: once more after 3 s
    fake = use_fake_ai(monkeypatch, failures + [GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and result.model == MAIN
    assert fake.models == [FLASH] * len(failures) + [MAIN, MAIN]
    assert waits == ([3] if error is connection_error else [])
    assert "test-gemini-key" not in caplog.text                          # never the key


def test_a_gemini_timeout_moves_on_at_once(monkeypatch, five_notes, user, chain):
    monkeypatch.setenv("AI_MODEL_CHAIN", "gemini-flash,groq-main")
    five_notes.results = [ROWS]
    timeout = openai.APITimeoutError(request=httpx.Request("POST", GEMINI_CHAT_URL))
    fake = use_fake_ai(monkeypatch, [timeout, GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and fake.models == [FLASH, MAIN, MAIN]
    assert result.model_note == "Gemini Flash could not be reached"


def test_a_per_minute_limit_of_groq_main_still_waits(monkeypatch, five_notes, user, chain):
    waits = []
    monkeypatch.setattr(agent.time, "sleep", waits.append)
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [rate_limit_error(retry_after=2), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and result.model == MAIN and result.model_note == ""
    assert waits == [2.5] and fake.models == [MAIN, MAIN, MAIN]          # no Gemini call


def test_every_model_failing_gives_the_error_message(monkeypatch, five_notes, user, chain):
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), gemini_busy(), api_error(400, "Error code: 400 - bad")])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "error" and result.answer == agent.AI_ERROR
    assert fake.models == [MAIN, FLASH, BACKUP] and Question.objects.get().model == ""
    assert Question.objects.get().model_note == ""
    assert api._card(result.question)["model_label"] == "" and api._card(result.question)["model_note"] == ""


def test_every_model_at_its_daily_limit_gives_the_daily_limit_message(monkeypatch, five_notes, user, chain):
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), gemini_daily_limit(), daily_limit_error(BACKUP)])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "error" and result.answer == agent.AI_DAILY_LIMIT
    assert fake.models == [MAIN, FLASH, BACKUP]                          # Flash-Lite writes no SQL
    assert all(agent.resting(model_id) for model_id in ("groq-main", "gemini-flash", "groq-backup"))


# ---------- the admin's choice ----------

def test_a_chosen_model_answers_the_question(monkeypatch, five_notes, user, chain):
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user, model="groq-backup")

    assert fake.models == [BACKUP, BACKUP] and result.model == BACKUP and result.model_note == "chosen by you"
    assert "the 2 pieces" in sql_request(fake.calls[0])                  # still its own (cut) request
    saved = Question.objects.get()
    assert saved.model_note == "chosen by you"                            # saved with the question


@pytest.mark.parametrize("error, message", [
    (gemini_busy, "Gemini Flash is busy right now (Google free tier). Try again in a minute, or choose Auto."),
    (gemini_minute_limit, "Gemini Flash is busy right now (Google free tier). Try again in a minute, or choose Auto."),
    (gemini_daily_limit, "Gemini Flash has reached its daily limit (Google free tier). Choose another model, or Auto."),
    (lambda: gemini_error(401, "Error code: 401 - API key not valid"),
     "Gemini Flash returned an error. Try again, or choose Auto."),
], ids=["busy", "per-minute", "daily", "error"])
def test_a_chosen_model_that_fails_gives_a_clear_error_and_no_other_model(monkeypatch, five_notes, user, chain,
                                                                          error, message):
    fake = use_fake_ai(monkeypatch, [error(), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user, model="gemini-flash")

    assert fake.models == [FLASH]                                         # no Groq, no Flash-Lite, no backup
    assert result.status == "error" and result.answer == message and result.model == ""
    saved = Question.objects.get()
    assert saved.answer == message and saved.model == "" and saved.model_note == ""


def test_a_chosen_model_is_asked_even_while_it_rests(monkeypatch, five_notes, user, chain):
    five_notes.results = [ROWS]
    agent.model_rests("gemini-flash", 120, "Gemini Flash was busy")
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user, model="gemini-flash")

    assert fake.models == [FLASH, FLASH] and result.model_note == "chosen by you"


def test_a_chosen_model_not_set_up_says_so(monkeypatch, five_notes, user, chain):
    monkeypatch.delenv("GEMINI_API_KEY")
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user, model="gemini-flash")

    assert fake.models == [] and result.status == "error"
    assert result.answer == "Gemini Flash is not set up (GEMINI_API_KEY missing). Choose another model, or Auto."
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", "")
    assert agent.ask("Top customers in Aug 2026?", user, model="groq-backup").answer == (
        "The Groq backup model is not set up (GROQ_FALLBACK_MODEL missing). Choose another model, or Auto.")
    monkeypatch.setenv("AI_MODEL_CHAIN", "groq-main")
    assert agent.ask("Top customers in Aug 2026?", user, model="gemini-flash").answer == (
        "Gemini Flash is not in AI_MODEL_CHAIN (.env). Choose another model, or Auto.")


def test_a_chosen_flash_lite_writes_no_sql(monkeypatch, five_notes, user, chain):
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user, model="gemini-flash-lite")

    assert fake.models == [] and result.status == "error"
    assert result.answer == ("Gemini Flash-Lite only does the small steps (rewriting a follow-up, choosing the route), "
                             "not the SQL or the answers. Choose another model, or Auto.")


def test_auto_still_falls_back_in_the_chain(monkeypatch, five_notes, user, chain):
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user, model="")

    assert fake.models == [MAIN, FLASH, FLASH] and result.model == FLASH
    assert result.model_note == "Groq's daily limit was reached"


def ask_api(client, data):
    return client.post(reverse("api_ask"), data=json.dumps(data), content_type="application/json")


def test_staff_choose_the_model_on_the_api(monkeypatch, client, mysql, staff, chain):
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])
    client.force_login(staff)

    r = ask_api(client, {"question": "Top customers in Aug 2026?", "chat_id": None, "model": "gemini-flash"})

    assert r.status_code == 200, r.content
    card = r.json()["card"]
    assert fake.models == [FLASH, FLASH]
    assert (card["backup_model"], card["model_label"], card["model_note"]) == (
        "gemini-flash", f"Gemini Flash ({FLASH})", "chosen by you")
    reopened = client.get(reverse("api_question", args=[card["id"]])).json()["card"]
    assert reopened["model_note"] == "chosen by you"                     # saved: the reopened card says the same


def test_a_busy_chosen_model_is_an_error_card_on_the_api(monkeypatch, client, mysql, staff, chain):
    fake = use_fake_ai(monkeypatch, [gemini_busy(), GOOD_SQL, ANSWER])
    client.force_login(staff)

    r = ask_api(client, {"question": "Top customers in Aug 2026?", "chat_id": None, "model": "gemini-flash"})

    assert r.status_code == 200, r.content
    card = r.json()["card"]
    assert fake.models == [FLASH]
    assert card["status"] == "error" and card["answer"] == (
        "Gemini Flash is busy right now (Google free tier). Try again in a minute, or choose Auto.")
    assert card["model_label"] == "" and card["model_note"] == ""


def test_the_backup_note_is_saved_and_kept_on_the_reopened_card(monkeypatch, client, mysql, user, chain):
    mysql.results = [ROWS]
    use_fake_ai(monkeypatch, [daily_limit_error(), gemini_busy(), GOOD_SQL, ANSWER])
    client.force_login(user)

    card = ask_api(client, {"question": "Top customers in Aug 2026?", "chat_id": None}).json()["card"]
    reopened = client.get(reverse("api_question", args=[card["id"]])).json()["card"]

    assert card["model_note"] == reopened["model_note"] == BACKUP_NOTE   # never "used instead of Groq"
    assert Question.objects.get(pk=card["id"]).model_note == BACKUP_NOTE
    assert reopened["backup_model"] == "groq-backup" and reopened["model_label"] == f"Groq qwen ({BACKUP})"


def test_an_old_answer_without_a_saved_note_keeps_the_old_note(client, user, chain):
    old = Question.objects.create(user=user, text="Top customers?", answer="A", status="docs", model=BACKUP)
    client.force_login(user)

    card = client.get(reverse("api_question", args=[old.pk])).json()["card"]

    assert card["model_note"] == "used instead of Groq"


def test_the_streamed_ask_takes_the_choice_too(monkeypatch, client, mysql, staff, chain):
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])
    client.force_login(staff)

    r = client.post(reverse("api_ask_stream"), data=json.dumps({"question": "Top customers in Aug 2026?",
                                                                 "model": "groq-backup"}),
                    content_type="application/json")
    lines = [json.loads(line) for line in b"".join(r.streaming_content).decode().splitlines()]

    assert lines[-1]["type"] == "done" and lines[-1]["card"]["model_note"] == "chosen by you"
    assert fake.models == [BACKUP, BACKUP]


def test_a_users_choice_is_ignored(monkeypatch, client, mysql, user, chain):
    mysql.results = [ROWS, ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER, GOOD_SQL, ANSWER])
    client.force_login(user)

    r = ask_api(client, {"question": "Top customers in Aug 2026?", "model": "gemini-flash"})

    assert r.status_code == 200 and fake.models == [MAIN, MAIN]
    assert r.json()["card"]["model_note"] == "" and r.json()["card"]["model_label"] == "Groq gpt-oss-120b"
    assert ask_api(client, {"question": "Top customers in Aug 2026?", "model": "no-such-model"}).status_code == 200


def test_a_wrong_model_id_is_400_for_staff(monkeypatch, client, staff, chain):
    fake = use_fake_ai(monkeypatch, [])
    client.force_login(staff)

    r = ask_api(client, {"question": "Top customers in Aug 2026?", "model": "gpt-5"})

    assert r.status_code == 400
    assert r.json()["detail"] == ("model must be one of: auto, groq-main, gemini-flash, gemini-flash-lite, "
                                  "groq-backup.")
    assert fake.calls == [] and not Question.objects.exists()
    for auto in ("auto", "", None):
        request = RequestFactory().post("/api/ask", data=json.dumps({"model": auto}), content_type="application/json")
        request.user = staff
        assert api._chosen_model(request) == ("", None)


def test_the_ai_chart_takes_the_choice_too(monkeypatch, client, staff, chain):
    from portal.tests.test_views_ask import SQL, TABLES
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: TABLES)
    monkeypatch.setattr(warehouse, "run_select", lambda sql: ROWS)
    saved = Question.objects.create(user=staff, text="Top customers?", sql=SQL, answer="A", status="ok",
                                    rows_count=2, model=MAIN)
    option = {"series": [{"type": "pie", "data": [{"name": "Aurora", "value": 1}]}]}
    fake = use_fake_ai(monkeypatch, [json.dumps(option), gemini_busy(), daily_limit_error(), json.dumps(option)])
    client.force_login(staff)

    def chart(model):
        return client.post(reverse("api_chart", args=[saved.pk]), content_type="application/json",
                           data=json.dumps({"kind": "sankey diagram", "model": model}))

    r = chart("groq-backup")
    assert r.status_code == 200, r.content
    assert fake.models == [BACKUP] and r.json()["model"] == BACKUP     # the same chain as a question's calls
    busy = chart("gemini-flash")                                          # the chosen model only: no fallback
    assert busy.status_code == 503 and fake.models == [BACKUP, FLASH]
    assert "Gemini Flash is busy right now (Google free tier)" in busy.content.decode()
    lite = chart("gemini-flash-lite")                                     # Flash-Lite makes no AI chart
    assert lite.status_code == 503 and fake.models == [BACKUP, FLASH]
    assert "Gemini Flash-Lite only does the small steps" in lite.content.decode()
    r = chart("auto")                                                     # auto: Groq's daily limit -> the backup
    assert r.status_code == 200 and fake.models == [BACKUP, FLASH, MAIN, BACKUP]


# ---------- GET /api/models ----------

def test_the_models_list_is_for_staff_only(client, user, chain):
    client.force_login(user)
    assert client.get(reverse("api_models")).status_code == 403


def test_the_models_list_says_what_can_be_chosen(monkeypatch, client, staff, chain):
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", "")
    agent.model_rests("gemini-flash", 120, "Gemini Flash was busy")
    client.force_login(staff)

    models = client.get(reverse("api_models")).json()["models"]

    assert [m["id"] for m in models] == ["auto", "groq-main", "gemini-flash", "gemini-flash-lite", "groq-backup"]
    assert models[0] == {"id": "auto", "label": "Auto (recommended)", "available": True}
    assert models[1] == {"id": "groq-main", "label": "Groq gpt-oss-120b", "available": True}
    assert models[2]["available"] is False and models[2]["note"].startswith("resting until ")
    assert models[2]["note"].endswith("(Gemini Flash was busy)")
    assert models[3] == {"id": "gemini-flash-lite", "label": f"Gemini Flash-Lite ({LITE})", "available": False,
                         "note": "only for the small steps (rewrite, route) - not for the SQL or the answers"}
    assert models[4]["available"] is False and models[4]["note"] == "GROQ_FALLBACK_MODEL is not set in .env"
    assert "test-gemini-key" not in json.dumps(models)


def test_without_the_gemini_key_gemini_cannot_be_chosen(monkeypatch, client, staff, chain):
    monkeypatch.delenv("GEMINI_API_KEY")
    client.force_login(staff)

    models = {m["id"]: m for m in client.get(reverse("api_models")).json()["models"]}

    assert models["gemini-flash"]["available"] is False
    assert models["gemini-flash"]["note"] == "GEMINI_API_KEY is not set in .env"
    assert models["groq-backup"]["available"] is True
