"""The vector store (portal/rag/store.py, Qdrant) - no server and no Docker needed:
Qdrant runs in-process in memory, and a closed port stands in for a stopped server.
The embedding model is faked here (small hand-made vectors), so these tests are fast.
Run with:  python -m pytest -q"""
import pytest
from django.urls import reverse

from portal.rag import agent, store

CHUNKS = [
    {"id": "sql_examples-002", "source": "sql_examples.md", "kind": "example",
     "heading": "Q: Second example?", "text": "Example two text", "embed_text": "two"},
    {"id": "business_rules-001", "source": "business_rules.md", "kind": "rule",
     "heading": "First rule", "text": "Rule one text", "embed_text": "one"},
    {"id": "data_dictionary-003", "source": "data_dictionary.md", "kind": "table",
     "heading": "fact_invoice_lines - columns", "text": "Table text", "embed_text": "three"},
]
VECTORS = {"one": [1.0, 0.0, 0.0, 0.0], "two": [0.6, 0.8, 0.0, 0.0], "three": [0.0, 0.0, 1.0, 0.0]}


@pytest.fixture
def fake_embed(monkeypatch):
    """Vectors from VECTORS instead of the real model; a question is embedded like its text."""
    monkeypatch.setattr(store.embed, "embed_documents", lambda texts: [VECTORS[t] for t in texts])
    monkeypatch.setattr(store.embed, "embed_query", lambda text: VECTORS[text])


@pytest.fixture
def qdrant_dir(tmp_path):
    yield tmp_path / "qdrant"
    store.close_clients()


@pytest.fixture
def qdrant_down(monkeypatch):
    """Nothing listens on the Qdrant port from .env (like a stopped Docker container)."""
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("QDRANT_API_KEY", "secret-test-key-123")
    store.close_clients()
    yield
    store.close_clients()


def test_point_ids_are_stable_uuids():
    first = store.point_id("sql_examples-007")
    assert first == store.point_id("sql_examples-007")  # same chunk -> same point every rebuild
    assert first != store.point_id("sql_examples-008")
    assert len(first) == 36 and first.count("-") == 4


def test_rebuild_and_all_pieces_round_trip_in_id_order(fake_embed, qdrant_dir):
    assert store.rebuild(CHUNKS, path=qdrant_dir) == 3
    pieces = store.all_pieces(path=qdrant_dir)
    assert [p["id"] for p in pieces] == sorted(c["id"] for c in CHUNKS)
    by_id = {p["id"]: p for p in pieces}
    for chunk in CHUNKS:  # everything we stored comes back unchanged (embed_text is not stored)
        assert by_id[chunk["id"]] == {k: chunk[k] for k in ("id", "text", "source", "heading", "kind")}


def test_rebuild_replaces_the_old_points(fake_embed, qdrant_dir):
    store.rebuild(CHUNKS, path=qdrant_dir)
    assert store.rebuild(CHUNKS[:1], path=qdrant_dir) == 1
    assert [p["id"] for p in store.all_pieces(path=qdrant_dir)] == ["sql_examples-002"]


def test_search_best_first_with_cosine_scores(fake_embed, qdrant_dir):
    store.rebuild(CHUNKS, path=qdrant_dir)
    hits = store.search("one", top_k=3, path=qdrant_dir)
    assert [h["heading"] for h in hits] == ["First rule", "Q: Second example?",
                                            "fact_invoice_lines - columns"]
    assert [h["score"] for h in hits] == pytest.approx([1.0, 0.6, 0.0], abs=1e-4)
    assert set(hits[0]) == {"text", "source", "heading", "kind", "score"}


def test_search_keeps_the_time_of_the_embedding_for_the_agent(fake_embed, qdrant_dir):
    store.rebuild(CHUNKS, path=qdrant_dir)
    store.last_search.embed_secs = None
    store.search("one", top_k=1, path=qdrant_dir)
    assert isinstance(store.last_search.embed_secs, float) and store.last_search.embed_secs >= 0


def test_empty_store_says_run_ingest_docs_and_a_missing_folder_stays_missing(tmp_path):
    missing = tmp_path / "no_store_here"
    assert store.all_pieces(path=missing) == []
    assert not missing.exists()
    with pytest.raises(RuntimeError, match="ingest_docs"):
        store.search("anything", path=tmp_path / "empty")
    store.close_clients()


def test_describe_names_the_db_but_never_the_key(monkeypatch):
    monkeypatch.setenv("QDRANT_API_KEY", "secret-test-key-123")
    monkeypatch.setenv("QDRANT_URL", "http://user:pw@localhost:6333")
    assert store.describe() == "Qdrant - http://localhost:6333"
    monkeypatch.delenv("QDRANT_URL")
    assert store.describe() == "Qdrant - http://127.0.0.1:6333"  # the default


def test_a_stopped_server_gives_a_clear_error(qdrant_down):
    with pytest.raises(store.VectorStoreUnavailable) as caught:
        store.search("open orders")
    assert str(caught.value) == store.QDRANT_DOWN
    assert "secret-test-key-123" not in str(caught.value)


@pytest.mark.django_db
def test_agent_answers_with_the_friendly_message_when_qdrant_is_down(qdrant_down, user):
    result = agent.ask("What were net sales in Dec 2026?", user)
    assert result.status == "error"
    assert result.answer == "The vector database (Qdrant) is not reachable - an admin must start it."
    assert result.question.status == "error"  # still saved in the history
    assert "secret-test-key-123" not in result.answer + result.error


@pytest.mark.django_db
def test_documents_page_shows_the_friendly_message_when_qdrant_is_down(qdrant_down, client, staff):
    client.force_login(staff)
    page = client.get(reverse("documents")).content.decode()
    assert "The vector database (Qdrant) is not reachable - an admin must start it." in page
    assert "Vector DB: <b>Qdrant - http://127.0.0.1:1</b>" in page
    assert "secret-test-key-123" not in page
    assert "Test search" not in page


@pytest.mark.django_db
def test_documents_page_names_the_qdrant_server(monkeypatch, client, staff):
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setattr(store, "all_pieces", lambda path=None: [])
    client.force_login(staff)
    page = client.get(reverse("documents")).content.decode()
    assert "Vector DB: <b>Qdrant - http://localhost:6333</b>" in page
