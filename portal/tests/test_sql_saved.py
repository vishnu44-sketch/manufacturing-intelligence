"""Saved queries of the SQL page (/api/sql/saved, /api/sql/saved/<id>, /api/sql/saved/<id>/delete): staff only,
kept as text in the app's own database. Saving never runs the SQL and never checks it with the guard; only the
owner changes or deletes a query; a shared one is seen by the other administrators. No AI call, no MySQL.
Run with:  python -m pytest portal/tests/test_sql_saved.py -q"""
import datetime
import json

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from portal import sql_page
from portal.models import AuditLog, SavedQuery
from portal.rag import warehouse
from portal.tests.test_views_ask import api_get, api_post

pytestmark = pytest.mark.django_db

SELECT = "SELECT customer_id, customer_name FROM dim_customers WHERE customer_id = 16"
Q_KEYS = {"id", "name", "sql", "shared", "owner", "owner_name", "updated_at", "updated_text", "mine"}


@pytest.fixture(autouse=True)
def no_warehouse(monkeypatch):
    """Saving is only text: any call to MySQL (the guard's table list or a SELECT) fails the test."""
    def never(*args, **kwargs):
        raise AssertionError("A saved query reached the warehouse.")

    for name in ("allowed_tables", "run_select", "run_select_params"):
        monkeypatch.setattr(warehouse, name, never)


@pytest.fixture
def staff2(django_user_model):
    return django_user_model.objects.create_user("meena", password="Test-pass-123", is_staff=True,
                                                 first_name="Meena")


def save(client, name="Top customers", sql=SELECT, **extra):
    return api_post(client, "api_sql_saved", {"name": name, "sql": sql, **extra})


def change(client, query_id, **fields):
    return api_post(client, "api_sql_saved_change", fields, query_id)


def delete(client, query_id):
    return api_post(client, "api_sql_saved_delete", {}, query_id)


def listed(client):
    r = api_get(client, "api_sql_saved")
    assert r.status_code == 200
    return r.json()


def lines(action):
    return list(AuditLog.objects.filter(action=action).order_by("pk"))


# ------------------------------------------------------------------ who may use it
def test_signed_out_gets_401_everywhere(client, staff):
    query = SavedQuery.objects.create(owner=staff, name="Mine", sql=SELECT)
    for r in (api_get(client, "api_sql_saved"), save(client), change(client, query.pk, name="x"),
              delete(client, query.pk)):
        assert r.status_code == 401 and r.json() == {"detail": "Please sign in."}
    assert SavedQuery.objects.get().name == "Mine"


def test_a_normal_user_gets_403_everywhere(client, user, staff):
    query = SavedQuery.objects.create(owner=staff, name="Mine", sql=SELECT, shared=True)
    client.force_login(user)
    for r in (api_get(client, "api_sql_saved"), save(client), change(client, query.pk, name="x"),
              delete(client, query.pk)):
        assert r.status_code == 403 and "Only administrators" in r.json()["detail"]
    assert SavedQuery.objects.count() == 1 and SavedQuery.objects.get().name == "Mine"
    assert AuditLog.objects.filter(action__startswith="sql_saved").count() == 0


def test_a_post_needs_the_csrf_token(staff):
    client = Client(enforce_csrf_checks=True)
    client.force_login(staff)
    query = SavedQuery.objects.create(owner=staff, name="Mine", sql=SELECT)
    for name, args in (("api_sql_saved", []), ("api_sql_saved_change", [query.pk]),
                       ("api_sql_saved_delete", [query.pk])):
        r = client.post(reverse(name, args=args), data=json.dumps({"name": "New", "sql": SELECT}),
                        content_type="application/json")
        assert r.status_code == 403 and "CSRF" in r.json()["detail"], name
    assert SavedQuery.objects.count() == 1 and SavedQuery.objects.get().name == "Mine"
    assert client.get(reverse("api_sql_saved")).status_code == 200   # the list needs no token

    token = client.get(reverse("api_csrf")).json()["csrfToken"]
    r = client.post(reverse("api_sql_saved"), data=json.dumps({"name": "New", "sql": SELECT}),
                    content_type="application/json", HTTP_X_CSRFTOKEN=token)
    assert r.status_code == 201


def test_only_the_right_methods(client, staff):
    client.force_login(staff)
    query = SavedQuery.objects.create(owner=staff, name="Mine", sql=SELECT)
    assert api_get(client, "api_sql_saved_change", query.pk).status_code == 405
    assert api_get(client, "api_sql_saved_delete", query.pk).status_code == 405
    assert client.delete(reverse("api_sql_saved")).status_code == 405


