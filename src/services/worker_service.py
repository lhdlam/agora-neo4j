"""
WorkerService — dispatches Kafka CommandMessage to the appropriate service operation.

This service runs inside the agora-worker container. It receives a
``CommandMessage`` from ``KafkaCommandConsumer`` and delegates to
``ListingService`` based on the action field.
"""

from __future__ import annotations

import logging

from src.domain.models import CommandAction, CommandMessage, Listing
from src.services.listing_service import ListingService

logger = logging.getLogger(__name__)


class WorkerService:
    """
    Dispatcher: translates a ``CommandMessage`` into a ``ListingService`` call.

    Injected with a fully-wired ``ListingService`` — tests pass a fake.
    """

    def __init__(self, listing_service: ListingService) -> None:
        self._svc = listing_service

    def handle(self, msg: CommandMessage) -> None:
        """
        Process one command message.

        Args:
            msg: The command to process.

        Raises:
            ValueError:   If the action is unknown or the payload is invalid.
            RuntimeError: If the underlying service operation fails.
        """
        logger.info("WorkerService handling action=%s request_id=%s", msg.action, msg.request_id)

        if msg.action == CommandAction.CREATE:
            self._handle_create(msg)
        elif msg.action == CommandAction.DELETE:
            self._handle_delete(msg)
        else:
            raise ValueError(f"Unknown CommandAction: {msg.action!r}")

    # ── Action handlers ───────────────────────────────────────────────────────

    def _handle_create(self, msg: CommandMessage) -> None:
        """Validate payload as a Listing and index it."""
        listing = Listing.model_validate(msg.payload)
        doc_id = self._svc.post(listing)
        logger.info("Worker created listing id=%s title=%r", doc_id, listing.title)

    def _handle_delete(self, msg: CommandMessage) -> None:
        """Delete a listing by ID."""
        listing_id: str = msg.payload.get("id", "")
        if not listing_id:
            raise ValueError("delete command payload must contain 'id'")
        deleted = self._svc.delete(listing_id)
        if deleted:
            logger.info("Worker deleted listing id=%s", listing_id)
        else:
            logger.warning("Worker: listing id=%s not found (already deleted?)", listing_id)
