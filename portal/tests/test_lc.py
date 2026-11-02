"""The LangChain version (portal/lc/), built step by step next to the classic one (portal/rag/).

No test calls the real Groq API: the LLM parts use fake chat models.
Run with:  python -m pytest -q portal/tests/test_lc.py
"""
import pytest
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda

from portal.lc import chains, llm, prompts, switch, vectorstore
from portal.rag import agent, embed, store

MAIN, BACKUP = "openai/gpt-oss-120b", "qwen/qwen3.8-27b"
SQL_VALUES = {"schema": "dim_customers: customer_id, customer_name", "count": 2,
              "documents": "Example SQL ...\n\n---\n\nNOP sales month rule ...",
              "today": "02-Nov-2026 (Monday)", "earlier": "", "question": "Top 5 customers in Aug 2026?"}

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
    """An in-memory Qdrant with the three CHUNKS, built by the classic store.rebuild(); both versions read it."""
    monkeypatch.setattr(store.embed, "embed_documents", lambda texts: [VECTORS[t] for t in texts])
    monkeypatch.setattr(store.embed, "embed_query", lambda text: VECTORS[text])
    monkeypatch.setattr(vectorstore, "get_embeddings", lambda: FakeEmbeddings())
    path = tmp_path / "qdrant"
    store.rebuild(CHUNKS, path=path)
    vectorstore.clear()
    yield path
    vectorstore.clear()
    store.close_clients()


# ---------- step A: the packages and the switch ----------

def test_the_langchain_packages_are_installed():
    """The versions in requirements.txt (langchain-groq is not used: it needs groq below 1.0)."""
    from importlib.metadata import version
    assert version("langchain-core") == "1.7.3"
    assert version("langchain-openai") == "1.7.3"
    assert version("langchain-qdrant") == "1.1.0"
    assert version("langchain-community") == "0.4.2"
    assert version("langchain-text-splitters") == "1.1.3"
    assert version("groq") == "1.7.0"                       # the classic pipeline's client stays as it was


@pytest.mark.parametrize("value", ["on", "ON", " on ", "1", "true", "yes"])
def test_the_switch_turns_langchain_on(monkeypatch, value):
    monkeypatch.setenv("USE_LANGCHAIN", value)
    assert switch.use_langchain() and switch.pipeline_name() == "langchain"


@pytest.mark.parametrize("value", ["off", "", "0", "no", "maybe"])
def test_the_switch_is_off_by_default_and_for_anything_else(monkeypatch, value):
    monkeypatch.setenv("USE_LANGCHAIN", value)
    assert not switch.use_langchain() and switch.pipeline_name() == "classic"


def test_no_line_in_env_means_the_classic_version(monkeypatch):
    monkeypatch.delenv("USE_LANGCHAIN", raising=False)
    assert switch.pipeline_name() == "classic"


# ---------- step B: embeddings, QdrantVectorStore and the retriever ----------

def test_ingest_also_writes_the_metadata_langchain_reads(test_store):
    client = store._client(test_store)
    points, _ = client.scroll(store.COLLECTION, limit=10, with_payload=True)
    for point in points:
        payload = point.payload
        assert payload["metadata"] == {"id": payload["id"], "source": payload["source"],
                                       "heading": payload["heading"], "kind": payload["kind"]}


def test_the_langchain_search_gives_the_same_notes_as_the_classic_search(test_store):
    for question in ("one", "two", "three"):
        assert vectorstore.search(question, top_k=3, path=test_store) == store.search(question, top_k=3,
                                                                                         path=test_store)


def test_the_retriever_gives_langchain_documents_with_the_notes_details(test_store):
    documents = vectorstore.get_retriever(k=2, path=test_store).invoke("one")
    assert [doc.page_content for doc in documents] == ["Rule one text", "Example two text"]
    assert documents[0].metadata["heading"] == "First rule" and documents[0].metadata["kind"] == "rule"


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


def test_the_langchain_vectors_are_the_classic_vectors():
    """The real model, both ways: the classic index can be searched with LangChain's question vectors."""
    from portal.lc.embeddings import get_embeddings
    lc = get_embeddings()
    question, notes = "top customers by net sales", ["NOP sales month rule", "Example question with its SQL"]
    assert lc.embed_query(question) == pytest.approx(embed.embed_query(question), abs=1e-6)
    for got, expected in zip(lc.embed_documents(notes), embed.embed_documents(notes)):
        assert got == pytest.approx(expected, abs=1e-6)


