"""The company's local AI model (20-Nov, lc/llm.py "local"): an OpenAI-compatible server inside the company (Ollama /v1,
LM Studio, llama.cpp server, vLLM) on a CPU.

It exists only when LOCAL_LLM_URL and LOCAL_LLM_MODEL are set, is NOT in Auto (Groq stays as it is) unless
AI_MODEL_CHAIN lists it, and an admin may choose it - then only it is asked, and its failures are plain messages
(could not be reached, too slow, context too small, 404). /api/models lists it with a "hint" (slow: a CPU).
python manage.py check_local_llm sends it one tiny message.

The AI is the FAKE of test_agent.py (FakeAI behind LangChain): no Groq call and no local server call, ever.
FakeAI.keys = the key setting each chat model was made with (LOCAL_LLM_API_KEY for the local model).
Run with:  python -m pytest -q portal/tests/test_local_model.py
"""
import json

import httpx
import openai
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from langchain_core.messages import AIMessageChunk

from portal import api
from portal.lc import calls, chains, llm
from portal.lc.calls import LcRequest
from portal.management.commands import check_local_llm, run_eval
from portal.models import Question
from portal.rag import agent
from portal.tests.test_agent import (ANSWER, BACKUP, GOOD_SQL, MAIN, ROWS, api_error, connection_error,  # noqa: F401
                                     daily_limit_error, mysql, use_fake_ai)
from portal.tests.test_backup_model import five_notes  # noqa: F401

pytestmark = pytest.mark.django_db

URL, NAME = "http://10.0.0.5:11434/v1", "qwen2.5:14b"
LOCAL_KEY, KEY = llm.LOCAL_KEY, llm.KEY
LOCAL_URL_ERROR = "http://10.0.0.5:11434/v1/chat/completions"


@pytest.fixture
def groq(monkeypatch):
    """Groq as it is: main, the second key, the backup."""
    monkeypatch.setenv("GROQ_MODEL", MAIN)
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", BACKUP)
    monkeypatch.setenv("GROQ_API_KEY_2", "test-groq-key-2")


@pytest.fixture
def local(monkeypatch, groq):
    """The local model is set up (no key: the server needs none)."""
    monkeypatch.setenv("LOCAL_LLM_URL", URL)
    monkeypatch.setenv("LOCAL_LLM_MODEL", NAME)


def local_error(status, message):
    response = httpx.Response(status, request=httpx.Request("POST", LOCAL_URL_ERROR))
    kind = openai.InternalServerError if status >= 500 else openai.APIStatusError
    return kind(message, response=response, body=None)


def ids():
    return [entry.id for entry in llm.chain_models()]


# ---------- set up / the chain ----------

def test_the_local_model_exists_only_with_url_and_model(monkeypatch, groq):
    assert "local" not in llm.known_models() and llm.local_model() is None
    monkeypatch.setenv("LOCAL_LLM_URL", URL)
    assert "local" not in llm.known_models()                              # the model name is missing
    monkeypatch.setenv("LOCAL_LLM_MODEL", NAME)
    entry = llm.known_models()["local"]
    assert (entry.id, entry.model, entry.label, entry.key_env, entry.full_request) == (
        "local", NAME, f"Local ({NAME})", LOCAL_KEY, True)
    assert entry.base_url == URL and entry.timeout == 300 and entry.is_local
    monkeypatch.setenv("LOCAL_LLM_LABEL", "Company AI")
    assert llm.known_models()["local"].label == "Company AI"


def test_the_local_model_is_not_in_auto(local):
    assert ids() == ["groq-main", "groq-main-2", "groq-backup"]          # Auto stays Groq
    assert [entry.id for entry in agent.models_in_order()] == ["groq-main", "groq-main-2", "groq-backup"]
    assert [entry.id for entry in llm.choosable_models()] == ["groq-main", "groq-main-2", "groq-backup", "local"]
    assert [entry.id for entry in agent.models_in_order("local")] == ["local"]


def test_listed_in_ai_model_chain_it_takes_its_place(monkeypatch, local):
    monkeypatch.setenv("AI_MODEL_CHAIN", "groq-main,local,groq-backup")
    assert ids() == ["groq-main", "local", "groq-backup"]
    assert [entry.id for entry in llm.choosable_models()] == ["groq-main", "local", "groq-backup"]


