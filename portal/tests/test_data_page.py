"""The Data page (/data/): records in each ai_gold table, staff only, read-only.
MySQL is faked here (the last test uses the real read-only MySQL and is skipped without it).
Run with:  python -m pytest -q"""
import datetime

import pytest
from django.urls import reverse

from portal.rag import warehouse

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


def test_a_stranger_goes_to_login(client):
    r = client.get(reverse("data"))
    assert r.status_code == 302
    assert r.url.startswith(reverse("login"))


def test_a_normal_user_gets_no_access(client, user, fake_mysql):
    client.force_login(user)
    r = client.get(reverse("data"))
    assert r.status_code == 403
    assert b"You do not have access" in r.content
    assert fake_mysql == []  # nothing is counted for them


def test_staff_sees_the_records_of_every_table_and_the_total(client, staff, fake_mysql):
    client.force_login(staff)
    r = client.get(reverse("data"))
    assert r.status_code == 200
    page = r.content.decode()
    for name, count in COUNTS.items():
        assert f"<code>{name}</code>" in page
        assert f"{count:,}" in page
    assert "321,415 records in 11 tables" in page
    assert "Stock ledger = inventory" in page
    assert "Invoices: 21 Dec 2025 to 20 Mar 2027" in page
    assert "Last data load: 06 Oct 2026 07:10 PM" in page
    assert len(fake_mysql) == 2  # one query counts every table, one gets the dates


def test_main_data_first_then_lookups_then_the_load_history(client, staff, fake_mysql):
    client.force_login(staff)
    page = client.get(reverse("data")).content.decode()
    order = ["fact_invoice_lines", "fact_stock_ledger", "dim_calendar", "dim_tax_codes", "load_log"]
    positions = [page.index(f"<code>{name}</code>") for name in order]
    assert positions == sorted(positions)
    assert "MAIN DATA" in page and "LOOKUP" in page and "LOAD HISTORY" in page


def test_one_count_query_for_every_table(client, staff, fake_mysql):
    client.force_login(staff)
    client.get(reverse("data"))
    count_sql = fake_mysql[0]
    assert count_sql.count("COUNT(*)") == len(COUNTS)
    assert count_sql.count("UNION ALL") == len(COUNTS) - 1
    assert "FROM `fact_stock_ledger`" in count_sql


def test_a_table_without_a_note_shows_its_name(client, staff, fake_mysql, monkeypatch):
    monkeypatch.setitem(COUNTS, "fact_new_table", 7)
    client.force_login(staff)
    page = client.get(reverse("data")).content.decode()
    assert "<code>fact_new_table</code>" in page
    assert "321,422 records in 12 tables" in page


def test_mysql_down_shows_a_clear_message(client, staff, monkeypatch):
    def down():
        raise warehouse.WarehouseUnavailable("Cannot connect to MySQL as nop_ai_reader: (2003) refused")

    monkeypatch.setattr(warehouse, "allowed_tables", down)
    client.force_login(staff)
    r = client.get(reverse("data"))
    assert r.status_code == 200
    page = r.content.decode()
    assert "The NOP data (MySQL) cannot be read right now" in page
    assert "(2003) refused" in page
    assert "records in" not in page


def test_menu_link_only_for_staff(client, user, staff):
    link = f'href="{reverse("data")}"'.encode()
    client.force_login(user)
    assert link not in client.get(reverse("ask")).content
    client.force_login(staff)
    assert link in client.get(reverse("ask")).content


def test_real_mysql_counts_match_a_direct_count(client, staff):
    """With the real read-only MySQL: the page shows the same number as a COUNT(*) of its own."""
    try:
        tables = warehouse.allowed_tables()
    except Exception as exc:
        pytest.skip(f"read-only MySQL not available: {exc}")
    client.force_login(staff)
    page = client.get(reverse("data")).content.decode()
    for name in ("fact_invoice_lines", "dim_customers"):
        assert name in tables
        rows = warehouse.run_select(f"SELECT COUNT(*) FROM {name}")["rows"][0][0]
        assert f"<code>{name}</code>" in page and f"{rows:,}" in page
