"""The Documents data (/api/documents): what the AI can read, staff only, read-only.
The vector store and MySQL are faked here, so the tests are fast and need neither.
Run with:  python -m pytest -q"""
import pytest

from portal.lc import vectorstore
from portal.rag import store, warehouse
from portal.tests.test_views_ask import api_get

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

    monkeypatch.setattr(vectorstore, "search", fake_search)
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: {
        "dim_calendar", "dim_customers", "dim_products", "dim_fx_rates", "dim_sales_people",
        "dim_tax_codes", "dim_stock_movement_types", "fact_invoice_lines",
        "fact_sales_order_lines", "fact_stock_ledger", "load_log"})
    return asked


def documents(client, **params):
    return api_get(client, "api_documents", data=params).json()


def headings(body):
    return [piece["heading"] for piece in body["pieces"]]


def test_a_stranger_must_sign_in(client):
    r = api_get(client, "api_documents")
    assert r.status_code == 401


def test_a_normal_user_gets_no_access(client, user, fake_store):
    client.force_login(user)
    r = api_get(client, "api_documents", data={"q": "stock value"})
    assert r.status_code == 403
    assert "Only administrators can open this page" in r.json()["detail"]
    assert fake_store == []  # nothing is searched for them


def test_staff_sees_every_piece_and_the_counts(client, staff, fake_store):
    client.force_login(staff)
    body = documents(client)
    assert body["total"] == 4                                            # "All files · 4 pieces"
    assert body["counts"] == [{"source": "business_rules.md", "count": 2}, {"source": "data_dictionary.md", "count": 1},
                              {"source": "sql_examples.md", "count": 1}]
    assert headings(body) == [p["heading"] for p in PIECES]              # "Showing 4 of 4 pieces"
    assert [p["no"] for p in body["pieces"]] == [1, 2, 3, 4]
    assert body["pieces"][1]["text"] == "Never SUM every row." and body["pieces"][1]["kind"] == "rule"
    assert body["hits"] == [] and fake_store == []  # no question -> no search


def test_filter_by_file(client, staff, fake_store):
    client.force_login(staff)
    body = documents(client, source="business_rules.md")
    assert body["total"] == 4 and len(body["pieces"]) == 2                # "Showing 2 of 4 pieces"
    assert body["source"] == "business_rules.md"
    assert "fact_invoice_lines - what one row is" not in headings(body)


def test_find_a_word_in_heading_or_text_any_case(client, staff, fake_store):
    client.force_login(staff)
    body = documents(client, find="STOCK")
    assert headings(body) == ["Stock value on a date - Closing balance rows only", "Q: What is our current stock value?"]
    body = documents(client, find="never sum")
    assert [p["no"] for p in body["pieces"]] == [2]  # found in the text only; the number stays as in the full list


def test_test_search_has_the_five_pieces_in_order_with_scores(client, staff, fake_store):
    client.force_login(staff)
    body = documents(client, q="what is our current stock value")
    assert fake_store == [("what is our current stock value", 5)]  # the same search as the AI, top 5
    assert [hit["heading"] for hit in body["hits"]] == [f"Hit number {i}" for i in range(1, 6)]  # best first
    assert body["hits"][0]["score"] == 0.9123 and body["hits"][-1]["score"] == 0.655   # the app shows 2 decimals
    assert body["tables"]["all"] is False                                 # "The SQL step would show the columns of:"
    assert "fact_stock_ledger" in body["tables"]["names"]


def test_test_search_works_without_mysql(client, staff, fake_store, monkeypatch):
    def down():
        raise warehouse.WarehouseUnavailable("MySQL is down")

    monkeypatch.setattr(warehouse, "allowed_tables", down)
    client.force_login(staff)
    body = documents(client, q="open orders")
    assert body["hits"][0]["heading"] == "Hit number 1"
    assert body["tables"] is None  # that line is simply left out


def test_an_empty_store_says_how_to_build_it(client, staff, fake_store, monkeypatch):
    monkeypatch.setattr(store, "all_pieces", lambda path=None: [])
    client.force_login(staff)
    body = documents(client, q="anything")
    assert body["total"] == 0 and "ingest_docs" in body["store_empty"]
    assert body["hits"] == [] and fake_store == []  # no test search


def test_all_pieces_of_a_missing_store_is_empty_and_creates_nothing(tmp_path):
    folder = tmp_path / "no_store_here"
    assert store.all_pieces(path=folder) == []
    assert not folder.exists()
