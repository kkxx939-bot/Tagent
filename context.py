"""把检索出来的 chunk 拼成 prompt 可以直接使用的上下文。"""

from __future__ import annotations

from typing import Any

from prompts.promptcase import build_case_generation_prompt_text
from RAGwork.searchfile import search_knowledge

try:
    from RAGwork.hybrid_search import hybrid_search
except RuntimeError:
    hybrid_search = None


QUERY = "用户筛选房源后没有看到正确结果"

# 先用 bm25，速度快，方便看上下文拼接结果。
# 如果要走完整链路，改成 "hybrid"，会使用 BM25 + 向量召回 + rerank。
SEARCH_MODE = "bm25"

# 每类资料最多放多少条进 prompt。
# 不是越多越好，太多会让模型抓不到重点。
SOURCE_LIMITS = {
    "requirement": 4,
    "case": 4,
    "bug": 2,
    "api": 2,
}

# 单个 chunk 放进 prompt 的最大长度。
# chunk 原文已经切过一次，这里再截断是为了控制 prompt 长度。
MAX_CONTENT_CHARS = 700

SOURCE_CONTEXT_KEYS = {
    "requirement": "requirements",
    "case": "cases",
    "bug": "bugs",
    "api": "apis",
}

SOURCE_NAMES = {
    "requirement": "需求",
    "case": "历史用例",
    "bug": "历史 Bug",
    "api": "接口",
}


def build_case_context(query: str = QUERY) -> dict[str, Any]:
    """生成测试用例 prompt 需要的上下文。"""
    context: dict[str, Any] = {
        "query": query,
        "requirements": "无",
        "cases": "无",
        "bugs": "无",
        "apis": "无",
        "chunks": [],
        "source_summary": {},
    }

    source_summary = {}
    all_chunks = []

    for source_type, limit in SOURCE_LIMITS.items():
        results = search_chunks(query=query, source_type=source_type, top_k=limit)
        all_chunks.extend(results)

        context_key = SOURCE_CONTEXT_KEYS[source_type]
        context[context_key] = format_context_group(source_type, results)
        source_summary[source_type] = {
            "count": len(results),
            "chunk_ids": [result.get("chunk_id") for result in results],
        }

    context["chunks"] = all_chunks
    context["source_summary"] = source_summary
    return context


def search_chunks(query: str, source_type: str, top_k: int) -> list[dict[str, Any]]:
    """按资料类型检索 chunk。"""
    if SEARCH_MODE == "hybrid":
        if hybrid_search is None:
            raise RuntimeError("hybrid_search 不可用，请先检查 RAGwork/hybrid_search.py。")
        return hybrid_search(
            query=query,
            source_type=source_type,
            final_top_k=top_k,
            bm25_top_k=max(top_k * 8, 20),
            vector_top_k=max(top_k * 8, 20),
        )

    return search_knowledge(
        query=query,
        top_k=top_k,
        source_type=source_type,
        min_score=0.01,
    )


def format_context_group(source_type: str, results: list[dict[str, Any]]) -> str:
    """把同一类资料拼成一段上下文。"""
    if not results:
        return "无"

    blocks = []
    for index, result in enumerate(results, start=1):
        blocks.append(format_context_item(source_type, index, result))
    return "\n\n".join(blocks)


def format_context_item(source_type: str, index: int, result: dict[str, Any]) -> str:
    """把单个 chunk 拼成模型容易引用的格式。"""
    metadata = result.get("metadata") or {}
    lines = [
        f"【{SOURCE_NAMES.get(source_type, source_type)} {index}】",
        f"chunk_id: {result.get('chunk_id')}",
        f"title: {result.get('title') or '未命名'}",
        f"source_file: {result.get('source_file')}",
    ]

    score = result.get("rerank_score", result.get("fusion_score", result.get("score")))
    if score is not None:
        lines.append(f"score: {score}")

    retrieval_type = result.get("retrieval_type")
    if retrieval_type:
        lines.append(f"retrieval_type: {retrieval_type}")

    project = metadata.get("project")
    feature = metadata.get("feature")
    if project or feature:
        lines.append(f"project/feature: {project or '无'} / {feature or '无'}")

    tags = collect_tags(metadata)
    if tags:
        lines.append(f"tags: {', '.join(tags)}")

    matched_terms = result.get("matched_terms") or []
    if matched_terms:
        lines.append(f"matched_terms: {', '.join(matched_terms[:10])}")

    lines.append("content:")
    lines.append(trim_text(result.get("content") or "", MAX_CONTENT_CHARS))
    return "\n".join(lines)


def collect_tags(metadata: dict[str, Any]) -> list[str]:
    """从 metadata 里挑一些对生成用例有帮助的标签。"""
    tags = []

    for key in ("module", "priority", "severity", "status", "method", "path", "risk_hint"):
        value = metadata.get(key)
        if value:
            tags.append(str(value))

    for key in ("business_topics", "test_dimensions", "api_constraints"):
        value = metadata.get(key)
        if isinstance(value, list):
            tags.extend(str(item) for item in value if item)

    return remove_duplicates(tags)


def remove_duplicates(items: list[str]) -> list[str]:
    result = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def trim_text(text: str, max_chars: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}..."


def main() -> None:
    context = build_case_context(QUERY)
    prompt_text = build_case_generation_prompt_text(context)

    print(f"query: {context['query']}")
    print(f"source_summary: {context['source_summary']}")
    print()
    print(prompt_text)


if __name__ == "__main__":
    main()
