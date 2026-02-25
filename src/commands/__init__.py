"""
Commands package — registers all Agora CLI sub-commands.

Usage in cli.py::

    from src.commands import register
    register(cli)
"""

from __future__ import annotations

import click

# Kept for backward-compat with any code that imported AgoraCLI directly.
# All new code should call register() instead.
from src.commands.commands import AgoraCLI  # noqa: F401
from src.commands.delete_cmd import delete
from src.commands.import_cmd import import_cmd
from src.commands.match_cmd import match
from src.commands.post import post
from src.commands.search_cmd import search


def register(group: click.Group) -> None:
    """Register all Agora commands on a Click group."""
    group.add_command(post)
    group.add_command(import_cmd, name="import")
    group.add_command(search)
    group.add_command(match)
    group.add_command(delete)


__all__ = [
    "register",
    "post",
    "import_cmd",
    "search",
    "match",
    "delete",
    "AgoraCLI",
]
