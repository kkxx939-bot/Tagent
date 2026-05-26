"""Source 文件解析和轻量画像。

这一层只把用户给到的文件变成结构化上下文，不注册成业务意图。
业务意图仍由 IntentRouter 根据 query + source_profile 判断。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from filework.requirementsfile import parse_requirement_file

try:
    from llm_client import call_llm
except ModuleNotFoundError:
    call_llm = None


SUPPORTED_SOURCE_SUFFIXES = {
    ".doc",
    ".docx",
    ".pdf",
    ".xlsx",
    ".txt",
    ".md",
    ".csv",
    ".yaml",
    ".yml",
    ".json",
    ".log",
}

SOURCE_TYPES = {
    "requirement_document",
    "log_trace",
    "api_document",
    "bug_list",
    "test_case_file",
    "automation_project",
    "unknown",
}

ACTION_ALIASES = {
    "generate_test_cases": "generate_test_cases",
    "生成测试用例": "generate_test_cases",
    "生成case": "generate_test_cases",
    "生成 case": "generate_test_cases",
    "generate_automation": "generate_automation",
    "automation_writing": "generate_automation",
    "生成自动化脚本": "generate_automation",
    "failure_triage": "failure_triage",
    "失败排查": "failure_triage",
    "summarize_source": "summarize_source",
    "总结文档内容": "summarize_source",
    "context_search": "context_search",
    "检索相关资料": "context_search",
    "project_qa": "project_qa",
    "bug_report_generation": "bug_report_generation",
}

MAX_PROFILE_CHARS = 6000
MAX_CONTEXT_CHARS = 12000


@dataclass
class SourceProcessingResult:
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    source_profile: dict[str, Any] | None = None
    document_context: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def has_source(self) -> bool:
        return bool(self.source_refs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_refs": self.source_refs,
            "source_profile": self.source_profile,
            "document_context": self.document_context,
            "warnings": self.warnings,
        }


def process_query_sources(user_query: str) -> SourceProcessingResult:
    """从 query 中找 Source，解析文件，并生成 source_profile。"""
    refs = extract_source_refs(user_query)
    if not refs:
        return SourceProcessingResult()

    documents = []
    warnings = []
    for ref in refs:
        if ref.get("type") != "local_file":
            if ref.get("type") == "unresolved_reference":
                warnings.append("识别到文档引用，但缺少明确文件路径或上传文件。")
            else:
                warnings.append(f"暂不支持读取 Source 类型：{ref.get('type')}")
            continue
        if not ref.get("exists"):
            warnings.append(f"Source 文件不存在：{ref.get('path')}")
            continue
        document, parse_warnings = _parse_local_file(Path(str(ref["path"])))
        warnings.extend(parse_warnings)
        if document:
            documents.append(document)

    document_context = _build_document_context(documents) if documents else None
    source_profile = _profile_source(user_query, document_context, refs)
    return SourceProcessingResult(
        source_refs=refs,
        source_profile=source_profile,
        document_context=document_context,
        warnings=warnings,
    )


def extract_source_refs(user_query: str) -> list[dict[str, Any]]:
    """抽取 query 中的本地文件路径和 URL 引用。"""
    text = user_query or ""
    refs: list[dict[str, Any]] = []

    for url in _extract_urls(text):
        refs.append({"type": "url", "url": url, "status": "unresolved"})

    for raw_path in _extract_desktop_path_candidates(text):
        ref = _local_file_ref(Path(raw_path).expanduser())
        if ref and ref not in refs:
            refs.append(ref)

    for raw_path in _extract_path_candidates(text):
        ref = _local_file_ref(Path(raw_path).expanduser())
        if ref and ref not in refs:
            refs.append(ref)

    if not refs:
        unresolved = _extract_unresolved_source_ref(text)
        if unresolved:
            refs.append(unresolved)

    return refs


def _extract_urls(text: str) -> list[str]:
    return [match.group(0).rstrip("，。；,;") for match in re.finditer(r"https?://\S+", text or "")]


def _extract_desktop_path_candidates(text: str) -> list[str]:
    if "桌面" not in (text or ""):
        return []
    filenames = _extract_file_names(text)
    desktop = Path.home() / "Desktop"
    return [str(desktop / filename) for filename in filenames]


def _extract_path_candidates(text: str) -> list[str]:
    text = re.sub(r"https?://\S+", " ", text or "")
    candidates: list[str] = []
    quoted_patterns = [
        r"[\"'“”‘’]([^\"'“”‘’]+\.(?:docx?|pdf|xlsx|txt|md|csv|ya?ml|json|log))[\"'“”‘’]",
    ]
    for pattern in quoted_patterns:
        candidates.extend(match.group(1).strip() for match in re.finditer(pattern, text or "", re.IGNORECASE))

    path_pattern = r"(?:~|/).+?\.(?:docx?|pdf|xlsx|txt|md|csv|ya?ml|json|log)"
    candidates.extend(
        match.group(0).strip().rstrip(")，。；,;") for match in re.finditer(path_pattern, text or "", re.IGNORECASE)
    )
    return _dedupe(candidates)


def _extract_file_names(text: str) -> list[str]:
    pattern = r"(?<![/\w.-])([\w\u4e00-\u9fff][\w\u4e00-\u9fff ._-]*?\.(?:docx?|pdf|xlsx|txt|md|csv|ya?ml|json|log))"
    return _dedupe(match.group(1).strip().rstrip(")，。；,;") for match in re.finditer(pattern, text or "", re.IGNORECASE))


def _local_file_ref(path: Path) -> dict[str, Any] | None:
    suffix = path.suffix.lower()
    if suffix and suffix not in SUPPORTED_SOURCE_SUFFIXES:
        return None
    return {
        "type": "local_file",
        "path": str(path),
        "exists": path.exists(),
        "suffix": suffix,
        "name": path.name,
    }


def _extract_unresolved_source_ref(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    if "桌面" in text and any(keyword in text for keyword in ("文档", "文件", "资料")):
        return {"type": "unresolved_reference", "hint": "desktop_document", "status": "missing_source_path"}
    if any(keyword in text for keyword in ("这个文档", "该文档", "这个文件", "该文件", "上传的文档")):
        return {"type": "unresolved_reference", "hint": "mentioned_document", "status": "missing_source_path"}
    return None


def _parse_local_file(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    suffix = path.suffix.lower()
    try:
        if suffix == ".log":
            text = _read_text(path)
            items = [{"item_type": "log_text", "source_file": str(path), "title": path.name, "content": text[:MAX_CONTEXT_CHARS]}]
        elif suffix == ".json":
            text = _read_text(path)
            items = [{"item_type": "json_text", "source_file": str(path), "title": path.name, "content": text[:MAX_CONTEXT_CHARS]}]
        else:
            parsed_items = parse_requirement_file(path)
            items = [asdict(item) for item in parsed_items]
    except Exception as exc:
        return None, [f"解析 Source 文件失败：{path}，{type(exc).__name__}: {exc}"]

    errors = [str(item.get("error")) for item in items if isinstance(item, dict) and item.get("error")]
    warnings.extend(errors)
    content = _items_to_text(items)
    return (
        {
            "path": str(path),
            "name": path.name,
            "suffix": suffix,
            "item_count": len(items),
            "items": items[:20],
            "content_preview": content[:MAX_CONTEXT_CHARS],
        },
        warnings,
    )


def _read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return path.read_text(encoding=encoding, errors="replace")
        except UnicodeError:
            continue
    return path.read_text(errors="replace")


def _items_to_text(items: list[dict[str, Any]]) -> str:
    parts = []
    for item in items:
        title = str(item.get("section_title") or item.get("title") or "").strip()
        content = str(item.get("content") or "").strip()
        raw = item.get("raw")
        if not content and raw:
            content = json.dumps(raw, ensure_ascii=False)
        if title or content:
            parts.append("\n".join(part for part in (title, content) if part))
    return "\n\n".join(parts)


def _build_document_context(documents: list[dict[str, Any]]) -> dict[str, Any]:
    content = "\n\n".join(
        f"【Source 文件】{document['name']}\n{document.get('content_preview') or ''}" for document in documents
    )
    return {
        "source_files": [
            {
                "path": document["path"],
                "name": document["name"],
                "suffix": document["suffix"],
                "item_count": document["item_count"],
            }
            for document in documents
        ],
        "content": content[:MAX_CONTEXT_CHARS],
        "documents": documents,
    }


def _profile_source(
    user_query: str,
    document_context: dict[str, Any] | None,
    refs: list[dict[str, Any]],
) -> dict[str, Any]:
    text = (document_context or {}).get("content") or ""
    model_profile = _model_profile(user_query, text)
    fallback_profile = _fallback_profile(user_query, text, refs)
    if model_profile:
        return _normalize_profile(_merge_profile(fallback_profile, model_profile))
    return _normalize_profile(fallback_profile)


def _model_profile(user_query: str, source_text: str) -> dict[str, Any] | None:
    if call_llm is None or not source_text.strip():
        return None
    prompt = [
        {
            "role": "system",
            "content": (
                "你是 Test Agent 的 Source 理解器。只输出 JSON，不要解释。"
                "识别用户给到的文件类型、摘要、业务域、模块、关键主题和可能动作。"
            ),
        },
        {
            "role": "user",
            "content": (
                "用户输入：\n"
                f"{user_query}\n\n"
                "Source 内容节选：\n"
                f"{source_text[:MAX_PROFILE_CHARS]}\n\n"
                "输出 JSON 字段：source_type, confidence, summary, domain, module, "
                "key_topics, detected_actions, possible_actions, evidence。"
                "source_type 只能是 requirement_document, log_trace, api_document, "
                "bug_list, test_case_file, automation_project, unknown。"
            ),
        },
    ]
    try:
        raw = call_llm(prompt, temperature=0.1, max_tokens=900)
        payload = _parse_json(raw)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _fallback_profile(user_query: str, source_text: str, refs: list[dict[str, Any]]) -> dict[str, Any]:
    haystack = (source_text or "").lower()
    source_type, evidence = _classify_source_type(haystack, refs)
    key_topics = _extract_key_topics(source_text)
    detected_actions = _detect_actions(user_query, source_type)
    possible_actions = _possible_actions(source_type)
    return {
        "source_type": source_type,
        "confidence": 0.72 if source_type != "unknown" else 0.35,
        "summary": _build_summary(source_type, source_text, key_topics),
        "domain": _first_topic(key_topics, ("商场", "商城", "银行", "信贷", "租房", "车机")),
        "module": _first_topic(key_topics, ("登录", "注册", "订单", "支付", "退款", "房源", "贷款", "接口")),
        "key_topics": key_topics,
        "detected_actions": detected_actions,
        "possible_actions": possible_actions,
        "evidence": evidence,
    }


def _classify_source_type(text: str, refs: list[dict[str, Any]]) -> tuple[str, list[str]]:
    suffixes = {str(ref.get("suffix") or "").lower() for ref in refs}
    evidence = []
    log_hits = _matched_keywords(text, ("exception", "stacktrace", "traceid", "requestid", "error", "timeout"))
    if ".log" in suffixes or len(log_hits) >= 2:
        evidence.append("出现日志/异常/trace 相关特征")
        return "log_trace", evidence
    api_hits = _matched_keywords(text, ("接口地址", "请求方式", "请求参数", "响应字段", "openapi", "swagger", "endpoint"))
    if len(api_hits) >= 2:
        evidence.append("出现接口文档字段")
        return "api_document", evidence
    bug_hits = _matched_keywords(text, ("缺陷等级", "复现步骤", "实际结果", "期望结果", "缺陷编号", "bug编号", "bug清单"))
    if len(bug_hits) >= 2:
        evidence.append("出现 Bug 清单字段")
        return "bug_list", evidence
    case_hits = _matched_keywords(text, ("测试用例", "前置条件", "测试步骤", "预期结果", "case_id"))
    if len(case_hits) >= 2:
        evidence.append("出现测试用例字段")
        return "test_case_file", evidence
    requirement_hits = _matched_keywords(text, ("需求说明书", "功能需求", "业务规则", "输入输出", "字段说明", "验收标准"))
    if len(requirement_hits) >= 2 or "需求说明书" in requirement_hits:
        evidence.append("出现需求文档字段")
        return "requirement_document", evidence
    return "unknown", ["未命中稳定 Source 类型特征"]


def _matched_keywords(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [keyword for keyword in keywords if keyword in (text or "")]


def _detect_actions(user_query: str, source_type: str) -> list[str]:
    text = (user_query or "").lower()
    actions = []
    if any(
        keyword in text
        for keyword in ("生成用例", "生成测试用例", "生成case", "生成 case", "写用例", "设计用例", "整理用例")
    ):
        actions.append("generate_test_cases")
    if any(keyword in text for keyword in ("自动化", "playwright", "selenium", "pytest")):
        actions.append("generate_automation")
    if any(keyword in text for keyword in ("排查", "报错", "错误", "失败", "看一下", "分析")):
        actions.append("failure_triage")
    if any(keyword in text for keyword in ("总结", "摘要", "概括")):
        actions.append("summarize_source")
    if not actions and source_type == "log_trace":
        actions.append("failure_triage")
    return _dedupe(actions)


def _possible_actions(source_type: str) -> list[str]:
    mapping = {
        "requirement_document": ["generate_test_cases", "context_search", "project_qa"],
        "api_document": ["generate_test_cases", "context_search", "project_qa"],
        "bug_list": ["context_search", "failure_triage", "bug_report_generation"],
        "test_case_file": ["automation_writing", "result_review"],
        "log_trace": ["failure_triage", "bug_report_generation"],
    }
    return mapping.get(source_type, ["summarize_source"])


def _extract_key_topics(text: str) -> list[str]:
    candidates = ("商场", "商城", "银行", "信贷", "租房", "车机", "登录", "注册", "订单", "支付", "退款", "房源", "贷款", "接口")
    return [keyword for keyword in candidates if keyword in (text or "")]


def _build_summary(source_type: str, source_text: str, key_topics: list[str]) -> str:
    type_name = {
        "requirement_document": "需求文档",
        "log_trace": "日志/错误文件",
        "api_document": "接口文档",
        "bug_list": "Bug 清单",
        "test_case_file": "测试用例文件",
        "automation_project": "自动化项目",
        "unknown": "未知类型文件",
    }.get(source_type, source_type)
    topics = "、".join(key_topics[:6]) if key_topics else "暂未识别到明确业务主题"
    preview = " ".join((source_text or "").split())[:180]
    return f"识别到 {type_name}，主题：{topics}。内容节选：{preview}"


def _merge_profile(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    profile = dict(base)
    for key in ("summary", "domain", "module"):
        value = incoming.get(key)
        if value:
            profile[key] = value
    if incoming.get("source_type") in SOURCE_TYPES:
        profile["source_type"] = incoming["source_type"]
    for key in ("key_topics", "detected_actions", "possible_actions", "evidence"):
        profile[key] = _dedupe([*_as_list(base.get(key)), *_as_list(incoming.get(key))])
    if isinstance(incoming.get("confidence"), (int, float)):
        profile["confidence"] = max(float(profile.get("confidence") or 0), float(incoming["confidence"]))
    return profile


def _normalize_profile(profile: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(profile)
    if normalized.get("source_type") not in SOURCE_TYPES:
        normalized["source_type"] = "unknown"
    normalized["key_topics"] = [str(item) for item in _as_list(normalized.get("key_topics")) if item]
    normalized["evidence"] = [str(item) for item in _as_list(normalized.get("evidence")) if item]
    normalized["detected_actions"] = _normalize_actions(normalized.get("detected_actions"))
    normalized["possible_actions"] = _normalize_actions(normalized.get("possible_actions")) or _possible_actions(
        str(normalized.get("source_type") or "unknown")
    )
    return normalized


def _normalize_actions(value: Any) -> list[str]:
    actions = []
    for item in _as_list(value):
        action = ACTION_ALIASES.get(str(item).strip())
        if action:
            actions.append(action)
    return _dedupe(actions)


def _parse_json(raw: str) -> Any:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _first_topic(topics: list[str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in topics:
            return candidate
    return None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _dedupe(items: list[Any]) -> list[Any]:
    result = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result
