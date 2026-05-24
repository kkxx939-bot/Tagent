"""用于 FAILURE_TRIAGE 的模型二级意图识别。"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from llm_client import call_llm
from prompts.prompt_failure import FAILURE_INTENT_OPTIONS, build_failure_intent_prompt


DEFAULT_CONFIDENCE = 0.3
MAX_TOKENS = 900
TEMPERATURE = 0.0


NEXT_ACTIONS = {
    "ENV_ERROR": "check_environment_availability",
    "BRANCH_VERSION_MISMATCH": "check_deployed_branch_and_version",
    "CONFIG_OR_GRAY_ERROR": "check_config_switch_and_gray_rules",
    "FRONTEND_REQUEST_ERROR": "check_browser_network_and_console",
    "BACKEND_API_ERROR": "query_backend_logs_by_trace_id",
    "CONTRACT_MISMATCH": "compare_frontend_params_and_api_contract",
    "AUTH_OR_PERMISSION_ERROR": "check_auth_token_and_permission",
    "DB_SCHEMA_OR_DATA_ERROR": "check_database_schema_and_test_data",
    "DEPENDENCY_SERVICE_ERROR": "check_downstream_dependency_status",
    "AUTOMATION_SCRIPT_ERROR": "route_to_automation_failure_fix",
    "FLAKY_OR_CONCURRENCY_ERROR": "collect_repro_steps_and_timing_evidence",
    "UNKNOWN": "ask_for_failure_triage_context",
}


@dataclass
class FailureIntentResult:
    primary_category: str
    secondary_categories: list[str]
    confidence: float
    evidence: list[str]
    missing_context: list[str]
    next_action: str
    reason: str
    raw_response: str
    is_valid: bool
    error: str | None = None


def classify_failure_intent(
    user_input: str,
    known_context: dict[str, Any] | None = None,
) -> dict[str, object]:
    """识别失败排查场景下的二级意图。"""
    context = {
        "user_input": user_input,
        "known_context": known_context or {},
    }
    messages = build_failure_intent_prompt(context)

    try:
        response_text = call_llm(messages, temperature=TEMPERATURE, max_tokens=MAX_TOKENS)
    except RuntimeError as exc:
        return asdict(build_invalid_result(raw_response="", error=f"LLM 调用失败: {exc}"))

    try:
        payload = parse_failure_response(response_text)
        return asdict(build_validated_result(payload, response_text))
    except (json.JSONDecodeError, ValueError) as exc:
        return asdict(build_invalid_result(raw_response=response_text, error=str(exc)))


def parse_failure_response(response_text: str) -> dict[str, Any]:
    text = remove_markdown_fence(response_text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = json.loads(extract_json_object(text))

    if not isinstance(data, dict):
        raise ValueError("失败二级意图返回的 JSON 不是对象。")
    return data


def build_validated_result(payload: dict[str, Any], raw_response: str) -> FailureIntentResult:
    primary_category = normalize_category(payload.get("primary_category"))
    confidence = normalize_confidence(payload.get("confidence"))
    evidence = normalize_string_list(payload.get("evidence"))
    missing_context = normalize_string_list(payload.get("missing_context"))
    reason = str(payload.get("reason") or "")

    if primary_category not in FAILURE_INTENT_OPTIONS:
        return build_invalid_result(raw_response=raw_response, error=f"非法失败类别: {primary_category}")

    if confidence < 0.55 and primary_category != "UNKNOWN":
        primary_category = "UNKNOWN"
        reason = reason or "模型置信度低于阈值，降级为 UNKNOWN。"

    return FailureIntentResult(
        primary_category=primary_category,
        secondary_categories=normalize_secondary_categories(payload.get("secondary_categories"), primary_category),
        confidence=confidence,
        evidence=evidence,
        missing_context=missing_context,
        next_action=str(payload.get("next_action") or NEXT_ACTIONS[primary_category]),
        reason=reason,
        raw_response=raw_response,
        is_valid=True,
        error=None,
    )


def build_invalid_result(raw_response: str, error: str) -> FailureIntentResult:
    return FailureIntentResult(
        primary_category="UNKNOWN",
        secondary_categories=[],
        confidence=DEFAULT_CONFIDENCE,
        evidence=["失败二级意图识别不可用，降级为 UNKNOWN"],
        missing_context=["环境", "错误现象", "接口状态码/response", "traceId/requestId", "复现步骤"],
        next_action=NEXT_ACTIONS["UNKNOWN"],
        reason="需要补充失败排查上下文。",
        raw_response=raw_response,
        is_valid=False,
        error=error,
    )


def normalize_category(value: Any) -> str:
    return str(value or "UNKNOWN").strip().upper()


def normalize_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return DEFAULT_CONFIDENCE
    return max(0.0, min(confidence, 1.0))


def normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def normalize_secondary_categories(value: Any, primary_category: str) -> list[str]:
    if not isinstance(value, list):
        return []

    categories = []
    for item in value:
        category = normalize_category(item)
        if category not in FAILURE_INTENT_OPTIONS:
            continue
        if category in {"UNKNOWN", primary_category}:
            continue
        categories.append(category)
    return categories[:3]


def remove_markdown_fence(text: str) -> str:
    text = (text or "").strip()
    if not text.startswith("```"):
        return text

    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("失败二级意图返回内容中没有找到 JSON 对象。")
    return text[start : end + 1]


def main() -> None:
    result = classify_failure_intent("登录接口返回 500，有 traceId=abc123，帮我看一下")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
