"""
`agora post sell` and `agora post buy` commands.

Both commands share a set of common options (title, location, contact, …)
via the ``_common_options`` decorator applied before type-specific options.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel

from src.config import settings
from src.domain.models import (
    BuyerInfo,
    Category,
    Condition,
    Contact,
    ContactMethod,
    GeoLocation,
    Listing,
    ListingType,
    SellerInfo,
    Urgency,
)
from src.infrastructure.es_client import get_es_client
from src.infrastructure.kafka_producer import send_command
from src.services.factories import make_listing_service

_console = Console()

# The "post" group must be module-level so the @post.command(…) decorator works.
post = click.Group("post", help="Post a classified listing (sell or buy).")


def _check_es() -> None:
    """Exit with code 3 if Elasticsearch is not reachable."""
    if not get_es_client().ping():
        _console.print("[bold red]Cannot connect to Elasticsearch.[/]")
        raise SystemExit(3)


def _common_options(f: Callable[..., Any]) -> Callable[..., Any]:
    """Attach CLI options shared by both `post sell` and `post buy`."""
    options = [
        click.option("--title", required=True, help="Listing title"),
        click.option("--description", default=None, help="Detailed description"),
        click.option(
            "--category",
            required=True,
            type=click.Choice([c.value for c in Category]),
            help="Product category",
        ),
        click.option("--location", default=None, help="Location name (e.g. Hanoi)"),
        click.option("--district", default=None, help="District / borough"),
        click.option("--city", default=None, help="City"),
        click.option("--country", default="VN", help="ISO-3166 country code"),
        click.option("--lat", default=None, type=float, help="Latitude"),
        click.option("--lon", default=None, type=float, help="Longitude"),
        click.option("--tags", default="", help="Comma-separated tags"),
        click.option("--contact-name", default=None, help="Contact person name"),
        click.option("--contact-phone", default=None, help="Contact phone number"),
        click.option("--contact-email", default=None, help="Contact email"),
        click.option(
            "--contact-method",
            default="call",
            type=click.Choice([m.value for m in ContactMethod]),
            help="Preferred contact channel",
        ),
    ]
    for option in reversed(options):
        f = option(f)
    return f


@post.command("sell")
@_common_options
@click.option("--price", required=True, type=int, help="Asking price (integer)")
@click.option("--currency", default="VND", help="ISO-4217 currency code")
@click.option("--brand", default=None, help="Brand name")
@click.option("--model", default=None, help="Product model")
@click.option("--storage", default=None, help="Storage / capacity")
@click.option("--color", default=None, help="Color")
@click.option(
    "--condition",
    default=None,
    type=click.Choice([c.value for c in Condition]),
    help="Item condition",
)
@click.option("--warranty", default=None, type=int, help="Remaining warranty (months)")
@click.option("--negotiable", is_flag=True, default=False, help="Price is negotiable")
def post_sell(
    title: str,
    description: str | None,
    category: str,
    location: str | None,
    district: str | None,
    city: str | None,
    country: str,
    lat: float | None,
    lon: float | None,
    tags: str,
    contact_name: str | None,
    contact_phone: str | None,
    contact_email: str | None,
    contact_method: str,
    price: int,
    currency: str,
    brand: str | None,
    model: str | None,
    storage: str | None,
    color: str | None,
    condition: str | None,
    warranty: int | None,
    negotiable: bool,
) -> None:
    """Post a SELL listing."""
    listing = Listing(
        type=ListingType.SELL,
        title=title,
        description=description,
        category=Category(category),
        location=location,
        district=district,
        city=city,
        country=country,
        geo_location=GeoLocation(lat=lat, lon=lon) if lat and lon else None,
        tags=[t.strip() for t in tags.split(",") if t.strip()],
        price=price,
        price_currency=currency,
        contact=Contact(
            name=contact_name,
            phone=contact_phone,
            email=contact_email,
            preferred_chan=ContactMethod(contact_method),
        ),
        seller_info=SellerInfo(
            brand=brand,
            model=model,
            storage=storage,
            color=color,
            condition=Condition(condition) if condition else None,
            warranty_months=warranty,
            negotiable=negotiable,
        ),
    )
    if settings.KAFKA_WRITE_MODE:
        offset = send_command("create", listing.model_dump(mode="json"))
        _console.print(
            Panel(
                f"[bold green]Sell listing queued ✔[/]\n"
                f"[dim]Kafka offset:[/] [yellow]{offset}[/]\n"
                f"[dim]Title:[/] {title}\n"
                f"[dim]Price:[/] {price:,} {currency}\n"
                f"[dim]Worker will embed and index shortly.[/]",
                title="POST SELL → QUEUED",
                border_style="yellow",
            )
        )
        return
    _check_es()
    with _console.status("[bold cyan]Embedding and indexing…"):
        doc_id = make_listing_service().post(listing)
    _console.print(
        Panel(
            f"[bold green]Sell listing posted successfully.[/]\n"
            f"[dim]ID:[/] [yellow]{doc_id}[/]\n"
            f"[dim]Title:[/] {title}\n"
            f"[dim]Price:[/] {price:,} {currency}",
            title="POST SELL",
            border_style="green",
        )
    )


@post.command("buy")
@_common_options
@click.option("--budget-min", default=None, type=int, help="Minimum budget")
@click.option("--budget-max", default=None, type=int, help="Maximum budget")
@click.option("--currency", default="VND", help="ISO-4217 currency code")
@click.option("--desired-brand", default=None, help="Desired brand")
@click.option("--desired-model", default=None, help="Desired model")
@click.option("--desired-storage", default=None, help="Desired storage / capacity")
@click.option("--desired-color", default=None, help="Desired color")
@click.option(
    "--desired-condition",
    default=None,
    type=click.Choice([c.value for c in Condition]),
    help="Desired condition",
)
@click.option(
    "--urgency",
    default="normal",
    type=click.Choice([u.value for u in Urgency]),
    help="Urgency level",
)
def post_buy(
    title: str,
    description: str | None,
    category: str,
    location: str | None,
    district: str | None,
    city: str | None,
    country: str,
    lat: float | None,
    lon: float | None,
    tags: str,
    contact_name: str | None,
    contact_phone: str | None,
    contact_email: str | None,
    contact_method: str,
    budget_min: int | None,
    budget_max: int | None,
    currency: str,
    desired_brand: str | None,
    desired_model: str | None,
    desired_storage: str | None,
    desired_color: str | None,
    desired_condition: str | None,
    urgency: str,
) -> None:
    """Post a BUY listing (wanted / looking to buy)."""
    listing = Listing(
        type=ListingType.BUY,
        title=title,
        description=description,
        category=Category(category),
        location=location,
        district=district,
        city=city,
        country=country,
        geo_location=GeoLocation(lat=lat, lon=lon) if lat and lon else None,
        tags=[t.strip() for t in tags.split(",") if t.strip()],
        budget_min=budget_min,
        budget_max=budget_max,
        price_currency=currency,
        contact=Contact(
            name=contact_name,
            phone=contact_phone,
            email=contact_email,
            preferred_chan=ContactMethod(contact_method),
        ),
        buyer_info=BuyerInfo(
            desired_brand=desired_brand,
            desired_model=desired_model,
            desired_storage=desired_storage,
            desired_color=desired_color,
            desired_condition=Condition(desired_condition) if desired_condition else None,
            urgency=Urgency(urgency),
        ),
    )
    if settings.KAFKA_WRITE_MODE:
        offset = send_command("create", listing.model_dump(mode="json"))
        _console.print(
            Panel(
                f"[bold green]Buy listing queued ✔[/]\n"
                f"[dim]Kafka offset:[/] [yellow]{offset}[/]\n"
                f"[dim]Title:[/] {title}\n"
                f"[dim]Budget:[/] {(budget_max or 0):,} {currency}\n"
                f"[dim]Worker will embed and index shortly.[/]",
                title="POST BUY → QUEUED",
                border_style="yellow",
            )
        )
        return
    _check_es()
    with _console.status("[bold cyan]Embedding and indexing…"):
        doc_id = make_listing_service().post(listing)
    _console.print(
        Panel(
            f"[bold green]Buy listing posted successfully.[/]\n"
            f"[dim]ID:[/] [yellow]{doc_id}[/]\n"
            f"[dim]Title:[/] {title}\n"
            f"[dim]Budget:[/] {(budget_max or 0):,} {currency}",
            title="POST BUY",
            border_style="blue",
        )
    )