def test_the_local_chat_model_has_its_own_address_key_and_timeout(monkeypatch, local):
    chat = llm.make_llm(NAME, agent.SQL_MAX_TOKENS, "medium", key_env=LOCAL_KEY)

    assert chat.openai_api_base == URL and chat.model_name == NAME
    assert chat.openai_api_key.get_secret_value() == llm.LOCAL_DUMMY_KEY  # no key set: a dummy
    assert chat.request_timeout == 300 and chat.max_retries == 0 and chat.temperature == 0
    assert chat.max_tokens == agent.SQL_MAX_TOKENS                       # the full max_tokens
    assert chat.stream_usage is True and chat.use_responses_api is False
    assert chat.extra_body == llm.LOCAL_NO_THINKING                       # none of Groq's own settings; no thinking

    monkeypatch.setenv("LOCAL_LLM_API_KEY", "test-local-key")
    monkeypatch.setenv("LOCAL_LLM_TIMEOUT", "600")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "openai/gpt-oss-20b")           # a gpt-oss name: still no Groq options
    chat = llm.make_llm("openai/gpt-oss-20b", 900, "low", key_env=LOCAL_KEY)
    assert chat.openai_api_key.get_secret_value() == "test-local-key"
    assert chat.request_timeout == 600 and chat.extra_body == llm.LOCAL_NO_THINKING
    for wrong in ("abc", "-5", "0"):
        monkeypatch.setenv("LOCAL_LLM_TIMEOUT", wrong)
        assert llm.local_timeout() == 300


def test_local_thinking_is_off_unless_switched_on(monkeypatch, local):
    """20-Nov: the company's Qwen3.6 thought through all 800 tokens of a SQL request and gave no answer."""
    assert llm.LOCAL_NO_THINKING == {"chat_template_kwargs": {"enable_thinking": False}}
    for value, thinking in (("", False), ("off", False), ("no", False), ("on", True), ("TRUE", True), ("1", True)):
        monkeypatch.setenv("LOCAL_LLM_THINKING", value)
        assert llm.local_thinking() is thinking
        chat = llm.make_llm(NAME, 900, "low", key_env=LOCAL_KEY)
        assert chat.extra_body == (None if thinking else llm.LOCAL_NO_THINKING)


def test_check_local_llm_warns_about_a_url_without_http(monkeypatch, local):
    monkeypatch.setenv("LOCAL_LLM_URL", "10.0.0.5:11434/v1")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "")
    from io import StringIO
    out = StringIO()
    with pytest.raises(CommandError):
        call_command("check_local_llm", stdout=out)
    assert "must start with http://" in out.getvalue() and "LOCAL_LLM_THINKING: off" in out.getvalue()


def test_groqs_chat_model_is_unchanged(monkeypatch, local):
    monkeypatch.setenv(KEY, "test-groq-key-1")
    chat = llm.make_llm(MAIN, agent.ANSWER_MAX_TOKENS, "low")
    assert chat.openai_api_base == llm.GROQ_OPENAI_URL and chat.request_timeout == llm.TIMEOUT_SECS
    assert chat.extra_body == {"reasoning_effort": "low", "include_reasoning": False}


def test_without_the_settings_no_local_chat_model_is_made(monkeypatch, groq):
    with pytest.raises(agent.AIUnavailable) as missing:
        llm.make_llm(NAME, 100, "low", key_env=LOCAL_KEY)
    assert str(missing.value) == llm.LOCAL_MISSING


# ---------- the admin's choice ----------

def test_a_chosen_local_model_answers_alone(monkeypatch, five_notes, user, local):
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])                   # no token usage reported

    result = agent.ask("Top customers in Aug 2026?", user, model="local")

    assert result.status == "ok" and result.answer == ANSWER
    assert fake.models == [NAME, NAME] and fake.keys == [LOCAL_KEY, LOCAL_KEY]   # never Groq
    assert fake.max_tokens == [agent.SQL_MAX_TOKENS, agent.ANSWER_MAX_TOKENS]    # the full request's limits
    assert result.model == NAME and result.model_note == "chosen by you"
    assert result.total_tokens in (None, 0)                               # no usage from the server: no crash
    card = api._card(result.question)
    assert card["model_label"] == f"Local ({NAME})" and card["model_note"] == "chosen by you"
    assert card["backup_model"] == "local"                               # not the main Groq model (older pages)


