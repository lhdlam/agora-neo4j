"""
Elasticsearch client wrapper.
Handles index lifecycle, search, kNN, hybrid search, and CRUD.
"""

from __future__ import annotations

import functools
import logging
from typing import Any

from elasticsearch import Elasticsearch, NotFoundError
from elasticsearch.helpers import bulk

from src.config import settings
from src.domain.models import ListingStatus

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Index mapping
# ─────────────────────────────────────────────────────────────────────────────
INDEX_MAPPING: dict[str, Any] = {
    "settings": {
        # ES_NUM_SHARDS / ES_NUM_REPLICAS come from settings (default: 1 shard, 0 replicas).
        # Single-node dev: 1 shard, 0 replicas → cluster stays GREEN.
        # Production: raise shard count based on data volume; replicas ≥ 1 for HA.
        "number_of_shards": settings.ES_NUM_SHARDS,
        "number_of_replicas": settings.ES_NUM_REPLICAS,
        "refresh_interval": "1s",
    },
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "type": {"type": "keyword"},
            "title": {"type": "text", "analyzer": "standard"},
            "description": {"type": "text", "analyzer": "standard"},
            "category": {"type": "keyword"},
            "price": {"type": "long"},
            "price_currency": {"type": "keyword"},
            "budget_min": {"type": "long"},
            "budget_max": {"type": "long"},
            "location": {"type": "keyword"},
            "district": {"type": "keyword"},
            "city": {"type": "keyword"},
            "country": {"type": "keyword"},
            "geo_location": {"type": "geo_point"},
            "tags": {"type": "keyword"},
            "status": {"type": "keyword"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "contact": {
                "type": "nested",
                "properties": {
                    "name": {"type": "keyword"},
                    "phone": {"type": "keyword"},
                    "email": {"type": "keyword"},
                    "preferred_chan": {"type": "keyword"},
                },
            },
            "seller_info": {
                "type": "nested",
                "properties": {
                    "condition": {"type": "keyword"},
                    "warranty_months": {"type": "integer"},
                    "brand": {"type": "keyword"},
                    "model": {"type": "keyword"},
                    "storage": {"type": "keyword"},
                    "color": {"type": "keyword"},
                    "negotiable": {"type": "boolean"},
                },
            },
            "buyer_info": {
                "type": "nested",
                "properties": {
                    "desired_condition": {"type": "keyword"},
                    "desired_brand": {"type": "keyword"},
                    "desired_model": {"type": "keyword"},
                    "desired_storage": {"type": "keyword"},
                    "desired_color": {"type": "keyword"},
                    "urgency": {"type": "keyword"},
                },
            },
            "embedding": {
                "type": "dense_vector",
                "dims": settings.EMBEDDING_DIMS,
                "index": True,
                "similarity": "cosine",
            },
        }
    },
}


