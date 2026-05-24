"""面向 knowledge_chunks.jsonl 的轻量 BM25 检索。"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHUNKS_PATH = PROJECT_ROOT / "data" / "processed" / "knowledge_chunks.jsonl"

QUERY = "租房"
TOP_K = 1
SOURCE_TYPE = None  # 可选："case" / "requirement" / "bug" / "api"
MIN_SCORE = 0.01

# TODO: 第一版框架稳定后，调研 OpenViking 作为 Agent 上下文数据库，
#       对比当前 BM25 / 后续 hybrid search 在上下文组织和召回效果上的差异。


@dataclass
class SearchResult:
    score: float
    chunk: dict[str, Any]
    matched_terms: list[str]


def load_chunks(path: Path) -> list[dict[str, Any]]:
    """读取已生成的 chunk。"""
    chunks: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    return chunks


def tokenize(text: str) -> list[str]:
    """给中英文混合文本做 BM25 分词。"""
    text = (text or "").lower()
    ascii_tokens = re.findall(r"[a-z0-9_/-]+", text)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    chinese_bigrams = ["".join(chinese_chars[index : index + 2]) for index in range(len(chinese_chars) - 1)]
    chinese_singletons = chinese_chars if len(chinese_chars) <= 2 else []
    return ascii_tokens + chinese_bigrams + chinese_singletons


def chunk_search_text(chunk: dict[str, Any]) -> str:
    """拼出检索索引用的文本。"""
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
        chunk.get("chunk_id"),
        chunk.get("source_type"),
        chunk.get("item_type"),
        chunk.get("chunk_type"),
        chunk.get("source_file"),
        chunk.get("title"),
        chunk.get("content"),
        " ".join(metadata_parts),
    ]
    return "\n".join(str(part) for part in parts if part)


class BM25Index:
    """内存版 BM25 索引，够当前本地检索使用。"""

    def __init__(self, chunks: list[dict[str, Any]], k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self.doc_tokens: list[list[str]] = []
        self.doc_term_counts: list[Counter[str]] = []
        self.doc_lengths: list[int] = []
        self.document_frequency: Counter[str] = Counter()
        self.average_doc_length = 0.0
        self._build()

    def _build(self) -> None:
        total_length = 0
        for chunk in self.chunks:
            tokens = tokenize(chunk_search_text(chunk))
            term_counts = Counter(tokens)
            self.doc_tokens.append(tokens)
            self.doc_term_counts.append(term_counts)
            self.doc_lengths.append(len(tokens))
            self.document_frequency.update(set(tokens))
            total_length += len(tokens)
        self.average_doc_length = total_length / len(self.chunks) if self.chunks else 0.0

    def idf(self, term: str) -> float:
        doc_count = len(self.chunks)
        df = self.document_frequency.get(term, 0)
        if df == 0:
            return 0.0
        return math.log(1 + (doc_count - df + 0.5) / (df + 0.5))

    def score(self, query_tokens: list[str], doc_index: int) -> float:
        score = 0.0
        term_counts = self.doc_term_counts[doc_index]
        doc_length = self.doc_lengths[doc_index]
        if doc_length == 0 or self.average_doc_length == 0:
            return 0.0

        for term in query_tokens:
            tf = term_counts.get(term, 0)
            if tf == 0:
                continue
            idf = self.idf(term)
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * doc_length / self.average_doc_length)
            score += idf * numerator / denominator
        return score

    def search(self, query: str, top_k: int = 20, source_type: str | None = None, min_score: float = 0.01) -> list[SearchResult]:
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        results: list[SearchResult] = []
        unique_query_tokens = sorted(set(query_tokens))
        for index, chunk in enumerate(self.chunks):
            if source_type and chunk.get("source_type") != source_type:
                continue
            score = self.score(query_tokens, index)
            if score < min_score:
                continue
            matched_terms = [term for term in unique_query_tokens if term in self.doc_term_counts[index]]
            results.append(SearchResult(score=score, chunk=chunk, matched_terms=matched_terms))

        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]


def search_knowledge(
    query: str,
    chunks_path: Path = DEFAULT_CHUNKS_PATH,
    top_k: int = TOP_K,
    source_type: str | None = SOURCE_TYPE,
    min_score: float = MIN_SCORE,
) -> list[dict[str, Any]]:
    chunks = load_chunks(chunks_path)
    index = BM25Index(chunks)
    results = index.search(query, top_k=top_k, source_type=source_type, min_score=min_score)
    return [result_to_dict(result) for result in results]


def result_to_dict(result: SearchResult) -> dict[str, Any]:
    chunk = result.chunk
    metadata = chunk.get("metadata") or {}
    return {
        "score": round(result.score, 4),
        "chunk_id": chunk.get("chunk_id"),
        "source_type": chunk.get("source_type"),
        "item_type": chunk.get("item_type"),
        "chunk_type": chunk.get("chunk_type"),
        "source_file": chunk.get("source_file"),
        "title": chunk.get("title"),
        "content": chunk.get("content"),
        "metadata": metadata,
        "matched_terms": result.matched_terms,
    }


def group_results(results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[result.get("source_type") or "unknown"].append(result)
    return dict(grouped)


def preview(text: str, max_chars: int = 180) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}..."


def print_results(query: str, results: list[dict[str, Any]], grouped: bool = True) -> None:
    if not results:
        print(f"query: {query}")
        print("confidence: low")
        print("未找到足够相关的 chunk。建议补充需求、用例、Bug 或 API 资料，或换一个更具体的关键词。")
        return

    print(f"query: {query}")
    print(f"results: {len(results)}")
    print()

    if grouped:
        for source_type, group in group_results(results).items():
            print(f"[{source_type}]")
            for result in group:
                print_one_result(result)
            print()
    else:
        for result in results:
            print_one_result(result)


def print_one_result(result: dict[str, Any]) -> None:
    metadata = result.get("metadata") or {}
    print(f"- score={result.get('score'):.4f} {result.get('chunk_id')} {result.get('chunk_type')} {result.get('title')}")
    print(f"  source_file: {result.get('source_file')}")
    if metadata.get("project") or metadata.get("feature"):
        print(f"  project/feature: {metadata.get('project')} / {metadata.get('feature')}")
    matched_terms = result.get("matched_terms") or []
    if matched_terms:
        print(f"  matched_terms: {', '.join(matched_terms[:12])}")
    print(f"  content: {preview(result.get('content') or '')}")
    print(f"  metadata: {json.dumps(metadata, ensure_ascii=False)}")


def main() -> None:
    results = search_knowledge(QUERY)
    print_results(QUERY, results, grouped=True)

if __name__ == "__main__":
    main()