@pytest.mark.parametrize("errors, message", [
    ([connection_error(), connection_error()], llm.LOCAL_DOWN),
    ([openai.APITimeoutError(request=httpx.Request("POST", LOCAL_URL_ERROR))],
     "The local AI model did not answer within 300 s (LOCAL_LLM_TIMEOUT) - the server may still be busy. "
     "Try again, or raise LOCAL_LLM_TIMEOUT."),
    ([local_error(404, "Error code: 404 - model 'qwen2.5:14b' not found")], llm.LOCAL_NOT_FOUND),
    ([local_error(401, "Error code: 401 - unauthorized")],
     "The local AI server refused the key (401) - check LOCAL_LLM_API_KEY."),
    ([local_error(500, "Error code: 500 - model requires more system memory")],
     "The local AI model returned an error (HTTP 500). Try again, or choose Auto."),
    ([local_error(503, "Error code: 503 - busy")], llm.LOCAL_BUSY),
    ([openai.RateLimitError("Error code: 429 - tokens per day (TPD): too many requests",
                            response=httpx.Response(429, request=httpx.Request("POST", LOCAL_URL_ERROR)),
                            body=None)], llm.LOCAL_BUSY),
], ids=["refused", "timeout", "404", "401", "500", "503", "429"])
def test_a_chosen_local_model_that_fails_gives_a_plain_message_and_no_groq_call(monkeypatch, five_notes, user, local,
                                                                                errors, message, caplog):
    waits = []
    monkeypatch.setattr(agent.time, "sleep", waits.append)
    fake = use_fake_ai(monkeypatch, errors + [GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user, model="local")

    assert fake.keys == [LOCAL_KEY] * len(errors)                         # not Groq, not the backup
    assert result.status == "error" and result.answer == message and result.model == ""
    assert waits == ([3] if len(errors) == 2 else [])                     # a 429: no Groq waiting
    assert "Traceback" not in result.answer
    assert Question.objects.get().answer == message


@pytest.mark.parametrize("text, status", [
    ("Error code: 400 - This model's maximum context length is 8192 tokens. However, you requested 9500 tokens", 400),
    ("Error code: 400 - the request exceeds the available context size, try increasing it", 400),
    ("Error code: 413 - request too large", 413),
], ids=["vllm", "llama.cpp", "413"])
def test_a_context_too_small_says_how_to_fix_it(monkeypatch, five_notes, user, local, text, status):
    fake = use_fake_ai(monkeypatch, [local_error(status, text), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user, model="local")

    assert result.status == "error" and fake.keys == [LOCAL_KEY]
    assert result.answer == ("The local model's context is too small for this question - set its context to at least "
                             "16,000 tokens (e.g. Ollama num_ctx).")


def test_a_chosen_local_model_not_set_up_says_so(monkeypatch, five_notes, user, groq):
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user, model="local")

    assert fake.models == [] and result.status == "error"
    assert result.answer == ("The local AI model is not set up (LOCAL_LLM_URL / LOCAL_LLM_MODEL missing in .env). "
                             "Choose another model, or Auto.")


def test_auto_never_asks_the_local_model(monkeypatch, five_notes, user, local):
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), daily_limit_error(), daily_limit_error(BACKUP)])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "error" and result.answer == agent.AI_DAILY_LIMIT
    assert LOCAL_KEY not in fake.keys and NAME not in fake.models


def test_listed_after_groq_it_answers_when_groq_cannot(monkeypatch, five_notes, user, local):
    monkeypatch.setenv("AI_MODEL_CHAIN", "groq-main,local")
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and fake.keys == [KEY, LOCAL_KEY, LOCAL_KEY]
    assert result.model == NAME
    assert result.model_note == "Groq's daily limit was reached - the local AI model answered"


