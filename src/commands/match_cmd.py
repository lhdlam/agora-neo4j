"""``agora match`` command — semantic BUY→SELL matching with re-ranking."""

from __future__ import annotations

from typing import Any

import click
from rich.console import Console

from src.config import settings
from src.domain.models import Category
from src.infrastructure.es_client import get_es_client
from src.services.factories import make_listing_service, make_match_service

from .output import render_match_table

_console = Console()


def _check_es() -> None:
    if not get_es_client().ping():
        _console.print("[bold red]Cannot connect to Elasticsearch.[/]")
        raise SystemExit(3)


@click.command("match")
@click.option("--buy-id", default=None, help="ID of an existing BUY listing in ES")
@click.option("--query", "-q", default=None, help="Free-text description of what you want")
@click.option("--budget", "-b", default=None, type=int, help="Maximum budget")
@click.option("--currency", default="VND", help="ISO-4217 currency code")
@click.option(
    "--category",
    "-c",
    default=None,
    type=click.Choice([cat.value for cat in Category]),
    help="Preferred category",
)
@click.option("--lat", default=None, type=float, help="Search origin latitude")
@click.option("--lon", default=None, type=float, help="Search origin longitude")
@click.option("--radius", default=None, help="Geo-radius (e.g. 10km)")
@click.option("--top", "-n", default=settings.MATCH_TOP_K, type=int, help="Number of results")
@click.option(
    "--min-score",
    default=settings.MATCH_MIN_COSINE_SCORE,
    type=float,
    show_default=True,
    help="Minimum cosine similarity threshold (0–1)",
)
def match(
    buy_id: str | None,
    query: str | None,
    budget: int | None,
    currency: str,
    category: str | None,
    lat: float | None,
    lon: float | None,
    radius: str | None,
    top: int,
    min_score: float,
) -> None:
    """Find SELL listings that best match a BUY intent (semantic matching).

    \b
    Logic:
      1. Embed query -> kNN search on SELL listings (budget = HARD filter in ES)
      2. Discard results with cosine similarity < --min-score  (default 0.65)
      3. Re-rank: +bonus for same category, same city

    \b
    Examples:
      agora match --query "looking for iphone 14 pro" --budget 26000000
      agora match --buy-id <uuid>
    """
    _check_es()
    if not buy_id and not query:
        _console.print("[red]Provide either --buy-id or --query.[/]")
        raise SystemExit(1)
    buy_doc: dict[str, Any] | None = None
    with _console.status("[bold cyan]Preparing match…"):
        if buy_id:
            buy_doc = make_listing_service().get(buy_id)
            if not buy_doc:
                _console.print(f"[red]Buy listing id={buy_id} not found.[/]")
                raise SystemExit(1)
        results = make_match_service().match(
            query=query,
            buy_doc=buy_doc,
            category=category,
            budget=budget,
            lat=lat,
            lon=lon,
            radius=radius,
            top=top,
            min_score=min_score,
        )
    if not results:
        budget_str = f"{budget:,} {currency}" if budget else "any"
        _console.print(
            f"[yellow]No results above min-score={min_score:.0%}"
            f"{f' within budget {budget_str}' if budget else ''}.[/]"
        )
        return
    _doc: dict[str, Any] = buy_doc or {}
    query_label = (_doc.get("title") or query or "—")[:50]
    render_match_table(
        results,
        query_label=query_label,
        budget=budget or _doc.get("budget_max"),
        currency=currency,
        category=category or _doc.get("category"),
        min_score=min_score,
    )
