"""
API 文档处理。

目标：
1. 把 OpenAPI/YAML、Markdown、CSV、纯文本接口说明转成统一 JSONL。
2. 接口本身输出为 api_endpoint。
3. 请求/响应字段输出为 api_field。
4. 错误码输出为 api_error_code。

API 文档通常比需求和用例更不规范，所以这一版采用：
结构化格式优先解析；非结构化文本用正则尽量抽取；原始内容保留在 raw/content 中。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_DIR = PROJECT_ROOT / "data" / "api_docs"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "processed" / "api_items.jsonl"

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}


@dataclass
class ApiItem:
    item_type: str
    source_file: str
    title: str
    method: str | None = None
    path: str | None = None
    field_name: str | None = None
    required: str | None = None
    location: str | None = None
    error_code: str | None = None
    description: str | None = None
    content: str | None = None
    raw: dict[str, Any] | None = None


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def display_path(path: Path) -> str:
    """保存项目内相对路径，避免 JSONL 里出现本机绝对目录。"""
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def parse_openapi_yaml(path: Path) -> list[ApiItem]:
    source_file = display_path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    items: list[ApiItem] = []
    if not isinstance(data, dict):
        return []

    paths = data.get("paths", {})
    for api_path, path_info in paths.items():
        if not isinstance(path_info, dict):
            continue
        for method, operation in path_info.items():
            method_upper = method.upper()
            if method_upper not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            title = clean_text(operation.get("summary")) or f"{method_upper} {api_path}"
            items.append(
                ApiItem(
                    item_type="api_endpoint",
                    source_file=source_file,
                    title=title,
                    method=method_upper,
                    path=api_path,
                    description=clean_text(operation.get("description")) or None,
                    raw={"operation": operation},
                )
            )

            schema = (
                operation.get("requestBody", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema", {})
            )
            required_fields = set(schema.get("required", [])) if isinstance(schema, dict) else set()
            properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
            for field_name, field_info in properties.items():
                field_info = field_info if isinstance(field_info, dict) else {}
                items.append(
                    ApiItem(
                        item_type="api_field",
                        source_file=source_file,
                        title=f"{method_upper} {api_path} request field {field_name}",
                        method=method_upper,
                        path=api_path,
                        field_name=field_name,
                        required="是" if field_name in required_fields else "否",
                        location="request",
                        description=clean_text(field_info.get("description")) or None,
                        raw=field_info,
                    )
                )

            responses = operation.get("responses", {})
            for status_code, response_info in responses.items():
                response_info = response_info if isinstance(response_info, dict) else {}
                items.append(
                    ApiItem(
                        item_type="api_error_code" if str(status_code) != "200" else "api_response",
                        source_file=source_file,
                        title=f"{method_upper} {api_path} response {status_code}",
                        method=method_upper,
                        path=api_path,
                        error_code=str(status_code),
                        location="response",
                        description=clean_text(response_info.get("description")) or None,
                        raw=response_info,
                    )
                )
    return items


def parse_csv_api(path: Path) -> list[ApiItem]:
    source_file = display_path(path)
    items: list[ApiItem] = []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            api_name = clean_text(row.get("接口名"))
            method = clean_text(row.get("方法")).upper()
            api_path = clean_text(row.get("路径"))
            field_name = clean_text(row.get("字段"))
            required = clean_text(row.get("必填"))
            description = clean_text(row.get("说明"))

            if method in HTTP_METHODS:
                items.append(
                    ApiItem(
                        item_type="api_field",
                        source_file=source_file,
                        title=f"{api_name} {field_name}",
                        method=method,
                        path=api_path,
                        field_name=field_name or None,
                        required=required or None,
                        location="request",
                        description=description or None,
                        raw=dict(row),
                    )
                )
            elif method == "RESPONSE":
                item_type = "api_error_code" if "code" in field_name.lower() else "api_field"
                items.append(
                    ApiItem(
                        item_type=item_type,
                        source_file=source_file,
                        title=f"{api_name} response {field_name}",
                        path=api_path,
                        field_name=field_name or None,
                        required=required or None,
                        location="response",
                        description=description or None,
                        raw=dict(row),
                    )
                )
    return items


def parse_text_api(path: Path) -> list[ApiItem]:
    source_file = display_path(path)
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = [clean_text(line) for line in text.splitlines()]
    items: list[ApiItem] = []
    current_method: str | None = None
    current_path: str | None = None
    current_title = path.stem

    endpoint_pattern = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\b\s+`?(/[A-Za-z0-9_./{}-]+)`?", re.IGNORECASE)
    inline_endpoint_pattern = re.compile(r"接口[:：]\s*(GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_./{}-]+)", re.IGNORECASE)
    field_pattern = re.compile(r"^-?\s*([A-Za-z_][A-Za-z0-9_]*)\s*[:：]?\s*([A-Za-z0-9_?/-]+)?\s*(.*)$")
    error_pattern = re.compile(r"^-?\s*(\d{3,5})\s*[= ]\s*(.+)$")
    code_equals_pattern = re.compile(r"(.+?)\s+code\s*=\s*(\d{3,5})", re.IGNORECASE)

    for line in lines:
        if not line:
            continue
        if line.startswith("#"):
            current_title = line.lstrip("#").strip() or current_title
            continue

        endpoint_match = endpoint_pattern.search(line) or inline_endpoint_pattern.search(line)
        if endpoint_match:
            current_method = endpoint_match.group(1).upper()
            current_path = endpoint_match.group(2)
            title = f"{current_method} {current_path}"
            items.append(
                ApiItem(
                    item_type="api_endpoint",
                    source_file=source_file,
                    title=title,
                    method=current_method,
                    path=current_path,
                    description=current_title if current_title != path.stem else None,
                    content=line,
                )
            )
            continue

        code_match = error_pattern.match(line)
        if code_match and current_path:
            items.append(
                ApiItem(
                    item_type="api_error_code",
                    source_file=source_file,
                    title=f"{current_path} error {code_match.group(1)}",
                    method=current_method,
                    path=current_path,
                    error_code=code_match.group(1),
                    location="response",
                    description=code_match.group(2),
                    content=line,
                )
            )
            continue

        code_equals_match = code_equals_pattern.search(line)
        if code_equals_match and current_path:
            items.append(
                ApiItem(
                    item_type="api_error_code",
                    source_file=source_file,
                    title=f"{current_path} error {code_equals_match.group(2)}",
                    method=current_method,
                    path=current_path,
                    error_code=code_equals_match.group(2),
                    location="response",
                    description=code_equals_match.group(1).strip(),
                    content=line,
                )
            )
            continue

        if current_path and (":" in line or "必填" in line or line.startswith("- ")):
            field_line = line[2:] if line.startswith("- ") else line
            field_match = field_pattern.match(field_line)
            if field_match:
                field_name = field_match.group(1)
                if field_name.lower() not in {"说明", "返回", "成功", "失败", "备注", "body"}:
                    items.append(
                        ApiItem(
                            item_type="api_field",
                            source_file=source_file,
                            title=f"{current_path} field {field_name}",
                            method=current_method,
                            path=current_path,
                            field_name=field_name,
                            required="是" if "必填" in line or "required" in line.lower() else None,
                            location="request",
                            description=clean_text(" ".join(part for part in field_match.groups()[1:] if part)) or None,
                            content=line,
                        )
                    )

    if not items:
        items.append(
            ApiItem(
                item_type="api_note",
                source_file=source_file,
                title=path.stem,
                content=clean_text(text),
            )
        )
    return items


def parse_api_file(path: Path) -> list[ApiItem]:
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        return parse_openapi_yaml(path)
    if suffix == ".csv":
        return parse_csv_api(path)
    if suffix in {".md", ".txt"}:
        return parse_text_api(path)
    return []


def parse_all_apis(api_dir: Path = DEFAULT_API_DIR) -> list[ApiItem]:
    items: list[ApiItem] = []
    for path in sorted(api_dir.iterdir()):
        if not path.is_file():
            continue
        parsed = parse_api_file(path)
        print(f"{path.name}: {len(parsed)} items")
        items.extend(parsed)
    return items


def write_jsonl(items: list[ApiItem], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for item in items:
            file.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse API docs into JSONL.")
    parser.add_argument("--api-dir", type=Path, default=DEFAULT_API_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    items = parse_all_apis(args.api_dir)
    write_jsonl(items, args.output)
    counts: dict[str, int] = {}
    for item in items:
        counts[item.item_type] = counts.get(item.item_type, 0) + 1
    print(f"total: {len(items)} items")
    print(f"by_type: {counts}")
    print(f"output: {args.output}")


if __name__ == "__main__":
    main()
