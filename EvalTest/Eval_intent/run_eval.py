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
    if not args.allow_llm:
        disable_llm()

    generated_at = datetime.now().isoformat(timespec="seconds")
    cases = load_cases(args.suite)
    if args.case_id:
        wanted = set(args.case_id)
        cases = [case for case in cases if case["id"] in wanted]

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
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.no_report:
        write_report_artifacts(report, args.report_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["summary"]["failed"] == 0 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行意图评测。")
    parser.add_argument("--suite", choices=sorted(SUITES), default="full_eval")
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--allow-llm", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--no-report", action="store_true")
    return parser.parse_args()


def disable_llm() -> None:
    import Intent.main_intent_route as main_intent_route

    def invalid_intent(*_: Any, **__: Any) -> dict[str, Any]:
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

    main_intent_route.classify_main_intent_with_llm = invalid_intent


def load_cases(suite: str) -> list[dict[str, Any]]:
    path = SUITES[suite]
    cases = []
    with path.open("r", encoding="utf-8") as file:
        for line_no, line in enumerate(file, start=1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            case = json.loads(text)
            case["_line"] = line_no
            cases.append(case)
    return cases


def run_case(case: dict[str, Any]) -> IntentEvalResult:
    expect = case.get("expect") or {}
    try:
        actual = run_intent(case["query"])
        failures = evaluate_case(actual, expect)
        return IntentEvalResult(
            case_id=str(case["id"]),
            expected_intent=str(expect.get("intent") or ""),
            actual_intent=str((actual.get("intent_result") or {}).get("intent") or ""),
            passed=not failures,
            failures=failures,
            tags=mark_expected_tags(expect, list(case.get("tags") or [])),
        )
    except Exception as exc:
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

    expanded_query = expand_query(query)
    query_context = normalize_query(expanded_query)
    intent_result = recognize_main_intent(query_context.normalized_query)
    merge_query_context(intent_result, query_context.to_dict())
    return {
        "query": expanded_query,
        "query_context": query_context.to_dict(),
        "intent_result": intent_result,
    }


def merge_query_context(intent_result: dict[str, Any], query_context: dict[str, Any]) -> None:
    extracted = intent_result.setdefault("extracted_context", {})
    normalized_extracted = query_context.get("extracted_context") or {}
    for key in ("target", "frameworks", "source_refs"):
        existing = extracted.get(key) if isinstance(extracted.get(key), list) else []
        incoming = normalized_extracted.get(key) if isinstance(normalized_extracted.get(key), list) else []
        extracted[key] = dedupe([*existing, *incoming])
    if normalized_extracted.get("trace_id") and not extracted.get("trace_id"):
        extracted["trace_id"] = normalized_extracted["trace_id"]
    if normalized_extracted.get("force_source_generation"):
        extracted["force_source_generation"] = True
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
    full_report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (report_dir / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    history_item = build_history_item(report, full_report_path)
    history_path = report_dir / "history.jsonl"
    with history_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(history_item, ensure_ascii=False) + "\n")

    history = load_history(history_path)
    write_trend_csv(history, report_dir / "trend.csv")
    write_trend_svg(history, report_dir / "trend.svg")


def build_history_item(report: dict[str, Any], full_report_path: Path) -> dict[str, Any]:
    summary = report.get("summary") or {}
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