QUESTIONS = ["Top 5 customers by net sales in FY 2026-27", "How many sales orders are open?",
             "What is our current stock value?", "net sales by state last month", "What was our profit last year?"]


def test_the_real_index_gives_the_same_5_notes_both_ways():
    """The real Qdrant and collection (mi_docs): same notes, same order, same scores."""
    try:
        classic = [store.search(question, top_k=5) for question in QUESTIONS]
    except Exception as exc:  # Qdrant down or never built: like the other real-service tests
        pytest.skip(f"vector store not available (start Qdrant, run manage.py ingest_docs): {exc}")
    vectorstore.clear()
    for question, expected in zip(QUESTIONS, classic):
        got = vectorstore.search(question, top_k=5)
        assert [hit["heading"] for hit in got] == [hit["heading"] for hit in expected], question
        assert [hit["score"] for hit in got] == pytest.approx([hit["score"] for hit in expected], abs=1e-3)
        assert [hit["kind"] for hit in got] == [hit["kind"] for hit in expected]


# ---------- step C: the chat model, the prompt templates and the chains (fake AI only) ----------

def classic_sql_messages(values):
    """The SQL call's messages as the classic agent._answer() builds them by hand."""
    return [{"role": "system", "content": agent.SQL_SYSTEM_PROMPT},
            {"role": "user", "content": agent.SQL_REQUEST.format(**values)}]


def test_the_sql_template_gives_the_same_messages_as_the_classic_code():
    messages = prompts.SQL_PROMPT.format_messages(**SQL_VALUES)
    classic = classic_sql_messages(SQL_VALUES)
    assert [type(m) for m in messages] == [SystemMessage, HumanMessage]
    assert [m.content for m in messages] == [m["content"] for m in classic]


def test_a_retry_adds_the_ais_reply_and_the_problem_like_the_classic_loop():
    problem = "MySQL returned an error: Unknown column 'il.amount'"
    retries = [AIMessage("```sql\nSELECT il.amount FROM fact_invoice_lines il\n```"),
               HumanMessage(prompts.RETRY_PROMPT.format(problem=problem))]
    messages = prompts.SQL_PROMPT.format_messages(**SQL_VALUES, retries=retries)
    assert len(messages) == 4 and messages[2:] == retries
    assert messages[3].content == agent.RETRY_PROMPT.format(problem=problem)


def test_the_rewrite_and_answer_templates_use_the_classic_texts():
    rewrite = prompts.REWRITE_PROMPT.format_messages(earlier="1. Top customers in Aug 2026 (latest)",
                                                     question="and for Sep?")
    assert rewrite[0].content == agent.REWRITE_SYSTEM_PROMPT
    assert rewrite[1].content == agent.REWRITE_REQUEST.format(earlier="1. Top customers in Aug 2026 (latest)",
                                                              question="and for Sep?")
    values = {"question": "Top customers?", "understood": "", "sql": "SELECT 1", "periods": "",
              "note": "2 row(s)", "table": "customer_name | net_sales_inr"}
    answer = prompts.EXPLAIN_PROMPT.format_messages(**values)
    assert [m.content for m in answer] == [agent.EXPLAIN_SYSTEM_PROMPT, agent.EXPLAIN_REQUEST.format(**values)]


def test_the_sql_chain_sends_the_filled_template_to_the_model_and_returns_its_reply():
    seen = []

    def fake_model(prompt_value):  # a stand-in for the chat model that remembers what it got
        seen.append(prompt_value.to_messages())
        return AIMessage("```sql\nSELECT 1\n```")

    reply = chains.sql_chain(RunnableLambda(fake_model)).invoke(SQL_VALUES)
    assert reply.content == "```sql\nSELECT 1\n```"
    assert [m.content for m in seen[0]] == [m["content"] for m in classic_sql_messages(SQL_VALUES)]


