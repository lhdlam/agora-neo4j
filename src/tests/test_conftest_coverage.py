"""
Tests that exercise all conftest.py shared fixtures and FakeStore/FakeEmbedder/FakeEventBus
class methods to achieve 100% coverage of conftest.py.
"""

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# FakeStore — all methods
# ─────────────────────────────────────────────────────────────────────────────


class TestFakeStore:
    def test_ensure_index_is_noop(self, fake_store):
        fake_store.ensure_index()  # should not raise

    def test_index_doc_stores_and_returns_id(self, fake_store):
        result = fake_store.index_doc({"id": "abc", "title": "test"})
        assert result == "abc"
        assert fake_store.docs["abc"]["title"] == "test"

    def test_bulk_index_stores_all_docs(self, fake_store):
        docs = [{"id": f"item-{i}"} for i in range(3)]
        ok, err = fake_store.bulk_index(docs)
        assert ok == 3
        assert err == 0
        assert len(fake_store.docs) == 3

    def test_get_doc_returns_stored_doc(self, fake_store):
        fake_store.index_doc({"id": "x123", "title": "Widget"})
        result = fake_store.get_doc("x123")
        assert result == {"id": "x123", "title": "Widget"}

    def test_get_doc_returns_none_for_missing(self, fake_store):
        assert fake_store.get_doc("nonexistent") is None

    def test_delete_doc_returns_true_when_found(self, fake_store):
        fake_store.index_doc({"id": "del-me"})
        assert fake_store.delete_doc("del-me") is True
        assert "del-me" not in fake_store.docs

    def test_delete_doc_returns_false_when_missing(self, fake_store):
        assert fake_store.delete_doc("ghost") is False

    def test_hybrid_search_returns_all_docs(self, fake_store):
        fake_store.index_doc({"id": "s1", "title": "Alpha"})
        fake_store.index_doc({"id": "s2", "title": "Beta"})
        result = fake_store.hybrid_search("query", [0.1] * 768)
        assert len(result) == 2

    def test_knn_match_returns_all_docs(self, fake_store):
        fake_store.index_doc({"id": "k1"})
        result = fake_store.knn_match([0.1] * 768)
        assert len(result) == 1

    def test_ping_returns_true(self, fake_store):
        assert fake_store.ping() is True


# ─────────────────────────────────────────────────────────────────────────────
# FakeEmbedder — all methods
# ─────────────────────────────────────────────────────────────────────────────


class TestFakeEmbedder:
    def test_embed_returns_768_dim_vector(self, fake_embedder):
        result = fake_embedder.embed("some text")
        assert len(result) == 768
        assert all(v == 0.1 for v in result)

    def test_embed_batch_returns_list_of_vectors(self, fake_embedder):
        result = fake_embedder.embed_batch(["a", "b", "c"])
        assert len(result) == 3
        assert all(len(v) == 768 for v in result)

    def test_embed_batch_custom_batch_size(self, fake_embedder):
        result = fake_embedder.embed_batch(["a", "b"], batch_size=1)
        assert len(result) == 2


# ─────────────────────────────────────────────────────────────────────────────
# FakeEventBus — all methods
# ─────────────────────────────────────────────────────────────────────────────


class TestFakeEventBus:
    def test_emit_captures_event(self, fake_event_bus):
        fake_event_bus.emit("listing.created", {"id": "abc"})
        assert len(fake_event_bus.events) == 1
        event_type, payload = fake_event_bus.events[0]
        assert event_type == "listing.created"
        assert payload["id"] == "abc"

    def test_emit_multiple_events(self, fake_event_bus):
        fake_event_bus.emit("created", {"id": "1"})
        fake_event_bus.emit("deleted", {"id": "2"})
        assert len(fake_event_bus.events) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Listing fixtures — sell_listing, buy_listing, sell_listing_with_geo
# ─────────────────────────────────────────────────────────────────────────────


class TestListingFixtures:
    def test_sell_listing_is_sell_type(self, sell_listing):
        from src.domain.models import ListingType

        assert sell_listing.type == ListingType.SELL
        assert sell_listing.seller_info is not None

    def test_buy_listing_is_buy_type(self, buy_listing):
        from src.domain.models import ListingType

        assert buy_listing.type == ListingType.BUY
        assert buy_listing.buyer_info is not None

    def test_sell_listing_with_geo_has_location(self, sell_listing_with_geo):
        assert sell_listing_with_geo.geo_location is not None
        assert sell_listing_with_geo.geo_location.lat == pytest.approx(21.0285)


# ─────────────────────────────────────────────────────────────────────────────
# Other fixtures — fake_vector, fake_sell_hit
# ─────────────────────────────────────────────────────────────────────────────


class TestMiscFixtures:
    def test_fake_vector_has_768_dims(self, fake_vector):
        assert len(fake_vector) == 768

    def test_fake_sell_hit_has_score(self, fake_sell_hit):
        assert "_score" in fake_sell_hit
        assert fake_sell_hit["type"] == "sell"
