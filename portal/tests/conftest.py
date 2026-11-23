"""Shared test helpers (pytest reads this file by itself).

- Three test people: asha (normal user), ravi (another normal user), boss (staff).
  They live in pytest's own empty test database - db.sqlite3 is never touched.
- A safety net: no test may ever reach the real Groq API. The key is removed, and the openai
  library's chat call (what LangChain's ChatOpenAI uses to reach Groq) fails at once.
  Tests that need the AI use a fake chat model (test_agent.FakeAI, installed as portal.lc.llm.make_llm).
"""
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


@pytest.fixture(autouse=True)
def fast_passwords(settings):
    """Test people get a quick (weak) password hash - the real one takes ~2 s per user.
    Only inside tests; the real site keeps Django's strong default."""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture(autouse=True)
def no_groq_key(monkeypatch):
    """Runs for every test: no Groq key (a real chat model cannot even be made), and no second Groq key - so the
    model chain is the Groq main model and the backup; a test of the chain sets its own (test_model_chain.py,
    19-Nov). The chain's order comes from the test, never from .env. 20-Nov: no local model either (LOCAL_LLM_*) -
    test_local_model.py sets its own."""
    for name in ("GROQ_API_KEY", "GROQ_API_KEY_2", "AI_MODEL_CHAIN", "LOCAL_LLM_URL", "LOCAL_LLM_MODEL",
                 "LOCAL_LLM_API_KEY", "LOCAL_LLM_TIMEOUT", "LOCAL_LLM_LABEL"):
        monkeypatch.delenv(name, raising=False)


def _no_real_openai_call(*args, **kwargs):
    raise AssertionError("A test tried to call the real AI through LangChain (openai) - use a fake chat model.")


@pytest.fixture(autouse=True)
def no_real_langchain_llm(monkeypatch):
    """Runs for every test: a LangChain ChatOpenAI can be made (with a test key), but its call to the AI fails at once."""
    monkeypatch.setattr(openai_chat.Completions, "create", _no_real_openai_call)
    monkeypatch.setattr(openai_chat.AsyncCompletions, "create", _no_real_openai_call)


@pytest.fixture(autouse=True)
def main_model_not_resting(monkeypatch):
    """Every test starts with every model available (a daily limit in one test must not
    send the next test to the backup model)."""
    from portal.rag import agent
    monkeypatch.setattr(agent, "_resting", {})


@pytest.fixture(autouse=True)
def no_pdf_hits(monkeypatch):
    """Every test starts with an empty PDF search: the router sends each question to the data with NO AI call,
    so the fake AI's reply queues of the data tests stay as they were (one reply per SQL / answer call).
    A router test opts in by setting agent.search_pdfs again (test_agent.use_pdf_hits)."""
    from portal.rag import agent
    monkeypatch.setattr(agent, "search_pdfs", lambda question, k=agent.PDF_TOP_K: [])


@pytest.fixture(autouse=True)
def demo_data_is_over(monkeypatch):
    """Every test's "today" (agent.today) is after the demo data (up to 20-Mar-2027), so the fake AI's FY 2026-27
    SQL is a finished year and is not sent back as "not over yet". The tests of that check set their own day."""
    import datetime
    from portal.rag import agent
    monkeypatch.setattr(agent, "today", lambda: datetime.date(2027, 6, 1))


@pytest.fixture(autouse=True, scope="session")
def close_vector_store_clients():
    """At the end of the run, close the Qdrant clients the tests opened (frees their folders)."""
    yield
    from portal.rag import store
    store.close_clients()
