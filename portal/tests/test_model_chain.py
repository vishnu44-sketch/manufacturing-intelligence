"""The model chain (18-Nov; 19-Nov: Groq only, with a second Groq key): Groq main -> the same model on the second
Groq key (GROQ_API_KEY_2) -> the Groq backup (lc/llm.py).

Every AI call tries the models in turn (agent._ask_models): a daily limit, a busy or unreachable model, a request too
large even when cut, or any other error moves the call on; a model at its daily limit (or busy) rests a while and is
passed over. Groq main and the second key get the full request, the Groq backup the cut one (calls.for_backup).
The second key is the same model name as the first: the chain tells them apart by id and key setting, so the first
key resting never makes the second one rest. The answer card names the model (model_label) and says why it was not
the first (model_note, saved with the question). Staff may choose a model (POST /api/ask "model", GET /api/models):
then ONLY that model is asked and its failure is a clear error card; anyone else's choice is ignored.

The AI is the FAKE of test_agent.py (FakeAI behind LangChain): no Groq call, ever. FakeAI.keys = the key setting each
chat model was made with (GROQ_API_KEY / GROQ_API_KEY_2).
Run with:  python -m pytest -q portal/tests/test_model_chain.py
"""
import json

import pytest
from django.test import RequestFactory
from django.urls import reverse

from portal import api
from portal.lc import llm
from portal.models import Question
from portal.rag import agent, warehouse
from portal.tests.test_agent import (ANSWER, BACKUP, GOOD_SQL, MAIN, ROWS, api_error, connection_error,  # noqa: F401
                                     daily_limit_error, mysql, rate_limit_error, use_fake_ai)
from portal.tests.test_backup_model import five_notes, sql_request, too_large_error  # noqa: F401

pytestmark = pytest.mark.django_db

KEY, KEY_2 = llm.KEY, llm.KEY_2
SECOND_NOTE = "Groq's daily limit was reached - the second Groq key answered"


@pytest.fixture
def chain(monkeypatch):
    """The three models of the chain: Groq main, the same model on the second Groq key, the Groq backup."""
    monkeypatch.setenv("GROQ_MODEL", MAIN)
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", BACKUP)
    monkeypatch.setenv(KEY_2, "test-groq-key-2")


def busy_error():
    """Groq's 503 (over capacity), as ChatOpenAI raises it."""
    return api_error(503, "Error code: 503 - Service Unavailable: over capacity")


def ids():
    return [entry.id for entry in llm.chain_models()]


# ---------- the chain from the settings ----------

def test_the_chain_order_comes_from_the_settings(monkeypatch, chain):
    assert ids() == ["groq-main", "groq-main-2", "groq-backup"]
    assert [entry.model for entry in llm.chain_models()] == [MAIN, MAIN, BACKUP]     # the same model on both keys
    assert [entry.key_env for entry in llm.chain_models()] == [KEY, KEY_2, KEY]
    assert [entry.full_request for entry in llm.chain_models()] == [True, True, False]
    assert [entry.label for entry in llm.chain_models()] == [
        "Groq gpt-oss-120b", "Groq gpt-oss-120b (2nd key)", f"Groq qwen ({BACKUP})"]

    monkeypatch.setenv("AI_MODEL_CHAIN", "groq-main-2, groq-main,old-model-id,unknown-model")
    assert ids() == ["groq-main-2", "groq-main"]                          # only these, in this order


def test_the_second_key_is_not_deduped_away(monkeypatch, chain):
    monkeypatch.setenv("AI_MODEL_CHAIN", "groq-main,groq-main,groq-main-2")

    assert ids() == ["groq-main", "groq-main-2"]                          # an id listed twice: once
    assert llm.chain_models()[0].model == llm.chain_models()[1].model == MAIN
    assert llm.label_of(MAIN) == "Groq gpt-oss-120b" and llm.find(MAIN).id == "groq-main"


