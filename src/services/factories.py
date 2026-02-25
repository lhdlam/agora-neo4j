"""
Service Factories — wire up services with concrete infrastructure adapters.

These functions are the **only** place in the codebase where infrastructure
singletons (``get_es_client``, ``get_embedder``, ``_get_kafka_producer``) are
imported and composed together.

Usage
-----
CLI commands and HTTP handlers call these factories to get fully wired
service instances::

    from src.services.factories import make_listing_service
    svc = make_listing_service()
    doc_id = svc.post(listing)

Tests pass ``FakeListingStore`` / ``FakeEmbedder`` / ``FakeEventBus`` directly
to the service constructors — they never call these factories.
"""

from __future__ import annotations

from src.infrastructure.embedder import get_embedder
from src.infrastructure.es_client import get_es_client
from src.infrastructure.kafka_producer import _get_kafka_producer  # noqa: PLC2701
from src.services.listing_service import ListingService
from src.services.match_service import MatchService
from src.services.search_service import SearchService
from src.services.worker_service import WorkerService


def make_listing_service() -> ListingService:
    """
    Return a production-wired :class:`ListingService`.

    Uses the process-wide ESClient, Embedder, and KafkaProducer singletons.
    """
    return ListingService(
        store=get_es_client(),
        embedder=get_embedder(),
        event_bus=_get_kafka_producer(),
    )


def make_search_service() -> SearchService:
    """
    Return a production-wired :class:`SearchService`.

    Uses the process-wide ESClient and Embedder singletons.
    """
    return SearchService(
        store=get_es_client(),
        embedder=get_embedder(),
    )


def make_match_service() -> MatchService:
    """
    Return a production-wired :class:`MatchService`.

    Uses the process-wide ESClient and Embedder singletons.
    """
    return MatchService(
        store=get_es_client(),
        embedder=get_embedder(),
    )


def make_worker_service() -> WorkerService:
    """
    Return a production-wired :class:`WorkerService`.

    The worker uses its own ListingService instance (same infrastructure
    singletons) so embedding + ES indexing happen inside the worker process.
    """
    return WorkerService(listing_service=make_listing_service())
