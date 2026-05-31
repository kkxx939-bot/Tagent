# 负责上下文噪声、跨项目命中、可追踪性、load_context 延迟
from __future__ import annotations

from typing import Any

from observability.token_observation import summarize_value


def summarize_context_payload(context_type: str, payload: Any) -> dict[str, Any]:
    summary = summarize_value(context_type, payload, metadata={"context_type": context_type})
    if not isinstance(payload, dict):
        return summary

    chunks = payload.get("chunks")
    if isinstance(chunks, list):
        summary["metadata"]["chunk_count"] = len(chunks)
        summary["metadata"]["source_type_counts"] = _source_type_counts(chunks)
        summary["metadata"]["project_counts"] = _metadata_value_counts(chunks, "project")
        summary["metadata"]["feature_counts"] = _metadata_value_counts(chunks, "feature")
        summary["metadata"]["source_file_counts"] = _field_value_counts(chunks, "source_file")
        summary["metadata"]["chunk_ids"] = [
            item.get("chunk_id") for item in chunks[:20] if isinstance(item, dict) and item.get("chunk_id")
        ]
        summary["metadata"]["trace_items"] = _context_trace_items(chunks)
        summary["metadata"]["traceability"] = _context_traceability(chunks)

    source_summary = payload.get("source_summary")
    if isinstance(source_summary, dict):
        summary["metadata"]["source_summary"] = _compact_source_summary(source_summary)
    return summary


def build_context_observation(
    context_trace: list[dict[str, Any]],
    *,
    query_context: dict[str, Any],
    source_context: dict[str, Any],
    intent_result: dict[str, Any],
) -> dict[str, Any]:
    context_count = 0
    traceable_count = 0
    untraceable_count = 0
    latency_calls: list[dict[str, Any]] = []
    project_counts: dict[str, int] = {}
    feature_counts: dict[str, int] = {}
    source_file_counts: dict[str, int] = {}

    for item in context_trace:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        traceability = metadata.get("traceability") if isinstance(metadata.get("traceability"), dict) else {}
        count = int(traceability.get("context_count") or metadata.get("chunk_count") or 0)
        context_count += count
        traceable_count += int(traceability.get("traceable_context_count") or 0)
        untraceable_count += int(traceability.get("untraceable_context_count") or 0)
        _merge_counts(project_counts, metadata.get("project_counts"))
        _merge_counts(feature_counts, metadata.get("feature_counts"))
        _merge_counts(source_file_counts, metadata.get("source_file_counts"))
        if item.get("latency_ms") is not None:
            latency_calls.append(
                {
                    "name": item.get("name"),
                    "latency_ms": item.get("latency_ms"),
                    "chunk_count": count,
                }
            )

    trace_items = _context_trace_items_from_trace(context_trace)
    topic_hints = _expected_topic_hints(query_context, source_context, intent_result)
    project_hints = _expected_project_hints(query_context, source_context)
    noise_context_count = _noise_context_count(trace_items, topic_hints)
    cross_project_count = _cross_project_count_from_items(trace_items, project_hints)

    return {
        "noise": {
            "noise_context_count": noise_context_count,
            "noise_context_rate": _rate(noise_context_count, context_count) if topic_hints else None,
            "cross_project_context_count": cross_project_count if project_hints else None,
            "cross_project_context_rate": _rate(cross_project_count, context_count) if project_hints else None,
            "expected_topic_hints": topic_hints,
            "expected_project_hints": project_hints,
            "method": "topic_hint_heuristic" if topic_hints else "not_enough_topic_hint",
        },
        "traceability": {
            "context_count": context_count,
            "traceable_context_count": traceable_count,
            "untraceable_context_count": untraceable_count,
            "traceable_context_rate": _rate(traceable_count, context_count),
            "project_counts": project_counts,
            "feature_counts": feature_counts,
            "source_file_counts": source_file_counts,
        },
        "latency": {
            "load_context_total_ms": round(sum(float(item.get("latency_ms") or 0) for item in latency_calls), 2),
            "load_context_call_count": len(latency_calls),
            "load_context_calls": latency_calls,
        },
    }


