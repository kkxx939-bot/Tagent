from __future__ import annotations

import argparse
import csv
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any


METRICS = [
    ("estimated_total_tokens", "总 Token 估算", "越低越好"),
    ("estimated_context_tokens", "上下文 Token 估算", "越低越好"),
    ("context_count", "上下文条数", "看场景"),
    ("noise_context_rate", "噪声比例", "越低越好"),
    ("cross_project_context_rate", "跨项目比例", "越低越好"),
    ("traceable_context_rate", "上下文可追踪率", "越高越好"),
    ("memory_hit_count", "Memory 命中数", "看质量"),
    ("load_context_total_ms", "上下文加载耗时 ms", "越低越好"),
]


def main() -> int:
    args = parse_args()
    baseline = load_json(args.baseline)
    after = load_json(args.after) if args.after.exists() else None
    reports = [baseline, *( [after] if after else [] )]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = build_metric_rows(baseline, after)
    write_csv(args.output_dir / "openviking_observation_compare.csv", rows)
    write_svg(args.output_dir / "openviking_observation_compare.svg", rows)
    write_html(args.output_dir / "openviking_observation_compare.html", reports, rows)
    print(
        json.dumps(
            {
                "csv": str(args.output_dir / "openviking_observation_compare.csv"),
                "svg": str(args.output_dir / "openviking_observation_compare.svg"),
                "html": str(args.output_dir / "openviking_observation_compare.html"),
                "after_loaded": after is not None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成 OpenViking 接入前后观测对比报表。")
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--baseline", type=Path, default=root / "result/openviking_observation_baseline_local.json")
    parser.add_argument("--after", type=Path, default=root / "result/openviking_observation_after_openviking.json")
    parser.add_argument("--output-dir", type=Path, default=root / "result")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_metric_rows(baseline: dict[str, Any], after: dict[str, Any] | None) -> list[dict[str, Any]]:
    baseline_summary = baseline.get("summary") or {}
    after_summary = after.get("summary") if after else {}
    rows = []
    for key, label, note in METRICS:
        before_value = baseline_summary.get(key)
        after_value = after_summary.get(key) if isinstance(after_summary, dict) else None
        rows.append(
            {
                "metric": key,
                "label": label,
                "before": before_value,
                "after": after_value,
                "delta": delta(before_value, after_value),
                "delta_rate": delta_rate(before_value, after_value),
                "note": note,
            }
        )
    return rows


def delta(before: Any, after: Any) -> float | None:
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return None
    return round(after - before, 4)


def delta_rate(before: Any, after: Any) -> float | None:
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)) or before == 0:
        return None
    return round((after - before) / before, 4)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["metric", "label", "before", "after", "delta", "delta_rate", "note"])
        writer.writeheader()
        writer.writerows(rows)


