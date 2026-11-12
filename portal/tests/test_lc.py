"""The LangChain parts (portal/lc/): every AI call, the embeddings, the docs chunks, the notes search and the PDFs.

No test calls the real Groq API: the LLM parts use fake chat models.
Run with:  python -m pytest -q portal/tests/test_lc.py
"""
import pytest
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda

from portal.lc import chains, llm, prompts, vectorstore
from portal.rag import agent, store

MAIN, BACKUP = "openai/gpt-oss-120b", "qwen/qwen3.8-27b"
SQL_VALUES = {"schema": "dim_customers: customer_id, customer_name", "count": 2,
              "documents": "Example SQL ...\n\n---\n\nNOP sales month rule ...",
              "today": "02-Nov-2026 (Monday)", "preferences": "", "earlier": "",
              "question": "Top 5 customers in Aug 2026?"}

CHUNKS = [  # three notes with small hand-made vectors (like test_store_qdrant.py)
    {"id": "sql_examples-002", "source": "sql_examples.md", "kind": "example",
     "heading": "Q: Second example?", "text": "Example two text", "embed_text": "two"},
    {"id": "business_rules-001", "source": "business_rules.md", "kind": "rule",
     "heading": "First rule", "text": "Rule one text", "embed_text": "one"},
    {"id": "data_dictionary-003", "source": "data_dictionary.md", "kind": "table",
     "heading": "fact_invoice_lines - columns", "text": "Table text", "embed_text": "three"},
]
VECTORS = {"one": [1.0, 0.0, 0.0, 0.0], "two": [0.6, 0.8, 0.0, 0.0], "three": [0.0, 0.0, 1.0, 0.0],
           "dummy_text": [0.5, 0.5, 0.5, 0.5]}  # QdrantVectorStore embeds 'dummy_text' to check the vector size


class FakeEmbeddings(Embeddings):
    """A LangChain embedding model that gives the hand-made VECTORS (no real model is loaded)."""

    def embed_documents(self, texts):
        return [VECTORS[text] for text in texts]

    def embed_query(self, text):
        return VECTORS[text]


@pytest.fixture
def test_store(monkeypatch, tmp_path):
    """An in-memory Qdrant with the three CHUNKS, built by vectorstore.rebuild() with the fake vectors."""
    monkeypatch.setattr(vectorstore, "get_embeddings", lambda: FakeEmbeddings())
    path = tmp_path / "qdrant"
    vectorstore.clear()
    vectorstore.rebuild(CHUNKS, path=path)
    yield path
    vectorstore.clear()
    store.close_clients()


# ---------- step A: the packages ----------

def test_the_langchain_packages_are_installed():
    """The versions in requirements.txt (langchain-groq is not used: it needs an old groq package)."""
    from importlib.metadata import version
    assert version("langchain-core") == "1.7.3"
    assert version("langchain-openai") == "1.7.3"
    assert version("langchain-qdrant") == "1.1.0"
    assert version("langchain-community") == "0.4.2"
    assert version("langchain-text-splitters") == "1.1.3"


# ---------- step B: embeddings, QdrantVectorStore and the retriever ----------

def test_ingest_also_writes_the_metadata_langchain_reads(test_store):
    client = store._client(test_store)
    points, _ = client.scroll(store.COLLECTION, limit=10, with_payload=True)
    for point in points:
        payload = point.payload
        assert payload["metadata"] == {"id": payload["id"], "source": payload["source"],
                                       "heading": payload["heading"], "kind": payload["kind"]}


def test_the_search_gives_the_notes_best_first_with_their_details(test_store):
    hits = vectorstore.search("one", top_k=3, path=test_store)
    assert [h["heading"] for h in hits] == ["First rule", "Q: Second example?", "fact_invoice_lines - columns"]
    assert hits[0] == {"text": "Rule one text", "source": "business_rules.md", "heading": "First rule",
                       "kind": "rule", "score": 1.0}


def test_the_main_projects_collection_is_refused(monkeypatch):
    monkeypatch.setattr(store, "COLLECTION", "nop_docs")
    with pytest.raises(vectorstore.WrongCollection, match="main project"):
        vectorstore.get_vectorstore()


def test_a_store_that_was_never_built_says_run_ingest_docs(tmp_path, monkeypatch):
    monkeypatch.setattr(vectorstore, "get_embeddings", lambda: FakeEmbeddings())
    vectorstore.clear()
    with pytest.raises(RuntimeError, match="ingest_docs"):
        vectorstore.search("one", path=tmp_path / "never-built")
    store.close_clients()


