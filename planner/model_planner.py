"""模型 Planner。

默认采用 hybrid 策略：先让模型生成紧凑计划，再用 validator 校验。
模型不可用或计划非法时，回退到本文件里的轻量模板计划。
"""

from __future__ import annotations

import json
import re
from typing import Any

from planner.actions import (
    ACTION_SPECS,
    ASK_USER,
    CALL_TOOL,
    FINISH,
    GENERATE_ARTIFACT,
    LOAD_CONTEXT,
    REPORT_CAPABILITY_GAP,
    SAVE_ARTIFACT,
    SUMMARIZE_RESULT,
    VALIDATE_ARTIFACT,
)
from planner.plan import Plan, PlanStep
from planner.validator import validate_plan
from prompts.prompt_planner import build_planner_prompt

try:
    from llm_client import call_llm
except ModuleNotFoundError:
    call_llm = None

try:
    from skills.registry import get_skill
except ModuleNotFoundError:
    get_skill = None

try:
    from tools.registry import list_tools
except ModuleNotFoundError:
    list_tools = None


def build_plan(
    user_query: str,
    intent_result: dict[str, Any],
    selected_skill: dict[str, Any] | None = None,
    session_memory: dict[str, Any] | None = None,
    strategy: str = "hybrid",
) -> Plan:
    """生成计划。

    strategy:
    - hybrid：模型优先，失败后模板兜底。
    - model：只尝试模型，失败时返回 OUT_OF_SCOPE 能力边界计划，并记录错误原因。
    - template：只使用轻量模板。
    """
    # TODO(Planner优化): 后续可让 model strategy 直接抛出模型规划异常，由上层决定是否兜底。
    # TODO(Planner优化): 模板兜底还需要补齐 BUG_REPORT、REGRESSION、CONFIG、PROJECT_QA 等专属流程。
    # TODO(Planner优化): 复合任务后续可增加 phase 字段，方便 Executor 和 UI 展示阶段。
    skill = selected_skill or _skill_for_intent(str(intent_result.get("intent") or "OUT_OF_SCOPE"))
    intent = str(intent_result.get("intent") or "OUT_OF_SCOPE")
    if _is_case_and_automation_task(user_query, intent_result):
        skill = _skill_for_intent("CASE_GENERATION") or skill
        plan = build_template_plan(user_query, intent_result, skill, session_memory)
        plan.metadata["planner_source"] = "template"
        plan.metadata["planner_skip_reason"] = "复合任务使用稳定模板计划"
        return plan

    if intent in {"OUT_OF_SCOPE", "CONTEXT_SEARCH", "CASE_GENERATION", "FAILURE_TRIAGE", "EXECUTION_ASSISTANT"}:
        plan = build_template_plan(user_query, intent_result, skill, session_memory)
        plan.metadata["planner_source"] = "template"
        plan.metadata["planner_skip_reason"] = f"{intent} 使用稳定模板计划"
        return plan

    if strategy in {"hybrid", "model"}:
        model_plan, model_error = build_model_plan(user_query, intent_result, skill, session_memory)
        if model_plan:
            validation = validate_plan(model_plan)
            if validation.is_valid:
                model_plan.metadata["planner_source"] = "model"
                if validation.warnings:
                    model_plan.warnings.extend(validation.warnings)
                return model_plan
            model_error = "; ".join(validation.errors)

        if strategy == "model":
            fallback = _model_failed_plan(user_query, intent_result, model_error)
            fallback.metadata["planner_source"] = "model_failed"
            if session_memory:
                fallback.metadata["session_id"] = session_memory.get("session_id")
            return fallback

    plan = build_template_plan(user_query, intent_result, skill, session_memory)
    plan.metadata["planner_source"] = "template"
    if "model_error" in locals() and model_error:
        plan.metadata["model_planner_error"] = model_error
        plan.warnings.append("模型 Planner 不可用或输出非法，已回退模板计划")
    return plan


