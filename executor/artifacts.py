"""产物处理逻辑。

Executor 只认识 generate_artifact、validate_artifact、save_artifact。
这里根据 artifact_type 分发到具体实现，避免业务动作不断塞进 Executor。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from config import GENERATED_DIR, ensure_output_dirs

# todo：好多不懂，需要真实的了解
@dataclass
class ArtifactOperationResult:
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


def generate_artifact(
    artifact_type: str,
    user_query: str,
    inputs: dict[str, Any],
    variables: dict[str, Any],
) -> ArtifactOperationResult:
    artifact_type = _normalize_artifact_type(artifact_type)
    if artifact_type == "test_case":
        return _generate_test_case_artifact(user_query, variables)
    if artifact_type == "failure_report":
        return _generate_failure_report(variables)
    if artifact_type == "automation_code":
        return _generate_automation_code_draft(user_query, inputs, variables)
    if artifact_type == "execution_report":
        return _generate_execution_report(inputs, variables)
    if artifact_type == "review_report":
        return _generate_review_report(inputs, variables)
    return ArtifactOperationResult(
        success=False,
        error=f"不支持的 artifact_type：{artifact_type}",
        data={"artifact_type": artifact_type},
    )


def validate_artifact(
    artifact_type: str,
    inputs: dict[str, Any],
    variables: dict[str, Any],
) -> ArtifactOperationResult:
    artifact_type = _normalize_artifact_type(artifact_type)
    if artifact_type == "test_case":
        from case_generator import grounding_errors, validate_cases

        result = variables.get("case_generation_result") or {}
        cases = result.get("cases") or []
        validate_cases(cases)
        grounding_report = result.get("grounding_report") or {}
        errors = grounding_errors(grounding_report)
        return ArtifactOperationResult(
            success=not errors,
            data={
                "artifact_type": artifact_type,
                "case_count": len(cases),
                "grounding_report": grounding_report,
            },
            warnings=list(grounding_report.get("warnings") or []) if isinstance(grounding_report, dict) else [],
            error="；".join(errors) if errors else None,
        )

    return ArtifactOperationResult(
        success=True,
        warnings=[f"artifact_type={artifact_type} 暂无专门校验规则，已跳过细粒度校验"],
        data={"artifact_type": artifact_type},
    )


def save_artifact(inputs: dict[str, Any], variables: dict[str, Any]) -> ArtifactOperationResult:
    artifacts = variables.get("artifacts") or []
    output_path = str(variables.get("output_path") or inputs.get("output_path") or "")
    if artifacts:
        return ArtifactOperationResult(success=True, data={"artifacts": artifacts})
    if not output_path:
        return ArtifactOperationResult(success=True, warnings=["当前步骤没有新的文件产物需要保存"])
    return ArtifactOperationResult(success=True, data={"output_path": output_path})


def _generate_test_case_artifact(user_query: str, variables: dict[str, Any]) -> ArtifactOperationResult:
    from case_generator import OUTPUT_PATH, generate_test_cases

    result = generate_test_cases(user_query, context_override=variables.get("case_generation_context"))
    variables["case_generation_result"] = result
    variables["output_path"] = str(OUTPUT_PATH)
    case_count = len(result.get("cases") or [])
    return ArtifactOperationResult(
        success=True,
        data={
            "artifact_type": "test_case",
            "case_count": case_count,
            "output_path": str(OUTPUT_PATH),
            "source_summary": result.get("source_summary") or {},
            "grounding_report": result.get("grounding_report") or {},
        },
        warnings=list((result.get("grounding_report") or {}).get("warnings") or []),
    )


def _generate_failure_report(variables: dict[str, Any]) -> ArtifactOperationResult:
    tool_results = variables.get("tool_results") or []
    report = {
        "artifact_type": "failure_report",
        "generated_at": _now(),
        "evidence_count": len(tool_results),
        "evidence": tool_results,
        "conclusion": "已整理工具返回的排查证据，后续可接模型生成更完整的失败分析报告。",
    }
    output_path = _write_json_artifact("failure_report.json", report)
    report["output_path"] = str(output_path)
    variables["failure_report"] = report
    return ArtifactOperationResult(success=True, data=report)


def _generate_automation_code_draft(
    user_query: str,
    inputs: dict[str, Any],
    variables: dict[str, Any],
) -> ArtifactOperationResult:
    project_context = variables.get("automation_project_context") or {}
    case_result = variables.get("case_generation_result") or {}
    cases = case_result.get("cases") or []
    target = _automation_target(inputs, variables, user_query)
    if not target and not cases:
        return ArtifactOperationResult(
            success=False,
            error="缺少自动化目标：需要说明要把哪条用例或哪个功能生成自动化代码",
            data={"artifact_type": "automation_code", "missing_context": ["自动化目标功能或测试用例"]},
        )

    framework = _automation_framework(inputs, variables, project_context, user_query)
    draft = {
        "artifact_type": "automation_code",
        "status": "draft",
        "generated_at": _now(),
        "framework": framework,
        "target": target,
        "project_context": project_context,
        "source_case_count": len(cases),
        "source_case_output_path": variables.get("output_path"),
        "user_query": user_query,
        "next_steps": _automation_next_steps(framework, project_context),
        "draft_files": _build_automation_draft_files(framework, cases),
    }
    output_path = _write_json_artifact("automation_code_draft.json", draft)
    draft["output_path"] = str(output_path)
    variables["automation_code_result"] = draft
    return ArtifactOperationResult(
        success=True,
        data=draft,
        warnings=["当前未接入真实代码写入器，已生成自动化代码草稿。"],
    )


def _generate_execution_report(inputs: dict[str, Any], variables: dict[str, Any]) -> ArtifactOperationResult:
    tool_results = variables.get("tool_results") or []
    report = {
        "artifact_type": "execution_report",
        "generated_at": _now(),
        "priority": inputs.get("priority") or "P0",
        "tool_result_count": len(tool_results),
        "tool_results": tool_results,
        "status": "collected" if tool_results else "no_execution_result",
    }
    output_path = _write_json_artifact("execution_report.json", report)
    report["output_path"] = str(output_path)
    variables["execution_report"] = report
    warnings = [] if tool_results else ["没有找到执行工具结果，已生成空执行报告。"]
    return ArtifactOperationResult(success=True, data=report, warnings=warnings)


def _generate_review_report(inputs: dict[str, Any], variables: dict[str, Any]) -> ArtifactOperationResult:
    report = {
        "artifact_type": "review_report",
        "generated_at": _now(),
        "review_type": inputs.get("review_type") or "general",
        "case_count": len((variables.get("case_generation_result") or {}).get("cases") or []),
        "artifact_count": len(variables.get("artifacts") or []),
        "tool_result_count": len(variables.get("tool_results") or []),
        "capability_gap": variables.get("capability_gap"),
        "summary": variables.get("summary_result") or {},
        "conclusion": _build_review_conclusion(variables),
    }
    output_path = _write_json_artifact("review_report.json", report)
    report["output_path"] = str(output_path)
    variables["review_report"] = report
    return ArtifactOperationResult(success=True, data=report)


def _build_automation_draft_files(framework: str, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected_cases = cases[:5]
    if framework == "playwright":
        return [
            {
                "path_hint": "tests/generated/p0.spec.ts",
                "case_titles": [str(case.get("title") or case.get("case_id") or "") for case in selected_cases],
            }
        ]
    if framework == "pytest":
        return [
            {
                "path_hint": "tests/generated/test_p0_cases.py",
                "case_titles": [str(case.get("title") or case.get("case_id") or "") for case in selected_cases],
            }
        ]
    return [
        {
            "path_hint": "generated_automation_code",
            "case_titles": [str(case.get("title") or case.get("case_id") or "") for case in selected_cases],
        }
    ]


def _build_review_conclusion(variables: dict[str, Any]) -> str:
    if variables.get("capability_gap"):
        return "存在能力缺口，需要补充工具或上下文后再继续。"
    if variables.get("tool_results"):
        return "已汇总工具执行结果，可继续做失败分析或人工复核。"
    if variables.get("case_generation_result"):
        return "已生成测试用例，可继续补充自动化代码生成和执行结果检查。"
    return "当前可评审信息有限，需要补充产物或执行结果。"


def _write_json_artifact(filename: str, payload: dict[str, Any]) -> Path:
    ensure_output_dirs()
    output_path = GENERATED_DIR / filename
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _first_item(value: Any) -> Any:
    if isinstance(value, list) and value:
        return value[0]
    return None


def _automation_target(inputs: dict[str, Any], variables: dict[str, Any], user_query: str) -> str | None:
    if inputs.get("target"):
        return str(inputs["target"])
    intent_result = variables.get("intent_result") or {}
    extracted_context = intent_result.get("extracted_context") if isinstance(intent_result, dict) else {}
    if isinstance(extracted_context, dict):
        targets = extracted_context.get("target")
        if isinstance(targets, list) and targets:
            cleaned_targets = [
                str(item).strip()
                for item in targets
                if str(item).strip() and str(item).strip().lower() not in {"case", "用例", "需求", "测试用例"}
            ]
            if cleaned_targets:
                return "、".join(cleaned_targets)
    if any(keyword in user_query for keyword in ("登录", "注册", "支付", "订单", "退款", "贷款", "额度")):
        return user_query
    return None


def _automation_next_steps(framework: str, project_context: dict[str, Any]) -> list[str]:
    next_steps = []
    if not project_context.get("project_path"):
        next_steps.append("补充自动化项目路径后，再生成可直接落库的代码文件。")
    if framework == "unknown":
        next_steps.append("补充自动化框架后，再生成框架匹配的代码结构。")
    next_steps.append("确认 P0 用例筛选规则和执行命令。")
    return next_steps


def _automation_framework(
    inputs: dict[str, Any],
    variables: dict[str, Any],
    project_context: dict[str, Any],
    user_query: str,
) -> str:
    if inputs.get("framework"):
        return str(inputs["framework"]).lower()
    intent_result = variables.get("intent_result") or {}
    extracted_context = intent_result.get("extracted_context") if isinstance(intent_result, dict) else {}
    if isinstance(extracted_context, dict):
        framework = _first_item(extracted_context.get("frameworks"))
        if framework:
            return str(framework).lower()
    framework = _first_item(project_context.get("framework_hints"))
    if framework:
        return str(framework).lower()
    text = user_query.lower()
    for name in ("playwright", "selenium", "appium", "pytest", "cypress"):
        if name in text:
            return name
    return "unknown"


def _normalize_artifact_type(artifact_type: str) -> str:
    return (artifact_type or "").strip().lower()