def test_the_embedding_model_and_its_cache_come_from_the_settings(monkeypatch):
    from portal.lc import embeddings
    monkeypatch.setenv("EMBED_MODEL", "")
    assert embeddings.model_name() == "BAAI/bge-base-en-v1.5"
    assert embeddings.CACHE_DIR.name == ".fastembed_cache" and (embeddings.CACHE_DIR.parent / "manage.py").exists()


def real_points(ids):
    """The stored points (with their vectors) of these chunk ids in the real collection (mi_docs); skip without it."""
    try:
        client = store._client()
        found = client.retrieve(store.COLLECTION, ids=[store.point_id(i) for i in ids], with_vectors=True)
    except Exception as exc:  # Qdrant down or never built: like the other real-service tests
        pytest.skip(f"vector store not available (start Qdrant, run manage.py ingest_docs): {exc}")
    return {point.payload["id"]: point for point in found}


def test_the_real_index_holds_the_langchain_vectors_of_the_notes_without_their_sql():
    """The real model and the real collection: every note's vector is FastEmbed's passage vector of its
    embed_text (lc/embeddings.py), so a question vector (embed_query) is compared with the right vectors."""
    import numpy
    from django.conf import settings
    from portal.lc.docs import load_docs
    from portal.lc.embeddings import get_embeddings

    chunks = [c for c in load_docs(settings.BASE_DIR / "docs") if c["id"] in
              ("business_rules-001", "data_dictionary-003", "sql_examples-007")]
    points = real_points([c["id"] for c in chunks])
    for chunk, vector in zip(chunks, get_embeddings().embed_documents([c["embed_text"] for c in chunks])):
        expected = numpy.array(vector) / numpy.linalg.norm(vector)  # Qdrant keeps cosine vectors normalised
        assert points[chunk["id"]].vector == pytest.approx(list(expected), abs=1e-5), chunk["id"]
        assert points[chunk["id"]].payload["text"] == chunk["text"]


QUESTIONS = {  # question -> the note that must come first (02-Nov, the same top 5 as before LangChain-only)
    "Top 5 customers by net sales in FY 2026-27": "Q: Who were the top 5 customers by invoice value in Aug 2026?",
    "How many sales orders are open?": "Q: Which customers have open sales orders, and for how much?",
    "What is our current stock value?": "Q: What is our current stock value (latest stock report)?",
    "net sales by state last month": "Q: What were net sales in each NOP sales month of FY 2026-27?",
    "What was our profit last year?":
        "Q: What were total net sales this year and last year, and how much did they grow?",
}


def test_the_real_index_finds_the_right_notes_with_the_search_and_the_retriever():
    """The real Qdrant and collection (mi_docs): search() and LangChain's retriever give the same 5 notes, best first."""
    vectorstore.clear()
    try:
        vectorstore.search("open orders", top_k=1)
    except Exception as exc:  # Qdrant down or never built: like the other real-service tests
        pytest.skip(f"vector store not available (start Qdrant, run manage.py ingest_docs): {exc}")
    for question, first in QUESTIONS.items():
        hits = vectorstore.search(question, top_k=5)
        assert hits[0]["heading"] == first, question
        assert [h["score"] for h in hits] == sorted((h["score"] for h in hits), reverse=True)


# ---------- step C: the chat model, the prompt templates and the chains (fake AI only) ----------

def expected_sql_messages(values):
    """The SQL call's messages: agent.py's prompt texts filled with the values."""
    return [{"role": "system", "content": agent.SQL_SYSTEM_PROMPT},
            {"role": "user", "content": agent.SQL_REQUEST.format(**values)}]


def test_the_sql_template_is_the_agents_prompt_text():
    messages = prompts.SQL_PROMPT.format_messages(**SQL_VALUES)
    assert [type(m) for m in messages] == [SystemMessage, HumanMessage]
    assert [m.content for m in messages] == [m["content"] for m in expected_sql_messages(SQL_VALUES)]


def test_a_retry_adds_the_ais_reply_and_the_problem():
    problem = "MySQL returned an error: Unknown column 'il.amount'"
    retries = [AIMessage("```sql\nSELECT il.amount FROM fact_invoice_lines il\n```"),
               HumanMessage(prompts.RETRY_PROMPT.format(problem=problem))]
    messages = prompts.SQL_PROMPT.format_messages(**SQL_VALUES, retries=retries)
    assert len(messages) == 4 and messages[2:] == retries
    assert messages[3].content == agent.RETRY_PROMPT.format(problem=problem)


