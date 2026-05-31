# 只负责 token 估算和结构化 token 分段
from __future__ import annotations

import json
import math
import re
from typing import Any


def estimate_tokens(value: Any) -> int:
    text = _to_text(value)
    if not text:
        return 0

    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    words = len(re.findall(r"[A-Za-z0-9_]+", text))
    other_chars = len(re.findall(r"[^\sA-Za-z0-9_\u4e00-\u9fff]", text))
    return max(1, math.ceil(cjk_chars * 0.8 + words * 1.2 + other_chars * 0.4))


def summarize_value(name: str, value: Any, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    text = _to_text(value)
    return {
        "name": name,
        "chars": len(text),
        "estimated_tokens": estimate_tokens(text),
        "metadata": metadata or {},
    }


def build_token_observation(
    *,
    user_query: str,
    normalized_query: str,
    query_context: dict[str, Any],
    source_context: dict[str, Any],
    intent_result: dict[str, Any],
    selected_skill: dict[str, Any] | None,
    plan: dict[str, Any] | None,
    execution_result: dict[str, Any] | None,
    final_output: dict[str, Any],
    context_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    sections = [
        summarize_value("user_query", user_query),
        summarize_value("normalized_query", normalized_query),
        summarize_value("query_context", query_context),
        summarize_value("source_profile", (source_context or {}).get("source_profile")),
        summarize_value("source_document", _source_document_text(source_context)),
        summarize_value("intent_result", intent_result),
        summarize_value("selected_skill", selected_skill),
        summarize_value("plan", plan),
        summarize_value("execution_result", execution_result),
        summarize_value("final_output", final_output),
    ]
    sections = [section for section in sections if section["chars"] > 0]
    estimated_structural = sum(section["estimated_tokens"] for section in sections)
    estimated_context = sum(
        int(item.get("estimated_tokens") or 0) for item in (context_trace or []) if isinstance(item, dict)
    )

    return {
        "estimate_method": "local_char_heuristic",
        "estimated_total_tokens": estimated_structural + estimated_context,
        "estimated_structural_tokens": estimated_structural,
        "estimated_context_tokens": estimated_context,
        "sections": sections,
    }


def _source_document_text(source_context: dict[str, Any]) -> str:
    document_context = source_context.get("document_context") if isinstance(source_context, dict) else None
    if not isinstance(document_context, dict):
        return ""
    return str(document_context.get("content") or "")


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)
