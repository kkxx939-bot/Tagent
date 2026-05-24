"""基于 embedding 的知识片段检索。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHUNKS_PATH = PROJECT_ROOT / "data" / "processed" / "knowledge_chunks.jsonl"
DEFAULT_MODEL_PATH = PROJECT_ROOT / "data" / "model" / "text2vec-base-chinese"
DEFAULT_INDEX_PATH = PROJECT_ROOT / "data" / "processed" / "embedding_index.npz"

QUERY = "租房"
TOP_K = 20
SOURCE_TYPE = None  # 可选："case" / "requirement" / "bug" / "api"
MIN_SCORE = 0.0
BATCH_SIZE = 32


def require_embedding_dependencies() -> tuple[Any, Any]:
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "Embedding search requires numpy and sentence-transformers. "
            "Install them in the Tagent environment first."
        ) from exc
    return np, SentenceTransformer


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


def load_chunks(path: Path = DEFAULT_CHUNKS_PATH) -> list[dict[str, Any]]:
    chunks = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    return chunks


def chunk_embedding_text(chunk: dict[str, Any]) -> str:
    metadata = chunk.get("metadata") or {}
    metadata_parts = []
    for key in (
        "project",
        "feature",
        "module",
        "method",
        "path",
        "field_name",
        "error_code",
        "severity",
        "priority",
        "status",
        "risk_hint",
        "suggested_dimension",
    ):
        value = metadata.get(key)
        if value:
            metadata_parts.append(str(value))
    for key in ("business_topics", "test_dimensions", "api_constraints"):
        value = metadata.get(key)
        if isinstance(value, list):
            metadata_parts.extend(str(item) for item in value)

    parts = [
        chunk.get("title"),
        chunk.get("content"),
        " ".join(metadata_parts),
    ]
    return "\n".join(str(part) for part in parts if part)


def load_embedding_model(model_path: Path = DEFAULT_MODEL_PATH) -> Any:
    _, SentenceTransformer = require_embedding_dependencies()
    if not model_path.exists():
        raise FileNotFoundError(f"Embedding model not found: {model_path}")
    return SentenceTransformer(str(model_path), device=choose_device())


def build_embedding_index(
    chunks_path: Path = DEFAULT_CHUNKS_PATH,
    model_path: Path = DEFAULT_MODEL_PATH,
    index_path: Path = DEFAULT_INDEX_PATH,
    batch_size: int = BATCH_SIZE,
    force: bool = False,
) -> Path:
    np, _ = require_embedding_dependencies()
    if index_path.exists() and not force:
        return index_path

    chunks = load_chunks(chunks_path)
    model = load_embedding_model(model_path)
    texts = [chunk_embedding_text(chunk) for chunk in chunks]
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    index_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        index_path,
        embeddings=embeddings.astype("float32"),
        chunk_ids=np.array([chunk.get("chunk_id") or "" for chunk in chunks]),
        model_path=str(model_path),
        chunks_path=str(chunks_path),
    )
    return index_path


def load_embedding_index(index_path: Path = DEFAULT_INDEX_PATH) -> tuple[Any, list[str]]:
    np, _ = require_embedding_dependencies()
    data = np.load(index_path, allow_pickle=False)
    return data["embeddings"], data["chunk_ids"].astype(str).tolist()


def chunk_to_result(chunk: dict[str, Any], score: float) -> dict[str, Any]:
    return {
        "score": round(float(score), 4),
        "retrieval_type": "embedding",
        "chunk_id": chunk.get("chunk_id"),
        "source_type": chunk.get("source_type"),
        "item_type": chunk.get("item_type"),
        "chunk_type": chunk.get("chunk_type"),
        "source_file": chunk.get("source_file"),
        "title": chunk.get("title"),
        "content": chunk.get("content"),
        "metadata": chunk.get("metadata") or {},
        "matched_terms": [],
    }


def vector_search(
    query: str,
    chunks_path: Path = DEFAULT_CHUNKS_PATH,
    model_path: Path = DEFAULT_MODEL_PATH,
    index_path: Path = DEFAULT_INDEX_PATH,
    top_k: int = TOP_K,
    source_type: str | None = SOURCE_TYPE,
    min_score: float = MIN_SCORE,
    auto_build: bool = True,
) -> list[dict[str, Any]]:
    np, _ = require_embedding_dependencies()
    if not index_path.exists():
        if not auto_build:
            raise FileNotFoundError(f"Embedding index not found: {index_path}")
        build_embedding_index(chunks_path=chunks_path, model_path=model_path, index_path=index_path)

    chunks = load_chunks(chunks_path)
    chunk_by_id = {chunk.get("chunk_id"): chunk for chunk in chunks}
    embeddings, chunk_ids = load_embedding_index(index_path)
    model = load_embedding_model(model_path)
    query_embedding = model.encode([query], normalize_embeddings=True)[0].astype("float32")
    scores = embeddings @ query_embedding

    results: list[dict[str, Any]] = []
    for index in np.argsort(scores)[::-1]:
        chunk_id = chunk_ids[int(index)]
        chunk = chunk_by_id.get(chunk_id)
        if not chunk:
            continue
        if source_type and chunk.get("source_type") != source_type:
            continue
        score = float(scores[int(index)])
        if score < min_score:
            continue
        results.append(chunk_to_result(chunk, score))
        if len(results) >= top_k:
            break
    return results


def print_results(query: str, results: list[dict[str, Any]]) -> None:
    print(f"query: {query}")
    print(f"results: {len(results)}")
    print()
    for result in results:
        metadata = result.get("metadata") or {}
        print(f"- score={result['score']:.4f} {result.get('chunk_id')} {result.get('source_type')} {result.get('title')}")
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
    results = vector_search(QUERY, top_k=TOP_K, source_type=SOURCE_TYPE, min_score=MIN_SCORE)
    print_results(QUERY, results)


if __name__ == "__main__":
    main()