def test_the_rewrite_and_answer_templates_use_the_agents_texts():
    rewrite = prompts.REWRITE_PROMPT.format_messages(earlier="1. Top customers in Aug 2026 (latest)",
                                                     question="and for Sep?")
    assert rewrite[0].content == agent.REWRITE_SYSTEM_PROMPT
    assert rewrite[1].content == agent.REWRITE_REQUEST.format(earlier="1. Top customers in Aug 2026 (latest)",
                                                              question="and for Sep?")
    values = {"question": "Top customers?", "understood": "", "preferences": "", "sql": "SELECT 1", "periods": "",
              "note": "2 row(s)", "table": "customer_name | net_sales_inr", "documents": ""}
    answer = prompts.EXPLAIN_PROMPT.format_messages(**values)
    assert [m.content for m in answer] == [agent.EXPLAIN_SYSTEM_PROMPT, agent.EXPLAIN_REQUEST.format(**values)]


def test_the_sql_chain_sends_the_filled_template_to_the_model_and_returns_its_reply():
    seen = []

    def fake_model(prompt_value):  # a stand-in for the chat model that remembers what it got
        seen.append(prompt_value.to_messages())
        return AIMessage("```sql\nSELECT 1\n```")

    reply = chains.sql_chain(RunnableLambda(fake_model)).invoke(SQL_VALUES)
    assert reply.content == "```sql\nSELECT 1\n```"
    assert [m.content for m in seen[0]] == [m["content"] for m in expected_sql_messages(SQL_VALUES)]


def test_the_chains_work_with_a_langchain_fake_chat_model():
    fake = FakeListChatModel(responses=["```sql\nSELECT 1\n```", "Aurora had the highest sales.",
                                        "Top customers in Sep 2026?"])
    assert chains.sql_chain(fake).invoke(SQL_VALUES).content == "```sql\nSELECT 1\n```"
    assert chains.answer_chain(fake).invoke(
        {"question": "q", "understood": "", "preferences": "", "sql": "SELECT 1", "periods": "", "note": "1 row(s)",
         "table": "x", "documents": ""}).content == "Aurora had the highest sales."
    assert chains.rewrite_chain(fake).invoke(
        {"earlier": "1. Top customers in Aug 2026", "question": "and Sep?"}).content == "Top customers in Sep 2026?"


def test_reply_info_reads_the_text_the_tokens_and_a_cut_off_reply():
    message = AIMessage(" SELECT 1 ", usage_metadata={"input_tokens": 3900, "output_tokens": 100, "total_tokens": 4000},
                        response_metadata={"finish_reason": "length"})
    assert chains.reply_info(message) == ("SELECT 1", 4000, True)
    assert chains.reply_info(AIMessage("ok", response_metadata={"finish_reason": "stop"})) == ("ok", None, False)


