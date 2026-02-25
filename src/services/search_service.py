"""
SearchService — hybrid BM25 + kNN search.

Encapsulates all read/search operations so the same logic can be consumed
by the CLI, a REST endpoint, or a test without modification.

Dependency injection pattern
-----------------------------
``store`` and ``embedder`` are injected via constructor.
Production code uses ``src.services.factories.make_search_service()``.
"""

from __future__ import annotations

import logging
from typing import Any

from src.ports import EmbedderPort, SearchStorePort

logger = logging.getLogger(__name__)


class SearchService:
    """Provides hybrid semantic + keyword search over the listings index."""

    def __init__(self, store: SearchStorePort, embedder: EmbedderPort) -> None:
        self._store = store
        self._embedder = embedder

    def search(
        self,
        query: str,
        *,
        listing_type: str | None = None,
        category: str | None = None,
        max_price: int | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Execute a hybrid search (BM25 + kNN vector) and return ranked results.

        Args:
            query:        Free-text query string.
            listing_type: ``"sell"`` | ``"buy"`` | ``None`` (all).
            category:     Category slug to filter by.
            max_price:    Maximum price filter.
            lat / lon:    Geographic origin for radius search.
            radius:       Geo-radius string, e.g. ``"10km"``.
            limit:        Maximum number of results to return.

        Returns:
            List of document dicts, each with an added ``_score`` field.
        """
        query_vector = self._embedder.embed(query)

        hits = self._store.hybrid_search(
            query_text=query,
            query_vector=query_vector,
            listing_type=listing_type,
            category=category,
            max_price=max_price,
            lat=lat,
            lon=lon,
            radius=radius,
            size=limit,
        )

        logger.debug("Search '%s' returned %d hits", query, len(hits))
        return hits