def write_svg(path: Path, rows: list[dict[str, Any]]) -> None:
    width = 980
    row_height = 54
    top = 60
    height = top + row_height * len(rows) + 40
    chart_x = 320
    chart_width = 430
    label_x = 24
    before_color = "#2563eb"
    after_color = "#16a34a"
    pending_color = "#cbd5e1"

    values = [
        value
        for row in rows
        for value in (row.get("before"), row.get("after"))
        if isinstance(value, (int, float)) and value > 0
    ]
    max_value = max(values) if values else 1

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="24" y="34" font-size="20" font-family="Arial, sans-serif" font-weight="700" fill="#111827">OpenViking 接入前后观测对比</text>',
        f'<rect x="{chart_x}" y="18" width="14" height="14" fill="{before_color}"/><text x="{chart_x + 20}" y="30" font-size="12" font-family="Arial, sans-serif" fill="#374151">接入前</text>',
        f'<rect x="{chart_x + 90}" y="18" width="14" height="14" fill="{after_color}"/><text x="{chart_x + 110}" y="30" font-size="12" font-family="Arial, sans-serif" fill="#374151">接入后</text>',
    ]
    for index, row in enumerate(rows):
        y = top + index * row_height
        before = row.get("before")
        after = row.get("after")
        before_width = bar_width(before, max_value, chart_width)
        after_width = bar_width(after, max_value, chart_width)
        parts.extend(
            [
                f'<text x="{label_x}" y="{y + 18}" font-size="13" font-family="Arial, sans-serif" fill="#111827">{escape(row["label"])}</text>',
                f'<text x="{label_x}" y="{y + 36}" font-size="11" font-family="Arial, sans-serif" fill="#6b7280">{escape(row["metric"])}</text>',
                f'<rect x="{chart_x}" y="{y + 6}" width="{before_width}" height="16" rx="3" fill="{before_color}"/>',
                f'<text x="{chart_x + before_width + 8}" y="{y + 19}" font-size="12" font-family="Arial, sans-serif" fill="#374151">{format_svg_value(before)}</text>',
            ]
        )
        if after is None:
            parts.extend(
                [
                    f'<rect x="{chart_x}" y="{y + 30}" width="84" height="16" rx="3" fill="{pending_color}"/>',
                    f'<text x="{chart_x + 92}" y="{y + 43}" font-size="12" font-family="Arial, sans-serif" fill="#6b7280">待生成</text>',
                ]
            )
        else:
            parts.extend(
                [
                    f'<rect x="{chart_x}" y="{y + 30}" width="{after_width}" height="16" rx="3" fill="{after_color}"/>',
                    f'<text x="{chart_x + after_width + 8}" y="{y + 43}" font-size="12" font-family="Arial, sans-serif" fill="#374151">{format_svg_value(after)}</text>',
                ]
            )
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def write_html(path: Path, reports: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    baseline = reports[0]
    cases = baseline.get("cases") or []
    after_exists = len(reports) > 1
    body = f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>OpenViking 观测对比</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #111827; }}
    h1 {{ font-size: 24px; margin-bottom: 6px; }}
    h2 {{ font-size: 18px; margin-top: 28px; }}
    .meta {{ color: #6b7280; margin-bottom: 20px; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 12px; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 9px 10px; font-size: 13px; text-align: left; }}
    th {{ background: #f9fafb; font-weight: 700; }}
    .pending {{ color: #6b7280; }}
    .chart {{ border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; margin-top: 14px; }}
    .summary {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }}
    .card {{ border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; }}
    .card-label {{ color: #6b7280; font-size: 12px; }}
    .card-value {{ font-size: 20px; font-weight: 700; margin-top: 4px; }}
  </style>
</head>
<body>
  <h1>OpenViking 观测对比</h1>
  <div class="meta">生成时间：{escape(datetime.now().isoformat(timespec="seconds"))}；当前接入后数据：{"已加载" if after_exists else "未生成"}</div>
  {summary_cards(baseline.get("summary") or {})}
  <h2>指标表</h2>
  {metric_table(rows)}
  <h2>图表</h2>
  <div class="chart"><img src="openviking_observation_compare.svg" alt="OpenViking 观测对比图"></div>
  <h2>Baseline 场景明细</h2>
  {case_table(cases)}
</body>
</html>
"""
    path.write_text(body.strip() + "\n", encoding="utf-8")


def summary_cards(summary: dict[str, Any]) -> str:
    cards = [
        ("总 Token", summary.get("estimated_total_tokens")),
        ("上下文 Token", summary.get("estimated_context_tokens")),
        ("噪声比例", summary.get("noise_context_rate")),
        ("加载耗时 ms", summary.get("load_context_total_ms")),
    ]
    items = []
    for label, value in cards:
        items.append(
            f'<div class="card"><div class="card-label">{escape(label)}</div><div class="card-value">{format_value(value)}</div></div>'
        )
    return '<div class="summary">' + "\n".join(items) + "</div>"


def metric_table(rows: list[dict[str, Any]]) -> str:
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{escape(row['label'])}</td>"
            f"<td>{escape(row['metric'])}</td>"
            f"<td>{format_value(row.get('before'))}</td>"
            f"<td>{format_value(row.get('after'))}</td>"
            f"<td>{format_value(row.get('delta'))}</td>"
            f"<td>{format_percent(row.get('delta_rate'))}</td>"
            f"<td>{escape(row['note'])}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>指标</th><th>字段</th><th>接入前</th><th>接入后</th><th>差值</th><th>变化率</th><th>说明</th></tr></thead><tbody>"
        + "\n".join(body)
        + "</tbody></table>"
    )


def case_table(cases: list[dict[str, Any]]) -> str:
    body = []
    for case in cases:
        token = case.get("token") or {}
        noise = case.get("noise") or {}
        traceability = case.get("traceability") or {}
        memory = case.get("memory") or {}
        latency = case.get("latency") or {}
        body.append(
            "<tr>"
            f"<td>{escape(case.get('case_id'))}</td>"
            f"<td>{escape(case.get('status'))}</td>"
            f"<td>{escape(case.get('intent'))}</td>"
            f"<td>{format_value(token.get('estimated_total_tokens'))}</td>"
            f"<td>{format_value(noise.get('noise_context_rate'))}</td>"
            f"<td>{format_value(traceability.get('traceable_context_rate'))}</td>"
            f"<td>{format_value(memory.get('memory_hit_count'))}</td>"
            f"<td>{format_value(latency.get('load_context_total_ms'))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>case_id</th><th>状态</th><th>意图</th><th>总 Token</th><th>噪声比例</th><th>追踪率</th><th>Memory 命中</th><th>耗时 ms</th></tr></thead><tbody>"
        + "\n".join(body)
        + "</tbody></table>"
    )


def bar_width(value: Any, max_value: float, chart_width: int) -> int:
    if not isinstance(value, (int, float)) or value <= 0:
        return 0
    return max(2, int(value / max_value * chart_width))


def format_value(value: Any) -> str:
    if value is None:
        return '<span class="pending">待生成</span>'
    if isinstance(value, float):
        return str(round(value, 4))
    return escape(value)


def format_svg_value(value: Any) -> str:
    if value is None:
        return "待生成"
    if isinstance(value, float):
        return str(round(value, 4))
    return escape(value)


def format_percent(value: Any) -> str:
    if value is None:
        return '<span class="pending">待生成</span>'
    if isinstance(value, (int, float)):
        return f"{round(value * 100, 2)}%"
    return escape(value)


def escape(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


if __name__ == "__main__":
    raise SystemExit(main())
