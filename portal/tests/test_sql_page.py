"""The SQL page (/api/sql/schema, /api/sql, /api/sql/excel): staff only, one checked SELECT on ss_gold,
run as the read-only MySQL user, every run in the audit log. MySQL is faked here (the last tests use the
real read-only MySQL and are skipped without it). No AI call.
Run with:  python -m pytest portal/tests/test_sql_page.py -q"""
import datetime
import decimal
import io
import json

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from portal import sql_page
from portal.models import AuditLog
from portal.rag import warehouse
from portal.tests.test_views_ask import api_get, api_post

pytestmark = pytest.mark.django_db

COLUMNS = {  # a small ss_gold: table -> [(column, type)]
    "dim_customers": [("customer_id", "int"), ("customer_name", "varchar(200)")],
    "fact_invoice_lines": [("invoice_id", "bigint"), ("invoice_date", "date"),
                           ("net_taxable_value", "decimal(18,2)")],
    "dim_calendar": [("date_id", "int"), ("full_date", "date")],
}
COUNTS = {"dim_customers": 5001, "fact_invoice_lines": 100720, "dim_calendar": 1096}
SELECT = "SELECT customer_id, customer_name FROM dim_customers WHERE customer_id = 16"
SECRET = "S3cret-Reader-Pass"


class FakeMySQL:
    """The read-only MySQL, faked: the ss_gold tables, the information_schema read of the tree, the row counts
    of the Data page, and one reply (or error) for a typed SELECT. Every SQL it was given is kept in .asked."""

    def __init__(self):
        self.asked = []          # the typed SELECTs (after the guard) that reached run_select
        self.schema_reads = 0
        self.result = {"columns": ["customer_id", "customer_name"], "rows": [[16, "Aurangabad Electricals"]],
                       "truncated": False}
        self.error = None        # an exception run_select raises for a typed SELECT

    def allowed_tables(self):
        return set(COLUMNS)

    def run_select_params(self, sql, params=(), max_rows=500):
        assert "information_schema.columns" in sql and params == (warehouse.database_name(),)
        self.schema_reads += 1
        rows = [[table, column, kind] for table in sorted(COLUMNS) for column, kind in COLUMNS[table]]
        return {"columns": ["table_name", "column_name", "column_type"], "rows": rows, "truncated": False}

    def run_select(self, sql, max_rows=500):
        if "COUNT(*)" in sql and "UNION ALL" in sql:  # services.table_counts
            return {"columns": ["name", "rows"], "rows": [[n, c] for n, c in COUNTS.items()], "truncated": False}
        self.asked.append(sql)
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def mysql(monkeypatch):
    fake = FakeMySQL()
    monkeypatch.setattr(warehouse, "allowed_tables", fake.allowed_tables)
    monkeypatch.setattr(warehouse, "run_select", fake.run_select)
    monkeypatch.setattr(warehouse, "run_select_params", fake.run_select_params)
    monkeypatch.setenv("AI_DB_PASSWORD", SECRET)
    sql_page.clear_cache()
    yield fake
    sql_page.clear_cache()


def run(client, sql):
    return api_post(client, "api_sql", {"sql": sql})


def lines(action="sql_run"):
    return list(AuditLog.objects.filter(action=action).order_by("pk"))


# ------------------------------------------------------------------ who may use it
def test_signed_out_gets_401_everywhere(client, mysql):
    assert api_get(client, "api_sql_schema").status_code == 401
    assert run(client, SELECT).status_code == 401
    assert api_post(client, "api_sql_excel", {"sql": SELECT}).status_code == 401
    assert mysql.asked == [] and mysql.schema_reads == 0


def test_a_normal_user_gets_403_everywhere(client, user, mysql):
    client.force_login(user)
    for r in [api_get(client, "api_sql_schema"), run(client, SELECT),
              api_post(client, "api_sql_excel", {"sql": SELECT})]:
        assert r.status_code == 403
        assert "Only administrators" in r.json()["detail"]
    assert mysql.asked == [] and mysql.schema_reads == 0
    assert AuditLog.objects.filter(action__startswith="sql_").count() == 0


def test_a_post_needs_the_csrf_token(staff, mysql):
    client = Client(enforce_csrf_checks=True)
    client.force_login(staff)
    for name in ("api_sql", "api_sql_excel"):
        r = client.post(reverse(name), data=json.dumps({"sql": SELECT}), content_type="application/json")
        assert r.status_code == 403 and "CSRF" in r.json()["detail"], name
    assert mysql.asked == []
    assert client.get(reverse("api_sql_schema")).status_code == 200   # reading the tree needs no token

    token = client.get(reverse("api_csrf")).json()["csrfToken"]
    assert settings.CSRF_COOKIE_NAME in client.cookies
    r = client.post(reverse("api_sql"), data=json.dumps({"sql": SELECT}), content_type="application/json",
                    HTTP_X_CSRFTOKEN=token)
    assert r.status_code == 200 and len(mysql.asked) == 1


