"""LangChain step B: the embedding model as a LangChain object (FastEmbedEmbeddings).

The same model and the same cache folder as the classic rag/embed.py, and the same two kinds of vectors:
'passage' vectors for the notes (embed_documents) and 'query' vectors for a question (embed_query).
So the index the classic ingest built (collection mi_docs) works for both versions.
"""
from functools import lru_cache

from ..rag import embed


@lru_cache(maxsize=1)
def get_embeddings():
    """FastEmbedEmbeddings, made once (loading the model takes a few seconds) and reused afterwards."""
    from langchain_community.embeddings import FastEmbedEmbeddings  # imported here: the import itself is slow

    return FastEmbedEmbeddings(model_name=embed.model_name(), cache_dir=str(embed.CACHE_DIR),
                               doc_embed_type="passage")  # like embed.embed_documents(): passage_embed
