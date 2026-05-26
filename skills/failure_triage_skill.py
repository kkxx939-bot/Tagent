"""FAILURE_TRIAGE 的 Skill 元数据。"""

from __future__ import annotations

from skills.base import SkillSpec


FAILURE_TRIAGE_SKILL = SkillSpec(
    name="failure_triage",
    intent="FAILURE_TRIAGE",
    description="对业务功能、接口、环境或数据失败进行初步排查，并输出证据和下一步建议。",
    status="intent_only",
    instructions_path="skills/failure_triage/SKILL.md",
    prompt_modules=["prompts.prompt_failure"],
    rag_sources=["requirement", "bug", "api", "case"],
    tools=["query_trace_log"],
)
