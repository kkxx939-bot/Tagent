"""产物处理逻辑。

Executor 只认识 generate_artifact、validate_artifact、save_artifact。
这里根据 artifact_type 分发到具体实现，避免业务动作不断塞进 Executor。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    if artifact_type in {"automation_code", "review_report"}:
        return ArtifactOperationResult(
            success=False,
            error=f"当前还没有实现 artifact_type={artifact_type} 的产物生成器",
            data={"artifact_type": artifact_type},
        )
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
        from case_generator import validate_cases

        result = variables.get("case_generation_result") or {}
        cases = result.get("cases") or []
        validate_cases(cases)
        return ArtifactOperationResult(success=True, data={"artifact_type": artifact_type, "case_count": len(cases)})

    return ArtifactOperationResult(
        success=True,
        warnings=[f"artifact_type={artifact_type} 暂无专门校验规则，已跳过细粒度校验"],
        data={"artifact_type": artifact_type},
    )


def save_artifact(inputs: dict[str, Any], variables: dict[str, Any]) -> ArtifactOperationResult:
    output_path = str(variables.get("output_path") or inputs.get("output_path") or "")
    if not output_path:
        return ArtifactOperationResult(success=True, warnings=["当前步骤没有新的文件产物需要保存"])
    return ArtifactOperationResult(success=True, data={"output_path": output_path})


def _generate_test_case_artifact(user_query: str, variables: dict[str, Any]) -> ArtifactOperationResult:
    from case_generator import OUTPUT_PATH, generate_test_cases

    result = generate_test_cases(user_query)
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
        },
    )


def _generate_failure_report(variables: dict[str, Any]) -> ArtifactOperationResult:
    tool_results = variables.get("tool_results") or []
    report = {
        "artifact_type": "failure_report",
        "evidence_count": len(tool_results),
        "evidence": tool_results,
        "conclusion": "已整理工具返回的排查证据，后续可接模型生成更完整的失败分析报告。",
    }
    variables["failure_report"] = report
    return ArtifactOperationResult(success=True, data=report)


def _normalize_artifact_type(artifact_type: str) -> str:
    return (artifact_type or "").strip().lower()
