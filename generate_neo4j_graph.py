from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

from neo4j import GraphDatabase
from pyan.analyzer import CallGraphVisitor

# ==========================================
# CONFIGURATION
# ==========================================
TARGET_FOLDER = "src"
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password"
OUTPUT_CYPHER_FILE = "import_neo4j.cypher"

logger = logging.getLogger(__name__)

# Architecture layer inference: module prefix -> layer name
LAYER_MAP: dict[str, str] = {
    "src.commands": "commands",
    "src.services": "services",
    "src.infrastructure": "infrastructure",
    "src.domain": "domain",
    "src.ports": "ports",
    "src.config": "config",
    "src.cli": "cli",
    "src.tests": "tests",
}

# Human-readable description for each architecture layer
LAYER_DESCRIPTIONS: dict[str, str] = {
    "commands": "CLI input parsing, Click arg validation, Rich output rendering",
    "services": "Business logic, framework-agnostic, orchestrates ports",
    "infrastructure": "Elasticsearch, embedder, Kafka adapters — satisfies port protocols",
    "domain": "Pydantic models, enums — pure data, zero I/O",
    "ports": "Protocol interfaces for dependency inversion",
    "config": "Application settings via pydantic-settings",
    "cli": "Click group entry point and debug flag",
    "tests": "Unit and integration tests using fake adapters",
    "unknown": "Uncategorized components",
}

# Class name suffixes that signal a Port/Protocol interface
_PORT_SUFFIXES: tuple[str, ...] = ("Port", "Protocol")

# Synthetic pyan artifacts to filter out
_SYNTHETIC_SUFFIXES: tuple[str, ...] = (".listcomp.", ".lambda.", ".genexpr.")


# ==========================================
# DATA CLASSES
# ==========================================


@dataclass
class ComponentNode:
    """Represents a single analyzed code component stored in Neo4j."""

    name: str  # Fully qualified name: "src.services.listing_service.ListingService"
    kind: str  # "module" | "class" | "function" | "method"
    module: str  # Parent module: "src.services.listing_service"
    layer: str  # Architecture layer: "services" | "infrastructure" | etc.
    source_file: str  # Relative path: "src/services/listing_service.py"
    line_number: int  # Line where this component is defined
    docstring: str = ""  # First paragraph of the docstring
    signature: str = ""  # Human-readable function/method signature


@dataclass
class GraphData:
    """Container for all extracted graph nodes and edges."""

    nodes: dict[str, ComponentNode] = field(default_factory=dict)
    calls_edges: set[tuple[str, str]] = field(default_factory=set)
    imports_edges: set[tuple[str, str]] = field(default_factory=set)
    inherits_edges: set[tuple[str, str]] = field(default_factory=set)
    implements_edges: set[tuple[str, str]] = field(default_factory=set)
    defined_in_edges: set[tuple[str, str]] = field(default_factory=set)
    belongs_to_layer_edges: set[tuple[str, str]] = field(default_factory=set)


# ==========================================
# HELPER FUNCTIONS
# ==========================================


def _escape_cypher(value: str) -> str:
    """Escape backslashes and single quotes to prevent Cypher injection."""
    return value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ").replace("\r", "")


def _detect_layer(module_name: str) -> str:
    """Infer the architecture layer from the module's dotted path."""
    for prefix, layer in LAYER_MAP.items():
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

    # Positional args with optional default values
    defaults_offset = len(args.args) - len(args.defaults)
    for i, arg in enumerate(args.args):
        param = arg.arg
        if arg.annotation:
            param += f": {ast.unparse(arg.annotation)}"
        if i >= defaults_offset:
            param += f" = {ast.unparse(args.defaults[i - defaults_offset])}"
        params.append(param)

    # Variadic positional (*args)
    if args.vararg:
        vp = f"*{args.vararg.arg}"
        if args.vararg.annotation:
            vp += f": {ast.unparse(args.vararg.annotation)}"
        params.append(vp)

    # Keyword-only arguments
    for i, kwo in enumerate(args.kwonlyargs):
        param = kwo.arg
        if kwo.annotation:
            param += f": {ast.unparse(kwo.annotation)}"
        kw_default = args.kw_defaults[i] if i < len(args.kw_defaults) else None
        if kw_default is not None:
            param += f" = {ast.unparse(kw_default)}"
        params.append(param)

    # Variadic keyword (**kwargs)
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
    """Return True if the module name belongs to this project (not stdlib/third-party)."""
    return name.startswith("src.")


