"""The vector store: the docs/ pieces and their vectors, kept in a Qdrant server
(QDRANT_URL in .env, default http://127.0.0.1:6333; API key in QDRANT_API_KEY), e.g. in Docker.

rebuild(chunks)               drop the collection and fill it again (used by manage.py ingest_docs)
search(question, top_k=5)     the top_k chunks closest to the question (used by the agent)
all_pieces()                  every stored chunk, read-only (used by the Documents page)
describe()                    which vector DB is used, for messages (never shows the API key)

Qdrant gets OUR OWN vectors from embed.py and compares them by cosine similarity; it never uses
or downloads a model of its own.
`path` is only given by tests and tools: it names an in-process, in-memory store (no server,
nothing written to disk - Qdrant's on-disk local mode does not really delete a collection on
Windows, so it is not used).
"""
import logging
import os
import threading
import time
import uuid
import warnings
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from . import embed

log = logging.getLogger(__name__)

COLLECTION = os.getenv("QDRANT_COLLECTION", "").strip() or "mi_docs"  # its own: never the main project's nop_docs
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"  # not "localhost": on Windows that tries IPv6 first and costs ~4 s per call
QDRANT_TIMEOUT = 10        # seconds per request to the Qdrant server
QDRANT_BATCH = 64          # points per upsert
VECTOR_SIZE = 768          # BAAI/bge-base-en-v1.5; only used to create an empty collection

STORE_EMPTY = "The document store is empty - run: python manage.py ingest_docs"
QDRANT_DOWN = "The vector database (Qdrant) is not reachable - an admin must start it."
QDRANT_REFUSED = "The vector database (Qdrant) refused the connection - check QDRANT_API_KEY in .env."

# every chunk id ('sql_examples-007') always gets the same Qdrant point id
_POINT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "nop-ai/nop_docs")
_qdrant_clients = {}       # one client per server / in-memory store, reused for the life of the process


class VectorStoreUnavailable(Exception):
    """The vector DB server cannot be used: not running, or it refused the API key.
    The message is safe to show to users (no key, no internals)."""


# ------------------------------------------------------------------ settings
def qdrant_url():
    """The Qdrant server from .env (QDRANT_URL), else http://127.0.0.1:6333."""
    return os.getenv("QDRANT_URL", "").strip() or DEFAULT_QDRANT_URL


def describe():
    """The vector DB in plain words, e.g. 'Qdrant - http://127.0.0.1:6333'. Never the key."""
    parts = urlsplit(qdrant_url())
    host = parts.netloc.rsplit("@", 1)[-1]  # leave out any user:password@ in the URL
    return f"Qdrant - {urlunsplit((parts.scheme, host, parts.path, '', ''))}"


def point_id(chunk_id):
    """Qdrant point ids must be numbers or UUIDs: the same chunk id always gives the same UUID."""
    return str(uuid.uuid5(_POINT_NAMESPACE, chunk_id))


# ------------------------------------------------------------------ clients and errors
def _local_key(path):
    return ("memory", str(Path(path).resolve()))


def _client(path=None):
    """The Qdrant server from .env, or (tests / tools) the in-process, in-memory store named `path`."""
    from qdrant_client import QdrantClient  # imported here: the import itself is slow

    api_key = os.getenv("QDRANT_API_KEY", "").strip() or None
    key = _local_key(path) if path else ("url", qdrant_url(), api_key)
    client = _qdrant_clients.get(key)
    if client is None:
        if path:
            client = QdrantClient(location=":memory:")
        else:
            with warnings.catch_warnings():
                if urlsplit(qdrant_url()).hostname in ("localhost", "127.0.0.1"):
                    # the key never leaves this computer, so plain http is fine here
                    warnings.filterwarnings("ignore", "Api key is used with an insecure connection")
                client = QdrantClient(url=qdrant_url(), api_key=api_key, timeout=QDRANT_TIMEOUT,
                                      check_compatibility=False)
        _qdrant_clients[key] = client
    return client


