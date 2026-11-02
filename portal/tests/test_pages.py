"""Step 1 checks: login works, pages need a login, Users is for staff only.
Run with:  python -m pytest -q
(pytest makes its own empty test database - db.sqlite3 is not touched.)"""
import pytest
from django.urls import reverse

from portal.models import Question

pytestmark = pytest.mark.django_db  # every test here may use the test database

# the test people (user = asha, staff = boss) come from conftest.py


def test_login_page_loads(client):
    r = client.get(reverse("login"))
    assert r.status_code == 200
    assert b"Sign in" in r.content
    assert b"portal/app.css" in r.content


@pytest.mark.parametrize("name", ["ask", "history", "users"])
def test_pages_send_a_stranger_to_login(client, name):
    r = client.get(reverse(name))
    assert r.status_code == 302
    assert r.url.startswith(reverse("login"))


def test_home_opens_ask(client):
    r = client.get("/")
    assert r.status_code == 302
    assert r.url == reverse("ask")


def test_sign_in_with_password_goes_to_ask(client, user):
    r = client.post(reverse("login"), {"username": "asha", "password": "Test-pass-123"})
    assert r.status_code == 302
    assert r.url == reverse("ask")


def test_wrong_password_shows_error(client, user):
    r = client.post(reverse("login"), {"username": "asha", "password": "wrong"})
    assert r.status_code == 200
    assert b"did not match" in r.content


def test_signed_in_user_sees_ask_and_history(client, user):
    client.force_login(user)
    r = client.get(reverse("ask"))
    assert r.status_code == 200
    assert b'<textarea id="q" name="question"' in r.content  # the question box
    assert b">Ask</button>" in r.content
    r = client.get(reverse("history"))
    assert r.status_code == 200
    assert b"No questions yet" in r.content


def test_history_shows_only_my_questions(client, user, staff):
    Question.objects.create(user=user, text="My own question", rows_count=3, secs=1.2)
    Question.objects.create(user=staff, text="Somebody else's question")
    client.force_login(user)
    r = client.get(reverse("history"))
    assert b"My own question" in r.content
    assert b"Somebody else" not in r.content


def test_users_page_is_for_staff_only(client, user, staff):
    client.force_login(user)
    r = client.get(reverse("users"))
    assert r.status_code == 403
    assert b'href="/users/"' not in r.content  # no Users menu item either

    client.force_login(staff)
    r = client.get(reverse("users"))
    assert r.status_code == 200
    assert b"asha" in r.content
    assert b"/admin/auth/user/" in r.content


def test_sign_out(client, user):
    client.force_login(user)
    r = client.post(reverse("logout"))
    assert r.status_code == 302
    assert r.url == reverse("login")
    assert client.get(reverse("ask")).status_code == 302  # signed out again


def test_ask_nop_uses_its_own_cookie_names(client, user):
    """13-Oct: the main NOP project on 127.0.0.1:8080 also sets 'csrftoken' / 'sessionid' - the browser
    shares them between ports, so Ask NOP's questions got 403 "CSRF token incorrect"."""
    r = client.get(reverse("login"))
    assert "asknop_csrftoken" in r.cookies and "csrftoken" not in r.cookies
    r = client.post(reverse("login"), {"username": "asha", "password": "Test-pass-123"})
    assert "asknop_sessionid" in r.cookies and "sessionid" not in r.cookies
