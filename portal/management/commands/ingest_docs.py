"""python manage.py ingest_docs

Reads docs/*.md, cuts them into chunks (one per '## ' heading, LangChain's MarkdownHeaderTextSplitter),
turns every chunk into a vector (LangChain's FastEmbedEmbeddings) and rebuilds the vector store: the
Qdrant server at QDRANT_URL (collection store.COLLECTION). Run it again after every docs change.
"""
import time
from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from portal.lc.docs import load_docs
from portal.lc.vectorstore import WrongCollection, rebuild
from portal.rag import store
from portal.rag.store import VectorStoreUnavailable, describe


class Command(BaseCommand):
    help = "Rebuild the vector store (Qdrant server, QDRANT_URL in .env) from docs/*.md"

    def handle(self, *args, **options):
        started = time.perf_counter()
        docs_dir = settings.BASE_DIR / "docs"

        chunks = load_docs(docs_dir)
        if not chunks:
            raise CommandError(f"No '## ' sections found in {docs_dir}\\*.md")

        self.stdout.write(f"Chunks per file (from {docs_dir}):")
        for source, count in sorted(Counter(c["source"] for c in chunks).items()):
            self.stdout.write(f"  {source}: {count}")

        self.stdout.write(f"Vector DB: {describe()}")
        try:
            stored = rebuild(chunks)  # embeds every chunk (first run downloads the model once)
        except (VectorStoreUnavailable, WrongCollection) as exc:  # e.g. the Qdrant server is not running
            raise CommandError(str(exc)) from None
        seconds = time.perf_counter() - started
        self.stdout.write(self.style.SUCCESS(
            f"Stored {stored} chunks in {describe()} (collection {store.COLLECTION}) in {seconds:.1f} s"))
