"""
Build rich text representations of Listing objects for embedding generation.

Keeping this separate from the model itself ensures the domain model stays
a plain data container, and the text-transform logic is independently testable.
"""

from __future__ import annotations

from src.domain.models import Listing


def build_embed_text(listing: Listing) -> str:
    """
    Concatenate the most semantically meaningful fields into a single string
    suitable for passing to the embedding model.
    """
    parts: list[str] = [listing.title]

    if listing.description:
        parts.append(listing.description)

    if listing.category:
        parts.append(listing.category.value)

    if listing.tags:
        parts.append(" ".join(listing.tags))

    if listing.seller_info:
        si = listing.seller_info
        for val in [
            si.brand,
            si.model,
            si.storage,
            si.color,
            si.condition.value if si.condition else None,
        ]:
            if val:
                parts.append(val)

    if listing.buyer_info:
        bi = listing.buyer_info
        for val in [
            bi.desired_brand,
            bi.desired_model,
            bi.desired_storage,
            bi.desired_color,
            bi.desired_condition.value if bi.desired_condition else None,
        ]:
            if val:
                parts.append(val)

    return " ".join(parts)