def test_without_the_second_key_it_is_left_out(monkeypatch, chain):
    monkeypatch.delenv(KEY_2)
    monkeypatch.setenv("AI_MODEL_CHAIN", "groq-main-2,groq-main,groq-backup")

    assert ids() == ["groq-main", "groq-backup"]
    assert "groq-main-2" not in llm.known_models()


def test_the_second_key_is_made_with_its_own_key_and_groqs_address(monkeypatch, chain):
    monkeypatch.setenv(KEY, "test-groq-key-1")

    second = llm.make_llm(MAIN, agent.ANSWER_MAX_TOKENS, "low", key_env=KEY_2)
    first = llm.make_llm(MAIN, agent.ANSWER_MAX_TOKENS, "low")

    assert second.openai_api_key.get_secret_value() == "test-groq-key-2"
    assert first.openai_api_key.get_secret_value() == "test-groq-key-1"
    assert second.model_name == MAIN and second.openai_api_base == llm.GROQ_OPENAI_URL
    assert second.request_timeout == llm.TIMEOUT_SECS and second.max_retries == 0
    assert second.max_tokens == agent.ANSWER_MAX_TOKENS
    assert second.extra_body == {"reasoning_effort": "low", "include_reasoning": False}
    monkeypatch.delenv(KEY_2)
    with pytest.raises(agent.AIUnavailable) as missing:
        llm.make_llm(MAIN, agent.ANSWER_MAX_TOKENS, "low", key_env=KEY_2)
    assert str(missing.value) == "The AI service is not set up (GROQ_API_KEY_2 is missing in .env)."


# ---------- moving on ----------

def test_the_first_keys_daily_limit_moves_the_question_to_the_second_key(monkeypatch, five_notes, user, chain):
    waits = []
    monkeypatch.setattr(agent.time, "sleep", waits.append)
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), (GOOD_SQL, 4000), (ANSWER, 900)])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and result.answer == ANSWER and waits == []
    assert fake.models == [MAIN, MAIN, MAIN] and fake.keys == [KEY, KEY_2, KEY_2]
    assert fake.calls[1] == fake.calls[0]                                # the second key: the full request
    assert fake.max_tokens[1:] == [agent.SQL_MAX_TOKENS, agent.ANSWER_MAX_TOKENS]
    assert result.model == MAIN and Question.objects.get().model == MAIN  # the same model name
    card = api._card(result.question)
    assert card["backup_model"] == ""                                     # not the backup model
    assert card["model_label"] == "Groq gpt-oss-120b"
    assert card["model_note"] == SECOND_NOTE                              # but the note says which key answered


def test_the_first_key_resting_does_not_rest_the_second(monkeypatch, five_notes, user, chain):
    five_notes.results = [ROWS, ROWS]
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), GOOD_SQL, ANSWER, GOOD_SQL, ANSWER])

    agent.ask("Top customers in Aug 2026?", user)
    second = agent.ask("Top customers in Jul 2026?", user)

    assert fake.keys == [KEY, KEY_2, KEY_2, KEY_2, KEY_2]                 # the next question starts on the second key
    assert second.model == MAIN and second.model_note == SECOND_NOTE
    assert agent.resting("groq-main")[1] == "Groq's daily limit was reached"
    assert agent.resting("groq-main-2") is None


def test_the_second_key_resting_does_not_rest_the_first(monkeypatch, five_notes, user, chain):
    five_notes.results = [ROWS]
    agent.model_rests("groq-main-2", 600, "the second Groq key's daily limit was reached")
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert fake.keys == [KEY, KEY] and result.model_note == ""
    assert agent.resting("groq-main") is None


BACKUP_NOTE = ("the backup model qwen answered - Groq and the second Groq key were not available (Groq's daily limit "
               "was reached; the second Groq key's daily limit was reached); answers may be less exact")


