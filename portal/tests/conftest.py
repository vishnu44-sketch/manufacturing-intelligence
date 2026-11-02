"""Shared test helpers (pytest reads this file by itself).

- Three test people: asha (normal user), ravi (another normal user), boss (staff).
  They live in pytest's own empty test database - db.sqlite3 is never touched.
- A safety net: no test may ever reach the real Groq API. The key is removed and the
  Groq client class is swapped for one that fails at once. Tests that need the AI use a fake.
"""
import groq
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
