"""上下文加载逻辑。

Executor 只负责调度 load_context，具体怎么取上下文放在这里。
后续如果接真实文档、项目、执行报告读取，也优先扩展这个文件。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ContextLoadResult:
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    memory_payload: dict[str, Any] | None = None


def load_context(
    context_type: str,
    user_query: str,
    inputs: dict[str, Any],
    variables: dict[str, Any],
) -> ContextLoadResult:
    context_type = _normalize_context_type(context_type)
    if context_type == "requirement_document":
        return _load_requirement_document_context(user_query, inputs, variables)
    if context_type in {"rag", "case_generation", "context_search", "failure_triage"}:
        return _load_rag_context(context_type, user_query, inputs, variables)
    if context_type == "automation_project":
        return _load_automation_project_context(inputs, variables)
    if context_type == "result_file":
        return _load_result_file_context(inputs, variables)
    return ContextLoadResult(
        success=False,
        error=f"不支持的 context_type：{context_type}",
        data={"context_type": context_type},
    )


def _load_rag_context(
    context_type: str,
    user_query: str,
    inputs: dict[str, Any],
    variables: dict[str, Any],
) -> ContextLoadResult:
    from context import build_case_context

    if context_type == "failure_triage":
        source_context = variables.get("source_context") or {}
        profile = source_context.get("source_profile") if isinstance(source_context, dict) else {}
        if isinstance(profile, dict) and profile.get("source_type") == "log_trace":
            data = _build_source_log_context(source_context)
            variables["loaded_context"] = data
            variables["failure_source_context"] = data
            return ContextLoadResult(success=True, data=data)

    query = str(inputs.get("query") or user_query)
    context = build_case_context(query)
    variables["retrieved_context"] = context
    variables["loaded_context"] = context
    source_summary = context.get("source_summary") or {}
    return ContextLoadResult(
        success=True,
        data={"context_type": context_type, "source_summary": source_summary},
        memory_payload={"query": query, "source_summary": source_summary},
    )


def _load_requirement_document_context(
    user_query: str,
    inputs: dict[str, Any],
    variables: dict[str, Any],
) -> ContextLoadResult:
    source_context = variables.get("source_context") or {}
    document_context = source_context.get("document_context") if isinstance(source_context, dict) else None
    profile = source_context.get("source_profile") if isinstance(source_context, dict) else {}
    if not isinstance(document_context, dict) or not document_context.get("content"):
        data = {
            "context_type": "requirement_document",
            "missing_context": ["可解析的 Source 需求文档"],
        }
        variables["loaded_context"] = data
        return ContextLoadResult(success=False, data=data, error="缺少可解析的 Source 需求文档")

    from context import build_case_context

    retrieval_query = _source_retrieval_query(user_query, profile)
    rag_context = build_case_context(retrieval_query)
    document_chunk = _document_chunk(document_context, profile)
    source_summary = dict(rag_context.get("source_summary") or {})
    source_summary["source_document"] = {
        "count": len(document_context.get("source_files") or []),
        "source_files": [item.get("name") for item in document_context.get("source_files") or []],
        "source_type": profile.get("source_type") if isinstance(profile, dict) else None,
        "force_source_generation": _force_source_generation(variables),
    }

    context = {
        **rag_context,
        "query": user_query,
        "requirements": _format_source_requirements(document_context, profile, _force_source_generation(variables)),
        "chunks": [document_chunk, *(rag_context.get("chunks") or [])],
        "source_summary": source_summary,
        "source_profile": profile,
    }
    data = {
        "context_type": "requirement_document",
        "source_profile": profile,
        "source_summary": source_summary,
    }
    variables["retrieved_context"] = context
    variables["loaded_context"] = context
    variables["case_generation_context"] = context
    variables["requirement_document_context"] = data
    return ContextLoadResult(success=True, data=data, memory_payload={"query": retrieval_query, "source_summary": source_summary})


def _source_retrieval_query(user_query: str, profile: dict[str, Any]) -> str:
    parts = [user_query]
    if isinstance(profile, dict):
        for key in ("domain", "module"):
            if profile.get(key):
                parts.append(str(profile[key]))
        parts.extend(str(item) for item in profile.get("key_topics") or [] if item)
    return " ".join(_dedupe_text(parts))


def _format_source_requirements(
    document_context: dict[str, Any],
    profile: dict[str, Any],
    force_source_generation: bool = False,
) -> str:
    source_files = document_context.get("source_files") or []
    file_names = "、".join(str(item.get("name")) for item in source_files if item.get("name"))
    summary = profile.get("summary") if isinstance(profile, dict) else ""
    content = document_context.get("content") or ""
    return "\n".join(
        item
        for item in (
            "【用户 Source 需求文档】",
            f"source_files: {file_names}" if file_names else "",
            f"summary: {summary}" if summary else "",
            "note: 用户已明确强制基于该 Source 泛化生成测试用例，Source 未必是标准需求/API/用例文档。"
            if force_source_generation
            else "",
            "content:",
            content[:12000],
        )
        if item
    )


def _force_source_generation(variables: dict[str, Any]) -> bool:
    intent_result = variables.get("intent_result") or {}
    if isinstance(intent_result, dict):
        if intent_result.get("force_source_generation"):
            return True
        extracted = intent_result.get("extracted_context")
        if isinstance(extracted, dict) and extracted.get("force_source_generation"):
            return True
    query_context = variables.get("query_context") or {}
    extracted = query_context.get("extracted_context") if isinstance(query_context, dict) else {}
    return isinstance(extracted, dict) and bool(extracted.get("force_source_generation"))


def _document_chunk(document_context: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    source_files = document_context.get("source_files") or []
    first_file = source_files[0] if source_files else {}
    return {
        "chunk_id": "source_document_000001",
        "source_type": "source_document",
        "title": first_file.get("name") or "用户 Source 文档",
        "source_file": first_file.get("path"),
        "content": document_context.get("content") or "",
        "metadata": {
            "source_profile": profile,
            "project": profile.get("domain") if isinstance(profile, dict) else None,
            "feature": profile.get("module") if isinstance(profile, dict) else None,
        },
    }


def _build_source_log_context(source_context: dict[str, Any]) -> dict[str, Any]:
    document_context = source_context.get("document_context") or {}
    profile = source_context.get("source_profile") or {}
    content = str(document_context.get("content") or "")
    return {
        "context_type": "failure_triage",
        "source_type": "log_trace",
        "source_profile": profile,
        "log_excerpt": content[:8000],
        "source_summary": {
            "source_log": {
                "count": len(document_context.get("source_files") or []),
                "source_files": [item.get("name") for item in document_context.get("source_files") or []],
            }
        },
    }


def _load_automation_project_context(inputs: dict[str, Any], variables: dict[str, Any]) -> ContextLoadResult:
    project_path = str(inputs.get("project_path") or inputs.get("path") or "").strip()
    if not project_path:
        data = {
            "context_type": "automation_project",
            "project_path": None,
            "detected_files": [],
            "missing_context": ["自动化项目路径"],
        }
        variables["loaded_context"] = data
        variables["automation_project_context"] = data
        return ContextLoadResult(
            success=True,
            data=data,
            warnings=["缺少自动化项目路径，暂时只能生成自动化代码草稿。"],
        )

    path = Path(project_path).expanduser()
    if not path.exists():
        data = {
            "context_type": "automation_project",
            "project_path": str(path),
            "detected_files": [],
            "missing_context": ["有效的自动化项目路径"],
        }
        variables["loaded_context"] = data
        return ContextLoadResult(success=False, data=data, error=f"自动化项目路径不存在：{path}")

    detected_files = _detect_project_files(path)
    data = {
        "context_type": "automation_project",
        "project_path": str(path),
        "detected_files": detected_files,
        "framework_hints": _framework_hints(detected_files),
    }
    variables["loaded_context"] = data
    variables["automation_project_context"] = data
    return ContextLoadResult(success=True, data=data)


def _load_result_file_context(inputs: dict[str, Any], variables: dict[str, Any]) -> ContextLoadResult:
    result_path = str(inputs.get("result_path") or inputs.get("output_path") or variables.get("output_path") or "").strip()
    if not result_path:
        data = {
            "context_type": "result_file",
            "result_path": None,
            "missing_context": ["结果文件路径"],
        }
        variables["loaded_context"] = data
        return ContextLoadResult(success=True, data=data, warnings=["缺少结果文件路径，无法读取具体结果内容。"])

    path = Path(result_path).expanduser()
    if not path.exists():
        data = {"context_type": "result_file", "result_path": str(path), "exists": False}
        variables["loaded_context"] = data
        return ContextLoadResult(success=False, data=data, error=f"结果文件不存在：{path}")

    content = _read_result_file(path)
    data = {
        "context_type": "result_file",
        "result_path": str(path),
        "exists": True,
        "content": content,
    }
    variables["loaded_context"] = data
    variables["result_file_context"] = data
    return ContextLoadResult(success=True, data=data)


def _detect_project_files(path: Path) -> list[str]:
    candidates = [
        "package.json",
        "playwright.config.ts",
        "playwright.config.js",
        "pytest.ini",
        "pyproject.toml",
        "requirements.txt",
        "pom.xml",
    ]
    return [name for name in candidates if (path / name).exists()]


def _framework_hints(detected_files: list[str]) -> list[str]:
    hints = []
    if any(name.startswith("playwright.config") for name in detected_files):
        hints.append("playwright")
    if "pytest.ini" in detected_files or "pyproject.toml" in detected_files:
        hints.append("pytest")
    if "package.json" in detected_files:
        hints.append("node")
    return hints


def _read_result_file(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return text[:8000]


def _normalize_context_type(context_type: str) -> str:
    return (context_type or "rag").strip().lower()


def _dedupe_text(items: list[str]) -> list[str]:
    result = []
    for item in items:
        value = str(item or "").strip()
        if value and value not in result:
            result.append(value)
    return result
