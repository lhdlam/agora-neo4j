"""``agora search`` command — hybrid BM25 + kNN semantic search."""

from __future__ import annotations

import click
from rich.console import Console

from src.domain.models import Category
from src.infrastructure.es_client import get_es_client
from src.services.factories import make_search_service

from .output import render_search_table

_console = Console()


def _check_es() -> None:
    if not get_es_client().ping():
        _console.print("[bold red]Cannot connect to Elasticsearch.[/]")
        raise SystemExit(3)


@click.command("search")
@click.argument("query")
@click.option(
    "--type",
    "-t",
    "listing_type",
    type=click.Choice(["sell", "buy", "all"]),
    default="all",
    help="Listing type filter (sell / buy / all)",
)
@click.option(
    "--category",
    "-c",
    default=None,
    type=click.Choice([cat.value for cat in Category]),
    help="Filter by category",
)
@click.option("--max-price", "-p", default=None, type=int, help="Maximum price")
@click.option("--lat", default=None, type=float, help="Search origin latitude")
@click.option("--lon", default=None, type=float, help="Search origin longitude")
@click.option("--radius", default=None, help="Geo-radius (e.g. 10km)")
@click.option("--limit", "-n", default=10, type=int, help="Number of results")
def search(
    query: str,
    listing_type: str,
    category: str | None,
    max_price: int | None,
    lat: float | None,
    lon: float | None,
    radius: str | None,
    limit: int,
) -> None:
    """Search listings using hybrid search (BM25 + kNN vector).

    \b
    Examples:
      agora search "iphone 14" --type sell --max-price 30000000
      agora search "honda motorbike" --category xe-may --lat 21.02 --lon 105.85 --radius 10km
    """
    _check_es()
    ltype = None if listing_type == "all" else listing_type
    with _console.status(f"[bold cyan]Searching: [italic]{query}[/]…"):
        hits = make_search_service().search(
            query,
            listing_type=ltype,
            category=category,
            max_price=max_price,
            lat=lat,
            lon=lon,
            radius=radius,
            limit=limit,
        )
    if not hits:
        _console.print("[yellow]No results found.[/]")
        return
    render_search_table(hits, query)
