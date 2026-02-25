"""
Agora — AI-powered classified ads service.

Entry points
─────────────────────────────────────────
  python -m src              → auto-detect via MODE env var
  python -m src.cli          → CLI explicitly
  uvicorn src.http:app       → HTTP explicitly (future)
  python -m src -- --help    → show CLI help

Environment
─────────────────────────────────────────
  MODE=cli   (default)   → Click CLI
  MODE=http              → FastAPI / ASGI app
"""

import os
from pathlib import Path
import sys


def _detect_mode() -> str:
    """
    Determine which entry point to activate.

    Priority order:
      1. MODE env var (explicit, most reliable)
      2. sys.argv[0] heuristic  (uvicorn, gunicorn, etc.)
      3. Default: cli
    """
    env = os.environ.get("MODE", "").lower()
    if env in ("http", "web", "api"):  # pragma: no cover
        return "http"
    if env == "cli":
        return "cli"

    # Heuristic: detect common ASGI/WSGI runners
    runner = Path(sys.argv[0]).name if sys.argv else ""
    if runner in ("uvicorn", "gunicorn", "hypercorn", "daphne"):  # pragma: no cover
        return "http"

    return "cli"


def main() -> None:  # pragma: no cover
    """
    Unified entry point — dispatches to CLI or HTTP based on MODE.
    Called by __main__.py when running ``python -m src``.
    """
    mode = _detect_mode()

    if mode == "http":  # pragma: no cover
        # Import here (lazy) — avoids pulling FastAPI into CLI context
        try:
            import uvicorn  # type: ignore[import-not-found]

            from src.http import app  # type: ignore[attr-defined]

            host = os.environ.get("HOST", "0.0.0.0")
            port = int(os.environ.get("PORT", "8000"))
            uvicorn.run(app, host=host, port=port)
        except ImportError:
            sys.stderr.write(
                "HTTP mode requires uvicorn.\nInstall with:  pip install uvicorn fastapi\n"
            )
            sys.exit(1)
    else:
        from src.cli import cli

        cli()