def test_both_keys_at_their_daily_limit_go_to_the_backup(monkeypatch, five_notes, user, chain):
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), daily_limit_error(), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and result.model == BACKUP
    assert fake.models == [MAIN, MAIN, BACKUP, BACKUP] and fake.keys == [KEY, KEY_2, KEY, KEY]
    backup_request = sql_request(fake.calls[2])
    assert "note piece 2" in backup_request and "note piece 3" not in backup_request  # the cut request
    assert fake.max_tokens[2:] == [agent.FALLBACK_MAX_TOKENS, agent.FALLBACK_MAX_TOKENS]
    assert result.model_note == BACKUP_NOTE
    assert agent.resting("groq-main") and agent.resting("groq-main-2")


def test_a_busy_second_key_goes_to_the_backup(monkeypatch, five_notes, user, chain):
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), busy_error(), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and result.model == BACKUP and fake.keys == [KEY, KEY_2, KEY, KEY]
    assert result.model_note == ("the backup model qwen answered - Groq and the second Groq key were not available "
                                 "(Groq's daily limit was reached; the second Groq key was busy); answers may be "
                                 "less exact")
    assert agent.resting("groq-main-2")[0] <= agent.BUSY_RESTING_SECS


# ---------- a per-minute limit: the other Groq key at once (19-Nov) ----------

MINUTE_NOTE = "Groq was at its per-minute limit - the second Groq key answered"


def rest_ends(model_id):
    """The model's short rest is over (as if its seconds had passed)."""
    until, why, minute = agent._resting[model_id]
    agent._resting[model_id] = (agent.time.monotonic() - 1, why, minute)


