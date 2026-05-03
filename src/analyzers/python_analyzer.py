"""Python-specific code analyzer using ast + pyan3."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import ClassVar

from src.analyzers.base import BaseAnalyzer
from src.neo4j_graph import ComponentNode, GraphData

logger = logging.getLogger(__name__)

# Architecture layer inference: module prefix -> layer name (Agora-specific)
PYTHON_LAYER_MAP: dict[str, str] = {
    "src.commands": "commands",
    "src.services": "services",
    "src.infrastructure": "infrastructure",
    "src.domain": "domain",
    "src.ports": "ports",
    "src.config": "config",
    "src.cli": "cli",
    "src.tests": "tests",
}

# Class name suffixes that signal a Port/Protocol interface
_PORT_SUFFIXES: tuple[str, ...] = ("Port", "Protocol")

# Synthetic pyan artifacts to filter out
_SYNTHETIC_SUFFIXES: tuple[str, ...] = (".listcomp.", ".lambda.", ".genexpr.")


def _detect_layer(module_name: str) -> str:
    """Infer the architecture layer from the module's dotted path."""
    for prefix, layer in PYTHON_LAYER_MAP.items():
        if module_name == prefix or module_name.startswith(prefix + "."):
            return layer
    return "unknown"


def _path_to_module(filepath: Path, root: Path) -> str:
    """Convert a file path to a dotted Python module name relative to root's parent."""
    relative = filepath.relative_to(root.parent)
    return ".".join(relative.with_suffix("").parts)


def _first_paragraph(text: str) -> str:
    """Extract the first non-empty paragraph from a docstring."""
    if not text:
        return ""
    lines: list[str] = []
    for line in text.strip().splitlines():
        stripped = line.strip()
        if not stripped and lines:
            break
        if stripped:
            lines.append(stripped)
    return " ".join(lines)


