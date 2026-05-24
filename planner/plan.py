"""计划数据结构。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from uuid import uuid4


PENDING = "pending"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
SKIPPED = "skipped"


@dataclass
class PlanStep:
    step_id: str
    name: str
    action: str
    status: str = PENDING
    depends_on: list[str] = field(default_factory=list)
    inputs: dict[str, object] = field(default_factory=dict)
    outputs: dict[str, object] = field(default_factory=dict)
    requires_permission: bool = False
    tool_name: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class Plan:
    intent: str
    user_query: str
    steps: list[PlanStep]
    plan_id: str = field(default_factory=lambda: f"plan_{uuid4().hex[:12]}")
    status: str = PENDING
    is_composite: bool = False
    sub_tasks: list[str] = field(default_factory=list)
    missing_context: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["steps"] = [step.to_dict() for step in self.steps]
        return data
