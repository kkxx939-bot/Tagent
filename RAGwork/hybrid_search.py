"""Hybrid retrieval pipeline: BM25 + embedding recall + rerank."""

#bm25+向量检索+rerank重排 ，这里这么用有什么好处，和为什么这么用

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from RAGwork.embedding import vector_search
    from RAGwork.rerank import rerank_results
    from RAGwork.searchfile import search_knowledge
except ModuleNotFoundError:
    from embedding import vector_search
    from rerank import rerank_results
    from searchfile import search_knowledge


PROJECT_ROOT = Path(__file__).resolve().parents[1]

QUERY = "用户筛选房源后没有看到正确结果"
SOURCE_TYPE = None  # 可选："case" / "requirement" / "bug" / "api"

BM25_TOP_K = 30
VECTOR_TOP_K = 30
FINAL_TOP_K = 1

BM25_MIN_SCORE = 0.01
VECTOR_MIN_SCORE = 0.0
RRF_K = 60

USE_VECTOR = True
USE_RERANK = True
AUTO_BUILD_VECTOR_INDEX = True
STRICT_VECTOR = True
STRICT_RERANK = True


def hybrid_search(
    query: str,
    source_type: str | None = SOURCE_TYPE,
    bm25_top_k: int = BM25_TOP_K,
    vector_top_k: int = VECTOR_TOP_K,
    final_top_k: int = FINAL_TOP_K,
    bm25_min_score: float = BM25_MIN_SCORE,
    vector_min_score: float = VECTOR_MIN_SCORE,
    use_vector: bool = USE_VECTOR,
    use_rerank: bool = USE_RERANK,
    auto_build_vector_index: bool = AUTO_BUILD_VECTOR_INDEX,
    strict_vector: bool = STRICT_VECTOR,
    strict_rerank: bool = STRICT_RERANK,
) -> list[dict[str, Any]]:
    bm25_results = search_knowledge(
        query,
        top_k=bm25_top_k,
        source_type=source_type,
        min_score=bm25_min_score,
    )
    bm25_results = mark_retrieval_type(bm25_results, "bm25")

    vector_results: list[dict[str, Any]] = []
    if use_vector:
        try:
            vector_results = vector_search(
                query,
                top_k=vector_top_k,
                source_type=source_type,
                min_score=vector_min_score,
                auto_build=auto_build_vector_index,
            )
            vector_results = mark_retrieval_type(vector_results, "embedding")
        except (FileNotFoundError, RuntimeError) as exc:
            if strict_vector:
                raise RuntimeError(
                    "Vector recall is unavailable. Prepare data/model/text2vec-base-chinese "
                    "and build the embedding index first, or run with strict_vector=False."
                ) from exc

    candidates = merge_recall_results(bm25_results, vector_results)
    if not candidates:
        return []

    if not use_rerank:
        return candidates[:final_top_k]

    try:
        return rerank_results(query, candidates, top_k=final_top_k)
    except (FileNotFoundError, RuntimeError) as exc:
        if strict_rerank:
            raise RuntimeError(
                "Rerank is unavailable. Prepare data/model/bge-reranker-large "
                "or run with strict_rerank=False."
            ) from exc
        return candidates[:final_top_k]


def mark_retrieval_type(results: list[dict[str, Any]], retrieval_type: str) -> list[dict[str, Any]]:
    marked = []
    for result in results:
        item = dict(result)
        item["retrieval_type"] = retrieval_type
        marked.append(item)
    return marked


def merge_recall_results(*result_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for results in result_groups:
        for rank, result in enumerate(results, start=1):
            chunk_id = result.get("chunk_id")
            if not chunk_id:
                continue

            retrieval_type = result.get("retrieval_type") or "unknown"
            score_key = f"{retrieval_type}_score"
            rank_key = f"{retrieval_type}_rank"
            rrf_score = 1.0 / (RRF_K + rank)

            if chunk_id not in merged:
                item = dict(result)
                item["recall_sources"] = []
                item["fusion_score"] = 0.0
                merged[chunk_id] = item

            item = merged[chunk_id]
            if retrieval_type not in item["recall_sources"]:
                item["recall_sources"].append(retrieval_type)
            item[score_key] = result.get("score")
            item[rank_key] = rank
            item["fusion_score"] += rrf_score
            item["score"] = round(item["fusion_score"], 6)
            item["retrieval_type"] = "+".join(item["recall_sources"])

    candidates = list(merged.values())
    candidates.sort(key=lambda item: item.get("fusion_score", 0.0), reverse=True)
    return candidates


def print_results(query: str, results: list[dict[str, Any]]) -> None:
    print(f"query: {query}")
    print(f"results: {len(results)}")
    print()
    for result in results:
        metadata = result.get("metadata") or {}
        score = result.get("rerank_score", result.get("fusion_score", result.get("score", 0.0)))
        print(f"- score={score:.4f} {result.get('chunk_id')} {result.get('source_type')} {result.get('title')}")
        print(f"  retrieval_type: {result.get('retrieval_type')}")
        print(f"  recall_sources: {result.get('recall_sources')}")
        print(f"  source_file: {result.get('source_file')}")
        if metadata.get("project") or metadata.get("feature"):
            print(f"  project/feature: {metadata.get('project')} / {metadata.get('feature')}")
        print(f"  content: {preview(result.get('content') or '')}")


def preview(text: str, max_chars: int = 180) -> str:
    text = " ".join((text or "").split())
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}..."


def main() -> None:
    results = hybrid_search(QUERY)
    print_results(QUERY, results)


if __name__ == "__main__":
    main()