def close_clients():
    """Close every Qdrant client this process opened (in-memory test stores are then gone)."""
    for client in _qdrant_clients.values():
        try:
            client.close()
        except Exception:  # closing is best effort
            pass
    _qdrant_clients.clear()


@contextmanager
def _qdrant_errors():
    """Turn 'server not running' / 'wrong API key' into VectorStoreUnavailable (a safe message)."""
    import httpx
    from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

    try:
        yield
    except UnexpectedResponse as exc:
        if exc.status_code in (401, 403):
            log.warning("Qdrant at %s refused the API key (HTTP %s)", describe(), exc.status_code)
            raise VectorStoreUnavailable(QDRANT_REFUSED) from None
        raise
    except (ResponseHandlingException, httpx.HTTPError, ConnectionError, TimeoutError) as exc:
        log.warning("Qdrant at %s is not reachable (%s)", describe(), type(exc).__name__)
        raise VectorStoreUnavailable(QDRANT_DOWN) from None


# ------------------------------------------------------------------ public functions
def rebuild(chunks, path=None):
    """Drop the COLLECTION, create it again and add every chunk with its vector.
    chunks = list of dicts from chunking.load_docs(). Returns the number of chunks stored."""
    from qdrant_client import models

    vectors = embed.embed_documents([c.get("embed_text", c["text"]) for c in chunks]) if chunks else []
    points = [models.PointStruct(id=point_id(c["id"]), vector=vector,
                                 payload={"id": c["id"], "text": c["text"], "source": c["source"],
                                          "heading": c["heading"], "kind": c["kind"]})
              for c, vector in zip(chunks, vectors)]
    client = _client(path)
    with _qdrant_errors():
        if client.collection_exists(COLLECTION):
            client.delete_collection(COLLECTION)
        client.create_collection(COLLECTION, vectors_config=models.VectorParams(
            size=len(vectors[0]) if vectors else VECTOR_SIZE,
            distance=models.Distance.COSINE))  # compare vectors by cosine similarity
        for start in range(0, len(points), QDRANT_BATCH):
            client.upsert(COLLECTION, points=points[start:start + QDRANT_BATCH], wait=True)
        return client.count(COLLECTION, exact=True).count


# the seconds the last search() of this thread spent turning the question into a vector (embed_secs);
# per thread, so two people asking at the same time do not mix their times
last_search = threading.local()


def search(question, top_k=5, path=None):
    """The top_k chunks closest to the question, best first.

    Returns a list of dicts: {text, source (file name), heading, kind ('table' | 'rule' |
    'example'), score (cosine similarity, 1.0 = same meaning)}. Step 4 relies on this shape.
    """
    client = _client(path)
    with _qdrant_errors():
        if not client.collection_exists(COLLECTION):
            raise RuntimeError(STORE_EMPTY)
        started = time.perf_counter()
        vector = embed.embed_query(question)
        last_search.embed_secs = time.perf_counter() - started  # the agent shows it as its own step
        result = client.query_points(COLLECTION, query=vector, limit=top_k, with_payload=True)
    return [{"text": p.payload["text"], "source": p.payload["source"],
             "heading": p.payload["heading"], "kind": p.payload["kind"],
             "score": round(p.score, 4)}  # Qdrant's cosine score is the similarity itself
            for p in result.points]


def all_pieces(path=None):
    """Every stored chunk in id order, read-only: nothing is embedded or written.

    Returns a list of dicts: {id, text, source, heading, kind}; [] when the store was never built.
    """
    if path and _local_key(path) not in _qdrant_clients:  # a test store that was never built
        return []
    client = _client(path)
    pieces, offset = [], None
    with _qdrant_errors():
        if not client.collection_exists(COLLECTION):
            return []
        while True:
            points, offset = client.scroll(COLLECTION, limit=256, offset=offset,
                                           with_payload=True, with_vectors=False)
            pieces += [{"id": p.payload["id"], "text": p.payload["text"],
                        "source": p.payload["source"], "heading": p.payload["heading"],
                        "kind": p.payload["kind"]} for p in points]
            if offset is None:
                break
    return sorted(pieces, key=lambda piece: piece["id"])
