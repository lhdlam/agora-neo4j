"""Task and bug analysis engine — rule-based keyword + pattern matching."""

from __future__ import annotations

from collections import Counter
import logging
import re
from typing import cast

from src.analyzers.document_models import (
    AnalysisItem,
    AnalysisResult,
    ItemType,
    ParsedDocument,
    Severity,
)

logger = logging.getLogger(__name__)


# ── Keyword Dictionaries ──────────────────────────────────────────────────────

BUG_KEYWORDS: list[str] = [
    # English
    "bug",
    "error",
    "crash",
    "exception",
    "fail",
    "broken",
    "fix",
    "issue",
    "defect",
    "regression",
    "incorrect",
    "wrong",
    "unexpected",
    "null pointer",
    "stack trace",
    "segfault",
    "memory leak",
    "timeout",
    "500",
    "404",
    "403",
    "unhandled",
    "traceback",
    # Vietnamese
    "lỗi",
    "sự cố",
    "không hoạt động",
    "bị crash",
    "bị lỗi",
    "hỏng",
    "không chạy",
    "không thể",
    "bị treo",
    "báo lỗi",
    "thất bại",
    "không đúng",
    "sai",
    "gặp vấn đề",
]

TASK_KEYWORDS: list[str] = [
    # English
    "task",
    "todo",
    "to-do",
    "implement",
    "create",
    "build",
    "develop",
    "add",
    "update",
    "modify",
    "change",
    "refactor",
    "migrate",
    "setup",
    "configure",
    "deploy",
    "integrate",
    "write",
    "design",
    # Vietnamese
    "nhiệm vụ",
    "công việc",
    "thêm",
    "tạo",
    "xây dựng",
    "phát triển",
    "cập nhật",
    "chỉnh sửa",
    "triển khai",
    "cấu hình",
    "thiết kế",
    "viết",
    "làm",
    "hoàn thành",
    "yêu cầu",
]

IMPROVEMENT_KEYWORDS: list[str] = [
    # English
    "improve",
    "enhance",
    "optimize",
    "refine",
    "upgrade",
    "better",
    "performance",
    "speed up",
    "clean up",
    "simplify",
    "suggestion",
    # Vietnamese
    "cải thiện",
    "nâng cấp",
    "tối ưu",
    "cải tiến",
    "đề xuất",
    "gợi ý",
    "tốt hơn",
    "nhanh hơn",
]

QUESTION_KEYWORDS: list[str] = [
    # English
    "question",
    "clarify",
    "unclear",
    "confirm",
    "what",
    "how",
    "why",
    "?",
    "need info",
    "tbd",
    "pending decision",
    # Vietnamese
    "câu hỏi",
    "hỏi",
    "xác nhận",
    "chưa rõ",
    "cần thông tin",
    "cần xác nhận",
    "làm sao",
    "tại sao",
    "như thế nào",
]

SEVERITY_PATTERNS: dict[str, list[str]] = {
    "critical": [
        "crash",
        "data loss",
        "security",
        "blocker",
        "production down",
        "urgent",
        "p0",
        "critical",
        "nghiêm trọng",
        "khẩn cấp",
        "mất dữ liệu",
        "bảo mật",
    ],
    "high": [
        "broken",
        "cannot",
        "fails",
        "high priority",
        "p1",
        "major",
        "important",
        "không thể",
        "quan trọng",
        "ưu tiên cao",
    ],
    "medium": [
        "should",
        "inconsistent",
        "medium",
        "p2",
        "moderate",
        "nên",
        "trung bình",
    ],
    "low": [
        "minor",
        "cosmetic",
        "nice to have",
        "low priority",
        "p3",
        "nhỏ",
        "thẩm mỹ",
        "ưu tiên thấp",
    ],
}

# Patterns that indicate list items (tasks/bugs)
LIST_ITEM_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^\s*[-*•]\s+(.+)", re.MULTILINE),  # bullet points
    re.compile(r"^\s*\d+[.)]\s+(.+)", re.MULTILINE),  # numbered lists
    re.compile(r"^\s*\[[ x/]\]\s+(.+)", re.MULTILINE),  # checkbox items
    re.compile(r"^#+\s+(.+)", re.MULTILINE),  # markdown headings
]

