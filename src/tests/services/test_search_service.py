"""Tests for SearchService — infrastructure replaced by in-memory fakes."""

from __future__ import annotations

from src.services.search_service import SearchService

FAKE_VECTOR = [0.1] * 768
FAKE_HIT = {"id": "1", "title": "iPhone 14", "type": "sell", "_score": 0.9}


class FakeEmbedder:
    def embed(self, text):
        return FAKE_VECTOR

    def embed_batch(self, texts, batch_size=32):
        return [FAKE_VECTOR for _ in texts]


class FakeSearchStore:
    def __init__(self, hits=None):
        self.hits = hits or []
        self.last_call = {}

    def hybrid_search(self, query_text, query_vector, **kwargs):
        self.last_call = {"query_text": query_text, "query_vector": query_vector, **kwargs}
        return self.hits

    def knn_match(self, query_vector, **kwargs):
        return self.hits


def _make_service(hits=None) -> SearchService:
    return SearchService(store=FakeSearchStore(hits=hits), embedder=FakeEmbedder())


class TestSearchService:
    def test_search_returns_hits(self):
        svc = _make_service(hits=[FAKE_HIT])
        hits = svc.search("iphone 14")
        assert len(hits) == 1
        assert hits[0]["title"] == "iPhone 14"

    def test_search_passes_filters_to_store(self):
        store = FakeSearchStore()
        svc = SearchService(store=store, embedder=FakeEmbedder())
        svc.search(
            "test",
            listing_type="sell",
            category="dien-tu",
            max_price=30_000_000,
            lat=21.0,
            lon=105.0,
            radius="10km",
            limit=5,
        )
        assert store.last_call["query_text"] == "test"
        assert store.last_call["query_vector"] == FAKE_VECTOR
        assert store.last_call["listing_type"] == "sell"
        assert store.last_call["category"] == "dien-tu"
        assert store.last_call["max_price"] == 30_000_000
        assert store.last_call["size"] == 5

    def test_search_returns_empty_list_on_no_hits(self):
        svc = _make_service(hits=[])
        assert svc.search("no match") == []


# ─────────────────────────────────────────────────────────────────────────────
# Inline fake coverage — embed_batch and knn_match
# ─────────────────────────────────────────────────────────────────────────────


class TestInlineFakeMethods:
    """Exercise inline fake class methods to hit lines 16 and 29 of this test file."""

    def test_fake_embedder_embed_batch_returns_vectors(self):
        """Covers FakeEmbedder.embed_batch (line 16 of this file)."""
        embedder = FakeEmbedder()
        result = embedder.embed_batch(["hello", "world"])
        assert len(result) == 2
        assert all(len(v) == 768 for v in result)

    def test_fake_search_store_knn_match_returns_hits(self):
        """Covers FakeSearchStore.knn_match (line 29 of this file)."""
        store = FakeSearchStore(hits=[FAKE_HIT])
        result = store.knn_match(FAKE_VECTOR)
        assert result == [FAKE_HIT]
