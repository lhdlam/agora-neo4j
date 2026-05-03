"""Multi-language code analyzers for Neo4j graph building."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.analyzers.base import BaseAnalyzer

# Language name → file extensions
LANGUAGE_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "python": (".py",),
    "javascript": (".js", ".jsx", ".mjs"),
    "typescript": (".ts", ".tsx"),
    "ruby": (".rb",),
    "php": (".php",),
}


def detect_language(target_folder: str) -> str:
    """Auto-detect the dominant programming language in a folder based on file extensions."""
    root = Path(target_folder)
    counts: dict[str, int] = {}

    for lang, exts in LANGUAGE_EXTENSIONS.items():
        total = sum(len(list(root.rglob(f"*{ext}"))) for ext in exts)
        if total > 0:
            counts[lang] = total

    if not counts:
        return "python"  # fallback default

    return max(counts, key=lambda k: counts[k])


def get_analyzer(language: str) -> BaseAnalyzer:
    """Return the appropriate analyzer instance for the given language."""
    if language == "python":
        from src.analyzers.python_analyzer import PythonAnalyzer

        return PythonAnalyzer()
    if language in ("javascript", "typescript"):
        from src.analyzers.javascript_analyzer import JavaScriptAnalyzer

        return JavaScriptAnalyzer(language=language)
    if language == "ruby":
        from src.analyzers.ruby_analyzer import RubyAnalyzer

        return RubyAnalyzer()
    if language == "php":
        from src.analyzers.php_analyzer import PHPAnalyzer

        return PHPAnalyzer()

    # Fallback to Python analyzer
    from src.analyzers.python_analyzer import PythonAnalyzer

    return PythonAnalyzer()


__all__ = ["detect_language", "get_analyzer", "LANGUAGE_EXTENSIONS"]