# ------------------------------------------------------------------ the owner's own queries
def test_staff_saves_a_query_and_gets_the_contract_shape(client, staff):
    client.force_login(staff)
    r = save(client, name="  Top   customers  ", sql=SELECT + "\n")
    assert r.status_code == 201
    query = r.json()["query"]
    assert set(r.json()) == {"query"} and set(query) == Q_KEYS
    saved = SavedQuery.objects.get()
    assert query["id"] == saved.pk and saved.owner == staff
    assert query["name"] == "Top customers"           # trimmed, spaces tidied
    assert query["sql"] == SELECT + "\n"               # the SQL is kept as typed
    assert query["shared"] is False and query["mine"] is True
    assert query["owner"] == "boss" and query["owner_name"] == "boss"   # no first name: the user name
    assert query["updated_at"] == timezone.localtime(saved.updated_at).isoformat()
    assert query["updated_at"].endswith("+05:30")       # India time
    assert query["updated_text"] == timezone.localtime(saved.updated_at).strftime("%d %b %Y %I:%M %p")


def test_the_list_has_mine_newest_change_first_and_shared(client, staff, staff2):
    old = SavedQuery.objects.create(owner=staff, name="Old", sql=SELECT)
    new = SavedQuery.objects.create(owner=staff, name="New", sql=SELECT, shared=True)
    SavedQuery.objects.filter(pk=old.pk).update(updated_at=timezone.now() - datetime.timedelta(days=2))
    SavedQuery.objects.create(owner=staff2, name="Meena private", sql=SELECT)
    hers = SavedQuery.objects.create(owner=staff2, name="Meena shared", sql="SELECT 1")
    hers.shared = True
    hers.save()
    client.force_login(staff)
    body = listed(client)
    assert set(body) == {"mine", "shared"}
    assert [q["name"] for q in body["mine"]] == ["New", "Old"]   # own ones, shared or not
    assert [q["id"] for q in body["mine"]] == [new.pk, old.pk]
    assert [q["name"] for q in body["shared"]] == ["Meena shared"]
    other = body["shared"][0]
    assert set(other) == Q_KEYS
    assert other == {**other, "owner": "meena", "owner_name": "Meena", "mine": False, "shared": True,
                     "sql": "SELECT 1", "id": hers.pk}
    assert all(q["mine"] is True for q in body["mine"])


def test_the_owner_renames_changes_shares_and_deletes(client, staff):
    client.force_login(staff)
    number = save(client).json()["query"]["id"]

    r = change(client, number, name="Customer 16")
    assert r.status_code == 200 and r.json()["query"]["name"] == "Customer 16"
    r = change(client, number, sql="SELECT 2")
    assert r.status_code == 200 and r.json()["query"]["sql"] == "SELECT 2"
    assert r.json()["query"]["name"] == "Customer 16"              # what was not sent stays
    r = change(client, number, shared=True)
    assert r.status_code == 200 and r.json()["query"]["shared"] is True
    r = change(client, number, shared=False)
    assert r.status_code == 200 and r.json()["query"]["shared"] is False
    r = change(client, number, name="customer 16")                 # its own name in another case is fine
    assert r.status_code == 200 and SavedQuery.objects.get().name == "customer 16"
    assert set(r.json()) == {"query"} and set(r.json()["query"]) == Q_KEYS

    r = delete(client, number)
    assert r.status_code == 200 and r.json() == {"deleted": number}
    assert not SavedQuery.objects.exists()
    assert listed(client) == {"mine": [], "shared": []}


def test_a_missing_query_is_404(client, staff):
    client.force_login(staff)
    for r in (change(client, 999, name="x"), delete(client, 999)):
        assert r.status_code == 404 and r.json() == {"detail": "Not found."}


# ------------------------------------------------------------------ another administrator
def test_another_admin_sees_it_only_when_shared(client, staff, staff2):
    client.force_login(staff)
    number = save(client).json()["query"]["id"]
    client.force_login(staff2)
    assert listed(client) == {"mine": [], "shared": []}
    # a private query of someone else is not even shown to exist
    assert change(client, number, name="x").status_code == 404
    assert delete(client, number).status_code == 404

    client.force_login(staff)
    change(client, number, shared=True)
    client.force_login(staff2)
    body = listed(client)
    assert body["mine"] == [] and [q["id"] for q in body["shared"]] == [number]
    assert body["shared"][0]["mine"] is False and body["shared"][0]["owner"] == "boss"

    client.force_login(staff)
    change(client, number, shared=False)                           # made private again
    client.force_login(staff2)
    assert listed(client)["shared"] == []


