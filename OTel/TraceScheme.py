"""Tagent OpenTelemetry Trace Schema 辅助模块。

这个模块不初始化 OpenTelemetry，也不导出 trace。
它只定义 Tagent 第一版 trace schema，并提供一些小函数，
把 Tagent 运行时对象转换成安全的 span attributes。

v0.1 设计规则：
- 优先覆盖 run_agent 主链路。
- 优先记录数量、状态、类型、hash、版本等摘要字段。
- 默认不记录用户原文、完整 prompt、完整模型回复、文档正文、本地文件路径、
  API key、token 或 secret。
- 每个 attribute value 都保持为 OpenTelemetry 支持的基础类型：
  str、bool、int、float，或这些类型组成的 list。
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any


SCHEMA_VERSION = "0.1"
SERVICE_NAME = "tagent"
AGENT_NAME = "Tagent"


SPAN_AGENT_RUN = "tagent.agent_run"
SPAN_QUERY_NORMALIZE = "tagent.query.normalize"
SPAN_SOURCE_PROCESS = "tagent.source.process"
SPAN_INTENT_RECOGNIZE = "tagent.intent.recognize"
SPAN_SKILL_SELECT = "tagent.skill.select"
SPAN_PLANNER_BUILD = "tagent.planner.build"
SPAN_EXECUTOR_RUN = "tagent.executor.run"
SPAN_RESULT_BUILD = "tagent.result.build"
SPAN_LLM_CALL = "tagent.llm.call"
SPAN_EXECUTOR_STEP = "tagent.executor.step"
SPAN_TOOL_CALL = "tagent.tool.call"


EVENT_QUERY_ALIAS_APPLIED = "tagent.query.alias_applied"
EVENT_PLANNER_FALLBACK_USED = "tagent.planner.fallback_used"
EVENT_AGENT_WAITING_FOR_USER = "tagent.agent.waiting_for_user"
EVENT_AGENT_FAILED = "tagent.agent.failed"


@dataclass(frozen=True)
class SpanSchema:
    name: str
    description: str
    attributes: tuple[str, ...]


TRACE_SPANS: tuple[SpanSchema, ...] = (
    SpanSchema(
        name=SPAN_AGENT_RUN,
        description="一次 run_agent 请求的根 span。",
        attributes=(
            "tagent.schema.version",
            "service.name",
            "agent.name",
            "agent.entrypoint",
            "agent.planner_strategy",
            "request.query.length",
            "request.query.hash",
            "request.has_source",
            "agent.intent",
            "agent.status",
            "agent.success",
            "agent.session_id",
            "agent.error_type",
            "agent.warning_count",
        ),
    ),
    SpanSchema(
        name=SPAN_QUERY_NORMALIZE,
        description="标准化用户 query，并抽取轻量 query context。",
        attributes=(
            "query.raw.length",
            "query.normalized.length",
            "query.changed",
            "query.alias.count",
            "query.alias.summary",
            "query.target.count",
            "query.framework.count",
            "query.has_trace_id",
            "query.source_ref.count",
            "query.force_source_generation",
        ),
    ),
    SpanSchema(
        name=SPAN_SOURCE_PROCESS,
        description="解析本地 source 引用，并生成 source profile。",
        attributes=(
            "source.has_source",
            "source.ref.count",
            "source.ref.types",
            "source.document.available",
            "source.profile.type",
            "source.warning_count",
            "source.file.count",
            "source.file.exts",
            "source.file.exists_count",
        ),
    ),
    SpanSchema(
        name=SPAN_INTENT_RECOGNIZE,
        description="识别主业务意图。",
        attributes=(
            "intent.name",
            "intent.confidence",
            "intent.is_ready",
            "intent.next_action",
            "intent.missing_context.count",
            "intent.alternative.count",
            "intent.source",
            "intent.llm_used",
            "intent.rule_fallback_used",
        ),
    ),
    SpanSchema(
        name=SPAN_SKILL_SELECT,
        description="把识别到的 intent 映射到 Tagent skill。",
        attributes=(
            "skill.selected",
            "skill.name",
            "skill.intent",
        ),
    ),
    SpanSchema(
        name=SPAN_PLANNER_BUILD,
        description="生成可校验的执行计划。",
        attributes=(
            "planner.strategy",
            "planner.source",
            "planner.intent",
            "planner.step_count",
            "planner.is_composite",
            "planner.warning_count",
            "planner.error_type",
        ),
    ),
    SpanSchema(
        name=SPAN_EXECUTOR_RUN,
        description="通过确定性 executor 执行计划。",
        attributes=(
            "executor.plan_id",
            "executor.intent",
            "executor.step_count",
            "executor.success",
            "executor.status",
            "executor.error_type",
            "executor.warning_count",
        ),
    ),
    SpanSchema(
        name=SPAN_RESULT_BUILD,
        description="生成最终 AgentResult 摘要。",
        attributes=(
            "result.success",
            "result.status",
            "result.has_final_output",
            "result.artifact.count",
            "result.tool_result.count",
            "result.warning_count",
            "result.error_type",
        ),
    ),
    SpanSchema(
        name=SPAN_LLM_CALL,
        description="一次模型调用，不记录 prompt/response 原文。",
        attributes=(
            "llm.task",
            "llm.model",
            "llm.message_count",
            "llm.prompt_chars",
            "llm.temperature",
            "llm.max_tokens",
            "llm.success",
            "llm.error_type",
            "llm.latency_ms",
            "llm.prompt_tokens",
            "llm.completion_tokens",
            "llm.total_tokens",
        ),
    ),
    SpanSchema(
        name=SPAN_EXECUTOR_STEP,
        description="Executor 执行单个 plan step。",
        attributes=(
            "executor.plan_id",
            "executor.step.index",
            "executor.step.id",
            "executor.step.name",
            "executor.step.action",
            "executor.step.status",
            "executor.step.depends_on.count",
            "executor.step.input_key.count",
            "executor.step.tool_name",
            "executor.step.success",
            "executor.step.error_type",
            "executor.step.warning_count",
        ),
    ),
    SpanSchema(
        name=SPAN_TOOL_CALL,
        description="一次工具调用。",
        attributes=(
            "tool.name",
            "tool.exists",
            "tool.implemented",
            "tool.category",
            "tool.type",
            "tool.risk_level",
            "tool.requires_config",
            "tool.requires_permission",
            "tool.arg_count",
            "tool.success",
            "tool.error_type",
            "tool.warning_count",
            "tool.missing_config.count",
            "tool.latency_ms",
        ),
    ),
)


FORBIDDEN_BY_DEFAULT = (
    "request.query.raw",
    "request.query.normalized",
    "llm.prompt.raw",
    "llm.response.raw",
    "source.document.raw",
    "source.file.path",
    "secret.api_key",
    "secret.token",
)


def span_names() -> tuple[str, ...]:
    return tuple(span.name for span in TRACE_SPANS)


def schema_as_dict() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "service_name": SERVICE_NAME,
        "agent_name": AGENT_NAME,
        "spans": [
            {
                "name": span.name,
                "description": span.description,
                "attributes": list(span.attributes),
            }
            for span in TRACE_SPANS
        ],
        "forbidden_by_default": list(FORBIDDEN_BY_DEFAULT),
    }


def build_agent_run_start_attributes(user_query: str, planner_strategy: str) -> dict[str, Any]:
    return clean_attributes(
        {
            "tagent.schema.version": SCHEMA_VERSION,
            "service.name": SERVICE_NAME,
            "agent.name": AGENT_NAME,
            "agent.entrypoint": "run_agent",
            "agent.planner_strategy": planner_strategy,
            "request.query.length": len(user_query or ""),
            "request.query.hash": stable_hash(user_query or ""),
        }
    )


def build_agent_run_result_attributes(
    *,
    intent_result: dict[str, Any] | None = None,
    final_output: dict[str, Any] | None = None,
    session_id: str | None = None,
    success: bool | None = None,
    status: str | None = None,
    error: Any | None = None,
    warnings: list[Any] | None = None,
    source_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    final_output = final_output or {}
    intent_result = intent_result or {}
    source_context = source_context or {}
    return clean_attributes(
        {
            "request.has_source": bool(source_context.get("has_source") or source_context.get("source_refs")),
            "agent.intent": intent_result.get("intent") or final_output.get("intent"),
            "agent.status": status or final_output.get("status"),
            "agent.success": success,
            "agent.session_id": session_id,
            "agent.error_type": error_type(error),
            "agent.warning_count": len(warnings or final_output.get("warnings") or []),
        }
    )


def build_query_normalize_attributes(query_context: Any) -> dict[str, Any]:
    context = to_mapping(query_context)
    extracted = to_mapping(context.get("extracted_context"))
    aliases = as_list(context.get("aliases"))
    return clean_attributes(
        {
            "query.raw.length": len(str(context.get("raw_query") or "")),
            "query.normalized.length": len(str(context.get("normalized_query") or "")),
            "query.changed": bool(context.get("changed")),
            "query.alias.count": len(aliases),
            "query.alias.summary": alias_summary(aliases),
            "query.target.count": len(as_list(extracted.get("target"))),
            "query.framework.count": len(as_list(extracted.get("frameworks"))),
            "query.has_trace_id": bool(extracted.get("trace_id")),
            "query.source_ref.count": len(as_list(extracted.get("source_refs"))),
            "query.force_source_generation": bool(extracted.get("force_source_generation")),
        }
    )


def build_source_process_attributes(source_context: Any) -> dict[str, Any]:
    context = to_mapping(source_context)
    refs = as_list(context.get("source_refs"))
    profile = to_mapping(context.get("source_profile"))
    document_context = to_mapping(context.get("document_context"))
    return clean_attributes(
        {
            "source.has_source": bool(context.get("has_source") or refs),
            "source.ref.count": len(refs),
            "source.ref.types": comma_join(unique_values(ref.get("type") for ref in refs if isinstance(ref, dict))),
            "source.document.available": bool(document_context),
            "source.profile.type": profile.get("source_type") or profile.get("type"),
            "source.warning_count": len(as_list(context.get("warnings"))),
            "source.file.count": count_local_file_refs(refs),
            "source.file.exts": comma_join(file_extensions(refs)),
            "source.file.exists_count": count_existing_file_refs(refs),
        }
    )


def build_intent_recognize_attributes(intent_result: Any) -> dict[str, Any]:
    result = to_mapping(intent_result)
    missing_context = as_list(result.get("missing_context"))
    alternatives = as_list(result.get("alternative_intents"))
    intent_source = infer_intent_source(result)
    return clean_attributes(
        {
            "intent.name": result.get("intent"),
            "intent.confidence": safe_float(result.get("confidence")),
            "intent.is_ready": result.get("is_ready"),
            "intent.next_action": result.get("next_action"),
            "intent.missing_context.count": len(missing_context),
            "intent.alternative.count": len(alternatives),
            "intent.source": intent_source,
            "intent.llm_used": intent_source == "llm",
            "intent.rule_fallback_used": intent_source in {"rule", "fallback"},
        }
    )


def build_skill_select_attributes(selected_skill: Any, intent_result: Any) -> dict[str, Any]:
    skill = to_mapping(selected_skill)
    intent = to_mapping(intent_result).get("intent")
    return clean_attributes(
        {
            "skill.selected": bool(skill),
            "skill.name": skill.get("name") or skill.get("skill_name"),
            "skill.intent": skill.get("intent") or intent,
        }
    )


def build_planner_build_attributes(plan: Any, strategy: str | None = None) -> dict[str, Any]:
    plan_data = to_mapping(plan)
    metadata = to_mapping(plan_data.get("metadata"))
    steps = as_list(plan_data.get("steps"))
    warnings = as_list(plan_data.get("warnings"))
    return clean_attributes(
        {
            "planner.strategy": strategy,
            "planner.source": metadata.get("planner_source") or "unknown",
            "planner.intent": plan_data.get("intent"),
            "planner.step_count": len(steps),
            "planner.is_composite": bool(plan_data.get("is_composite")),
            "planner.warning_count": len(warnings),
            "planner.error_type": error_type(metadata.get("model_planner_error")),
        }
    )


def build_executor_run_attributes(execution_result: Any, plan: Any | None = None) -> dict[str, Any]:
    result = to_mapping(execution_result)
    plan_data = to_mapping(plan)
    final_output = to_mapping(result.get("final_output"))
    step_results = as_list(result.get("step_results"))
    warnings = as_list(final_output.get("warnings"))
    return clean_attributes(
        {
            "executor.plan_id": result.get("plan_id") or plan_data.get("plan_id"),
            "executor.intent": final_output.get("intent") or plan_data.get("intent"),
            "executor.step_count": len(step_results) or len(as_list(plan_data.get("steps"))),
            "executor.success": result.get("success"),
            "executor.status": final_output.get("status") or plan_data.get("status"),
            "executor.error_type": error_type(result.get("error")),
            "executor.warning_count": len(warnings),
        }
    )


def build_result_build_attributes(agent_result: Any) -> dict[str, Any]:
    result = to_mapping(agent_result)
    final_output = to_mapping(result.get("final_output"))
    artifacts = as_list(final_output.get("artifacts"))
    tool_results = as_list(final_output.get("tool_results"))
    warnings = as_list(result.get("warnings") or final_output.get("warnings"))
    return clean_attributes(
        {
            "result.success": result.get("success"),
            "result.status": result.get("status") or final_output.get("status"),
            "result.has_final_output": bool(final_output),
            "result.artifact.count": len(artifacts),
            "result.tool_result.count": len(tool_results),
            "result.warning_count": len(warnings),
            "result.error_type": error_type(result.get("error")),
        }
    )


def build_llm_call_attributes(
    *,
    task: str | None = None,
    payload: dict[str, Any] | None = None,
    response: dict[str, Any] | None = None,
    success: bool | None = None,
    error: Any | None = None,
    latency_ms: float | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    response = response or {}
    usage = to_mapping(response.get("usage"))
    messages = as_list(payload.get("messages"))
    return clean_attributes(
        {
            "llm.task": task or "unknown",
            "llm.model": payload.get("model"),
            "llm.message_count": len(messages),
            "llm.prompt_chars": message_char_count(messages),
            "llm.temperature": safe_float(payload.get("temperature")),
            "llm.max_tokens": safe_int(payload.get("max_tokens")),
            "llm.success": success,
            "llm.error_type": error_type(error),
            "llm.latency_ms": latency_ms,
            "llm.prompt_tokens": safe_int(usage.get("prompt_tokens")),
            "llm.completion_tokens": safe_int(usage.get("completion_tokens")),
            "llm.total_tokens": safe_int(usage.get("total_tokens")),
        }
    )


def build_executor_step_attributes(
    *,
    plan: Any,
    step: Any,
    index: int,
    result: Any | None = None,
) -> dict[str, Any]:
    plan_data = to_mapping(plan)
    step_data = to_mapping(step)
    result_data = to_mapping(result)
    inputs = to_mapping(step_data.get("inputs"))
    warnings = as_list(result_data.get("warnings"))
    return clean_attributes(
        {
            "executor.plan_id": plan_data.get("plan_id"),
            "executor.step.index": index,
            "executor.step.id": step_data.get("step_id"),
            "executor.step.name": step_data.get("name"),
            "executor.step.action": step_data.get("action") or result_data.get("action"),
            "executor.step.status": step_data.get("status"),
            "executor.step.depends_on.count": len(as_list(step_data.get("depends_on"))),
            "executor.step.input_key.count": len(inputs),
            "executor.step.tool_name": step_data.get("tool_name") or inputs.get("tool_name"),
            "executor.step.success": result_data.get("success"),
            "executor.step.error_type": error_type(result_data.get("error")),
            "executor.step.warning_count": len(warnings),
        }
    )


def build_tool_call_attributes(
    *,
    tool_name: str,
    tool_spec: Any | None = None,
    kwargs: dict[str, Any] | None = None,
    result: Any | None = None,
    success: bool | None = None,
    error: Any | None = None,
    latency_ms: float | None = None,
) -> dict[str, Any]:
    spec = to_mapping(tool_spec)
    result_data = to_mapping(result)
    missing_config = as_list(result_data.get("missing_config"))
    warnings = as_list(result_data.get("warnings"))
    return clean_attributes(
        {
            "tool.name": tool_name,
            "tool.exists": tool_spec is not None,
            "tool.implemented": spec.get("implemented"),
            "tool.category": spec.get("category"),
            "tool.type": spec.get("tool_type"),
            "tool.risk_level": spec.get("risk_level"),
            "tool.requires_config": spec.get("requires_config"),
            "tool.requires_permission": spec.get("requires_permission"),
            "tool.arg_count": len(kwargs or {}),
            "tool.success": result_data.get("success") if result_data else success,
            "tool.error_type": error_type(result_data.get("error") if result_data else error),
            "tool.warning_count": len(warnings),
            "tool.missing_config.count": len(missing_config),
            "tool.latency_ms": latency_ms,
        }
    )


def clean_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in attributes.items():
        normalized = normalize_attribute_value(value)
        if normalized is not None:
            clean[key] = normalized
    return clean


def normalize_attribute_value(value: Any) -> str | bool | int | float | list[str | bool | int | float] | None:
    if value is None:
        return None
    if isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        values = [normalize_attribute_value(item) for item in value]
        primitive_values = [item for item in values if isinstance(item, (str, bool, int, float))]
        return primitive_values or None
    return str(value)


def stable_hash(value: str, length: int = 16) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return digest[:length]


def error_type(error: Any | None) -> str | None:
    if error is None:
        return None
    if isinstance(error, BaseException):
        return type(error).__name__
    text = str(error).strip()
    if not text:
        return None
    if ":" in text:
        return text.split(":", 1)[0].strip() or "Error"
    return text[:80]


def to_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        converted = asdict(value)
        return converted if isinstance(converted, dict) else {}
    if hasattr(value, "to_dict"):
        converted = value.to_dict()
        return converted if isinstance(converted, dict) else {}
    return {}


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def alias_summary(aliases: list[Any]) -> str | None:
    pairs: list[str] = []
    for item in aliases[:10]:
        data = to_mapping(item)
        raw = data.get("raw")
        normalized = data.get("normalized")
        if raw and normalized:
            pairs.append(f"{raw}->{normalized}")
    return comma_join(pairs)


def infer_intent_source(intent_result: dict[str, Any]) -> str:
    evidence = " ".join(str(item) for item in as_list(intent_result.get("evidence")))
    if "LLM" in evidence:
        return "llm"
    if "规则" in evidence:
        return "rule"
    if "兜底" in evidence:
        return "fallback"
    return "unknown"


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def message_char_count(messages: list[Any]) -> int:
    total = 0
    for message in messages:
        data = to_mapping(message)
        content = data.get("content")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            total += sum(len(str(item)) for item in content)
    return total


def unique_values(values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        if value in (None, "", []):
            continue
        text = str(value)
        if text not in result:
            result.append(text)
    return result


def comma_join(values: list[str]) -> str | None:
    return ",".join(values) if values else None


def count_local_file_refs(refs: list[Any]) -> int:
    return sum(1 for ref in refs if isinstance(ref, dict) and ref.get("type") == "local_file")


def count_existing_file_refs(refs: list[Any]) -> int:
    return sum(
        1
        for ref in refs
        if isinstance(ref, dict) and ref.get("type") == "local_file" and bool(ref.get("exists"))
    )


def file_extensions(refs: list[Any]) -> list[str]:
    extensions: list[str] = []
    for ref in refs:
        if not isinstance(ref, dict) or ref.get("type") != "local_file":
            continue
        path = str(ref.get("path") or "")
        if "." not in path:
            continue
        extension = "." + path.rsplit(".", 1)[-1].lower()
        if extension not in extensions:
            extensions.append(extension)
    return extensions
