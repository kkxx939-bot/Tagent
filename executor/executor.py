"""稳定动作执行器。

Executor 只负责执行 Planner 给出的通用 action。
业务差异由 artifact_type、tool_name、context_type 等参数表达。
"""

from __future__ import annotations

import re
from typing import Any, Callable

from executor.artifacts import generate_artifact, save_artifact, validate_artifact
from executor.policies import policy_for_step
from executor.result import ExecutionResult, StepResult
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
from planner.plan import COMPLETED, FAILED, RUNNING, Plan, PlanStep


StepHandler = Callable[[PlanStep], StepResult]


class Executor:
    """最小稳定执行内核。"""

    def __init__(self, user_query: str, memory_manager: Any | None = None) -> None:
        self.user_query = user_query
        self.memory_manager = memory_manager
        self.variables: dict[str, Any] = {}
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

        for step in plan.steps:
            step.status = RUNNING

            missing_dependencies = [dependency for dependency in step.depends_on if dependency not in completed_steps]
            if missing_dependencies:
                result = StepResult(
                    step_id=step.step_id,
                    action=step.action,
                    success=False,
                    error=f"依赖步骤未完成：{missing_dependencies}",
                )
                step.status = FAILED
                step_results.append(result)
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
                return self._build_result(plan, step_results, result.error)

            step.status = COMPLETED if result.success else FAILED
            completed_steps.add(step.step_id)
            self._record_step_note(step)

        plan.status = COMPLETED
        return self._build_result(plan, step_results)

    def handle_select_skill(self, step: PlanStep) -> StepResult:
        skill = step.inputs.get("skill") or step.inputs.get("skill_name") or step.inputs.get("intent")
        self.variables["selected_skill"] = skill
        return StepResult(step_id=step.step_id, action=step.action, success=True, data={"selected_skill": skill})

    def handle_load_memory(self, step: PlanStep) -> StepResult:
        session = self.memory_manager.get_current_session() if self.memory_manager else None
        memories = session.relevant_long_term_memories if session else []
        self.variables["relevant_memories"] = memories
        return StepResult(step_id=step.step_id, action=step.action, success=True, data={"memory_count": len(memories)})

    def handle_load_context(self, step: PlanStep) -> StepResult:
        context_type = str(step.inputs.get("context_type") or "rag")
        if context_type in {"automation_project", "result_file"}:
            data = {
                "context_type": context_type,
                "message": "当前还没有接入本地项目/结果文件读取工具，先记录为待补充上下文。",
            }
            self.variables["loaded_context"] = data
            return StepResult(
                step_id=step.step_id,
                action=step.action,
                success=True,
                data=data,
                warnings=[data["message"]],
            )

        from context import build_case_context

        query = str(step.inputs.get("query") or self.user_query)
        context = build_case_context(query)
        self.variables["retrieved_context"] = context
        self.variables["loaded_context"] = context
        if self.memory_manager:
            self.memory_manager.add_retrieved_context(
                {
                    "query": query,
                    "source_summary": context.get("source_summary") or {},
                }
            )
        return StepResult(
            step_id=step.step_id,
            action=step.action,
            success=True,
            data={"context_type": context_type, "source_summary": context.get("source_summary") or {}},
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
        if self.variables.get("tool_results"):
            data["tool_result_count"] = len(self.variables["tool_results"])
        if self.variables.get("case_generation_result"):
            data["case_count"] = len(self.variables["case_generation_result"].get("cases") or [])
        self.variables["summary_result"] = data
        return StepResult(step_id=step.step_id, action=step.action, success=True, data=data)

    def handle_ask_user(self, step: PlanStep) -> StepResult:
        missing_context = step.inputs.get("missing_context") or []
        self.variables["clarification_required"] = missing_context
        return StepResult(
            step_id=step.step_id,
            action=step.action,
            success=True,
            data={"missing_context": missing_context},
            warnings=["需要用户补充信息"],
        )

    def handle_report_capability_gap(self, step: PlanStep) -> StepResult:
        gap = {
            "reason": step.inputs.get("reason") or "当前 Agent 没有可执行的 tool、artifact handler 或上下文配置来完成该任务。",
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

        result = self.memory_manager.complete_task(summary="Executor 执行完成")
        self.variables["memory_result"] = result
        return StepResult(step_id=step.step_id, action=step.action, success=True, data=result)

    def _record_generated_artifact(self, artifact_type: str, data: dict[str, Any]) -> None:
        if not self.memory_manager:
            return
        output_path = str(data.get("output_path") or "")
        if not output_path:
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

    def _build_result(
        self,
        plan: Plan,
        step_results: list[StepResult],
        error: str | None = None,
    ) -> ExecutionResult:
        if error:
            plan.status = FAILED
        return ExecutionResult(
            plan_id=plan.plan_id,
            success=error is None,
            step_results=step_results,
            final_output=self._final_output(),
            error=error,
        )

    def _final_output(self) -> dict[str, Any]:
        output: dict[str, Any] = {}
        if self.variables.get("output_path"):
            output["output_path"] = self.variables["output_path"]
        if self.variables.get("case_generation_result"):
            result = self.variables["case_generation_result"]
            output["case_count"] = len(result.get("cases") or [])
            output["source_summary"] = result.get("source_summary") or {}
        if self.variables.get("summary_result"):
            output["summary_result"] = self.variables["summary_result"]
        if self.variables.get("clarification_required"):
            output["missing_context"] = self.variables["clarification_required"]
        if self.variables.get("capability_gap"):
            output["capability_gap"] = self.variables["capability_gap"]
        if self.variables.get("tool_results"):
            output["tool_results"] = self.variables["tool_results"]
        if self.variables.get("failure_report"):
            output["failure_report"] = self.variables["failure_report"]
        return output


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