# Status detection patterns
STATUS_PATTERNS: dict[str, list[str]] = {
    "done": ["done", "completed", "fixed", "resolved", "closed", "hoàn thành", "đã sửa"],
    "in-progress": ["in progress", "wip", "working on", "đang làm", "đang xử lý"],
    "open": ["open", "new", "todo", "pending", "mới", "chờ xử lý"],
}


class RuleBasedAnalyzer:
    """Analyze documents using keyword matching and pattern recognition."""

    # Structured field patterns (Vietnamese + English)
    FIELD_PATTERNS: dict[str, list[str]] = {
        "location": ["vị trí", "khu vực", "thành phần", "component", "location", "area"],
        "scope": ["phạm vi", "ảnh hưởng", "scope", "affected", "range"],
        "description": ["mô tả", "chi tiết", "description", "detail", "nội dung"],
        "expected": ["mong muốn", "kỳ vọng", "expected", "want", "yêu cầu", "cần"],
        "actual": ["thực tế", "hiện tại", "actual", "current", "đang"],
        "steps": ["bước", "steps", "reproduce", "tái hiện", "cách tái hiện"],
        "assignee": ["phụ trách", "assign", "người xử lý", "responsible"],
    }

    def analyze(self, document: ParsedDocument) -> AnalysisResult:
        """Analyze a parsed document and extract tasks, bugs, and other items."""
        items: list[AnalysisItem] = []
        text = document.raw_text

        # Strategy 0: Try structured field extraction first
        structured = self._extract_structured_input(text)
        if structured:
            items.extend(structured)
        else:
            # Strategy 1: Extract from list items (bullet points, numbered lists)
            items.extend(self._extract_from_list_items(text))

            # Strategy 2: Extract from sections (headings + content)
            for section in document.sections:
                items.extend(self._extract_from_section(section.heading, section.content))

            # Strategy 3: If no items found, try sentence-level analysis
            if not items:
                items.extend(self._extract_from_sentences(text))

        # Deduplicate by title similarity
        items = self._deduplicate(items)

        # Compute statistics
        severity_stats = dict(Counter(item.severity for item in items))
        type_stats = dict(Counter(item.item_type for item in items))

        summary = self._generate_summary(document.filename, items, type_stats)

        return AnalysisResult(
            filename=document.filename,
            summary=summary,
            items=items,
            severity_stats=severity_stats,
            type_stats=type_stats,
        )

    def _extract_structured_input(self, text: str) -> list[AnalysisItem]:
        """Extract from structured input like 'vị trí: X / phạm vi: Y / mô tả: Z'."""
        fields: dict[str, str] = {}

        for field_key, patterns in self.FIELD_PATTERNS.items():
            for pat in patterns:
                # Match "- key: value" or "key: value" patterns
                regex = re.compile(
                    rf"[-*•]?\s*{re.escape(pat)}\s*[:：]\s*(.+?)(?=\n[-*•]?\s*(?:"
                    + "|".join(re.escape(p) for ps in self.FIELD_PATTERNS.values() for p in ps)
                    + r")\s*[:：]|\Z)",
                    re.IGNORECASE | re.DOTALL,
                )
                match = regex.search(text)
                if match:
                    value = match.group(1).strip()
                    if value and field_key not in fields:
                        fields[field_key] = value

        # Need at least location+description or description+expected to form a structured item
        if not fields.get("description") and not fields.get("expected"):
            return []

        item_type = self._classify_type(text)
        severity = self._classify_severity(text)
        tags = self._extract_tags(text)

        desc = fields.get("description", "")
        location = fields.get("location", "")
        scope = fields.get("scope", "")
        expected = fields.get("expected", "")
        actual = fields.get("actual", desc)

        # Build a meaningful title
        title_parts: list[str] = []
        if location:
            title_parts.append(f"[{location.rstrip('.')}]")
        if desc:
            title_parts.append(desc.split("\n")[0][:80])
        elif expected:
            title_parts.append(expected.split("\n")[0][:80])
        title = " ".join(title_parts) or "Untitled item"

        return [
            AnalysisItem(
                item_type=item_type,
                title=title,
                description=desc or expected,
                severity=severity,
                tags=tags,
                source_text=text.strip(),
                location=location,
                scope=scope,
                actual_result=actual,
                expected_result=expected,
            )
        ]

    def _extract_from_list_items(self, text: str) -> list[AnalysisItem]:
        """Extract items from bullet points, numbered lists, checkboxes."""
        items: list[AnalysisItem] = []
        seen_titles: set[str] = set()

        for pattern in LIST_ITEM_PATTERNS:
            for match in pattern.finditer(text):
                line = match.group(1).strip()
                if len(line) < 5 or line.lower() in seen_titles:
                    continue

                item_type = self._classify_type(line)
                severity = self._classify_severity(line)
                status = self._detect_status(match.group(0))
                tags = self._extract_tags(line)

                items.append(
                    AnalysisItem(
                        item_type=item_type,
                        title=self._make_title(line),
                        description=line,
                        severity=severity,
                        status=status,
                        tags=tags,
                        source_text=match.group(0).strip(),
                    )
                )
                seen_titles.add(line.lower())

        return items

    def _extract_from_section(self, heading: str | None, content: str) -> list[AnalysisItem]:
        """Extract items from document sections."""
        items: list[AnalysisItem] = []

        if not content.strip():
            return items

        # If heading suggests a specific type
        combined = f"{heading or ''} {content}"
        item_type = self._classify_type(combined)
        severity = self._classify_severity(combined)

        # Split content into meaningful chunks
        lines = [ln.strip() for ln in content.split("\n") if ln.strip()]

        for line in lines:
            if len(line) < 10:
                continue
            # Skip if it's just a heading being re-processed
            if line == heading:
                continue

            line_type = self._classify_type(line)
            if line_type != "task":  # non-default classification
                item_type = line_type

            items.append(
                AnalysisItem(
                    item_type=item_type,
                    title=self._make_title(line),
                    description=line,
                    severity=self._classify_severity(line)
                    if self._has_severity_signal(line)
                    else severity,
                    tags=self._extract_tags(line),
                    source_text=line,
                )
            )

        return items

    def _extract_from_sentences(self, text: str) -> list[AnalysisItem]:
        """Fallback: split text into sentences and classify each."""
        items: list[AnalysisItem] = []
        # Split by period, newline, or semicolon
        sentences = re.split(r"[.\n;]+", text)

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 15:
                continue

            item_type = self._classify_type(sentence)
            # Only include sentences that have clear signals
            if not self._has_type_signal(sentence):
                continue

            items.append(
                AnalysisItem(
                    item_type=item_type,
                    title=self._make_title(sentence),
                    description=sentence,
                    severity=self._classify_severity(sentence),
                    tags=self._extract_tags(sentence),
                    source_text=sentence,
                )
            )

        return items

    def _classify_type(self, text: str) -> ItemType:
        """Classify text as bug, task, improvement, or question."""
        lower = text.lower()

        scores: dict[str, int] = {"bug": 0, "task": 0, "improvement": 0, "question": 0}

        for kw in BUG_KEYWORDS:
            if kw in lower:
                scores["bug"] += 2 if len(kw) > 4 else 1

        for kw in TASK_KEYWORDS:
            if kw in lower:
                scores["task"] += 2 if len(kw) > 4 else 1

        for kw in IMPROVEMENT_KEYWORDS:
            if kw in lower:
                scores["improvement"] += 2 if len(kw) > 4 else 1

        for kw in QUESTION_KEYWORDS:
            if kw in lower:
                scores["question"] += 2 if len(kw) > 4 else 1

        max_score = max(scores.values())
        if max_score == 0:
            return "task"  # default

        # Return the type with highest score
        for item_type, score in sorted(scores.items(), key=lambda x: -x[1]):
            if score == max_score:
                return cast(ItemType, item_type)

        return "task"

    def _classify_severity(self, text: str) -> Severity:
        """Classify the severity of an item based on keywords."""
        lower = text.lower()

        for severity, patterns in SEVERITY_PATTERNS.items():
            for pattern in patterns:
                if pattern in lower:
                    return cast(Severity, severity)

        return "medium"  # default

    def _has_severity_signal(self, text: str) -> bool:
        """Check if text contains any severity-related keywords."""
        lower = text.lower()
        return any(
            pattern in lower for patterns in SEVERITY_PATTERNS.values() for pattern in patterns
        )

    def _has_type_signal(self, text: str) -> bool:
        """Check if text contains any type classification keywords."""
        lower = text.lower()
        all_keywords = BUG_KEYWORDS + TASK_KEYWORDS + IMPROVEMENT_KEYWORDS + QUESTION_KEYWORDS
        return any(kw in lower for kw in all_keywords)

    def _detect_status(self, text: str) -> str | None:
        """Detect task/bug status from text."""
        lower = text.lower()

        # Checkbox detection
        if re.search(r"\[x\]", lower):
            return "done"
        if re.search(r"\[/\]", lower):
            return "in-progress"
        if re.search(r"\[ \]", lower):
            return "open"

        for status, keywords in STATUS_PATTERNS.items():
            for kw in keywords:
                if kw in lower:
                    return status

        return None

    def _extract_tags(self, text: str) -> list[str]:
        """Extract relevant tags from text."""
        tags: list[str] = []
        lower = text.lower()

        tag_categories: dict[str, list[str]] = {
            "frontend": ["ui", "css", "html", "react", "vue", "angular", "giao diện"],
            "backend": ["api", "server", "database", "db", "endpoint", "máy chủ"],
            "auth": ["login", "auth", "password", "permission", "đăng nhập", "quyền"],
            "performance": ["slow", "performance", "memory", "cpu", "hiệu suất", "chậm"],
            "security": ["security", "xss", "csrf", "injection", "bảo mật"],
            "testing": ["test", "unit test", "integration", "kiểm thử"],
            "documentation": ["doc", "readme", "comment", "tài liệu"],
            "deployment": ["deploy", "ci/cd", "docker", "kubernetes", "triển khai"],
        }

        for tag, keywords in tag_categories.items():
            if any(kw in lower for kw in keywords):
                tags.append(tag)

        return tags

    def _make_title(self, text: str) -> str:
        """Create a concise title from text (max 80 chars)."""
        # Remove leading markers like "- ", "* ", "1. ", etc.
        cleaned = re.sub(r"^[\s\-*•\d.)]+", "", text).strip()
        if len(cleaned) <= 80:
            return cleaned
        return cleaned[:77] + "..."

    def _deduplicate(self, items: list[AnalysisItem]) -> list[AnalysisItem]:
        """Remove duplicate items based on title similarity."""
        seen: set[str] = set()
        unique: list[AnalysisItem] = []

        for item in items:
            normalized = item.title.lower().strip()
            if normalized not in seen:
                seen.add(normalized)
                unique.append(item)

        return unique

    def _generate_summary(
        self,
        filename: str,
        items: list[AnalysisItem],
        type_stats: dict[ItemType, int],
    ) -> str:
        """Generate a human-readable summary."""
        total = len(items)
        if total == 0:
            return f"Không tìm thấy task hoặc bug nào trong '{filename}'."

        parts: list[str] = []
        type_labels: dict[ItemType, str] = {
            "bug": "bug",
            "task": "task",
            "improvement": "cải tiến",
            "question": "câu hỏi",
        }
        for t, label in type_labels.items():
            count = type_stats.get(t, 0)
            if count > 0:
                parts.append(f"{count} {label}")

        return f"Phân tích '{filename}': tìm thấy {total} mục ({', '.join(parts)})."


def analyze_document(document: ParsedDocument) -> AnalysisResult:
    """Convenience function: analyze a parsed document using the rule-based engine."""
    analyzer = RuleBasedAnalyzer()
    return analyzer.analyze(document)
