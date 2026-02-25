"""
Indexer — thin compatibility shims (deprecated, kept for backward compatibility).

.. deprecated::
    The orchestration logic that used to live here has been moved into
    :class:`src.services.listing_service.ListingService`.

    These module-level functions are kept temporarily so that any external
    scripts that call them directly continue to work.  They will be removed
    in a future cleanup once all callers have been migrated to the service layer.

    **Do not add new logic here.**  Implement new behaviour in
    :class:`~src.services.listing_service.ListingService` and inject the
    required ports from :func:`~src.services.factories.make_listing_service`.
"""

from __future__ import annotations

from collections.abc import Callable
import logging

from src.domain.models import Listing
from src.services.factories import make_listing_service

logger = logging.getLogger(__name__)


def index_single(listing: Listing) -> str:  # pragma: no cover
    """
    Embed + index a single listing via the ListingService.

    .. deprecated::
        Call :meth:`~src.services.listing_service.ListingService.post` directly.
    """
    logger.debug("index_single() is deprecated — use ListingService.post() instead.")
    return make_listing_service().post(listing)


def bulk_index(  # pragma: no cover
    listings: list[Listing],
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[int, int]:
    """
    Batch-embed and bulk-index listings via the ListingService.

    .. deprecated::
        Call :meth:`~src.services.listing_service.ListingService.bulk_import` directly.
    """
    logger.debug("bulk_index() is deprecated — use ListingService.bulk_import() instead.")
    return make_listing_service().bulk_import(listings, on_progress=on_progress)
