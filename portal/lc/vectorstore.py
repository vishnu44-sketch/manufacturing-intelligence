"""LangChain step B: the SQL notes in Qdrant as LangChain objects - QdrantVectorStore and its retriever.

It uses our own collection (QDRANT_COLLECTION in .env, mi_docs) and never the main project's nop_docs.
The notes' details (heading, kind, source) are read from the 'metadata' field that rebuild() writes for
LangChain; the note text from 'text'. The Qdrant connection itself is rag/store.py.

rebuild(chunks)   drop the collection and fill it again from docs.load_docs() (used by manage.py ingest_docs)
search(question)  the notes closest to the question - list of {text, source, heading, kind, score} -
                  used by the agent, the Documents page and the MCP server
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
    """The collection to use: store.COLLECTION; WrongCollection for the main project's nop_docs."""
    if store.COLLECTION == MAIN_PROJECT_COLLECTION:
        raise WrongCollection(WRONG_COLLECTION)
    return store.COLLECTION


def rebuild(chunks, path=None):
    """Drop the collection, create it again (cosine) and add every chunk with its vector.
    chunks = list of dicts from docs.load_docs(). The vector is made from embed_text (the text without its
    SQL); the point keeps the full text, the details for the Documents page and the same details under
    'metadata' (where QdrantVectorStore reads them). The same chunk id always gets the same point id.
    path = a test store (in memory). Returns the number of chunks stored."""
    from qdrant_client import models

    name = collection_name()
    vectors = get_embeddings().embed_documents([c.get("embed_text", c["text"]) for c in chunks]) if chunks else []
    points = [models.PointStruct(id=store.point_id(c["id"]), vector=vector,
                                 payload={"id": c["id"], "text": c["text"], "source": c["source"],
                                          "heading": c["heading"], "kind": c["kind"],
                                          "metadata": {"id": c["id"], "source": c["source"],
                                                       "heading": c["heading"], "kind": c["kind"]}})
              for c, vector in zip(chunks, vectors)]
    client = store._client(path)
    with store._qdrant_errors():
        if client.collection_exists(name):
            client.delete_collection(name)
        client.create_collection(name, vectors_config=models.VectorParams(
            size=len(vectors[0]) if vectors else store.VECTOR_SIZE,
            distance=models.Distance.COSINE))  # compare vectors by cosine similarity
        _stores.pop((name, store._local_key(path) if path else None), None)
        for start in range(0, len(points), store.QDRANT_BATCH):
            client.upsert(name, points=points[start:start + store.QDRANT_BATCH], wait=True)
        return client.count(name, exact=True).count


def get_vectorstore(path=None):
    """QdrantVectorStore on our collection (made once). path = a test store (in memory).
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


def search(question, top_k=5, path=None):
    """The top_k notes closest to the question, best first: list of {text, source (file name), heading,
    kind ('table' | 'rule' | 'example'), score (cosine similarity, 1.0 = same meaning)}. The embedding
    time is kept in store.last_search.embed_secs, so the time box can show it."""
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
