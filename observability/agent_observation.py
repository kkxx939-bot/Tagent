# 只做总装，不放具体指标逻辑
from __future__ import annotations


from typing import Any

from observability.context_observation import build_context_observation
from observability.llm_observation import build_llm_observation
from observability.memory_observation import build_memory_observation
from observability.token_observation import build_token_observation


def build_agent_observation(
    *,
    user_query: str,
    normalized_query: str,
    query_context: dict[str, Any],
    source_context: dict[str, Any],
    intent_result: dict[str, Any],
    selected_skill: dict[str, Any] | None,
    plan: dict[str, Any] | None,
    execution_result: dict[str, Any] | None,
    final_output: dict[str, Any],
    context_trace: list[dict[str, Any]] | None = None,
    llm_usage: list[dict[str, Any]] | None = None,
    session_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trace = context_trace or []
    return {
        "token": build_token_observation(
            user_query=user_query,
            normalized_query=normalized_query,
            query_context=query_context,
            source_context=source_context,
            intent_result=intent_result,
            selected_skill=selected_skill,
            plan=plan,
            execution_result=execution_result,
            final_output=final_output,
            context_trace=trace,
        ),
        "context": build_context_observation(
            trace,
            query_context=query_context,
            source_context=source_context,
            intent_result=intent_result,
        ),
        "memory": build_memory_observation(session_memory or {}),
        "llm": build_llm_observation(llm_usage),
        "context_trace": trace,
    }
