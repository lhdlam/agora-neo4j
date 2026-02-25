"""Tests for domain.embed_text — pure unit tests, no I/O."""

from __future__ import annotations

from src.domain.embed_text import build_embed_text
from src.domain.models import (
    BuyerInfo,
    Category,
    Condition,
    Listing,
    ListingType,
    SellerInfo,
)


def _make_sell_listing(**kwargs: object) -> Listing:
    defaults: dict[str, object] = {
        "type": ListingType.SELL,
        "title": "iPhone 14 Pro 256GB",
        "category": Category.DIEN_TU,
        "seller_info": SellerInfo(
            brand="Apple", model="iPhone 14 Pro", condition=Condition.LIKE_NEW
        ),
    }
    return Listing(**(defaults | kwargs))


def _make_buy_listing(**kwargs: object) -> Listing:
    defaults: dict[str, object] = {
        "type": ListingType.BUY,
        "title": "Looking for iPhone 14 Pro",
        "category": Category.DIEN_TU,
        "buyer_info": BuyerInfo(desired_brand="Apple", desired_condition=Condition.LIKE_NEW),
    }
    return Listing(**(defaults | kwargs))


class TestBuildEmbedText:
    def test_title_always_present(self) -> None:
        listing = _make_sell_listing()
        text = build_embed_text(listing)
        assert "iPhone 14 Pro 256GB" in text

    def test_description_included_when_present(self) -> None:
        listing = _make_sell_listing(description="Like new, boxed")
        text = build_embed_text(listing)
        assert "Like new, boxed" in text

    def test_description_absent_when_none(self) -> None:
        listing = _make_sell_listing(description=None)
        text = build_embed_text(listing)
        # No stray "None" string
        assert "None" not in text

    def test_category_value_included(self) -> None:
        listing = _make_sell_listing()
        text = build_embed_text(listing)
        assert "dien-tu" in text

    def test_tags_joined_with_space(self) -> None:
        listing = _make_sell_listing(tags=["apple", "smartphone"])
        text = build_embed_text(listing)
        assert "apple smartphone" in text

    def test_seller_info_fields_included(self) -> None:
        listing = _make_sell_listing()
        text = build_embed_text(listing)
        assert "Apple" in text
        assert "iPhone 14 Pro" in text
        assert "like-new" in text

    def test_buyer_info_fields_included(self) -> None:
        listing = _make_buy_listing()
        text = build_embed_text(listing)
        assert "Apple" in text
        assert "like-new" in text

    def test_no_seller_info_no_crash(self) -> None:
        listing = _make_sell_listing(seller_info=None)
        text = build_embed_text(listing)
        assert isinstance(text, str)

    def test_returns_single_string(self) -> None:
        listing = _make_sell_listing(tags=["a", "b"], description="desc")
        text = build_embed_text(listing)
        assert isinstance(text, str)
        assert "\n" not in text
