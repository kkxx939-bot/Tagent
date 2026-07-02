"""工具注册表和统一调度入口。"""

from __future__ import annotations

import time

from OTel.OTelClient import mark_span_error, mark_span_ok, set_span_attributes, start_span
from OTel.TraceScheme import SPAN_TOOL_CALL, build_tool_call_attributes
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
    with start_span(
        SPAN_TOOL_CALL,
        build_tool_call_attributes(tool_name=name, tool_spec=tool, kwargs=kwargs),
    ) as span:
        started_at = time.perf_counter()
        if tool is None:
            result = ToolResult(tool=name, success=False, error="unknown_tool")
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            set_span_attributes(
                span,
                build_tool_call_attributes(
                    tool_name=name,
                    tool_spec=None,
                    kwargs=kwargs,
                    result=result.to_dict(),
                    latency_ms=latency_ms,
                ),
            )
            mark_span_error(span, result.error)
            return result

        try:
            result = tool.handler(**kwargs)
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            set_span_attributes(
                span,
                build_tool_call_attributes(
                    tool_name=name,
                    tool_spec=tool,
                    kwargs=kwargs,
                    success=False,
                    error=exc,
                    latency_ms=latency_ms,
                ),
            )
            mark_span_error(span, exc)
            raise

        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        set_span_attributes(
            span,
            build_tool_call_attributes(
                tool_name=name,
                tool_spec=tool,
                kwargs=kwargs,
                result=result.to_dict(),
                latency_ms=latency_ms,
            ),
        )
        if result.success:
            mark_span_ok(span)
        else:
            mark_span_error(span, result.error)
        return result