def test_only_get_on_the_tree_and_only_post_to_run(client, staff, mysql):
    client.force_login(staff)
    assert api_post(client, "api_sql_schema", {}).status_code == 405
    assert api_get(client, "api_sql").status_code == 405
    assert api_get(client, "api_sql_excel").status_code == 405


# ------------------------------------------------------------------ the tree
def test_staff_gets_the_tables_a_to_z_with_rows_and_typed_columns(client, staff, mysql):
    client.force_login(staff)
    r = api_get(client, "api_sql_schema")
    assert r.status_code == 200
    body = r.json()
    assert body["database"] == warehouse.database_name()
    assert [t["name"] for t in body["tables"]] == ["dim_calendar", "dim_customers", "fact_invoice_lines"]
    customers = body["tables"][1]
    assert customers == {"name": "dim_customers", "rows": 5001, "columns": [
        {"name": "customer_id", "type": "int"}, {"name": "customer_name", "type": "varchar(200)"}]}
    invoice = body["tables"][2]
    assert [c["name"] for c in invoice["columns"]] == ["invoice_id", "invoice_date", "net_taxable_value"]
    text = r.content.decode()
    assert SECRET not in text and "localhost" not in text and "password" not in text.lower()


def test_the_tree_is_kept_a_few_minutes(client, staff, mysql):
    client.force_login(staff)
    api_get(client, "api_sql_schema")
    api_get(client, "api_sql_schema")
    assert mysql.schema_reads == 1
    sql_page.clear_cache()
    api_get(client, "api_sql_schema")
    assert mysql.schema_reads == 2


def test_the_tree_when_mysql_is_down(client, staff, monkeypatch):
    def down():
        raise warehouse.WarehouseUnavailable("Cannot connect to MySQL as ss_ai_reader: (2003) refused on localhost")

    monkeypatch.setattr(warehouse, "allowed_tables", down)
    sql_page.clear_cache()
    client.force_login(staff)
    r = api_get(client, "api_sql_schema")
    assert r.status_code == 503
    assert r.json()["detail"] == sql_page.MYSQL_DOWN
    assert "ss_ai_reader" not in r.content.decode() and "localhost" not in r.content.decode()


# ------------------------------------------------------------------ running a SELECT
def test_staff_runs_a_select(client, staff, mysql):
    client.force_login(staff)
    r = run(client, SELECT)
    assert r.status_code == 200
    body = r.json()
    assert body["columns"] == ["customer_id", "customer_name"]
    assert body["rows"] == [[16, "Aurangabad Electricals"]]
    assert (body["row_count"], body["truncated"], body["max_rows"]) == (1, False, 500)
    assert isinstance(body["secs"], float) and body["secs"] >= 0
    assert body["headers"] == [{"name": "customer_id", "num": True}, {"name": "customer_name", "num": False}]
    assert body["sql"] == mysql.asked[0]           # the SQL that ran is the one the guard wrote
    assert "LIMIT 500" in body["sql"]              # the guard's row cap


def test_rows_are_plain_json(client, staff, mysql):
    mysql.result = {"columns": ["d", "t", "amount", "rate", "nothing", "raw", "dur", "flag"],
                    "rows": [[datetime.date(2026, 8, 21), datetime.datetime(2026, 10, 6, 19, 10, 45),
                              decimal.Decimal("16547240.50"), 1.25, None, b"abc", datetime.timedelta(hours=1, minutes=2),
                              True]],
                    "truncated": False}
    client.force_login(staff)
    body = run(client, "SELECT * FROM fact_invoice_lines").json()
    assert body["rows"] == [["2026-08-21", "2026-10-06T19:10:45", "16547240.50", 1.25, None, "abc", "1:02:00", True]]


def test_at_most_500_rows_and_truncated(client, staff, mysql):
    mysql.result = {"columns": ["n"], "rows": [[i] for i in range(500)], "truncated": False}
    client.force_login(staff)
    body = run(client, "SELECT customer_id FROM dim_customers").json()   # no LIMIT: the guard adds LIMIT 500
    assert mysql.asked[-1].rstrip().endswith("LIMIT 500")
    assert body["row_count"] == 500 and body["truncated"] is True

    body = run(client, "SELECT customer_id FROM dim_customers LIMIT 100000").json()   # lowered to 500
    assert "LIMIT 500" in mysql.asked[-1] and "100000" not in mysql.asked[-1]
    assert body["truncated"] is True

    body = run(client, "SELECT customer_id FROM dim_customers LIMIT 500").json()   # asked for exactly 500
    assert body["truncated"] is False

    mysql.result = {"columns": ["n"], "rows": [[1]], "truncated": False}
    assert run(client, "SELECT customer_id FROM dim_customers").json()["truncated"] is False