def test_the_first_keys_per_minute_limit_asks_the_second_key_at_once(monkeypatch, five_notes, user, chain):
    waits = []
    monkeypatch.setattr(agent.time, "sleep", waits.append)
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [rate_limit_error(retry_after=7), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and result.model == MAIN and waits == []  # no waiting at all
    assert fake.keys == [KEY, KEY_2, KEY_2]                               # the answer starts on the second key too
    assert fake.calls[1] == fake.calls[0]                                 # the full request, not the backup's cut one
    assert BACKUP not in fake.models
    assert result.model_note == MINUTE_NOTE
    left, why = agent.resting("groq-main")                                # rests until Groq's reset (7 s + 0.5)
    assert 6 < left <= 7.5 and why == "Groq was at its per-minute limit"
    assert agent.minute_resting("groq-main") and agent.resting("groq-main-2") is None
    card = api._card(result.question)
    assert card["model_note"] == MINUTE_NOTE and card["model_label"] == "Groq gpt-oss-120b"


def test_the_first_key_is_used_again_when_its_short_rest_ends(monkeypatch, five_notes, user, chain):
    waits = []
    monkeypatch.setattr(agent.time, "sleep", waits.append)
    five_notes.results = [ROWS, ROWS, ROWS]
    fake = use_fake_ai(monkeypatch, [rate_limit_error(retry_after=30), GOOD_SQL, ANSWER,
                                     GOOD_SQL, ANSWER, GOOD_SQL, ANSWER])

    agent.ask("Top customers in Aug 2026?", user)
    second = agent.ask("Top customers in Jul 2026?", user)               # while the first key rests
    assert fake.keys == [KEY, KEY_2, KEY_2, KEY_2, KEY_2]
    assert second.model_note == MINUTE_NOTE

    rest_ends("groq-main")
    third = agent.ask("Top customers in Jun 2026?", user)

    assert fake.keys[5:] == [KEY, KEY] and third.model_note == "" and waits == []


def test_both_keys_at_their_per_minute_limit_wait_not_the_backup(monkeypatch, five_notes, user, chain):
    waits = []
    monkeypatch.setattr(agent.time, "sleep", waits.append)
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [rate_limit_error(retry_after=7), rate_limit_error(retry_after=2), GOOD_SQL,
                                     ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and result.model == MAIN
    assert fake.keys == [KEY, KEY_2, KEY_2, KEY_2] and BACKUP not in fake.models  # the second key waited
    assert waits == [2.5] and result.model_note == MINUTE_NOTE


def test_the_first_key_waits_when_the_second_key_fails_after_the_switch(monkeypatch, five_notes, user, chain):
    waits = []
    monkeypatch.setattr(agent.time, "sleep", waits.append)
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [rate_limit_error(retry_after=7), daily_limit_error(),
                                     rate_limit_error(retry_after=2), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    # the first key is asked again (and waits) before the weaker backup - for the answer too, while it rests
    assert result.status == "ok" and result.model == MAIN and BACKUP not in fake.models
    assert fake.keys == [KEY, KEY_2, KEY, KEY, KEY] and waits == [2.5]
    assert result.model_note == ""


def test_with_only_the_first_key_a_per_minute_limit_still_waits(monkeypatch, five_notes, user, chain):
    monkeypatch.delenv(KEY_2)
    waits = []
    monkeypatch.setattr(agent.time, "sleep", waits.append)
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [rate_limit_error(retry_after=2), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and result.model == MAIN and result.model_note == ""
    assert waits == [2.5] and fake.keys == [KEY, KEY, KEY]               # not the backup
    assert agent.resting("groq-main") is None


def test_a_resting_second_key_leaves_the_first_key_waiting(monkeypatch, five_notes, user, chain):
    agent.model_rests("groq-main-2", 600, "the second Groq key's daily limit was reached")
    waits = []
    monkeypatch.setattr(agent.time, "sleep", waits.append)
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [rate_limit_error(retry_after=2), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert waits == [2.5] and fake.keys == [KEY, KEY, KEY] and result.model_note == ""


def test_a_chosen_key_at_its_per_minute_limit_still_waits(monkeypatch, five_notes, user, chain):
    waits = []
    monkeypatch.setattr(agent.time, "sleep", waits.append)
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [rate_limit_error(retry_after=2), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user, model="groq-main")

    assert result.status == "ok" and result.model_note == "chosen by you"
    assert waits == [2.5] and fake.keys == [KEY, KEY, KEY]               # the second key not asked


def test_the_first_keys_per_minute_limit_on_the_streamed_ask(monkeypatch, client, mysql, user, chain):
    waits = []
    monkeypatch.setattr(agent.time, "sleep", waits.append)
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, rate_limit_error(retry_after=7), ANSWER])
    client.force_login(user)

    r = client.post(reverse("api_ask_stream"), data=json.dumps({"question": "Top customers in Aug 2026?"}),
                    content_type="application/json")
    lines = [json.loads(line) for line in b"".join(r.streaming_content).decode().splitlines()]

    assert lines[-1]["type"] == "done" and lines[-1]["card"]["model_note"] == MINUTE_NOTE
    assert fake.keys == [KEY, KEY, KEY_2] and waits == []                 # the streamed answer moved at once


@pytest.mark.parametrize("headers, text, secs", [
    ({"retry-after": "7"}, "Rate limit reached", 7.5),
    ({}, "Rate limit reached ... Please try again in 3.2s.", 3.7),
    ({"x-ratelimit-reset-tokens": "7.66s"}, "Rate limit reached", 7.66),
    ({"x-ratelimit-reset-tokens": "500ms"}, "Rate limit reached", 1.0),          # at least 1 s
    ({"x-ratelimit-reset-tokens": "2m59.56s"}, "Rate limit reached", 60),        # at most a minute
    ({"retry-after": "300"}, "Rate limit reached", 60),
    ({}, "Rate limit reached", 60),                                              # nothing said: a minute
], ids=["retry-after", "text", "reset-header", "ms", "minutes", "long", "none"])
def test_the_short_rest_lasts_until_groqs_reset(headers, text, secs):
    import httpx
    import openai
    from portal.lc import calls

    response = httpx.Response(429, headers=headers, request=httpx.Request("POST", "https://api.groq.com/x"))
    error = openai.RateLimitError(text, response=response, body=None)

    assert calls.minute_reset(error) == pytest.approx(secs)


def test_the_first_keys_413_gives_the_second_key_the_full_request(monkeypatch, five_notes, user, chain):
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [too_large_error(MAIN), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    # a 413 is that minute's limit, so the first key does not rest: the answer call goes to it again
    assert result.status == "ok" and fake.keys == [KEY, KEY_2, KEY]
    assert fake.calls[1] == fake.calls[0]                                # not cut: the other account's tokens a minute
    assert result.model_reasons == {"groq-main": "the question was too large for Groq"}
    assert agent.resting("groq-main") is None


@pytest.mark.parametrize("error", [connection_error, lambda: api_error(401, "Error code: 401 - Invalid API Key")],
                         ids=["network", "auth"])
def test_other_errors_of_the_second_key_move_on(monkeypatch, five_notes, user, chain, error, caplog):
    waits = []
    monkeypatch.setattr(agent.time, "sleep", waits.append)
    monkeypatch.setenv("AI_MODEL_CHAIN", "groq-main-2,groq-main")
    five_notes.results = [ROWS]
    failures = [error(), error()] if error is connection_error else [error()]  # a network error: once more after 3 s
    fake = use_fake_ai(monkeypatch, failures + [GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and result.model == MAIN
    # the SQL call moved on to the first key (an error that is not a limit does not rest: the answer call may try
    # the second key again)
    assert fake.keys[:len(failures) + 1] == [KEY_2] * len(failures) + [KEY]
    assert waits == ([3] if error is connection_error else [])
    assert "test-groq-key-2" not in caplog.text                          # never the key


def test_the_backup_too_large_gets_the_smallest_request_once(monkeypatch, five_notes, user, chain):
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), busy_error(), too_large_error(BACKUP), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and result.model == BACKUP
    assert fake.models == [MAIN, MAIN, BACKUP, BACKUP, BACKUP]
    assert "the 2 pieces" in sql_request(fake.calls[2])                  # the backup starts with its cut request
    assert "the 1 pieces" in sql_request(fake.calls[3])                  # then once its smallest one


def test_every_model_failing_gives_the_error_message(monkeypatch, five_notes, user, chain):
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), busy_error(), api_error(400, "Error code: 400 - bad")])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "error" and result.answer == agent.AI_ERROR
    assert fake.keys == [KEY, KEY_2, KEY] and Question.objects.get().model == ""
    assert Question.objects.get().model_note == ""
    assert api._card(result.question)["model_label"] == "" and api._card(result.question)["model_note"] == ""


def test_every_model_at_its_daily_limit_gives_the_daily_limit_message(monkeypatch, five_notes, user, chain):
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), daily_limit_error(), daily_limit_error(BACKUP)])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "error" and result.answer == agent.AI_DAILY_LIMIT
    assert fake.models == [MAIN, MAIN, BACKUP] and fake.keys == [KEY, KEY_2, KEY]
    assert all(agent.resting(model_id) for model_id in ("groq-main", "groq-main-2", "groq-backup"))


