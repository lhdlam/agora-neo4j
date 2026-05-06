from __future__ import annotations

from collections.abc import AsyncIterator
import contextlib
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.analyzers.document_models import AnalysisResult, MultiDocumentResult
from src.analyzers.document_parser import SUPPORTED_EXTENSIONS, parse_document
from src.analyzers.report_generator import generate_combined_report, generate_report
from src.analyzers.task_bug_analyzer import analyze_document
from src.neo4j_graph import (
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    WORKSPACE_BASE_PATH,
    build_graph_data,
    push_to_neo4j,
    write_cypher_file,
)

if TYPE_CHECKING:
    from neo4j import GraphDatabase

with contextlib.suppress(ImportError):
    from neo4j import GraphDatabase

from dotenv import load_dotenv

load_dotenv()  # Load .env for AI API keys etc.


class ScanRequest(BaseModel):
    project_name: str
    target_folder: str


class ProjectUpdateRequest(BaseModel):
    new_name: str | None = None
    target_folder: str | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


app = FastAPI(lifespan=lifespan)

# Mount static files
ui_dir = Path(__file__).parent / "ui"
app.mount("/static", StaticFiles(directory=str(ui_dir)), name="static")


@app.get("/")
def read_root() -> FileResponse:
    return FileResponse(ui_dir / "index.html")


@app.get("/api/projects")
def get_projects() -> dict[str, Any]:
    try:
        with (
            GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)) as driver,
            driver.session() as session,
        ):
            result = session.run(
                "MATCH (p:Project) "
                "RETURN p.name AS name, p.target_folder AS target_folder, "
                "p.language AS language"
            )
            projects = [
                {
                    "name": record["name"],
                    "target_folder": record.get("target_folder"),
                    "language": record.get("language", "python"),
                }
                for record in result
            ]
            return {"status": "success", "projects": projects}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return {
        "status": "success",
        "workspace_base_path": WORKSPACE_BASE_PATH,
    }


@app.get("/api/fs")
def get_fs(path: str | None = None) -> dict[str, Any]:
    try:
        if path is None:
            path = WORKSPACE_BASE_PATH

        # Security check: only allow browsing within WORKSPACE_BASE_PATH
        base_path = Path(WORKSPACE_BASE_PATH)
        abs_path = Path(path).resolve()
        if not str(abs_path).startswith(str(base_path)):
            abs_path = base_path

        if not abs_path.exists() or not abs_path.is_dir():
            raise HTTPException(status_code=400, detail="Invalid path")

        folders = []
        for item in abs_path.iterdir():
            # Skip hidden files and non-directories
            if not item.name.startswith(".") and item.is_dir():
                folders.append({"name": item.name, "path": str(item)})

        # Sort folders alphabetically
        folders.sort(key=lambda x: x["name"].lower())

        return {
            "status": "success",
            "current_path": str(abs_path),
            "parent_path": str(abs_path.parent) if abs_path != base_path else None,
            "folders": folders,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/scan")
def scan_project(req: ScanRequest) -> dict[str, Any]:
    try:
        if not Path(req.target_folder).exists():
            raise HTTPException(
                status_code=400, detail=f"Target folder does not exist: {req.target_folder}"
            )

        result = build_graph_data(req.project_name, req.target_folder)
        if not result:
            raise HTTPException(
                status_code=400,
                detail="Failed to build graph data. No source files found?",
            )

        graph_data, detected_language = result

        write_cypher_file(graph_data, "import_neo4j.cypher")
        push_to_neo4j(graph_data, req.target_folder)

        # Store detected language on the Project node
        try:
            with (
                GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)) as driver,
                driver.session() as session,
            ):
                session.run(
                    "MATCH (p:Project {name: $name}) SET p.language = $language",
                    name=req.project_name,
                    language=detected_language,
                )
        except Exception:  # noqa: BLE001 — best effort, don't fail the scan
            pass

        return {
            "status": "success",
            "message": f"Successfully scanned and pushed project '{req.project_name}'",
            "language": detected_language,
            "stats": {
                "nodes": len(graph_data.nodes),
                "calls_edges": len(graph_data.calls_edges),
                "imports_edges": len(graph_data.imports_edges),
                "inherits_edges": len(graph_data.inherits_edges),
                "implements_edges": len(graph_data.implements_edges),
                "defined_in_edges": len(graph_data.defined_in_edges),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/projects/{project_name}/graph")
def get_project_graph(project_name: str, limit: int = 500) -> dict[str, Any]:
    try:
        with (
            GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)) as driver,
            driver.session() as session,
        ):
            nodes_query = """
            MATCH (n:Component {project: $project_name})
            RETURN id(n) AS id, labels(n) AS labels, n AS properties
            LIMIT $limit
            """
            nodes_result = session.run(nodes_query, project_name=project_name, limit=limit)

            nodes = []
            node_ids = set()
            for record in nodes_result:
                node_id = record["id"]
                node_ids.add(node_id)
                props = dict(record["properties"])
                label = props.get("name", "Unknown")
                if "." in label:
                    label = label.split(".")[-1]

                nodes.append(
                    {
                        "id": node_id,
                        "label": label,
                        "full_name": props.get("name", ""),
                        "kind": props.get("kind", ""),
                        "layer": props.get("layer", ""),
                        "type": record["labels"][0] if record["labels"] else "Node",
                        "properties": props,
                    }
                )

            edges_query = """
            MATCH (n:Component {project: $project_name})-[r]->(m:Component {project: $project_name})
            WHERE id(n) IN $node_ids AND id(m) IN $node_ids
            RETURN id(n) AS source, id(m) AS target, type(r) AS type, id(r) AS id
            """
            edges_result = session.run(
                edges_query, project_name=project_name, node_ids=list(node_ids)
            )

            edges = []
            for record in edges_result:
                edges.append(
                    {
                        "id": record["id"],
                        "from": record["source"],
                        "to": record["target"],
                        "label": record["type"],
                        "type": record["type"],
                    }
                )

            return {"status": "success", "nodes": nodes, "edges": edges}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.patch("/api/projects/{project_name}")
