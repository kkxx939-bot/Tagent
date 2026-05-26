"""Agent 运行结果。

这个结构是 Tagent 对外返回的统一结果，避免 API、UI、评测代码直接依赖内部模块细节。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AgentResult:
    user_query: str
    success: bool
    status: str
    intent_result: dict[str, Any]
    selected_skill: dict[str, Any] | None
    plan: dict[str, Any] | None
    execution_result: dict[str, Any] | None
    final_output: dict[str, Any] = field(default_factory=dict)
    query_context: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