# ---------- the admin's choice ----------

def test_a_chosen_model_answers_the_question(monkeypatch, five_notes, user, chain):
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user, model="groq-backup")

    assert fake.models == [BACKUP, BACKUP] and result.model == BACKUP and result.model_note == "chosen by you"
    assert "the 2 pieces" in sql_request(fake.calls[0])                  # still its own (cut) request
    saved = Question.objects.get()
    assert saved.model_note == "chosen by you"                            # saved with the question


def test_a_chosen_second_key_answers_alone(monkeypatch, five_notes, user, chain):
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user, model="groq-main-2")

    assert fake.models == [MAIN, MAIN] and fake.keys == [KEY_2, KEY_2]
    assert result.model == MAIN and result.model_note == "chosen by you"


@pytest.mark.parametrize("error, message", [
    (busy_error, "The second Groq key is busy right now (Groq free tier). Try again in a minute, or choose Auto."),
    (daily_limit_error,
     "The second Groq key has reached its daily limit (Groq free tier). Choose another model, or Auto."),
    (lambda: api_error(401, "Error code: 401 - Invalid API Key"),
     "The second Groq key returned an error. Try again, or choose Auto."),
], ids=["busy", "daily", "error"])
def test_a_chosen_model_that_fails_gives_a_clear_error_and_no_other_model(monkeypatch, five_notes, user, chain,
                                                                          error, message):
    fake = use_fake_ai(monkeypatch, [error(), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user, model="groq-main-2")

    assert fake.keys == [KEY_2]                                           # not the first key, not the backup
    assert result.status == "error" and result.answer == message and result.model == ""
    saved = Question.objects.get()
    assert saved.answer == message and saved.model == "" and saved.model_note == ""


def test_a_chosen_model_is_asked_even_while_it_rests(monkeypatch, five_notes, user, chain):
    five_notes.results = [ROWS]
    agent.model_rests("groq-main-2", 120, "the second Groq key was busy")
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user, model="groq-main-2")

    assert fake.keys == [KEY_2, KEY_2] and result.model_note == "chosen by you"


