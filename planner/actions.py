"""Planner 可使用的稳定动作。

action 只表达 Executor 的通用执行能力，不表达具体业务。
具体业务差异放到 inputs.artifact_type、tool_name、skill_name 等参数里。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


SELECT_SKILL = "select_skill"
LOAD_MEMORY = "load_memory"
LOAD_CONTEXT = "load_context"
CALL_TOOL = "call_tool"
GENERATE_ARTIFACT = "generate_artifact"
VALIDATE_ARTIFACT = "validate_artifact"
SAVE_ARTIFACT = "save_artifact"
SUMMARIZE_RESULT = "summarize_result"
ASK_USER = "ask_user"
REPORT_CAPABILITY_GAP = "report_capability_gap"
FINISH = "finish"


@dataclass(frozen=True)
class ActionSpec:
    name: str
    description: str
    requires_tool: bool = False
    requires_permission: bool = False
    internal: bool = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


ACTION_SPECS = {
    SELECT_SKILL: ActionSpec(SELECT_SKILL, "选择当前步骤对应的技能"),
    LOAD_MEMORY: ActionSpec(LOAD_MEMORY, "读取当前任务相关的长期记忆"),
    LOAD_CONTEXT: ActionSpec(LOAD_CONTEXT, "读取或检索任务需要的上下文"),
    CALL_TOOL: ActionSpec(CALL_TOOL, "调用外部工具", requires_tool=True, requires_permission=True, internal=False),
    GENERATE_ARTIFACT: ActionSpec(GENERATE_ARTIFACT, "生成指定类型的产物"),
    VALIDATE_ARTIFACT: ActionSpec(VALIDATE_ARTIFACT, "校验指定类型的产物"),
    SAVE_ARTIFACT: ActionSpec(SAVE_ARTIFACT, "保存或确认产物位置"),
    SUMMARIZE_RESULT: ActionSpec(SUMMARIZE_RESULT, "汇总执行结果、证据或上下文"),
    ASK_USER: ActionSpec(ASK_USER, "向用户追问缺失信息"),
    REPORT_CAPABILITY_GAP: ActionSpec(REPORT_CAPABILITY_GAP, "说明当前能力无法完成的部分"),
    FINISH: ActionSpec(FINISH, "结束任务并写入记忆"),
}


ALLOWED_ACTIONS = set(ACTION_SPECS)


def get_action_spec(action: str) -> ActionSpec | None:
    return ACTION_SPECS.get(action)


def list_actions() -> list[dict[str, object]]:
    return [spec.to_dict() for spec in ACTION_SPECS.values()]
