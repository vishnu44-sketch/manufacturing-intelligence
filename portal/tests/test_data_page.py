"""The Data numbers (/api/data): records in each ai_gold table, staff only, read-only.
MySQL is faked here (the last test uses the real read-only MySQL and is skipped without it).
Run with:  python -m pytest -q"""
import datetime

import pytest

from portal.rag import warehouse
from portal.tests.test_views_ask import api_get

pytestmark = pytest.mark.django_db

COUNTS = {  # the counts of 12-Oct-2026
    "dim_calendar": 1096, "dim_customers": 5001, "dim_fx_rates": 28, "dim_products": 5001,
    "dim_sales_people": 31, "dim_stock_movement_types": 8, "dim_tax_codes": 6,
    "fact_invoice_lines": 100720, "fact_sales_order_lines": 101260, "fact_stock_ledger": 108246,
    "load_log": 18,
}
DATES = {"invoices_from": datetime.date(2025, 12, 21), "invoices_to": datetime.date(2027, 3, 20),
         "last_load": datetime.datetime(2026, 10, 6, 19, 10, 45)}


@pytest.fixture
def fake_mysql(monkeypatch):
    """allowed_tables() = the 11 tables; run_select() answers the count and the dates query
    and records every SQL it was given."""
    asked = []
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: set(COUNTS))

    def fake_run_select(sql, max_rows=500):
        asked.append(sql)
        if "COUNT(*)" in sql:
            return {"columns": ["name", "rows"], "rows": [[n, c] for n, c in COUNTS.items()],
                    "truncated": False}
        return {"columns": list(DATES), "rows": [list(DATES.values())], "truncated": False}

    monkeypatch.setattr(warehouse, "run_select", fake_run_select)
    return asked


def data(client):
    return api_get(client, "api_data").json()


def test_a_stranger_must_sign_in(client):
    r = api_get(client, "api_data")
    assert r.status_code == 401


def test_a_normal_user_gets_no_access(client, user, fake_mysql):
    client.force_login(user)
    r = api_get(client, "api_data")
    assert r.status_code == 403
    assert "Only administrators can open this page" in r.json()["detail"]
    assert fake_mysql == []  # nothing is counted for them


def test_staff_sees_the_records_of_every_table_and_the_total(client, staff, fake_mysql):
    client.force_login(staff)
    body = data(client)
    rows = {t["name"]: t for t in body["tables"]}
    for name, count in COUNTS.items():
        assert rows[name]["rows"] == count and rows[name]["rows_text"] == f"{count:,}"
    assert (body["total"], body["table_count"]) == ("321,415", 11)   # "321,415 records in 11 tables"
    assert rows["fact_stock_ledger"]["note"].startswith("Stock ledger = inventory")
    assert (body["invoices_from"], body["invoices_to"]) == ("21 Dec 2025", "20 Mar 2027")
    assert body["last_load"] == "06 Oct 2026 07:10 PM"
    assert body["database"] and body["mysql_error"] == ""
    assert len(fake_mysql) == 2  # one query counts every table, one gets the dates


def test_main_data_first_then_lookups_then_the_load_history(client, staff, fake_mysql):
    client.force_login(staff)
    tables = data(client)["tables"]
    names = [t["name"] for t in tables]
    order = ["fact_invoice_lines", "fact_stock_ledger", "dim_calendar", "dim_tax_codes", "load_log"]
    positions = [names.index(name) for name in order]
    assert positions == sorted(positions)
    assert {t["kind"] for t in tables} == {"Main data", "Lookup", "Load history"}


def test_one_count_query_for_every_table(client, staff, fake_mysql):
    client.force_login(staff)
    data(client)
    count_sql = fake_mysql[0]
    assert count_sql.count("COUNT(*)") == len(COUNTS)
    assert count_sql.count("UNION ALL") == len(COUNTS) - 1
    assert "FROM `fact_stock_ledger`" in count_sql


def test_a_table_without_a_note_shows_its_name(client, staff, fake_mysql, monkeypatch):
    monkeypatch.setitem(COUNTS, "fact_new_table", 7)
    client.force_login(staff)
    body = data(client)
    new = next(t for t in body["tables"] if t["name"] == "fact_new_table")
    assert new["note"] == "" and new["kind"] == "Main data"
    assert (body["total"], body["table_count"]) == ("321,422", 12)


def test_mysql_down_gives_a_clear_message(client, staff, monkeypatch):
    def down():
        raise warehouse.WarehouseUnavailable("Cannot connect to MySQL as nop_ai_reader: (2003) refused")

    monkeypatch.setattr(warehouse, "allowed_tables", down)
    client.force_login(staff)
    r = api_get(client, "api_data")
    assert r.status_code == 200
    body = r.json()
    assert "(2003) refused" in body["mysql_error"]     # the app: "The NOP data (MySQL) cannot be read right now: ..."
    assert body["tables"] == [] and body["table_count"] == 0


def test_real_mysql_counts_match_a_direct_count(client, staff):
    """With the real read-only MySQL: the API gives the same number as a COUNT(*) of its own."""
    try:
        tables = warehouse.allowed_tables()
    except Exception as exc:
        pytest.skip(f"read-only MySQL not available: {exc}")
    client.force_login(staff)
    rows = {t["name"]: t["rows"] for t in data(client)["tables"]}
    for name in ("fact_invoice_lines", "dim_customers"):
        assert name in tables
        count = warehouse.run_select(f"SELECT COUNT(*) FROM {name}")["rows"][0][0]
        assert rows[name] == count
