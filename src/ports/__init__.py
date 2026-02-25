"""
Ports — abstract interfaces (Protocols) for the Agora infrastructure layer.

Each port defines *what* the infrastructure must do, not *how* it does it.
Concrete adapters in ``src/infrastructure/`` implement these protocols via
structural subtyping (no explicit ``class Foo(SomePort)`` inheritance needed).

Usage in services::

    from src.ports import EmbedderPort, ListingStorePort
"""

from __future__ import annotations

from src.ports.command_bus import CommandBusPort
from src.ports.embedder_port import EmbedderPort
from src.ports.event_bus import EventBusPort
from src.ports.listing_store import ListingStorePort
from src.ports.search_store import SearchStorePort

__all__ = [
    "CommandBusPort",
    "EmbedderPort",
    "EventBusPort",
    "ListingStorePort",
    "SearchStorePort",
]
