"""Markdown report generator for document analysis results."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from src.analyzers.document_models import (
    AnalysisItem,
    AnalysisResult,
    MultiDocumentResult,
    Severity,
)

# ── Severity display config ─────────────────────────────────────────────────

SEVERITY_EMOJI: dict[str, str] = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🟢",
    "info": "🔵",
}

SEVERITY_LABEL: dict[str, str] = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "info": "Info",
}

TYPE_EMOJI: dict[str, str] = {
    "bug": "🐛",
    "task": "✅",
    "improvement": "💡",
    "question": "❓",
}

TYPE_LABEL: dict[str, str] = {
    "bug": "Bug",
    "task": "Task",
    "improvement": "Cải tiến",
    "question": "Câu hỏi",
}

TYPE_HEADER: dict[str, str] = {
    "bug": "Bugs",
    "task": "Tasks",
    "improvement": "Cải tiến (Improvements)",
    "question": "Câu hỏi (Questions)",
}


def generate_report(result: AnalysisResult) -> str:
    """Generate a full Markdown report from an analysis result."""
    lines: list[str] = []

    # Header
    lines.append("# 📋 Document Analysis Report")
    lines.append("")
    lines.append(f"**File:** `{result.filename}`  ")
    lines.append(f"**Ngày phân tích:** {result.analyzed_at.strftime('%Y-%m-%d %H:%M')}  ")
    lines.append(f"**Tổng số mục:** {len(result.items)}")
    lines.append("")

    if not result.items:
        lines.append("> Không tìm thấy task hoặc bug nào trong tài liệu này.")
        return "\n".join(lines)

    # Summary section
    lines.append("---")
    lines.append("")
    lines.append("## 📊 Tổng quan")
    lines.append("")
    lines.append(_build_summary_table(result))
    lines.append("")

    # Severity breakdown
    if result.severity_stats:
        lines.append("### Phân bố mức độ")
        lines.append("")
        for severity in cast(list[Severity], ["critical", "high", "medium", "low", "info"]):
            count = result.severity_stats.get(severity, 0)
            if count > 0:
                emoji = SEVERITY_EMOJI.get(severity, "⚪")
                label = SEVERITY_LABEL.get(severity, severity)
                bar = "█" * min(count, 20)
                lines.append(f"- {emoji} **{label}**: {count} {bar}")
        lines.append("")

    # Items grouped by type
    lines.append("---")
    lines.append("")

    for item_type in ["bug", "task", "improvement", "question"]:
        type_items = [i for i in result.items if i.item_type == item_type]
        if not type_items:
            continue

        emoji = TYPE_EMOJI.get(item_type, "📌")
        header = TYPE_HEADER.get(item_type, item_type)
        lines.append(f"## {emoji} {header} ({len(type_items)})")
        lines.append("")

        # Sort by severity: critical > high > medium > low > info
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        type_items.sort(key=lambda x: severity_order.get(x.severity, 99))

        for idx, item in enumerate(type_items, 1):
            lines.append(_format_item(item, idx))
            lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append(
        f"*Báo cáo được tạo tự động bởi Agora Document Analyzer — "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"
    )

    return "\n".join(lines)


def generate_combined_report(multi_result: MultiDocumentResult) -> str:
    """Generate a combined Markdown report for multiple documents."""
    lines: list[str] = []

    lines.append("# 📋 Combined Document Analysis Report")
    lines.append("")
    lines.append(f"**Số file đã phân tích:** {len(multi_result.results)}  ")
    lines.append(f"**Ngày phân tích:** {multi_result.analyzed_at.strftime('%Y-%m-%d %H:%M')}  ")
    lines.append(f"**Tổng số mục:** {multi_result.total_items}")
    lines.append("")

    if not multi_result.results:
        lines.append("> Không có kết quả phân tích.")
        return "\n".join(lines)

    # Combined summary table
    lines.append("---")
    lines.append("")
    lines.append("## 📊 Tổng quan")
    lines.append("")
    lines.append("| File | Bugs | Tasks | Cải tiến | Câu hỏi | Tổng |")
    lines.append("|------|------|-------|----------|---------|------|")

    total_bugs = 0
    total_tasks = 0
    total_improvements = 0
    total_questions = 0

    for result in multi_result.results:
        bugs = result.type_stats.get("bug", 0)
        tasks = result.type_stats.get("task", 0)
        improvements = result.type_stats.get("improvement", 0)
        questions = result.type_stats.get("question", 0)
        total = len(result.items)

        total_bugs += bugs
        total_tasks += tasks
        total_improvements += improvements
        total_questions += questions

        lines.append(
            f"| `{result.filename}` | {bugs} | {tasks} | "
            f"{improvements} | {questions} | **{total}** |"
        )

    lines.append(
        f"| **Tổng cộng** | **{total_bugs}** | **{total_tasks}** | "
        f"**{total_improvements}** | **{total_questions}** | "
        f"**{multi_result.total_items}** |"
    )
    lines.append("")

    # Individual reports
    for result in multi_result.results:
        lines.append("---")
        lines.append("")
        lines.append(f"# 📄 {result.filename}")
        lines.append("")

        if not result.items:
            lines.append("> Không tìm thấy task hoặc bug nào.")
            lines.append("")
            continue

        for item_type in ["bug", "task", "improvement", "question"]:
            type_items = [i for i in result.items if i.item_type == item_type]
            if not type_items:
                continue

            emoji = TYPE_EMOJI.get(item_type, "📌")
            header = TYPE_HEADER.get(item_type, item_type)
            lines.append(f"### {emoji} {header} ({len(type_items)})")
            lines.append("")

            severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
            type_items.sort(key=lambda x: severity_order.get(x.severity, 99))

            for idx, item in enumerate(type_items, 1):
                lines.append(_format_item(item, idx))
                lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append(
        f"*Báo cáo được tạo tự động bởi Agora Document Analyzer — "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"
    )

    return "\n".join(lines)


def _build_summary_table(result: AnalysisResult) -> str:
    """Build a summary table in Markdown format."""
    lines: list[str] = []
    lines.append("| Loại | Critical | High | Medium | Low | Info | Tổng |")
    lines.append("|------|----------|------|--------|-----|------|------|")

    for item_type in ["bug", "task", "improvement", "question"]:
        type_items = [i for i in result.items if i.item_type == item_type]
        if not type_items:
            continue

        emoji = TYPE_EMOJI.get(item_type, "📌")
        label = TYPE_LABEL.get(item_type, item_type)

        counts: dict[str, int] = {}
        for severity in ["critical", "high", "medium", "low", "info"]:
            counts[severity] = sum(1 for i in type_items if i.severity == severity)

        total = len(type_items)
        lines.append(
            f"| {emoji} {label} | {counts['critical']} | {counts['high']} | "
            f"{counts['medium']} | {counts['low']} | {counts['info']} | **{total}** |"
        )

    return "\n".join(lines)


def _format_item(item: AnalysisItem, index: int) -> str:
    """Format a single analysis item as Markdown."""
    severity_emoji = SEVERITY_EMOJI.get(item.severity, "⚪")
    severity_label = SEVERITY_LABEL.get(item.severity, item.severity).upper()
    type_emoji = TYPE_EMOJI.get(item.item_type, "📌")

    lines: list[str] = []
    has_structured = bool(item.location or item.scope or item.expected_result)

    if has_structured:
        # ── Rich structured format ──
        lines.append(f"### {index}. {type_emoji} {item.title}")
        lines.append("")
        lines.append(f"**Tiêu đề:** {item.title}")
        lines.append("")

        # Section 1: Location
        if item.location or item.scope:
            lines.append("#### 1. Khu vực xảy ra lỗi")
            if item.location:
                lines.append(f"* **Thành phần:** {item.location}")
            if item.scope:
                lines.append(f"* **Phạm vi ảnh hưởng:** {item.scope}")
            lines.append("")

        # Section 2: Description
        if item.description:
            lines.append("#### 2. Mô tả lỗi")
            lines.append(item.description)
            lines.append("")

        # Section 3: Steps to reproduce
        if item.steps_to_reproduce:
            lines.append("#### 3. Các bước tái hiện (Steps to Reproduce)")
            for si, step in enumerate(item.steps_to_reproduce, 1):
                lines.append(f"{si}. {step}")
            lines.append("")

        # Section 4: Actual result
        if item.actual_result and item.actual_result != item.description:
            lines.append("#### 4. Kết quả thực tế (Actual Result)")
            lines.append(f"* {item.actual_result}")
            lines.append("")

        # Section 5: Expected result
        if item.expected_result:
            lines.append("#### 5. Kết quả mong muốn (Expected Result)")
            lines.append(f"* {item.expected_result}")
            lines.append("")

        # Metadata
        lines.append(f"- **Mức độ:** {severity_emoji} {severity_label}")
        if item.status:
            status_emoji = {"done": "✅", "in-progress": "🔄", "open": "⬜"}.get(item.status, "❔")
            lines.append(f"- **Trạng thái:** {status_emoji} {item.status}")
        if item.assignee:
            lines.append(f"- **Phụ trách:** {item.assignee}")
        if item.tags:
            tags_str = " ".join(f"`{tag}`" for tag in item.tags)
            lines.append(f"- **Tags:** {tags_str}")
    else:
        # ── Simple format for list-extracted items ──
        lines.append(f"### {index}. [{severity_label}] {item.title}")
        lines.append("")
        lines.append(f"- **Mức độ:** {severity_emoji} {severity_label}")

        if item.status:
            status_emoji = {"done": "✅", "in-progress": "🔄", "open": "⬜"}.get(item.status, "❔")
            lines.append(f"- **Trạng thái:** {status_emoji} {item.status}")
        if item.assignee:
            lines.append(f"- **Phụ trách:** {item.assignee}")
        if item.tags:
            tags_str = " ".join(f"`{tag}`" for tag in item.tags)
            lines.append(f"- **Tags:** {tags_str}")
        if item.description and item.description != item.title:
            lines.append(f"- **Mô tả:** {item.description}")
        if item.source_text and item.source_text != item.description:
            lines.append(f"- **Nguồn:** _{item.source_text}_")

    return "\n".join(lines)
