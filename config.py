"""Tagent 项目配置。

这里放项目里会反复用到的路径、检索参数和 LLM 参数。
"""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent

DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR
PROCESSED_DIR = DATA_DIR / "processed"
MODEL_DIR = DATA_DIR / "model"
GENERATED_DIR = DATA_DIR / "generated"

REQUIREMENTS_DIR = DATA_DIR / "requirements"
TEST_CASES_DIR = DATA_DIR / "test_cases"
BUGS_DIR = DATA_DIR / "bugs"
API_DOCS_DIR = DATA_DIR / "api_docs"

CASE_ITEMS_PATH = PROCESSED_DIR / "case_items.jsonl"
REQUIREMENT_ITEMS_PATH = PROCESSED_DIR / "requirement_items.jsonl"
BUG_ITEMS_PATH = PROCESSED_DIR / "bug_items.jsonl"
API_ITEMS_PATH = PROCESSED_DIR / "api_items.jsonl"
QUALITY_REPORT_PATH = PROCESSED_DIR / "quality_report.json"
KNOWLEDGE_CHUNKS_PATH = PROCESSED_DIR / "knowledge_chunks.jsonl"
EMBEDDING_INDEX_PATH = PROCESSED_DIR / "embedding_index.npz"

EMBEDDING_MODEL_PATH = MODEL_DIR / "text2vec-base-chinese"
RERANK_MODEL_PATH = MODEL_DIR / "bge-reranker-large"

DEFAULT_QUERY = "租房"


BM25_TOP_K = 30
VECTOR_TOP_K = 30
RERANK_TOP_K = 10
FINAL_TOP_K = 4
BM25_MIN_SCORE = 0.01
VECTOR_MIN_SCORE = 0.0

CHUNK_MAX_CHARS = 800
CHUNK_OVERLAP_CHARS = 120

CONTEXT_SEARCH_MODE = "bm25"
CONTEXT_SOURCE_LIMITS = {
    "requirement": 4,
    "case": 4,
    "bug": 2,
    "api": 2,
}
CONTEXT_MAX_CONTENT_CHARS = 700

LLM_BASE_URL = "https://api.deepseek.com"
LLM_MODEL = "deepseek-v4-flash"
LLM_TEMPERATURE = 0.2
LLM_MAX_TOKENS = 4096
APIKEY = ""


def get_llm_config() -> dict[str, str | int | float | None]:
    """返回 LLM 调用需要的配置。"""
    return {
        "base_url": os.getenv("LLM_BASE_URL", LLM_BASE_URL),
        "api_key": os.getenv("LLM_API_KEY") or APIKEY or None,
        "model": os.getenv("LLM_MODEL", LLM_MODEL),
        "temperature": float(os.getenv("LLM_TEMPERATURE", str(LLM_TEMPERATURE))),
        "max_tokens": int(os.getenv("LLM_MAX_TOKENS", str(LLM_MAX_TOKENS))),
    }


def require_llm_api_key() -> str:
    """需要真正调用 LLM 时，用这个函数检查 API Key 是否存在。"""
    api_key = get_llm_config().get("api_key")
    if not api_key:
        raise RuntimeError("缺少 LLM_API_KEY，请先配置环境变量，或临时在 config.py 的 APIKEY 中填写。")
    return str(api_key)


def ensure_output_dirs() -> None:
    """创建运行时输出目录。"""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
