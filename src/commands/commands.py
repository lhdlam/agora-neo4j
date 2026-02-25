"""All Agora CLI commands consolidated into a single AgoraCLI class."""

from __future__ import annotations

from collections.abc import Callable
import csv
import json
from pathlib import Path
from typing import Any

import click
from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

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
from src.services.factories import make_listing_service, make_match_service, make_search_service
from src.services.match_service import MatchResult

# ─────────────────────────────────────────────────────────────────────────────
# Module-level helpers
# ─────────────────────────────────────────────────────────────────────────────

_console = Console()

# The "post" group must be module-level so that @_post.command(…) can be
# used as a decorator inside the AgoraCLI class body.
_post: click.Group = click.Group(
    "post", help="Post a classified listing (sell or buy)."
)  # pragma: no cover


def _common_options(f: Callable[..., Any]) -> Callable[..., Any]:  # pragma: no cover
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


# ─────────────────────────────────────────────────────────────────────────────
# AgoraCLI — single-class namespace for all commands
# ─────────────────────────────────────────────────────────────────────────────


class AgoraCLI:  # pragma: no cover
    """
    Single-class namespace for all Agora CLI commands and output helpers.

    Register all commands at once::

        AgoraCLI.register(cli_group)

    Or individually::

        cli.add_command(AgoraCLI.post)
        cli.add_command(AgoraCLI.import_cmd, name="import")
        cli.add_command(AgoraCLI.search)
        cli.add_command(AgoraCLI.match)
        cli.add_command(AgoraCLI.delete)
    """

    # ── Registration ───────────────────────────────────────────────────────

    @classmethod
    def register(cls, group: click.Group) -> None:
        """Register all AgoraCLI commands on a Click group."""
        group.add_command(cls.post)
        group.add_command(cls.import_cmd, name="import")
        group.add_command(cls.search)
        group.add_command(cls.match)
        group.add_command(cls.delete)

    # ── Guard ──────────────────────────────────────────────────────────────

    @staticmethod
    def _check_es() -> None:
        """Exit with code 3 if Elasticsearch is not reachable."""
        if not get_es_client().ping():
            _console.print("[bold red]Cannot connect to Elasticsearch.[/]")
            raise SystemExit(3)

    # ── Output helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _score_bar(score: float) -> str:
        filled = int(round(score * 5))
        return "█" * filled + "░" * (5 - filled)

    @staticmethod
    def _extract_contact(hit: dict[str, Any]) -> str:
        """Handle both list (kNN hits) and dict (get()) ES contact formats."""
        contact = hit.get("contact")
        c: dict[str, Any] | None = None
        if isinstance(contact, list) and contact:
            c = contact[0]
        elif isinstance(contact, dict):
            c = contact
        if c is None:
            return "—"
        return str(c.get("phone") or c.get("email") or "—")

    @staticmethod
    def _render_search_table(hits: list[dict[str, Any]], query: str) -> None:
        table = Table(
            title=f'Search: "{query}"  ({len(hits)} results)',
            show_header=True,
            header_style="bold magenta",
            border_style="dim",
        )
        table.add_column("#", justify="right", style="dim", max_width=4)
        table.add_column("Type", justify="center", style="cyan", max_width=6)
        table.add_column("Title", style="bold", max_width=40)
        table.add_column("Category", style="dim", max_width=14)
        table.add_column("Price", justify="right", style="yellow", max_width=14)
        table.add_column("City", style="dim", max_width=14)
        table.add_column("Score", justify="right", style="green", max_width=8)
        for idx, hit in enumerate(hits, 1):
            price_raw = hit.get("price") or hit.get("budget_max")
            price_str = f"{price_raw:,}" if price_raw else "—"
            table.add_row(
                str(idx),
                "SELL" if hit.get("type") == "sell" else "BUY",
                hit.get("title", "")[:38],
                hit.get("category", ""),
                f"{price_str} {hit.get('price_currency', '')}",
                hit.get("city") or hit.get("location") or "—",
                f"{hit.get('_score', 0.0):.3f}",
            )
        _console.print(table)

    @staticmethod
    def _render_match_table(
        results: list[MatchResult],
        *,
        query_label: str,
        budget: int | None,
        currency: str,
        category: str | None,
        min_score: float,
    ) -> None:
        budget_str = f"{budget:,} {currency}" if budget else "—"
        header = (
            f"[bold]Query:[/] [italic]{query_label}[/]\n"
            f"[bold]Budget:[/] [yellow]{budget_str}[/]   "
            f"[bold]Category:[/] [cyan]{category or 'all'}[/]   "
            f"[bold]Min-score:[/] [dim]{min_score:.0%}[/]"
        )
        _console.print(
            Panel(header, title="[bold magenta]MATCH RESULTS[/]", border_style="magenta")
        )
        table = Table(show_header=True, header_style="bold cyan", border_style="dim")
        table.add_column("#", justify="right", style="dim", max_width=4)
        table.add_column("Title", style="bold", max_width=38)
        table.add_column("Price", justify="right", style="yellow", max_width=16)
        table.add_column("City", style="dim", max_width=12)
        table.add_column("Contact", style="dim", max_width=14)
        table.add_column("Match %", justify="right", style="green", max_width=10)
        for idx, result in enumerate(results, 1):
            hit = result.listing
            price_raw = hit.get("price")
            price_str = f"{price_raw:,} {hit.get('price_currency', '')}" if price_raw else "—"
            bar = AgoraCLI._score_bar(result.score)
            table.add_row(
                str(idx),
                hit.get("title", "")[:36],
                price_str,
                hit.get("city") or hit.get("location") or "—",
                AgoraCLI._extract_contact(hit),
                f"{bar} {result.score * 100:.0f}%",
            )
        _console.print(table)

    @staticmethod
    def _render_import_summary(
        total: int, validation_errors: int, indexed_ok: int, index_errors: int
    ) -> None:
        table = Table(title="Import Summary", show_header=True, header_style="bold magenta")
        table.add_column("Metric", style="dim")
        table.add_column("Count", justify="right")
        table.add_row("Total in file", str(total))
        table.add_row("Validation errors", str(validation_errors))
        table.add_row("[green]Indexed OK[/]", f"[green]{indexed_ok}[/]")
        table.add_row("[red]Index errors[/]", f"[red]{index_errors}[/]")
        _console.print(table)

    # ── post group ─────────────────────────────────────────────────────────

    post = _post  # expose the Click group as a class attribute

    @staticmethod
    @_post.command("sell")
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
        AgoraCLI._check_es()
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

    @staticmethod
    @_post.command("buy")
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
        AgoraCLI._check_es()
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

    # ── import ─────────────────────────────────────────────────────────────

    @staticmethod
    @click.command("import")
    @click.option(
        "--file", "-f", required=True, type=click.Path(exists=True), help="Path to JSON or CSV file"
    )
    @click.option(
        "--format",
        "-F",
        "fmt",
        default="json",
        type=click.Choice(["json", "csv"]),
        help="File format",
    )
    def import_cmd(file: str, fmt: str) -> None:
        """Import listings from a JSON or CSV file into Elasticsearch."""
        AgoraCLI._check_es()
        path = Path(file)
        _console.rule(f"[bold]Importing from [cyan]{path.name}[/][/]")
        if fmt == "json":
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
            raw_records: list[dict[str, Any]] = data if isinstance(data, list) else [data]
        else:
            with path.open(encoding="utf-8", newline="") as f:
                raw_records = list(csv.DictReader(f))
        _console.print(f"[dim]→ {len(raw_records)} records found in file[/]")
        listings: list[Listing] = []
        validation_errors: list[dict[str, Any]] = []
        for i, record in enumerate(raw_records):
            try:
                listings.append(Listing.model_validate(record))
            except ValidationError as exc:
                validation_errors.append({"row": i + 1, "error": str(exc)})
        if validation_errors:
            _console.print(
                f"[yellow]Warning: {len(validation_errors)} records failed validation:[/]"
            )
            for e in validation_errors[:10]:
                _console.print(f"  [dim]Row {e['row']}:[/] [red]{e['error'][:120]}[/]")
        if not listings:
            _console.print("[red]No valid records to import.[/]")
            raise SystemExit(1)
        _console.print(f"[cyan]→ Embedding and indexing {len(listings)} valid records…[/]")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task("[cyan]Indexing…", total=len(listings))

            def _on_progress(completed: int, total: int) -> None:
                progress.update(task, completed=completed)

            ok, err_count = make_listing_service().bulk_import(listings, on_progress=_on_progress)
        AgoraCLI._render_import_summary(
            total=len(raw_records),
            validation_errors=len(validation_errors),
            indexed_ok=ok,
            index_errors=err_count,
        )

    # ── search ─────────────────────────────────────────────────────────────

    @staticmethod
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
        AgoraCLI._check_es()
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
        AgoraCLI._render_search_table(hits, query)

    # ── match ──────────────────────────────────────────────────────────────

    @staticmethod
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
        AgoraCLI._check_es()
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
        AgoraCLI._render_match_table(
            results,
            query_label=query_label,
            budget=budget or _doc.get("budget_max"),
            currency=currency,
            category=category or _doc.get("category"),
            min_score=min_score,
        )

    # ── delete ─────────────────────────────────────────────────────────────

    @staticmethod
    @click.command("delete")
    @click.option("--id", "-i", "listing_id", required=True, help="Listing ID to delete")
    @click.confirmation_option(prompt="Permanently delete this listing? This cannot be undone.")
    def delete(listing_id: str) -> None:
        """Hard-delete a listing from Elasticsearch (irreversible)."""
        AgoraCLI._check_es()
        service = make_listing_service()
        doc = service.get(listing_id)
        if not doc:
            _console.print(f"[yellow]Listing id={listing_id} not found.[/]")
            raise SystemExit(1)
        deleted = service.delete(listing_id)
        if deleted:
            _console.print(
                f'[bold green]Deleted listing [yellow]{listing_id}[/] — "{doc.get("title", "")}"[/]'
            )
        else:
            _console.print(f"[red]Failed to delete id={listing_id}.[/]")
            raise SystemExit(3)
