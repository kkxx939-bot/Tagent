"""意图识别评测入口。

这个脚本只评测 Tagent 的前半段链路：

1. 从 jsonl 评测集读取 query 和 expect 标准答案
2. 对 query 做 normalize_query 标准化
3. 调用 recognize_main_intent 做意图识别
4. 用 metrics.evaluate_case 把实际结果和 expect 逐项比较
5. 汇总通过率、意图准确率、实体抽取准确率等指标

注意：默认不启用 LLM。这样可以先得到稳定、低成本、可复现的规则兜底基线。
如果需要评测 LLM + 规则混合效果，运行时加 --allow-llm。
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parents[1]
# 评测脚本位于 EvalTest/Eval_intent 下，直接运行时 Python 默认找不到项目根目录模块。
# 这里把项目根目录和当前评测目录加入 sys.path，方便导入 Intent、query_processing 和 metrics。
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from metrics import compute_summary, evaluate_case, mark_expected_tags, result_to_dict, IntentEvalResult


SUITES = {
    "smoke_eval": CURRENT_DIR / "smoke_eval.jsonl",
    "full_eval": CURRENT_DIR / "full_eval.jsonl",
}
DEFAULT_REPORT_DIR = CURRENT_DIR / "report"
TREND_METRICS = (
    "case_pass_rate",
    "intent_accuracy",
    "ready_accuracy",
    "entity_accuracy",
    "missing_context_accuracy",
)


def main() -> int:
    args = parse_args()
    # 默认禁用 LLM，强制 classify_main_intent_with_llm 返回无效结果。
    # 这样 recognize_main_intent 会进入规则兜底路径，适合作为 CI/回归评测基线。
    if not args.allow_llm:
        disable_llm()

    generated_at = datetime.now().isoformat(timespec="seconds")
    cases = load_cases(args.suite)
    # --case-id 可以只跑某几条 case，调试单个失败样本时很有用。
    if args.case_id:
        wanted = set(args.case_id)
        cases = [case for case in cases if case["id"] in wanted]

    # 每条 case 会得到一个 IntentEvalResult：
    # - passed 表示这条 case 的所有 expect 检查项都通过
    # - failures 记录具体哪一项不符合预期
    results = [run_case(case) for case in cases]
    report = {
        "run_id": build_run_id(args.suite, generated_at, args.allow_llm),
        "suite": args.suite,
        "generated_at": generated_at,
        "llm_enabled": args.allow_llm,
        "git": get_git_info(),
        "summary": compute_summary(results),
        "results": [result_to_dict(result) for result in results],
    }
    # --output 适合把本次完整报告写到指定文件。
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # 默认会写 report/latest.json、report/history.jsonl、trend.csv、trend.svg。
    # --no-report 则只打印结果，不落盘，适合临时验证。
    if not args.no_report:
        write_report_artifacts(report, args.report_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # 退出码是给 CI/CD 用的：有失败返回 1，全部通过返回 0。
    return 0 if report["summary"]["failed"] == 0 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行意图评测。")
    # suite 决定读取哪个 jsonl 评测集。
    parser.add_argument("--suite", choices=sorted(SUITES), default="full_eval")
    # 可以多次传入，例如：--case-id a --case-id b。
    parser.add_argument("--case-id", action="append", default=[])
    # 默认关闭 LLM；加这个参数后才会走真实 LLM 意图识别。
    parser.add_argument("--allow-llm", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--no-report", action="store_true")
    return parser.parse_args()


def disable_llm() -> None:
    import Intent.main_intent_route as main_intent_route

    def invalid_intent(*_: Any, **__: Any) -> dict[str, Any]:
        # 这里不是返回一个真实意图，而是模拟“LLM 不可用/结果无效”。
        # recognize_main_intent 看到 is_valid=False 后，会继续走规则匹配。
        return {
            "intent": "OUT_OF_SCOPE",
            "confidence": 0.3,
            "evidence": ["评测中禁用 LLM"],
            "alternative_intents": [],
            "reason": "评测中禁用 LLM",
            "raw_response": "",
            "is_valid": False,
            "error": "intent_eval_disabled_llm",
        }

    # 直接替换模块里的函数引用，是这个评测脚本控制 LLM 开关的关键。
    main_intent_route.classify_main_intent_with_llm = invalid_intent


def load_cases(suite: str) -> list[dict[str, Any]]:
    path = SUITES[suite]
    cases = []
    with path.open("r", encoding="utf-8") as file:
        for line_no, line in enumerate(file, start=1):
            text = line.strip()
            # 允许 jsonl 里出现空行或 # 注释行，方便维护评测集。
            if not text or text.startswith("#"):
                continue
            case = json.loads(text)
            # 保存原始行号，后续如果要定位坏 case，可以用这个字段扩展错误提示。
            case["_line"] = line_no
            cases.append(case)
    return cases


def run_case(case: dict[str, Any]) -> IntentEvalResult:
    expect = case.get("expect") or {}
    try:
        # actual 是 Tagent 实际跑出来的结果，包含 query_context 和 intent_result。
        actual = run_intent(case["query"])
        # evaluate_case 是真正的打分入口：
        # 它会把 expect.intent / expect.is_ready / expect.target_contains 等字段
        # 和 actual.intent_result / actual.query_context 逐项比较。
        failures = evaluate_case(actual, expect)
        return IntentEvalResult(
            case_id=str(case["id"]),
            expected_intent=str(expect.get("intent") or ""),
            actual_intent=str((actual.get("intent_result") or {}).get("intent") or ""),
            # 一条 case 的判定很严格：没有任何 failure 才算通过。
            passed=not failures,
            failures=failures,
            tags=mark_expected_tags(expect, list(case.get("tags") or [])),
        )
    except Exception as exc:
        # 如果评测过程本身抛异常，这条 case 也算失败。
        # 例如 json 格式问题、代码运行错误、依赖导入失败等。
        return IntentEvalResult(
            case_id=str(case.get("id") or ""),
            expected_intent=str(expect.get("intent") or ""),
            actual_intent=None,
            passed=False,
            tags=list(case.get("tags") or []),
            error=f"{type(exc).__name__}: {exc}",
        )


def run_intent(query: str) -> dict[str, Any]:
    from Intent.main_intent_route import recognize_main_intent
    from query_processing import normalize_query

    # 评测集里可以写 {project_root} 占位符，运行时替换成本机项目路径。
    expanded_query = expand_query(query)
    # 第一步：query_processing。这里会做别名替换、traceId/source_refs/target/framework 抽取。
    query_context = normalize_query(expanded_query)
    # 第二步：Intent。注意传入的是 normalized_query，不是原始 query。
    intent_result = recognize_main_intent(query_context.normalized_query)
    # 第三步：把 query_processing 抽取出的上下文合并进 intent_result。
    # 这样 metrics.py 可以统一从 actual 里检查 target、framework、trace_id 等字段。
    merge_query_context(intent_result, query_context.to_dict())
    return {
        "query": expanded_query,
        "query_context": query_context.to_dict(),
        "intent_result": intent_result,
    }


def merge_query_context(intent_result: dict[str, Any], query_context: dict[str, Any]) -> None:
    extracted = intent_result.setdefault("extracted_context", {})
    normalized_extracted = query_context.get("extracted_context") or {}
    # Intent 自己可能抽到一部分实体，query_processing 也可能抽到一部分实体。
    # 这里做合并和去重，避免评测时漏掉标准化阶段抽出来的 target/framework/source_refs。
    for key in ("target", "frameworks", "source_refs"):
        existing = extracted.get(key) if isinstance(extracted.get(key), list) else []
        incoming = normalized_extracted.get(key) if isinstance(normalized_extracted.get(key), list) else []
        extracted[key] = dedupe([*existing, *incoming])
    # trace_id 和 force_source_generation 是单值/布尔值，按“标准化阶段有则补充”的方式合并。
    if normalized_extracted.get("trace_id") and not extracted.get("trace_id"):
        extracted["trace_id"] = normalized_extracted["trace_id"]
    if normalized_extracted.get("force_source_generation"):
        extracted["force_source_generation"] = True
    # 把原始 query 和标准化 query 放到 intent_result，方便 metrics 检查 normalized_query_contains。
    intent_result["normalized_query"] = query_context.get("normalized_query")
    intent_result["raw_query"] = query_context.get("raw_query")


def expand_query(query: str) -> str:
    return query.replace("{project_root}", str(PROJECT_ROOT))


def dedupe(items: list[Any]) -> list[Any]:
    result = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result


def build_run_id(suite: str, generated_at: str, llm_enabled: bool) -> str:
    compact_time = generated_at.replace("-", "").replace(":", "").replace("T", "_")
    mode = "llm" if llm_enabled else "rule"
    return f"{compact_time}_{suite}_{mode}"


def get_git_info() -> dict[str, Any]:
    # 报告里记录 git 信息，便于以后追踪“哪个版本跑出了这个评测结果”。
    return {
        "branch": run_git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "commit": run_git(["rev-parse", "--short", "HEAD"]),
        "dirty": bool(run_git(["status", "--porcelain"])),
    }


def run_git(args: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def write_report_artifacts(report: dict[str, Any], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = report_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    run_id = str(report["run_id"])
    full_report_path = runs_dir / f"{run_id}.json"
    # runs/ 保存每次完整报告；latest.json 总是指向最近一次报告。
    full_report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (report_dir / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # history.jsonl 是趋势数据源：每次评测追加一行摘要。
    history_item = build_history_item(report, full_report_path)
    history_path = report_dir / "history.jsonl"
    with history_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(history_item, ensure_ascii=False) + "\n")

    # 根据历史记录生成趋势表和趋势图。
    history = load_history(history_path)
    write_trend_csv(history, report_dir / "trend.csv")
    write_trend_svg(history, report_dir / "trend.svg")


def build_history_item(report: dict[str, Any], full_report_path: Path) -> dict[str, Any]:
    summary = report.get("summary") or {}
    # 历史记录只保留摘要和失败 case id，不重复保存完整 results，避免 history.jsonl 越来越大。
    failed_case_ids = [
        result.get("case_id")
        for result in report.get("results") or []
        if isinstance(result, dict) and not result.get("passed")
    ]
    confusion = summary.get("confusion_matrix") or {}
    return {
        "run_id": report.get("run_id"),
        "suite": report.get("suite"),
        "generated_at": report.get("generated_at"),
        "llm_enabled": report.get("llm_enabled"),
        "git_branch": (report.get("git") or {}).get("branch"),
        "git_commit": (report.get("git") or {}).get("commit"),
        "git_dirty": (report.get("git") or {}).get("dirty"),
        "total": summary.get("total"),
        "passed": summary.get("passed"),
        "failed": summary.get("failed"),
        "case_pass_rate": summary.get("case_pass_rate"),
        "intent_accuracy": summary.get("intent_accuracy"),
        "ready_accuracy": summary.get("ready_accuracy"),
        "next_action_accuracy": summary.get("next_action_accuracy"),
        "entity_accuracy": summary.get("entity_accuracy"),
        "missing_context_accuracy": summary.get("missing_context_accuracy"),
        "failed_case_ids": failed_case_ids,
        "intent_distribution": intent_distribution(confusion),
        "confusion_matrix": confusion,
        "report_path": str(full_report_path),
    }


def intent_distribution(confusion: dict[str, dict[str, int]]) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for expected_intent, actuals in confusion.items():
        distribution[expected_intent] = sum(actuals.values()) if isinstance(actuals, dict) else 0
    return distribution


def load_history(history_path: Path) -> list[dict[str, Any]]:
    history = []
    if not history_path.exists():
        return history
    with history_path.open("r", encoding="utf-8") as file:
        for line in file:
            text = line.strip()
            if text:
                history.append(json.loads(text))
    return history


def write_trend_csv(history: list[dict[str, Any]], output_path: Path) -> None:
    # trend.csv 方便用表格工具或 Grafana/BI 看各版本指标变化。
    fields = [
        "run_id",
        "suite",
        "generated_at",
        "llm_enabled",
        "git_branch",
        "git_commit",
        "total",
        "passed",
        "failed",
        *TREND_METRICS,
    ]
    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for item in history:
            writer.writerow({field: item.get(field) for field in fields})


def write_trend_svg(history: list[dict[str, Any]], output_path: Path) -> None:
    # 这里手写一个轻量 SVG 趋势图，避免额外引入 matplotlib 等依赖。
    width = 960
    height = 420
    margin_left = 70
    margin_right = 30
    margin_top = 40
    margin_bottom = 80
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    colors = {
        "case_pass_rate": "#2563eb",
        "intent_accuracy": "#16a34a",
        "ready_accuracy": "#f97316",
        "entity_accuracy": "#9333ea",
        "missing_context_accuracy": "#dc2626",
    }

    points_by_metric: dict[str, list[tuple[float, float]]] = {}
    count = max(len(history), 1)
    for metric in TREND_METRICS:
        points: list[tuple[float, float]] = []
        for index, item in enumerate(history):
            value = item.get(metric)
            if value is None:
                continue
            x = margin_left + (plot_width * index / max(count - 1, 1))
            y = margin_top + plot_height * (1 - float(value))
            points.append((x, y))
        points_by_metric[metric] = points

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="70" y="25" font-family="Arial" font-size="18" fill="#111827">意图评测趋势</text>',
    ]
    for tick in range(0, 6):
        value = tick / 5
        y = margin_top + plot_height * (1 - value)
        svg_parts.append(f'<line x1="{margin_left}" y1="{y:.1f}" x2="{width - margin_right}" y2="{y:.1f}" stroke="#e5e7eb"/>')
        svg_parts.append(f'<text x="20" y="{y + 4:.1f}" font-family="Arial" font-size="12" fill="#6b7280">{value:.1f}</text>')
    svg_parts.append(f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_height}" stroke="#9ca3af"/>')
    svg_parts.append(f'<line x1="{margin_left}" y1="{margin_top + plot_height}" x2="{width - margin_right}" y2="{margin_top + plot_height}" stroke="#9ca3af"/>')

    for metric, points in points_by_metric.items():
        color = colors[metric]
        if len(points) >= 2:
            point_text = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
            svg_parts.append(f'<polyline points="{point_text}" fill="none" stroke="{color}" stroke-width="2"/>')
        for x, y in points:
            svg_parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>')

    legend_x = margin_left
    legend_y = height - 45
    for index, metric in enumerate(TREND_METRICS):
        x = legend_x + index * 170
        color = colors[metric]
        svg_parts.append(f'<rect x="{x}" y="{legend_y}" width="12" height="12" fill="{color}"/>')
        svg_parts.append(f'<text x="{x + 18}" y="{legend_y + 11}" font-family="Arial" font-size="12" fill="#374151">{metric}</text>')

    if history:
        first = str(history[0].get("generated_at") or "")
        last = str(history[-1].get("generated_at") or "")
        svg_parts.append(f'<text x="{margin_left}" y="{height - 18}" font-family="Arial" font-size="12" fill="#6b7280">{first}</text>')
        svg_parts.append(f'<text x="{width - 230}" y="{height - 18}" font-family="Arial" font-size="12" fill="#6b7280">{last}</text>')
    else:
        svg_parts.append(f'<text x="{margin_left}" y="{margin_top + 30}" font-family="Arial" font-size="14" fill="#6b7280">暂无历史记录</text>')

    svg_parts.append("</svg>")
    output_path.write_text("\n".join(svg_parts), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
