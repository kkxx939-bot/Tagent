"""基于模型的主意图识别器。

这里负责调用模型并校验结构化输出；模型不可用时怎么兜底由主路由决定。
"""

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
from prompts.prompt_intent import MAIN_INTENT_OPTIONS, build_main_intent_prompt


DEFAULT_CONFIDENCE = 0.3
MAX_TOKENS = 700
TEMPERATURE = 0.0


@dataclass
class LlmIntentFallbackResult:
    intent: str
    confidence: float
    evidence: list[str]
    alternative_intents: list[dict[str, object]]
    reason: str
    raw_response: str
    is_valid: bool
    error: str | None = None


def classify_main_intent_with_llm(
    user_input: str,
    rule_result: dict[str, Any] | None = None,
    rule_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, object]:
    """调用模型识别主意图，并返回校验后的结果。"""
    context = {
        "user_input": user_input,
        "rule_result": rule_result or {},
        "rule_candidates": rule_candidates or [],
    }
    messages = build_main_intent_prompt(context)

    try:
        response_text = call_llm(messages, temperature=TEMPERATURE, max_tokens=MAX_TOKENS)
    except RuntimeError as exc:
        return asdict(build_invalid_result(raw_response="", error=f"LLM 调用失败: {exc}"))

    try:
        payload = parse_fallback_response(response_text)
        return asdict(build_validated_result(payload, response_text))
    except (json.JSONDecodeError, ValueError) as exc:
        return asdict(build_invalid_result(raw_response=response_text, error=str(exc)))


def parse_fallback_response(response_text: str) -> dict[str, Any]:
    """把模型输出解析成 JSON 对象。"""
    text = remove_markdown_fence(response_text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = json.loads(extract_json_object(text))

    if not isinstance(data, dict):
        raise ValueError("模型兜底返回的 JSON 不是对象。")
    return data


def build_validated_result(payload: dict[str, Any], raw_response: str) -> LlmIntentFallbackResult:
    intent = normalize_intent(payload.get("intent"))
    confidence = normalize_confidence(payload.get("confidence"))
    evidence = normalize_string_list(payload.get("evidence"))
    alternative_intents = normalize_alternative_intents(payload.get("alternative_intents"))
    reason = str(payload.get("reason") or "")

    if intent not in MAIN_INTENT_OPTIONS:
        return build_invalid_result(raw_response=raw_response, error=f"非法 intent: {intent}")

    if confidence < 0.55 and intent != "OUT_OF_SCOPE":
        intent = "OUT_OF_SCOPE"
        reason = reason or "模型置信度低于阈值，降级为 OUT_OF_SCOPE。"

    return LlmIntentFallbackResult(
        intent=intent,
        confidence=confidence,
        evidence=evidence,
        alternative_intents=alternative_intents,
        reason=reason,
        raw_response=raw_response,
        is_valid=True,
        error=None,
    )


def build_invalid_result(raw_response: str, error: str) -> LlmIntentFallbackResult:
    return LlmIntentFallbackResult(
        intent="OUT_OF_SCOPE",
        confidence=DEFAULT_CONFIDENCE,
        evidence=["模型主意图识别不可用，降级为 OUT_OF_SCOPE"],
        alternative_intents=[],
        reason="当前无法进入明确的测试任务流程。",
        raw_response=raw_response,
        is_valid=False,
        error=error,
    )


def normalize_intent(value: Any) -> str:
    return str(value or "OUT_OF_SCOPE").strip().upper()


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


def normalize_alternative_intents(value: Any) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []

    alternatives = []
    for item in value:
        if not isinstance(item, dict):
            continue
        intent = normalize_intent(item.get("intent"))
        if intent not in MAIN_INTENT_OPTIONS or intent == "OUT_OF_SCOPE":
            continue
        alternatives.append(
            {
                "intent": intent,
                "confidence": normalize_confidence(item.get("confidence")),
                "reason": str(item.get("reason") or ""),
            }
        )
    return alternatives[:3]


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
        raise ValueError("模型兜底返回内容中没有找到 JSON 对象。")
    return text[start : end + 1]


def main() -> None:
    result = classify_main_intent_with_llm(
        user_input="登录接口返回500，帮我写回归测试用例",
        rule_result={"intent": "OUT_OF_SCOPE", "confidence": 0.3},
        rule_candidates=[
            {"intent": "FAILURE_TRIAGE", "confidence": 0.36},
            {"intent": "CASE_GENERATION", "confidence": 0.84},
        ],
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
