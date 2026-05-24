"""AUTOMATION_WRITING 的 Skill 元数据。"""

from __future__ import annotations

from skills.base import SkillSpec


AUTOMATION_WRITING_SKILL = SkillSpec(
    name="automation_writing",
    intent="AUTOMATION_WRITING",
    description="根据测试用例或功能需求生成自动化测试代码。",
    status="planned",
    instructions_path="skills/automation_writing/SKILL.md",
    prompt_modules=["prompts.prompt_automation"],
    rag_sources=["case", "requirement", "api", "code"],
    tools=["search_code", "read_file", "write_file", "run_test"],
)
