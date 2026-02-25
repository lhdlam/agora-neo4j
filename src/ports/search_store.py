"""
SearchStorePort — abstract interface for hybrid BM25 + kNN search.

Separating search from CRUD allows the two capabilities to evolve
independently and makes ``SearchService`` testable with a fake that
returns canned hits without touching Elasticsearch.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SearchStorePort(Protocol):
    """Semantic + keyword search operations on the listings index."""

    def hybrid_search(
        self,
        query_text: str,
        query_vector: list[float],
        *,
        listing_type: str | None = None,
        category: str | None = None,
        max_price: int | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius: str | None = None,
        size: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Combined BM25 + kNN search.

        Returns:
            List of document dicts, each with an added ``_score`` key.
        """
        ...  # pragma: no cover

    def knn_match(
        self,
        query_vector: list[float],
        *,
        category: str | None = None,
        budget: int | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius: str | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Pure kNN search on SELL listings only.

        Returns:
            List of document dicts, each with an added ``_score`` key.
        """
        ...  # pragma: no cover