def test_another_admin_cannot_change_or_delete_a_shared_query(client, staff, staff2):
    staff.first_name = "Vikram"
    staff.save()
    query = SavedQuery.objects.create(owner=staff, name="Shared one", sql=SELECT, shared=True)
    client.force_login(staff2)
    for fields in ({"name": "Mine now"}, {"sql": "SELECT 3"}, {"shared": False}):
        r = change(client, query.pk, **fields)
        assert r.status_code == 403
        assert r.json() == {"detail": "Only Vikram can change this query - use Save as to keep your own copy."}
    r = delete(client, query.pk)
    assert r.status_code == 403 and r.json() == {"detail": "Only Vikram can delete this query."}
    query.refresh_from_db()
    assert (query.name, query.sql, query.shared) == ("Shared one", SELECT, True)
    assert AuditLog.objects.filter(action__startswith="sql_saved").count() == 0

    # "Save as": the other admin keeps his own copy, even with the same name
    r = save(client, name="Shared one", sql=query.sql)
    assert r.status_code == 201 and r.json()["query"]["owner"] == "meena"


def test_a_former_admins_shared_query_is_not_listed(client, staff, staff2):
    SavedQuery.objects.create(owner=staff2, name="Hers", sql=SELECT, shared=True)
    staff2.is_staff = False
    staff2.save()
    client.force_login(staff)
    assert listed(client)["shared"] == []


# ------------------------------------------------------------------ the checks of the text
@pytest.mark.parametrize("name", ["", "   ", None, 5])
def test_a_name_is_needed(client, staff, name):
    client.force_login(staff)
    r = api_post(client, "api_sql_saved", {"name": name, "sql": SELECT})
    assert r.status_code == 400 and r.json() == {"detail": "Give the query a name."}
    r = api_post(client, "api_sql_saved", {"sql": SELECT})
    assert r.status_code == 400 and r.json() == {"detail": "Give the query a name."}
    assert not SavedQuery.objects.exists()


def test_a_name_of_at_most_120_characters(client, staff):
    client.force_login(staff)
    r = save(client, name="n" * 121)
    assert r.status_code == 400 and r.json() == {"detail": "Please keep the name to 120 characters or fewer."}
    assert save(client, name="n" * 120).status_code == 201
    number = SavedQuery.objects.get().pk
    assert change(client, number, name="m" * 121).status_code == 400
    assert change(client, number, name="  ").status_code == 400
    assert SavedQuery.objects.get().name == "n" * 120


def test_a_name_is_unique_per_owner_whatever_the_case(client, staff, staff2):
    client.force_login(staff)
    assert save(client, name="Top customers").status_code == 201
    r = save(client, name="TOP  Customers ")
    assert r.status_code == 400
    assert r.json() == {"detail": 'You already have a saved query named "TOP Customers" - pick another name.'}
    other = save(client, name="Other").json()["query"]["id"]
    r = change(client, other, name="top customers")                # renaming onto another of his own
    assert r.status_code == 400 and "already have a saved query" in r.json()["detail"]
    assert SavedQuery.objects.filter(owner=staff).count() == 2

    client.force_login(staff2)                                     # another owner may use the same name
    assert save(client, name="Top customers").status_code == 201


@pytest.mark.parametrize("sql", ["", "  \n ", None, 7])
def test_the_sql_is_needed(client, staff, sql):
    client.force_login(staff)
    r = api_post(client, "api_sql_saved", {"name": "Empty", "sql": sql})
    assert r.status_code == 400 and r.json() == {"detail": "Type the SQL to save first."}
    assert not SavedQuery.objects.exists()


def test_the_sql_of_at_most_20000_characters(client, staff):
    client.force_login(staff)
    too_long = "SELECT 1 " + "x" * sql_page.MAX_SQL_CHARS
    r = save(client, sql=too_long)
    assert r.status_code == 400 and r.json() == {"detail": "Please keep the SQL under 20,000 characters."}
    exact = "S" * sql_page.MAX_SQL_CHARS
    assert save(client, sql=exact).status_code == 201
    number = SavedQuery.objects.get().pk
    assert change(client, number, sql=too_long).status_code == 400
    assert change(client, number, sql="").status_code == 400
    assert SavedQuery.objects.get().sql == exact