@pytest.mark.parametrize("sql, words", [
    ("UPDATE dim_customers SET customer_name = 'x'", "Only SELECT queries are allowed"),
    ("DELETE FROM dim_customers", "Only SELECT queries are allowed"),
    ("DROP TABLE dim_customers", "Only SELECT queries are allowed"),
    ("INSERT INTO dim_customers (customer_id) VALUES (1)", "Only SELECT queries are allowed"),
    ("SELECT 1 FROM dim_customers; DROP TABLE dim_customers", "Only one SQL statement"),
    ("SELECT 1; SELECT 2", "Only one SQL statement"),
    ("SELECT * FROM auth_user", "Unknown table 'auth_user'"),
    ("SELECT username, password FROM auth_user", "Unknown table 'auth_user'"),
    ("SELECT * FROM portal_question", "Unknown table 'portal_question'"),
    ("SELECT * FROM mi_app.portal_question", "not 'mi_app'"),
    ("SELECT * FROM mi_app.auth_user", "not 'mi_app'"),
    ("SELECT * FROM ss_gold.auth_user", "Unknown table 'auth_user'"),
    ("SELECT * FROM information_schema.tables", "not 'information_schema'"),
    ("SELECT user, authentication_string FROM mysql.user", "not 'mysql'"),
    ("SELECT c.customer_id FROM dim_customers c JOIN mi_app.auth_user u ON u.id = c.customer_id", "not 'mi_app'"),
    ("SELECT * FROM dim_customers WHERE customer_id IN (SELECT id FROM auth_user)", "Unknown table 'auth_user'"),
    ("SELECT SLEEP(40)", "SLEEP() is not allowed"),
    ("SELECT * FROM dim_customers INTO OUTFILE '/tmp/x'", "INTO OUTFILE"),
    ("SELECT @@version", "MySQL variables"),
])
def test_the_guard_refuses(client, staff, mysql, sql, words):
    client.force_login(staff)
    r = run(client, sql)
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert words in detail and detail.startswith("This SQL cannot run:")
    assert "Traceback" not in detail
    assert mysql.asked == []                       # nothing reached MySQL


def test_empty_too_long_or_not_json_is_400(client, staff, mysql):
    client.force_login(staff)
    assert run(client, "   ").json()["detail"] == "Type a SELECT query first."
    too_long = "SELECT customer_id FROM dim_customers WHERE " + " OR ".join(["customer_id = 1"] * 2000)
    assert len(too_long) > sql_page.MAX_SQL_CHARS
    r = run(client, too_long)
    assert r.status_code == 400 and "under 20,000 characters" in r.json()["detail"]
    r = client.post(reverse("api_sql"), data="not json", content_type="application/json")
    assert r.status_code == 400 and "JSON" in r.json()["detail"]
    assert api_post(client, "api_sql", {"sql": 5}).status_code == 400
    assert mysql.asked == []


def test_a_mysql_error_is_400_in_plain_words(client, staff, mysql):
    mysql.error = warehouse.QueryError("(1054) Unknown column 'nmae' in 'field list'")
    client.force_login(staff)
    r = run(client, "SELECT nmae FROM dim_customers")
    assert r.status_code == 400
    assert r.json() == {"detail": "MySQL could not run the query: (1054) Unknown column 'nmae' in 'field list'"}


def test_the_30_second_limit_in_plain_words(client, staff, mysql):
    mysql.error = warehouse.QueryError("(3024) Query execution was interrupted, maximum statement execution time exceeded")
    client.force_login(staff)
    r = run(client, "SELECT COUNT(*) FROM fact_invoice_lines")
    assert r.status_code == 400 and "longer than 30 seconds" in r.json()["detail"]


def test_mysql_down_is_503(client, staff, mysql):
    mysql.error = warehouse.WarehouseUnavailable("Cannot connect to MySQL as ss_ai_reader: (2003) refused on localhost")
    client.force_login(staff)
    r = run(client, SELECT)
    assert r.status_code == 503
    assert r.json()["detail"] == sql_page.MYSQL_DOWN
    assert "ss_ai_reader" not in r.content.decode()


