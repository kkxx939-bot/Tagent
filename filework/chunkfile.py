"""
统一知识 chunk 生成。

输入：
- data/processed/case_items.jsonl
- data/processed/requirement_items.jsonl
- data/processed/bug_items.jsonl
- data/processed/api_items.jsonl

输出：
- data/processed/knowledge_chunks.jsonl

作用：
把需求、用例、Bug、API 统一成一种可检索结构，给后续 BM25 / 向量检索使用。
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
DEFAULT_OUTPUT = DEFAULT_PROCESSED_DIR / "knowledge_chunks.jsonl"

INPUT_FILES = {
    "case": "case_items.jsonl",
    "requirement": "requirement_items.jsonl",
    "bug": "bug_items.jsonl",
    "api": "api_items.jsonl",
}

MAX_CHARS = 1200
OVERLAP_CHARS = 160

BUSINESS_TOPIC_KEYWORDS = {
    "登录注册": ["登录", "注册", "密码", "验证码", "手机号", "短信"],
    "转账": ["转账", "收款人", "付款", "手机号转账"],
    "贷款": ["贷款", "授信", "放款", "出账", "合同", "还款", "贷后", "农贷", "个贷", "征信"],
    "订单": ["订单", "下单", "支付", "库存"],
    "退款": ["退款", "退货", "售后"],
    "优惠券": ["优惠券", "券", "活动", "领取"],
    "用户资料": ["用户资料", "头像", "昵称", "生日", "简介"],
    "车机": ["车机", "TBOX", "蓝牙", "导航", "倒车", "音乐", "收音机", "CarPlay", "CarLife"],
    "租房": ["租房", "房源", "房东", "租客", "看房", "预约"],
    "组合管理": ["组合", "调仓", "证券池", "投资日历", "自选"],
}

TEST_DIMENSION_KEYWORDS = {
    "正常流": ["成功", "正常", "可以", "允许", "正确", "有效"],
    "异常流": ["失败", "错误", "异常", "不可", "不能", "无效", "不存在", "未注册", "已下架"],
    "边界值": ["为空", "空", "最大", "最小", "超过", "少于", "大于", "小于", "长度", "次数", "过期", "超时", "限制"],
    "权限": ["权限", "角色", "管理员", "普通用户", "未登录", "登录态", "token", "鉴权", "黑名单"],
    "状态流转": ["状态", "冻结", "锁定", "已解决", "待处理", "审批", "复核", "提交", "取消", "关闭"],
    "数据校验": ["字段", "必填", "格式", "枚举", "校验", "参数", "身份证", "手机号"],
    "幂等": ["重复", "多次", "再次", "幂等", "重复提交", "重复点击"],
    "并发": ["并发", "同时", "多用户", "抢", "库存"],
    "安全": ["密码", "加密", "明文", "token", "cookie", "越权", "注入"],
    "兼容性": ["兼容", "Android", "iOS", "浏览器", "版本", "机型"],
    "性能": ["响应时间", "P95", "耗时", "性能", "并发量"],
    "历史Bug回归": ["bug", "缺陷", "崩溃", "闪退", "死机", "黑屏", "修复", "回归"],
}

PROJECT_KEYWORDS = {
    "xx租房项目": ["xx租房项目", "美客美租", "租房"],
    "手机银行": ["手机银行", "西藏银行", "XZ银行", "手机号转账"],
    "信贷业务": ["信贷", "贷款", "授信", "放款", "贷后", "农贷", "个贷"],
    "车机": ["车机", "长安汽车", "TBOX", "高德地图", "蓝牙音乐"],
    "KIMS": ["KIMS", "组合管理", "投资日历", "证券池"],
    "智慧社区": ["智慧社区", "SaaS"],
}

API_CONSTRAINT_KEYWORDS = {
    "必填校验": ["必填", "required", "不能为空"],
    "枚举校验": ["enum", "app/h5", "password", "sms"],
    "错误码校验": ["错误码", "code", "400", "401", "403", "404", "423", "500"],
    "鉴权校验": ["token", "登录态", "鉴权", "权限"],
    "条件必填": ["时必填", "模式", "可为空", "非必填"],
}


@dataclass
class KnowledgeChunk:
    chunk_id: str
    source_type: str
    item_type: str
    chunk_type: str
    source_file: str
    title: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = " / ".join(str(item) for item in value)
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def match_keywords(text: str, keyword_map: dict[str, list[str]]) -> list[str]:
    lower_text = text.lower()
    return [label for label, keywords in keyword_map.items() if any(keyword.lower() in lower_text for keyword in keywords)]


def enrich_metadata(content: str, metadata: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(metadata)
    metadata["business_topics"] = match_keywords(content, BUSINESS_TOPIC_KEYWORDS)
    metadata["test_dimensions"] = match_keywords(content, TEST_DIMENSION_KEYWORDS)
    return metadata


def infer_project(source_file: str, content: str) -> str | None:
    text = f"{source_file} {content}"
    matches = match_keywords(text, PROJECT_KEYWORDS)
    return matches[0] if matches else None


def infer_feature(content: str) -> str | None:
    matches = match_keywords(content, BUSINESS_TOPIC_KEYWORDS)
    return matches[0] if matches else None


def infer_chunk_type(source_type: str, item_type: str) -> str:
    mapping = {
        ("case", "test_case"): "case_full",
        ("case", "test_point"): "test_point_path",
        ("requirement", "requirement_section"): "requirement_text",
        ("requirement", "requirement_table_row"): "requirement_table_row",
        ("requirement", "unsupported"): "unsupported_source",
        ("bug", "bug_record"): "bug_record",
        ("bug", "bug_severity_rule"): "bug_severity_rule",
        ("api", "api_endpoint"): "api_endpoint",
        ("api", "api_field"): "api_field",
        ("api", "api_response"): "api_response",
        ("api", "api_error_code"): "api_error_code",
    }
    return mapping.get((source_type, item_type), item_type or source_type)


def api_constraints(content: str) -> list[str]:
    return match_keywords(content, API_CONSTRAINT_KEYWORDS)


def split_long_text(text: str, max_chars: int = MAX_CHARS, overlap_chars: int = OVERLAP_CHARS) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start = max(0, end - overlap_chars)
    return [chunk for chunk in chunks if chunk]


def make_chunk_id(source_type: str, index: int) -> str:
    return f"{source_type}_{index:06d}"


def content_from_case(item: dict[str, Any]) -> str:
    if item.get("item_type") == "test_case":
        parts = [
            f"测试用例：{item.get('title')}",
            f"模块：{item.get('module')}" if item.get("module") else "",
            f"用例编号：{item.get('case_id')}" if item.get("case_id") else "",
            f"操作步骤：{item.get('steps')}" if item.get("steps") else "",
            f"预期结果：{item.get('expected_result')}" if item.get("expected_result") else "",
        ]
        return clean_text("\n".join(part for part in parts if part))

    path = item.get("path") or []
    parts = [
        f"测试点：{item.get('title')}",
        f"模块：{item.get('module')}" if item.get("module") else "",
        f"路径：{' > '.join(path)}" if path else "",
    ]
    return clean_text("\n".join(part for part in parts if part))


def content_from_requirement(item: dict[str, Any]) -> str:
    if item.get("item_type") == "requirement_table_row":
        parts = [
            f"需求表格行：{item.get('title')}",
            f"工作表：{item.get('sheet')}" if item.get("sheet") else "",
            clean_text(item.get("content")),
        ]
        return clean_text("\n".join(part for part in parts if part))

    parts = [
        f"需求章节：{item.get('section_title') or item.get('title')}",
        clean_text(item.get("content")),
        f"解析错误：{item.get('error')}" if item.get("error") else "",
    ]
    return clean_text("\n".join(part for part in parts if part))


def content_from_bug(item: dict[str, Any]) -> str:
    if item.get("item_type") == "bug_severity_rule":
        parts = [
            f"Bug等级规则：{item.get('severity')}",
            f"定义：{(item.get('raw') or {}).get('definition')}" if item.get("raw") else "",
            f"详细描述：{(item.get('raw') or {}).get('detail')}" if item.get("raw") else "",
            f"示例：{item.get('description')}" if item.get("description") else "",
        ]
        return clean_text("\n".join(part for part in parts if part))

    parts = [
        f"历史Bug：{item.get('title')}",
        f"Bug ID：{item.get('bug_id')}" if item.get("bug_id") else "",
        f"类型：{item.get('bug_type')}" if item.get("bug_type") else "",
        f"状态：{item.get('status')}" if item.get("status") else "",
        f"优先级：{item.get('priority')}" if item.get("priority") else "",
        f"版本：{item.get('version')}" if item.get("version") else "",
        f"描述：{item.get('description')}" if item.get("description") else "",
    ]
    return clean_text("\n".join(part for part in parts if part))


def content_from_api(item: dict[str, Any]) -> str:
    parts = [
        f"API：{item.get('title')}",
        f"方法：{item.get('method')}" if item.get("method") else "",
        f"路径：{item.get('path')}" if item.get("path") else "",
        f"字段：{item.get('field_name')}" if item.get("field_name") else "",
        f"必填：{item.get('required')}" if item.get("required") else "",
        f"位置：{item.get('location')}" if item.get("location") else "",
        f"错误码：{item.get('error_code')}" if item.get("error_code") else "",
        f"说明：{item.get('description')}" if item.get("description") else "",
        clean_text(item.get("content")),
    ]
    return clean_text("\n".join(part for part in parts if part))


def build_item_content(source_type: str, item: dict[str, Any]) -> str:
    if source_type == "case":
        return content_from_case(item)
    if source_type == "requirement":
        return content_from_requirement(item)
    if source_type == "bug":
        return content_from_bug(item)
    if source_type == "api":
        return content_from_api(item)
    return clean_text(item.get("content") or item.get("title"))


def build_metadata(source_type: str, item: dict[str, Any], source_line: int, content: str) -> dict[str, Any]:
    metadata_keys = [
        "case_id",
        "module",
        "sheet",
        "row_index",
        "section_title",
        "bug_id",
        "bug_type",
        "status",
        "priority",
        "severity",
        "version",
        "method",
        "path",
        "field_name",
        "required",
        "location",
        "error_code",
    ]
    metadata = {key: item.get(key) for key in metadata_keys if item.get(key) not in (None, "", [])}
    metadata["source_line"] = source_line
    metadata["source_item_id"] = f"{source_type}:{source_line}"
    project = infer_project(item.get("source_file") or "", content)
    feature = infer_feature(content)
    if project:
        metadata["project"] = project
    if feature:
        metadata["feature"] = feature
    if item.get("path") and isinstance(item.get("path"), list):
        metadata["mindmap_path"] = item["path"]
    if source_type == "bug" and item.get("item_type") == "bug_record":
        metadata["risk_hint"] = f"生成相关用例时需要覆盖历史缺陷：{item.get('title')}"
        metadata["suggested_dimension"] = "历史Bug回归"
    if source_type == "api":
        constraints = api_constraints(content)
        if constraints:
            metadata["api_constraints"] = constraints
    return metadata


def build_chunks_for_items(source_type: str, items: list[dict[str, Any]], start_index: int) -> tuple[list[KnowledgeChunk], int]:
    chunks: list[KnowledgeChunk] = []
    next_index = start_index
    for source_line, item in enumerate(items, start=1):
        content = build_item_content(source_type, item)
        if not content:
            continue

        item_type = item.get("item_type") or ""
        chunk_type = infer_chunk_type(source_type, item_type)
        metadata = build_metadata(source_type, item, source_line, content)
        parts = split_long_text(content)
        for part_index, part in enumerate(parts):
            metadata_for_part = dict(metadata)
            metadata_for_part["part_index"] = part_index
            metadata_for_part["part_count"] = len(parts)
            metadata_for_part = enrich_metadata(part, metadata_for_part)

            chunks.append(
                KnowledgeChunk(
                    chunk_id=make_chunk_id(source_type, next_index),
                    source_type=source_type,
                    item_type=item_type,
                    chunk_type=chunk_type,
                    source_file=item.get("source_file") or "",
                    title=item.get("title") or "",
                    content=part,
                    metadata=metadata_for_part,
                )
            )
            next_index += 1

    return chunks, next_index


def build_all_chunks(processed_dir: Path) -> list[KnowledgeChunk]:
    all_chunks: list[KnowledgeChunk] = []
    for source_type, filename in INPUT_FILES.items():
        items = load_jsonl(processed_dir / filename)
        chunks, _ = build_chunks_for_items(source_type, items, 1)
        print(f"{filename}: {len(items)} items -> {len(chunks)} chunks")
        all_chunks.extend(chunks)
    return all_chunks


def write_jsonl(chunks: list[KnowledgeChunk], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for chunk in chunks:
            file.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build unified knowledge chunks.")
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    chunks = build_all_chunks(args.processed_dir)
    write_jsonl(chunks, args.output)

    counts: dict[str, int] = {}
    for chunk in chunks:
        counts[chunk.source_type] = counts.get(chunk.source_type, 0) + 1
    print(f"total_chunks: {len(chunks)}")
    print(f"by_source_type: {counts}")
    print(f"output: {args.output}")


if __name__ == "__main__":
    main()
