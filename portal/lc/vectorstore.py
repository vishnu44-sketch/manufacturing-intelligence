"""LangChain step B: the Qdrant search as LangChain objects - QdrantVectorStore and its retriever.

It reads the same collection as the classic rag/store.py (QDRANT_COLLECTION in .env, mi_docs) and
never the main project's nop_docs. The notes' details (heading, kind, source) are read from the
'metadata' field that store.rebuild() writes for LangChain; the note text from 'text'.

get_retriever(k)  the LangChain way: retriever.invoke("question") -> the k closest notes as Documents
search(question)  the same result as store.search() - list of {text, source, heading, kind, score} -
                  so the agent can use either version (step D)
"""
import time

from ..rag import store
from .embeddings import get_embeddings

MAIN_PROJECT_COLLECTION = "nop_docs"  # the company project's index on the same Qdrant: never used here
WRONG_COLLECTION = ("QDRANT_COLLECTION is nop_docs - the main project's index. This copy must use its own "
                    "collection (mi_docs).")

_stores = {}  # (collection, test path) -> QdrantVectorStore, made once


class WrongCollection(RuntimeError):
    """The collection in .env is the main project's one."""


def collection_name():
    """The collection to read: store.COLLECTION; WrongCollection for the main project's nop_docs."""
    if store.COLLECTION == MAIN_PROJECT_COLLECTION:
        raise WrongCollection(WRONG_COLLECTION)
    return store.COLLECTION


def get_vectorstore(path=None):
    """QdrantVectorStore on our collection (made once). path = a test store, as in store.search().
    RuntimeError(STORE_EMPTY) when the collection was never built; VectorStoreUnavailable when Qdrant is down."""
    from langchain_qdrant import QdrantVectorStore  # imported here: the import itself is slow

    name = collection_name()
    key = (name, store._local_key(path) if path else None)
    if key not in _stores:
        client = store._client(path)
        with store._qdrant_errors():
            if not client.collection_exists(name):
                raise RuntimeError(store.STORE_EMPTY)
            _stores[key] = QdrantVectorStore(client=client, collection_name=name, embedding=get_embeddings(),
                                             content_payload_key="text", metadata_payload_key="metadata")
    return _stores[key]


def get_retriever(k=5, path=None):
    """The LangChain retriever: retriever.invoke("question") -> the k closest notes (Documents)."""
    return get_vectorstore(path).as_retriever(search_kwargs={"k": k})


def search(question, top_k=5, path=None):
    """The top_k notes closest to the question, best first, like store.search(); the embedding time is kept
    in store.last_search.embed_secs, so the time box can show it."""
    vectorstore = get_vectorstore(path)
    started = time.perf_counter()
    vector = get_embeddings().embed_query(question)
    store.last_search.embed_secs = time.perf_counter() - started
    with store._qdrant_errors():
        found = vectorstore.similarity_search_with_score_by_vector(vector, k=top_k)
    return [{"text": doc.page_content, "source": doc.metadata.get("source", ""),
             "heading": doc.metadata.get("heading", ""), "kind": doc.metadata.get("kind", ""),
             "score": round(score, 4)}
            for doc, score in found]


def clear():
    """Forget the made stores (tests: a test store is built again)."""
    _stores.clear()
