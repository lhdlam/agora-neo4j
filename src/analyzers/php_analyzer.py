"""PHP code analyzer using tree-sitter."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

from src.analyzers.treesitter_base import TreeSitterAnalyzer
from src.neo4j_graph import GraphData

logger = logging.getLogger(__name__)


class PHPAnalyzer(TreeSitterAnalyzer):
    """Analyzer for PHP source files."""

    extensions: ClassVar[tuple[str, ...]] = (".php",)
    language_name: ClassVar[str] = "php"
    ts_language: str = "php"

    def find_files(self, root: Path) -> list[Path]:
        """Find all PHP files, excluding vendor and cache directories."""
        files = list(root.rglob("*.php"))
        files = [
            f
            for f in files
            if not any(
                part in ("vendor", "node_modules", "cache", "storage", "public") for part in f.parts
            )
        ]
        return sorted(files)

    def parse_file(self, filepath: Path, root: Path, graph: GraphData) -> None:
        """Parse a PHP file using tree-sitter."""
        parser = self._get_parser()

        try:
            source = filepath.read_bytes()
            tree = parser.parse(source)
        except OSError as e:
            logger.warning("Skipping %s due to read error: %s", filepath, e)
            return

        module_name, layer, source_file = self._add_module_node(filepath, root, graph)
        root_node = tree.root_node

        # PHP wraps everything in a program node
        self._walk_php_node(root_node, module_name, layer, source_file, graph)

    def _walk_php_node(
        self,
        node: object,
        parent_name: str,
        layer: str,
        source_file: str,
        graph: GraphData,
    ) -> None:
        """Walk tree-sitter PHP AST to extract classes, functions, imports."""
        node_type = getattr(node, "type", "")
        children = getattr(node, "children", []) or []

        if node_type == "class_declaration":
            self._handle_class(node, parent_name, layer, source_file, graph)
        elif node_type == "interface_declaration":
            self._handle_interface(node, parent_name, layer, source_file, graph)
        elif node_type == "trait_declaration":
            self._handle_trait(node, parent_name, layer, source_file, graph)
        elif node_type == "function_definition":
            self._handle_function(node, parent_name, layer, source_file, graph)
        elif node_type == "namespace_use_declaration":
            self._handle_use(node, parent_name, graph)
        elif node_type == "namespace_definition":
            self._handle_namespace(node, parent_name, layer, source_file, graph)
        else:
            for child in children:
                self._walk_php_node(child, parent_name, layer, source_file, graph)

    def _handle_class(
        self,
        node: object,
        parent_name: str,
        layer: str,
        source_file: str,
        graph: GraphData,
    ) -> None:
        """Extract PHP class declaration, methods, and inheritance."""
        children = getattr(node, "children", []) or []
        class_name = ""
        superclass = ""

        for child in children:
            child_type = getattr(child, "type", "")
            if child_type == "name":
                class_name = self._node_text(child)
            elif child_type == "base_clause":
                bc_children = getattr(child, "children", []) or []
                for bc in bc_children:
                    if getattr(bc, "type", "") in ("name", "qualified_name"):
                        superclass = self._node_text(bc)

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

        # Extract methods from declaration_list (class body)
        for child in children:
            if getattr(child, "type", "") == "declaration_list":
                body_children = getattr(child, "children", []) or []
                for member in body_children:
                    member_type = getattr(member, "type", "")
                    if member_type == "method_declaration":
                        self._handle_method(member, class_fqn, layer, source_file, graph)

    def _handle_interface(
        self,
        node: object,
        parent_name: str,
        layer: str,
        source_file: str,
        graph: GraphData,
    ) -> None:
        """Extract PHP interface declaration."""
        children = getattr(node, "children", []) or []
        iface_name = ""

        for child in children:
            if getattr(child, "type", "") == "name":
                iface_name = self._node_text(child)
                break

        if not iface_name:
            return

        iface_fqn = f"{parent_name}.{iface_name}"
        line = getattr(node, "start_point", (0,))[0] + 1

        self._add_component(
            name=iface_fqn,
            kind="interface",
            module_name=parent_name,
            layer=layer,
            source_file=source_file,
            line_number=line,
            graph=graph,
        )

        # Extract method signatures from interface body
        for child in children:
            if getattr(child, "type", "") == "declaration_list":
                body_children = getattr(child, "children", []) or []
                for member in body_children:
                    if getattr(member, "type", "") == "method_declaration":
                        self._handle_method(member, iface_fqn, layer, source_file, graph)

    def _handle_trait(
        self,
        node: object,
        parent_name: str,
        layer: str,
        source_file: str,
        graph: GraphData,
    ) -> None:
        """Extract PHP trait declaration."""
        children = getattr(node, "children", []) or []
        trait_name = ""

        for child in children:
            if getattr(child, "type", "") == "name":
                trait_name = self._node_text(child)
                break

        if not trait_name:
            return

        trait_fqn = f"{parent_name}.{trait_name}"
        line = getattr(node, "start_point", (0,))[0] + 1

        self._add_component(
            name=trait_fqn,
            kind="class",  # Treat traits as classes in the graph
            module_name=parent_name,
            layer=layer,
            source_file=source_file,
            line_number=line,
            graph=graph,
        )

        # Extract methods
        for child in children:
            if getattr(child, "type", "") == "declaration_list":
                body_children = getattr(child, "children", []) or []
                for member in body_children:
                    if getattr(member, "type", "") == "method_declaration":
                        self._handle_method(member, trait_fqn, layer, source_file, graph)

    def _handle_method(
        self,
        node: object,
        class_fqn: str,
        layer: str,
        source_file: str,
        graph: GraphData,
    ) -> None:
        """Extract PHP method from class/interface/trait body."""
        children = getattr(node, "children", []) or []
        method_name = ""

        for child in children:
            if getattr(child, "type", "") == "name":
                method_name = self._node_text(child)
                break

        if not method_name:
            return

        method_fqn = f"{class_fqn}.{method_name}"
        line = getattr(node, "start_point", (0,))[0] + 1

        # Extract parameter list
        sig = ""
        for child in children:
            if getattr(child, "type", "") == "formal_parameters":
                sig = self._node_text(child)
                break

        self._add_component(
            name=method_fqn,
            kind="method",
            module_name=class_fqn.rsplit(".", 1)[0] if "." in class_fqn else class_fqn,
            layer=layer,
            source_file=source_file,
            line_number=line,
            graph=graph,
            signature=sig,
            parent=class_fqn,
        )

    def _handle_function(
        self,
        node: object,
        parent_name: str,
        layer: str,
        source_file: str,
        graph: GraphData,
    ) -> None:
        """Extract PHP top-level function definition."""
        children = getattr(node, "children", []) or []
        func_name = ""

        for child in children:
            if getattr(child, "type", "") == "name":
                func_name = self._node_text(child)
                break

        if not func_name:
            return

        func_fqn = f"{parent_name}.{func_name}"
        line = getattr(node, "start_point", (0,))[0] + 1

        sig = ""
        for child in children:
            if getattr(child, "type", "") == "formal_parameters":
                sig = self._node_text(child)
                break

        self._add_component(
            name=func_fqn,
            kind="function",
            module_name=parent_name,
            layer=layer,
            source_file=source_file,
            line_number=line,
            graph=graph,
            signature=sig,
        )

    def _handle_use(
        self,
        node: object,
        module_name: str,
        graph: GraphData,
    ) -> None:
        """Extract PHP use declarations as import edges."""
        children = getattr(node, "children", []) or []

        for child in children:
            child_type = getattr(child, "type", "")
            if child_type in ("qualified_name", "name"):
                import_name = self._node_text(child)
                graph.imports_edges.add((module_name, import_name))
            elif child_type == "namespace_use_clause":
                uc_children = getattr(child, "children", []) or []
                for uc in uc_children:
                    if getattr(uc, "type", "") in ("qualified_name", "name"):
                        import_name = self._node_text(uc)
                        graph.imports_edges.add((module_name, import_name))

    def _handle_namespace(
        self,
        node: object,
        parent_name: str,
        layer: str,
        source_file: str,
        graph: GraphData,
    ) -> None:
        """Handle PHP namespace definitions — walk into the namespace body."""
        children = getattr(node, "children", []) or []
        ns_name = ""

        for child in children:
            child_type = getattr(child, "type", "")
            if child_type in ("qualified_name", "name"):
                ns_name = self._node_text(child)
            elif child_type == "compound_statement":
                # Walk namespace body with the namespace as parent context
                effective_name = f"{parent_name}.{ns_name}" if ns_name else parent_name
                body_children = getattr(child, "children", []) or []
                for member in body_children:
                    self._walk_php_node(member, effective_name, layer, source_file, graph)
