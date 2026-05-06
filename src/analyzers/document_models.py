"""Domain models for document analysis — pure data, zero I/O."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ItemType = Literal["bug", "task", "improvement", "question"]
Severity = Literal["critical", "high", "medium", "low", "info"]
FileType = Literal["docx", "txt", "md", "image"]


class DocumentSection(BaseModel):
    """A section of the parsed document."""

    heading: str | None = None
    content: str
    level: int = 0  # heading level (0 = body, 1-6 = h1-h6)


class ParsedDocument(BaseModel):
    """Raw content extracted from a document file."""

    filename: str
    file_type: FileType
    raw_text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    sections: list[DocumentSection] = Field(default_factory=list)
    parsed_at: datetime = Field(default_factory=datetime.now)


class AnalysisItem(BaseModel):
    """A single task or bug identified in the document."""

    item_type: ItemType
    title: str
    description: str
    severity: Severity = "medium"
    status: str | None = None  # "open", "in-progress", "done"
    assignee: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_text: str = ""  # original text that triggered this item
    # Structured report fields
    location: str = ""  # component/area where the issue occurs
    scope: str = ""  # scope/range of the issue
    actual_result: str = ""  # what currently happens
    expected_result: str = ""  # what should happen
    steps_to_reproduce: list[str] = Field(default_factory=list)  # reproduction steps


class AnalysisResult(BaseModel):
    """Structured result of document analysis."""

    filename: str
    analyzed_at: datetime = Field(default_factory=datetime.now)
    summary: str = ""
    items: list[AnalysisItem] = Field(default_factory=list)
    severity_stats: dict[Severity, int] = Field(default_factory=dict)
    type_stats: dict[ItemType, int] = Field(default_factory=dict)
    markdown_report: str = ""


class MultiDocumentResult(BaseModel):
    """Combined result from analyzing multiple documents."""

    results: list[AnalysisResult] = Field(default_factory=list)
    total_items: int = 0
    combined_markdown: str = ""
    analyzed_at: datetime = Field(default_factory=datetime.now)
