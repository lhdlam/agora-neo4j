---
name: add_cli_command
description: >
  Add a new top-level `agora <command>` subcommand to the CLI.
  Covers Click command creation, service wiring via factory, Rich output, and registration.
  Use this skill whenever the task is to expose a new feature via the CLI.
---

# Skill: Add a New CLI Command

## When to use
- Adding a new subcommand: `agora <cmd>` or `agora <group> <sub>`.
- Extending an existing command with new options.

## Architecture reminder

```
src/commands/<cmd>.py     ← Click command (arg parsing, validation, Rich output)
src/commands/output.py    ← Shared Rich render helpers (tables, panels)
src/services/<svc>.py     ← Business logic (framework-agnostic)
src/services/factories.py ← DI wiring (make_<svc>_service())
src/ports/<port>.py       ← Protocol/interface for infrastructure
src/infrastructure/*.py   ← ES / embedder / Kafka (concrete adapters)
```

**Imports flow in ONE direction:** `commands` → `services` → `infrastructure` → `domain`. Never reverse.

---

## Step-by-step

### Step 1 — Create `src/commands/<cmd>.py`

```python
"""<Short description of this command>."""

from __future__ import annotations

import logging

import click
from rich.console import Console

from src.infrastructure.es_client import get_es_client
from src.services.factories import make_<svc>_service

_console = Console()
logger = logging.getLogger(__name__)


def _check_es() -> None:
    if not get_es_client().ping():
        _console.print("[bold red]Cannot connect to Elasticsearch.[/]")
        raise SystemExit(3)


@click.command("<cmd-name>")
@click.option("--option", "-o", type=str, required=True, help="Description.")
@click.option("--flag", is_flag=True, default=False, help="Description.")
def <cmd_name>(option: str, flag: bool) -> None:
    """One-line CLI help string shown in `agora --help`."""
    _check_es()
    svc = make_<svc>_service()
    try:
        result = svc.do_thing(option, flag=flag)
        _console.print(f"[green]✓[/green] Done: {result}")
    except <SpecificError> as exc:
        logger.debug("Command failed", exc_info=True)
        _console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1) from exc
```

Click rules:
- Use `raise SystemExit(<code>)` for early exits: 1=user error, 3=infra unavailable.
- Use `@click.argument` for positional args, `@click.option` for named options.
- Always provide `help=` strings for every option.
- For enum-constrained options: `type=click.Choice([e.value for e in MyEnum])`.
- No `print()` — use `Console().print()` only.
- Use `@click.confirmation_option(prompt="…")` for destructive actions.

### Step 2 — Add factory to `src/services/factories.py`

If you created a new service, add a factory function:

```python
def make_<svc>_service() -> <SvcClass>:
    """Return a production-wired :<SvcClass>:."""
    return <SvcClass>(
        store=get_es_client(),
        embedder=get_embedder(),
        event_bus=_get_kafka_producer(),
    )
```

**Tests** should never call factories — they inject fakes directly into the service constructor.

### Step 3 — Register in `src/commands/__init__.py`

```python
# 1. Import at top with other command imports
from src.commands.<cmd> import <cmd_name>

# 2. Add to register() function
def register(group: click.Group) -> None:
    group.add_command(post)
    group.add_command(import_cmd, name="import")
    group.add_command(search)
    group.add_command(match)
    group.add_command(delete)
    group.add_command(<cmd_name>)  # ← add here

# 3. Add to __all__
__all__ = [..., "<cmd_name>"]
```

`cli.py` calls `register(cli)` once — you **do not** need to touch `cli.py` unless adding a new top-level group.

### Step 4 — Add Rich output to `src/commands/output.py`

Put any reusable render function here (tables, panels, progress bars):

```python
def render_<cmd>_result(items: list[dict]) -> None:
    table = Table(title="Results", header_style="bold cyan")
    table.add_column("ID", style="dim")
    table.add_column("Title")
    for item in items:
        table.add_row(item["id"], item["title"])
    console.print(table)
```

Import from command file:
```python
from .output import render_<cmd>_result
```

### Step 5 — Write tests

File: `src/tests/commands/test_<cmd>.py`

**Patch the factory function, not the service class:**

```python
from click.testing import CliRunner
from unittest.mock import MagicMock, patch
from src.cli import cli


def _mock_es_ok():
    m = MagicMock()
    m.ping.return_value = True
    return m


class Test<Cmd>Command:
    def test_success(self):
        mock_svc = MagicMock()
        mock_svc.do_thing.return_value = "ok"
        with (
            patch("src.commands.<cmd>.get_es_client", return_value=_mock_es_ok()),
            patch("src.commands.<cmd>.make_<svc>_service", return_value=mock_svc),
        ):
            result = CliRunner().invoke(cli, ["<cmd-name>", "--option", "val"])
        assert result.exit_code == 0
        assert "ok" in result.output

    def test_es_unreachable_exits_3(self):
        mock_es = MagicMock()
        mock_es.ping.return_value = False
        with patch("src.commands.<cmd>.get_es_client", return_value=mock_es):
            result = CliRunner().invoke(cli, ["<cmd-name>", "--option", "val"])
        assert result.exit_code == 3
```

### Step 6 — Run checks

```bash
make check   # format + lint + typecheck + test (must pass with 0 errors)
```

---

## Common patterns

### Subcommand group (e.g., `agora post sell` / `agora post buy`)

```python
post = click.Group("post", help="Post a listing (sell or buy).")

@post.command("sell")
@click.option(...)
def post_sell(...) -> None: ...

@post.command("buy")
@click.option(...)
def post_buy(...) -> None: ...
```

Register in `__init__.py`: `group.add_command(post)`

### Pagination / limit option

```python
@click.option("--limit", "-n", type=int, default=10, show_default=True, help="Max results.")
```

### Confirmation prompt (destructive actions)

```python
@click.confirmation_option(prompt="This will delete the listing. Continue?")
def delete(listing_id: str) -> None:
    ...
```
