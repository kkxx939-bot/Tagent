"""稳定动作执行器。

Executor 只负责执行 Planner 给出的通用 action。
业务差异由 artifact_type、tool_name、context_type 等参数表达。
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable

from OTel.OTelClient import mark_span_error, mark_span_ok, set_span_attributes, start_span
from OTel.TraceScheme import SPAN_EXECUTOR_STEP, build_executor_step_attributes
from executor.artifacts import generate_artifact, save_artifact, validate_artifact
from executor.context_loader import load_context
from executor.policies import policy_for_step
from executor.result import ExecutionResult, StepResult
from observability import summarize_context_payload
from planner.actions import (
    ASK_USER,
    CALL_TOOL,
    FINISH,
    GENERATE_ARTIFACT,
    LOAD_CONTEXT,
    LOAD_MEMORY,
    REPORT_CAPABILITY_GAP,
    SAVE_ARTIFACT,
    SELECT_SKILL,
    SUMMARIZE_RESULT,
    VALIDATE_ARTIFACT,
)
from planner.plan import COMPLETED, FAILED, RUNNING, SKIPPED, WAITING_FOR_USER, Plan, PlanStep
from planner.validator import validate_plan


StepHandler = Callable[[PlanStep], StepResult]


class Executor:
    """最小稳定执行内核。"""

    def __init__(
        self,
        user_query: str,
        memory_manager: Any | None = None,
        execution_context: dict[str, Any] | None = None,
    ) -> None:
        self.user_query = user_query
        self.memory_manager = memory_manager
        self.variables: dict[str, Any] = {"artifacts": [], **(execution_context or {})}
        self.handlers: dict[str, StepHandler] = {
            SELECT_SKILL: self.handle_select_skill,
            LOAD_MEMORY: self.handle_load_memory,
            LOAD_CONTEXT: self.handle_load_context,
            CALL_TOOL: self.handle_call_tool,
            GENERATE_ARTIFACT: self.handle_generate_artifact,
            VALIDATE_ARTIFACT: self.handle_validate_artifact,
            SAVE_ARTIFACT: self.handle_save_artifact,
            SUMMARIZE_RESULT: self.handle_summarize_result,
            ASK_USER: self.handle_ask_user,
            REPORT_CAPABILITY_GAP: self.handle_report_capability_gap,
            FINISH: self.handle_finish,
        }

    def run(self, plan: Plan) -> ExecutionResult:
        step_results: list[StepResult] = []
        completed_steps: set[str] = set()
        validation = validate_plan(plan)
        if not validation.is_valid:
            plan.status = FAILED
            return self._build_result(
                plan,
                step_results,
                "计划校验失败：" + "；".join(validation.errors),
                warnings=validation.warnings,
            )

        plan.status = RUNNING
        self.variables["plan_missing_context"] = list(plan.missing_context or [])
        self.variables["plan_intent"] = plan.intent

        for index, step in enumerate(plan.steps):
            with start_span(
                SPAN_EXECUTOR_STEP,
                build_executor_step_attributes(plan=plan.to_dict(), step=step.to_dict(), index=index),
            ) as span:
                step.status = RUNNING

                missing_dependencies = [
                    dependency for dependency in step.depends_on if dependency not in completed_steps
                ]
                if missing_dependencies:
                    result = StepResult(
                        step_id=step.step_id,
                        action=step.action,
                        success=False,
                        error=f"依赖步骤未完成：{missing_dependencies}",
                    )
                    step.status = FAILED
                    step_results.append(result)
                    self._record_step_span_result(span, plan, step, index, result)
                    mark_span_error(span, result.error)
                    return self._build_result(plan, step_results, result.error)

                handler = self.handlers.get(step.action)
                if not handler:
                    result = StepResult(
                        step_id=step.step_id,
                        action=step.action,
                        success=False,
                        error=f"action 未实现：{step.action}",
                    )
                else:
                    try:
                        result = handler(step)
                    except Exception as exc:
                        result = StepResult(
                            step_id=step.step_id,
                            action=step.action,
                            success=False,
                            error=f"{type(exc).__name__}: {exc}",
                        )

                step_results.append(result)
                policy = policy_for_step(step)
                if not result.success and not policy.continue_on_failure:
                    step.status = FAILED
                    self._record_step_span_result(span, plan, step, index, result)
                    mark_span_error(span, result.error)
                    return self._build_result(plan, step_results, result.error)

                step.status = COMPLETED if result.success else FAILED
                completed_steps.add(step.step_id)
                self._record_step_note(step)
                if step.action == ASK_USER and result.success:
                    for remaining_step in plan.steps[index + 1 :]:
                        remaining_step.status = SKIPPED
                    plan.status = WAITING_FOR_USER
                    self._record_step_span_result(span, plan, step, index, result)
                    mark_span_ok(span)
                    return self._build_result(plan, step_results)

                self._record_step_span_result(span, plan, step, index, result)
                if result.success:
                    mark_span_ok(span)
                else:
                    mark_span_error(span, result.error)

        plan.status = self._status_for_output(None)
        return self._build_result(plan, step_results)

    def handle_select_skill(self, step: PlanStep) -> StepResult:
        skill = step.inputs.get("skill") or step.inputs.get("skill_name") or step.inputs.get("intent")
        if skill is None:
            skill = self.variables.get("selected_skill")
        self.variables["selected_skill"] = skill
        return StepResult(step_id=step.step_id, action=step.action, success=True, data={"selected_skill": skill})

    def handle_load_memory(self, step: PlanStep) -> StepResult:
        session = self.memory_manager.get_current_session() if self.memory_manager else None
        memories = session.relevant_long_term_memories if session else []
        self.variables["relevant_memories"] = memories
        return StepResult(step_id=step.step_id, action=step.action, success=True, data={"memory_count": len(memories)})

    def handle_load_context(self, step: PlanStep) -> StepResult:
        context_type = str(step.inputs.get("context_type") or "")
        if not context_type:
            return StepResult(
                step_id=step.step_id,
                action=step.action,
                success=False,
                error="缺少 context_type，不能默认执行 RAG 检索",
            )
        started_at = time.perf_counter()
        result = load_context(context_type, self.user_query, dict(step.inputs), self.variables)
        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        if self.memory_manager and result.memory_payload:
            self.memory_manager.add_retrieved_context(result.memory_payload)
        self._record_context_trace(context_type, latency_ms=latency_ms)
        return StepResult(
            step_id=step.step_id,
            action=step.action,
            success=result.success,
            data=result.data,
            warnings=result.warnings,
            error=result.error,
        )

    def handle_call_tool(self, step: PlanStep) -> StepResult:
        from tools.registry import run_tool

        tool_name = step.tool_name or str(step.inputs.get("tool_name") or "")
        if not tool_name:
            return StepResult(step_id=step.step_id, action=step.action, success=False, error="缺少 tool_name")

        kwargs = dict(step.inputs)
        kwargs.pop("tool_name", None)
        if tool_name == "query_trace_log" and "trace_id" not in kwargs:
            trace_id = extract_trace_or_request_id(self.user_query)
            if trace_id:
                kwargs["trace_id"] = trace_id

        tool_result = run_tool(tool_name, **kwargs)
        data = tool_result.to_dict()
        self.variables.setdefault("tool_results", []).append(data)
        if self.memory_manager:
            self.memory_manager.add_tool_result(tool_name, data)

        if tool_result.error in {"tool_not_configured", "tool_not_implemented"}:
            self.variables["capability_gap"] = {
                "reason": f"工具 {tool_name} 当前不可用，无法完成对应外部环境查询。",
                "missing_tools": [tool_name] if tool_result.error == "tool_not_implemented" else [],
                "missing_artifacts": [],
                "missing_config": tool_result.missing_config,
            }
            return StepResult(
                step_id=step.step_id,
                action=step.action,
                success=True,
                data=data,
                warnings=tool_result.warnings,
            )

        return StepResult(
            step_id=step.step_id,
            action=step.action,
            success=tool_result.success,
            data=data,
            warnings=tool_result.warnings,
            error=tool_result.error,
        )

    def handle_generate_artifact(self, step: PlanStep) -> StepResult:
        artifact_type = str(step.inputs.get("artifact_type") or "")
        result = generate_artifact(artifact_type, self.user_query, dict(step.inputs), self.variables)
        if result.success:
            self._record_generated_artifact(artifact_type, result.data)
        return StepResult(
            step_id=step.step_id,
            action=step.action,
            success=result.success,
            data=result.data,
            warnings=result.warnings,
            error=result.error,
        )

    def handle_validate_artifact(self, step: PlanStep) -> StepResult:
        artifact_type = str(step.inputs.get("artifact_type") or "")
        result = validate_artifact(artifact_type, dict(step.inputs), self.variables)
        return StepResult(
            step_id=step.step_id,
            action=step.action,
            success=result.success,
            data=result.data,
            warnings=result.warnings,
            error=result.error,
        )

    def handle_save_artifact(self, step: PlanStep) -> StepResult:
        result = save_artifact(dict(step.inputs), self.variables)
        if result.data.get("artifacts"):
            self.variables["artifacts"] = result.data["artifacts"]
        return StepResult(
            step_id=step.step_id,
            action=step.action,
            success=result.success,
            data=result.data,
            warnings=result.warnings,
            error=result.error,
        )

    def handle_summarize_result(self, step: PlanStep) -> StepResult:
        summary_type = str(step.inputs.get("summary_type") or "general")
        data = {"summary_type": summary_type}
        if self.variables.get("retrieved_context"):
            data["source_summary"] = self.variables["retrieved_context"].get("source_summary") or {}
        if self.variables.get("failure_source_context"):
            data["source_summary"] = self.variables["failure_source_context"].get("source_summary") or {}
            data["source_profile"] = self.variables["failure_source_context"].get("source_profile") or {}
        if self.variables.get("tool_results"):
            data["tool_result_count"] = len(self.variables["tool_results"])
        if self.variables.get("case_generation_result"):
            data["case_count"] = len(self.variables["case_generation_result"].get("cases") or [])
        self.variables["summary_result"] = data
        return StepResult(step_id=step.step_id, action=step.action, success=True, data=data)

    def handle_ask_user(self, step: PlanStep) -> StepResult:
        message = str(step.inputs.get("message") or "需要用户补充信息后再继续。")
        missing_context = step.inputs.get("missing_context") or self.variables.get("plan_missing_context") or []
        self.variables["clarification_required"] = missing_context
        self.variables["clarification_message"] = message
        return StepResult(
            step_id=step.step_id,
            action=step.action,
            success=True,
            data={"message": message, "missing_context": missing_context},
            warnings=["需要用户补充信息"],
        )

    def handle_report_capability_gap(self, step: PlanStep) -> StepResult:
        gap = {
            "reason": step.inputs.get("reason")
            or step.inputs.get("message")
            or "当前 Agent 没有可执行的 tool、artifact handler 或上下文配置来完成该任务。",
            "missing_tools": step.inputs.get("missing_tools") or [],
            "missing_artifacts": step.inputs.get("missing_artifacts") or [],
        }
        self.variables["capability_gap"] = gap
        return StepResult(step_id=step.step_id, action=step.action, success=True, data=gap)

    def handle_finish(self, step: PlanStep) -> StepResult:
        if not self.memory_manager:
            return StepResult(
                step_id=step.step_id,
                action=step.action,
                success=True,
                warnings=["未配置 memory_manager，跳过记忆写入"],
            )

        persist_summary = self.variables.get("plan_intent") != "OUT_OF_SCOPE" and not self.variables.get("capability_gap")
        final_status = self._status_for_output(None)
        result = self.memory_manager.complete_task(
            summary="Executor 执行完成",
            final_status=final_status,
            final_output=self._memory_final_output(final_status),
            persist_summary=persist_summary,
            persist_async=True,
        )
        self.variables["memory_result"] = result
        return StepResult(step_id=step.step_id, action=step.action, success=True, data=result)

    def _record_generated_artifact(self, artifact_type: str, data: dict[str, Any]) -> None:
        # TODO(Executor优化): 后续把 artifact manifest 标准化，补 artifact_id、source_step_id、created_at、status。
        artifact = {
            "artifact_type": artifact_type,
            "output_path": data.get("output_path"),
            "metadata": {key: value for key, value in data.items() if key not in {"output_path"}},
        }
        self.variables.setdefault("artifacts", []).append(artifact)

        output_path = str(data.get("output_path") or "")
        if not self.memory_manager or not output_path:
            return
        self.memory_manager.add_generated_output(
            output_path=output_path,
            output_type=artifact_type,
            summary=f"生成产物：{artifact_type}",
            metadata=data,
        )

    def _record_step_note(self, step: PlanStep) -> None:
        if self.memory_manager and self.memory_manager.get_current_session():
            self.memory_manager.add_note(f"执行完成：{step.step_id} {step.action}")

    def _record_step_span_result(self, span: Any, plan: Plan, step: PlanStep, index: int, result: StepResult) -> None:
        set_span_attributes(
            span,
            build_executor_step_attributes(
                plan=plan.to_dict(),
                step=step.to_dict(),
                index=index,
                result=result.to_dict(),
            ),
        )

    def _build_result(
        self,
        plan: Plan,
        step_results: list[StepResult],
        error: str | None = None,
        warnings: list[str] | None = None,
    ) -> ExecutionResult:
        if error:
            plan.status = FAILED
        merged_warnings = [*plan.warnings, *(warnings or [])]
        for result in step_results:
            merged_warnings.extend(result.warnings)
        final_output = self._final_output(plan, error, merged_warnings)
        if not error and plan.status != WAITING_FOR_USER:
            plan.status = str(final_output.get("status") or plan.status)
        return ExecutionResult(
            plan_id=plan.plan_id,
            success=error is None,
            step_results=step_results,
            final_output=final_output,
            error=error,
        )

    def _final_output(self, plan: Plan, error: str | None, warnings: list[str]) -> dict[str, Any]:
        status = self._status_for_output(error)
        missing_context = self.variables.get("clarification_required") or []
        if status == "partial_completed":
            missing_context = _merge_unique(missing_context, self.variables.get("plan_missing_context") or [])

        output: dict[str, Any] = {
            "status": status,
            "intent": plan.intent,
            "artifacts": self.variables.get("artifacts") or [],
            "tool_results": self.variables.get("tool_results") or [],
            "summary": self.variables.get("summary_result") or {},
            "missing_context": missing_context,
            "message": self.variables.get("clarification_message"),
            "capability_gap": self.variables.get("capability_gap"),
            "warnings": warnings,
        }
        if self.variables.get("case_generation_result"):
            result = self.variables["case_generation_result"]
            output["summary"] = {
                **output["summary"],
                "case_count": len(result.get("cases") or []),
                "source_summary": result.get("source_summary") or {},
            }
        if self.variables.get("failure_report"):
            output["failure_report"] = self.variables["failure_report"]
        if self.variables.get("context_trace"):
            output["context_trace"] = self.variables["context_trace"]
        return output

    def _memory_final_output(self, status: str) -> dict[str, Any]:
        output = {
            "status": status,
            "artifacts": self.variables.get("artifacts") or [],
            "tool_results": self.variables.get("tool_results") or [],
            "missing_context": self.variables.get("clarification_required") or [],
            "capability_gap": self.variables.get("capability_gap"),
            "warnings": [],
        }
        if self.variables.get("case_generation_result"):
            output["summary"] = {
                "case_count": len(self.variables["case_generation_result"].get("cases") or []),
                "source_summary": self.variables["case_generation_result"].get("source_summary") or {},
                "grounding_report": self.variables["case_generation_result"].get("grounding_report") or {},
            }
        return output

    def _record_context_trace(self, context_type: str, latency_ms: float | None = None) -> None:
        payload = self.variables.get("loaded_context")
        if payload is None:
            return
        summary = summarize_context_payload(context_type, payload)
        if latency_ms is not None:
            summary["latency_ms"] = latency_ms
            summary.setdefault("metadata", {})["latency_ms"] = latency_ms
        self.variables.setdefault("context_trace", []).append(summary)

    def _status_for_output(self, error: str | None) -> str:
        if error:
            return "failed"
        if self.variables.get("clarification_required"):
            return "waiting_for_user"
        if self.variables.get("capability_gap"):
            return "capability_gap"
        if _has_draft_artifact(self.variables.get("artifacts") or []):
            return "partial_completed"
        return "completed"


def extract_trace_or_request_id(text: str) -> str | None:
    patterns = [
        r"(?i)(?:traceid|trace_id|trace id)\s*[:= ]\s*([a-z0-9._\-]+)",
        r"(?i)(?:requestid|request_id|request id)\s*[:= ]\s*([a-z0-9._\-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "")
        if match:
            return match.group(1)
    return None


def _has_draft_artifact(artifacts: list[dict[str, Any]]) -> bool:
    for artifact in artifacts:
        metadata = artifact.get("metadata") if isinstance(artifact, dict) else None
        if isinstance(metadata, dict) and metadata.get("status") == "draft":
            return True
    return False


def _merge_unique(existing: list[Any], incoming: list[Any]) -> list[Any]:
    merged = []
    for item in [*existing, *incoming]:
        if item and item not in merged:
            merged.append(item)
    return merged