def test_the_streamed_ask_works_with_the_local_model(monkeypatch, client, mysql, staff, local):
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])
    client.force_login(staff)

    r = client.post(reverse("api_ask_stream"), data=json.dumps({"question": "Top customers in Aug 2026?",
                                                                 "model": "local"}),
                    content_type="application/json")
    lines = [json.loads(line) for line in b"".join(r.streaming_content).decode().splitlines()]

    assert any(line["type"] == "token" for line in lines)
    done = lines[-1]
    assert done["type"] == "done" and done["card"]["status"] == "ok"
    assert done["card"]["model_label"] == f"Local ({NAME})" and done["card"]["model_note"] == "chosen by you"
    assert fake.keys == [LOCAL_KEY, LOCAL_KEY]


def test_a_stream_without_token_usage_counts_none():
    class Chain:
        def stream(self, inputs):
            yield AIMessageChunk(content="Hel")
            yield AIMessageChunk(content="lo")

    shown = []
    message = calls._streamed(Chain(), LcRequest("general", {}), shown.append)

    assert shown == ["Hel", "lo"] and chains.reply_info(message) == ("Hello", None, False)
    calls._log_usage("general", message, NAME)                            # no usage: logged as '?', no crash


def test_the_ai_chart_takes_the_local_choice(monkeypatch, client, staff, local):
    from portal.rag import warehouse
    from portal.tests.test_views_ask import SQL, TABLES
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: TABLES)
    monkeypatch.setattr(warehouse, "run_select", lambda sql: ROWS)
    saved = Question.objects.create(user=staff, text="Top customers?", sql=SQL, answer="A", status="ok",
                                    rows_count=2, model=MAIN)
    option = {"series": [{"type": "pie", "data": [{"name": "Aurora", "value": 1}]}]}
    fake = use_fake_ai(monkeypatch, [json.dumps(option), connection_error(), connection_error()])
    monkeypatch.setattr(agent.time, "sleep", lambda secs: None)
    client.force_login(staff)

    def chart():
        return client.post(reverse("api_chart", args=[saved.pk]), content_type="application/json",
                           data=json.dumps({"kind": "sankey diagram", "model": "local"}))

    r = chart()
    assert r.status_code == 200, r.content
    assert r.json()["model"] == NAME and fake.keys == [LOCAL_KEY]
    down = chart()
    assert down.status_code == 503 and llm.LOCAL_DOWN in down.content.decode()
    assert fake.keys == [LOCAL_KEY] * 3


# ---------- GET /api/models ----------

def models(client, staff):
    client.force_login(staff)
    return {m["id"]: m for m in client.get(reverse("api_models")).json()["models"]}


def test_the_models_list_shows_the_local_model_not_set_up(client, staff, groq):
    assert models(client, staff)["local"] == {
        "id": "local", "label": "Local model", "available": False,
        "note": "LOCAL_LLM_URL / LOCAL_LLM_MODEL not set in .env",
        "hint": "Runs on the company's CPU server - an answer can take a few minutes"}


def test_the_models_list_shows_the_local_model_set_up(monkeypatch, client, staff, local):
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "test-local-key")
    found = models(client, staff)

    assert list(found) == ["auto", "groq-main", "groq-main-2", "groq-backup", "local"]
    assert found["local"] == {"id": "local", "label": f"Local ({NAME})", "available": True, "hint": llm.LOCAL_HINT}
    assert "hint" not in found["groq-main"]
    assert "test-local-key" not in json.dumps(found)

    agent.model_rests("local", 120, "the local AI model could not be reached")
    resting = models(client, staff)["local"]
    assert resting["available"] is False and resting["note"].startswith("resting until ")


# ---------- run_eval --model local ----------

@pytest.fixture
def results_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(run_eval, "current_commit", lambda: "abc1234")
    monkeypatch.setattr("portal.evals.grading.truth_values", lambda sql: [] if isinstance(sql, str) else list(sql or []))
    return tmp_path


def test_run_eval_asks_the_local_model(results_dir, monkeypatch, staff, local, capsys):
    fake = use_fake_ai(monkeypatch, [("Top customers in Sep 2026?", 1_500)])
    chosen, refused = [], []

    def ask_local(question, user, context=None, mode="", model=""):
        chosen.append(model)
        request = LcRequest("rewrite", {"earlier": "1. Q (latest)", "question": question})
        try:
            calls.chat(request, 100, "low", agent.model_name())               # Groq during a local run: refused
        except agent.DailyLimitReached:
            refused.append(question)
        calls.chat(request, 100, "low", NAME, key_env=LOCAL_KEY)
        return agent.AskResult(text=question, status="ok", answer="A", model=NAME)
    monkeypatch.setattr(agent, "ask", ask_local)

    call_command("run_eval", "quick", "--ids", "Q38", "--model", "local")

    assert chosen == ["local"] and len(refused) == 1
    assert fake.keys == [LOCAL_KEY] and fake.models == [NAME]
    assert "the local model uses no Groq tokens - no cap" in capsys.readouterr().out
    assert len(list(results_dir.glob("quick_local_*.json"))) == 1