def test_the_main_model_has_the_app_settings(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MODEL", MAIN)
    model = llm.make_llm(agent.model_name(), agent.SQL_MAX_TOKENS, "medium")
    assert model.model_name == MAIN and model.openai_api_base == llm.GROQ_OPENAI_URL
    assert model.temperature == 0 and model.max_tokens == 3000 and model.max_retries == 0
    assert model.request_timeout == llm.TIMEOUT_SECS == 90
    assert model.extra_body == {"reasoning_effort": "medium", "include_reasoning": False}
    payload = model._get_request_payload([HumanMessage("hi")])
    assert payload["model"] == MAIN and payload["temperature"] == 0
    assert payload.get("max_completion_tokens", payload.get("max_tokens")) == 3000


def test_the_backup_model_gets_its_smaller_limit_and_its_own_setting(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MODEL", MAIN)
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", BACKUP)
    model = llm.make_llm(agent.fallback_model_name(), agent.SQL_MAX_TOKENS, "medium")
    assert model.model_name == BACKUP and model.max_tokens == agent.FALLBACK_MAX_TOKENS
    assert model.extra_body == {"reasoning_format": "hidden"}


def test_a_missing_key_gives_the_friendly_message():
    with pytest.raises(agent.AIUnavailable) as missing:
        llm.make_llm(MAIN, agent.SQL_MAX_TOKENS, "medium")
    assert str(missing.value) == llm.MISSING_KEY == "The AI service is not set up (GROQ_API_KEY is missing in .env)."


def test_no_test_can_reach_the_real_ai_through_langchain(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    with pytest.raises(AssertionError, match="use a fake chat model"):
        chains.sql_chain(llm.make_llm(MAIN, agent.SQL_MAX_TOKENS, "medium")).invoke(SQL_VALUES)


# ---------- step D: the app answers through LangChain (calls.py) ----------

from portal.lc import calls  # noqa: E402
from portal.tests.test_agent import (ANSWER, GOOD_SQL, HITS, ROWS, FakeMySQL, connection_error,  # noqa: E402
                                     daily_limit_error, rate_limit_error, use_fake_ai)


@pytest.fixture
def lc_app(monkeypatch):
    """A fake AI behind LangChain's chains, fake notes and a fake MySQL; .chains = the chain of every AI call
    that went through portal/lc/calls.py."""
    db = FakeMySQL()
    monkeypatch.setattr(agent, "search", lambda text, top_k=5: HITS)
    monkeypatch.setattr(agent.warehouse, "allowed_tables", lambda: {"dim_customers", "dim_calendar", "fact_invoice_lines"})
    monkeypatch.setattr(agent.warehouse, "schema_text", lambda: "dim_customers: customer_id, customer_name")
    monkeypatch.setattr(agent.warehouse, "run_select", db.run_select)
    monkeypatch.setattr(agent, "unknown_values", lambda sql, allowed: [])
    monkeypatch.setattr(agent, "invoice_data_dates", lambda: None)
    db.chains = []
    real_chat = calls.chat
    monkeypatch.setattr(calls, "chat", lambda request, *args: db.chains.append(request.chain) or real_chat(request, *args))
    return db


@pytest.mark.django_db
def test_the_answer_comes_through_the_langchain_chains(monkeypatch, lc_app, user):
    lc_app.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [(GOOD_SQL, 4000), (ANSWER, 900)])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and result.answer == ANSWER and result.row_count == 2
    assert lc_app.chains == ["sql", "answer"]                       # both AI calls went through LangChain
    assert result.sql_tokens == 4000 and result.answer_tokens == 900  # the tokens are counted
    assert {"search", "sql_ai", "mysql", "answer_ai"} <= set(result.step_secs)
    assert fake.calls[0][0]["content"] == agent.SQL_SYSTEM_PROMPT    # the agent's prompt text
    assert "LIMIT 2" in lc_app.calls[0]                              # our SQL guard's SQL ran on MySQL


@pytest.mark.django_db
def test_a_follow_up_is_rewritten_through_the_rewrite_chain(monkeypatch, lc_app, user):
    from types import SimpleNamespace
    lc_app.results = [ROWS]
    use_fake_ai(monkeypatch, ["Top customers in Sep 2026?", GOOD_SQL, ANSWER])
    earlier = SimpleNamespace(text="Top customers in Aug 2026?", sql="SELECT 1", answer="Aurora.", understood_as="")

    result = agent.ask("and for Sep?", user, context=[earlier])

    assert lc_app.chains == ["rewrite", "sql", "answer"] and result.understood_as == "Top customers in Sep 2026?"


@pytest.mark.django_db
def test_a_mysql_error_goes_back_to_the_ai_through_the_sql_chains_retries(monkeypatch, lc_app, user):
    lc_app.results = [agent.warehouse.QueryError("(1054) Unknown column 'il.amount'"), ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and result.tries == 2 and lc_app.chains == ["sql", "sql", "answer"]
    second_try = fake.calls[1]
    assert [m["role"] for m in second_try] == ["system", "user", "assistant", "user"]
    assert "MySQL returned an error: (1054) Unknown column 'il.amount'" in second_try[-1]["content"]


@pytest.mark.django_db
def test_the_per_minute_limit_waits_and_the_wait_is_shown(monkeypatch, lc_app, user):
    waits = []
    monkeypatch.setattr(agent.time, "sleep", waits.append)
    lc_app.results = [ROWS]
    use_fake_ai(monkeypatch, [rate_limit_error(retry_after=4), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and waits == [4.5] and result.step_secs["wait"] == 4.5


@pytest.mark.django_db
def test_the_daily_limit_moves_to_the_backup_model(monkeypatch, lc_app, user):
    monkeypatch.setenv("GROQ_MODEL", MAIN)
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", BACKUP)
    lc_app.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and result.model == BACKUP and result.answered_by_backup
    assert fake.models == [MAIN, BACKUP, BACKUP]


@pytest.mark.django_db
def test_an_unreachable_ai_gives_the_friendly_message(monkeypatch, lc_app, user):
    waits = []
    monkeypatch.setattr(agent.time, "sleep", waits.append)
    use_fake_ai(monkeypatch, [connection_error()] * 2)

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "error" and result.answer == agent.AI_DOWN and lc_app.calls == []
    assert waits == [3]                                              # one more try after 3 s


@pytest.mark.django_db
def test_a_missing_key_stops_the_question_with_the_friendly_message(lc_app, user):
    """No fake AI and no GROQ_API_KEY (conftest removes it): the real make_llm says what to fix."""
    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "error" and result.answer == llm.MISSING_KEY and lc_app.calls == []


def test_the_answer_values_fill_the_answer_template():
    """agent.explain_values() gives every {field} of the answer template: the request is EXPLAIN_REQUEST filled in."""
    result = agent.AskResult(text="Top customers?", sql="SELECT 1", columns=ROWS["columns"], rows=ROWS["rows"])
    values = agent.explain_values(result, agent.ROWS_FOR_ANSWER)
    messages = prompts.EXPLAIN_PROMPT.format_messages(**values)
    assert [m.content for m in messages] == [agent.EXPLAIN_SYSTEM_PROMPT, agent.EXPLAIN_REQUEST.format(**values)]
    assert "Aurora Fluid Power Limited | 1,730,000.00" in messages[1].content


# ---------- step G: reading PDFs (load, split, store and search in their own collection mi_pdfs) ----------

import httpx  # noqa: E402
from django.core.management import CommandError, call_command  # noqa: E402

from portal.lc import pdfs  # noqa: E402

PDF_FILES = ["maintenance_and_troubleshooting_guide.pdf", "product_catalogue.pdf",
             "sales_terms_and_discount_policy.pdf", "warranty_and_returns_policy.pdf"]
PDF_TITLES = {"maintenance_and_troubleshooting_guide.pdf": "Maintenance and Troubleshooting Guide",
              "product_catalogue.pdf": "Product Catalogue",
              "sales_terms_and_discount_policy.pdf": "Sales Terms and Discount Policy",
              "warranty_and_returns_policy.pdf": "Warranty and Returns Policy"}
WORDS = ["warranty", "hydraulic", "discount", "noise", "pressure", "pump", "filter", "invoice"]


class WordEmbeddings(Embeddings):
    """A fake embedding model for any text: how often each of WORDS appears (no real model is loaded)."""

    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text):
        text = text.lower()
        return [float(text.count(word)) for word in WORDS] + [0.1]  # 0.1: never an all-zero vector


@pytest.fixture(scope="module")
def real_pages():
    """The 4 real PDFs in pdfs/, loaded once."""
    return pdfs.load_pdfs()


@pytest.fixture
def pdf_store(monkeypatch, tmp_path):
    """An in-memory Qdrant with the real PDFs' chunks and fake vectors; yields (path, counts)."""
    monkeypatch.setattr(pdfs, "get_embeddings", lambda: WordEmbeddings())
    pdfs.clear()
    path = tmp_path / "qdrant"
    counts = pdfs.rebuild(path=path)
    yield path, counts
    pdfs.clear()
    store.close_clients()


def test_pypdf_is_installed():
    from importlib.metadata import version
    assert version("pypdf") == "6.21.4"


def test_the_4_pdfs_load_as_8_pages_numbered_from_1(real_pages):
    assert len(real_pages) == 8
    assert [(page.metadata["source"], page.metadata["page"]) for page in real_pages] == [
        (name, number) for name in PDF_FILES for number in (1, 2)]
    for page in real_pages:
        assert page.metadata["title"] == PDF_TITLES[page.metadata["source"]]
    warranty_page_1 = next(page for page in real_pages if page.metadata["source"] == "warranty_and_returns_policy.pdf"
                           and page.metadata["page"] == 1)
    assert "Hydraulic motors" in warranty_page_1.page_content


def test_a_pdf_without_a_title_gets_its_file_name_made_readable(tmp_path):
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with open(tmp_path / "spare_parts_list.pdf", "wb") as file:
        writer.write(file)
    [page] = pdfs.load_pdfs(tmp_path)
    assert page.metadata == {"source": "spare_parts_list.pdf", "page": 1, "title": "Spare parts list"}


def test_the_pages_are_split_into_small_chunks_with_stable_ids(real_pages):
    chunks = pdfs.split_pages(real_pages)
    ids = [chunk.metadata["id"] for chunk in chunks]
    assert len(chunks) > len(real_pages)                      # a page holds more than one chunk
    assert all(len(chunk.page_content) <= pdfs.CHUNK_SIZE for chunk in chunks)
    assert len(set(ids)) == len(ids)                          # unique
    assert ids == [chunk.metadata["id"] for chunk in pdfs.split_pages(pdfs.load_pdfs())]  # stable
    assert "warranty_and_returns_policy-p1-01" in ids
    for chunk in chunks:
        assert chunk.metadata["kind"] == "pdf" and chunk.metadata["source"] in PDF_FILES
        assert chunk.metadata["page"] in (1, 2) and chunk.metadata["title"] == PDF_TITLES[chunk.metadata["source"]]


def test_rebuild_stores_every_chunk_with_its_details(pdf_store, real_pages):
    path, counts = pdf_store
    chunks = pdfs.split_pages(real_pages)
    assert counts == {"pdfs": 4, "pages": 8, "chunks": len(chunks)}
    client = store._client(path)
    assert not client.collection_exists(store.COLLECTION)   # only the PDFs' own collection is written
    points, _ = client.scroll(pdfs.COLLECTION, limit=100, with_payload=True)
    stored = {point.payload["metadata"]["id"]: point for point in points}
    assert set(stored) == {chunk.metadata["id"] for chunk in chunks}
    for chunk in chunks:
        point = stored[chunk.metadata["id"]]
        assert str(point.id) == store.point_id(chunk.metadata["id"])  # the same id after every rebuild
        assert point.payload == {"text": chunk.page_content, "metadata": chunk.metadata}


def test_search_gives_the_closest_chunks_best_first(pdf_store):
    path, _ = pdf_store
    hits = pdfs.search_pdfs("discount", k=3, path=path)
    assert len(hits) == 3
    assert set(hits[0]) == {"text", "source", "title", "page", "score"}
    assert [hit["score"] for hit in hits] == sorted((hit["score"] for hit in hits), reverse=True)
    assert hits[0]["source"] == "sales_terms_and_discount_policy.pdf" and "discount" in hits[0]["text"].lower()
    assert hits[0]["title"] == "Sales Terms and Discount Policy" and hits[0]["page"] in (1, 2)


@pytest.mark.parametrize("name, message", [("nop_docs", "main project"), (store.COLLECTION, "SQL notes")])
def test_the_main_projects_and_the_sql_notes_collections_are_refused(monkeypatch, tmp_path, name, message):
    monkeypatch.setattr(pdfs, "COLLECTION", name)
    with pytest.raises(vectorstore.WrongCollection, match=message):
        pdfs.rebuild(path=tmp_path / "qdrant")
    with pytest.raises(vectorstore.WrongCollection, match=message):
        pdfs.search_pdfs("warranty", path=tmp_path / "qdrant")


def test_a_pdf_store_that_was_never_built_says_run_ingest_pdfs(monkeypatch, tmp_path):
    monkeypatch.setattr(pdfs, "get_embeddings", lambda: WordEmbeddings())
    pdfs.clear()
    with pytest.raises(RuntimeError, match="ingest_pdfs"):
        pdfs.search_pdfs("warranty", path=tmp_path / "never-built")
    store.close_clients()


def test_a_missing_or_empty_pdf_folder_gives_a_clear_message(tmp_path):
    with pytest.raises(pdfs.NoPdfs, match="does not exist"):
        pdfs.load_pdfs(tmp_path / "no-such-folder")
    with pytest.raises(pdfs.NoPdfs, match="No PDF files"):
        pdfs.rebuild(folder=tmp_path, path=tmp_path / "qdrant")


class _DownQdrant:
    """A Qdrant client whose server is not running."""

    def collection_exists(self, name):
        raise httpx.ConnectError("connection refused")


def test_qdrant_down_gives_the_friendly_message(monkeypatch):
    monkeypatch.setattr(pdfs, "get_embeddings", lambda: WordEmbeddings())
    monkeypatch.setattr(store, "_client", lambda path=None: _DownQdrant())
    for call in (pdfs.rebuild, lambda: pdfs.search_pdfs("warranty")):
        with pytest.raises(store.VectorStoreUnavailable, match="not reachable"):
            call()


def test_the_ingest_pdfs_command_reports_the_counts(monkeypatch, capsys):
    monkeypatch.setattr(pdfs, "rebuild", lambda: {"pdfs": 4, "pages": 8, "chunks": 17})
    call_command("ingest_pdfs")
    assert (f"Stored 17 chunks from 4 PDFs (8 pages) in {store.describe()} (collection {pdfs.COLLECTION})"
            in capsys.readouterr().out)


@pytest.mark.parametrize("error", [pdfs.NoPdfs("No PDF files found in pdfs"),
                                   vectorstore.WrongCollection("the main project's index"),
                                   store.VectorStoreUnavailable(store.QDRANT_DOWN)])
def test_the_ingest_pdfs_command_turns_problems_into_a_clear_error(monkeypatch, error):
    def fail():
        raise error
    monkeypatch.setattr(pdfs, "rebuild", fail)
    with pytest.raises(CommandError) as raised:
        call_command("ingest_pdfs")
    assert str(raised.value) == str(error)


def test_the_real_pdf_index_finds_the_hydraulic_motor_warranty():
    """The real model and the real Qdrant collection (mi_pdfs)."""
    pdfs.clear()
    try:
        hits = pdfs.search_pdfs("How long is the warranty on hydraulic motors?")
    except Exception as exc:  # Qdrant down or never built: like the other real-service tests
        pytest.skip(f"PDF store not available (start Qdrant, run manage.py ingest_pdfs): {exc}")
    assert (hits[0]["source"], hits[0]["page"]) == ("warranty_and_returns_policy.pdf", 1)


# ---------- chat memory: LangChain's chat history on our History DB ----------

from types import SimpleNamespace  # noqa: E402

from portal.lc import memory  # noqa: E402
from portal.models import Conversation, Question  # noqa: E402

EARLIER = [SimpleNamespace(text="who is our top customer  in japan", understood_as="", answer="Sakura Ltd bought most.",
                           sql="SELECT 1"),
           SimpleNamespace(text="and for export?", understood_as="Top customer for export sales in FY 2026-27?",
                           answer="", sql="")]


def test_the_chat_history_gives_one_message_pair_per_earlier_question():
    history = memory.ChatHistory(EARLIER, session_id="7")
    messages = history.messages
    assert [type(m) for m in messages] == [HumanMessage, AIMessage, HumanMessage, AIMessage]
    assert messages[0].content == "who is our top customer  in japan" and messages[1].content == "Sakura Ltd bought most."
    assert messages[1].additional_kwargs["sql"] == "SELECT 1"
    assert messages[2].additional_kwargs["understood_as"] == "Top customer for export sales in FY 2026-27?"
    assert history and len(history) == 2 and list(history) == EARLIER and history.session_id == "7"
    assert not memory.ChatHistory() and memory.ChatHistory(None).messages == []


def test_only_the_last_context_size_questions_are_kept():
    many = [SimpleNamespace(text=f"Q{n}", understood_as="", answer="", sql="") for n in range(1, 7)]
    assert [m.content for m in memory.ChatHistory(many).messages[0::2]] == ["Q4", "Q5", "Q6"]


def test_the_rewrite_list_is_numbered_with_the_latest_marked():
    """The format the 27-Oct fix needs ("and for sep 2026?" must build on the LATEST question)."""
    assert memory.rewrite_earlier(memory.ChatHistory(EARLIER).messages) == (
        "1. who is our top customer in japan\n2. Top customer for export sales in FY 2026-27? (latest)")


def test_the_sql_request_shows_each_earlier_question_with_its_sql_and_answer():
    text = memory.sql_earlier(memory.ChatHistory(EARLIER).messages)
    assert text == (agent.EARLIER_HEAD + "\n"
                    + "1. Question: who is our top customer in japan\n   SQL: SELECT 1\n   Answer: Sakura Ltd bought most.\n"
                    + "2. Question: and for export?\n   Understood as: Top customer for export sales in FY 2026-27?\n"
                    + "   SQL: (no SQL - not answered with data)\n   Answer: \n")
    long = memory.ChatHistory([SimpleNamespace(text="q", understood_as="", answer="a" * 400, sql="S" * 1300)])
    cut = memory.sql_earlier(long.messages)
    assert "S" * agent.CONTEXT_SQL_CHARS + " ..." in cut and "a" * agent.CONTEXT_ANSWER_CHARS + " ..." in cut
    assert memory.sql_earlier([]) == "" and memory.latest_question([]) == ""
    assert memory.latest_question(memory.ChatHistory(EARLIER).messages) == "Top customer for export sales in FY 2026-27?"


def test_the_rewrite_reads_the_chat_memory_without_runnable_with_message_history(monkeypatch):
    """The rewrite step reads the earlier questions from the chat memory (ChatHistory) and sends them to the
    plain rewrite chain as a numbered list (03-Nov: RunnableWithMessageHistory is deprecated in favour of
    LangGraph). Nothing is handed back to the memory: agent.ask() saves the whole Question row."""
    class SpyHistory(memory.ChatHistory):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.loaded, self.handed_back = 0, []

        @property
        def messages(self):
            self.loaded += 1
            return super().messages

        def add_messages(self, messages):
            self.handed_back.extend(messages)
            super().add_messages(messages)

    seen = []
    model = RunnableLambda(lambda prompt: seen.append(prompt.to_messages()) or AIMessage("Top customer in Sep 2026?"))
    monkeypatch.setattr(llm, "make_llm", lambda name, max_tokens, effort: model)
    history = SpyHistory(EARLIER, session_id="42")
    result = agent.AskResult(text="and for sep 2026?")

    assert agent.rewrite_follow_up(result, history) == "Top customer in Sep 2026?" and history.loaded >= 1
    assert "1. who is our top customer in japan\n2. Top customer for export sales in FY 2026-27? (latest)" in seen[0][-1].content
    assert "New question: and for sep 2026?" in seen[0][-1].content
    assert history.handed_back == []
    assert not hasattr(chains, "rewrite_with_memory")


@pytest.mark.django_db
def test_the_chat_memory_is_loaded_from_the_history_db_and_never_written_twice(user):
    chat = Conversation.objects.create(user=user, title="chat")
    made = [Question.objects.create(user=user, conversation=chat, text=f"Q{n}", answer=f"A{n}", sql="SELECT 1",
                                    status=status)
            for n, status in enumerate(["ok", "refused", "ok", "nodata", "ok"], start=1)]
    history = memory.ChatHistory.for_chat(chat)
    assert history.session_id == str(chat.pk)
    assert [m.content for m in history.messages[0::2]] == ["Q3", "Q4", "Q5"]   # last 3, the refused one left out
    assert [q.text for q in memory.ChatHistory.for_chat(chat, before=made[3]).questions] == ["Q1", "Q3"]
    history.add_messages([HumanMessage("x"), AIMessage("y")])
    history.clear()
    assert Question.objects.count() == 5                                      # LangChain wrote nothing


# ---------- step H: running headers and footers are dropped from the PDF pages ----------

import re  # noqa: E402

from langchain_core.documents import Document  # noqa: E402


def test_the_real_pdfs_lose_their_running_header_and_footer(real_pages):
    for page in real_pages:
        text = page.page_content
        assert "for testing only" not in text                              # the footer line
        assert not re.search(r"(?m)^Page \d+$", text)                      # the page number
        assert not re.search(r"(?m)^Demo Pumps Pvt\. Ltd\.  -  ", text)    # the running header
    chunks = pdfs.split_pages(real_pages)
    first = next(c for c in chunks if c.metadata["id"] == "sales_terms_and_discount_policy-p2-01")
    assert first.page_content.startswith("4. Discount policy")              # the chunk starts with real content


def _page(text, number):
    return Document(page_content=text, metadata={"page": number})


def test_only_lines_repeated_at_the_edges_of_every_page_are_dropped():
    """The header and 'Page N' go; a line repeated in the middle of the pages and a table's last number stay."""
    pages = [_page("ACME - Guide\nPage 1\nIntro\na\nsame middle line\nb\nc\nd\nModel\n12", 0),
             _page("ACME  -  guide\nPage 2\nSafety\ne\nsame middle line\nf\ng\nh\nWeight\n12", 1)]

    cleaned = pdfs.drop_running_lines(pages)

    assert cleaned[0].page_content == "Intro\na\nsame middle line\nb\nc\nd\nModel\n12"
    assert cleaned[1].page_content == "Safety\ne\nsame middle line\nf\ng\nh\nWeight\n12"


def test_a_one_page_pdf_is_left_as_it_is():
    [page] = pdfs.drop_running_lines([_page("ACME - Guide\nPage 1\nIntro", 0)])
    assert page.page_content == "ACME - Guide\nPage 1\nIntro"
