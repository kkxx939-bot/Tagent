"""外部工具的权限检查。"""

from __future__ import annotations


def ensure_read_only_sql(sql: str) -> None:
    """后续 DB 工具只允许只读 SQL。"""
    normalized = " ".join((sql or "").strip().lower().split())
    if not normalized.startswith(("select", "show", "describe", "explain")):
        raise PermissionError("Only read-only SQL is allowed.")


def require_permission(tool_name: str, reason: str) -> None:
    """人工授权流程的占位入口。"""
    raise PermissionError(f"{tool_name} requires permission: {reason}")