def _source_type_counts(chunks: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        source_type = str(chunk.get("source_type") or "unknown")
        counts[source_type] = counts.get(source_type, 0) + 1
    return counts


def _field_value_counts(chunks: list[Any], field_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        value = chunk.get(field_name)
        if value in (None, "", []):
            continue
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _metadata_value_counts(chunks: list[Any], field_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        metadata = chunk.get("metadata")
        if not isinstance(metadata, dict):
            continue
        value = metadata.get(field_name)
        if value in (None, "", []):
            continue
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _context_traceability(chunks: list[Any]) -> dict[str, Any]:
    total = len(chunks)
    traceable = 0
    missing_chunk_id = 0
    missing_source_file = 0
    missing_project = 0
    missing_feature = 0
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        has_chunk_id = bool(chunk.get("chunk_id"))
        has_source_file = bool(chunk.get("source_file"))
        if has_chunk_id and has_source_file:
            traceable += 1
        if not has_chunk_id:
            missing_chunk_id += 1
        if not has_source_file:
            missing_source_file += 1
        if not metadata.get("project"):
            missing_project += 1
        if not metadata.get("feature"):
            missing_feature += 1

    return {
        "context_count": total,
        "traceable_context_count": traceable,
        "untraceable_context_count": max(total - traceable, 0),
        "traceable_context_rate": _rate(traceable, total),
        "missing_chunk_id_count": missing_chunk_id,
        "missing_source_file_count": missing_source_file,
        "missing_project_count": missing_project,
        "missing_feature_count": missing_feature,
    }


def _context_trace_items(chunks: list[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for chunk in chunks[:80]:
        if not isinstance(chunk, dict):
            continue
        metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        items.append(
            {
                "chunk_id": chunk.get("chunk_id"),
                "source_type": chunk.get("source_type"),
                "source_file": chunk.get("source_file"),
                "title": chunk.get("title"),
                "project": metadata.get("project"),
                "feature": metadata.get("feature"),
            }
        )
    return items


def _context_trace_items_from_trace(context_trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for trace in context_trace:
        metadata = trace.get("metadata") if isinstance(trace, dict) and isinstance(trace.get("metadata"), dict) else {}
        trace_items = metadata.get("trace_items")
        if isinstance(trace_items, list):
            items.extend(item for item in trace_items if isinstance(item, dict))
    return items


def _expected_topic_hints(
    query_context: dict[str, Any],
    source_context: dict[str, Any],
    intent_result: dict[str, Any],
) -> list[str]:
    hints: list[str] = []
    profile = source_context.get("source_profile") if isinstance(source_context, dict) else None
    if isinstance(profile, dict):
        for key in ("domain", "module"):
            if profile.get(key):
                hints.append(str(profile[key]))
    extracted = intent_result.get("extracted_context") if isinstance(intent_result, dict) else None
    if isinstance(extracted, dict):
        hints.extend(str(item) for item in extracted.get("target") or [] if item)
    normalized = query_context.get("normalized_query") if isinstance(query_context, dict) else ""
    if isinstance(normalized, str):
        for keyword in ("车机", "银行", "租房", "信贷", "贷款", "登录", "注册", "订单", "商场"):
            if keyword in normalized:
                hints.append(keyword)
    return [item for item in _dedupe_text(hints) if item not in {"需求", "用例", "测试用例", "case", "文档", "资料"}]


def _expected_project_hints(query_context: dict[str, Any], source_context: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    profile = source_context.get("source_profile") if isinstance(source_context, dict) else None
    if isinstance(profile, dict) and profile.get("domain"):
        hints.append(str(profile["domain"]))
    normalized = query_context.get("normalized_query") if isinstance(query_context, dict) else ""
    if isinstance(normalized, str):
        for keyword in ("车机", "银行", "租房", "信贷", "贷款", "商场"):
            if keyword in normalized:
                hints.append(keyword)
    return _dedupe_text(hints)


def _noise_context_count(trace_items: list[dict[str, Any]], topic_hints: list[str]) -> int | None:
    if not topic_hints:
        return None
    count = 0
    for item in trace_items:
        text = " ".join(str(item.get(key) or "") for key in ("project", "feature", "title", "source_file", "source_type"))
        if not _matches_any(text, topic_hints):
            count += 1
    return count


def _cross_project_count_from_items(trace_items: list[dict[str, Any]], expected_hints: list[str]) -> int:
    if not expected_hints:
        return 0
    count = 0
    for item in trace_items:
        project = str(item.get("project") or "")
        if project and not _matches_any(project, expected_hints):
            count += 1
    return count


def _compact_source_summary(source_summary: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for source_type, item in source_summary.items():
        if not isinstance(item, dict):
            continue
        compact[source_type] = {
            "count": item.get("count"),
            "chunk_ids": item.get("chunk_ids") or item.get("source_files") or [],
        }
    return compact


def _matches_any(value: str, candidates: list[str]) -> bool:
    normalized = str(value or "").lower()
    for candidate in candidates:
        text = str(candidate or "").lower()
        if text and (text in normalized or normalized in text):
            return True
    return False


def _merge_counts(target: dict[str, int], source: Any) -> None:
    if not isinstance(source, dict):
        return
    for key, value in source.items():
        if not key:
            continue
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        target[str(key)] = target.get(str(key), 0) + count


def _rate(count: int | None, total: int) -> float | None:
    if count is None or total <= 0:
        return None
    return round(count / total, 4)


def _dedupe_text(items: list[str]) -> list[str]:
    result = []
    for item in items:
        value = str(item or "").strip()
        if value and value not in result:
            result.append(value)
    return result
