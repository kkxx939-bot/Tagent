"""受限 ReAct 执行器。

这个执行器只用于需要“观察结果后再决定下一步”的少数 intent。
普通任务继续走 Planner + Executor 的稳定流水线。
"""

from __future__ import annotations

from typing import Any

from OTel.OTelClient import mark_span_error, mark_span_ok, start_span
from OTel.TraceScheme import SPAN_EXECUTOR_STEP, build_executor_step_attributes
from executor.executor import Executor, extract_trace_or_request_id
from executor.policies import policy_for_step
from executor.result import ExecutionResult, StepResult
from planner.actions import (
    ASK_USER,
    CALL_TOOL,
    FINISH,
    GENERATE_ARTIFACT,
    LOAD_CONTEXT,
    REPORT_CAPABILITY_GAP,
    SUMMARIZE_RESULT,
)
from planner.plan import COMPLETED, FAILED, RUNNING, WAITING_FOR_USER, Plan, PlanStep


REACT_INTENTS = {"FAILURE_TRIAGE", "AUTOMATION_FAILURE_FIX"}


def should_use_react(intent: str) -> bool:
    """判断当前 intent 是否进入局部 ReAct 子流程。"""
    return intent in REACT_INTENTS


class ReactExecutor:
    """只复用已注册 action/tool 的 ReAct 循环。

    这里不让模型自由调用任意工具，而是把每一步收敛到现有 Executor action。
    """

    def __init__(
        self,
        user_query: str,
        intent_result: dict[str, Any],
        selected_skill: dict[str, Any] | None = None,
        memory_manager: Any | None = None,
        execution_context: dict[str, Any] | None = None,
        max_steps: int = 8,
    ) -> None:
        self.user_query = user_query
        self.intent_result = intent_result
        self.selected_skill = selected_skill
        self.max_steps = max_steps
        self.core = Executor(
            user_query=user_query,
            memory_manager=memory_manager,
            execution_context={
                **(execution_context or {}),
                "intent_result": intent_result,
                "selected_skill": selected_skill,
            },
        )
        intent = str(intent_result.get("intent") or "OUT_OF_SCOPE")
        self.plan = Plan(
            intent=intent,
            user_query=user_query,
            steps=[],
            metadata={
                "planner_source": "react",
                "react_intents": sorted(REACT_INTENTS),
                "max_steps": max_steps,
            },
        )
        self.step_results: list[StepResult] = []
        self.react_trace: list[dict[str, Any]] = []

    def run(self) -> ExecutionResult:
        """运行局部 ReAct 流程。"""
        self.plan.status = RUNNING
        self.core.variables["plan_intent"] = self.plan.intent
        self.core.variables["plan_missing_context"] = list(self.intent_result.get("missing_context") or [])
        self.core.variables["react_trace"] = self.react_trace

        if self.plan.intent == "FAILURE_TRIAGE":
            return self._run_failure_triage()
        if self.plan.intent == "AUTOMATION_FAILURE_FIX":
            return self._run_automation_failure_fix()

        self._think("当前 intent 未接入 ReAct，返回能力边界。")
        self._execute(
            name="说明当前 ReAct 能力边界",
            action=REPORT_CAPABILITY_GAP,
            inputs={"reason": f"intent={self.plan.intent} 未接入 ReAct 子流程"},
        )
        return self._finish()

    def _run_failure_triage(self) -> ExecutionResult:
        source_context = self.core.variables.get("source_context") or {}
        if _is_source_log_trace(source_context):
            self._think("用户已提供日志类 Source，先读取日志上下文作为排查证据。")
            result = self._execute(
                name="读取失败排查上下文",
                action=LOAD_CONTEXT,
                inputs={"context_type": "failure_triage"},
            )
            if not result.success:
                return self._finish(result.error)
            self._think("日志上下文可用，整理已有证据并结束本轮排查。")
            self._execute(
                name="整理失败排查证据",
                action=SUMMARIZE_RESULT,
                inputs={"summary_type": "failure_triage"},
            )
            return self._finish()

        trace_id = self._trace_id()
        if not trace_id:
            self._think("缺少 traceId/requestId，无法进入日志查询，先向用户补充关键信息。")
            self._execute(
                name="等待用户补充排查信息",
                action=ASK_USER,
                inputs={
                    "message": "当前信息不足，请补充 traceId/requestId、环境、错误现象或日志文件后继续排查。",
                    "missing_context": self._missing_context(["traceId/requestId", "环境", "错误现象"]),
                },
            )
            return self._waiting_result()

        self._think("已识别 traceId/requestId，先检索本地上下文，再查询日志工具。")
        self._execute(
            name="读取失败排查上下文",
            action=LOAD_CONTEXT,
            inputs={"context_type": "failure_triage"},
        )
        tool_result = self._execute(
            name="按 traceId/requestId 查询日志",
            action=CALL_TOOL,
            inputs={"tool_name": "query_trace_log", "trace_id": trace_id},
            tool_name="query_trace_log",
        )
        if not tool_result.success:
            return self._finish(tool_result.error)

        if self.core.variables.get("capability_gap"):
            self._think("日志工具不可用或未配置，保留能力缺口并输出可执行的下一步。")
            self._execute(
                name="汇总工具能力缺口",
                action=SUMMARIZE_RESULT,
                inputs={"summary_type": "failure_triage"},
            )
            return self._finish()

        self._think("日志查询已有返回，生成排查报告并汇总证据。")
        self._execute(
            name="生成失败排查报告",
            action=GENERATE_ARTIFACT,
            inputs={"artifact_type": "failure_report"},
        )
        self._execute(
            name="汇总失败排查结论",
            action=SUMMARIZE_RESULT,
            inputs={"summary_type": "failure_triage"},
        )
        return self._finish()

    def _run_automation_failure_fix(self) -> ExecutionResult:
        missing_context = self._missing_context(["失败日志", "失败脚本路径", "自动化框架"])
        if missing_context or not bool(self.intent_result.get("is_ready")):
            self._think("自动化失败修复缺少失败证据或脚本位置，不能猜测式修改代码。")
            self._execute(
                name="等待用户补充自动化失败证据",
                action=ASK_USER,
                inputs={
                    "message": "请补充失败日志、失败脚本路径、自动化框架，以及截图/trace/控制台日志中的任意可用证据。",
                    "missing_context": missing_context,
                },
            )
            return self._waiting_result()

        self._think("自动化失败证据已具备，先读取自动化项目上下文。")
        context_result = self._execute(
            name="读取自动化项目上下文",
            action=LOAD_CONTEXT,
            inputs={"context_type": "automation_project"},
        )
        if not context_result.success:
            return self._finish(context_result.error)

        self._think("当前工具注册表还没有代码搜索、读写文件和运行测试工具，不能执行真实修复。")
        self._execute(
            name="说明自动化修复工具缺口",
            action=REPORT_CAPABILITY_GAP,
            inputs={
                "reason": "自动化失败修复需要 search_code/read_file/write_file/run_test 等工具；当前工具注册表尚未接入这些能力。",
                "missing_tools": ["search_code", "read_file", "write_file", "run_test"],
            },
        )
        return self._finish()

    def _execute(
        self,
        name: str,
        action: str,
        inputs: dict[str, Any] | None = None,
        tool_name: str | None = None,
        requires_permission: bool = False,
    ) -> StepResult:
        if len(self.plan.steps) >= self.max_steps:
            result = StepResult(
                step_id=f"step_{len(self.plan.steps) + 1}",
                action=action,
                success=False,
                error=f"ReAct 超过最大步数：{self.max_steps}",
            )
            self.step_results.append(result)
            return result

        step = PlanStep(
            step_id=f"step_{len(self.plan.steps) + 1}",
            name=name,
            action=action,
            depends_on=[self.plan.steps[-1].step_id] if self.plan.steps else [],
            inputs=inputs or {},
            requires_permission=requires_permission,
            tool_name=tool_name,
        )
        self.plan.steps.append(step)
        self._record_action(step)

        with start_span(
            SPAN_EXECUTOR_STEP,
            build_executor_step_attributes(plan=self.plan.to_dict(), step=step.to_dict(), index=len(self.plan.steps) - 1),
        ) as span:
            step.status = RUNNING
            handler = self.core.handlers.get(action)
            if not handler:
                result = StepResult(step_id=step.step_id, action=action, success=False, error=f"action 未实现：{action}")
            else:
                try:
                    result = handler(step)
                except Exception as exc:
                    result = StepResult(
                        step_id=step.step_id,
                        action=action,
                        success=False,
                        error=f"{type(exc).__name__}: {exc}",
                    )

            self.step_results.append(result)
            step.outputs = result.data
            step.status = COMPLETED if result.success else FAILED
            self._record_observation(step, result)
            self.core._record_step_span_result(span, self.plan, step, len(self.plan.steps) - 1, result)

            if result.success:
                self.core._record_step_note(step)
                mark_span_ok(span)
            else:
                mark_span_error(span, result.error)
                policy = policy_for_step(step)
                if not policy.continue_on_failure:
                    self.plan.status = FAILED
            return result

    def _finish(self, error: str | None = None) -> ExecutionResult:
        if error:
            return self.core._build_result(self.plan, self.step_results, error)
        if not self.step_results or self.step_results[-1].action != FINISH:
            self._think("当前 ReAct 循环已有结论，结束任务并写入记忆。")
            self._execute(name="完成任务并写入记忆", action=FINISH)
        result = self.core._build_result(self.plan, self.step_results)
        result.final_output["react_trace"] = self.react_trace
        result.final_output["execution_mode"] = "react"
        return result

    def _waiting_result(self) -> ExecutionResult:
        self.plan.status = WAITING_FOR_USER
        result = self.core._build_result(self.plan, self.step_results)
        result.final_output["react_trace"] = self.react_trace
        result.final_output["execution_mode"] = "react"
        return result

    def _trace_id(self) -> str | None:
        extracted = self.intent_result.get("extracted_context") or {}
        if isinstance(extracted, dict) and extracted.get("trace_id"):
            return str(extracted["trace_id"])
        return extract_trace_or_request_id(self.user_query)

    def _missing_context(self, fallback: list[str]) -> list[str]:
        missing = [str(item) for item in self.intent_result.get("missing_context") or [] if item]
        return missing or fallback

    def _think(self, thought: str) -> None:
        self.react_trace.append({"type": "thought", "content": thought})

    def _record_action(self, step: PlanStep) -> None:
        self.react_trace.append(
            {
                "type": "action",
                "step_id": step.step_id,
                "action": step.action,
                "name": step.name,
                "inputs": step.inputs,
                "tool_name": step.tool_name,
            }
        )

    def _record_observation(self, step: PlanStep, result: StepResult) -> None:
        self.react_trace.append(
            {
                "type": "observation",
                "step_id": step.step_id,
                "success": result.success,
                "data": result.data,
                "warnings": result.warnings,
                "error": result.error,
            }
        )


def _is_source_log_trace(source_context: dict[str, Any]) -> bool:
    profile = source_context.get("source_profile") if isinstance(source_context, dict) else {}
    return isinstance(profile, dict) and profile.get("source_type") == "log_trace"
