"""计划校验。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from planner.actions import (
    ASK_USER,
    CALL_TOOL,
    FINISH,
    GENERATE_ARTIFACT,
    LOAD_CONTEXT,
    REPORT_CAPABILITY_GAP,
    SAVE_ARTIFACT,
    VALIDATE_ARTIFACT,
    get_action_spec,
)
from planner.plan import Plan

try:
    from tools.registry import get_tool
except ModuleNotFoundError:
    get_tool = None


@dataclass
class PlanValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def validate_plan(plan: Plan) -> PlanValidationResult:
    # TODO(Planner优化): 接 Executor 后，校验 action 是否存在可执行 handler。
    # TODO(Planner优化): 后续补充 step_id 连续性、依赖环、finish 是否最后一步等校验。
    errors = []
    warnings = []

    if not plan.steps:
        errors.append("计划必须至少包含一个步骤")

    step_ids = [step.step_id for step in plan.steps]
    duplicated_ids = sorted({step_id for step_id in step_ids if step_ids.count(step_id) > 1})
    if duplicated_ids:
        errors.append(f"存在重复 step_id：{duplicated_ids}")

    known_step_ids = set(step_ids)
    ask_user_index = next((index for index, step in enumerate(plan.steps) if step.action == ASK_USER), None)
    for step in plan.steps:
        action_spec = get_action_spec(step.action)
        if not action_spec:
            errors.append(f"{step.step_id} 使用了未注册 action：{step.action}")
            continue

        for dependency in step.depends_on:
            if dependency not in known_step_ids:
                errors.append(f"{step.step_id} 依赖不存在的步骤：{dependency}")

        tool_name = step.tool_name or step.inputs.get("tool_name")
        if action_spec.requires_tool and not tool_name:
            errors.append(f"{step.step_id} action={step.action} 需要指定 tool_name")
        if action_spec.requires_tool and tool_name and get_tool and get_tool(str(tool_name)) is None:
            errors.append(f"{step.step_id} 指定了未注册工具：{tool_name}")

        if action_spec.requires_permission and not step.requires_permission:
            warnings.append(f"{step.step_id} action={step.action} 建议标记 requires_permission=True")

        if step.action in {GENERATE_ARTIFACT, VALIDATE_ARTIFACT} and not step.inputs.get("artifact_type"):
            errors.append(f"{step.step_id} action={step.action} 需要指定 artifact_type")

        if step.action == LOAD_CONTEXT and not step.inputs.get("context_type"):
            errors.append(f"{step.step_id} action={step.action} 需要指定 context_type")

        if step.action == ASK_USER and not (step.inputs.get("message") or step.inputs.get("missing_context")):
            errors.append(f"{step.step_id} action={step.action} 需要指定 message 或 missing_context")

        if step.action == CALL_TOOL and step.inputs.get("tool_name") and not step.tool_name:
            step.tool_name = str(step.inputs["tool_name"])

        if step.action == SAVE_ARTIFACT and step.inputs.get("artifact_type") and not isinstance(step.inputs["artifact_type"], str):
            errors.append(f"{step.step_id} artifact_type 必须是字符串")

    if plan.intent == "OUT_OF_SCOPE" and not any(step.action == REPORT_CAPABILITY_GAP for step in plan.steps):
        errors.append("OUT_OF_SCOPE 意图必须包含 report_capability_gap 步骤")

    if ask_user_index is not None:
        for later_step in plan.steps[ask_user_index + 1 :]:
            if later_step.action != FINISH:
                errors.append("ask_user 后只能接 finish，不能继续执行上下文加载、工具调用或产物生成")
                break

    return PlanValidationResult(is_valid=not errors, errors=errors, warnings=warnings)
