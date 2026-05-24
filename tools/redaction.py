"""工具输出里的敏感信息脱敏。"""

from __future__ import annotations

import re
from typing import Any


SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(token|authorization|cookie|password|passwd|secret|api[_-]?key)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)(bearer)\s+([a-z0-9._\-]+)"),
]


def redact_text(text: str) -> str:
    redacted = str(text)
    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1)}=<REDACTED>", redacted)
    return redacted


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    return value
