"""REGRESSION_ANALYSIS 的 Skill 元数据。"""

from __future__ import annotations

from skills.base import SkillSpec


REGRESSION_ANALYSIS_SKILL = SkillSpec(
    name="regression_analysis",
    intent="REGRESSION_ANALYSIS",
    description="分析需求、缺陷修复或代码变更带来的回归影响范围。",
    status="planned",
    instructions_path="skills/regression_analysis/SKILL.md",
    prompt_modules=["prompts.prompt_regression"],
    rag_sources=["requirement", "case", "bug", "api", "code"],
    tools=["get_git_diff", "search_existing_cases", "search_related_bugs", "search_code"],
)
