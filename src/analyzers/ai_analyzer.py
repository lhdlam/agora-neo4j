"""AI-powered document analyzer using Groq API."""

from __future__ import annotations

from collections import Counter
import json
import logging
import os
from typing import Any, cast

from openai import AsyncOpenAI

from src.analyzers.document_models import AnalysisItem, AnalysisResult, ItemType, Severity
from src.analyzers.report_generator import generate_report

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_MODEL = "groq/compound"

MAX_INPUT_CHARS = 120_000  # ~30K tokens — safe for API

# ── System Prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Bạn là chuyên gia phân tích tài liệu phần mềm. Nhiệm vụ: phân tích văn bản
đầu vào và tạo báo cáo Bug/Task/Improvement có cấu trúc.

**QUY TẮC BẮT BUỘC:**
1. Trả về CHÍNH XÁC một JSON object (không markdown, không giải thích thêm).
2. Phân tích toàn bộ nội dung, xác định loại (bug/task/improvement/question).
3. Phản hồi bằng ngôn ngữ giống với ngôn ngữ đầu vào (Việt/Anh).
4. Tạo tiêu đề chuyên nghiệp, rõ ràng. Mô tả chi tiết hơn input gốc.

**JSON SCHEMA bắt buộc:**
{
  "items": [
    {
      "item_type": "bug" | "task" | "improvement" | "question",
      "title": "Tiêu đề ngắn gọn, chuyên nghiệp",
      "description": "Mô tả chi tiết về vấn đề hoặc yêu cầu",
      "severity": "critical" | "high" | "medium" | "low" | "info",
      "location": "Vị trí/thành phần xảy ra (nếu có)",
      "scope": "Phạm vi ảnh hưởng (nếu có)",
      "actual_result": "Kết quả thực tế / hiện trạng (nếu có)",
      "expected_result": "Kết quả mong muốn / yêu cầu (nếu có)",
      "steps_to_reproduce": ["Bước 1", "Bước 2"],
      "tags": ["frontend", "backend", "auth", "performance", "security", "ui", ...],
      "status": "open" | "in-progress" | "done" | null
    }
  ],
  "summary": "Tóm tắt ngắn gọn toàn bộ phân tích"
}

**VÍ DỤ:**
Input: "- vị trí: Legend panel - mô tả: font size quá nhỏ - mong muốn: tăng font size"
Output:
{
  "items": [{
    "item_type": "improvement",
    "title": "[Legend Panel] Font size quá nhỏ, cần tăng kích thước",
    "description": "Font size hiện tại trong Legend Panel được thiết lập quá nhỏ, gây khó đọc.",
    "severity": "low",
    "location": "Legend Panel",
    "scope": "Toàn bộ Legend Panel",
    "actual_result": "Font size hiện tại quá nhỏ, khó đọc",
    "expected_result": "Tăng font size để cải thiện khả năng đọc",
    "steps_to_reproduce": ["Mở ứng dụng", "Quan sát Legend Panel"],
    "tags": ["ui", "frontend"],
    "status": "open"
  }],
  "summary": "1 cải tiến UI liên quan đến font size trong Legend Panel"
}"""


# ── AI Analyzer Class ─────────────────────────────────────────────────────────


class AIAnalyzer:
    """Analyze documents using AI (Groq REST APIs)."""

    def __init__(
        self,
        provider: str = "groq",
        api_key: str = "",
        model: str = "",
    ) -> None:
        self.provider = "groq"
        self.api_key = api_key.strip() or os.getenv("GROQ_API_KEY", "")
        self.model = model or os.getenv("AI_MODEL_GROQ", DEFAULT_GROQ_MODEL)
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=GROQ_BASE_URL,
        )

    async def analyze(self, text: str, filename: str = "input") -> AnalysisResult:
        """Analyze text using AI and return structured result."""
        # Truncate if too long
        if len(text) > MAX_INPUT_CHARS:
            text = text[:MAX_INPUT_CHARS] + "\n\n[... văn bản bị cắt ngắn do quá dài]"
            logger.warning("Text truncated to %d chars for AI analysis", MAX_INPUT_CHARS)

        try:
            raw_json = await self._call_api(text)
            result = self._parse_response(raw_json, filename)
        except Exception:
            logger.exception("AI analysis failed for '%s'", filename)
            raise
        else:
            # Generate markdown report
            markdown = generate_report(result)
            result.markdown_report = markdown

            return result

    async def _call_api(self, text: str) -> dict[str, Any]:
        """Call Groq API and return parsed JSON response."""
        response = await self.client.responses.create(
            input=f"Phân tích văn bản sau:\n\n{text}",
            instructions=SYSTEM_PROMPT,
            model=self.model,
        )

        try:
            raw_text = response.output_text
            # Remove any markdown formatting if present (e.g., ```json ... ```)
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            if raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
            return json.loads(raw_text.strip())  # type: ignore[no-any-return]
        except (AttributeError, json.JSONDecodeError) as e:
            msg = f"Failed to parse Groq response: {e}"
            raise RuntimeError(msg) from e

    def _parse_response(self, data: dict[str, Any], filename: str) -> AnalysisResult:
        """Parse AI JSON response into AnalysisResult."""
        items: list[AnalysisItem] = []

        raw_items = data.get("items", [])
        for raw in raw_items:
            try:
                item = AnalysisItem(
                    item_type=self._safe_type(raw.get("item_type", "task")),
                    title=raw.get("title", "Untitled"),
                    description=raw.get("description", ""),
                    severity=self._safe_severity(raw.get("severity", "medium")),
                    status=raw.get("status"),
                    tags=raw.get("tags", []),
                    source_text="",
                    location=raw.get("location", ""),
                    scope=raw.get("scope", ""),
                    actual_result=raw.get("actual_result", ""),
                    expected_result=raw.get("expected_result", ""),
                    steps_to_reproduce=raw.get("steps_to_reproduce", []),
                )
                items.append(item)
            except Exception:
                logger.warning("Skipping malformed AI item: %s", raw)

        severity_stats = dict(Counter(item.severity for item in items))
        type_stats = dict(Counter(item.item_type for item in items))
        summary = data.get("summary", f"AI phân tích '{filename}': {len(items)} mục.")

        return AnalysisResult(
            filename=filename,
            summary=summary,
            items=items,
            severity_stats=severity_stats,
            type_stats=type_stats,
        )

    @staticmethod
    def _safe_type(val: str) -> ItemType:
        """Ensure item_type is valid."""
        valid = {"bug", "task", "improvement", "question"}
        res = val if val in valid else "task"
        return cast(ItemType, res)

    @staticmethod
    def _safe_severity(val: str) -> Severity:
        """Ensure severity is valid."""
        valid = {"critical", "high", "medium", "low", "info"}
        res = val if val in valid else "medium"
        return cast(Severity, res)
