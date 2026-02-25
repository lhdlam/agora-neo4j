"""Domain layer — pure Python, no I/O, no framework dependency."""

from src.domain.embed_text import build_embed_text
from src.domain.models import (
    BuyerInfo,
    Category,
    Condition,
    Contact,
    ContactMethod,
    GeoLocation,
    Listing,
    ListingStatus,
    ListingType,
    SellerInfo,
    Urgency,
)

__all__ = [
    "Listing",
    "ListingType",
    "ListingStatus",
    "Category",
    "ContactMethod",
    "Condition",
    "Urgency",
    "GeoLocation",
    "Contact",
    "SellerInfo",
    "BuyerInfo",
    "build_embed_text",
]
