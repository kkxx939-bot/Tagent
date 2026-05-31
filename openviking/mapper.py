from __future__ import annotations

from typing import Any


OPENVIKING_BACKEND = "openviking"


def response_to_context(query: str, result: dict[str, Any], target_uri: str, search_mode: str) -> dict[str, Any]:
    chunks: list[dict[str, Any]] = []
    source_summary: dict[str, dict[str, Any]] = {}

    for group_name, source_type in (("resources", "resource"), ("memories", "memory"), ("skills", "skill")):
        matches = result.get(group_name)
        if not isinstance(matches, list):
            continue
        for item in matches:
            if not isinstance(item, dict):
                continue
            chunk = matched_context_to_chunk(item, source_type=source_type, index=len(chunks) + 1)
            chunks.append(chunk)
            add_source_summary(source_summary, chunk)

    return {
        "query": query,
        "backend": OPENVIKING_BACKEND,
        "target_uri": target_uri,
        "chunks": chunks,
        "source_summary": source_summary,
        "openviking": {
            "search_mode": search_mode,
            "total": result.get("total"),
            "query_plan": result.get("query_plan"),
        },
    }


def matched_context_to_chunk(item: dict[str, Any], source_type: str, index: int) -> dict[str, Any]:
    uri = str(item.get("uri") or "")
    content = matched_context_content(item)
    title = title_from_uri(uri) or str(item.get("category") or source_type)
    mapped_source_type = map_source_type(source_type, uri, item)
    metadata = {
        "uri": uri,
        "openviking_context_type": item.get("context_type") or source_type,
        "openviking_level": item.get("level"),
        "score": item.get("score"),
        "category": item.get("category"),
        "match_reason": item.get("match_reason"),
        "relations": item.get("relations") or [],
        "project": project_from_uri(uri),
        "feature": feature_from_uri(uri),
    }
    return {
        "chunk_id": f"openviking_{index:06d}",
        "source_type": mapped_source_type,
        "item_type": source_type,
        "chunk_type": "openviking_context",
        "source_file": uri,
        "title": title,
        "content": content,
        "metadata": {key: value for key, value in metadata.items() if value not in (None, "", [])},
    }


def matched_context_content(item: dict[str, Any]) -> str:
    parts = []
    if item.get("overview"):
        parts.append(str(item["overview"]))
    if item.get("abstract"):
        parts.append(str(item["abstract"]))
    if item.get("match_reason"):
        parts.append(f"match_reason: {item['match_reason']}")
    return "\n".join(parts).strip()


def map_source_type(source_type: str, uri: str, item: dict[str, Any]) -> str:
    text = " ".join(str(value or "").lower() for value in (uri, item.get("category"), item.get("context_type")))
    mapping = {
        "requirement": ("requirement", "requirements", "需求", "prd"),
        "case": ("case", "test_case", "测试用例", "用例"),
        "bug": ("bug", "defect", "缺陷"),
        "api": ("api", "openapi", "swagger", "接口"),
    }
    for mapped, keywords in mapping.items():
        if any(keyword.lower() in text for keyword in keywords):
            return mapped
    return source_type


def add_source_summary(source_summary: dict[str, dict[str, Any]], chunk: dict[str, Any]) -> None:
    source_type = str(chunk.get("source_type") or "unknown")
    item = source_summary.setdefault(source_type, {"count": 0, "chunk_ids": []})
    item["count"] += 1
    item["chunk_ids"].append(chunk.get("chunk_id"))


def title_from_uri(uri: str) -> str:
    if not uri:
        return ""
    return uri.rstrip("/").split("/")[-1]


def project_from_uri(uri: str) -> str | None:
    parts = uri_parts(uri)
    if len(parts) >= 2 and parts[0] == "resources":
        return parts[1]
    return None


def feature_from_uri(uri: str) -> str | None:
    parts = uri_parts(uri)
    if len(parts) >= 3 and parts[0] == "resources":
        return parts[2]
    return None


def uri_parts(uri: str) -> list[str]:
    prefix = "viking://"
    value = uri[len(prefix) :] if uri.startswith(prefix) else uri
    return [part for part in value.split("/") if part]