def update_project(project_name: str, req: ProjectUpdateRequest) -> dict[str, Any]:
    try:
        with (
            GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)) as driver,
            driver.session() as session,
        ):
            # Update Project node
            query = """
            MATCH (p:Project {name: $project_name})
            SET p.name = COALESCE($new_name, p.name),
                p.target_folder = COALESCE($target_folder, p.target_folder)
            RETURN p.name AS name
            """
            result = session.run(
                query,
                project_name=project_name,
                new_name=req.new_name,
                target_folder=req.target_folder,
            )
            record = result.single()
            if not record:
                raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found")

            # Update associated components if name changed
            if req.new_name and req.new_name != project_name:
                session.run(
                    "MATCH (c:Component {project: $project_name}) SET c.project = $new_name",
                    project_name=project_name,
                    new_name=req.new_name,
                )

            return {
                "status": "success",
                "message": f"Project '{project_name}' updated successfully",
                "new_name": record["name"],
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.delete("/api/projects/{project_name}")
def delete_project(project_name: str) -> dict[str, Any]:
    try:
        with (
            GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)) as driver,
            driver.session() as session,
        ):
            # Delete Project node and all its components
            query = """
            MATCH (p:Project {name: $project_name})
            OPTIONAL MATCH (c:Component {project: $project_name})
            DETACH DELETE p, c
            RETURN count(p) as deleted_count
            """
            result = session.run(query, project_name=project_name)
            record = result.single()

            if record and record["deleted_count"] == 0:
                # If project node wasn't found, maybe only components exist (unlikely but safe)
                session.run(
                    "MATCH (c:Component {project: $project_name}) DETACH DELETE c",
                    project_name=project_name,
                )

            return {
                "status": "success",
                "message": f"Project '{project_name}' and its components deleted successfully",
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


# ── Document Analyzer ─────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_FILES = 5


@app.post("/api/analyze")
async def analyze_documents(
    files: list[UploadFile],
) -> dict[str, Any]:
    """Upload document(s) and receive structured task/bug analysis.

    Accepts: .docx, .txt, .md, .png, .jpg, .jpeg, .bmp, .tiff, .webp
    Returns: Markdown report + structured JSON data
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    if len(files) > MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files. Maximum {MAX_FILES} files allowed.",
        )

    results: list[dict[str, Any]] = []
    analysis_results = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        for upload_file in files:
            filename = upload_file.filename or "unknown"
            suffix = Path(filename).suffix.lower()

            # Validate file extension
            if suffix not in SUPPORTED_EXTENSIONS:
                results.append(
                    {
                        "filename": filename,
                        "status": "error",
                        "error": f"Unsupported file type: {suffix}. "
                        f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
                    }
                )
                continue

            # Read and validate file size
            content = await upload_file.read()
            if len(content) > MAX_FILE_SIZE:
                results.append(
                    {
                        "filename": filename,
                        "status": "error",
                        "error": (
                            f"File too large ({len(content)} bytes). Max: {MAX_FILE_SIZE} bytes."
                        ),
                    }
                )
                continue

            # Save to temp file
            file_path = tmp_path / filename
            file_path.write_bytes(content)

            try:
                # Parse document
                parsed = parse_document(file_path)

                # Analyze for tasks/bugs
                analysis = analyze_document(parsed)

                # Generate markdown report
                markdown = generate_report(analysis)
                analysis.markdown_report = markdown

                analysis_results.append(analysis)

                results.append(
                    {
                        "filename": filename,
                        "status": "success",
                        "file_type": parsed.file_type,
                        "raw_text_length": len(parsed.raw_text),
                        "items_found": len(analysis.items),
                        "type_stats": analysis.type_stats,
                        "severity_stats": analysis.severity_stats,
                        "items": [
                            {
                                "type": item.item_type,
                                "title": item.title,
                                "severity": item.severity,
                                "status": item.status,
                                "tags": item.tags,
                                "description": item.description,
                            }
                            for item in analysis.items
                        ],
                        "markdown": markdown,
                    }
                )

            except Exception as e:  # noqa: BLE001 — per-file error handling
                logger.exception("Failed to analyze %s", filename)
                results.append(
                    {
                        "filename": filename,
                        "status": "error",
                        "error": str(e),
                    }
                )

    # Generate combined report if multiple files
    combined_markdown = ""
    if len(analysis_results) > 1:
        multi = MultiDocumentResult(
            results=analysis_results,
            total_items=sum(len(r.items) for r in analysis_results),
        )
        combined_markdown = generate_combined_report(multi)
        multi.combined_markdown = combined_markdown
    elif len(analysis_results) == 1:
        combined_markdown = analysis_results[0].markdown_report

    return {
        "status": "success",
        "total_files": len(files),
        "processed": len([r for r in results if r.get("status") == "success"]),
        "errors": len([r for r in results if r.get("status") == "error"]),
        "results": results,
        "combined_markdown": combined_markdown,
    }


class TextAnalyzeRequest(BaseModel):
    """Request body for direct text analysis."""

    text: str
    filename: str = "text-input.txt"
    engine: str = "rule"  # "rule" | "ai"
    provider: str = "groq"  # "groq"
    api_key: str = ""  # client-provided API key (takes priority over env)


@app.post("/api/analyze-text")
async def analyze_text(req: TextAnalyzeRequest) -> dict[str, Any]:
    """Analyze raw text input using rule-based or AI engine."""
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text input is empty")

    if len(req.text) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Text too long")

    try:
        if req.engine == "ai":
            return await _analyze_with_ai(req)
        return await _analyze_with_rules(req)

    except Exception as e:
        logger.exception("Failed to analyze text input")
        raise HTTPException(status_code=500, detail=str(e)) from e


async def _analyze_with_rules(req: TextAnalyzeRequest) -> dict[str, Any]:
    """Analyze text using the rule-based engine."""
    from src.analyzers.document_models import DocumentSection, ParsedDocument

    sections: list[DocumentSection] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in req.text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            if current_lines:
                sections.append(
                    DocumentSection(
                        heading=current_heading,
                        content="\n".join(current_lines),
                        level=0,
                    )
                )
                current_lines = []
            current_heading = stripped.lstrip("# ").strip()
        else:
            current_lines.append(line)

    if current_lines:
        sections.append(
            DocumentSection(
                heading=current_heading,
                content="\n".join(current_lines),
                level=0,
            )
        )

    parsed = ParsedDocument(
        filename=req.filename,
        file_type="txt",
        raw_text=req.text,
        sections=sections,
    )

    analysis = analyze_document(parsed)
    markdown = generate_report(analysis)
    analysis.markdown_report = markdown

    return _format_text_response(analysis, markdown)


async def _analyze_with_ai(req: TextAnalyzeRequest) -> dict[str, Any]:
    """Analyze text using AI (Groq)."""
    from src.analyzers.ai_analyzer import AIAnalyzer

    # Resolve API key: request > env
    api_key = req.api_key or os.getenv("GROQ_API_KEY", "")

    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="API key cho Groq chưa được cấu hình. "
            "Vui lòng nhập key trong phần cài đặt AI hoặc thiết lập biến môi trường.",
        )

    analyzer = AIAnalyzer(provider="groq", api_key=api_key)

    try:
        analysis = await analyzer.analyze(req.text, req.filename)
    except RuntimeError as e:
        # AI failed — fallback to rule-based with warning
        logger.warning("AI analysis failed, falling back to rule-based: %s", e)
        rule_result = await _analyze_with_rules(req)
        rule_result["ai_fallback"] = True
        rule_result["ai_error"] = str(e)
        return rule_result

    return _format_text_response(analysis, analysis.markdown_report)


def _format_text_response(analysis: AnalysisResult, markdown: str) -> dict[str, Any]:
    """Format analysis result as API response dict."""
    return {
        "status": "success",
        "filename": analysis.filename,
        "items_found": len(analysis.items),
        "type_stats": analysis.type_stats,
        "severity_stats": analysis.severity_stats,
        "items": [
            {
                "type": item.item_type,
                "title": item.title,
                "severity": item.severity,
                "status": item.status,
                "tags": item.tags,
                "description": item.description,
                "location": item.location,
                "scope": item.scope,
                "expected_result": item.expected_result,
            }
            for item in analysis.items
        ],
        "markdown": markdown,
    }


@app.get("/api/ai-config")
async def get_ai_config() -> dict[str, Any]:
    """Return available AI providers based on configured API keys."""
    groq_key = os.getenv("GROQ_API_KEY", "")

    return {
        "providers": {
            "groq": {
                "available": bool(groq_key),
                "model": os.getenv("AI_MODEL_GROQ", "groq/compound"),
            },
        },
        "default_provider": "groq",
    }
