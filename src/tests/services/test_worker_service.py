"""Tests for WorkerService — dispatch logic with injected fakes."""

from unittest.mock import MagicMock

from pydantic import ValidationError
import pytest

from src.domain.models import (
    Category,
    CommandAction,
    CommandMessage,
    Condition,
    Listing,
    ListingType,
    SellerInfo,
)
from src.services.worker_service import WorkerService

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_listing(**kwargs):
    defaults = {
        "type": ListingType.SELL,
        "title": "Test iPhone",
        "category": Category.DIEN_TU,
        "seller_info": SellerInfo(condition=Condition.LIKE_NEW),
    }
    return Listing(**(defaults | kwargs))


def _make_worker():
    """Return a WorkerService with a mock ListingService."""
    mock_svc = MagicMock()
    mock_svc.post.return_value = "doc-id-123"
    mock_svc.delete.return_value = True
    return WorkerService(listing_service=mock_svc), mock_svc


# ─────────────────────────────────────────────────────────────────────────────
# handle — CREATE
# ─────────────────────────────────────────────────────────────────────────────


class TestHandleCreate:
    def test_calls_listing_service_post(self):
        worker, mock_svc = _make_worker()
        listing = _make_listing()
        msg = CommandMessage(
            action=CommandAction.CREATE,
            payload=listing.model_dump(mode="json"),
        )
        worker.handle(msg)
        mock_svc.post.assert_called_once()

    def test_passes_validated_listing_to_post(self):
        worker, mock_svc = _make_worker()
        listing = _make_listing(title="Laptop Dell XPS")
        msg = CommandMessage(
            action=CommandAction.CREATE,
            payload=listing.model_dump(mode="json"),
        )
        worker.handle(msg)
        posted_listing: Listing = mock_svc.post.call_args.args[0]
        assert posted_listing.title == "Laptop Dell XPS"
        assert posted_listing.type == ListingType.SELL

    def test_raises_on_invalid_payload(self):
        worker, _ = _make_worker()
        msg = CommandMessage(
            action=CommandAction.CREATE,
            payload={"invalid": "data"},  # missing required fields
        )
        with pytest.raises(ValidationError):
            worker.handle(msg)

    def test_does_not_call_delete_on_create(self):
        worker, mock_svc = _make_worker()
        listing = _make_listing()
        msg = CommandMessage(
            action=CommandAction.CREATE,
            payload=listing.model_dump(mode="json"),
        )
        worker.handle(msg)
        mock_svc.delete.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# handle — DELETE
# ─────────────────────────────────────────────────────────────────────────────


class TestHandleDelete:
    def test_calls_listing_service_delete(self):
        worker, mock_svc = _make_worker()
        msg = CommandMessage(
            action=CommandAction.DELETE,
            payload={"id": "abc-123"},
        )
        worker.handle(msg)
        mock_svc.delete.assert_called_once_with("abc-123")

    def test_raises_when_id_missing(self):
        worker, _ = _make_worker()
        msg = CommandMessage(
            action=CommandAction.DELETE,
            payload={},  # no 'id' key
        )
        with pytest.raises(ValueError, match="id"):
            worker.handle(msg)

    def test_does_not_raise_when_not_found(self):
        worker, mock_svc = _make_worker()
        mock_svc.delete.return_value = False  # already deleted
        msg = CommandMessage(
            action=CommandAction.DELETE,
            payload={"id": "missing-id"},
        )
        # Should NOT raise — just logs a warning
        worker.handle(msg)
        mock_svc.delete.assert_called_once()

    def test_does_not_call_post_on_delete(self):
        worker, mock_svc = _make_worker()
        msg = CommandMessage(
            action=CommandAction.DELETE,
            payload={"id": "abc-123"},
        )
        worker.handle(msg)
        mock_svc.post.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# handle — unknown action
# ─────────────────────────────────────────────────────────────────────────────


class TestHandleUnknown:
    def test_raises_value_error_on_unknown_action(self):
        worker, _ = _make_worker()
        # Bypass enum validation by patching action directly
        msg = CommandMessage(action=CommandAction.CREATE, payload={})
        msg.__dict__["action"] = "unknown_action"
        with pytest.raises(ValueError):
            worker.handle(msg)
