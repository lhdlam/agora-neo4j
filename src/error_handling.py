"""
Registry-based CLI error dispatcher.

Usage
-----
Register a custom handler at import time (e.g. in a command module)::

    from src.error_handling import PredicateHandler, register_handler

    register_handler(
        PredicateHandler(
            match=lambda exc: isinstance(exc, MyDomainError),
            title="Domain Error",
            body_fn=lambda exc: str(exc),
            exit_code=4,
        )
    )

Then in the CLI group::

    from src.error_handling import dispatch

    result = dispatch(exc)
    _err.print(Panel(result.body, title=f"[bold red]{result.title}[/]", ...))
    ctx.exit(result.exit_code)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
import json
import logging

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Result type
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ErrorResult:
    """Human-friendly error data to display in a Rich panel."""

    title: str
    body: str
    exit_code: int = field(default=1)


# ─────────────────────────────────────────────────────────────────────────────
# Handler base + concrete implementations
# ─────────────────────────────────────────────────────────────────────────────


class BaseHandler(ABC):
    """Abstract base for all error handlers."""

    @abstractmethod
    def matches(self, exc: Exception) -> bool:
        """Return True if this handler should process *exc*."""

    @abstractmethod
    def build(self, exc: Exception) -> ErrorResult:
        """Build the ErrorResult for *exc*."""


class TypeHandler(BaseHandler):
    """Match by exact *isinstance* check — the most precise handler type."""

    def __init__(
        self,
        exc_types: type[Exception] | tuple[type[Exception], ...],
        title: str,
        body_fn: Callable[[Exception], str],
        exit_code: int = 1,
    ) -> None:
        self._exc_types = exc_types
        self._title = title
        self._body_fn = body_fn
        self._exit_code = exit_code

    def matches(self, exc: Exception) -> bool:
        return isinstance(exc, self._exc_types)

    def build(self, exc: Exception) -> ErrorResult:
        return ErrorResult(title=self._title, body=self._body_fn(exc), exit_code=self._exit_code)


class PredicateHandler(BaseHandler):
    """Match by an arbitrary callable predicate — maximum flexibility."""

    def __init__(
        self,
        match: Callable[[Exception], bool],
        title: str,
        body_fn: Callable[[Exception], str],
        exit_code: int = 1,
    ) -> None:
        self._match = match
        self._title = title
        self._body_fn = body_fn
        self._exit_code = exit_code

    def matches(self, exc: Exception) -> bool:
        try:
            return self._match(exc)
        except Exception:  # noqa: BLE001 — predicate must never crash the dispatcher
            return False

    def build(self, exc: Exception) -> ErrorResult:
        return ErrorResult(title=self._title, body=self._body_fn(exc), exit_code=self._exit_code)


class NameHandler(BaseHandler):
    """Match by substring in the exception class name.

    Fallback for libs without a stable exception class hierarchy.
    """

    def __init__(
        self,
        name_fragments: str | tuple[str, ...],
        title: str,
        body_fn: Callable[[Exception], str],
        exit_code: int = 1,
    ) -> None:
        self._fragments = (name_fragments,) if isinstance(name_fragments, str) else name_fragments
        self._title = title
        self._body_fn = body_fn
        self._exit_code = exit_code

    def matches(self, exc: Exception) -> bool:
        name = type(exc).__name__
        return any(frag in name for frag in self._fragments)

    def build(self, exc: Exception) -> ErrorResult:
        return ErrorResult(title=self._title, body=self._body_fn(exc), exit_code=self._exit_code)


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

_REGISTRY: list[BaseHandler] = []


def register_handler(handler: BaseHandler) -> None:
    """Append *handler* to the global registry. First-match-wins ordering.

    Call this at module import time (e.g. top of a command module) to register
    domain-specific handlers without touching ``cli.py``.
    """
    _REGISTRY.append(handler)


# ─────────────────────────────────────────────────────────────────────────────
# Dispatcher
# ─────────────────────────────────────────────────────────────────────────────

#: Catch-all displayed when no registered handler matches.
_CATCH_ALL = ErrorResult(
    title="Unexpected Error",
    body=("{name}: {msg}\n\n[dim]Run with [bold]--debug[/bold] to see the full traceback.[/dim]"),
    exit_code=1,
)


def dispatch(exc: Exception) -> ErrorResult:
    """Walk the registry and return the first matching ErrorResult.

    Falls back to a generic "Unexpected Error" panel when no handler matches.
    """
    for handler in _REGISTRY:
        if handler.matches(exc):
            try:
                return handler.build(exc)
            except Exception:  # noqa: BLE001 — handler.build must never crash the CLI
                logger.exception("Error handler %r failed to build result for %r", handler, exc)
                break

    # Catch-all
    name = type(exc).__name__
    msg = str(exc)[:200]
    return ErrorResult(
        title=_CATCH_ALL.title,
        body=_CATCH_ALL.body.format(name=name, msg=msg),
        exit_code=_CATCH_ALL.exit_code,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Built-in handler registrations
# ─────────────────────────────────────────────────────────────────────────────


def _truncated(msg: str, limit: int = 120) -> str:
    return msg if len(msg) <= limit else msg[:limit] + "…"


def _register_defaults() -> None:
    """Register all built-in handlers. Called once at module import."""

    # ── 1. Elasticsearch connection error (lazy import — ES may not be installed) ──
    def _es_conn_match(exc: Exception) -> bool:
        try:
            from elastic_transport import ConnectionError as _ESConnErr  # noqa: A001

            return isinstance(exc, _ESConnErr)
        except ImportError:  # pragma: no cover
            return False  # pragma: no cover

    register_handler(
        PredicateHandler(
            match=_es_conn_match,
            title="Connection Error",
            body_fn=lambda exc: f"Cannot reach Elasticsearch.\n[dim]{_truncated(str(exc))}[/dim]",
            exit_code=1,
        )
    )

    # ── 2. Pydantic ValidationError ───────────────────────────────────────────
    try:
        from pydantic import ValidationError as _PydanticValidationError

        register_handler(
            TypeHandler(
                exc_types=_PydanticValidationError,
                title="Validation Error",
                body_fn=lambda exc: (
                    f"Input validation failed:\n[dim]{_truncated(str(exc), 300)}[/dim]"
                ),
                exit_code=2,
            )
        )
    except ImportError:  # pragma: no cover
        pass  # pragma: no cover

    # ── 3. Standard library: file & permission ────────────────────────────────
    # IMPORTANT: must come BEFORE NameHandler("NotFoundError") because
    # FileNotFoundError's class name contains "NotFoundError" — isinstance
    # checks are always preferred over name-based matching.
    register_handler(
        TypeHandler(
            exc_types=FileNotFoundError,
            title="File Not Found",
            body_fn=lambda exc: (
                f"[yellow]{getattr(exc, 'filename', str(exc))}[/yellow] does not exist."
            ),
            exit_code=1,
        )
    )
    register_handler(
        TypeHandler(
            exc_types=PermissionError,
            title="Permission Denied",
            body_fn=lambda exc: (
                f"Cannot read/write [yellow]{getattr(exc, 'filename', str(exc))}[/yellow]."
            ),
            exit_code=1,
        )
    )

    # ── 4. JSON decode error ──────────────────────────────────────────────────
    register_handler(
        TypeHandler(
            exc_types=json.JSONDecodeError,
            title="Invalid JSON",
            body_fn=lambda exc: f"The file is not valid JSON.\n[dim]{_truncated(str(exc))}[/dim]",
            exit_code=1,
        )
    )

    # ── 5. Elasticsearch NotFoundError (name-based — covers all ES versions) ─
    # Placed after stdlib TypeHandlers to avoid false-matching FileNotFoundError.
    register_handler(
        NameHandler(
            name_fragments="NotFoundError",
            title="Not Found",
            body_fn=lambda exc: (
                f"The resource was not found in Elasticsearch.\n[dim]{_truncated(str(exc))}[/dim]"
            ),
            exit_code=3,
        )
    )

    # ── 6. Elasticsearch bad request ─────────────────────────────────────────
    register_handler(
        NameHandler(
            name_fragments=("RequestError", "BadRequestError"),
            title="Bad Request",
            body_fn=lambda exc: (
                f"Elasticsearch rejected the query.\n[dim]{_truncated(str(exc))}[/dim]"
            ),
            exit_code=1,
        )
    )

    # ── 7. Elasticsearch auth error ───────────────────────────────────────────
    register_handler(
        NameHandler(
            name_fragments=("AuthenticationException", "AuthorizationException"),
            title="Auth Error",
            body_fn=lambda exc: (
                f"Elasticsearch authentication failed.\n[dim]{_truncated(str(exc))}[/dim]"
            ),
            exit_code=1,
        )
    )

    # ── 8. fastembed / embedding model errors ─────────────────────────────────
    register_handler(
        PredicateHandler(
            match=lambda exc: isinstance(exc, RuntimeError) and "fastembed" in str(exc).lower(),
            title="Embedding Model Error",
            body_fn=lambda exc: f"{exc}\n→ Run:  pip install fastembed",
            exit_code=1,
        )
    )

    # ── 9. Generic RuntimeError (usually already human-friendly) ─────────────
    register_handler(
        TypeHandler(
            exc_types=RuntimeError,
            title="Error",
            body_fn=lambda exc: str(exc),
            exit_code=1,
        )
    )

    # ── 10. ValueError (e.g. service-level input validation) ─────────────────
    register_handler(
        TypeHandler(
            exc_types=ValueError,
            title="Invalid Input",
            body_fn=lambda exc: str(exc),
            exit_code=2,
        )
    )


_register_defaults()