def _is_valid_pyan_node(name: str) -> bool:
    """Filter out pyan synthetic nodes and external library references."""
    if name.startswith("*.") or name.startswith("---:"):
        return False
    return not any(s in name for s in _SYNTHETIC_SUFFIXES)


# ==========================================
# AST ANALYSIS
# ==========================================


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
    )
    graph.defined_in_edges.add((class_fqn, module_name))
    graph.belongs_to_layer_edges.add((class_fqn, layer))

    # Inheritance and port implementation detection
    for base in class_node.bases:
        base_name = ast.unparse(base)
        graph.inherits_edges.add((class_fqn, base_name))
        if any(base_name.endswith(suffix) for suffix in _PORT_SUFFIXES):
            graph.implements_edges.add((class_fqn, base_name))

    # Methods defined directly in this class body
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
            )
            graph.defined_in_edges.add((method_fqn, class_fqn))
            graph.belongs_to_layer_edges.add((method_fqn, layer))


def _parse_file_ast(filepath: Path, root: Path, graph: GraphData) -> None:
    """Parse one Python file and accumulate enriched nodes and edges into graph."""
    module_name = _path_to_module(filepath, root)
    layer = _detect_layer(module_name)
    source_file = str(filepath.relative_to(root.parent))

    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8"), filename=str(filepath))
    except (SyntaxError, OSError) as e:
        logger.warning("Skipping %s due to parse error: %s", filepath, e)
        return

    # Module-level node
    graph.nodes[module_name] = ComponentNode(
        name=module_name,
        kind="module",
        module=module_name,
        layer=layer,
        source_file=source_file,
        line_number=1,
        docstring=_first_paragraph(ast.get_docstring(tree) or ""),
    )
    graph.belongs_to_layer_edges.add((module_name, layer))

    # Walk only the top-level body to avoid double-counting nested definitions
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            # Record project-internal import edges only
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
            )
            graph.defined_in_edges.add((func_fqn, module_name))
            graph.belongs_to_layer_edges.add((func_fqn, layer))


def _resolve_inheritance(graph: GraphData) -> None:
    """
    Post-process raw base class names (e.g. 'ListingStorePort') into fully-qualified
    node names. Edges pointing to unknown external classes are dropped.
    """
    # Build short-name -> fqn lookup for classes and modules only
    short_to_fqn: dict[str, str] = {}
    for fqn, node in graph.nodes.items():
        if node.kind in ("class", "module"):
            short_to_fqn[fqn.rsplit(".", 1)[-1]] = fqn

    known = set(graph.nodes.keys())

    def resolve(edges: set[tuple[str, str]]) -> set[tuple[str, str]]:
        resolved: set[tuple[str, str]] = set()
        for child, base in edges:
            if base in known:
                resolved.add((child, base))
            elif base in short_to_fqn:
                resolved.add((child, short_to_fqn[base]))
            # else: external class — skip silently
        return resolved

    graph.inherits_edges = resolve(graph.inherits_edges)
    graph.implements_edges = resolve(graph.implements_edges)


# ==========================================
# PYAN CALL GRAPH EXTRACTION
# ==========================================


def _extract_call_edges(py_files: list[str], graph: GraphData) -> None:
    """Use pyan3 to extract CALLS relationships from the project call graph."""
    try:
        visitor = CallGraphVisitor(py_files)
    except (SyntaxError, TypeError, ValueError) as e:
        logger.exception("Failed to analyze call graph with pyan3: %s", e)
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


