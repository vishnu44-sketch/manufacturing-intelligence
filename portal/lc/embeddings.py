"""LangChain step B: the embedding model as a LangChain object (FastEmbedEmbeddings) - runs on this computer, no key needed.

The model name comes from .env (EMBED_MODEL, default BAAI/bge-base-en-v1.5).
Its files (about 210 MB) are downloaded once into <repo>/.fastembed_cache.
Two kinds of vectors: 'passage' vectors for the notes (embed_documents, manage.py ingest_docs) and
'query' vectors for a question (embed_query, every search).
"""
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

REPO_DIR = Path(__file__).resolve().parents[2]  # the folder that holds manage.py
CACHE_DIR = REPO_DIR / ".fastembed_cache"
DEFAULT_MODEL = "BAAI/bge-base-en-v1.5"

load_dotenv(REPO_DIR / ".env")  # does nothing if Django already read .env
# Windows cannot make the shortcuts (symlinks) the model download prefers - hide that warning
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def model_name():
    """The embedding model to use (from .env, else the default)."""
    return os.getenv("EMBED_MODEL", "").strip() or DEFAULT_MODEL


@lru_cache(maxsize=1)
def get_embeddings():
    """FastEmbedEmbeddings, made once (loading the model takes a few seconds) and reused afterwards."""
    from langchain_community.embeddings import FastEmbedEmbeddings  # imported here: the import itself is slow

    return FastEmbedEmbeddings(model_name=model_name(), cache_dir=str(CACHE_DIR),
                               doc_embed_type="passage")  # notes: FastEmbed's passage_embed
