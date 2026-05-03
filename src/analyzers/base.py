"""Base analyzer interface and shared data structures."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from src.neo4j_graph import GraphData

# Generic layer map for non-Python projects based on common folder names
GENERIC_LAYER_MAP: dict[str, str] = {
    "controllers": "controllers",
    "models": "models",
    "views": "views",
    "services": "services",
    "lib": "library",
    "utils": "utilities",
    "helpers": "helpers",
    "middleware": "middleware",
    "config": "config",
    "tests": "tests",
    "test": "tests",
    "spec": "tests",
    "components": "components",
    "pages": "pages",
    "routes": "routes",
    "api": "api",
    "app": "application",
    "src": "source",
    "public": "public",
    "assets": "assets",
}

GENERIC_LAYER_DESCRIPTIONS: dict[str, str] = {
    "controllers": "Request handling and response rendering",
    "models": "Data models and business entities",
    "views": "View templates and UI rendering",
    "services": "Business logic and orchestration",
    "library": "Shared library code",
    "utilities": "Utility functions and helpers",
    "helpers": "Helper functions and mixins",
    "middleware": "Request/response middleware",
    "config": "Application configuration",
    "tests": "Test suites and specs",
    "components": "Reusable UI components",
    "pages": "Page-level components or views",
    "routes": "Routing definitions",
    "api": "API endpoint definitions",
    "application": "Application-level code",
    "source": "Main source code",
    "public": "Public-facing assets",
    "assets": "Static assets",
    "unknown": "Uncategorized components",
}


def detect_layer_generic(filepath: Path, root: Path) -> str:
    """Infer the architecture layer from the file path using generic folder naming."""
    try:
        relative = filepath.relative_to(root)
    except ValueError:
        return "unknown"

    parts = relative.parts
    for part in parts:
        lower = part.lower()
        if lower in GENERIC_LAYER_MAP:
            return GENERIC_LAYER_MAP[lower]
    return "unknown"


def path_to_module_generic(filepath: Path, root: Path) -> str:
    """Convert a file path to a dotted module name relative to the root folder."""
    try:
        relative = filepath.relative_to(root)
    except ValueError:
        return filepath.stem

    return ".".join(relative.with_suffix("").parts)


class BaseAnalyzer(ABC):
    """Abstract base class for language-specific code analyzers."""

    # Subclasses must define these
    extensions: ClassVar[tuple[str, ...]]
    language_name: ClassVar[str]

    def find_files(self, root: Path) -> list[Path]:
        """Find all source files matching this analyzer's extensions."""
        files: list[Path] = []
        for ext in self.extensions:
            files.extend(root.rglob(f"*{ext}"))
        return sorted(files)

    @abstractmethod
    def parse_file(self, filepath: Path, root: Path, graph: GraphData) -> None:
        """Parse a single source file and populate graph nodes/edges."""

    @abstractmethod
    def extract_call_edges(self, files: list[Path], graph: GraphData) -> None:
        """Extract CALLS relationships from the analyzed files."""