def test_a_chosen_model_not_set_up_says_so(monkeypatch, five_notes, user, chain):
    monkeypatch.delenv(KEY_2)
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user, model="groq-main-2")

    assert fake.models == [] and result.status == "error"
    assert result.answer == "The second Groq key is not set up (GROQ_API_KEY_2 missing). Choose another model, or Auto."
    monkeypatch.setenv(KEY_2, "test-groq-key-2")
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", "")
    assert agent.ask("Top customers in Aug 2026?", user, model="groq-backup").answer == (
        "The Groq backup model is not set up (GROQ_FALLBACK_MODEL missing). Choose another model, or Auto.")
    monkeypatch.setenv("AI_MODEL_CHAIN", "groq-main")
    assert agent.ask("Top customers in Aug 2026?", user, model="groq-main-2").answer == (
        "The second Groq key is not in AI_MODEL_CHAIN (.env). Choose another model, or Auto.")


def test_auto_still_falls_back_in_the_chain(monkeypatch, five_notes, user, chain):
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user, model="")

    assert fake.keys == [KEY, KEY_2, KEY_2] and result.model_note == SECOND_NOTE


def ask_api(client, data):
    return client.post(reverse("api_ask"), data=json.dumps(data), content_type="application/json")


def test_staff_choose_the_model_on_the_api(monkeypatch, client, mysql, staff, chain):
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])
    client.force_login(staff)

    r = ask_api(client, {"question": "Top customers in Aug 2026?", "chat_id": None, "model": "groq-main-2"})

    assert r.status_code == 200, r.content
    card = r.json()["card"]
    assert fake.keys == [KEY_2, KEY_2]
    assert (card["backup_model"], card["model_label"], card["model_note"]) == (
        "", "Groq gpt-oss-120b", "chosen by you")
    reopened = client.get(reverse("api_question", args=[card["id"]])).json()["card"]
    assert reopened["model_note"] == "chosen by you"                     # saved: the reopened card says the same


def test_a_busy_chosen_model_is_an_error_card_on_the_api(monkeypatch, client, mysql, staff, chain):
    fake = use_fake_ai(monkeypatch, [busy_error(), GOOD_SQL, ANSWER])
    client.force_login(staff)

    r = ask_api(client, {"question": "Top customers in Aug 2026?", "chat_id": None, "model": "groq-main-2"})

    assert r.status_code == 200, r.content
    card = r.json()["card"]
    assert fake.keys == [KEY_2]
    assert card["status"] == "error" and card["answer"] == (
        "The second Groq key is busy right now (Groq free tier). Try again in a minute, or choose Auto.")
    assert card["model_label"] == "" and card["model_note"] == ""