def build_model_plan(
    user_query: str,
    intent_result: dict[str, Any],
    selected_skill: dict[str, Any] | None = None,
    session_memory: dict[str, Any] | None = None,
) -> tuple[Plan | None, str | None]:
    """调用模型生成计划；失败时返回错误原因。"""
    if call_llm is None:
        return None, "llm_client 不可用"

    context = {
        "user_query": user_query,
        "intent_result": intent_result,
        "selected_skill": selected_skill or {},
        "allowed_actions": _format_allowed_actions(),
        "available_tools": list_tools() if list_tools else [],
    }
    try:
        response = call_llm(build_planner_prompt(context), temperature=0.1, max_tokens=1600)
        payload = _parse_json_response(response)
        return _plan_from_payload(payload, user_query, intent_result, session_memory), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def build_template_plan(
    user_query: str,
    intent_result: dict[str, Any],
    selected_skill: dict[str, Any] | None = None,
    session_memory: dict[str, Any] | None = None,
) -> Plan:
    """轻量模板兜底计划。"""
    intent = str(intent_result.get("intent") or "OUT_OF_SCOPE")
    missing_context = list(intent_result.get("missing_context") or [])
    framework = _framework_from_intent_or_query(intent_result, user_query)
    case_context_type = _case_context_type(intent_result)

    if _needs_clarification_before_execution(intent, intent_result):
        plan = _ask_user_plan(user_query, intent, missing_context)
        if selected_skill:
            plan.metadata["selected_skill"] = selected_skill
        if session_memory:
            plan.metadata["session_id"] = session_memory.get("session_id")
        return plan

    if _is_case_and_automation_task(user_query, intent_result):
        plan = Plan(
            intent="CASE_GENERATION",
            user_query=user_query,
            is_composite=True,
            sub_tasks=["CASE_GENERATION", "AUTOMATION_WRITING"],
            missing_context=_merge_missing_context(_automation_missing_context(user_query), missing_context),
            steps=[
                _step("step_1", "读取需求和历史测试资产", LOAD_CONTEXT, inputs={"context_type": case_context_type}),
                _step("step_2", "生成测试用例", GENERATE_ARTIFACT, ["step_1"], inputs={"artifact_type": "test_case"}),
                _step("step_3", "校验测试用例", VALIDATE_ARTIFACT, ["step_2"], inputs={"artifact_type": "test_case"}),
                _step("step_4", "读取自动化项目上下文", LOAD_CONTEXT, ["step_3"], inputs={"context_type": "automation_project"}),
                _step("step_5", "生成自动化代码", GENERATE_ARTIFACT, ["step_4"], inputs=_artifact_inputs("automation_code", framework)),
                _step("step_6", "保存输出结果", SAVE_ARTIFACT, ["step_5"]),
                _step("step_7", "完成任务并写入记忆", FINISH, ["step_6"]),
            ],
        )
    elif intent == "CASE_GENERATION":
        plan = Plan(
            intent=intent,
            user_query=user_query,
            missing_context=missing_context,
            steps=[
                _step("step_1", "读取相关上下文", LOAD_CONTEXT, inputs={"context_type": case_context_type}),
                _step("step_2", "生成测试用例", GENERATE_ARTIFACT, ["step_1"], inputs={"artifact_type": "test_case"}),
                _step("step_3", "校验测试用例", VALIDATE_ARTIFACT, ["step_2"], inputs={"artifact_type": "test_case"}),
                _step("step_4", "保存结果", SAVE_ARTIFACT, ["step_3"]),
                _step("step_5", "完成任务并写入记忆", FINISH, ["step_4"]),
            ],
        )
    elif intent == "FAILURE_TRIAGE":
        plan = _failure_triage_template(user_query, missing_context)
    elif intent == "AUTOMATION_WRITING":
        plan = Plan(
            intent=intent,
            user_query=user_query,
            missing_context=_merge_missing_context(_automation_missing_context(user_query), missing_context),
            steps=[
                _step("step_1", "读取自动化项目上下文", LOAD_CONTEXT, inputs={"context_type": "automation_project"}),
                _step("step_2", "生成自动化代码", GENERATE_ARTIFACT, ["step_1"], inputs=_artifact_inputs("automation_code", framework)),
                _step("step_3", "汇总验证方式", SUMMARIZE_RESULT, ["step_2"], inputs={"summary_type": "verification"}),
                _step("step_4", "完成任务并写入记忆", FINISH, ["step_3"]),
            ],
        )
    elif intent == "CONTEXT_SEARCH":
        plan = Plan(
            intent=intent,
            user_query=user_query,
            missing_context=missing_context,
            steps=[
                _step("step_1", "检索相关上下文", LOAD_CONTEXT, inputs={"context_type": "context_search"}),
                _step("step_2", "汇总检索结果", SUMMARIZE_RESULT, ["step_1"], inputs={"summary_type": "context"}),
                _step("step_3", "完成任务并写入记忆", FINISH, ["step_2"]),
            ],
        )
    elif intent == "RESULT_REVIEW":
        plan = Plan(
            intent=intent,
            user_query=user_query,
            missing_context=missing_context,
            steps=[
                _step("step_1", "读取结果文件上下文", LOAD_CONTEXT, inputs={"context_type": "result_file"}),
                _step("step_2", "生成评审结论", GENERATE_ARTIFACT, ["step_1"], inputs={"artifact_type": "review_report"}),
                _step("step_3", "完成任务并写入记忆", FINISH, ["step_2"]),
            ],
        )
    elif intent == "OUT_OF_SCOPE":
        plan = Plan(
            intent="OUT_OF_SCOPE",
            user_query=user_query,
            missing_context=missing_context,
            steps=[
                _step(
                    "step_1",
                    "说明当前请求不在测试 Agent 能力范围内",
                    REPORT_CAPABILITY_GAP,
                    inputs={
                        "reason": "当前 Test Agent 只处理测试相关任务，例如用例生成、失败排查、自动化代码生成、测试执行辅助和结果检查。",
                    },
                ),
                _step("step_2", "结束任务", FINISH, ["step_1"]),
            ],
        )
    elif intent == "EXECUTION_ASSISTANT":
        plan = Plan(
            intent=intent,
            user_query=user_query,
            missing_context=["缺少可执行的环境操作工具"],
            warnings=["当前未接入测试环境执行类工具，不能执行服务重启、环境变更等操作"],
            steps=[
                _step(
                    "step_1",
                    "说明当前能力缺口",
                    REPORT_CAPABILITY_GAP,
                    inputs={
                        "reason": "当前 Test Agent 未接入服务重启工具，不能执行测试环境服务重启操作。",
                        "missing_tools": ["restart_service"],
                    },
                ),
                _step("step_2", "结束任务", FINISH, ["step_1"]),
            ],
        )
    else:
        plan = Plan(
            intent=intent,
            user_query=user_query,
            missing_context=missing_context,
            steps=[
                _step("step_1", "说明当前能力缺口", REPORT_CAPABILITY_GAP),
                _step("step_2", "结束任务", FINISH, ["step_1"]),
            ],
        )

    if selected_skill:
        plan.metadata["selected_skill"] = selected_skill
    if session_memory:
        plan.metadata["session_id"] = session_memory.get("session_id")
    return plan


