"""
Serializers — convert between domain models and storage representations.

Separating serialization from the domain model keeps ``Listing`` a pure data
container with zero knowledge of Elasticsearch's wire format.

Public API
----------
listing_to_es_doc(listing)  →  dict ready to index in ES
es_doc_to_listing(doc)      →  Listing domain object (for read-back / tests)
"""

from __future__ import annotations

from typing import Any

from src.domain.models import Listing


def listing_to_es_doc(listing: Listing) -> dict[str, Any]:
    """
    Serialize a ``Listing`` to a dict suitable for Elasticsearch indexing.

    The ``embedding`` field is included only when present on the listing
    (i.e. after the infrastructure layer has attached a vector).

    ``geo_location`` is serialized as ``{"lat": float, "lon": float}`` which
    is the ES ``geo_point`` format.
    """
    doc = listing.model_dump(mode="json", exclude={"embedding"})

    # Ensure geo_location is in the correct ES geo_point format.
    if listing.geo_location:
        doc["geo_location"] = {
            "lat": listing.geo_location.lat,
            "lon": listing.geo_location.lon,
        }

    if listing.embedding is not None:
        doc["embedding"] = listing.embedding

    return doc


def es_doc_to_listing(doc: dict[str, Any]) -> Listing:
    """
    Deserialize an Elasticsearch source document back into a ``Listing``.

    Useful for tests and future read-model use-cases where you need a fully
    typed domain object rather than a raw dict.
    """
    return Listing.model_validate(doc)