def test_the_backup_note_is_saved_and_kept_on_the_reopened_card(monkeypatch, client, mysql, user, chain):
    mysql.results = [ROWS]
    use_fake_ai(monkeypatch, [daily_limit_error(), daily_limit_error(), GOOD_SQL, ANSWER])
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
                                                                 "model": "groq-main-2"}),
                    content_type="application/json")
    lines = [json.loads(line) for line in b"".join(r.streaming_content).decode().splitlines()]

    assert lines[-1]["type"] == "done" and lines[-1]["card"]["model_note"] == "chosen by you"
    assert fake.keys == [KEY_2, KEY_2]                                    # the streamed answer on the second key too


def test_a_users_choice_is_ignored(monkeypatch, client, mysql, user, chain):
    mysql.results = [ROWS, ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER, GOOD_SQL, ANSWER])
    client.force_login(user)

    r = ask_api(client, {"question": "Top customers in Aug 2026?", "model": "groq-main-2"})

    assert r.status_code == 200 and fake.keys == [KEY, KEY]
    assert r.json()["card"]["model_note"] == "" and r.json()["card"]["model_label"] == "Groq gpt-oss-120b"
    assert ask_api(client, {"question": "Top customers in Aug 2026?", "model": "no-such-model"}).status_code == 200


def test_a_wrong_model_id_is_400_for_staff(monkeypatch, client, staff, chain):
    fake = use_fake_ai(monkeypatch, [])
    client.force_login(staff)

    r = ask_api(client, {"question": "Top customers in Aug 2026?", "model": "gpt-5"})

    assert r.status_code == 400
    assert r.json()["detail"] == "model must be one of: auto, groq-main, groq-main-2, groq-backup, local."
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
    fake = use_fake_ai(monkeypatch, [json.dumps(option), busy_error(), daily_limit_error(), json.dumps(option)])
    client.force_login(staff)

    def chart(model):
        return client.post(reverse("api_chart", args=[saved.pk]), content_type="application/json",
                           data=json.dumps({"kind": "sankey diagram", "model": model}))

    r = chart("groq-backup")
    assert r.status_code == 200, r.content
    assert fake.models == [BACKUP] and r.json()["model"] == BACKUP     # the same chain as a question's calls
    busy = chart("groq-main-2")                                           # the chosen model only: no fallback
    assert busy.status_code == 503 and fake.keys == [KEY, KEY_2]
    assert "The second Groq key is busy right now (Groq free tier)" in busy.content.decode()
    r = chart("auto")                                 # auto: the first key's daily limit, the second key rests -> backup
    assert r.status_code == 200 and fake.models == [BACKUP, MAIN, MAIN, BACKUP]
    assert fake.keys == [KEY, KEY_2, KEY, KEY]


# ---------- 23-Nov: editing a question and "Ask again" use the chosen model too (they used Auto only) ----------

def edit_or_again(client, name, old, model=None):
    """POST /api/questions/<id>/edit ({question}) or /again, with "model" when given."""
    data = {"question": "Top customers in Aug 2026?"} if name == "api_edit" else {}
    if model is not None:
        data["model"] = model
    return client.post(reverse(name, args=[old.pk]), data=json.dumps(data), content_type="application/json")


def old_question(owner):
    return Question.objects.create(user=owner, text="Top customers in Jul 2026?", answer="A", status="ok")


@pytest.mark.parametrize("name", ["api_edit", "api_again"])
def test_edit_and_ask_again_take_the_chosen_model(monkeypatch, client, mysql, staff, chain, name):
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])
    client.force_login(staff)
    old = old_question(staff)

    r = edit_or_again(client, name, old, "groq-main-2")

    assert r.status_code == 200, r.content
    assert fake.keys == [KEY_2, KEY_2]                                    # the chosen key, not Auto's first key
    assert r.json()["card"]["model_note"] == "chosen by you"
    assert Question.objects.get(pk=r.json()["card"]["id"]).model_note == "chosen by you"


