"""Shared tree-sitter base analyzer for non-Python languages."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.analyzers.base import BaseAnalyzer, detect_layer_generic, path_to_module_generic
from src.neo4j_graph import ComponentNode, GraphData

logger = logging.getLogger(__name__)


class TreeSitterAnalyzer(BaseAnalyzer):
    """Base class for tree-sitter-powered analyzers (JS, TS, Ruby, PHP)."""

    # Subclasses must set the tree-sitter grammar name
    ts_language: str = ""

    def _get_parser(self) -> Any:
        """Get a tree-sitter parser for the configured language."""
        from tree_sitter_language_pack import get_parser

        return get_parser(self.ts_language)

    def _get_language(self) -> Any:
        """Get the tree-sitter Language object for queries."""
        from tree_sitter_language_pack import get_language

        return get_language(self.ts_language)

    def _node_text(self, node: object) -> str:
        """Extract text content from a tree-sitter node."""
        text = getattr(node, "text", b"")
        if isinstance(text, bytes):
            return text.decode("utf-8", errors="replace")
        return str(text)

    def _add_module_node(
        self,
        filepath: Path,
        root: Path,
        graph: GraphData,
    ) -> tuple[str, str, str]:
        """Create a module-level node and return (module_name, layer, source_file)."""
        module_name = path_to_module_generic(filepath, root)
        layer = detect_layer_generic(filepath, root)
        source_file = str(filepath.relative_to(root))

        graph.nodes[module_name] = ComponentNode(
            name=module_name,
            kind="module",
            module=module_name,
            layer=layer,
            source_file=source_file,
            line_number=1,
            project=graph.project_name,
        )
        graph.belongs_to_layer_edges.add((module_name, layer))
        return module_name, layer, source_file

    def _add_component(
        self,
        *,
        name: str,
        kind: str,
        module_name: str,
        layer: str,
        source_file: str,
        line_number: int,
        graph: GraphData,
        signature: str = "",
        parent: str | None = None,
    ) -> None:
        """Add a component node and its structural edges."""
        graph.nodes[name] = ComponentNode(
            name=name,
            kind=kind,
            module=module_name,
            layer=layer,
            source_file=source_file,
            line_number=line_number,
            signature=signature,
            project=graph.project_name,
        )
        if parent:
            graph.defined_in_edges.add((name, parent))
        else:
            graph.defined_in_edges.add((name, module_name))
        graph.belongs_to_layer_edges.add((name, layer))

    def _extract_calls_from_tree(
        self,
        tree: object,
        module_name: str,
        graph: GraphData,
    ) -> None:
        """Walk tree-sitter AST to find call expressions and create CALLS edges."""
        known = set(graph.nodes.keys())
        root_node = getattr(tree, "root_node", None)
        if root_node is None:
            return

        self._walk_for_calls(root_node, module_name, known, graph)

    def _walk_for_calls(
        self,
        node: object,
        context_name: str,
        known: set[str],
        graph: GraphData,
    ) -> None:
        """Recursively walk tree-sitter nodes looking for call expressions."""
        node_type = getattr(node, "type", "")
        children = getattr(node, "children", [])

        if node_type == "call_expression":
            func_node = None
            for child in children:
                child_field = getattr(child, "type", "")
                if child_field == "identifier":
                    func_node = child
                    break
                if child_field in ("member_expression", "scoped_identifier"):
                    func_node = child
                    break

            if func_node is not None:
                func_text = self._node_text(func_node)
                # Try to match against known nodes
                for kn in known:
                    if kn.endswith(f".{func_text}") or kn == func_text:
                        if context_name != kn:
                            graph.calls_edges.add((context_name, kn))
                        break

        for child in children:
            self._walk_for_calls(child, context_name, known, graph)

    def extract_call_edges(self, files: list[Path], graph: GraphData) -> None:
        """Extract CALLS edges by re-parsing files and matching call expressions."""
        parser = self._get_parser()
        known = set(graph.nodes.keys())

        for filepath in files:
            try:
                source = filepath.read_bytes()
                tree = parser.parse(source)
            except OSError as e:
                logger.warning("Skipping %s for call extraction: %s", filepath, e)
                continue

            module_name = path_to_module_generic(filepath, filepath.parent)
            # Find the actual module name in graph
            for kn in known:
                if kn.endswith(path_to_module_generic(filepath, filepath.parent)):
                    module_name = kn
                    break

            root_node = getattr(tree, "root_node", None)
            if root_node:
                self._walk_for_calls(root_node, module_name, known, graph)