def test_mysql_down_before_the_guard_is_503(client, staff, mysql, monkeypatch):
    def down():
        raise warehouse.WarehouseUnavailable("Cannot connect")

    monkeypatch.setattr(warehouse, "allowed_tables", down)
    client.force_login(staff)
    assert run(client, SELECT).status_code == 503
    assert mysql.asked == []


# ------------------------------------------------------------------ the audit log
def test_every_run_is_one_audit_line_without_secrets(client, staff, mysql):
    client.force_login(staff)
    run(client, SELECT)
    run(client, "DROP TABLE dim_customers")
    mysql.error = warehouse.QueryError("(1054) Unknown column 'nmae' in 'field list'")
    run(client, "SELECT nmae FROM dim_customers")
    ok, refused, failed = lines()
    assert ok.username == "boss" and ok.target == warehouse.database_name()
    assert ok.details["sql"] == SELECT and ok.details["outcome"] == "ok"
    assert ok.details["rows"] == 1 and ok.details["truncated"] is False and isinstance(ok.details["secs"], float)
    assert refused.details["outcome"] == "refused" and "Only SELECT queries" in refused.details["error"]
    assert "Unknown column" in failed.details["error"]
    for line in (ok, refused, failed):
        text = json.dumps(line.details)
        assert SECRET not in text and "password" not in text.lower()


def test_the_audit_keeps_a_long_sql_cut(client, staff, mysql):
    client.force_login(staff)
    long_sql = "SELECT customer_id FROM dim_customers WHERE customer_name IN (" + ", ".join(
        f"'name {i}'" for i in range(1000)) + ")"
    run(client, long_sql)
    line, = lines()
    assert 0 < len(line.details["sql"]) <= 2000 and long_sql.startswith(line.details["sql"])


# ------------------------------------------------------------------ the Excel file
def test_excel_returns_an_xlsx_of_the_rows(client, staff, mysql):
    from openpyxl import load_workbook

    mysql.result = {"columns": ["customer_id", "net"], "rows": [[16, decimal.Decimal("1200.50")], [17, None]],
                    "truncated": False}
    client.force_login(staff)
    r = api_post(client, "api_sql_excel", {"sql": SELECT})
    assert r.status_code == 200
    assert r["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert r["Content-Disposition"].startswith('attachment; filename="sql_result_')
    book = load_workbook(io.BytesIO(r.content))
    result = book["Result"]
    assert [c.value for c in result[1]] == ["customer_id", "net"]
    assert [c.value for c in result[2]] == [16, 1200.5]
    info = {row[0].value: row[1].value for row in book["SQL"].iter_rows()}
    assert info["SQL"] == mysql.asked[0] and info["Run by"] == "boss" and info["Rows"] == 2
    line, = lines("sql_excel")
    assert line.details["outcome"] == "ok" and line.details["rows"] == 2 and line.details["sql"] == SELECT


def test_excel_has_the_same_guard_and_errors(client, staff, mysql):
    client.force_login(staff)
    r = api_post(client, "api_sql_excel", {"sql": "SELECT * FROM auth_user"})
    assert r.status_code == 400 and "Unknown table 'auth_user'" in r.json()["detail"]
    mysql.error = warehouse.WarehouseUnavailable("down")
    assert api_post(client, "api_sql_excel", {"sql": SELECT}).status_code == 503
    assert [line.details["outcome"] for line in lines("sql_excel")] == ["refused", "mysql_down"]


# ------------------------------------------------------------------ the real read-only MySQL (skipped without it)
@pytest.fixture
def real_mysql():
    try:
        warehouse.allowed_tables()
    except Exception as exc:
        pytest.skip(f"read-only MySQL not available: {exc}")
    sql_page.clear_cache()
    yield
    sql_page.clear_cache()


def test_real_mysql_tree_and_a_select(client, staff, real_mysql):
    client.force_login(staff)
    tables = {t["name"]: t for t in api_get(client, "api_sql_schema").json()["tables"]}
    assert "dim_customers" in tables and tables["dim_customers"]["rows"] > 0
    assert tables["dim_customers"]["columns"][0]["type"]
    body = run(client, "SELECT COUNT(*) AS n FROM dim_customers").json()
    assert body["rows"] == [[tables["dim_customers"]["rows"]]]


@pytest.mark.parametrize("sql", ["SELECT * FROM mysql.user", "SELECT * FROM information_schema.tables",
                                 "SELECT * FROM auth_user", "SELECT * FROM portal_question",
                                 "SELECT * FROM mi_app.auth_user", "SELECT * FROM test_mi_app.portal_question"])
def test_real_mysql_never_reaches_the_app_database(client, staff, real_mysql, sql):
    client.force_login(staff)
    r = run(client, sql)
    assert r.status_code == 400
