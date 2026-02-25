"""
MatchService — semantic BUY→SELL matching with business re-ranking.

Resolves a BUY intent against indexed SELL listings using:
  1. kNN vector search (semantic similarity; budget as hard ES filter)
  2. Client-side cosine threshold: discard hits below ``min_score``
  3. Re-rank: bonus for same category / same city

Dependency injection pattern
-----------------------------
``store`` and ``embedder`` are injected via constructor.
Production code uses ``src.services.factories.make_match_service()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from src.config import settings
from src.ports import EmbedderPort, SearchStorePort

logger = logging.getLogger(__name__)

# Over-fetch factor: retrieve N × candidates from ES before threshold + re-ranking.
# A higher value improves recall at the cost of more data transferred per query.
_OVERFETCH_FACTOR = 5


@dataclass(frozen=True)
class MatchResult:
    """A single re-ranked match result."""

    score: float
    listing: dict[str, Any] = field(compare=False)


class MatchService:
    """
    Resolves a BUY intent against indexed SELL listings using:

    1. kNN vector search (semantic similarity, budget as hard ES filter)
    2. Client-side threshold: discard hits below ``min_score``
    3. Re-rank: bonus for same category / same city
    """

    def __init__(self, store: SearchStorePort, embedder: EmbedderPort) -> None:
        self._store = store
        self._embedder = embedder

    def match(
        self,
        *,
        query: str | None = None,
        buy_doc: dict[str, Any] | None = None,
        category: str | None = None,
        budget: int | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius: str | None = None,
        top: int | None = None,
        min_score: float | None = None,
    ) -> list[MatchResult]:
        """
        Find and rank SELL listings matching a BUY intent.

        Provide either ``query`` (free-text) or ``buy_doc`` (an existing ES
        document dict).  Fields from ``buy_doc`` are used as fallbacks for
        ``category``, ``budget``, ``lat``, and ``lon``.

        Args:
            query:     Free-text description of the desired item.
            buy_doc:   Pre-fetched ES document for an existing BUY listing.
            category:  Category slug override.
            budget:    Maximum budget (hard filter in ES).
            lat / lon: Geographic search origin.
            radius:    Geo-radius string, e.g. ``"15km"``.
            top:       Maximum results to return after re-ranking.
            min_score: Minimum cosine similarity (0–1) to include a result.

        Returns:
            Sorted list of :class:`MatchResult` (highest score first), capped at ``top``.
        """
        _top = top or settings.MATCH_TOP_K
        _min_score = min_score if min_score is not None else settings.MATCH_MIN_COSINE_SCORE

        # ── 1. Resolve vector ─────────────────────────────────────────────────
        if buy_doc:
            raw_embedding = buy_doc.get("embedding")
            # Any non-empty stored vector is used directly to avoid re-embedding.
            if raw_embedding and len(raw_embedding) > 0:
                vector: list[float] = raw_embedding
            else:
                vector = self._embedder.embed(
                    buy_doc.get("title", "") + " " + (buy_doc.get("description") or "")
                )
            category = category or buy_doc.get("category")
            budget = budget or buy_doc.get("budget_max")
            lat = lat or (buy_doc.get("geo_location") or {}).get("lat")
            lon = lon or (buy_doc.get("geo_location") or {}).get("lon")
        elif query:
            vector = self._embedder.embed(query)
        else:
            raise ValueError("Provide either 'query' or 'buy_doc'.")

        # ── 2. kNN search — budget is a HARD ES filter ────────────────────────
        hits = self._store.knn_match(
            query_vector=vector,
            category=category,
            budget=budget,
            lat=lat,
            lon=lon,
            radius=radius,
            top_k=_top * _OVERFETCH_FACTOR,
        )

        # ── 3. Threshold + re-rank ────────────────────────────────────────────
        buy_city = (buy_doc or {}).get("city") or (buy_doc or {}).get("location")
        results = self._rerank(hits, buy_city=buy_city, category=category, min_score=_min_score)

        return results[:_top]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _rerank(
        self,
        hits: list[dict[str, Any]],
        *,
        buy_city: str | None,
        category: str | None,
        min_score: float,
    ) -> list[MatchResult]:
        """
        Apply cosine threshold and add domain-specific bonuses.

        Budget is a HARD filter handled in Elasticsearch, so it is not
        re-applied here.  Bonuses reward category and city alignment.
        """
        scored: list[MatchResult] = []

        for hit in hits:
            base = float(hit.get("_score", 0))

            if base < min_score:
                continue

            bonus = 0.0

            if category and hit.get("category") == category:
                bonus += settings.MATCH_BONUS_SAME_CATEGORY

            hit_city = hit.get("city") or hit.get("location")
            if buy_city and hit_city and buy_city == hit_city:
                bonus += settings.MATCH_BONUS_SAME_CITY

            scored.append(MatchResult(score=min(base + bonus, 1.0), listing=hit))

        scored.sort(key=lambda r: r.score, reverse=True)
        return scored
