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


def generate_test_cases(query: str = QUERY, output_path: Path = OUTPUT_PATH) -> dict[str, Any]:
    """完整生成链路入口。"""
    context = build_case_context(query)
    messages = build_case_generation_prompt(context)
    response_text = call_llm(messages)
    try:
        cases = parse_cases_response(response_text)
    except (json.JSONDecodeError, ValueError) as exc:
        save_raw_response(response_text, RAW_OUTPUT_PATH)
        raise RuntimeError(f"模型返回不是合法 JSON，原始内容已保存到: {RAW_OUTPUT_PATH}") from exc
    cases = normalize_cases(cases)
    validate_cases(cases)

    result = {
        "query": query,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_summary": context.get("source_summary") or {},
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
