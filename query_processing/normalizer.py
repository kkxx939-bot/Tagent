"""Query 标准化。

这一层只做输入清洗和结构化抽取，不做最终意图判断。
后续可以在这里接模型改写和 embedding 领域别名召回。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from filework.queryfile import extract_source_refs


@dataclass
class QueryAlias:
    raw: str
    normalized: str
    source: str = "rule"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class QueryNormalizationResult:
    raw_query: str
    normalized_query: str
    aliases: list[QueryAlias] = field(default_factory=list)
    extracted_context: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.raw_query != self.normalized_query

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_query": self.raw_query,
            "normalized_query": self.normalized_query,
            "changed": self.changed,
            "aliases": [alias.to_dict() for alias in self.aliases],
            "extracted_context": self.extracted_context,
            "warnings": self.warnings,
        }


DETERMINISTIC_ALIASES: tuple[tuple[str, str], ...] = (
    ("登陆", "登录"),
    ("case", "测试用例"),
    ("request_id", "requestId"),
    ("request id", "requestId"),
    ("trace_id", "traceId"),
    ("trace id", "traceId"),
)


def normalize_query(user_query: str) -> QueryNormalizationResult:
    """把用户输入整理成 Tagent 内部标准 query。"""
    raw_query = user_query or ""
    normalized_query = _normalize_spacing(raw_query)
    aliases: list[QueryAlias] = []

    for raw, normalized in DETERMINISTIC_ALIASES:
        normalized_query, changed = _replace_alias(normalized_query, raw, normalized)
        if changed:
            aliases.append(QueryAlias(raw=raw, normalized=normalized))

    extracted_context = {
        "target": _extract_targets(normalized_query),
        "frameworks": _extract_frameworks(normalized_query),
        "trace_id": _extract_trace_or_request_id(normalized_query),
        "source_refs": extract_source_refs(normalized_query),
        "force_source_generation": _extract_force_source_generation(normalized_query),
    }
    return QueryNormalizationResult(
        raw_query=raw_query,
        normalized_query=normalized_query,
        aliases=aliases,
        extracted_context=extracted_context,
    )


def _normalize_spacing(text: str) -> str:
    return " ".join((text or "").strip().split())


def _replace_alias(text: str, raw: str, normalized: str) -> tuple[str, bool]:
    if raw.lower() == "case":
        new_text = re.sub(r"(?<![A-Za-z0-9_])case(?![A-Za-z0-9_])", normalized, text, flags=re.IGNORECASE)
        return new_text, new_text != text
    new_text = re.sub(re.escape(raw), normalized, text, flags=re.IGNORECASE)
    return new_text, new_text != text


def _extract_targets(text: str) -> list[str]:
    target_markers = (
        "登录",
        "注册",
        "房源",
        "筛选",
        "订单",
        "支付",
        "退款",
        "转账",
        "贷款",
        "接口",
        "用例",
        "case",
        "需求",
        "改动",
        "变更",
    )
    return [marker for marker in target_markers if marker in text]


def _extract_frameworks(text: str) -> list[str]:
    lower_text = text.lower()
    return [name for name in ("playwright", "selenium", "appium", "pytest", "cypress") if name in lower_text]


def _extract_trace_or_request_id(text: str) -> str | None:
    patterns = [
        r"(?i)(?:traceid|trace_id|trace id)\s*[:= ]\s*([a-z0-9._\-]+)",
        r"(?i)(?:requestid|request_id|request id)\s*[:= ]\s*([a-z0-9._\-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "")
        if match:
            return match.group(1)
    return None


def _extract_force_source_generation(text: str) -> bool:
    return any(
        keyword in (text or "")
        for keyword in (
            "force_source_generation=true",
            "force source generation=true",
            "强制生成",
            "确认生成",
            "仍按该文档",
            "就按这个文档",
            "按这个文档泛化生成",
        )
    )