# ==========================================
# MAIN BUILD FUNCTION
# ==========================================


def build_graph_data(target_folder: str) -> GraphData | None:
    """
    Analyze the Python project and build a rich source-code knowledge graph.

    Combines AST analysis (metadata, imports, inheritance) with pyan3 call graph
    analysis (CALLS edges) to produce a fully enriched GraphData object.
    """
    root = Path(target_folder)
    py_files = [p for p in root.rglob("*.py") if p.name != "__init__.py"]

    if not py_files:
        logger.error("No .py files found in '%s'.", target_folder)
        return None

    graph = GraphData()

    logger.info("STEP 1: Extracting AST metadata from %d Python files...", len(py_files))
    for filepath in sorted(py_files):
        _parse_file_ast(filepath, root, graph)

    logger.info("STEP 2: Resolving inheritance edges to fully-qualified names...")
    _resolve_inheritance(graph)

    logger.info("STEP 3: Extracting call graph with pyan3...")
    _extract_call_edges([str(p) for p in py_files], graph)

    logger.info(
        "Extraction complete — nodes: %d | CALLS: %d | IMPORTS: %d | "
        "INHERITS: %d | IMPLEMENTS: %d | DEFINED_IN: %d",
        len(graph.nodes),
        len(graph.calls_edges),
        len(graph.imports_edges),
        len(graph.inherits_edges),
        len(graph.implements_edges),
        len(graph.defined_in_edges),
    )
    return graph


# ==========================================
# CYPHER FILE OUTPUT
# ==========================================


def write_cypher_file(graph: GraphData, output_file: str) -> None:
    """Write all graph data as a Cypher import script for manual Neo4j import."""
    output_path = Path(output_file)

    def _write_edge_block(
        lines: list[str],
        label: str,
        edges: set[tuple[str, str]],
        target_label: str = "Component",
    ) -> None:
        """Append relationship Cypher statements to the lines buffer."""
        lines.append(f"// --- {label} RELATIONSHIPS ---\n")
        for src, dst in sorted(edges):
            lines.append(
                f"MATCH (a:Component {{name: '{_escape_cypher(src)}'}}), "
                f"(b:{target_label} {{name: '{_escape_cypher(dst)}'}})\n"
                f"MERGE (a)-[:{label}]->(b);\n"
            )
        lines.append("\n")

    lines: list[str] = []
    lines.append("// ================================================================\n")
    lines.append("// AGORA SOURCE CODE KNOWLEDGE GRAPH — CYPHER IMPORT SCRIPT\n")
    lines.append("// ================================================================\n\n")
    lines.append("// Uncomment below to wipe existing data before re-import:\n")
    lines.append("// MATCH (n) DETACH DELETE n;\n\n")

    # 1. Layer nodes
    lines.append("// --- LAYER NODES ---\n")
    for layer_name, description in LAYER_DESCRIPTIONS.items():
        lines.append(
            f"MERGE (l:Layer {{name: '{_escape_cypher(layer_name)}', "
            f"description: '{_escape_cypher(description)}'}});\n"
        )
    lines.append("\n")

    # 2. Component nodes — MERGE on name, SET all metadata properties
    lines.append("// --- COMPONENT NODES ---\n")
    for node in sorted(graph.nodes.values(), key=lambda n: n.name):
        lines.append(f"MERGE (n:Component {{name: '{_escape_cypher(node.name)}'}})\n")
        lines.append(
            f"  SET n.kind = '{_escape_cypher(node.kind)}', "
            f"n.module = '{_escape_cypher(node.module)}', "
            f"n.layer = '{_escape_cypher(node.layer)}',\n"
            f"      n.source_file = '{_escape_cypher(node.source_file)}', "
            f"n.line_number = {node.line_number},\n"
            f"      n.docstring = '{_escape_cypher(node.docstring)}', "
            f"n.signature = '{_escape_cypher(node.signature)}';\n"
        )
    lines.append("\n")

    # 3. All relationship types
    _write_edge_block(lines, "CALLS", graph.calls_edges)
    _write_edge_block(lines, "IMPORTS", graph.imports_edges)
    _write_edge_block(lines, "INHERITS", graph.inherits_edges)
    _write_edge_block(lines, "IMPLEMENTS", graph.implements_edges)
    _write_edge_block(lines, "DEFINED_IN", graph.defined_in_edges)
    _write_edge_block(lines, "BELONGS_TO_LAYER", graph.belongs_to_layer_edges, target_label="Layer")

    output_path.write_text("".join(lines), encoding="utf-8")
    logger.info("Cypher script written to %s.", output_file)


