"""工具注册表和统一调度入口。"""

from __future__ import annotations

from tools.base import ToolResult, ToolSpec
from tools.log_tool import query_trace_log


TOOLS = {
    "query_trace_log": ToolSpec(
        name="query_trace_log",
        description="根据 traceId/requestId 查询日志。",
        category="logs",
        handler=query_trace_log,
        tool_type="external",
        risk_level="medium",
        requires_config=True,
        requires_permission=False,
        implemented=False,
    ),
}


def get_tool(name: str) -> ToolSpec | None:
    return TOOLS.get(name)


def list_tools() -> list[dict[str, object]]:
    result = []
    for tool in TOOLS.values():
        result.append(
            {
                "name": tool.name,
                "description": tool.description,
                "category": tool.category,
                "tool_type": tool.tool_type,
                "risk_level": tool.risk_level,
                "requires_config": tool.requires_config,
                "requires_permission": tool.requires_permission,
                "implemented": tool.implemented,
            }
        )
    return result


def run_tool(name: str, **kwargs) -> ToolResult:
    tool = get_tool(name)
    if tool is None:
        return ToolResult(tool=name, success=False, error="unknown_tool")
    return tool.handler(**kwargs)
