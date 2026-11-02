"""python manage.py ingest_pdfs

Reads pdfs/*.pdf page by page, cuts the pages into chunks, turns every chunk into a vector and
rebuilds the PDFs' own Qdrant collection (QDRANT_PDF_COLLECTION, default mi_pdfs). The SQL notes'
collection (mi_docs) is not touched. Run it again after adding or changing a PDF.
"""
import time

from django.core.management.base import BaseCommand, CommandError

from portal.lc import pdfs
from portal.lc.vectorstore import WrongCollection
from portal.rag.store import VectorStoreUnavailable, describe


class Command(BaseCommand):
    help = "Rebuild the PDF store (Qdrant collection mi_pdfs) from pdfs/*.pdf"

    def handle(self, *args, **options):
        started = time.perf_counter()
        self.stdout.write(f"PDFs from {pdfs.PDF_DIR}, vector DB: {describe()}")
        try:
            counts = pdfs.rebuild()  # embeds every chunk (first run downloads the model once)
        except (pdfs.NoPdfs, WrongCollection, VectorStoreUnavailable) as exc:
            raise CommandError(str(exc)) from None
        seconds = time.perf_counter() - started
        self.stdout.write(self.style.SUCCESS(
            f"Stored {counts['chunks']} chunks from {counts['pdfs']} PDFs ({counts['pages']} pages) in "
            f"{describe()} (collection {pdfs.COLLECTION}) in {seconds:.1f} s"))
