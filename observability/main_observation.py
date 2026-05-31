from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESULT_DIR = ROOT / "result"
RECORD_PATH = RESULT_DIR / "main_observation_records.json"
COMPARE_DIR = RESULT_DIR / "main_compare"


def record_main_run(result: dict[str, Any], mode: str) -> None:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    records = load_records()
    query = str(result.get("user_query") or "")
    query_record = find_or_create_record(records, query)
    query_record[mode] = build_run_summary(result, mode)
    query_record["updated_at"] = datetime.now().isoformat(timespec="seconds")
    write_json(RECORD_PATH, records)
    write_query_compare(query_record)


def load_records() -> list[dict[str, Any]]:
    if not RECORD_PATH.exists():
        return []
    try:
        data = json.loads(RECORD_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def find_or_create_record(records: list[dict[str, Any]], query: str) -> dict[str, Any]:
    for record in records:
        if record.get("query") == query and record.get("dimension") == "main":
            return record
    record = {
        "dimension": "main",
        "query": query,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": None,
        "native_rag": None,
        "openviking": None,
    }
    records.append(record)
    return record


def build_run_summary(result: dict[str, Any], mode: str) -> dict[str, Any]:
    final_output = result.get("final_output") or {}
    intent_result = result.get("intent_result") or {}
    observability = ((result.get("metadata") or {}).get("observability")) or {}
    context = observability.get("context") or {}
    token = observability.get("token") or {}
    memory = observability.get("memory") or {}
    llm = observability.get("llm") or {}
    return {
        "mode": mode,
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        "success": result.get("success"),
        "status": result.get("status") or final_output.get("status"),
        "intent": intent_result.get("intent") or final_output.get("intent"),
        "backend": extract_backend(result),
        "normalized_query": ((result.get("query_context") or {}).get("normalized_query")),
        "source_summary": final_output.get("summary", {}).get("source_summary"),
        "estimated_total_tokens": token.get("estimated_total_tokens"),
        "estimated_context_tokens": token.get("estimated_context_tokens"),
        "context_count": (context.get("traceability") or {}).get("context_count"),
        "noise_context_rate": (context.get("noise") or {}).get("noise_context_rate"),
        "traceable_context_rate": (context.get("traceability") or {}).get("traceable_context_rate"),
        "load_context_total_ms": (context.get("latency") or {}).get("load_context_total_ms"),
        "memory_hit_count": memory.get("memory_hit_count"),
        "llm_total_tokens": (llm.get("total") or {}).get("total_tokens"),
        "error": result.get("error"),
        "warnings": result.get("warnings") or final_output.get("warnings") or [],
    }


def extract_backend(result: dict[str, Any]) -> str | None:
    execution_result = result.get("execution_result") or {}
    for step in execution_result.get("step_results") or []:
        data = step.get("data") or {}
        if data.get("backend"):
            return str(data.get("backend"))
    return None


def write_query_compare(record: dict[str, Any]) -> None:
    query_dir = COMPARE_DIR / slugify(str(record.get("query") or "empty_query"))
    query_dir.mkdir(parents=True, exist_ok=True)
    write_json(query_dir / "compare.json", record)
    write_compare_csv(query_dir / "compare.csv", record)
    write_index()


def write_compare_csv(path: Path, record: dict[str, Any]) -> None:
    rows = []
    native = record.get("native_rag") or {}
    openviking = record.get("openviking") or {}
    for key, label in metric_fields():
        rows.append(
            {
                "metric": key,
                "label": label,
                "native_rag": native.get(key),
                "openviking": openviking.get(key),
            }
        )
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["metric", "label", "native_rag", "openviking"])
        writer.writeheader()
        writer.writerows(rows)


def write_index() -> None:
    records = load_records()
    COMPARE_DIR.mkdir(parents=True, exist_ok=True)
    index = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "description": "main.py 维度的运行记录；native_rag 或 openviking 未执行时对应字段为空。",
        "files": [
            {
                "query": record.get("query"),
                "file": f"main_compare/{slugify(str(record.get('query') or 'empty_query'))}/compare.json",
                "table_file": f"main_compare/{slugify(str(record.get('query') or 'empty_query'))}/compare.csv",
            }
            for record in records
            if record.get("dimension") == "main"
        ],
    }
    write_json(COMPARE_DIR / "index.json", index)


def metric_fields() -> list[tuple[str, str]]:
    return [
        ("status", "执行状态"),
        ("success", "是否成功"),
        ("intent", "识别意图"),
        ("backend", "上下文后端"),
        ("estimated_total_tokens", "总 Token 估算"),
        ("estimated_context_tokens", "上下文 Token 估算"),
        ("context_count", "上下文条数"),
        ("noise_context_rate", "噪声比例"),
        ("traceable_context_rate", "上下文可追踪率"),
        ("load_context_total_ms", "上下文加载耗时 ms"),
        ("memory_hit_count", "Memory 命中数"),
        ("llm_total_tokens", "LLM Token"),
        ("error", "错误"),
    ]


def slugify(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^0-9a-zA-Z_\-\u4e00-\u9fff]+", "_", text)
    text = text.strip("_")
    return text[:80] or "empty_query"


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
