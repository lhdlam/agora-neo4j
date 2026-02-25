"""Tests for src/domain/models.py — validators, serialization, invariants."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from src.domain.models import (
    Category,
    Contact,
    GeoLocation,
    Listing,
    ListingStatus,
    ListingType,
    SellerInfo,
)
from src.infrastructure.serializers import listing_to_es_doc


class TestContactValidator:
    def test_valid_phone_accepted(self):
        c = Contact(phone="0901234567")
        assert c.phone == "0901234567"

    def test_phone_with_plus_prefix(self):
        c = Contact(phone="+84901234567")
        assert c.phone == "+84901234567"

    def test_invalid_phone_raises(self):
        with pytest.raises(ValidationError, match="Invalid phone number format"):
            Contact(phone="not-a-phone!!!")

    def test_none_phone_accepted(self):
        c = Contact(phone=None)
        assert c.phone is None

    def test_short_phone_rejected(self):
        with pytest.raises(ValidationError):
            Contact(phone="123")


class TestListingDefaults:
    def test_status_defaults_to_active(self):
        listing = Listing(type=ListingType.SELL, title="Test", category=Category.KHAC)
        assert listing.status == ListingStatus.ACTIVE

    def test_country_defaults_to_vn(self):
        listing = Listing(type=ListingType.SELL, title="Test", category=Category.KHAC)
        assert listing.country == "VN"

    def test_tags_default_is_empty_list(self):
        listing = Listing(type=ListingType.SELL, title="Test", category=Category.KHAC)
        assert listing.tags == []
        # Ensure it's not shared between instances (mutable default check)
        listing2 = Listing(type=ListingType.SELL, title="Test2", category=Category.KHAC)
        listing.tags.append("x")
        assert listing2.tags == []

    def test_embedding_defaults_to_none(self):
        listing = Listing(type=ListingType.SELL, title="Test", category=Category.KHAC)
        assert listing.embedding is None

    def test_id_is_auto_generated_unique(self):
        a = Listing(type=ListingType.SELL, title="A", category=Category.KHAC)
        b = Listing(type=ListingType.SELL, title="B", category=Category.KHAC)
        assert a.id != b.id


class TestListingFieldValidation:
    def test_title_cannot_be_empty(self):
        with pytest.raises(ValidationError):
            Listing(type=ListingType.SELL, title="", category=Category.KHAC)

    def test_title_max_length_enforced(self):
        with pytest.raises(ValidationError):
            Listing(type=ListingType.SELL, title="x" * 201, category=Category.KHAC)

    def test_description_max_length_enforced(self):
        with pytest.raises(ValidationError):
            Listing(
                type=ListingType.SELL,
                title="Test",
                category=Category.KHAC,
                description="x" * 5001,
            )

    def test_tags_max_count_enforced(self):
        with pytest.raises(ValidationError, match="30 tags"):
            Listing(
                type=ListingType.SELL,
                title="Test",
                category=Category.KHAC,
                tags=[f"tag{i}" for i in range(31)],
            )

    def test_tags_within_limit_accepted(self):
        listing = Listing(
            type=ListingType.SELL,
            title="Test",
            category=Category.KHAC,
            tags=[f"tag{i}" for i in range(30)],
        )
        assert len(listing.tags) == 30


class TestListingToEsDoc:
    """Tests for listing_to_es_doc() serializer — moved from domain into infrastructure."""

    def test_excludes_embedding_when_none(self):
        listing = Listing(type=ListingType.SELL, title="Test", category=Category.KHAC)
        doc = listing_to_es_doc(listing)
        assert "embedding" not in doc

    def test_includes_embedding_when_set(self):
        listing = Listing(
            type=ListingType.SELL,
            title="Test",
            category=Category.KHAC,
            embedding=[0.1] * 768,
        )
        doc = listing_to_es_doc(listing)
        assert "embedding" in doc
        assert len(doc["embedding"]) == 768

    def test_geo_location_serialized_as_dict(self):
        listing = Listing(
            type=ListingType.SELL,
            title="Test",
            category=Category.KHAC,
            geo_location=GeoLocation(lat=21.0285, lon=105.8542),
        )
        doc = listing_to_es_doc(listing)
        assert doc["geo_location"] == {"lat": 21.0285, "lon": 105.8542}

    def test_seller_info_present_in_doc(self):
        listing = Listing(
            type=ListingType.SELL,
            title="Test",
            category=Category.DIEN_TU,
            seller_info=SellerInfo(brand="Apple"),
        )
        doc = listing_to_es_doc(listing)
        assert doc["seller_info"]["brand"] == "Apple"

    def test_type_serialized_as_string(self):
        listing = Listing(type=ListingType.BUY, title="Test", category=Category.KHAC)
        doc = listing_to_es_doc(listing)
        assert doc["type"] == "buy"

    def test_id_is_present_in_doc(self):
        listing = Listing(type=ListingType.SELL, title="Test", category=Category.KHAC)
        doc = listing_to_es_doc(listing)
        assert "id" in doc
        assert doc["id"] == listing.id


class TestEsDocToListing:
    """Tests for es_doc_to_listing() — covers serializers.py line 52."""

    def test_round_trip_sell_listing(self):
        """listing → es_doc → listing should preserve key fields."""
        from src.infrastructure.serializers import es_doc_to_listing

        original = Listing(
            type=ListingType.SELL,
            title="Round-trip Test",
            category=Category.DIEN_TU,
            price=10_000_000,
        )
        doc = listing_to_es_doc(original)
        restored = es_doc_to_listing(doc)
        assert restored.id == original.id
        assert restored.title == original.title
        assert restored.type == ListingType.SELL
        assert restored.price == original.price

    def test_round_trip_buy_listing(self):
        from src.infrastructure.serializers import es_doc_to_listing

        original = Listing(type=ListingType.BUY, title="I want a phone", category=Category.DIEN_TU)
        doc = listing_to_es_doc(original)
        restored = es_doc_to_listing(doc)
        assert restored.type == ListingType.BUY
