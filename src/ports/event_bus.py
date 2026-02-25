"""
EventBusPort — abstract interface for domain event emission.

Kafka, RabbitMQ, an in-memory list, or a no-op stub — any backend that
can call ``emit(event_type, payload)`` satisfies this protocol.

Domain rules:
  - ``emit`` must **never** raise.  Infrastructure failures must be caught
    internally and logged; they must not propagate to the caller.
  - The payload dict contains only JSON-serializable primitive types.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EventBusPort(Protocol):
    """Publish domain events to an external event stream."""

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        """
        Publish a domain event.

        Args:
            event_type: A dot-separated string identifier, e.g. ``"listing.created"``.
            payload:    JSON-serializable dict with event data.

        Note:
            Implementations must swallow all exceptions and log them instead of
            propagating — event failures must never block the happy path.
        """
        ...  # pragma: no cover
