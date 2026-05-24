"""Executor 执行结果结构。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class StepResult:
    step_id: str
    action: str
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionResult:
    plan_id: str
    success: bool
    step_results: list[StepResult]
    final_output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["step_results"] = [result.to_dict() for result in self.step_results]
        return data


def dump_execution_result(result: ExecutionResult, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
