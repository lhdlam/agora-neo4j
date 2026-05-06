"""JavaScript and TypeScript code analyzer using tree-sitter."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

from src.analyzers.treesitter_base import TreeSitterAnalyzer
from src.neo4j_graph import GraphData

logger = logging.getLogger(__name__)


class JavaScriptAnalyzer(TreeSitterAnalyzer):
    """Analyzer for JavaScript and TypeScript files."""

    extensions: ClassVar[tuple[str, ...]] = (".js", ".jsx", ".ts", ".tsx", ".mjs")
    language_name: ClassVar[str] = "javascript"

    def __init__(self, *, language: str = "javascript") -> None:
        # Use "typescript" grammar for .ts/.tsx files for better accuracy
        self._language = language
        if language == "typescript":
            self.ts_language = "typescript"
            self.language_name = "typescript"  # type: ignore[misc]
        else:
            self.ts_language = "javascript"

    def find_files(self, root: Path) -> list[Path]:
        """Find JS/TS files based on the configured language."""
        exts = (".ts", ".tsx") if self._language == "typescript" else (".js", ".jsx", ".mjs")

        files: list[Path] = []
        for ext in exts:
            files.extend(root.rglob(f"*{ext}"))

        # Filter out node_modules, dist, build directories
        files = [
            f
            for f in files
            if not any(
                part in ("node_modules", "dist", "build", ".next", "coverage") for part in f.parts
            )
        ]
        return sorted(files)

    def parse_file(self, filepath: Path, root: Path, graph: GraphData) -> None:
        """Parse a JavaScript/TypeScript file using tree-sitter."""
        # Determine which grammar to use based on file extension
        ts_lang = "typescript" if filepath.suffix in (".ts", ".tsx") else "javascript"

        from typing import Any, cast

        from tree_sitter_language_pack import get_parser

        parser = get_parser(cast(Any, ts_lang))

        try:
            source = filepath.read_bytes()
            tree = parser.parse(source)
        except OSError as e:
            logger.warning("Skipping %s due to read error: %s", filepath, e)
            return

        module_name, layer, source_file = self._add_module_node(filepath, root, graph)
        root_node = tree.root_node

        self._walk_js_node(root_node, module_name, layer, source_file, graph)

    def _walk_js_node(
        self,
        node: object,
        parent_name: str,
        layer: str,
        source_file: str,
        graph: GraphData,
    ) -> None:
        """Walk tree-sitter JS/TS AST to extract classes, functions, imports."""
        node_type = getattr(node, "type", "")
        children = getattr(node, "children", []) or []

        if node_type == "class_declaration":
            self._handle_class(node, parent_name, layer, source_file, graph)
        elif node_type in ("function_declaration", "generator_function_declaration"):
            self._handle_function(node, parent_name, layer, source_file, graph)
        elif node_type == "export_statement":
            # Walk into export statement body
            for child in children:
                self._walk_js_node(child, parent_name, layer, source_file, graph)
        elif node_type in ("import_statement", "import_declaration"):
            self._handle_import(node, parent_name, graph)
        elif node_type == "lexical_declaration":
            self._handle_lexical_declaration(node, parent_name, layer, source_file, graph)
        else:
            for child in children:
                self._walk_js_node(child, parent_name, layer, source_file, graph)

    def _handle_class(
        self,
        node: object,
        parent_name: str,
        layer: str,
        source_file: str,
        graph: GraphData,
    ) -> None:
        """Extract class declaration, its methods, and inheritance."""
        children = getattr(node, "children", []) or []
        class_name = ""
        superclass = ""

        for child in children:
            child_type = getattr(child, "type", "")
            if child_type == "identifier":
                class_name = self._node_text(child)
            elif child_type == "class_heritage":
                heritage_children = getattr(child, "children", []) or []
                for hc in heritage_children:
                    if getattr(hc, "type", "") == "identifier":
                        superclass = self._node_text(hc)

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

        # Extract methods from class body
        for child in children:
            if getattr(child, "type", "") == "class_body":
                body_children = getattr(child, "children", []) or []
                for member in body_children:
                    member_type = getattr(member, "type", "")
                    if member_type == "method_definition":
                        self._handle_method(member, class_fqn, layer, source_file, graph)

    def _handle_method(
        self,
        node: object,
        class_fqn: str,
        layer: str,
        source_file: str,
        graph: GraphData,
    ) -> None:
        """Extract method from class body."""
        children = getattr(node, "children", []) or []
        method_name = ""

        for child in children:
            child_type = getattr(child, "type", "")
            if child_type == "property_identifier":
                method_name = self._node_text(child)
                break
            if child_type == "identifier":
                method_name = self._node_text(child)
                break

        if not method_name:
            return

        method_fqn = f"{class_fqn}.{method_name}"
        line = getattr(node, "start_point", (0,))[0] + 1

        # Build signature from formal_parameters
        sig = self._extract_params_signature(node)

        self._add_component(
            name=method_fqn,
            kind="method",
            module_name=class_fqn.rsplit(".", 1)[0],
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
        """Extract function declaration."""
        children = getattr(node, "children", []) or []
        func_name = ""

        for child in children:
            if getattr(child, "type", "") == "identifier":
                func_name = self._node_text(child)
                break

        if not func_name:
            return

        func_fqn = f"{parent_name}.{func_name}"
        line = getattr(node, "start_point", (0,))[0] + 1
        sig = self._extract_params_signature(node)

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

    def _handle_lexical_declaration(
        self,
        node: object,
        parent_name: str,
        layer: str,
        source_file: str,
        graph: GraphData,
    ) -> None:
        """Handle const/let declarations that may contain arrow functions."""
        children = getattr(node, "children", []) or []

        for child in children:
            if getattr(child, "type", "") == "variable_declarator":
                decl_children = getattr(child, "children", []) or []
                var_name = ""
                is_arrow_func = False

                for dc in decl_children:
                    dc_type = getattr(dc, "type", "")
                    if dc_type == "identifier":
                        var_name = self._node_text(dc)
                    elif dc_type == "arrow_function":
                        is_arrow_func = True

                if var_name and is_arrow_func:
                    func_fqn = f"{parent_name}.{var_name}"
                    line = getattr(child, "start_point", (0,))[0] + 1

                    self._add_component(
                        name=func_fqn,
                        kind="function",
                        module_name=parent_name,
                        layer=layer,
                        source_file=source_file,
                        line_number=line,
                        graph=graph,
                    )

    def _handle_import(
        self,
        node: object,
        module_name: str,
        graph: GraphData,
    ) -> None:
        """Extract import source and create import edge."""
        children = getattr(node, "children", []) or []

        for child in children:
            child_type = getattr(child, "type", "")
            if child_type == "string":
                import_source = self._node_text(child).strip("'\"")
                # Only track relative imports (project-internal)
                if import_source.startswith("."):
                    graph.imports_edges.add((module_name, import_source))

    def _extract_params_signature(self, node: object) -> str:
        """Extract parameter list as a signature string."""
        children = getattr(node, "children", []) or []

        for child in children:
            if getattr(child, "type", "") == "formal_parameters":
                return self._node_text(child)
        return "()"