def test_the_chains_work_with_a_langchain_fake_chat_model():
    fake = FakeListChatModel(responses=["```sql\nSELECT 1\n```", "Aurora had the highest sales.",
                                        "Top customers in Sep 2026?"])
    assert chains.sql_chain(fake).invoke(SQL_VALUES).content == "```sql\nSELECT 1\n```"
    assert chains.as_text(chains.answer_chain(fake)).invoke(
        {"question": "q", "understood": "", "sql": "SELECT 1", "periods": "", "note": "1 row(s)",
         "table": "x"}) == "Aurora had the highest sales."
    assert chains.as_text(chains.rewrite_chain(fake)).invoke(
        {"earlier": "1. Top customers in Aug 2026", "question": "and Sep?"}) == "Top customers in Sep 2026?"


def test_reply_info_reads_the_text_the_tokens_and_a_cut_off_reply():
    message = AIMessage(" SELECT 1 ", usage_metadata={"input_tokens": 3900, "output_tokens": 100, "total_tokens": 4000},
                        response_metadata={"finish_reason": "length"})
    assert chains.reply_info(message) == ("SELECT 1", 4000, True)
    assert chains.reply_info(AIMessage("ok", response_metadata={"finish_reason": "stop"})) == ("ok", None, False)


def test_the_main_model_has_the_classic_settings(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MODEL", MAIN)
    model = llm.main_llm(agent.SQL_MAX_TOKENS, "medium")
    assert model.model_name == MAIN and model.openai_api_base == llm.GROQ_OPENAI_URL
    assert model.temperature == 0 and model.max_tokens == 3000 and model.max_retries == 0
    assert model.extra_body == {"reasoning_effort": "medium", "include_reasoning": False}
    payload = model._get_request_payload([HumanMessage("hi")])
    assert payload["model"] == MAIN and payload["temperature"] == 0
    assert payload.get("max_completion_tokens", payload.get("max_tokens")) == 3000


def test_the_backup_model_gets_its_smaller_limit_and_its_own_setting(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MODEL", MAIN)
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", BACKUP)
    model = llm.backup_llm(agent.SQL_MAX_TOKENS, "medium")
    assert model.model_name == BACKUP and model.max_tokens == agent.FALLBACK_MAX_TOKENS
    assert model.extra_body == {"reasoning_format": "hidden"}
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", "")
    assert llm.backup_llm(agent.SQL_MAX_TOKENS, "medium") is None


def test_a_missing_key_gives_the_same_friendly_message_as_the_classic_version():
    with pytest.raises(agent.AIUnavailable) as classic:
        agent.get_groq_client()
    with pytest.raises(agent.AIUnavailable) as lc:
        llm.main_llm(agent.SQL_MAX_TOKENS, "medium")
    assert str(lc.value) == str(classic.value) == llm.MISSING_KEY


def test_no_test_can_reach_the_real_ai_through_langchain(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    with pytest.raises(AssertionError, match="use a fake chat model"):
        chains.sql_chain(llm.main_llm(agent.SQL_MAX_TOKENS, "medium")).invoke(SQL_VALUES)


# ---------- step D: the app answers through LangChain when USE_LANGCHAIN=on ----------
# (TEST_PIPELINE=langchain also runs EVERY test again through LangChain - see conftest.pipeline)

from portal.lc import calls  # noqa: E402
from portal.tests.conftest import fake_langchain_llm  # noqa: E402
from portal.tests.test_agent import (ANSWER, GOOD_SQL, HITS, ROWS, FakeMySQL, daily_limit_error,  # noqa: E402
                                     rate_limit_error, use_fake_groq)


@pytest.fixture
def lc_app(monkeypatch):
    """USE_LANGCHAIN=on with a fake AI (the tests' fake Groq behind LangChain's chains), fake notes and a fake
    MySQL; .chains = the chain of every AI call that went through portal/lc/calls.py."""
    db = FakeMySQL()
    monkeypatch.setenv("USE_LANGCHAIN", "on")
    monkeypatch.setattr(llm, "make_llm", fake_langchain_llm)
    monkeypatch.setattr(vectorstore, "search", lambda text, top_k=5, path=None: HITS)
    monkeypatch.setattr(store, "search", lambda *args, **kwargs: pytest.fail("the classic search was used"))
    monkeypatch.setattr(agent, "search", lambda *args, **kwargs: pytest.fail("the classic search was used"))
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
def test_with_the_switch_on_the_answer_comes_through_the_langchain_chains(monkeypatch, lc_app, user):
    lc_app.results = [ROWS]
    fake = use_fake_groq(monkeypatch, [(GOOD_SQL, 4000), (ANSWER, 900)])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and result.answer == ANSWER and result.row_count == 2
    assert lc_app.chains == ["sql", "answer"]                       # both AI calls went through LangChain
    assert result.sql_tokens == 4000 and result.answer_tokens == 900  # the tokens are still counted
    assert {"search", "sql_ai", "mysql", "answer_ai"} <= set(result.step_secs)
    assert fake.calls[0][0]["content"] == agent.SQL_SYSTEM_PROMPT    # the same prompt text as classic
    assert "LIMIT 2" in lc_app.calls[0]                              # our SQL guard's SQL ran on MySQL


@pytest.mark.django_db
def test_with_the_switch_off_langchain_is_never_used(monkeypatch, user):
    monkeypatch.delenv("USE_LANGCHAIN", raising=False)
    monkeypatch.setattr(calls, "chat", lambda *args: pytest.fail("LangChain was used with the switch off"))
    monkeypatch.setattr(vectorstore, "search", lambda *args, **kwargs: pytest.fail("LangChain search was used"))
    monkeypatch.setattr(agent, "search", lambda question, top_k=5: HITS)
    db = FakeMySQL()
    db.results = [ROWS]
    monkeypatch.setattr(agent.warehouse, "allowed_tables", lambda: {"dim_customers", "dim_calendar", "fact_invoice_lines"})
    monkeypatch.setattr(agent.warehouse, "schema_text", lambda: "dim_customers: customer_id, customer_name")
    monkeypatch.setattr(agent.warehouse, "run_select", db.run_select)
    monkeypatch.setattr(agent, "invoice_data_dates", lambda: None)
    use_fake_groq(monkeypatch, [GOOD_SQL, ANSWER])

    assert agent.ask("Top customers in Aug 2026?", user).answer == ANSWER


@pytest.mark.django_db
def test_a_mysql_error_goes_back_to_the_ai_through_the_sql_chains_retries(monkeypatch, lc_app, user):
    lc_app.results = [agent.warehouse.QueryError("(1054) Unknown column 'il.amount'"), ROWS]
    fake = use_fake_groq(monkeypatch, [GOOD_SQL, GOOD_SQL, ANSWER])

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
    use_fake_groq(monkeypatch, [rate_limit_error(retry_after=4), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and waits == [4.5] and result.step_secs["wait"] == 4.5


@pytest.mark.django_db
def test_the_daily_limit_moves_to_the_backup_model(monkeypatch, lc_app, user):
    monkeypatch.setenv("GROQ_MODEL", MAIN)
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", BACKUP)
    lc_app.results = [ROWS]
    fake = use_fake_groq(monkeypatch, [daily_limit_error(), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and result.model == BACKUP and result.answered_by_backup
    assert fake.models == [MAIN, BACKUP, BACKUP]


@pytest.mark.django_db
def test_an_unreachable_ai_gives_the_friendly_message(monkeypatch, lc_app, user):
    monkeypatch.setattr(agent.time, "sleep", lambda secs: None)
    request = __import__("httpx").Request("POST", "https://api.groq.com")
    use_fake_groq(monkeypatch, [__import__("groq").APIConnectionError(request=request)] * 2)

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "error" and result.answer == agent.AI_DOWN and lc_app.calls == []


def test_the_answer_values_fill_the_classic_answer_text():
    """explain_messages() (classic) is now explain_values() + the text: the same request as before."""
    result = agent.AskResult(text="Top customers?", sql="SELECT 1", columns=ROWS["columns"], rows=ROWS["rows"])
    values = agent.explain_values(result, agent.ROWS_FOR_ANSWER)
    assert agent.explain_messages(result, agent.ROWS_FOR_ANSWER)[1]["content"] == agent.EXPLAIN_REQUEST.format(**values)
    assert [m.content for m in prompts.EXPLAIN_PROMPT.format_messages(**values)] == [
        m["content"] for m in agent.explain_messages(result, agent.ROWS_FOR_ANSWER)]


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