def test_wrong_json_is_400(client, staff):
    client.force_login(staff)
    r = client.post(reverse("api_sql_saved"), data="not json", content_type="application/json")
    assert r.status_code == 400 and "JSON" in r.json()["detail"]
    r = client.post(reverse("api_sql_saved"), data="[1, 2]", content_type="application/json")
    assert r.status_code == 400
    r = save(client, shared="yes")
    assert r.status_code == 400 and r.json() == {"detail": "shared must be true or false."}
    number = save(client).json()["query"]["id"]
    r = client.post(reverse("api_sql_saved_change", args=[number]), data="nope", content_type="application/json")
    assert r.status_code == 400 and "JSON" in r.json()["detail"]
    r = change(client, number)
    assert r.status_code == 400 and r.json() == {"detail": "Send the name, the SQL or shared to change."}
    assert change(client, number, shared=1).status_code == 400


def test_at_most_200_saved_queries(client, staff, staff2):
    SavedQuery.objects.bulk_create([SavedQuery(owner=staff, name=f"Query {n}", sql=SELECT)
                                    for n in range(SavedQuery.MAX_PER_USER)])
    client.force_login(staff)
    r = save(client, name="One more")
    assert r.status_code == 400
    assert r.json() == {"detail": "You can keep at most 200 saved queries - delete some you no longer need first."}
    assert SavedQuery.objects.filter(owner=staff).count() == 200
    assert len(listed(client)["mine"]) == 200
    client.force_login(staff2)                                     # the limit is per person
    assert save(client, name="One more").status_code == 201


def test_saving_never_runs_or_checks_the_sql(client, staff):
    """Not even a DROP is refused - it is only text here (the guard refuses it when someone presses Run)."""
    client.force_login(staff)
    r = save(client, name="Bad one", sql="DROP TABLE dim_customers")
    assert r.status_code == 201 and r.json()["query"]["sql"] == "DROP TABLE dim_customers"
    number = r.json()["query"]["id"]
    assert change(client, number, sql="SELECT * FROM mi_app.auth_user").status_code == 200
    assert listed(client)["mine"][0]["sql"] == "SELECT * FROM mi_app.auth_user"
    assert AuditLog.objects.filter(action__in=["sql_run", "sql_excel"]).count() == 0   # (no_warehouse: no MySQL)


# ------------------------------------------------------------------ the audit log
def test_one_audit_line_per_create_change_share_and_delete(client, staff):
    client.force_login(staff)
    number = save(client, name="Top customers").json()["query"]["id"]
    change(client, number, name="Customer 16")
    change(client, number, sql="SELECT 2")
    change(client, number, shared=True)
    change(client, number, shared=True)                            # nothing changed: no line
    change(client, number, name="Customer 17", shared=False)       # both: one line each
    delete(client, number)

    saved, = lines("sql_saved")
    assert saved.username == "boss" and saved.target == "Top customers"
    assert saved.details == {"id": number, "shared": False, "sql": SELECT}
    renamed, new_sql, both = lines("sql_saved_changed")
    assert renamed.target == "Customer 16" and renamed.details["old_name"] == "Top customers"
    assert renamed.details["sql"] == SELECT and renamed.details["id"] == number
    assert new_sql.details == {"id": number, "shared": False, "sql": "SELECT 2"}
    assert both.details["old_name"] == "Customer 16" and both.target == "Customer 17"
    shared, private = lines("sql_saved_shared")
    assert shared.details == {"id": number, "shared": True} and shared.target == "Customer 16"
    assert private.details == {"id": number, "shared": False} and private.target == "Customer 17"
    deleted, = lines("sql_saved_deleted")
    assert deleted.target == "Customer 17" and deleted.details == {"id": number, "shared": False}


def test_the_audit_keeps_a_long_sql_cut_to_2000(client, staff):
    client.force_login(staff)
    long_sql = "SELECT customer_id FROM dim_customers WHERE customer_name IN (" + ", ".join(
        f"'name {i}'" for i in range(1000)) + ")"
    number = save(client, sql=long_sql).json()["query"]["id"]
    change(client, number, sql=long_sql + " ")
    for line in lines("sql_saved") + lines("sql_saved_changed"):
        assert len(line.details["sql"]) == 2000 and long_sql.startswith(line.details["sql"])
    assert SavedQuery.objects.get().sql == long_sql + " "          # the query itself keeps all of it


def test_the_new_actions_have_their_words():
    words = dict(AuditLog.ACTIONS)
    assert words["sql_saved"] == "SQL page: query saved"
    assert words["sql_saved_changed"] == "SQL page: saved query changed"
    assert words["sql_saved_shared"] == "SQL page: saved query shared / made private"
    assert words["sql_saved_deleted"] == "SQL page: saved query deleted"
