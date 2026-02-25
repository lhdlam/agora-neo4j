"""
ListingStorePort — abstract interface for listing CRUD + index lifecycle.

Any concrete adapter (Elasticsearch, in-memory fake, DynamoDB, …) must
satisfy this structural protocol.  No explicit inheritance required.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ListingStorePort(Protocol):
    """Write + read operations on the listings index."""

    # ── Index lifecycle ───────────────────────────────────────────────────────

    def ensure_index(self) -> None:
        """Create the backing index / table if it does not already exist."""
        ...  # pragma: no cover

    # ── Write ─────────────────────────────────────────────────────────────────

    def index_doc(self, doc: dict[str, Any]) -> str:
        """
        Persist a single document.

        Returns:
            The document's ID as stored in the backend.
        """
        ...  # pragma: no cover

    def bulk_index(self, docs: list[dict[str, Any]]) -> tuple[int, int]:
        """
        Persist multiple documents in one batch.

        Returns:
            ``(success_count, error_count)``
        """
        ...  # pragma: no cover

    def delete_doc(self, listing_id: str) -> bool:
        """
        Hard-delete a document.

        Returns:
            ``True`` if the document existed and was deleted, ``False`` if not found.
        """
        ...  # pragma: no cover

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_doc(self, listing_id: str) -> dict[str, Any] | None:
        """
        Fetch a document by its ID.

        Returns:
            The document dict, or ``None`` if not found.
        """
        ...  # pragma: no cover