def test_run_eval_local_not_set_up_is_refused(results_dir, monkeypatch, staff, groq):
    monkeypatch.setattr(agent, "ask", lambda *args, **kwargs: pytest.fail("nothing may be asked"))
    with pytest.raises(CommandError, match="local is not set up"):
        call_command("run_eval", "quick", "--ids", "Q38", "--model", "local")


# ---------- python manage.py check_local_llm ----------

def run_check(*args):
    from io import StringIO
    out = StringIO()
    call_command("check_local_llm", *args, stdout=out)
    return out.getvalue()


def test_check_local_llm_sends_one_tiny_message(monkeypatch, local):
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "test-local-key")
    fake = use_fake_ai(monkeypatch, [("OK", 130)])

    out = run_check()

    assert fake.keys == [LOCAL_KEY] and fake.models == [NAME] and fake.max_tokens == [check_local_llm.MAX_TOKENS]
    assert fake.calls == [[{"role": "user", "content": "Reply with only the word OK."}]]
    assert "LOCAL_LLM_URL:     " + URL in out and "LOCAL_LLM_API_KEY: set" in out
    assert "Reply: 'OK'" in out and "Tokens: prompt 30, reply 100, total 130" in out
    assert "OK - the local model answered in" in out
    assert "test-local-key" not in out                                    # never the key


def test_check_local_llm_without_usage_says_so(monkeypatch, local):
    use_fake_ai(monkeypatch, ["OK"])
    out = run_check()
    assert "Tokens: the server reported none" in out and "not set (a dummy key is sent)" in out


def test_check_local_llm_not_set_up(monkeypatch, groq):
    fake = use_fake_ai(monkeypatch, [])
    with pytest.raises(CommandError) as failed:
        run_check()
    assert str(failed.value) == llm.LOCAL_MISSING and fake.calls == []


@pytest.mark.parametrize("error, text", [
    (connection_error, "could not be reached (LOCAL_LLM_URL) - check that the server is running"),
    (lambda: openai.APITimeoutError(request=httpx.Request("POST", LOCAL_URL_ERROR)), "did not answer within 300 s"),
    (lambda: local_error(404, "Error code: 404 - page not found"), "that LOCAL_LLM_URL ends with /v1"),
], ids=["refused", "timeout", "404"])
def test_check_local_llm_failures_are_plain(monkeypatch, local, error, text):
    use_fake_ai(monkeypatch, [error()])
    with pytest.raises(CommandError) as failed:
        run_check()
    assert text in str(failed.value) and "Traceback" not in str(failed.value)


def test_check_local_llm_lists_the_servers_models(monkeypatch, local):
    use_fake_ai(monkeypatch, ["OK"])
    asked = []
    monkeypatch.setattr(check_local_llm, "list_models",
                        lambda url, key: asked.append((url, key)) or ["qwen2.5:14b", "llama3.1:8b"])

    out = run_check("--models")

    assert asked == [(URL, llm.LOCAL_DUMMY_KEY)]
    assert "Models on the server (2): qwen2.5:14b, llama3.1:8b" in out


def test_the_models_list_reads_openai_and_ollama_replies(monkeypatch):
    replies = iter([{"object": "list", "data": [{"id": "qwen2.5:14b"}]}, {"models": [{"name": "llama3.1:8b"}]}])

    class Reply:
        def __init__(self):
            self.data = next(replies)

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    seen = []
    monkeypatch.setattr(check_local_llm.httpx, "get", lambda url, **kwargs: seen.append(url) or Reply())
    assert check_local_llm.list_models(URL + "/", "k") == ["qwen2.5:14b"]
    assert check_local_llm.list_models(URL, "k") == ["llama3.1:8b"]
    assert seen == [URL + "/models", URL + "/models"]
