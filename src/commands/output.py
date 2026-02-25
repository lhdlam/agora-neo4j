"""
Rich output helpers for Agora CLI commands.

All rendering logic lives here so individual command modules stay focused on
argument parsing and service orchestration only.  No Click or service imports
here — this module is purely about presentation.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
_err_console = Console(stderr=True)


def score_bar(score: float) -> str:
    """Return a 5-char unicode bar representing a 0–1 score."""
    filled = int(round(score * 5))
    return "█" * filled + "░" * (5 - filled)


def extract_contact(hit: dict[str, Any]) -> str:
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


def render_search_table(hits: list[dict[str, Any]], query: str) -> None:
    """Render a Rich table of hybrid search results."""
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
    console.print(table)


def render_match_table(
    results: list[Any],
    *,
    query_label: str,
    budget: int | None,
    currency: str,
    category: str | None,
    min_score: float,
) -> None:
    """Render a Rich table of BUY→SELL match results."""
    budget_str = f"{budget:,} {currency}" if budget else "—"
    header = (
        f"[bold]Query:[/] [italic]{query_label}[/]\n"
        f"[bold]Budget:[/] [yellow]{budget_str}[/]   "
        f"[bold]Category:[/] [cyan]{category or 'all'}[/]   "
        f"[bold]Min-score:[/] [dim]{min_score:.0%}[/]"
    )
    console.print(Panel(header, title="[bold magenta]MATCH RESULTS[/]", border_style="magenta"))
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
        bar = score_bar(result.score)
        table.add_row(
            str(idx),
            hit.get("title", "")[:36],
            price_str,
            hit.get("city") or hit.get("location") or "—",
            extract_contact(hit),
            f"{bar} {result.score * 100:.0f}%",
        )
    console.print(table)


def render_import_summary(
    total: int, validation_errors: int, indexed_ok: int, index_errors: int
) -> None:
    """Render a Rich summary table for the import command."""
    table = Table(title="Import Summary", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="dim")
    table.add_column("Count", justify="right")
    table.add_row("Total in file", str(total))
    table.add_row("Validation errors", str(validation_errors))
    table.add_row("[green]Indexed OK[/]", f"[green]{indexed_ok}[/]")
    table.add_row("[red]Index errors[/]", f"[red]{index_errors}[/]")
    console.print(table)
