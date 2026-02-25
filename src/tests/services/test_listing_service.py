"""Tests for ListingService — all infrastructure replaced by in-memory fakes."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.domain.models import Category, Listing, ListingType
from src.services.listing_service import ListingService

# ── Minimal fakes (inline for clarity) ──────────────────────────────────────


class FakeStore:
    def __init__(self):
        self.docs = {}
        self.ensure_index_called = False

    def ensure_index(self):
        self.ensure_index_called = True

    def index_doc(self, doc):
        self.docs[doc["id"]] = doc
        return doc["id"]

    def bulk_index(self, docs):
        for doc in docs:
            self.docs[doc["id"]] = doc
        return len(docs), 0

    def get_doc(self, listing_id):
        return self.docs.get(listing_id)

    def delete_doc(self, listing_id):
        return self.docs.pop(listing_id, None) is not None


class FakeEmbedder:
    def embed(self, text):
        return [0.1] * 768

    def embed_batch(self, texts, batch_size=32):
        return [[0.1] * 768 for _ in texts]


class FakeEventBus:
    def __init__(self):
        self.events = []

    def emit(self, event_type, payload):
        self.events.append((event_type, payload))


def _make_listing(**kwargs) -> Listing:
    return Listing(type=ListingType.SELL, title="Test Listing", category=Category.DIEN_TU, **kwargs)


def _make_service(store=None, embedder=None, event_bus=None) -> ListingService:
    return ListingService(
        store=store or FakeStore(),
        embedder=embedder or FakeEmbedder(),
        event_bus=event_bus or FakeEventBus(),
    )


# ── Tests ────────────────────────────────────────────────────────────────────


class TestListingServicePost:
    def test_post_returns_doc_id(self):
        store = FakeStore()
        svc = _make_service(store=store)
        listing = _make_listing()
        doc_id = svc.post(listing)
        assert doc_id == listing.id
        assert doc_id in store.docs

    def test_post_stores_embedding_in_doc(self):
        store = FakeStore()
        svc = _make_service(store=store)
        listing = _make_listing()
        doc_id = svc.post(listing)
        assert store.docs[doc_id]["embedding"] == [0.1] * 768

    def test_post_does_not_mutate_original_listing(self):
        svc = _make_service()
        listing = _make_listing()
        original_embedding = listing.embedding
        svc.post(listing)
        assert listing.embedding == original_embedding  # still None

    def test_post_emits_created_event(self):
        bus = FakeEventBus()
        svc = _make_service(event_bus=bus)
        listing = _make_listing()
        svc.post(listing)
        assert len(bus.events) == 1
        event_type, payload = bus.events[0]
        assert event_type == "listing.created"
        assert payload["type"] == "sell"

    def test_post_calls_ensure_index(self):
        store = FakeStore()
        svc = _make_service(store=store)
        svc.post(_make_listing())
        assert store.ensure_index_called

    def test_post_propagates_store_errors(self):
        bad_store = FakeStore()
        bad_store.index_doc = MagicMock(side_effect=RuntimeError("ES down"))
        svc = _make_service(store=bad_store)
        with pytest.raises(RuntimeError, match="ES down"):
            svc.post(_make_listing())


class TestListingServiceBulkImport:
    def test_bulk_import_returns_counts(self):
        svc = _make_service()
        listings = [_make_listing() for _ in range(5)]
        ok, errors = svc.bulk_import(listings)
        assert ok == 5
        assert errors == 0

    def test_bulk_import_stores_all_docs(self):
        store = FakeStore()
        svc = _make_service(store=store)
        listings = [_make_listing() for _ in range(3)]
        svc.bulk_import(listings)
        assert len(store.docs) == 3

    def test_bulk_import_calls_progress_callback(self):
        svc = _make_service()
        calls = []
        svc.bulk_import(
            [_make_listing() for _ in range(3)], on_progress=lambda c, t: calls.append((c, t))
        )
        assert len(calls) > 0
        assert calls[-1][0] == 3  # completed == total on last call

    def test_bulk_import_emits_imported_event(self):
        bus = FakeEventBus()
        svc = _make_service(event_bus=bus)
        svc.bulk_import([_make_listing()])
        event_type, payload = bus.events[0]
        assert event_type == "listing.imported"
        assert payload["count"] == 1


class TestListingServiceDelete:
    def test_delete_returns_true_when_found(self):
        store = FakeStore()
        svc = _make_service(store=store)
        listing = _make_listing()
        svc.post(listing)
        assert svc.delete(listing.id) is True

    def test_delete_returns_false_when_not_found(self):
        svc = _make_service()
        assert svc.delete("does-not-exist") is False

    def test_delete_removes_doc_from_store(self):
        store = FakeStore()
        svc = _make_service(store=store)
        listing = _make_listing()
        svc.post(listing)
        svc.delete(listing.id)
        assert store.get_doc(listing.id) is None


class TestListingServiceGet:
    def test_get_returns_doc(self):
        store = FakeStore()
        svc = _make_service(store=store)
        listing = _make_listing()
        svc.post(listing)
        result = svc.get(listing.id)
        assert result is not None
        assert result["id"] == listing.id

    def test_get_returns_none_when_missing(self):
        svc = _make_service()
        assert svc.get("missing") is None