def _model_failed_plan(user_query: str, intent_result: dict[str, Any], error: str | None) -> Plan:
    missing_context = list(intent_result.get("missing_context") or [])
    warning = "模型 Planner 不可用或输出非法"
    if error:
        warning = f"{warning}：{error}"
    intent = str(intent_result.get("intent") or "OUT_OF_SCOPE")
    if intent == "OUT_OF_SCOPE":
        steps = [
            _step(
                "step_1",
                "说明当前请求不在测试 Agent 能力范围内",
                REPORT_CAPABILITY_GAP,
                inputs={"reason": warning},
            ),
            _step("step_2", "结束任务", FINISH, ["step_1"]),
        ]
    else:
        steps = [
            _step(
                "step_1",
                "模型 Planner 失败，等待重新规划或人工确认",
                ASK_USER,
                inputs={"message": "模型规划失败，请补充任务目标或改写请求。", "missing_context": missing_context},
            ),
        ]
    return Plan(
        intent=intent,
        user_query=user_query,
        missing_context=missing_context,
        warnings=[warning],
        steps=steps,
        metadata={"model_planner_error": error or warning},
    )


def _ask_user_plan(user_query: str, intent: str, missing_context: list[str]) -> Plan:
    if not missing_context:
        missing_context = ["需要补充任务目标或输入材料"]
    return Plan(
        intent=intent,
        user_query=user_query,
        missing_context=missing_context,
        steps=[
            _step(
                "step_1",
                "等待用户补充信息",
                ASK_USER,
                inputs={
                    "message": "当前信息不足，请补充后再继续执行。",
                    "missing_context": missing_context,
                },
            ),
            _step("step_2", "结束当前等待状态", FINISH, ["step_1"]),
        ],
    )


