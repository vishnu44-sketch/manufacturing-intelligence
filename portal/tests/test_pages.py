"""Step 1 checks, now for the React website: every address opens the React page, signing in and out
works through the API, every API address needs a sign-in (401), the staff pages are for staff only
(403), and the app uses its own cookie names.
Run with:  python -m pytest -q
(pytest makes its own empty test database - db.sqlite3 is not touched.)"""
import pytest
from django.conf import settings
from django.urls import reverse

from portal import views
from portal.models import Question
from portal.tests.test_views_ask import api_get, api_post, history

pytestmark = pytest.mark.django_db  # every test here may use the test database

# the test people (user = asha, staff = boss) come from conftest.py
REACT_HTML = "<!doctype html><title>Manufacturing Intelligence</title><div id=root></div>"


@pytest.fixture
def react_build(tmp_path, monkeypatch):
    """A built React page (index.html) in a test folder."""
    index = tmp_path / "index.html"
    index.write_text(REACT_HTML, encoding="utf-8")
    monkeypatch.setattr(views, "REACT_INDEX", index)
    return index


@pytest.mark.parametrize("url", ["/", "/login", "/new", "/c/12", "/q/7", "/history", "/history/", "/users",
                                 "/documents", "/data", "/ask/", "/ask/c/3/", "/something-else"])
def test_every_website_address_opens_the_react_page(client, react_build, url):
    r = client.get(url)

    assert r.status_code == 200, url
    assert r.content.decode() == REACT_HTML, url
    assert settings.CSRF_COOKIE_NAME in r.cookies                         # for the app's first POST


def test_the_react_page_is_the_same_for_a_stranger_and_a_signed_in_user(client, user, react_build):
    """The page holds no data: the app asks /api/me and shows its sign-in on a 401."""
    stranger = client.get("/history").content
    client.force_login(user)

    assert client.get("/history").content == stranger


def test_without_a_build_the_page_says_how_to_make_it(client, tmp_path, monkeypatch):
    monkeypatch.setattr(views, "REACT_INDEX", tmp_path / "missing.html")

    r = client.get("/")

    assert r.status_code == 503 and b"npm run build" in r.content


def test_the_admin_keeps_its_own_sign_in(client, react_build):
    r = client.get("/admin/")

    assert r.status_code == 302 and r.url.startswith("/admin/login/")
    page = client.get(r.url)
    assert page.status_code == 200 and b'id="login-form"' in page.content and REACT_HTML.encode() not in page.content


def test_api_addresses_never_fall_through_to_the_react_page(client, react_build):
    for url in ("/api/nothing-here", "/api/", "/api"):
        r = client.get(url)
        assert r.status_code == 404 and r.json() == {"detail": "Not found."}, url


def test_a_sign_in_redirect_goes_to_the_react_sign_in():
    assert settings.LOGIN_URL == "/login" and settings.LOGIN_REDIRECT_URL == "/"


@pytest.mark.parametrize("name", ["api_me", "api_chats", "api_history", "api_users", "api_documents", "api_data"])
def test_the_api_sends_a_stranger_to_sign_in(client, name):
    r = api_get(client, name)
    assert r.status_code == 401
    assert r.json() == {"detail": "Please sign in."}


def test_sign_in_with_password(client, user):
    r = api_post(client, "api_login", {"username": "asha", "password": "Test-pass-123"})
    assert r.status_code == 200
    assert r.json()["username"] == "asha"
    assert api_get(client, "api_me").status_code == 200


def test_wrong_password_shows_error(client, user):
    r = api_post(client, "api_login", {"username": "asha", "password": "wrong"})
    assert r.status_code == 400
    assert "did not match" in r.json()["detail"]


def test_a_switched_off_person_cannot_sign_in(client, user):
    user.is_active = False
    user.save()

    r = api_post(client, "api_login", {"username": "asha", "password": "Test-pass-123"})

    assert r.status_code == 400 and "did not match" in r.json()["detail"]


def test_a_new_user_has_an_empty_history(client, user):
    client.force_login(user)

    body = history(client)

    assert body["questions"] == [] and body["count"] == 0                 # "No questions yet"


def test_history_shows_only_my_questions(client, user, staff):
    Question.objects.create(user=user, text="My own question", rows_count=3, secs=1.2)
    Question.objects.create(user=staff, text="Somebody else's question")
    client.force_login(user)

    texts = [q["text"] for q in history(client)["questions"]]

    assert texts == ["My own question"]


@pytest.mark.parametrize("name", ["api_users", "api_documents", "api_data"])
def test_staff_pages_are_for_staff_only(client, user, name):
    client.force_login(user)

    r = api_get(client, name)

    assert r.status_code == 403
    assert "Only administrators" in r.json()["detail"]
    assert api_get(client, "api_me").json()["is_staff"] is False           # the app hides their menu items


def test_staff_sees_the_users(client, user, staff):
    client.force_login(staff)

    r = api_get(client, "api_users")

    assert r.status_code == 200
    assert "asha" in [p["username"] for p in r.json()["people"]]
    assert r.json()["admin_url"] == reverse("admin:auth_user_changelist")
    assert api_get(client, "api_me").json()["is_staff"] is True


def test_sign_out(client, user):
    client.force_login(user)
    r = api_post(client, "api_logout")
    assert r.status_code == 200
    assert api_get(client, "api_me").status_code == 401                  # signed out again


def test_ask_nop_uses_its_own_cookie_names(client, user):
    """13-Oct: the main NOP project on 127.0.0.1:8080 also sets 'csrftoken' / 'sessionid' - the browser
    shares them between ports, so Ask NOP's questions got 403 "CSRF token incorrect"."""
    r = api_get(client, "api_csrf")
    assert "asknop_csrftoken" in r.cookies and "csrftoken" not in r.cookies
    r = api_post(client, "api_login", {"username": "asha", "password": "Test-pass-123"})
    assert "asknop_sessionid" in r.cookies and "sessionid" not in r.cookies
