"""日志查询工具适配器。"""

from __future__ import annotations

import os
from typing import Any

from tools.base import ToolResult, tool_not_configured, tool_not_implemented
from tools.redaction import redact_value
from tools.tool_config import get_nested, load_tool_config


TOOL_NAME = "query_trace_log"


def query_trace_log(trace_id: str, env: str = "test", service: str | None = None, limit: int = 50) -> ToolResult:
    """按 traceId/requestId 查询日志。

    这个版本只负责配置驱动和安全兜底，不硬编码任何真实日志平台。
    后端适配器未配置或未实现时，会返回结构化错误。
    """
    trace_id = (trace_id or "").strip()
    env = (env or "test").strip()
    if not trace_id:
        return ToolResult(
            tool=TOOL_NAME,
            success=False,
            error="missing_trace_id",
            warnings=["trace_id is required"],
        )

    config = load_tool_config()
    log_config = get_nested(config, ["log", "envs", env])
    if not isinstance(log_config, dict):
        return tool_not_configured(
            TOOL_NAME,
            missing_config=[f"log.envs.{env}"],
            warnings=["Create tools/config/tools.local.json from tools/config/tools.example.json."],
        )

    backend = str(log_config.get("backend") or config.get("log", {}).get("default_backend") or "").strip()
    endpoint = str(log_config.get("endpoint") or "").strip()
    topic = str(log_config.get("topic") or "").strip()
    auth_env = str(log_config.get("auth_env") or "").strip()

    missing = []
    if not backend:
        missing.append(f"log.envs.{env}.backend or log.default_backend")
    if not endpoint:
        missing.append(f"log.envs.{env}.endpoint")
    if not topic:
        missing.append(f"log.envs.{env}.topic")
    if backend != "mock" and auth_env and not os.getenv(auth_env):
        missing.append(f"environment variable {auth_env}")
    if missing:
        return tool_not_configured(TOOL_NAME, missing_config=missing)

    if backend == "mock":
        return query_mock_log(trace_id=trace_id, env=env, service=service, topic=topic, limit=limit)

    return tool_not_implemented(
        TOOL_NAME,
        message=f"log backend '{backend}' is configured but no adapter is implemented yet",
    )


def query_mock_log(trace_id: str, env: str, service: str | None, topic: str, limit: int) -> ToolResult:
    """给本地联调用的模拟日志结果。"""
    data: dict[str, Any] = {
        "env": env,
        "service": service,
        "topic": topic,
        "trace_id": trace_id,
        "limit": limit,
        "logs": [],
    }
    return ToolResult(
        tool=TOOL_NAME,
        success=True,
        data=redact_value(data),
        evidence=[f"mock log query accepted for trace_id={trace_id}"],
        warnings=["mock backend does not query real logs"],
    )
