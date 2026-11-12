"""LangChain step G: reading PDFs - load them, cut them into chunks and keep them in their own Qdrant collection.

The PDFs in pdfs/ (company documents: catalogue, warranty, sales terms, maintenance guide) go into a
separate collection (QDRANT_PDF_COLLECTION in .env, default mi_pdfs) - never the SQL notes' mi_docs and
never the main project's nop_docs. Step H: agent.py sends document questions here and answers them from
the closest chunks (the page is the source).

load_pdfs()           every PDF as LangChain Documents, one per page (source, page from 1, title), without
                      the running headers and footers that repeat on every page (drop_running_lines)
split_pages(pages)    the pages cut into chunks of at most 800 characters, each with a stable id
rebuild()             load + split + embed + store everything again (used by manage.py ingest_pdfs)
search_pdfs(q, k)     the k chunks closest to the question: list of {text, source, title, page, score}
"""
import os
import re
from pathlib import Path

from ..rag import store
from .embeddings import get_embeddings
from .vectorstore import MAIN_PROJECT_COLLECTION, WrongCollection

PDF_DIR = Path(__file__).resolve().parents[2] / "pdfs"
COLLECTION = os.getenv("QDRANT_PDF_COLLECTION", "").strip() or "mi_pdfs"
CHUNK_SIZE = 800     # characters per chunk: about one section of a page
CHUNK_OVERLAP = 100  # the end of one chunk starts the next, so a sentence cut in two is still found
EDGE_LINES = 4       # running headers / footers are looked for in the first and last 4 lines of a page

PDF_STORE_EMPTY = "The PDF store is empty - run: python manage.py ingest_pdfs"

_stores = {}  # (collection, test path) -> QdrantVectorStore, made once


class NoPdfs(RuntimeError):
    """The PDF folder is missing or has no PDF files in it."""


def collection_name():
    """The PDFs' own collection; WrongCollection for nop_docs or the SQL notes' collection."""
    if COLLECTION == MAIN_PROJECT_COLLECTION:
        raise WrongCollection(f"QDRANT_PDF_COLLECTION is {COLLECTION} - the main project's index. The PDFs "
                              "must use their own collection (mi_pdfs).")
    if COLLECTION == store.COLLECTION:
        raise WrongCollection(f"QDRANT_PDF_COLLECTION is {COLLECTION} - the SQL notes' collection. The PDFs "
                              "must use their own collection (mi_pdfs).")
    return COLLECTION


def _readable_title(file):
    """'warranty_and_returns_policy.pdf' -> 'Warranty and returns policy' (for a PDF without a title)."""
    return file.stem.replace("_", " ").replace("-", " ").strip().capitalize()


def load_pdfs(folder=PDF_DIR):
    """Every *.pdf in the folder (in name order) as LangChain Documents, one per page.
    metadata: source (file name), page (1 = first page) and title. NoPdfs when there is nothing to read."""
    from langchain_community.document_loaders import PyPDFLoader  # imported here: the import itself is slow

    folder = Path(folder)
    if not folder.is_dir():
        raise NoPdfs(f"The PDF folder {folder} does not exist - create it and put the PDFs in it.")
    files = sorted(folder.glob("*.pdf"), key=lambda file: file.name.lower())
    if not files:
        raise NoPdfs(f"No PDF files found in {folder} - put the PDFs there first.")

    pages = []
    for file in files:
        for page in drop_running_lines(PyPDFLoader(str(file)).load()):
            title = (page.metadata.get("title") or "").strip()
            if title.lower() in ("", "untitled", "(unspecified)"):  # what PDF makers write when there is none
                title = _readable_title(file)
            # PyPDFLoader counts pages from 0; people (and the answer's "see page 2") count from 1
            page.metadata = {"source": file.name, "page": page.metadata.get("page", 0) + 1, "title": title}
            pages.append(page)
    return pages


def _line_key(line):
    """A line as compared between pages: spaces and case ignored, every number as '#' ('Page 2' = 'Page 1')."""
    return re.sub(r"\d+", "#", " ".join(line.split())).lower()


