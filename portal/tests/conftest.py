"""Shared test helpers (pytest reads this file by itself).

- Three test people: asha (normal user), ravi (another normal user), boss (staff).
  They live in pytest's own empty test database - db.sqlite3 is never touched.
- A safety net: no test may ever reach the real Groq API. The key is removed and the
  Groq client class is swapped for one that fails at once. Tests that need the AI use a fake.
  The same for the LangChain version (portal/lc/), which reaches Groq through the openai library.
"""
import os

import groq
import httpx
import openai
import openai.resources.chat.completions as openai_chat
import pytest


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("asha", password="Test-pass-123")


@pytest.fixture
def other(django_user_model):
    return django_user_model.objects.create_user("ravi", password="Test-pass-123")


@pytest.fixture
def staff(django_user_model):
    return django_user_model.objects.create_user("boss", password="Test-pass-123", is_staff=True)


class _NoRealGroq:
    """Stands in for groq.Groq during tests: making one is a test bug."""

    def __init__(self, *args, **kwargs):
        raise AssertionError("A test tried to call the real Groq API - use a fake client.")


@pytest.fixture(autouse=True)
def fast_passwords(settings):
    """Test people get a quick (weak) password hash - the real one takes ~2 s per user.
    Only inside tests; the real site keeps Django's strong default."""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture(autouse=True)
def no_real_groq(monkeypatch):
    """Runs for every test: no Groq key and no real Groq client."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(groq, "Groq", _NoRealGroq)


def _no_real_openai_call(*args, **kwargs):
    raise AssertionError("A test tried to call the real AI through LangChain (openai) - use a fake chat model.")


@pytest.fixture(autouse=True)
def no_real_langchain_llm(monkeypatch):
    """Runs for every test: a LangChain ChatOpenAI can be made, but its call to the AI fails at once."""
    monkeypatch.setattr(openai_chat.Completions, "create", _no_real_openai_call)
    monkeypatch.setattr(openai_chat.AsyncCompletions, "create", _no_real_openai_call)


@pytest.fixture(autouse=True)
def pipeline(request, monkeypatch):
    """Which version the tests run: classic (default) or, with TEST_PIPELINE=langchain, every test again
    through LangChain - the tests' fake Groq answers through the LangChain chains (fake_langchain_llm), and
    LangChain's search gives what the test's (fake) agent.search gives. USE_LANGCHAIN in .env never decides
    it. test_lc.py tests the LangChain parts on their own and always starts from the classic setting."""
    if os.getenv("TEST_PIPELINE", "").strip().lower() != "langchain" or request.module.__name__.endswith("test_lc"):
        monkeypatch.delenv("USE_LANGCHAIN", raising=False)
        return "classic"
    from portal.lc import llm, vectorstore
    from portal.rag import agent
    monkeypatch.setenv("USE_LANGCHAIN", "on")
    monkeypatch.setattr(vectorstore, "search", lambda text, top_k=5, path=None: agent.search(text, top_k=top_k))
    monkeypatch.setattr(llm, "make_llm", fake_langchain_llm)
    return "langchain"


_ROLES = {"system": "system", "human": "user", "ai": "assistant"}


def as_openai_error(exc):
    """A groq error of a test's fake Groq as the openai error LangChain's ChatOpenAI raises for the same answer."""
    if isinstance(exc, groq.APIStatusError):
        kind = {429: openai.RateLimitError, 413: openai.APIStatusError}.get(exc.status_code)
        kind = kind or (openai.InternalServerError if exc.status_code >= 500 else openai.APIStatusError)
        return kind(exc.message, response=exc.response, body=None)
    if isinstance(exc, groq.APIConnectionError):
        return openai.APIConnectionError(request=httpx.Request("POST", "https://api.groq.com/openai/v1"))
    return exc


def fake_langchain_llm(model, max_tokens, effort):
    """Stands in for portal.lc.llm.make_llm in TEST_PIPELINE=langchain runs: a chat model that sends the
    filled template to the test's fake Groq (agent.get_groq_client()) and gives back its reply as an
    AIMessage with the tokens and the finish reason - like ChatOpenAI does with the real Groq."""
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda
    from portal.rag import agent

    if model == agent.fallback_model_name():
        max_tokens = min(max_tokens, agent.FALLBACK_MAX_TOKENS)
    client = agent.get_groq_client()  # the test's fake (or the missing-key message)

    def call(prompt_value):
        messages = [{"role": _ROLES[m.type], "content": m.content} for m in prompt_value.to_messages()]
        try:
            response = client.chat.completions.create(model=model, messages=messages, temperature=0,
                                                      max_completion_tokens=max_tokens,
                                                      **agent._model_options(model, effort))
        except (groq.APIStatusError, groq.APIConnectionError) as exc:
            raise as_openai_error(exc) from None
        choice, usage = response.choices[0], getattr(response, "usage", None)
        return AIMessage(choice.message.content or "",
                         usage_metadata={"input_tokens": usage.prompt_tokens, "output_tokens": usage.completion_tokens,
                                         "total_tokens": usage.total_tokens} if usage else None,
                         response_metadata={"finish_reason": getattr(choice, "finish_reason", "stop")})
    return RunnableLambda(call)


@pytest.fixture(autouse=True)
def main_model_not_resting(monkeypatch):
    """Every test starts with the main model available (a daily limit in one test must not
    send the next test to the backup model)."""
    from portal.rag import agent
    monkeypatch.setattr(agent, "_main_resting_until", 0.0)


@pytest.fixture(autouse=True, scope="session")
def close_vector_store_clients():
    """At the end of the run, close the Qdrant clients the tests opened (frees their folders)."""
    yield
    from portal.rag import store
    store.close_clients()
