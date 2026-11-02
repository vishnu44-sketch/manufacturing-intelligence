"""Turn text into vectors (embeddings) with FastEmbed - runs on this computer, no key needed.

The model name comes from .env (EMBED_MODEL, default BAAI/bge-base-en-v1.5).
Its files (about 210 MB) are downloaded once into <repo>/.fastembed_cache.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

REPO_DIR = Path(__file__).resolve().parents[2]  # the folder that holds manage.py
CACHE_DIR = REPO_DIR / ".fastembed_cache"
DEFAULT_MODEL = "BAAI/bge-base-en-v1.5"

load_dotenv(REPO_DIR / ".env")  # does nothing if Django already read .env
# Windows cannot make the shortcuts (symlinks) the model download prefers - hide that warning
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

_model = None  # loaded on first use, then kept for the life of the process


def model_name():
    """The embedding model to use (from .env, else the default)."""
    return os.getenv("EMBED_MODEL", "").strip() or DEFAULT_MODEL


def get_model():
    """Load the model once (takes a few seconds) and reuse it afterwards."""
    global _model
    if _model is None:
        from fastembed import TextEmbedding  # imported here because the import itself is slow

        _model = TextEmbedding(model_name=model_name(), cache_dir=str(CACHE_DIR))
    return _model


def embed_documents(texts):
    """One vector (list of floats) per document chunk - FastEmbed's 'passage' variant."""
    return [vector.tolist() for vector in get_model().passage_embed(list(texts))]


def embed_query(text):
    """The vector of one question - FastEmbed's 'query' variant."""
    return next(iter(get_model().query_embed(text))).tolist()
