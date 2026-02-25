"""``agora delete`` command — hard-delete a listing from Elasticsearch."""

from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel

from src.config import settings
from src.infrastructure.es_client import get_es_client
from src.infrastructure.kafka_producer import send_command
from src.services.factories import make_listing_service

_console = Console()


def _check_es() -> None:
    if not get_es_client().ping():
        _console.print("[bold red]Cannot connect to Elasticsearch.[/]")
        raise SystemExit(3)


@click.command("delete")
@click.option("--id", "-i", "listing_id", required=True, help="Listing ID to delete")
@click.confirmation_option(prompt="Permanently delete this listing? This cannot be undone.")
def delete(listing_id: str) -> None:
    """Hard-delete a listing (or queue a delete command to the worker)."""
    if settings.KAFKA_WRITE_MODE:
        offset = send_command("delete", {"id": listing_id})
        _console.print(
            Panel(
                f"[bold green]Delete queued ✔[/]\n"
                f"[dim]Kafka offset:[/] [yellow]{offset}[/]\n"
                f"[dim]Listing ID:[/] {listing_id}\n"
                f"[dim]Worker will delete from Elasticsearch shortly.[/]",
                title="DELETE → QUEUED",
                border_style="yellow",
            )
        )
        return
    _check_es()
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
