"""The Users page's API (/api/users...): staff see everyone; adding, changing, switching off and
setting a password follow the admin's rules (its 'add user' / 'change user' permissions, its forms
and the password rules of settings), plus: only a superuser touches a superuser or who is staff,
nobody switches himself off, and no password or hash ever leaves the server.
Run with:  python -m pytest -q portal/tests/test_users.py
"""
import pytest
from django.contrib.auth.models import Permission

from portal.tests.test_views_ask import api_get, api_post

pytestmark = pytest.mark.django_db

GOOD = "Plant-visit-2026!"


@pytest.fixture
def root(django_user_model):
    return django_user_model.objects.create_superuser("root", password="Test-pass-123")


@pytest.fixture
def manager(django_user_model):
    """Staff with the admin's 'add user' and 'change user' permissions (not a superuser)."""
    person = django_user_model.objects.create_user("meera", password="Test-pass-123", is_staff=True)
    person.user_permissions.add(*Permission.objects.filter(codename__in=["add_user", "change_user"]))
    return django_user_model.objects.get(pk=person.pk)  # fresh: no permission cache


def add(client, **fields):
    data = {"username": "kiran", "first_name": "Kiran", "last_name": "Rao", "email": "kiran@example.com",
            "password1": GOOD, "password2": GOOD, **fields}
    return api_post(client, "api_users", data)


# ---------- the list ----------

def test_staff_see_everyone_without_any_password(client, user, staff, root):
    client.force_login(staff)

    r = api_get(client, "api_users")

    body = r.json()
    people = {p["username"]: p for p in body["people"]}
    assert [name for name in people if name in ("asha", "boss", "root")] == ["asha", "boss", "root"]   # by sign-in name
    assert people["boss"]["is_me"] is True and people["asha"]["is_me"] is False
    assert people["root"]["is_superuser"] and people["boss"]["is_staff"] and not people["asha"]["is_staff"]
    assert people["asha"]["is_active"] and people["asha"]["last_login"] == ""          # never signed in
    assert "password" not in r.content.decode() and "md5$" not in r.content.decode()
    assert (body["can_add"], body["can_change"], body["can_set_roles"]) == (False, False, False)


def test_the_list_says_what_a_superuser_may_do(client, root):
    client.force_login(root)

    body = api_get(client, "api_users").json()

    assert (body["can_add"], body["can_change"], body["can_set_roles"]) == (True, True, True)


def test_normal_users_and_strangers_get_nothing(client, user):
    assert api_get(client, "api_users").status_code == 401
    client.force_login(user)
    for r in (api_get(client, "api_users"), add(client), api_post(client, "api_user_active", {"active": False}, user.pk)):
        assert r.status_code == 403


# ---------- adding a person ----------

def test_a_superuser_adds_a_person_who_can_sign_in(client, root, django_user_model):
    client.force_login(root)

    r = add(client, is_staff=True)

    assert r.status_code == 200 and r.json()["message"] == '"kiran" can now sign in.'
    person = django_user_model.objects.get(username="kiran")
    assert (person.first_name, person.email, person.is_staff, person.is_superuser) == ("Kiran", "kiran@example.com", True, False)
    assert person.check_password(GOOD)
    assert "password" not in r.content.decode()
    client.logout()
    assert api_post(client, "api_login", {"username": "kiran", "password": GOOD}).status_code == 200


def test_staff_without_the_add_permission_cannot_add(client, staff, django_user_model):
    client.force_login(staff)

    r = add(client)

    assert r.status_code == 403 and "permission" in r.json()["detail"]
    assert not django_user_model.objects.filter(username="kiran").exists()


def test_staff_with_the_add_permission_adds_a_normal_user_only(client, manager, django_user_model):
    client.force_login(manager)

    assert add(client, is_staff=True).status_code == 403                   # no admins made by non-superusers
    assert add(client, is_superuser=True).status_code == 403
    assert add(client).status_code == 200
    assert not django_user_model.objects.get(username="kiran").is_staff


@pytest.mark.parametrize("fields, field, words", [
    ({"username": "asha"}, "username", "already exists"),                   # taken (any case)
    ({"username": "ASHA"}, "username", "already exists"),
    ({"username": "bad name!"}, "username", "valid username"),
    ({"username": ""}, "username", "required"),
    ({"password2": "Other-pass-2026!"}, "password2", "didn"),               # the two passwords differ
    ({"password1": "12345678", "password2": "12345678"}, "password2", "entirely numeric"),
    ({"password1": "short", "password2": "short"}, "password2", "too short"),
    ({"password1": "password", "password2": "password"}, "password2", "too common"),
    ({"email": "not-an-email"}, "email", "valid email"),
])
def test_adding_checks_the_fields_like_the_admin(client, root, user, django_user_model, fields, field, words):
    client.force_login(root)
    before = django_user_model.objects.count()

    r = add(client, **fields)

    assert r.status_code == 400 and r.json()["detail"] == "Please correct the marked fields."
    assert any(words in message for message in r.json()["errors"][field]), r.json()["errors"]
    assert django_user_model.objects.count() == before                     # nobody was added