def _extract_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Build a concise human-readable signature string from an AST function node."""
    args = node.args
    params: list[str] = []

    defaults_offset = len(args.args) - len(args.defaults)
    for i, arg in enumerate(args.args):
        param = arg.arg
        if arg.annotation:
            param += f": {ast.unparse(arg.annotation)}"
        if i >= defaults_offset:
            param += f" = {ast.unparse(args.defaults[i - defaults_offset])}"
        params.append(param)

    if args.vararg:
        vp = f"*{args.vararg.arg}"
        if args.vararg.annotation:
            vp += f": {ast.unparse(args.vararg.annotation)}"
        params.append(vp)

    for i, kwo in enumerate(args.kwonlyargs):
        param = kwo.arg
        if kwo.annotation:
            param += f": {ast.unparse(kwo.annotation)}"
        kw_default = args.kw_defaults[i] if i < len(args.kw_defaults) else None
        if kw_default is not None:
            param += f" = {ast.unparse(kw_default)}"
        params.append(param)

    if args.kwarg:
        vk = f"**{args.kwarg.arg}"
        if args.kwarg.annotation:
            vk += f": {ast.unparse(args.kwarg.annotation)}"
        params.append(vk)

    sig = f"({', '.join(params)})"
    if node.returns:
        sig += f" -> {ast.unparse(node.returns)}"
    return sig


def _is_project_module(name: str) -> bool:
    """Return True if the module name belongs to this project."""
    return name.startswith("src.")


def _is_valid_pyan_node(name: str) -> bool:
    """Filter out pyan synthetic nodes and external library references."""
    if name.startswith(("*.", "---:")):
        return False
    return not any(s in name for s in _SYNTHETIC_SUFFIXES)


def _process_class(
    class_node: ast.ClassDef,
    *,
    module_name: str,
    layer: str,
    source_file: str,
    graph: GraphData,
) -> None:
    """Extract class metadata, methods, inheritance edges, and port implementation edges."""
    class_fqn = f"{module_name}.{class_node.name}"
    graph.nodes[class_fqn] = ComponentNode(
        name=class_fqn,
        kind="class",
        module=module_name,
        layer=layer,
        source_file=source_file,
        line_number=class_node.lineno,
        docstring=_first_paragraph(ast.get_docstring(class_node) or ""),
        project=graph.project_name,
    )
    graph.defined_in_edges.add((class_fqn, module_name))
    graph.belongs_to_layer_edges.add((class_fqn, layer))

    for base in class_node.bases:
        base_name = ast.unparse(base)
        graph.inherits_edges.add((class_fqn, base_name))
        if any(base_name.endswith(suffix) for suffix in _PORT_SUFFIXES):
            graph.implements_edges.add((class_fqn, base_name))

    for item in class_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            method_fqn = f"{class_fqn}.{item.name}"
            graph.nodes[method_fqn] = ComponentNode(
                name=method_fqn,
                kind="method",
                module=module_name,
                layer=layer,
                source_file=source_file,
                line_number=item.lineno,
                docstring=_first_paragraph(ast.get_docstring(item) or ""),
                signature=_extract_signature(item),
                project=graph.project_name,
            )
            graph.defined_in_edges.add((method_fqn, class_fqn))
            graph.belongs_to_layer_edges.add((method_fqn, layer))


class PythonAnalyzer(BaseAnalyzer):
    """Python code analyzer using ast module + pyan3 for call graphs."""

    extensions: ClassVar[tuple[str, ...]] = (".py",)
    language_name: ClassVar[str] = "python"

    def find_files(self, root: Path) -> list[Path]:
        """Find all Python files, excluding __init__.py."""
        return sorted(p for p in root.rglob("*.py") if p.name != "__init__.py")

    def parse_file(self, filepath: Path, root: Path, graph: GraphData) -> None:
        """Parse one Python file and accumulate enriched nodes and edges into graph."""
        module_name = _path_to_module(filepath, root)
        layer = _detect_layer(module_name)
        source_file = str(filepath.relative_to(root.parent))

        try:
            tree = ast.parse(filepath.read_text(encoding="utf-8"), filename=str(filepath))
        except (SyntaxError, OSError) as e:
            logger.warning("Skipping %s due to parse error: %s", filepath, e)
            return

        graph.nodes[module_name] = ComponentNode(
            name=module_name,
            kind="module",
            module=module_name,
            layer=layer,
            source_file=source_file,
            line_number=1,
            docstring=_first_paragraph(ast.get_docstring(tree) or ""),
            project=graph.project_name,
        )
        graph.belongs_to_layer_edges.add((module_name, layer))

        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                if node.module and _is_project_module(node.module):
                    graph.imports_edges.add((module_name, node.module))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_project_module(alias.name):
                        graph.imports_edges.add((module_name, alias.name))
            elif isinstance(node, ast.ClassDef):
                _process_class(
                    node,
                    module_name=module_name,
                    layer=layer,
                    source_file=source_file,
                    graph=graph,
                )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_fqn = f"{module_name}.{node.name}"
                graph.nodes[func_fqn] = ComponentNode(
                    name=func_fqn,
                    kind="function",
                    module=module_name,
                    layer=layer,
                    source_file=source_file,
                    line_number=node.lineno,
                    docstring=_first_paragraph(ast.get_docstring(node) or ""),
                    signature=_extract_signature(node),
                    project=graph.project_name,
                )
                graph.defined_in_edges.add((func_fqn, module_name))
                graph.belongs_to_layer_edges.add((func_fqn, layer))

    def extract_call_edges(self, files: list[Path], graph: GraphData) -> None:
        """Use pyan3 to extract CALLS relationships from the project call graph."""
        try:
            from pyan.analyzer import CallGraphVisitor
        except ImportError:
            logger.warning("pyan3 not installed — skipping call graph extraction for Python.")
            return

        try:
            visitor = CallGraphVisitor([str(f) for f in files])
        except (SyntaxError, TypeError, ValueError):
            logger.exception("Failed to analyze call graph with pyan3")
            return

        known = set(graph.nodes.keys())
        for caller_node, callees in visitor.uses_edges.items():
            caller_name = caller_node.get_name()
            if not _is_valid_pyan_node(caller_name) or caller_name not in known:
                continue
            for callee_node in callees:
                callee_name = callee_node.get_name()
                if not _is_valid_pyan_node(callee_name) or callee_name not in known:
                    continue
                if caller_name != callee_name:
                    graph.calls_edges.add((caller_name, callee_name))