def _failure_triage_template(user_query: str, missing_context: list[str]) -> Plan:
    if not _has_trace_or_request_id(user_query) and missing_context:
        return _ask_user_plan(user_query, "FAILURE_TRIAGE", missing_context)

    steps = [
        _step("step_1", "读取失败排查上下文", LOAD_CONTEXT, inputs={"context_type": "failure_triage"}),
    ]
    if _has_trace_or_request_id(user_query):
        steps.append(
            _step(
                "step_2",
                "按 traceId/requestId 查询日志",
                CALL_TOOL,
                ["step_1"],
                inputs={"tool_name": "query_trace_log"},
                requires_permission=True,
                tool_name="query_trace_log",
            )
        )
        steps.append(_step("step_3", "整理证据和建议", SUMMARIZE_RESULT, ["step_2"], inputs={"summary_type": "failure_triage"}))
        steps.append(_step("step_4", "完成任务并写入记忆", FINISH, ["step_3"]))
    else:
        steps.append(_step("step_2", "整理排查建议", SUMMARIZE_RESULT, ["step_1"], inputs={"summary_type": "failure_triage"}))
        steps.append(_step("step_3", "完成任务并写入记忆", FINISH, ["step_2"]))
    return Plan(intent="FAILURE_TRIAGE", user_query=user_query, missing_context=missing_context, steps=steps)


def _case_context_type(intent_result: dict[str, Any]) -> str:
    profile = intent_result.get("source_profile")
    if intent_result.get("source_document_available") and _force_source_generation(intent_result):
        return "requirement_document"
    if intent_result.get("source_document_available") and isinstance(profile, dict) and profile.get("source_type") in {
        "requirement_document",
        "api_document",
        "test_case_file",
    }:
        return "requirement_document"
    if isinstance(profile, dict) and profile.get("source_type") in {
        "requirement_document",
        "api_document",
        "test_case_file",
    }:
        return "requirement_document"
    return "case_generation"


def _force_source_generation(intent_result: dict[str, Any]) -> bool:
    if intent_result.get("force_source_generation"):
        return True
    extracted = intent_result.get("extracted_context")
    return isinstance(extracted, dict) and bool(extracted.get("force_source_generation"))


def _plan_from_payload(
    payload: dict[str, Any],
    user_query: str,
    intent_result: dict[str, Any],
    session_memory: dict[str, Any] | None,
) -> Plan:
    intent = str(payload.get("intent") or intent_result.get("intent") or "OUT_OF_SCOPE")
    steps_payload = payload.get("steps") or []
    framework = _framework_from_intent_or_query(intent_result, user_query)
    steps = [
        _enrich_step_inputs(_step_from_payload(index, item), intent, framework)
        for index, item in enumerate(steps_payload, start=1)
        if isinstance(item, dict)
    ]
    is_composite = bool(payload.get("is_composite")) or _is_case_and_automation_task(user_query, intent_result)
    sub_tasks = [str(item) for item in payload.get("sub_tasks") or []]
    if is_composite and _is_case_and_automation_task(user_query, intent_result):
        sub_tasks = ["CASE_GENERATION", "AUTOMATION_WRITING"]

    missing_context = _merge_missing_context(
        [str(item) for item in payload.get("missing_context") or []],
        [str(item) for item in intent_result.get("missing_context") or []],
    )
    if any(
        step.action == GENERATE_ARTIFACT and step.inputs.get("artifact_type") == "automation_code"
        for step in steps
    ) or is_composite:
        missing_context = _merge_missing_context(missing_context, _automation_missing_context(user_query))

    plan = Plan(
        intent=intent,
        user_query=user_query,
        steps=steps,
        is_composite=is_composite,
        sub_tasks=sub_tasks,
        missing_context=missing_context,
        warnings=[str(item) for item in payload.get("warnings") or []],
    )
    if session_memory:
        plan.metadata["session_id"] = session_memory.get("session_id")
    return plan


def _step_from_payload(index: int, payload: dict[str, Any]) -> PlanStep:
    step_id = str(payload.get("step_id") or f"step_{index}")
    return PlanStep(
        step_id=step_id,
        name=str(payload.get("name") or step_id),
        action=str(payload.get("action") or ""),
        depends_on=[str(item) for item in payload.get("depends_on") or []],
        inputs=payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {},
        requires_permission=bool(payload.get("requires_permission")),
        tool_name=str(payload["tool_name"]) if payload.get("tool_name") else None,
    )


