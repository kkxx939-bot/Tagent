from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CaseFailure:
    check: str
    expected: Any
    actual: Any
    message: str


@dataclass
class IntentEvalResult:
    case_id: str
    expected_intent: str
    actual_intent: str | None
    passed: bool
    failures: list[CaseFailure] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    error: str | None = None


def evaluate_case(actual: dict[str, Any], expect: dict[str, Any]) -> list[CaseFailure]:
    failures: list[CaseFailure] = []
    intent_result = actual.get("intent_result") or {}
    query_context = actual.get("query_context") or {}
    extracted = intent_result.get("extracted_context") or {}
    normalized_extracted = query_context.get("extracted_context") or {}

    _check_equal(failures, "intent", expect.get("intent"), intent_result.get("intent"))
    _check_equal(failures, "is_ready", expect.get("is_ready"), intent_result.get("is_ready"))
    _check_equal(failures, "next_action", expect.get("next_action"), intent_result.get("next_action"))
    _check_equal(failures, "trace_id", expect.get("trace_id"), extracted.get("trace_id"))
    _check_equal(
        failures,
        "force_source_generation",
        expect.get("force_source_generation"),
        normalized_extracted.get("force_source_generation") or extracted.get("force_source_generation"),
    )

    _check_contains_all(failures, "target_contains", expect.get("target_contains"), extracted.get("target") or [])
    _check_contains_all(
        failures,
        "frameworks_contains",
        expect.get("frameworks_contains"),
        extracted.get("frameworks") or [],
    )
    _check_contains_all(
        failures,
        "missing_context_contains",
        expect.get("missing_context_contains"),
        intent_result.get("missing_context") or [],
    )
    _check_contains_all(
        failures,
        "alternative_intents_contains",
        expect.get("alternative_intents_contains"),
        [item.get("intent") for item in intent_result.get("alternative_intents") or [] if isinstance(item, dict)],
    )

    if "source_ref_type" in expect:
        source_refs = normalized_extracted.get("source_refs") or extracted.get("source_refs") or []
        actual_type = source_refs[0].get("type") if source_refs and isinstance(source_refs[0], dict) else None
        _check_equal(failures, "source_ref_type", expect.get("source_ref_type"), actual_type)

    if "normalized_query_contains" in expect:
        normalized_query = str(query_context.get("normalized_query") or intent_result.get("normalized_query") or "")
        expected = str(expect["normalized_query_contains"])
        if expected not in normalized_query:
            failures.append(
                CaseFailure(
                    check="normalized_query_contains",
                    expected=expected,
                    actual=normalized_query,
                    message=f"normalized_query 未包含 {expected!r}",
                )
            )

    return failures


def compute_summary(results: list[IntentEvalResult]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    intent_correct = sum(1 for result in results if result.expected_intent == result.actual_intent)
    ready_total = 0
    ready_correct = 0
    next_total = 0
    next_correct = 0
    entity_total = 0
    entity_correct = 0
    missing_total = 0
    missing_correct = 0

    for result in results:
        by_check = {failure.check for failure in result.failures}
        if any(failure.check == "is_ready" for failure in result.failures) or "ready_expected" in result.tags:
            ready_total += 1
            if "is_ready" not in by_check:
                ready_correct += 1
        if any(failure.check == "next_action" for failure in result.failures) or "next_action_expected" in result.tags:
            next_total += 1
            if "next_action" not in by_check:
                next_correct += 1

        entity_checks = {
            "target_contains",
            "frameworks_contains",
            "trace_id",
            "source_ref_type",
            "force_source_generation",
            "alternative_intents_contains",
            "normalized_query_contains",
        }
        expected_entity_checks = set(result.tags) & {f"expected:{name}" for name in entity_checks}
        if expected_entity_checks or by_check & entity_checks:
            entity_total += 1
            if not (by_check & entity_checks):
                entity_correct += 1

        if "expected:missing_context_contains" in result.tags or "missing_context_contains" in by_check:
            missing_total += 1
            if "missing_context_contains" not in by_check:
                missing_correct += 1

    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "case_pass_rate": _rate(passed, total),
        "intent_accuracy": _rate(intent_correct, total),
        "ready_accuracy": _rate(ready_correct, ready_total),
        "next_action_accuracy": _rate(next_correct, next_total),
        "entity_accuracy": _rate(entity_correct, entity_total),
        "missing_context_accuracy": _rate(missing_correct, missing_total),
        "confusion_matrix": confusion_matrix(results),
    }


def confusion_matrix(results: list[IntentEvalResult]) -> dict[str, dict[str, int]]:
    matrix: dict[str, dict[str, int]] = {}
    for result in results:
        expected = result.expected_intent or "UNKNOWN"
        actual = result.actual_intent or "UNKNOWN"
        matrix.setdefault(expected, {})
        matrix[expected][actual] = matrix[expected].get(actual, 0) + 1
    return matrix


def result_to_dict(result: IntentEvalResult) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        "expected_intent": result.expected_intent,
        "actual_intent": result.actual_intent,
        "passed": result.passed,
        "tags": result.tags,
        "error": result.error,
        "failures": [
            {
                "check": failure.check,
                "expected": failure.expected,
                "actual": failure.actual,
                "message": failure.message,
            }
            for failure in result.failures
        ],
    }


def mark_expected_tags(expect: dict[str, Any], tags: list[str]) -> list[str]:
    result = list(tags)
    if "is_ready" in expect:
        result.append("ready_expected")
    if "next_action" in expect:
        result.append("next_action_expected")
    for key in (
        "target_contains",
        "frameworks_contains",
        "trace_id",
        "source_ref_type",
        "force_source_generation",
        "alternative_intents_contains",
        "normalized_query_contains",
        "missing_context_contains",
    ):
        if key in expect:
            result.append(f"expected:{key}")
    return result


def _check_equal(failures: list[CaseFailure], check: str, expected: Any, actual: Any) -> None:
    if expected is None:
        return
    if actual != expected:
        failures.append(
            CaseFailure(
                check=check,
                expected=expected,
                actual=actual,
                message=f"{check}: 期望 {expected!r}，实际 {actual!r}",
            )
        )


def _check_contains_all(failures: list[CaseFailure], check: str, expected_items: Any, actual_items: Any) -> None:
    if expected_items is None:
        return
    expected_list = list(expected_items)
    actual_list = list(actual_items) if isinstance(actual_items, list) else []
    missing = [item for item in expected_list if item not in actual_list]
    if missing:
        failures.append(
            CaseFailure(
                check=check,
                expected=expected_list,
                actual=actual_list,
                message=f"{check}: 缺少 {missing!r}，实际 {actual_list!r}",
            )
        )


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)
