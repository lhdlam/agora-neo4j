"""``agora import`` command — bulk-import listings from JSON or CSV."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import click
from pydantic import ValidationError
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from src.config import settings
from src.domain.models import Listing
from src.infrastructure.es_client import get_es_client
from src.infrastructure.kafka_producer import send_command
from src.services.factories import make_listing_service

from .output import render_import_summary

_console = Console()


def _check_es() -> None:
    if not get_es_client().ping():
        _console.print("[bold red]Cannot connect to Elasticsearch.[/]")
        raise SystemExit(3)


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
    """Import listings from a JSON or CSV file (or queue them to the worker)."""
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
        _console.print(f"[yellow]Warning: {len(validation_errors)} records failed validation:[/]")
        for e in validation_errors[:10]:
            _console.print(f"  [dim]Row {e['row']}:[/] [red]{e['error'][:120]}[/]")
    if not listings:
        _console.print("[red]No valid records to import.[/]")
        raise SystemExit(1)

    if settings.KAFKA_WRITE_MODE:
        _kafka_import(listings, validation_errors, raw_records)
    else:
        _sync_import(listings, validation_errors, raw_records)


def _kafka_import(
    listings: list[Listing],
    validation_errors: list[dict[str, Any]],
    raw_records: list[dict[str, Any]],
) -> None:
    """Send each listing as a CommandMessage to the listing.commands topic."""
    _console.print(f"[cyan]→ Queuing {len(listings)} records to Kafka…[/]")
    queued = 0
    kafka_errors = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        transient=True,
    ) as progress:
        task = progress.add_task("[yellow]Queuing…", total=len(listings))
        for listing in listings:
            try:
                send_command("create", listing.model_dump(mode="json"))
                queued += 1
            except Exception:
                kafka_errors += 1
            progress.advance(task)
    render_import_summary(
        total=len(raw_records),
        validation_errors=len(validation_errors),
        indexed_ok=queued,
        index_errors=kafka_errors,
    )


def _sync_import(
    listings: list[Listing],
    validation_errors: list[dict[str, Any]],
    raw_records: list[dict[str, Any]],
) -> None:
    """Embed + index listings directly (sync mode, no Kafka)."""
    _check_es()
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
    render_import_summary(
        total=len(raw_records),
        validation_errors=len(validation_errors),
        indexed_ok=ok,
        index_errors=err_count,
    )