# ---------- changing a person ----------

def test_a_superuser_changes_the_details_and_roles(client, root, user):
    client.force_login(root)

    r = api_post(client, "api_user", {"first_name": "Asha", "last_name": "Iyer", "email": "asha@example.com",
                                       "is_staff": True}, user.pk)

    user.refresh_from_db()
    assert r.status_code == 200 and r.json()["person"]["name"] == "Asha Iyer"
    assert (user.first_name, user.email, user.is_staff, user.username) == ("Asha", "asha@example.com", True, "asha")


def test_changing_needs_the_change_permission(client, staff, user):
    client.force_login(staff)

    r = api_post(client, "api_user", {"first_name": "Hacked"}, user.pk)

    assert r.status_code == 403
    user.refresh_from_db()
    assert user.first_name == ""


def test_a_non_superuser_cannot_change_roles_or_a_superuser(client, manager, user, root):
    client.force_login(manager)

    assert api_post(client, "api_user", {"first_name": "Asha"}, user.pk).status_code == 200
    assert api_post(client, "api_user", {"is_staff": True}, user.pk).status_code == 403
    assert api_post(client, "api_user", {"first_name": "Hacked"}, root.pk).status_code == 403
    assert api_post(client, "api_user_active", {"active": False}, root.pk).status_code == 403
    assert api_post(client, "api_user_password", {"password1": GOOD, "password2": GOOD}, root.pk).status_code == 403
    user.refresh_from_db(); root.refresh_from_db()
    assert not user.is_staff and root.first_name == "" and root.is_active and root.check_password("Test-pass-123")


def test_a_sign_in_name_must_stay_unique(client, root, user, other):
    client.force_login(root)

    r = api_post(client, "api_user", {"username": "ravi"}, user.pk)

    assert r.status_code == 400 and "already exists" in r.json()["errors"]["username"][0]


def test_an_unknown_person_is_not_found(client, root):
    client.force_login(root)

    assert api_post(client, "api_user", {"first_name": "X"}, 99999).status_code == 404
    assert api_post(client, "api_user_active", {"active": True}, 99999).status_code == 404


# ---------- switching off / on ----------

def test_switching_a_person_off_stops_the_sign_in_and_on_again_allows_it(client, root, user):
    client.force_login(root)

    off = api_post(client, "api_user_active", {"active": False}, user.pk)
    user.refresh_from_db()
    assert off.status_code == 200 and not user.is_active
    assert off.json()["message"] == '"asha" is switched off and cannot sign in.'

    on = api_post(client, "api_user_active", {"active": True}, user.pk)
    user.refresh_from_db()
    assert on.status_code == 200 and user.is_active


def test_nobody_switches_himself_off_or_takes_away_his_own_rights(client, root):
    client.force_login(root)

    assert api_post(client, "api_user_active", {"active": False}, root.pk).status_code == 400
    assert api_post(client, "api_user", {"is_superuser": False}, root.pk).status_code == 400
    root.refresh_from_db()
    assert root.is_active and root.is_superuser


def test_active_needs_a_yes_or_no(client, root, user):
    client.force_login(root)

    assert api_post(client, "api_user_active", {"active": "no"}, user.pk).status_code == 400
    user.refresh_from_db()
    assert user.is_active


# ---------- a new password ----------

def test_a_new_password_follows_the_password_rules(client, root, user):
    client.force_login(root)

    weak = api_post(client, "api_user_password", {"password1": "1234567890", "password2": "1234567890"}, user.pk)
    differ = api_post(client, "api_user_password", {"password1": GOOD, "password2": GOOD + "x"}, user.pk)
    ok = api_post(client, "api_user_password", {"password1": GOOD, "password2": GOOD}, user.pk)

    assert weak.status_code == 400 and weak.json()["errors"]["password2"]
    assert differ.status_code == 400 and "didn" in differ.json()["errors"]["password2"][0]
    assert ok.status_code == 200 and ok.json()["message"] == 'The password of "asha" was changed.'
    user.refresh_from_db()
    assert user.check_password(GOOD)
    assert GOOD not in ok.content.decode() and "password" not in ok.json()["person"]


def test_changing_my_own_password_keeps_me_signed_in(client, root):
    client.force_login(root)

    api_post(client, "api_user_password", {"password1": GOOD, "password2": GOOD}, root.pk)

    assert api_get(client, "api_me").status_code == 200
