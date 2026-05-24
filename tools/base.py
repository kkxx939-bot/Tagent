"""工具元数据和统一返回结构。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable


ToolHandler = Callable[..., "ToolResult"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    category: str
    handler: ToolHandler
    tool_type: str = "external"
    risk_level: str = "medium"
    requires_config: bool = True
    requires_permission: bool = False
    implemented: bool = False


@dataclass
class ToolResult:
    tool: str
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    missing_config: list[str] = field(default_factory=list)
    redacted: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def tool_not_configured(tool: str, missing_config: list[str], warnings: list[str] | None = None) -> ToolResult:
    return ToolResult(
        tool=tool,
        success=False,
        warnings=warnings or [],
        error="tool_not_configured",
        missing_config=missing_config,
    )


def tool_not_implemented(tool: str, message: str = "tool adapter is not implemented") -> ToolResult:
    return ToolResult(
        tool=tool,
        success=False,
        warnings=[message],
        error="tool_not_implemented",
    )
