"""CLI entry point – registers all sub-commands."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
import logging

import click
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from src.commands import register
from src.error_handling import dispatch

# Stderr console for error output (never mixed with normal stdout output)
_err = Console(stderr=True)
_out = Console()

try:
    _version = pkg_version("agora-market")
except PackageNotFoundError:  # pragma: no cover
    _version = "dev"


# ─────────────────────────────────────────────────────────────────────────────
# Colored banner (printed at runtime, not in docstring — Click strips ANSI)
# ─────────────────────────────────────────────────────────────────────────────

_BANNER_LINES = [
    " █████╗  ██████╗  ██████╗ ██████╗  █████╗ ",
    "██╔══██╗██╔════╝ ██╔═══██╗██╔══██╗██╔══██╗",
    "███████║██║  ███╗██║   ██║██████╔╝███████║",
    "██╔══██║██║   ██║██║   ██║██╔══██╗██╔══██║",
    "██║  ██║╚██████╔╝╚██████╔╝██║  ██║██║  ██║",
    "╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝",
]

_BANNER_COLOR = "bold #fbbf24"  # yellow-400 — bright, vivid, clear on dark terminals


def _print_banner() -> None:
    """Print the colored ASCII banner to stdout."""
    banner = Text()
    for line in _BANNER_LINES:
        banner.append(line + "\n", style=_BANNER_COLOR)
    _out.print(banner)


# ─────────────────────────────────────────────────────────────────────────────
# Custom Group with global error handling
# ─────────────────────────────────────────────────────────────────────────────


class _CLIGroup(click.Group):
    """
    Click Group subclass that catches unhandled exceptions and renders them
    as clean Rich panels instead of raw Python tracebacks.

    Use ``--debug`` to bypass and see the full stack trace.
    """

    def make_context(
        self,
        info_name: str | None,
        args: list[str],
        parent: click.Context | None = None,
        **extra: object,
    ) -> click.Context:
        _print_banner()
        return super().make_context(info_name, args, parent=parent, **extra)

    def invoke(self, ctx: click.Context) -> object:
        try:
            return super().invoke(ctx)
        except (SystemExit, KeyboardInterrupt, click.exceptions.Abort):
            # SystemExit / Ctrl-C — let Click handle these normally
            raise
        except click.ClickException:
            # Click's own exceptions (bad params, usage errors) — let Click render them
            raise
        except Exception as exc:
            debug: bool = ctx.params.get("debug", False)

            if debug:  # pragma: no cover
                # Full traceback for developers
                _err.print_exception(show_locals=True)
                ctx.exit(1)
            else:
                result = dispatch(exc)
                _err.print(
                    Panel(
                        result.body,
                        title=f"[bold red]{result.title}[/]",
                        border_style="red",
                        padding=(0, 1),
                    )
                )
                ctx.exit(result.exit_code)


# ─────────────────────────────────────────────────────────────────────────────
# CLI group
# ─────────────────────────────────────────────────────────────────────────────


@click.group(cls=_CLIGroup)
@click.version_option(_version, prog_name="agora")
@click.option(
    "--debug", is_flag=True, default=False, help="Enable debug logging and full tracebacks."
)
def cli(debug: bool) -> None:
    """
    AI-powered classified ads — buy, sell, search & match listings.

    \b
    Run  agora <command> --help  for detailed options.
    """
    level = logging.DEBUG if debug else logging.WARNING
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=level,
    )

    if not debug:
        # elastic_transport and urllib3 print retry tracebacks at WARNING level
        # (via logger.warning(exc_info=True)) — suppress them in normal mode so
        # our own error handler can present a clean message instead.
        for _noisy in (
            "elastic_transport",
            "urllib3",
            "urllib3.connectionpool",
            "elasticsearch",
            "kafka",  # silences kafka.client, kafka.producer.sender, kafka.future, etc.
        ):
            logging.getLogger(_noisy).setLevel(logging.CRITICAL)


register(cli)


if __name__ == "__main__":  # pragma: no cover
    cli()
