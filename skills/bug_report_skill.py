"""BUG_REPORT_GENERATION 的 Skill 元数据。"""

from __future__ import annotations

from skills.base import SkillSpec


BUG_REPORT_SKILL = SkillSpec(
    name="bug_report",
    intent="BUG_REPORT_GENERATION",
    description="根据失败现象、复现步骤和证据生成缺陷报告。",
    status="planned",
    instructions_path="skills/bug_report/SKILL.md",
    prompt_modules=["prompts.prompt_bug_report"],
    rag_sources=["requirement", "bug", "api"],
    tools=["search_related_bugs", "get_api_contract"],
)
