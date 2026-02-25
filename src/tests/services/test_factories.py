"""Tests for src/services/factories.py — verifies DI wiring returns correct service types."""

from unittest.mock import MagicMock, patch

from src.services.listing_service import ListingService
from src.services.match_service import MatchService
from src.services.search_service import SearchService
from src.services.worker_service import WorkerService


def _patch_infra():
    """Return a context manager that patches all three infrastructure singletons."""
    return (
        patch("src.services.factories.get_es_client", return_value=MagicMock()),
        patch("src.services.factories.get_embedder", return_value=MagicMock()),
        patch("src.services.factories._get_kafka_producer", return_value=MagicMock()),
    )


class TestMakeListingService:
    def test_returns_listing_service_instance(self):
        es_patch, emb_patch, kafka_patch = _patch_infra()
        with es_patch, emb_patch, kafka_patch:
            from src.services.factories import make_listing_service

            svc = make_listing_service()
        assert isinstance(svc, ListingService)


class TestMakeSearchService:
    def test_returns_search_service_instance(self):
        es_patch, emb_patch, kafka_patch = _patch_infra()
        with es_patch, emb_patch, kafka_patch:
            from src.services.factories import make_search_service

            svc = make_search_service()
        assert isinstance(svc, SearchService)


class TestMakeMatchService:
    def test_returns_match_service_instance(self):
        es_patch, emb_patch, kafka_patch = _patch_infra()
        with es_patch, emb_patch, kafka_patch:
            from src.services.factories import make_match_service

            svc = make_match_service()
        assert isinstance(svc, MatchService)


class TestMakeWorkerService:
    def test_returns_worker_service_instance(self):
        es_patch, emb_patch, kafka_patch = _patch_infra()
        with es_patch, emb_patch, kafka_patch:
            from src.services.factories import make_worker_service

            svc = make_worker_service()
        assert isinstance(svc, WorkerService)
