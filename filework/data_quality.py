"""
处理后数据质量检查。

输入：
- data/processed/case_items.jsonl
- data/processed/requirement_items.jsonl
- data/processed/bug_items.jsonl
- data/processed/api_items.jsonl

输出：
- 控制台摘要
- data/processed/quality_report.json

这一步只检查数据，不修改数据。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
DEFAULT_OUTPUT = DEFAULT_PROCESSED_DIR / "quality_report.json"

DATASETS = {
    "case": "case_items.jsonl",
    "requirement": "requirement_items.jsonl",
    "bug": "bug_items.jsonl",
    "api": "api_items.jsonl",
}

CORE_FIELDS = ["item_type", "source_file", "title"]
CONTENT_FIELDS = ["content", "steps", "expected_result", "description", "path"]
LONG_TEXT_LIMIT = 5000

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

REQUIREMENT_RULE_KEYWORDS = {
    "业务规则": ["规则", "必须", "需要", "不允许", "允许", "只能", "不能", "应当"],
    "验收标准": ["验收", "预期", "成功", "失败", "提示"],
    "字段规则": ["字段", "必填", "可为空", "格式", "枚举", "长度"],
    "流程规则": ["流程", "步骤", "审批", "提交", "跳转", "回调", "状态"],
    "限制规则": ["限制", "超过", "最多", "最少", "有效期", "次数", "锁定", "冻结"],
}

API_CONSTRAINT_KEYWORDS = {
    "必填校验": ["必填", "required", "不能为空"],
    "枚举校验": ["enum", "app/h5", "password", "sms"],
    "错误码校验": ["错误码", "code", "400", "401", "403", "404", "423", "500"],
    "鉴权校验": ["token", "登录态", "鉴权", "权限"],
    "条件必填": ["时必填", "模式", "可为空", "非必填"],
}


@dataclass
class DatasetQuality:
    dataset: str
    file: str
    total: int = 0
    json_errors: int = 0
    item_type_counts: dict[str, int] = field(default_factory=dict)
    source_file_counts: dict[str, int] = field(default_factory=dict)
    missing_core_fields: dict[str, int] = field(default_factory=dict)
    empty_content_like_items: int = 0
    unsupported_items: int = 0
    long_content_items: list[dict[str, Any]] = field(default_factory=list)
    duplicate_titles: list[dict[str, Any]] = field(default_factory=list)
    sample_items: list[dict[str, Any]] = field(default_factory=list)
    business_topic_counts: dict[str, int] = field(default_factory=dict)
    test_dimension_counts: dict[str, int] = field(default_factory=dict)
    rule_type_counts: dict[str, int] = field(default_factory=dict)
    api_constraint_counts: dict[str, int] = field(default_factory=dict)
    business_findings: list[dict[str, Any]] = field(default_factory=list)


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return len(value) == 0
    if isinstance(value, dict):
        return len(value) == 0
    return False


def content_length(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, list):
        return len(" / ".join(str(item) for item in value))
    return len(str(value))


def item_text(item: dict[str, Any]) -> str:
    parts = [
        item.get("title"),
        item.get("content"),
        item.get("steps"),
        item.get("expected_result"),
        item.get("description"),
        item.get("module"),
        item.get("bug_type"),
        item.get("priority"),
        item.get("status"),
        item.get("method"),
        item.get("path"),
        item.get("field_name"),
        item.get("error_code"),
    ]
    path = item.get("path")
    if isinstance(path, list):
        parts.append(" ".join(str(part) for part in path))
    raw = item.get("raw")
    if isinstance(raw, dict):
        parts.extend(str(value) for value in raw.values() if value)
    return " ".join(str(part) for part in parts if part)


def match_keywords(text: str, keyword_map: dict[str, list[str]]) -> list[str]:
    matched = []
    lower_text = text.lower()
    for label, keywords in keyword_map.items():
        if any(keyword.lower() in lower_text for keyword in keywords):
            matched.append(label)
    return matched


def load_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    items: list[dict[str, Any]] = []
    errors = 0
    if not path.exists():
        return items, 1

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                errors += 1
    return items, errors


def analyze_dataset(dataset: str, path: Path) -> DatasetQuality:
    items, json_errors = load_jsonl(path)
    quality = DatasetQuality(dataset=dataset, file=str(path.relative_to(PROJECT_ROOT)), total=len(items), json_errors=json_errors)

    item_type_counts = Counter()
    source_file_counts = Counter()
    missing_core_fields = Counter()
    title_groups: dict[tuple[str, str], int] = defaultdict(int)
    long_content_items: list[dict[str, Any]] = []
    empty_content_like_items = 0
    unsupported_items = 0
    business_topic_counts = Counter()
    test_dimension_counts = Counter()
    rule_type_counts = Counter()
    api_constraint_counts = Counter()
    business_findings: list[dict[str, Any]] = []

    for index, item in enumerate(items, start=1):
        item_type = item.get("item_type")
        source_file = item.get("source_file")
        title = item.get("title")

        item_type_counts.update([item_type or "<missing>"])
        source_file_counts.update([source_file or "<missing>"])

        for field_name in CORE_FIELDS:
            if is_empty(item.get(field_name)):
                missing_core_fields.update([field_name])

        if item_type == "unsupported":
            unsupported_items += 1

        has_content_like_value = any(not is_empty(item.get(field_name)) for field_name in CONTENT_FIELDS)
        if not has_content_like_value:
            empty_content_like_items += 1

        max_content_field = None
        max_content_length = 0
        for field_name in CONTENT_FIELDS:
            length = content_length(item.get(field_name))
            if length > max_content_length:
                max_content_field = field_name
                max_content_length = length
        if max_content_length > LONG_TEXT_LIMIT:
            long_content_items.append(
                {
                    "line": index,
                    "item_type": item_type,
                    "source_file": source_file,
                    "title": title,
                    "field": max_content_field,
                    "length": max_content_length,
                }
            )

        if title and source_file:
            title_groups[(source_file, title)] += 1

        text = item_text(item)
        topics = match_keywords(text, BUSINESS_TOPIC_KEYWORDS)
        dimensions = match_keywords(text, TEST_DIMENSION_KEYWORDS)
        rule_types = match_keywords(text, REQUIREMENT_RULE_KEYWORDS) if dataset == "requirement" else []
        api_constraints = match_keywords(text, API_CONSTRAINT_KEYWORDS) if dataset == "api" else []

        business_topic_counts.update(topics or ["<unknown>"])
        test_dimension_counts.update(dimensions or ["<unknown>"])
        rule_type_counts.update(rule_types)
        api_constraint_counts.update(api_constraints)

        if len(business_findings) < 80:
            if dataset == "bug" and item_type == "bug_record":
                risk_dimensions = dimensions or ["历史Bug回归"]
                business_findings.append(
                    {
                        "line": index,
                        "finding_type": "bug_risk",
                        "source_file": source_file,
                        "title": title,
                        "topics": topics,
                        "dimensions": risk_dimensions,
                        "suggestion": f"生成相关用例时需要覆盖历史缺陷：{title}",
                    }
                )
            elif dataset == "requirement" and rule_types:
                business_findings.append(
                    {
                        "line": index,
                        "finding_type": "requirement_rule",
                        "source_file": source_file,
                        "title": title,
                        "topics": topics,
                        "rule_types": rule_types,
                    }
                )
            elif dataset == "api" and api_constraints:
                business_findings.append(
                    {
                        "line": index,
                        "finding_type": "api_constraint",
                        "source_file": source_file,
                        "title": title,
                        "path": item.get("path"),
                        "field_name": item.get("field_name"),
                        "constraints": api_constraints,
                    }
                )

    duplicate_titles = [
        {"source_file": source_file, "title": title, "count": count}
        for (source_file, title), count in title_groups.items()
        if count > 1
    ]
    duplicate_titles.sort(key=lambda item: item["count"], reverse=True)

    quality.item_type_counts = dict(item_type_counts)
    quality.source_file_counts = dict(source_file_counts)
    quality.missing_core_fields = dict(missing_core_fields)
    quality.empty_content_like_items = empty_content_like_items
    quality.unsupported_items = unsupported_items
    quality.long_content_items = sorted(long_content_items, key=lambda item: item["length"], reverse=True)[:50]
    quality.duplicate_titles = duplicate_titles[:50]
    quality.sample_items = items[:3]
    quality.business_topic_counts = dict(business_topic_counts)
    quality.test_dimension_counts = dict(test_dimension_counts)
    quality.rule_type_counts = dict(rule_type_counts)
    quality.api_constraint_counts = dict(api_constraint_counts)
    quality.business_findings = business_findings
    return quality


def build_report(processed_dir: Path) -> dict[str, Any]:
    reports = {}
    for dataset, filename in DATASETS.items():
        reports[dataset] = asdict(analyze_dataset(dataset, processed_dir / filename))

    total_items = sum(report["total"] for report in reports.values())
    total_json_errors = sum(report["json_errors"] for report in reports.values())
    total_unsupported = sum(report["unsupported_items"] for report in reports.values())

    return {
        "summary": {
            "total_items": total_items,
            "total_json_errors": total_json_errors,
            "total_unsupported_items": total_unsupported,
            "datasets": list(DATASETS.keys()),
        },
        "datasets": reports,
        "business_summary": build_business_summary(reports),
    }


def build_business_summary(reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    topic_totals = Counter()
    dimension_totals = Counter()
    for report in reports.values():
        topic_totals.update(report.get("business_topic_counts", {}))
        dimension_totals.update(report.get("test_dimension_counts", {}))

    known_topics = {topic for topic in topic_totals if topic != "<unknown>"}
    known_dimensions = {dimension for dimension in dimension_totals if dimension != "<unknown>"}
    missing_core_dimensions = sorted(set(TEST_DIMENSION_KEYWORDS) - known_dimensions)

    return {
        "business_topic_counts": dict(topic_totals),
        "test_dimension_counts": dict(dimension_totals),
        "covered_topics": sorted(known_topics),
        "missing_core_dimensions": missing_core_dimensions,
        "note": "This is keyword-based business profiling, used as a first-pass QA data quality signal.",
    }


def write_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def print_summary(report: dict[str, Any], output_path: Path) -> None:
    summary = report["summary"]
    print(f"total_items: {summary['total_items']}")
    print(f"total_json_errors: {summary['total_json_errors']}")
    print(f"total_unsupported_items: {summary['total_unsupported_items']}")
    print()

    for dataset, detail in report["datasets"].items():
        print(f"[{dataset}]")
        print(f"  file: {detail['file']}")
        print(f"  total: {detail['total']}")
        print(f"  item_type_counts: {detail['item_type_counts']}")
        print(f"  missing_core_fields: {detail['missing_core_fields']}")
        print(f"  empty_content_like_items: {detail['empty_content_like_items']}")
        print(f"  unsupported_items: {detail['unsupported_items']}")
        print(f"  long_content_items: {len(detail['long_content_items'])}")
        print(f"  duplicate_titles: {len(detail['duplicate_titles'])}")
        print(f"  business_topic_counts: {detail['business_topic_counts']}")
        print(f"  test_dimension_counts: {detail['test_dimension_counts']}")
        if detail["rule_type_counts"]:
            print(f"  rule_type_counts: {detail['rule_type_counts']}")
        if detail["api_constraint_counts"]:
            print(f"  api_constraint_counts: {detail['api_constraint_counts']}")
        print()

    business_summary = report["business_summary"]
    print("[business_summary]")
    print(f"  covered_topics: {business_summary['covered_topics']}")
    print(f"  missing_core_dimensions: {business_summary['missing_core_dimensions']}")
    print()

    print(f"report: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check processed JSONL data quality.")
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    report = build_report(args.processed_dir)
    write_report(report, args.output)
    print_summary(report, args.output)


if __name__ == "__main__":
    main()
