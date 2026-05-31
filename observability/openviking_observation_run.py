from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    args = parse_args()
    os.environ.setdefault("CONTEXT_BACKEND", "openviking")
    os.environ.setdefault("OPENVIKING_URL", "http://localhost:1933")
    os.environ.setdefault("OPENVIKING_TARGET_URI", "viking://resources/tagent")
    os.environ.setdefault("OPENVIKING_ACCOUNT", "default")
    os.environ.setdefault("OPENVIKING_USER", "tagent")
    os.environ.setdefault("OPENVIKING_SEARCH_MODE", "find")

    from agent.orchestrator import run_agent

    baseline = load_json(args.baseline)
    cases = []
    for source_case in baseline.get("cases") or []:
        query = str(source_case.get("query") or "").strip()
        if not query:
            continue
        result = run_agent(query).to_dict()
        observation = (((result.get("metadata") or {}).get("observability")) or {})
        cases.append(build_case(source_case, result, observation))

    report = {
        "report_type": "openviking_comparison_after",
        "backend": "openviking",
        "openviking_enabled": True,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "llm_enabled": os.getenv("TAGENT_EVAL_ALLOW_LLM", "").lower() in {"1", "true", "yes"},
        "summary": summarize_cases(cases),
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": True, "output": str(args.output), "summary": report["summary"]}, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="跑 OpenViking 接入后的 Tagent 观测。")
    parser.add_argument("--baseline", type=Path, default=ROOT / "result/openviking_observation_baseline_local.json")
    parser.add_argument("--output", type=Path, default=ROOT / "result/openviking_observation_after_openviking.json")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_case(source_case: dict[str, Any], result: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    final_output = result.get("final_output") or {}
    context = observation.get("context") or {}
    context_noise = context.get("noise") or {}
    context_traceability = context.get("traceability") or {}
    context_latency = context.get("latency") or {}
    token = observation.get("token") or {}
    memory = observation.get("memory") or {}
    latency = observation.get("latency") or {}
    return {
        "case_id": source_case.get("case_id"),
        "query": source_case.get("query"),
        "status": result.get("status") or final_output.get("status"),
        "intent": result.get("intent_result", {}).get("intent") or final_output.get("intent"),
        "token": token,
        "noise": {
            "context_count": context_traceability.get("context_count"),
            "noise_context_count": context_noise.get("noise_context_count"),
            "noise_context_rate": context_noise.get("noise_context_rate"),
            "cross_project_context_count": context_noise.get("cross_project_context_count"),
            "cross_project_context_rate": context_noise.get("cross_project_context_rate"),
            "noise_scorable_context_count": context_traceability.get("context_count")
            if context_noise.get("noise_context_count") is not None
            else 0,
            "cross_project_scorable_context_count": context_traceability.get("context_count")
            if context_noise.get("cross_project_context_count") is not None
            else 0,
        },
        "traceability": {
            "traceable_context_count": context_traceability.get("traceable_context_count"),
            "traceable_context_rate": context_traceability.get("traceable_context_rate"),
        },
        "memory": memory,
        "latency": {
            **latency,
            "load_context_ms": context_latency.get("load_context_total_ms", latency.get("load_context_ms")),
        },
    }


def summarize_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "case_count": len(cases),
        "status_distribution": count_by(cases, "status"),
        "intent_distribution": count_by(cases, "intent"),
    }
    summary.update(sum_metric(cases))
    return summary


def count_by(cases: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in cases:
        value = str(case.get(key) or "UNKNOWN")
        counts[value] = counts.get(value, 0) + 1
    return counts


def sum_metric(cases: list[dict[str, Any]]) -> dict[str, Any]:
    total_tokens = 0
    context_tokens = 0
    context_count = 0
    noise_count = 0
    traceable_count = 0
    memory_hit_count = 0
    load_context_ms = 0.0
    noise_scorable_count = 0
    cross_project_scorable_count = 0
    cross_project_count = 0

    for case in cases:
        token = case.get("token") or {}
        noise = case.get("noise") or {}
        traceability = case.get("traceability") or {}
        memory = case.get("memory") or {}
        latency = case.get("latency") or {}
        total_tokens += int(token.get("estimated_total_tokens") or 0)
        context_tokens += int(token.get("estimated_context_tokens") or 0)
        context_count += int(noise.get("context_count") or 0)
        noise_count += int(noise.get("noise_context_count") or 0)
        traceable_count += int(traceability.get("traceable_context_count") or 0)
        memory_hit_count += int(memory.get("memory_hit_count") or 0)
        load_context_ms += float(latency.get("load_context_ms") or 0)
        noise_scorable_count += int(noise.get("noise_scorable_context_count") or 0)
        cross_project_scorable_count += int(noise.get("cross_project_scorable_context_count") or 0)
        cross_project_count += int(noise.get("cross_project_context_count") or 0)

    return {
        "estimated_total_tokens": total_tokens,
        "estimated_context_tokens": context_tokens,
        "context_count": context_count,
        "noise_context_count": noise_count,
        "noise_context_rate": round(noise_count / noise_scorable_count, 4) if noise_scorable_count else None,
        "cross_project_context_count": cross_project_count if cross_project_scorable_count else None,
        "cross_project_context_rate": round(cross_project_count / cross_project_scorable_count, 4)
        if cross_project_scorable_count
        else None,
        "traceable_context_count": traceable_count,
        "traceable_context_rate": round(traceable_count / context_count, 4) if context_count else None,
        "memory_hit_count": memory_hit_count,
        "load_context_total_ms": round(load_context_ms, 2),
        "noise_scorable_context_count": noise_scorable_count,
        "cross_project_scorable_context_count": cross_project_scorable_count,
    }


if __name__ == "__main__":
    raise SystemExit(main())