class ESClient:
    """Thin wrapper around the official elasticsearch-py client."""

    def __init__(self) -> None:
        self._client: Elasticsearch | None = None
        self._index_ensured: bool = False

    @property
    def client(self) -> Elasticsearch:
        if self._client is None:
            host: dict[str, str | int] = {
                "host": settings.ES_HOST,
                "port": settings.ES_PORT,
                "scheme": settings.ES_SCHEME,
            }
            self._client = Elasticsearch(
                hosts=[host],
                basic_auth=(settings.ES_USER, settings.ES_PASSWORD),
                request_timeout=30,
                retry_on_timeout=True,
                max_retries=3,
            )
        return self._client

    @functools.cached_property
    def _ping_client(self) -> Elasticsearch:
        """Lightweight cached client for health checks — no retries, fast timeout."""
        host: dict[str, str | int] = {
            "host": settings.ES_HOST,
            "port": settings.ES_PORT,
            "scheme": settings.ES_SCHEME,
        }
        return Elasticsearch(
            hosts=[host],
            basic_auth=(settings.ES_USER, settings.ES_PASSWORD),
            request_timeout=3,
            retry_on_timeout=False,
            max_retries=0,
        )

    # ── Index lifecycle ───────────────────────────────────────────────────────

    def ensure_index(self) -> None:
        """Create the index with mapping if it does not exist.

        Uses an instance-level flag to skip the round-trip on subsequent calls
        within the same process (the mapping never changes at runtime).
        """
        if self._index_ensured:
            return
        if not self.client.indices.exists(index=settings.ES_INDEX):
            self.client.indices.create(index=settings.ES_INDEX, body=INDEX_MAPPING)
            logger.info("Index '%s' created.", settings.ES_INDEX)
        else:
            logger.debug("Index '%s' already exists.", settings.ES_INDEX)
        self._index_ensured = True

    def delete_index(self) -> None:
        """Drop the index entirely (for re-indexing / dev reset)."""
        self.client.indices.delete(index=settings.ES_INDEX, ignore_unavailable=True)
        self._index_ensured = False  # reset cache so next ensure_index re-creates it
        logger.info("Index '%s' deleted.", settings.ES_INDEX)

    # ── Write operations ──────────────────────────────────────────────────────

    def index_doc(self, doc: dict[str, Any]) -> str:
        """Index a single document. Returns the ES document id."""
        resp = self.client.index(index=settings.ES_INDEX, id=doc["id"], document=doc)
        return str(resp["_id"])

    def bulk_index(self, docs: list[dict[str, Any]]) -> tuple[int, int]:
        """Bulk index documents. Returns (success_count, error_count).

        ``chunk_size=500`` ensures each HTTP request to ES stays well below
        the 100 MB default body limit (500 docs × ~2 KB ≈ 1 MB).
        """
        actions = [{"_index": settings.ES_INDEX, "_id": doc["id"], "_source": doc} for doc in docs]
        ok, errors = bulk(
            self.client,
            actions,
            chunk_size=500,  # cap per-request body size; ES default limit: 100 MB
            raise_on_error=False,
            stats_only=False,
        )
        error_count = len(errors) if isinstance(errors, list) else int(errors)
        return ok, error_count

    def delete_doc(self, listing_id: str) -> bool:
        """Hard-delete a document by id. Returns True if deleted."""
        try:
            self.client.delete(index=settings.ES_INDEX, id=listing_id)
        except NotFoundError:
            return False
        else:
            return True

    def get_doc(self, listing_id: str) -> dict[str, Any] | None:
        """Retrieve a document by id. Returns None if not found."""
        try:
            resp = self.client.get(index=settings.ES_INDEX, id=listing_id)
        except NotFoundError:
            return None
        else:
            return dict(resp["_source"])

    # ── Search ────────────────────────────────────────────────────────────────

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
        Hybrid search: BM25 (multi_match) + kNN (dense_vector).
        Scores are combined linearly by ES.
        """
        filters = self._build_filters(
            listing_type=listing_type,
            category=category,
            max_price=max_price,
            lat=lat,
            lon=lon,
            radius=radius,
        )

        query: dict[str, Any] = {
            "bool": {
                "should": [
                    {"match": {"title": {"query": query_text, "boost": 2.0}}},
                    {"match": {"description": {"query": query_text, "boost": 1.0}}},
                ],
                "filter": filters,
                "minimum_should_match": 0,
            }
        }

        knn: dict[str, Any] = {
            "field": "embedding",
            "query_vector": query_vector,
            "k": size,
            "num_candidates": settings.MATCH_NUM_CANDIDATES,
            "boost": 0.8,
            "filter": filters,
        }

        resp = self.client.search(
            index=settings.ES_INDEX,
            query=query,
            knn=knn,
            size=size,
            source=True,
        )
        return [{**hit["_source"], "_score": hit["_score"]} for hit in resp["hits"]["hits"]]

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
        Pure kNN search on SELL listings, filtered by business rules.
        Returns docs with ES cosine similarity score attached.
        """
        filters = self._build_filters(
            listing_type="sell",
            category=category,
            max_price=budget,
            lat=lat,
            lon=lon,
            radius=radius,
        )

        knn: dict[str, Any] = {
            "field": "embedding",
            "query_vector": query_vector,
            "k": top_k,
            "num_candidates": max(top_k * 5, settings.MATCH_NUM_CANDIDATES),
            "filter": filters,
        }

        resp = self.client.search(
            index=settings.ES_INDEX,
            knn=knn,
            size=top_k,
            source=True,
        )
        return [{**hit["_source"], "_score": hit["_score"]} for hit in resp["hits"]["hits"]]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_filters(
        self,
        listing_type: str | None,
        category: str | None,
        max_price: int | None,
        lat: float | None,
        lon: float | None,
        radius: str | None,
    ) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = [{"term": {"status": ListingStatus.ACTIVE.value}}]

        if listing_type:
            filters.append({"term": {"type": listing_type}})

        if category:
            filters.append({"term": {"category": category}})

        if max_price is not None:
            filters.append({"range": {"price": {"lte": max_price}}})

        if lat is not None and lon is not None and radius:
            filters.append(
                {
                    "geo_distance": {
                        "distance": radius,
                        "geo_location": {"lat": lat, "lon": lon},
                    }
                }
            )

        return filters

    def ping(self) -> bool:
        """
        Return True if Elasticsearch is reachable.

        Uses a separate lightweight cached client (no retries, 3 s timeout) so
        the health-check fails fast instead of waiting through 3 retry cycles.
        """
        try:
            return bool(self._ping_client.ping())
        except Exception:
            return False


@functools.lru_cache(maxsize=1)
def get_es_client() -> ESClient:
    """Return the process-wide ESClient singleton (thread-safe via lru_cache)."""
    return ESClient()
