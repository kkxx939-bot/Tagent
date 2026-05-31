# 负责 LLM usage 汇总
from __future__ import annotations

from typing import Any


def build_llm_observation(llm_usage: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    calls = llm_usage or []
    return {
        "calls": calls,
        "total": _sum_llm_usage(calls),
    }


def _sum_llm_usage(usages: list[dict[str, Any]]) -> dict[str, int]:
    total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for item in usages:
        usage = item.get("usage") if isinstance(item, dict) else None
        if not isinstance(usage, dict):
            continue
        for key in total:
            value = usage.get(key)
            if isinstance(value, int):
                total[key] += value
    return total
