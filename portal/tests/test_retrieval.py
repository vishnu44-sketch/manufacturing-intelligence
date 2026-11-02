"""Step 3 checks: docs/*.md are cut into chunks, and search() finds the right chunk.

The retrieval tests build their own in-process, in-memory Qdrant store (no server), so the real
vector store is not touched. The first run downloads the embedding model (about 210 MB) into
.fastembed_cache/; building the store takes about half a minute.
Run with:  python -m pytest -q
"""
from pathlib import Path

import pytest

from portal.rag import store
from portal.rag.chunking import chunk_markdown, load_docs

DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"

# the 40 example chunks of docs/sql_examples.md (read once, no model needed)
EXAMPLES = [c for c in load_docs(DOCS_DIR) if c["kind"] == "example"]


# ---------- chunking (fast, no model) ----------

def test_one_chunk_per_h2_heading():
    markdown = (
        "# Title\nIntro text that is not a chunk.\n\n"
        "## First rule\nUse table_a.\n\n"
        "## Q: An example?\n```sql\n## not a heading inside code\nSELECT 1;\n```\nExpected: 1\n"
    )
    chunks = chunk_markdown(markdown, "business_rules.md")

    assert [c["heading"] for c in chunks] == ["First rule", "Q: An example?"]
    assert [c["id"] for c in chunks] == ["business_rules-001", "business_rules-002"]
    assert all(c["kind"] == "rule" and c["source"] == "business_rules.md" for c in chunks)
    # the text starts with the kind label and the heading, then the body
    assert chunks[0]["text"] == "NOP business rule: First rule\n\nUse table_a."
    # the code block stays in the text, but is left out of what gets embedded
    assert "SELECT 1;" in chunks[1]["text"]
    assert "SELECT 1;" not in chunks[1]["embed_text"]
    assert "Expected: 1" in chunks[1]["embed_text"]


def test_docs_folder_gives_the_expected_chunks():
    chunks = load_docs(DOCS_DIR)
    kinds = {c["source"]: c["kind"] for c in chunks}
    assert kinds == {"data_dictionary.md": "table", "business_rules.md": "rule",
                     "sql_examples.md": "example"}
    assert len({c["id"] for c in chunks}) == len(chunks)  # ids are unique
    assert load_docs(DOCS_DIR) == chunks  # same files -> same chunks every time

    # 40 examples, each with its SQL and its expected result
    assert len(EXAMPLES) == 40
    for c in EXAMPLES:
        assert c["heading"].startswith("Q: ")
        assert "```sql" in c["text"] and "\nExpected: " in c["text"]

    # every data dictionary section about a table names that table (dim_ / fact_ / load_log)
    table_sections = [c for c in chunks if c["kind"] == "table"
                      and c["heading"].startswith(("dim_", "fact_", "load_log"))]
    assert len(table_sections) >= 11
    for c in table_sections:
        table = c["heading"].split(" - ")[0]
        assert f"Table `{table}`" in c["text"], c["heading"]


def test_search_without_a_store_says_what_to_do(tmp_path):
    with pytest.raises(RuntimeError, match="ingest_docs"):
        store.search("invoice value", path=tmp_path)
    store.close_clients()


# ---------- retrieval (needs the embedding model) ----------
# Qdrant in-process, in memory (no server).

class BuiltStore:
    """A store built from docs/, named by a temporary folder."""

    def __init__(self, path):
        self.path = path

    def search(self, question, top_k=5):
        return store.search(question, top_k=top_k, path=self.path)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    path = tmp_path_factory.mktemp("qdrant_store")
    chunks = load_docs(DOCS_DIR)
    assert store.rebuild(chunks, path=path) == len(chunks)
    yield BuiltStore(path)
    store.close_clients()


def test_search_result_shape(built):
    hits = built.search("open orders", top_k=5)
    assert len(hits) == 5
    for hit in hits:
        assert set(hit) == {"text", "source", "heading", "kind", "score"}
        assert hit["kind"] in ("table", "rule", "example")
        assert hit["source"].endswith(".md")
    scores = [hit["score"] for hit in hits]
    assert scores == sorted(scores, reverse=True)  # best first


def test_invoice_value_finds_the_invoice_amount_columns_first(built):
    top = built.search("invoice value")[0]
    assert top["kind"] == "table"
    assert top["heading"].startswith("fact_invoice_lines")
    assert "`taxable_value`" in top["text"] and "`net_taxable_value`" in top["text"]


def test_which_month_is_oct_2026_finds_the_nop_month_rule_first(built):
    top = built.search("which month is Oct 2026")[0]
    assert top["kind"] == "rule"
    assert top["heading"].startswith("NOP sales month")
    assert "21-Sep-2026 to 20-Oct-2026" in top["text"]


@pytest.mark.parametrize("example", EXAMPLES, ids=[c["id"] for c in EXAMPLES])
def test_each_example_question_finds_its_own_example(built, example):
    question = example["heading"][len("Q: "):]
    hits = built.search(question, top_k=5)
    assert example["heading"] in [hit["heading"] for hit in hits]
