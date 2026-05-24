"""Executor 执行策略。

这里先放最小规则：哪些步骤失败后可以继续，哪些必须中断。
后续接真实环境权限时，也可以在这里统一做 tool/action 的准入判断。
"""

from __future__ import annotations

from dataclasses import dataclass

from planner.actions import FINISH, LOAD_MEMORY, SAVE_ARTIFACT, SUMMARIZE_RESULT
from planner.plan import PlanStep


@dataclass(frozen=True)
class StepPolicy:
    continue_on_failure: bool = False
    requires_permission: bool = False


SOFT_FAIL_ACTIONS = {LOAD_MEMORY, SAVE_ARTIFACT, SUMMARIZE_RESULT, FINISH}


def policy_for_step(step: PlanStep) -> StepPolicy:
    return StepPolicy(
        continue_on_failure=step.action in SOFT_FAIL_ACTIONS,
        requires_permission=bool(step.requires_permission),
    )
