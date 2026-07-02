"""Agent 主编排入口。

Orchestrator 只负责把各层串起来，不承载具体业务逻辑。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from Intent.main_intent_route import recognize_main_intent
from OTel.OTelClient import mark_span_error, mark_span_ok, set_span_attributes, start_span
from OTel.TraceScheme import (
    SPAN_AGENT_RUN,
    SPAN_EXECUTOR_RUN,
    SPAN_INTENT_RECOGNIZE,
    SPAN_PLANNER_BUILD,
    SPAN_QUERY_NORMALIZE,
    SPAN_RESULT_BUILD,
    SPAN_SKILL_SELECT,
    SPAN_SOURCE_PROCESS,
    build_agent_run_result_attributes,
    build_agent_run_start_attributes,
    build_executor_run_attributes,
    build_intent_recognize_attributes,
    build_planner_build_attributes,
    build_query_normalize_attributes,
    build_result_build_attributes,
    build_skill_select_attributes,
    build_source_process_attributes,
)
from agent.result import AgentResult
from executor import Executor, ReactExecutor, should_use_react
from filework.queryfile import process_query_sources
from memory.MemoryManager import MemoryManager
from observability import build_agent_observation
from planner.model_planner import build_plan
from query_processing import normalize_query
from skills.registry import get_skill

try:
    from llm_client import consume_llm_usage_log
except ModuleNotFoundError:
    consume_llm_usage_log = None


def run_agent(
    user_query: str,
    memory_manager: MemoryManager | None = None,
    planner_strategy: str = "hybrid",
    memory_data_dir: str | Path | None = None,
) -> AgentResult:
    """运行一次完整 Agent 链路，并记录 root span。"""
    with start_span(
        SPAN_AGENT_RUN,
        build_agent_run_start_attributes(user_query, planner_strategy),
    ) as span:
        result = _run_agent_impl(
            user_query=user_query,
            memory_manager=memory_manager,
            planner_strategy=planner_strategy,
            memory_data_dir=memory_data_dir,
        )
        _record_agent_run_span_result(span, result)
        if result.success:
            mark_span_ok(span)
        else:
            mark_span_error(span, result.error)
        return result


def _run_agent_impl(
    user_query: str,
    memory_manager: MemoryManager | None = None,
    planner_strategy: str = "hybrid",
    memory_data_dir: str | Path | None = None,
) -> AgentResult:
    """运行一次完整 Agent 链路。"""
    _consume_llm_usage()
    manager = memory_manager or MemoryManager(data_dir=memory_data_dir)
    with start_span(SPAN_QUERY_NORMALIZE) as span:
        query_context = normalize_query(user_query)
        set_span_attributes(span, build_query_normalize_attributes(query_context.to_dict()))
        mark_span_ok(span)
    normalized_query = query_context.normalized_query
    with start_span(SPAN_SOURCE_PROCESS) as span:
        source_context = process_query_sources(normalized_query)
        set_span_attributes(span, build_source_process_attributes(source_context.to_dict()))
        mark_span_ok(span)
    source_context_dict = source_context.to_dict()
    query_context_dict = query_context.to_dict()
    if source_context.has_source:
        query_context_dict["source_context"] = _public_source_context(source_context_dict)
        query_context_dict.setdefault("warnings", []).extend(source_context.warnings)
    session = manager.start_task(
        user_query=user_query,
        metadata={"query_context": query_context_dict},
        memory_query=normalized_query,
    )

    intent_result: dict[str, Any] = {}
    selected_skill: dict[str, Any] | None = None
    plan_dict: dict[str, Any] | None = None
    execution_dict: dict[str, Any] | None = None
    final_output: dict[str, Any] = {}
    warnings: list[str] = []
    warnings.extend(source_context.warnings)

    try:
        with start_span(SPAN_INTENT_RECOGNIZE) as span:
            intent_result = recognize_main_intent(normalized_query)
            _merge_query_context(intent_result, query_context_dict)
            _merge_source_context(intent_result, source_context_dict)
            set_span_attributes(span, build_intent_recognize_attributes(intent_result))
            mark_span_ok(span)
        if _should_wait_for_source_action(intent_result, source_context_dict) or _should_wait_for_incompatible_case_source(
            intent_result, source_context_dict
        ):
            final_output = _source_waiting_output(intent_result, source_context_dict)
            manager.set_intent_result(intent_result)
            return _build_agent_result_with_span(
                user_query=user_query,
                success=True,
                status="waiting_for_user",
                intent_result=intent_result,
                selected_skill=None,
                plan=None,
                execution_result=None,
                final_output=final_output,
                query_context=query_context_dict,
                warnings=_dedupe([*warnings, *source_context.warnings, *(final_output.get("warnings") or [])]),
                metadata={
                    "session_id": session.session_id,
                    "normalized_query": normalized_query,
                    "source_profile": source_context.source_profile,
                    "observability": _build_observability(
                        user_query=user_query,
                        normalized_query=normalized_query,
                        query_context=query_context_dict,
                        source_context=source_context_dict,
                        intent_result=intent_result,
                        selected_skill=None,
                        plan=None,
                        execution_result=None,
                        final_output=final_output,
                        session_memory=session.to_dict(),
                    ),
                },
            )
        manager.set_intent_result(intent_result)

        with start_span(SPAN_SKILL_SELECT) as span:
            selected_skill = _select_skill(intent_result)
            if selected_skill:
                manager.set_selected_skill(selected_skill)
            set_span_attributes(span, build_skill_select_attributes(selected_skill, intent_result))
            mark_span_ok(span)

        if should_use_react(str(intent_result.get("intent") or "")):
            session_memory_before_execution = session.to_dict()
            react_executor = ReactExecutor(
                user_query=normalized_query,
                intent_result=intent_result,
                selected_skill=selected_skill,
                memory_manager=manager,
                execution_context={
                    "query_context": query_context_dict,
                    "source_context": source_context_dict,
                    "raw_user_query": user_query,
                },
            )
            with start_span(SPAN_EXECUTOR_RUN) as span:
                execution_result = react_executor.run()
                plan_dict = react_executor.plan.to_dict()
                set_span_attributes(span, build_executor_run_attributes(execution_result.to_dict(), plan_dict))
                if execution_result.success:
                    mark_span_ok(span)
                else:
                    mark_span_error(span, execution_result.error)
            execution_dict = execution_result.to_dict()
            final_output = execution_result.final_output
            warnings.extend(final_output.get("warnings") or [])
            _finalize_memory_from_execution(manager, execution_result)

            return _build_agent_result_with_span(
                user_query=user_query,
                success=execution_result.success,
                status=str(final_output.get("status") or ("completed" if execution_result.success else "failed")),
                intent_result=intent_result,
                selected_skill=selected_skill,
                plan=plan_dict,
                execution_result=execution_dict,
                final_output=final_output,
                query_context=query_context_dict,
                error=execution_result.error,
                warnings=_dedupe(warnings),
                metadata={
                    "session_id": session.session_id,
                    "planner_source": "react",
                    "normalized_query": normalized_query,
                    "source_profile": source_context.source_profile,
                    "observability": _build_observability(
                        user_query=user_query,
                        normalized_query=normalized_query,
                        query_context=query_context_dict,
                        source_context=source_context_dict,
                        intent_result=intent_result,
                        selected_skill=selected_skill,
                        plan=plan_dict,
                        execution_result=execution_dict,
                        final_output=final_output,
                        session_memory=session_memory_before_execution,
                    ),
                },
            )

        with start_span(SPAN_PLANNER_BUILD) as span:
            plan = build_plan(
                user_query=normalized_query,
                intent_result=intent_result,
                selected_skill=selected_skill,
                session_memory=session.to_dict(),
                strategy=planner_strategy,
            )
            set_span_attributes(span, build_planner_build_attributes(plan.to_dict(), planner_strategy))
            mark_span_ok(span)
        warnings.extend(plan.warnings)

        session_memory_before_execution = session.to_dict()
        plan_dict = plan.to_dict()
        with start_span(SPAN_EXECUTOR_RUN) as span:
            execution_result = Executor(
                user_query=normalized_query,
                memory_manager=manager,
                execution_context={
                    "intent_result": intent_result,
                    "selected_skill": selected_skill,
                    "query_context": query_context_dict,
                    "source_context": source_context_dict,
                    "raw_user_query": user_query,
                },
            ).run(plan)
            set_span_attributes(span, build_executor_run_attributes(execution_result.to_dict(), plan_dict))
            if execution_result.success:
                mark_span_ok(span)
            else:
                mark_span_error(span, execution_result.error)
        execution_dict = execution_result.to_dict()
        final_output = execution_result.final_output
        warnings.extend(final_output.get("warnings") or [])
        _finalize_memory_from_execution(manager, execution_result)

        return _build_agent_result_with_span(
            user_query=user_query,
            success=execution_result.success,
            status=str(final_output.get("status") or ("completed" if execution_result.success else "failed")),
            intent_result=intent_result,
            selected_skill=selected_skill,
            plan=plan_dict,
            execution_result=execution_dict,
            final_output=final_output,
            query_context=query_context_dict,
            error=execution_result.error,
            warnings=_dedupe(warnings),
            metadata={
                "session_id": session.session_id,
                "planner_source": plan.metadata.get("planner_source"),
                "normalized_query": normalized_query,
                "source_profile": source_context.source_profile,
                "observability": _build_observability(
                    user_query=user_query,
                    normalized_query=normalized_query,
                    query_context=query_context_dict,
                    source_context=source_context_dict,
                    intent_result=intent_result,
                    selected_skill=selected_skill,
                    plan=plan_dict,
                    execution_result=execution_dict,
                    final_output=final_output,
                    session_memory=session_memory_before_execution,
                ),
            },
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        _fail_memory_task(manager, error)
        return _build_agent_result_with_span(
            user_query=user_query,
            success=False,
            status="failed",
            intent_result=intent_result,
            selected_skill=selected_skill,
            plan=plan_dict,
            execution_result=execution_dict,
            final_output=final_output,
            query_context=query_context_dict,
            error=error,
            warnings=_dedupe(warnings),
            metadata={
                "session_id": session.session_id,
                "observability": _build_observability(
                    user_query=user_query,
                    normalized_query=normalized_query,
                    query_context=query_context_dict,
                    source_context=source_context_dict,
                    intent_result=intent_result,
                    selected_skill=selected_skill,
                    plan=plan_dict,
                    execution_result=execution_dict,
                    final_output=final_output,
                    session_memory=session.to_dict(),
                ),
            },
        )


def _select_skill(intent_result: dict[str, Any]) -> dict[str, Any] | None:
    intent = str(intent_result.get("intent") or "")
    skill = get_skill(intent)
    return skill.to_dict() if skill else None


def _build_agent_result_with_span(**kwargs: Any) -> AgentResult:
    """构建 AgentResult，并记录最终结果摘要 span。"""

    with start_span(SPAN_RESULT_BUILD) as span:
        result = AgentResult(**kwargs)
        set_span_attributes(span, build_result_build_attributes(result.to_dict()))
        if result.success:
            mark_span_ok(span)
        else:
            mark_span_error(span, result.error)
        return result


def _record_agent_run_span_result(span: Any, result: AgentResult) -> None:
    result_dict = result.to_dict()
    metadata = result_dict.get("metadata") or {}
    query_context = result_dict.get("query_context") or {}
    source_context = query_context.get("source_context") or {}
    set_span_attributes(
        span,
        build_agent_run_result_attributes(
            intent_result=result_dict.get("intent_result"),
            final_output=result_dict.get("final_output"),
            session_id=metadata.get("session_id"),
            success=result_dict.get("success"),
            status=result_dict.get("status"),
            error=result_dict.get("error"),
            warnings=result_dict.get("warnings"),
            source_context=source_context,
        ),
    )


def _finalize_memory_from_execution(manager: MemoryManager, execution_result: Any) -> None:
    """确保失败/等待类执行结果不会留下悬空 session 或污染长期记忆。"""
    if not manager.get_current_session():
        return

    final_output = execution_result.final_output if execution_result else {}
    status = str((final_output or {}).get("status") or "")
    if execution_result and execution_result.success and status == "completed":
        return

    persist_summary = False
    try:
        if execution_result and execution_result.success:
            manager.complete_task(
                summary="Executor 未完成可复用结果",
                final_status=status or "partial_completed",
                final_output=final_output,
                persist_summary=persist_summary,
                persist_async=False,
            )
        else:
            manager.fail_task(
                reason=str(getattr(execution_result, "error", None) or "execution failed"),
                final_output=final_output,
                persist_summary=persist_summary,
            )
    except RuntimeError:
        return


def _merge_query_context(intent_result: dict[str, Any], query_context: dict[str, Any]) -> None:
    extracted = intent_result.setdefault("extracted_context", {})
    if not isinstance(extracted, dict):
        return

    normalized_extracted = query_context.get("extracted_context") or {}
    if not isinstance(normalized_extracted, dict):
        return

    for key in ("target", "frameworks", "source_refs"):
        existing = extracted.get(key) if isinstance(extracted.get(key), list) else []
        incoming = normalized_extracted.get(key) if isinstance(normalized_extracted.get(key), list) else []
        extracted[key] = _dedupe([*existing, *incoming])

    if normalized_extracted.get("trace_id") and not extracted.get("trace_id"):
        extracted["trace_id"] = normalized_extracted["trace_id"]
    if normalized_extracted.get("force_source_generation"):
        extracted["force_source_generation"] = True
    intent_result["normalized_query"] = query_context.get("normalized_query")
    intent_result["raw_query"] = query_context.get("raw_query")


def _merge_source_context(intent_result: dict[str, Any], source_context: dict[str, Any]) -> None:
    profile = source_context.get("source_profile") if isinstance(source_context, dict) else None
    if not isinstance(profile, dict):
        return

    intent_result["source_profile"] = profile
    intent_result["source_document_available"] = bool(source_context.get("document_context"))
    extracted = intent_result.setdefault("extracted_context", {})
    if not isinstance(extracted, dict):
        return

    refs = source_context.get("source_refs")
    if isinstance(refs, list):
        existing_refs = extracted.get("source_refs") if isinstance(extracted.get("source_refs"), list) else []
        extracted["source_refs"] = _dedupe([*existing_refs, *refs])

    source_type = str(profile.get("source_type") or "")
    force_source_generation = _force_source_generation(intent_result)
    if force_source_generation:
        intent_result["force_source_generation"] = True
    existing_targets = extracted.get("target") if isinstance(extracted.get("target"), list) else []
    target_hints = []
    if _source_allows_case_generation(profile) or source_type == "log_trace" or force_source_generation:
        for key in ("domain", "module"):
            if profile.get(key):
                target_hints.append(str(profile[key]))
        target_hints.extend(str(item) for item in profile.get("key_topics") or [] if item)
    extracted["target"] = _dedupe([*existing_targets, *target_hints])

    if source_type == "log_trace" and intent_result.get("intent") in {"OUT_OF_SCOPE", "CONTEXT_SEARCH", "PROJECT_QA"}:
        intent_result["intent"] = "FAILURE_TRIAGE"
        intent_result["confidence"] = max(float(intent_result.get("confidence") or 0), 0.78)
        intent_result["next_action"] = "start_failure_triage"
        intent_result["is_ready"] = True
        intent_result["missing_context"] = []
        intent_result.setdefault("evidence", []).append("Source 内容识别为日志/错误文件，转入失败排查")

    if (
        intent_result.get("intent") == "CASE_GENERATION"
        and source_context.get("document_context")
        and (_source_allows_case_generation(profile) or force_source_generation)
    ):
        intent_result["is_ready"] = True
        intent_result["missing_context"] = []
        if force_source_generation and not _source_allows_case_generation(profile):
            intent_result.setdefault("evidence", []).append("用户已明确强制基于 Source 泛化生成测试用例")
        else:
            intent_result.setdefault("evidence", []).append("已读取到可用于生成测试用例的 Source 文件")

    if (
        intent_result.get("intent") == "CASE_GENERATION"
        and source_context.get("source_refs")
        and not source_context.get("document_context")
    ):
        intent_result["is_ready"] = False
        intent_result["missing_context"] = ["可读取的 Source 文档"]
        intent_result.setdefault("evidence", []).append("识别到 Source 引用，但当前还没有可解析的文档内容")

    if (
        intent_result.get("intent") == "CASE_GENERATION"
        and source_context.get("document_context")
        and not _source_allows_case_generation(profile)
        and not force_source_generation
    ):
        intent_result["is_ready"] = False
        intent_result["missing_context"] = ["需求文档、接口文档或测试用例文件"]
        intent_result.setdefault("evidence", []).append("Source 文件已读取，但未识别为可生成测试用例的需求/API/用例文档")


def _should_wait_for_source_action(intent_result: dict[str, Any], source_context: dict[str, Any]) -> bool:
    profile = source_context.get("source_profile") if isinstance(source_context, dict) else None
    if not isinstance(profile, dict):
        return False
    if profile.get("source_type") == "log_trace":
        return False
    if profile.get("detected_actions"):
        return False
    return str(intent_result.get("intent") or "") in {"OUT_OF_SCOPE", "CONTEXT_SEARCH", "PROJECT_QA"}


def _should_wait_for_incompatible_case_source(intent_result: dict[str, Any], source_context: dict[str, Any]) -> bool:
    profile = source_context.get("source_profile") if isinstance(source_context, dict) else None
    if not isinstance(profile, dict):
        return False
    return (
        str(intent_result.get("intent") or "") == "CASE_GENERATION"
        and bool(source_context.get("document_context"))
        and not _source_allows_case_generation(profile)
        and not _force_source_generation(intent_result)
    )


def _source_allows_case_generation(profile: dict[str, Any]) -> bool:
    return str(profile.get("source_type") or "") in {"requirement_document", "api_document", "test_case_file"}


def _force_source_generation(intent_result: dict[str, Any]) -> bool:
    if intent_result.get("force_source_generation"):
        return True
    extracted = intent_result.get("extracted_context")
    return isinstance(extracted, dict) and bool(extracted.get("force_source_generation"))


def _source_waiting_output(intent_result: dict[str, Any], source_context: dict[str, Any]) -> dict[str, Any]:
    profile = source_context.get("source_profile") or {}
    source_type = profile.get("source_type") or "unknown"
    summary = profile.get("summary") or "已识别到 Source 文件，但还没有明确任务。"
    possible_actions = profile.get("possible_actions") or ["summarize_source"]
    if _should_wait_for_incompatible_case_source(intent_result, source_context):
        message = (
            f"{summary} 当前 Source 类型为 {source_type}，不是需求文档、接口文档或测试用例文件；"
            "不能可靠生成测试用例。请提供对应需求/API/用例文件，或明确确认仍按该文档泛化生成。"
        )
    else:
        message = f"{summary} 请说明下一步要做什么，例如：{_format_actions(possible_actions)}。"
    return {
        "status": "waiting_for_user",
        "intent": intent_result.get("intent") or "OUT_OF_SCOPE",
        "artifacts": [],
        "tool_results": [],
        "summary": {"source_type": source_type, "source_profile": profile},
        "missing_context": ["需要说明要基于 Source 执行什么任务"],
        "message": message,
        "capability_gap": None,
        "warnings": source_context.get("warnings") or [],
    }


def _format_actions(actions: list[str]) -> str:
    labels = {
        "generate_test_cases": "生成测试用例",
        "context_search": "检索相关资料",
        "project_qa": "做需求问答/评审",
        "failure_triage": "排查失败原因",
        "bug_report_generation": "生成 Bug 报告",
        "automation_writing": "生成自动化脚本",
        "summarize_source": "总结文档内容",
    }
    return "、".join(labels.get(action, action) for action in actions[:3])


def _public_source_context(source_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_refs": source_context.get("source_refs") or [],
        "source_profile": source_context.get("source_profile"),
        "warnings": source_context.get("warnings") or [],
    }


def _fail_memory_task(manager: MemoryManager, reason: str) -> None:
    if not manager.get_current_session():
        return
    try:
        manager.fail_task(reason=reason)
    except Exception:
        return


def _build_observability(
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
    session_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_agent_observation(
        user_query=user_query,
        normalized_query=normalized_query,
        query_context=query_context,
        source_context=source_context,
        intent_result=intent_result,
        selected_skill=selected_skill,
        plan=plan,
        execution_result=execution_result,
        final_output=final_output,
        context_trace=final_output.get("context_trace") if isinstance(final_output, dict) else [],
        llm_usage=_consume_llm_usage(),
        session_memory=session_memory,
    )


def _consume_llm_usage() -> list[dict[str, Any]]:
    if consume_llm_usage_log is None:
        return []
    return consume_llm_usage_log()


def _dedupe(items: list[str]) -> list[str]:
    deduped = []
    for item in items:
        if item and item not in deduped:
            deduped.append(item)
    return deduped
