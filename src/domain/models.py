"""Pydantic v2 data models for the Agora Service."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import re
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, EmailStr, Field, field_validator

# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class ListingType(StrEnum):
    SELL = "sell"
    BUY = "buy"


class ListingStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"
    EXPIRED = "expired"


class Category(StrEnum):
    DIEN_TU = "dien-tu"
    XE_MAY = "xe-may"
    OTO = "oto"
    NHA_DAT = "nha-dat"
    NOI_THAT = "do-go-noi-that"
    THOI_TRANG = "thoi-trang"
    THE_THAO = "the-thao"
    SACH = "sach"
    THUC_PHAM = "thuc-pham"
    KHAC = "khac"


class ContactMethod(StrEnum):
    CALL = "call"
    EMAIL = "email"
    ZALO = "zalo"
    BOTH = "both"


class Condition(StrEnum):
    NEW = "new"
    LIKE_NEW = "like-new"
    USED = "used"
    HEAVILY_USED = "heavily-used"


class Urgency(StrEnum):
    ASAP = "asap"
    NORMAL = "normal"
    LOW = "low"


class CommandAction(StrEnum):
    """Actions that can be dispatched to the listing.commands Kafka topic."""

    CREATE = "create"
    DELETE = "delete"


# ─────────────────────────────────────────────────────────────────────────────
# Sub-models
# ─────────────────────────────────────────────────────────────────────────────


class GeoLocation(BaseModel):
    lat: float
    lon: float


class Contact(BaseModel):
    name: str | None = Field(None, max_length=100)
    phone: str | None = None
    email: EmailStr | None = None
    preferred_chan: ContactMethod = ContactMethod.CALL

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        if v is not None and not re.match(r"^\+?[\d\s\-\.]{7,20}$", v):
            raise ValueError(f"Invalid phone number format: '{v}'")
        return v


class SellerInfo(BaseModel):
    """Attributes specific to SELL listings."""

    condition: Condition | None = None
    warranty_months: int | None = None
    brand: str | None = Field(None, max_length=100)
    model: str | None = Field(None, max_length=100)
    storage: str | None = Field(None, max_length=50)
    color: str | None = Field(None, max_length=50)
    negotiable: bool = False


class BuyerInfo(BaseModel):
    """Attributes specific to BUY listings (desired product traits)."""

    desired_condition: Condition | None = None
    desired_brand: str | None = Field(None, max_length=100)
    desired_model: str | None = Field(None, max_length=100)
    desired_storage: str | None = Field(None, max_length=50)
    desired_color: str | None = Field(None, max_length=50)
    urgency: Urgency = Urgency.NORMAL


# ─────────────────────────────────────────────────────────────────────────────
# Main Listing model
# ─────────────────────────────────────────────────────────────────────────────


class Listing(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: ListingType

    # ── Text fields (used for BM25 + embedding) ───────────────
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    category: Category
    tags: list[str] = Field(default_factory=list)

    # ── Pricing ───────────────────────────────────────────────
    price: int | None = None  # seller asking price
    price_currency: str = "VND"
    budget_min: int | None = None  # buyer range
    budget_max: int | None = None

    # ── Location ──────────────────────────────────────────────
    location: str | None = Field(None, max_length=200)
    district: str | None = Field(None, max_length=100)
    city: str | None = Field(None, max_length=100)
    country: str = "VN"
    geo_location: GeoLocation | None = None

    # ── Contact ───────────────────────────────────────────────
    contact: Contact | None = None

    # ── Type-specific attributes ──────────────────────────────
    seller_info: SellerInfo | None = None
    buyer_info: BuyerInfo | None = None

    # ── Lifecycle ─────────────────────────────────────────────
    status: ListingStatus = ListingStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # ── AI vector (populated by embedder before indexing) ─────
    embedding: list[float] | None = None

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        if len(v) > 30:
            raise ValueError("A listing may not have more than 30 tags.")
        return [tag[:50] for tag in v]  # silently truncate individual tags


# ─────────────────────────────────────────────────────────────────────────────
# Command message (Kafka command bus envelope)
# ─────────────────────────────────────────────────────────────────────────────


class CommandMessage(BaseModel):
    """
    Envelope sent to the ``listing.commands`` Kafka topic.

    The ``payload`` is always a JSON-serialisable dict whose shape depends on
    the ``action``:

    * ``create``: a ``Listing`` dict (as produced by ``listing.model_dump()``).
    * ``delete``: ``{"id": "<listing-id>"}``.

    ``request_id`` can be used for end-to-end tracing across producer / worker.
    """

    action: CommandAction
    payload: dict[str, Any]
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