def _step(
    step_id: str,
    name: str,
    action: str,
    depends_on: list[str] | None = None,
    inputs: dict[str, object] | None = None,
    requires_permission: bool = False,
    tool_name: str | None = None,
) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        name=name,
        action=action,
        depends_on=depends_on or [],
        inputs=inputs or {},
        requires_permission=requires_permission,
        tool_name=tool_name,
    )


def _parse_json_response(response: str) -> dict[str, Any]:
    text = response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    return json.loads(text)


def _format_allowed_actions() -> list[dict[str, object]]:
    return [
        {
            "name": name,
            "description": spec.description,
            "requires_tool": spec.requires_tool,
            "requires_permission": spec.requires_permission,
        }
        for name, spec in ACTION_SPECS.items()
    ]


def _skill_for_intent(intent: str) -> dict[str, Any] | None:
    if get_skill is None:
        return None
    skill = get_skill(intent)
    return skill.to_dict() if skill else None


def _enrich_step_inputs(step: PlanStep, intent: str, framework: str | None) -> PlanStep:
    inputs = dict(step.inputs)
    if step.action == LOAD_CONTEXT and not inputs.get("context_type"):
        inputs["context_type"] = _default_context_type(intent)
    if step.action == GENERATE_ARTIFACT and inputs.get("artifact_type") == "automation_code" and framework:
        inputs.setdefault("framework", framework)
    step.inputs = inputs
    return step


def _default_context_type(intent: str) -> str:
    if intent == "CASE_GENERATION":
        return "case_generation"
    if intent == "AUTOMATION_WRITING":
        return "automation_project"
    if intent == "FAILURE_TRIAGE":
        return "failure_triage"
    if intent == "RESULT_REVIEW":
        return "result_file"
    if intent == "CONTEXT_SEARCH":
        return "context_search"
    return "context_search"


def _artifact_inputs(artifact_type: str, framework: str | None = None) -> dict[str, object]:
    inputs: dict[str, object] = {"artifact_type": artifact_type}
    if framework:
        inputs["framework"] = framework
    return inputs


def _framework_from_intent_or_query(intent_result: dict[str, Any], user_query: str) -> str | None:
    extracted_context = intent_result.get("extracted_context") or {}
    if isinstance(extracted_context, dict):
        frameworks = extracted_context.get("frameworks")
        if isinstance(frameworks, list) and frameworks:
            return str(frameworks[0]).lower()

    text = user_query.lower()
    for framework in ("playwright", "selenium", "appium", "pytest", "cypress"):
        if framework in text:
            return framework
    return None


def _needs_clarification_before_execution(intent: str, intent_result: dict[str, Any]) -> bool:
    if intent not in {"CASE_GENERATION", "AUTOMATION_WRITING", "REGRESSION_ANALYSIS"}:
        return False
    if bool(intent_result.get("is_ready")):
        return False
    return bool(intent_result.get("missing_context"))


def _is_case_and_automation_task(user_query: str, intent_result: dict[str, Any]) -> bool:
    text = user_query.lower()
    has_case = any(keyword in text for keyword in ("case", "用例", "测试点", "测试用例"))
    has_automation = any(keyword in text for keyword in ("自动化", "playwright", "selenium", "pytest"))
    if has_case and has_automation:
        return True

    intent = str(intent_result.get("intent") or "")
    alternatives = intent_result.get("alternative_intents") or []
    if intent != "CASE_GENERATION" or not isinstance(alternatives, list):
        return False
    return any(item.get("intent") == "AUTOMATION_WRITING" for item in alternatives if isinstance(item, dict))


def _automation_missing_context(user_query: str) -> list[str]:
    text = user_query.lower()
    missing = []
    if not any(name in text for name in ("playwright", "selenium", "pytest", "appium", "cypress")):
        missing.append("自动化框架")
    if "路径" not in user_query and "项目" not in user_query:
        missing.append("自动化项目路径")
    return missing


def _has_trace_or_request_id(user_query: str) -> bool:
    text = user_query.lower()
    return any(keyword in text for keyword in ("traceid", "trace id", "requestid", "request id"))


def _merge_missing_context(existing: list[str], incoming: list[str]) -> list[str]:
    merged = []
    for item in [*existing, *incoming]:
        if item and item not in merged:
            merged.append(item)
    return merged
