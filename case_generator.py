"""根据用户问题生成测试用例。

流程：
query -> 检索上下文 -> 拼 prompt -> 调用 LLM -> 解析 JSON -> 保存结果
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from config import GENERATED_DIR, ensure_output_dirs
from context import build_case_context
from llm_client import call_llm
from prompts.promptcase import build_case_generation_prompt


QUERY = "用户筛选房源后没有看到正确结果"
OUTPUT_PATH = GENERATED_DIR / "generated_cases.json"
RAW_OUTPUT_PATH = GENERATED_DIR / "generated_cases_raw.txt"

# TODO: 第二版可以改成更稳定的多阶段生成：
#       1. 先让模型生成 case plan，明确正常流/异常流/边界值/权限/历史 Bug 回归等场景。
#       2. 再按 plan 一条一条生成测试用例。
#       3. 每生成一条就做字段校验、source_chunk_ids 校验和重复用例检查。
#       4. 不合格的单条用例重试或修复，不影响其他已生成用例。

REQUIRED_CASE_FIELDS = {
    "case_id",
    "module",
    "title",
    "priority",
    "case_type",
    "precondition",
    "steps",
    "expected_result",
    "case_basis",
    "source_chunk_ids",
}


def generate_test_cases(
    query: str = QUERY,
    output_path: Path = OUTPUT_PATH,
    context_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """完整生成链路入口。"""
    context = context_override or build_case_context(query)
    context["query"] = query
    messages = build_case_generation_prompt(context)
    response_text = call_llm(messages)
    try:
        cases = parse_cases_response(response_text)
    except (json.JSONDecodeError, ValueError) as exc:
        save_raw_response(response_text, RAW_OUTPUT_PATH)
        raise RuntimeError(f"模型返回不是合法 JSON，原始内容已保存到: {RAW_OUTPUT_PATH}") from exc
    cases = normalize_cases(cases)
    validate_cases(cases)
    grounding_report = build_grounding_report(cases, context)

    result = {
        "query": query,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_summary": context.get("source_summary") or {},
        "grounding_report": grounding_report,
        "cases": cases,
    }
    save_generation_result(result, output_path)
    return result


def parse_cases_response(response_text: str) -> list[dict[str, Any]]:
    """从模型返回文本中解析测试用例 JSON。"""
    text = remove_markdown_fence(response_text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = json.loads(extract_json_object(text))
        except (json.JSONDecodeError, ValueError):
            data = json.loads(extract_json_array(text))

    if isinstance(data, dict) and isinstance(data.get("cases"), list):
        data = data["cases"]

    if not isinstance(data, list):
        raise ValueError("模型返回的 JSON 不是数组，无法作为测试用例列表。")

    return data


def normalize_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """补齐模型偶尔漏掉的字段，保证结果结构稳定。"""
    normalized = []
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            normalized.append(case)
            continue

        item = dict(case)
        item.setdefault("case_id", f"TC-{index:03d}")
        item.setdefault("module", "")
        item.setdefault("title", "")
        item.setdefault("priority", "P2")
        item.setdefault("case_type", "其他")
        item.setdefault("precondition", "")
        item.setdefault("steps", [])
        item.setdefault("expected_result", "")
        item.setdefault("case_basis", "")
        item.setdefault("source_chunk_ids", [])

        if isinstance(item["steps"], str):
            item["steps"] = split_steps(item["steps"])
        if isinstance(item["source_chunk_ids"], str):
            item["source_chunk_ids"] = [item["source_chunk_ids"]] if item["source_chunk_ids"] else []

        normalized.append(item)
    return normalized


def split_steps(steps: str) -> list[str]:
    """把模型返回的步骤字符串尽量转成步骤数组。"""
    text = steps.strip()
    if not text:
        return []

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        return [line.lstrip("0123456789.、 ") for line in lines]

    parts = [part.strip() for part in text.replace("；", ";").split(";") if part.strip()]
    return parts or [text]


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


def extract_json_array(text: str) -> str:
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("模型返回内容中没有找到 JSON 数组。")
    return text[start : end + 1]


def extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("模型返回内容中没有找到 JSON 对象。")
    return text[start : end + 1]


def validate_cases(cases: list[dict[str, Any]]) -> None:
    """做一层轻量格式校验，避免后续处理拿到坏数据。"""
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise ValueError(f"第 {index} 条用例不是 JSON 对象。")

        missing_fields = sorted(REQUIRED_CASE_FIELDS - set(case))
        if missing_fields:
            raise ValueError(f"第 {index} 条用例缺少字段: {', '.join(missing_fields)}")

        if not isinstance(case.get("steps"), list):
            raise ValueError(f"第 {index} 条用例的 steps 必须是数组。")

        if not isinstance(case.get("source_chunk_ids"), list):
            raise ValueError(f"第 {index} 条用例的 source_chunk_ids 必须是数组。")


def build_grounding_report(cases: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
    """校验用例引用的 chunk 是否来自本次召回上下文。"""
    chunks_by_id = _chunks_by_id(context.get("chunks") or [])
    available_chunk_ids = sorted(chunks_by_id)
    case_reports = []
    invalid_source_ref_count = 0
    status_counts = {"grounded": 0, "weakly_supported": 0, "unsupported": 0}

    for index, case in enumerate(cases, start=1):
        source_chunk_ids = _case_source_chunk_ids(case)
        valid_chunk_ids = [chunk_id for chunk_id in source_chunk_ids if chunk_id in chunks_by_id]
        invalid_chunk_ids = [chunk_id for chunk_id in source_chunk_ids if chunk_id not in chunks_by_id]
        invalid_source_ref_count += len(invalid_chunk_ids)
        basis = str(case.get("case_basis") or "")
        status = _grounding_status(source_chunk_ids, valid_chunk_ids, invalid_chunk_ids, basis)
        status_counts[status] += 1
        case_reports.append(
            {
                "case_id": case.get("case_id") or f"case_{index}",
                "title": case.get("title") or "",
                "status": status,
                "source_chunk_ids": source_chunk_ids,
                "valid_source_chunk_ids": valid_chunk_ids,
                "invalid_source_chunk_ids": invalid_chunk_ids,
                "evidence": [_chunk_evidence(chunks_by_id[chunk_id]) for chunk_id in valid_chunk_ids],
                "warnings": _case_grounding_warnings(status, source_chunk_ids, invalid_chunk_ids, basis),
            }
        )

    case_count = len(cases)
    warnings = _grounding_report_warnings(status_counts, invalid_source_ref_count, available_chunk_ids)
    return {
        "status": "warning" if warnings else "ok",
        "case_count": case_count,
        "available_chunk_count": len(available_chunk_ids),
        "available_chunk_ids": available_chunk_ids,
        "grounded_case_count": status_counts["grounded"],
        "weakly_supported_case_count": status_counts["weakly_supported"],
        "unsupported_case_count": status_counts["unsupported"],
        "invalid_source_ref_count": invalid_source_ref_count,
        "grounded_rate": _rate(status_counts["grounded"], case_count),
        "warnings": warnings,
        "cases": case_reports,
    }


def grounding_errors(report: dict[str, Any]) -> list[str]:
    """把 grounding report 转成会阻断产物校验的错误。"""
    if not isinstance(report, dict) or not report:
        return ["缺少 grounding_report，无法确认生成结果是否有上下文依据"]

    errors = []
    invalid_count = int(report.get("invalid_source_ref_count") or 0)
    unsupported_count = int(report.get("unsupported_case_count") or 0)
    if invalid_count:
        errors.append(f"存在 {invalid_count} 个不存在于召回上下文的 source_chunk_ids")
    if unsupported_count:
        errors.append(f"存在 {unsupported_count} 条未标明有效依据的测试用例")
    return errors


def _chunks_by_id(chunks: list[Any]) -> dict[str, dict[str, Any]]:
    result = {}
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        if chunk_id:
            result[chunk_id] = chunk
    return result


def _case_source_chunk_ids(case: dict[str, Any]) -> list[str]:
    values = case.get("source_chunk_ids") or []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []

    result = []
    for value in values:
        chunk_id = str(value or "").strip()
        if chunk_id and chunk_id not in result:
            result.append(chunk_id)
    return result


def _grounding_status(
    source_chunk_ids: list[str],
    valid_chunk_ids: list[str],
    invalid_chunk_ids: list[str],
    basis: str,
) -> str:
    if valid_chunk_ids and not invalid_chunk_ids and not _basis_marks_context_gap(basis):
        return "grounded"
    if valid_chunk_ids or _basis_marks_context_gap(basis):
        return "weakly_supported"
    if source_chunk_ids and not valid_chunk_ids:
        return "unsupported"
    return "unsupported"


def _basis_marks_context_gap(basis: str) -> bool:
    text = basis.strip()
    return any(keyword in text for keyword in ("上下文不足", "通用测试方向", "依据有限", "无明确依据"))


def _chunk_evidence(chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": chunk.get("chunk_id"),
        "source_type": chunk.get("source_type"),
        "source_file": chunk.get("source_file"),
        "title": chunk.get("title"),
    }


def _case_grounding_warnings(
    status: str,
    source_chunk_ids: list[str],
    invalid_chunk_ids: list[str],
    basis: str,
) -> list[str]:
    warnings = []
    if invalid_chunk_ids:
        warnings.append(f"引用了不存在的 source_chunk_ids: {', '.join(invalid_chunk_ids)}")
    if status == "unsupported":
        warnings.append("未引用有效上下文，也未在 case_basis 中说明上下文不足")
    if status == "weakly_supported" and not source_chunk_ids and _basis_marks_context_gap(basis):
        warnings.append("仅标记为通用测试方向，缺少可追踪 chunk 依据")
    return warnings


def _grounding_report_warnings(
    status_counts: dict[str, int],
    invalid_source_ref_count: int,
    available_chunk_ids: list[str],
) -> list[str]:
    warnings = []
    if not available_chunk_ids:
        warnings.append("本次生成没有可追踪召回 chunk，所有用例都只能视为弱依据或无依据")
    if invalid_source_ref_count:
        warnings.append("部分 source_chunk_ids 不存在于本次召回上下文")
    if status_counts["unsupported"]:
        warnings.append("部分用例未标明有效依据，建议补充上下文或重新生成")
    return warnings


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def save_generation_result(result: dict[str, Any], output_path: Path = OUTPUT_PATH) -> None:
    ensure_output_dirs()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)


def save_raw_response(response_text: str, output_path: Path = RAW_OUTPUT_PATH) -> None:
    ensure_output_dirs()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        file.write(response_text)


def print_summary(result: dict[str, Any], output_path: Path = OUTPUT_PATH) -> None:
    print(f"query: {result.get('query')}")
    print(f"case_count: {len(result.get('cases') or [])}")
    print(f"source_summary: {result.get('source_summary')}")
    print(f"output: {output_path}")


def main() -> None:
    result = generate_test_cases(QUERY, OUTPUT_PATH)
    print_summary(result, OUTPUT_PATH)


if __name__ == "__main__":
    main()