def drop_running_lines(pages):
    """The pages of ONE PDF without their running headers and footers: the lines found near the top or the
    bottom (EDGE_LINES) of every page. Otherwise every page's first chunk starts with the same company line
    and page number, and those words pull the search towards the wrong page. Needs 2 pages or more; a line
    of only numbers (e.g. a table's last value) never counts as a running line."""
    def edges(lines):
        return set(range(min(EDGE_LINES, len(lines)))) | set(range(max(0, len(lines) - EDGE_LINES), len(lines)))

    if len(pages) < 2:
        return pages
    texts = [[line for line in page.page_content.splitlines() if line.strip()] for page in pages]
    running = set.intersection(*({_line_key(lines[i]) for i in edges(lines)} for lines in texts))
    running = {key for key in running if re.search(r"[a-z]", key)}
    if running:
        for page, lines in zip(pages, texts):
            near_edge = edges(lines)
            page.page_content = "\n".join(line for i, line in enumerate(lines)
                                          if not (i in near_edge and _line_key(line) in running))
    return pages


def split_pages(pages):
    """The pages cut into chunks (RecursiveCharacterTextSplitter: paragraphs first, then lines, then words).
    Every chunk keeps its page's details and gets kind 'pdf' and a stable id such as
    'warranty_and_returns_policy-p1-01' (file, page, chunk number on that page)."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    chunks = []
    for page in pages:
        for number, chunk in enumerate(splitter.split_documents([page]), start=1):
            stem = Path(page.metadata["source"]).stem
            chunk.metadata.update(id=f"{stem}-p{page.metadata['page']}-{number:02d}", kind="pdf")
            chunks.append(chunk)
    return chunks


def _vectorstore(client, name, path):
    """QdrantVectorStore on the PDF collection, made once per collection and store."""
    from langchain_qdrant import QdrantVectorStore  # imported here: the import itself is slow

    key = (name, store._local_key(path) if path else None)
    if key not in _stores:
        _stores[key] = QdrantVectorStore(client=client, collection_name=name, embedding=get_embeddings(),
                                         content_payload_key="text", metadata_payload_key="metadata")
    return _stores[key]


def rebuild(folder=PDF_DIR, path=None):
    """Drop the PDF collection, create it again (cosine) and store every chunk with its vector.
    path = a test store, as in vectorstore.rebuild(). Returns {pdfs, pages, chunks}: the counts stored."""
    from qdrant_client import models

    name = collection_name()
    pages = load_pdfs(folder)
    chunks = split_pages(pages)
    size = len(get_embeddings().embed_query("vector size"))  # 768 for BAAI/bge-base-en-v1.5
    client = store._client(path)
    with store._qdrant_errors():
        if client.collection_exists(name):
            client.delete_collection(name)
        client.create_collection(name, vectors_config=models.VectorParams(size=size,
                                                                          distance=models.Distance.COSINE))
        _stores.pop((name, store._local_key(path) if path else None), None)
        # the same chunk id always gets the same point id, so a rebuild gives the same points
        _vectorstore(client, name, path).add_documents(
            chunks, ids=[store.point_id(chunk.metadata["id"]) for chunk in chunks],
            batch_size=store.QDRANT_BATCH, wait=True)
        stored = client.count(name, exact=True).count
    return {"pdfs": len({page.metadata["source"] for page in pages}), "pages": len(pages), "chunks": stored}


def search_pdfs(question, k=4, path=None):
    """The k PDF chunks closest to the question, best first: list of {text, source, title, page, score}
    (score = cosine similarity, 1.0 = same meaning). RuntimeError(PDF_STORE_EMPTY) when never built."""
    name = collection_name()
    client = store._client(path)
    with store._qdrant_errors():
        if not client.collection_exists(name):
            raise RuntimeError(PDF_STORE_EMPTY)
        found = _vectorstore(client, name, path).similarity_search_with_score(question, k=k)
    return [{"text": doc.page_content, "source": doc.metadata.get("source", ""),
             "title": doc.metadata.get("title", ""), "page": doc.metadata.get("page"),
             "score": round(score, 4)}
            for doc, score in found]


def clear():
    """Forget the made stores (tests: a test store is built again)."""
    _stores.clear()