# ==========================================
# NEO4J DIRECT PUSH
# ==========================================


def push_to_neo4j(
    graph: GraphData,
    *,
    uri: str = NEO4J_URI,
    user: str = NEO4J_USER,
    password: str = NEO4J_PASSWORD,
) -> None:
    """Push the enriched knowledge graph directly into a running Neo4j instance."""
    logger.info("Connecting to Neo4j at %s ...", uri)

    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session() as session:
            # Clear all existing data before re-import
            session.run("MATCH (n) DETACH DELETE n")
            logger.info("Cleared existing graph data.")

            # Create Layer nodes
            logger.info("Creating %d Layer nodes...", len(LAYER_DESCRIPTIONS))
            for layer_name, description in LAYER_DESCRIPTIONS.items():
                session.run(
                    "MERGE (l:Layer {name: $name}) SET l.description = $description",
                    name=layer_name,
                    description=description,
                )

            # Create Component nodes with all metadata properties
            logger.info("Creating %d Component nodes...", len(graph.nodes))
            for node in graph.nodes.values():
                session.run(
                    """
                    MERGE (n:Component {name: $name})
                    SET n.kind        = $kind,
                        n.module      = $module,
                        n.layer       = $layer,
                        n.source_file = $source_file,
                        n.line_number = $line_number,
                        n.docstring   = $docstring,
                        n.signature   = $signature
                    """,
                    name=node.name,
                    kind=node.kind,
                    module=node.module,
                    layer=node.layer,
                    source_file=node.source_file,
                    line_number=node.line_number,
                    docstring=node.docstring,
                    signature=node.signature,
                )

            def _push_edges(
                rel_type: str,
                edges: set[tuple[str, str]],
                target_label: str = "Component",
            ) -> None:
                """Push a batch of typed relationships into Neo4j."""
                logger.info("Creating %d %s edges...", len(edges), rel_type)
                # rel_type and target_label are internal constants — safe to interpolate
                query = (
                    f"MATCH (a:Component {{name: $src}}), (b:{target_label} {{name: $dst}}) "
                    f"MERGE (a)-[:{rel_type}]->(b)"
                )
                for src, dst in edges:
                    session.run(query, src=src, dst=dst)

            _push_edges("CALLS", graph.calls_edges)
            _push_edges("IMPORTS", graph.imports_edges)
            _push_edges("INHERITS", graph.inherits_edges)
            _push_edges("IMPLEMENTS", graph.implements_edges)
            _push_edges("DEFINED_IN", graph.defined_in_edges)
            _push_edges("BELONGS_TO_LAYER", graph.belongs_to_layer_edges, target_label="Layer")

    logger.info(
        "Push complete — nodes: %d | CALLS: %d | IMPORTS: %d | "
        "INHERITS: %d | IMPLEMENTS: %d | DEFINED_IN: %d",
        len(graph.nodes),
        len(graph.calls_edges),
        len(graph.imports_edges),
        len(graph.inherits_edges),
        len(graph.implements_edges),
        len(graph.defined_in_edges),
    )


# ==========================================
# ENTRY POINT
# ==========================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    graph_data = build_graph_data(TARGET_FOLDER)
    if graph_data:
        write_cypher_file(graph_data, OUTPUT_CYPHER_FILE)
        push_to_neo4j(graph_data)
