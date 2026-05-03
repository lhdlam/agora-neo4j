"""Ruby code analyzer using tree-sitter."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

from src.analyzers.treesitter_base import TreeSitterAnalyzer
from src.neo4j_graph import GraphData

logger = logging.getLogger(__name__)


class RubyAnalyzer(TreeSitterAnalyzer):
    """Analyzer for Ruby source files."""

    extensions: ClassVar[tuple[str, ...]] = (".rb",)
    language_name: ClassVar[str] = "ruby"
    ts_language: str = "ruby"

    def find_files(self, root: Path) -> list[Path]:
        """Find all Ruby files, excluding vendor and tmp directories."""
        files = list(root.rglob("*.rb"))
        files = [
            f
            for f in files
            if not any(
                part in ("vendor", "tmp", "node_modules", ".bundle", "coverage") for part in f.parts
            )
        ]
        return sorted(files)

    def parse_file(self, filepath: Path, root: Path, graph: GraphData) -> None:
        """Parse a Ruby file using tree-sitter."""
        parser = self._get_parser()

        try:
            source = filepath.read_bytes()
            tree = parser.parse(source)
        except OSError as e:
            logger.warning("Skipping %s due to read error: %s", filepath, e)
            return

        module_name, layer, source_file = self._add_module_node(filepath, root, graph)
        root_node = tree.root_node

        self._walk_ruby_node(root_node, module_name, layer, source_file, graph)

    def _walk_ruby_node(
        self,
        node: object,
        parent_name: str,
        layer: str,
        source_file: str,
        graph: GraphData,
    ) -> None:
        """Walk tree-sitter Ruby AST to extract modules, classes, methods, imports."""
        node_type = getattr(node, "type", "")
        children = getattr(node, "children", []) or []

        if node_type == "class":
            self._handle_class(node, parent_name, layer, source_file, graph)
        elif node_type == "module":
            self._handle_module(node, parent_name, layer, source_file, graph)
        elif node_type in ("method", "singleton_method"):
            self._handle_method(node, parent_name, layer, source_file, graph)
        elif node_type == "call":
            self._handle_require(node, parent_name, graph)
            # Continue walking for nested definitions
            for child in children:
                self._walk_ruby_node(child, parent_name, layer, source_file, graph)
        else:
            for child in children:
                self._walk_ruby_node(child, parent_name, layer, source_file, graph)

    def _handle_class(
        self,
        node: object,
        parent_name: str,
        layer: str,
        source_file: str,
        graph: GraphData,
    ) -> None:
        """Extract Ruby class, its methods, and inheritance."""
        children = getattr(node, "children", []) or []
        class_name = ""
        superclass = ""

        for child in children:
            child_type = getattr(child, "type", "")
            if child_type in ("constant", "scope_resolution") and not class_name:
                class_name = self._node_text(child)
            elif child_type == "superclass":
                sc_children = getattr(child, "children", []) or []
                for sc in sc_children:
                    if getattr(sc, "type", "") in ("constant", "scope_resolution"):
                        superclass = self._node_text(sc)

        if not class_name:
            return

        class_fqn = f"{parent_name}.{class_name}"
        line = getattr(node, "start_point", (0,))[0] + 1

        self._add_component(
            name=class_fqn,
            kind="class",
            module_name=parent_name,
            layer=layer,
            source_file=source_file,
            line_number=line,
            graph=graph,
        )

        if superclass:
            graph.inherits_edges.add((class_fqn, superclass))

        # Walk class body for methods
        for child in children:
            if getattr(child, "type", "") == "body_statement":
                body_children = getattr(child, "children", []) or []
                for member in body_children:
                    self._walk_ruby_node(member, class_fqn, layer, source_file, graph)

    def _handle_module(
        self,
        node: object,
        parent_name: str,
        layer: str,
        source_file: str,
        graph: GraphData,
    ) -> None:
        """Extract Ruby module definition."""
        children = getattr(node, "children", []) or []
        mod_name = ""

        for child in children:
            if getattr(child, "type", "") in ("constant", "scope_resolution") and not mod_name:
                mod_name = self._node_text(child)

        if not mod_name:
            return

        mod_fqn = f"{parent_name}.{mod_name}"
        line = getattr(node, "start_point", (0,))[0] + 1

        self._add_component(
            name=mod_fqn,
            kind="module",
            module_name=parent_name,
            layer=layer,
            source_file=source_file,
            line_number=line,
            graph=graph,
        )

        # Walk module body
        for child in children:
            if getattr(child, "type", "") == "body_statement":
                body_children = getattr(child, "children", []) or []
                for member in body_children:
                    self._walk_ruby_node(member, mod_fqn, layer, source_file, graph)

    def _handle_method(
        self,
        node: object,
        parent_name: str,
        layer: str,
        source_file: str,
        graph: GraphData,
    ) -> None:
        """Extract Ruby method definition."""
        children = getattr(node, "children", []) or []
        method_name = ""

        for child in children:
            if getattr(child, "type", "") == "identifier":
                method_name = self._node_text(child)
                break

        if not method_name:
            return

        method_fqn = f"{parent_name}.{method_name}"
        line = getattr(node, "start_point", (0,))[0] + 1

        # Extract parameters
        sig = ""
        for child in children:
            if getattr(child, "type", "") == "method_parameters":
                sig = self._node_text(child)
                break

        self._add_component(
            name=method_fqn,
            kind="method",
            module_name=parent_name.rsplit(".", 1)[0] if "." in parent_name else parent_name,
            layer=layer,
            source_file=source_file,
            line_number=line,
            graph=graph,
            signature=sig,
            parent=parent_name,
        )

    def _handle_require(
        self,
        node: object,
        module_name: str,
        graph: GraphData,
    ) -> None:
        """Extract require/require_relative statements as import edges."""
        children = getattr(node, "children", []) or []
        func_name = ""
        arg_value = ""

        for child in children:
            child_type = getattr(child, "type", "")
            if child_type == "identifier":
                func_name = self._node_text(child)
            elif child_type == "argument_list":
                arg_children = getattr(child, "children", []) or []
                for ac in arg_children:
                    if getattr(ac, "type", "") == "string":
                        arg_value = self._node_text(ac).strip("'\"")

        if func_name in ("require", "require_relative") and arg_value:
            graph.imports_edges.add((module_name, arg_value))