@pytest.mark.parametrize("model", [None, "auto"])
@pytest.mark.parametrize("name", ["api_edit", "api_again"])
def test_edit_and_ask_again_without_a_choice_use_auto(monkeypatch, client, mysql, staff, chain, name, model):
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])
    client.force_login(staff)

    r = edit_or_again(client, name, old_question(staff), model)

    assert r.status_code == 200, r.content
    assert fake.keys == [KEY, KEY] and r.json()["card"]["model_note"] == ""


@pytest.mark.parametrize("name", ["api_edit", "api_again"])
def test_a_users_choice_on_edit_and_ask_again_is_ignored(monkeypatch, client, mysql, user, chain, name):
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])
    client.force_login(user)

    r = edit_or_again(client, name, old_question(user), "groq-main-2")

    assert r.status_code == 200 and fake.keys == [KEY, KEY]              # not an administrator: always Auto
    assert r.json()["card"]["model_note"] == ""


@pytest.mark.parametrize("name", ["api_edit", "api_again"])
def test_a_wrong_model_id_on_edit_and_ask_again_is_400(monkeypatch, client, staff, chain, name):
    fake = use_fake_ai(monkeypatch, [])
    client.force_login(staff)
    old = old_question(staff)

    r = edit_or_again(client, name, old, "gpt-5")

    assert r.status_code == 400
    assert r.json()["detail"] == "model must be one of: auto, groq-main, groq-main-2, groq-backup, local."
    assert fake.calls == [] and Question.objects.count() == 1           # nothing asked, nothing saved
    assert Question.objects.get(pk=old.pk).replaced_by_id is None       # the old question is not replaced


@pytest.mark.parametrize("name", ["api_edit", "api_again"])
def test_an_unavailable_chosen_model_on_edit_and_ask_again_says_so(monkeypatch, client, staff, chain, name):
    monkeypatch.delenv(KEY_2)
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])
    client.force_login(staff)

    r = edit_or_again(client, name, old_question(staff), "groq-main-2")

    assert r.status_code == 200, r.content
    card = r.json()["card"]
    assert fake.models == [] and card["status"] == "error"               # never another model in its place
    assert card["answer"] == ("The second Groq key is not set up (GROQ_API_KEY_2 missing). Choose another model, "
                              "or Auto.")


# ---------- GET /api/models ----------

def test_the_models_list_is_for_staff_only(client, user, chain):
    client.force_login(user)
    assert client.get(reverse("api_models")).status_code == 403


def test_the_models_list_says_what_can_be_chosen(monkeypatch, client, staff, chain):
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", "")
    agent.model_rests("groq-main", 600, "Groq's daily limit was reached")
    client.force_login(staff)

    models = client.get(reverse("api_models")).json()["models"]

    assert [m["id"] for m in models] == ["auto", "groq-main", "groq-main-2", "groq-backup", "local"]  # 20-Nov
    assert models[0] == {"id": "auto", "label": "Auto (recommended)", "available": True}
    assert models[1]["available"] is False and models[1]["note"].startswith("resting until ")
    assert models[1]["label"] == "Groq gpt-oss-120b" and models[1]["note"].endswith("(Groq's daily limit was reached)")
    assert models[2] == {"id": "groq-main-2", "label": "Groq gpt-oss-120b (2nd key)", "available": True}
    assert models[3]["available"] is False and models[3]["note"] == "GROQ_FALLBACK_MODEL is not set in .env"
    assert "test-groq-key-2" not in json.dumps(models)


def test_without_the_second_key_it_cannot_be_chosen(monkeypatch, client, staff, chain):
    monkeypatch.delenv(KEY_2)
    client.force_login(staff)

    models = {m["id"]: m for m in client.get(reverse("api_models")).json()["models"]}

    assert models["groq-main-2"]["available"] is False
    assert models["groq-main-2"]["note"] == "GROQ_API_KEY_2 is not set in .env"
    assert models["groq-main"]["available"] is True and models["groq-backup"]["available"] is True
