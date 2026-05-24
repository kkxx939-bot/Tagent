"""使用 cross-encoder 模型对召回的 chunk 重新排序。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from RAGwork.searchfile import search_knowledge
except ModuleNotFoundError:
    from searchfile import search_knowledge


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_PATH = PROJECT_ROOT / "data" / "model" / "bge-reranker-large"

QUERY = "租房"
RECALL_TOP_K = 30
RERANK_TOP_K = 10
BATCH_SIZE = 16


def require_rerank_dependencies() -> Any:
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:
        raise RuntimeError(
            "Rerank requires sentence-transformers. "
            "Install it in the Tagent environment first."
        ) from exc
    return CrossEncoder


def choose_device() -> str:
    try:
        import torch
    except ImportError:
        return "cpu"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def load_reranker(model_path: Path = DEFAULT_MODEL_PATH) -> Any:
    CrossEncoder = require_rerank_dependencies()
    if not model_path.exists():
        raise FileNotFoundError(f"Rerank model not found: {model_path}")
    return CrossEncoder(str(model_path), device=choose_device())


def candidate_text(result: dict[str, Any]) -> str:
    metadata = result.get("metadata") or {}
    parts = [
        result.get("title"),
        result.get("content"),
        metadata.get("project"),
        metadata.get("feature"),
        metadata.get("module"),
        " ".join(metadata.get("business_topics") or []),
        " ".join(metadata.get("test_dimensions") or []),
        " ".join(metadata.get("api_constraints") or []),
    ]
    return "\n".join(str(part) for part in parts if part)


def dedupe_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for result in results:
        chunk_id = result.get("chunk_id")
        if not chunk_id or chunk_id in seen:
            continue
        seen.add(chunk_id)
        deduped.append(result)
    return deduped


def rerank_results(
    query: str,
    results: list[dict[str, Any]],
    model_path: Path = DEFAULT_MODEL_PATH,
    top_k: int = RERANK_TOP_K,
    batch_size: int = BATCH_SIZE,
) -> list[dict[str, Any]]:
    candidates = dedupe_results(results)
    if not candidates:
        return []

    reranker = load_reranker(model_path)
    pairs = [(query, candidate_text(result)) for result in candidates]
    scores = reranker.predict(pairs, batch_size=batch_size)

    reranked = []
    for result, score in zip(candidates, scores, strict=False):
        item = dict(result)
        item["original_score"] = result.get("score")
        item["rerank_score"] = round(float(score), 4)
        item["score"] = item["rerank_score"]
        item["retrieval_type"] = f"{result.get('retrieval_type') or 'bm25'}+rerank"
        reranked.append(item)

    reranked.sort(key=lambda item: item["rerank_score"], reverse=True)
    return reranked[:top_k]


def print_results(query: str, results: list[dict[str, Any]]) -> None:
    print(f"query: {query}")
    print(f"results: {len(results)}")
    print()
    for result in results:
        metadata = result.get("metadata") or {}
        print(
            f"- rerank_score={result.get('rerank_score'):.4f} "
            f"original_score={result.get('original_score')} "
            f"{result.get('chunk_id')} {result.get('source_type')} {result.get('title')}"
        )
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
    recall_results = search_knowledge(QUERY, top_k=RECALL_TOP_K)
    results = rerank_results(QUERY, recall_results, top_k=RERANK_TOP_K)
    print_results(QUERY, results)


if __name__ == "__main__":
    main()
