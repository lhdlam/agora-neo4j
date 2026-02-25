"""
ListingService — orchestrates all write/read operations on listings.

This is the single entry point for create / import / get / delete operations.
It is framework-agnostic: the CLI, a FastAPI route, a background worker, or a
test can all use it by injecting the required ports.

Dependency injection pattern
-----------------------------
All infrastructure dependencies are passed via the constructor.  Production
code uses ``src.services.factories.make_listing_service()`` for wiring.
Tests pass lightweight fakes (``FakeListingStore``, ``FakeEmbedder``, etc.).
"""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any

from src.domain.embed_text import build_embed_text
from src.domain.models import Listing
from src.infrastructure.serializers import listing_to_es_doc
from src.ports import EmbedderPort, EventBusPort, ListingStorePort

logger = logging.getLogger(__name__)


class ListingService:
    """Orchestrates listing lifecycle: post, bulk import, get, and delete."""

    def __init__(
        self,
        store: ListingStorePort,
        embedder: EmbedderPort,
        event_bus: EventBusPort,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._event_bus = event_bus

    # ── Create ────────────────────────────────────────────────────────────────

    def post(self, listing: Listing) -> str:
        """
        Embed and index a single listing.

        The ``Listing`` object passed in is **not** mutated — a copy with the
        embedding attached is created internally and discarded after indexing.

        Returns:
            The document ID of the newly indexed listing.
        """
        self._store.ensure_index()
        vector = self._embedder.embed(build_embed_text(listing))
        indexed = listing.model_copy(update={"embedding": vector})
        doc = listing_to_es_doc(indexed)
        doc_id = self._store.index_doc(doc)
        self._event_bus.emit("listing.created", {"id": doc_id, "type": listing.type.value})
        logger.info("Indexed listing '%s' (id=%s)", listing.title, doc_id)
        return doc_id

    def bulk_import(
        self,
        listings: list[Listing],
        on_progress: Callable[[int, int], None] | None = None,
        batch_size: int = 32,
    ) -> tuple[int, int]:
        """
        Batch-embed and bulk-index multiple listings.

        Processes one batch at a time so memory usage is O(batch_size),
        not O(N). Each batch is embedded → serialised → indexed → discarded
        before the next batch begins.

        ``on_progress`` is called after each batch so the caller can update
        a progress bar in real time.

        Args:
            listings:    Validated ``Listing`` objects to index.
            on_progress: Optional ``callback(completed, total)`` for progress.
            batch_size:  Embedding + indexing chunk size (default 32).

        Returns:
            ``(success_count, error_count)``
        """
        self._store.ensure_index()
        total = len(listings)
        total_ok = 0
        total_errors = 0

        for batch_start in range(0, total, batch_size):
            batch = listings[batch_start : batch_start + batch_size]

            # Embed
            texts = [build_embed_text(listing) for listing in batch]
            vectors = self._embedder.embed_batch(texts, batch_size=batch_size)

            # Serialise — docs are built and immediately passed to the store
            docs = [
                listing_to_es_doc(listing.model_copy(update={"embedding": vector}))
                for listing, vector in zip(batch, vectors, strict=True)
            ]

            ok, errors = self._store.bulk_index(docs)
            total_ok += ok
            total_errors += errors

            completed = min(batch_start + len(batch), total)
            if on_progress:
                on_progress(completed, total)

        self._event_bus.emit("listing.imported", {"count": total_ok, "errors": total_errors})
        logger.info("Bulk import complete: ok=%d errors=%d", total_ok, total_errors)
        return total_ok, total_errors

    # ── Read ──────────────────────────────────────────────────────────────────

    def get(self, listing_id: str) -> dict[str, Any] | None:
        """
        Retrieve a listing by its ID.

        Returns:
            The raw document dict, or ``None`` if not found.
        """
        return self._store.get_doc(listing_id)

    # ── Delete ────────────────────────────────────────────────────────────────

    def delete(self, listing_id: str) -> bool:
        """
        Hard-delete a listing.

        Returns:
            ``True`` if the document was found and deleted.
        """
        deleted = self._store.delete_doc(listing_id)
        if deleted:
            logger.info("Deleted listing id=%s", listing_id)
        return deleted
