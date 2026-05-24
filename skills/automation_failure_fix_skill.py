"""AUTOMATION_FAILURE_FIX 的 Skill 元数据。"""

from __future__ import annotations

from skills.base import SkillSpec


AUTOMATION_FAILURE_FIX_SKILL = SkillSpec(
    name="automation_failure_fix",
    intent="AUTOMATION_FAILURE_FIX",
    description="定位并修复自动化脚本失败。",
    status="planned",
    instructions_path="skills/automation_failure_fix/SKILL.md",
    prompt_modules=["prompts.prompt_automation_failure"],
    rag_sources=["case", "bug", "code"],
    tools=["search_code", "read_file", "write_file", "run_test", "analyze_trace"],
)
