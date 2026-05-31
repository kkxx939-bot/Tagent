# 负责 Memory 命中质量相关字段
from __future__ import annotations

from typing import Any


def build_memory_observation(session_memory: dict[str, Any]) -> dict[str, Any]:
    memories = session_memory.get("relevant_long_term_memories") if isinstance(session_memory, dict) else []
    if not isinstance(memories, list):
        memories = []

    type_counts: dict[str, int] = {}
    traceable = 0
    for memory in memories:
        if not isinstance(memory, dict):
            continue
        memory_type = str(memory.get("memory_type") or "unknown")
        type_counts[memory_type] = type_counts.get(memory_type, 0) + 1
        if memory.get("memory_id") or memory.get("source"):
            traceable += 1

    return {
        "memory_hit_count": len(memories),
        "useful_memory_hit_count": None,
        "memory_precision": None,
        "quality_evaluation": "not_evaluated",
        "memory_type_counts": type_counts,
        "traceable_memory_count": traceable,
        "traceable_memory_rate": _rate(traceable, len(memories)),
    }


def _rate(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(count / total, 4)
