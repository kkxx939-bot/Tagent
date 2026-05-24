"""CASE_GENERATION 的 Skill 元数据。"""

from __future__ import annotations

from skills.base import SkillSpec


CASE_GENERATION_SKILL = SkillSpec(
    name="case_generation",
    intent="CASE_GENERATION",
    description="根据需求、历史用例、历史 Bug 和接口资料生成结构化测试用例。",
    status="mvp_available",
    instructions_path="skills/case_generation/SKILL.md",
    prompt_modules=["prompts.promptcase"],
    rag_sources=["requirement", "case", "bug", "api"],
    tools=["build_case_context", "generate_test_cases"],
)
