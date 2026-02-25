"""Shared pytest fixtures for the Agora test suite."""

from __future__ import annotations

import pytest

from src.domain.models import (
    BuyerInfo,
    Category,
    Condition,
    Contact,
    GeoLocation,
    Listing,
    ListingType,
    SellerInfo,
    Urgency,
)


@pytest.fixture(autouse=True)
def _force_sync_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Ensure every test runs in sync mode regardless of the local ``.env`` file.

    ``settings`` is a module-level singleton loaded at import time, so
    ``KAFKA_WRITE_MODE=true`` in ``.env`` would otherwise bleed into every
    command test and cause them to hit the Kafka branch instead of the sync
    branch.

    Kafka-mode tests are unaffected: they patch the module-level *reference*
    (e.g. ``src.commands.post.settings``) with a fresh MagicMock that has
    ``KAFKA_WRITE_MODE = True``, which shadows this fixture's change.
    """
    from src.config import settings  # noqa: PLC0415

    monkeypatch.setattr(settings, "KAFKA_WRITE_MODE", False)


@pytest.fixture
def sell_listing() -> Listing:
    """A minimal valid SELL listing."""
    return Listing(
        type=ListingType.SELL,
        title="iPhone 14 Pro 256GB",
        category=Category.DIEN_TU,
        price=25_000_000,
        city="Hanoi",
        contact=Contact(phone="0901234567"),
        seller_info=SellerInfo(
            brand="Apple",
            model="iPhone 14 Pro",
            condition=Condition.LIKE_NEW,
        ),
    )


@pytest.fixture
def buy_listing() -> Listing:
    """A minimal valid BUY listing."""
    return Listing(
        type=ListingType.BUY,
        title="Looking for iPhone 14 Pro",
        category=Category.DIEN_TU,
        budget_max=27_000_000,
        city="Hanoi",
        contact=Contact(phone="0912345678"),
        buyer_info=BuyerInfo(
            desired_brand="Apple",
            desired_model="iPhone 14 Pro",
            urgency=Urgency.ASAP,
        ),
    )


@pytest.fixture
def sell_listing_with_geo() -> Listing:
    """A SELL listing with geo-location."""
    return Listing(
        type=ListingType.SELL,
        title="Honda SH 150 2022",
        category=Category.XE_MAY,
        price=65_000_000,
        city="Hanoi",
        geo_location=GeoLocation(lat=21.0285, lon=105.8542),
        seller_info=SellerInfo(brand="Honda", model="SH 150", condition=Condition.USED),
    )


@pytest.fixture
def fake_vector() -> list[float]:
    """A fixed 768-dim fake embedding vector for tests."""
    return [0.1] * 768


@pytest.fixture
def fake_sell_hit() -> dict:
    """A fake ES hit dict representing a SELL listing (includes _score)."""
    return {
        "id": "sell-abc-123",
        "type": "sell",
        "title": "iPhone 14 Pro",
        "category": "dien-tu",
        "price": 25_000_000,
        "price_currency": "VND",
        "city": "Hanoi",
        "status": "active",
        "contact": {"name": "An", "phone": "0901234567", "preferred_chan": "call"},
        "_score": 0.85,
    }


# ---------------------------------------------------------------------------
# Shared DI Fakes — use these fixtures instead of redefining in each test file
# ---------------------------------------------------------------------------


class FakeStore:
    """In-memory store satisfying ListingStorePort + SearchStorePort."""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}

    def ensure_index(self) -> None:
        pass

    def index_doc(self, doc: dict) -> str:
        self.docs[doc["id"]] = doc
        return doc["id"]

    def bulk_index(self, docs: list[dict]) -> tuple[int, int]:
        for d in docs:
            self.docs[d["id"]] = d
        return len(docs), 0

    def get_doc(self, id: str) -> dict | None:
        return self.docs.get(id)

    def delete_doc(self, id: str) -> bool:
        return self.docs.pop(id, None) is not None

    def hybrid_search(self, *args: object, **kwargs: object) -> list[dict]:
        return list(self.docs.values())

    def knn_match(self, *args: object, **kwargs: object) -> list[dict]:
        return list(self.docs.values())

    def ping(self) -> bool:
        return True


class FakeEmbedder:
    """Fixed 768-dim embedder satisfying EmbedderPort."""

    def embed(self, text: str) -> list[float]:
        return [0.1] * 768

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        return [[0.1] * 768 for _ in texts]


class FakeEventBus:
    """Captures emitted events satisfying EventBusPort."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def emit(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))


@pytest.fixture
def fake_store() -> FakeStore:
    """Fresh in-memory store for each test."""
    return FakeStore()


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    """Fixed-vector embedder for each test."""
    return FakeEmbedder()


@pytest.fixture
def fake_event_bus() -> FakeEventBus:
    """Capturing event bus for each test."""
    return FakeEventBus()
