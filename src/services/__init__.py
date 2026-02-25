"""Services layer — business logic, reusable by CLI, web API, or background workers."""

from src.services.factories import make_listing_service, make_match_service, make_search_service
from src.services.listing_service import ListingService
from src.services.match_service import MatchResult, MatchService
from src.services.search_service import SearchService

__all__ = [
    "ListingService",
    "SearchService",
    "MatchService",
    "MatchResult",
    "make_listing_service",
    "make_search_service",
    "make_match_service",
]
