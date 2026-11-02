"""The Documents page (/documents/): what the AI can read, staff only, read-only.
The vector store and MySQL are faked here, so the tests are fast and need neither.
Run with:  python -m pytest -q"""
import pytest
from django.urls import reverse

from portal.rag import store, warehouse

pytestmark = pytest.mark.django_db

PIECES = [
    {"id": "business_rules-001", "source": "business_rules.md", "kind": "rule",
     "heading": "Financial year (FY) - 1 April to 31 March", "text": "NOP business rule: FY text"},
    {"id": "business_rules-002", "source": "business_rules.md", "kind": "rule",
     "heading": "Stock value on a date - Closing balance rows only", "text": "Never SUM every row."},
    {"id": "data_dictionary-001", "source": "data_dictionary.md", "kind": "table",
     "heading": "fact_invoice_lines - what one row is", "text": "Table `fact_invoice_lines` ..."},
    {"id": "sql_examples-001", "source": "sql_examples.md", "kind": "example",
     "heading": "Q: What is our current stock value?", "text": "```sql\nSELECT 1 FROM fact_stock_ledger\n```"},
]

HITS = [  # what the fake search returns, best first
    {"text": f"text {i}", "source": "sql_examples.md", "heading": f"Hit number {i}",
     "kind": "example", "score": score}
    for i, score in enumerate([0.9123, 0.8, 0.75, 0.7, 0.655], start=1)
]


@pytest.fixture
def fake_store(monkeypatch):
    """A store with 4 pieces; search() returns HITS and records the questions it was given."""
    asked = []
    monkeypatch.setattr(store, "all_pieces", lambda path=None: [dict(p) for p in PIECES])

    def fake_search(question, top_k=5, path=None):
        asked.append((question, top_k))
        return [dict(h) for h in HITS]

    monkeypatch.setattr(store, "search", fake_search)
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: {
        "dim_calendar", "dim_customers", "dim_products", "dim_fx_rates", "dim_sales_people",
        "dim_tax_codes", "dim_stock_movement_types", "fact_invoice_lines",
        "fact_sales_order_lines", "fact_stock_ledger", "load_log"})
    return asked


def test_a_stranger_goes_to_login(client):
    r = client.get(reverse("documents"))
    assert r.status_code == 302
    assert r.url.startswith(reverse("login"))


def test_a_normal_user_gets_no_access(client, user, fake_store):
    client.force_login(user)
    r = client.get(reverse("documents"))
    assert r.status_code == 403
    assert b"You do not have access" in r.content


def test_staff_sees_every_piece_and_the_counts(client, staff, fake_store):
    client.force_login(staff)
    r = client.get(reverse("documents"))
    assert r.status_code == 200
    page = r.content.decode()
    assert "All files · 4 pieces" in page
    assert "business_rules.md · 2" in page and "data_dictionary.md · 1" in page
    assert "Showing 4 of 4 pieces" in page
    for piece in PIECES:
        assert piece["heading"] in page
    assert fake_store == []  # no question -> no search


def test_filter_by_file(client, staff, fake_store):
    client.force_login(staff)
    page = client.get(reverse("documents"), {"source": "business_rules.md"}).content.decode()
    assert "Showing 2 of 4 pieces" in page
    assert "Financial year (FY)" in page and "fact_invoice_lines - what one row is" not in page


def test_find_a_word_in_heading_or_text_any_case(client, staff, fake_store):
    client.force_login(staff)
    page = client.get(reverse("documents"), {"find": "STOCK"}).content.decode()
    assert "Showing 2 of 4 pieces" in page  # heading of the rule + heading/text of the example
    assert "Stock value on a date" in page and "Q: What is our current stock value?" in page
    page = client.get(reverse("documents"), {"find": "never sum"}).content.decode()
    assert "Showing 1 of 4 pieces" in page  # found in the text only


def test_test_search_shows_the_five_pieces_in_order_with_scores(client, staff, fake_store):
    client.force_login(staff)
    page = client.get(reverse("documents"), {"q": "what is our current stock value"}).content.decode()
    assert fake_store == [("what is our current stock value", 5)]  # the same search as the AI, top 5
    positions = [page.index(f"Hit number {i}") for i in range(1, 6)]
    assert positions == sorted(positions)  # best first
    assert "score 0.91" in page and "score 0.66" in page  # 2 decimals
    assert "The SQL step would show the columns of:" in page
    assert "fact_stock_ledger" in page.split("The SQL step would show the columns of:")[1]


def test_test_search_works_without_mysql(client, staff, fake_store, monkeypatch):
    def down():
        raise warehouse.WarehouseUnavailable("MySQL is down")

    monkeypatch.setattr(warehouse, "allowed_tables", down)
    client.force_login(staff)
    page = client.get(reverse("documents"), {"q": "open orders"}).content.decode()
    assert "Hit number 1" in page
    assert "The SQL step would show" not in page  # that line is simply left out


def test_an_empty_store_shows_how_to_build_it(client, staff, monkeypatch):
    monkeypatch.setattr(store, "all_pieces", lambda path=None: [])
    client.force_login(staff)
    page = client.get(reverse("documents"), {"q": "anything"}).content.decode()
    assert "ingest_docs" in page
    assert "Test search" not in page


def test_menu_link_only_for_staff(client, user, staff, fake_store):
    link = f'href="{reverse("documents")}"'.encode()
    client.force_login(user)
    assert link not in client.get(reverse("ask")).content
    client.force_login(staff)
    assert link in client.get(reverse("ask")).content


def test_all_pieces_of_a_missing_store_is_empty_and_creates_nothing(tmp_path):
    folder = tmp_path / "no_store_here"
    assert store.all_pieces(path=folder) == []
    assert not folder.exists()
