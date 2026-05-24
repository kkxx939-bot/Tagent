"""CONFIG_HELP 的 Skill 元数据。"""

from __future__ import annotations

from skills.base import SkillSpec


CONFIG_HELP_SKILL = SkillSpec(
    name="config_help",
    intent="CONFIG_HELP",
    description="解释和处理模型、API Key、base_url、环境变量等配置问题。",
    status="mvp_available",
    instructions_path="skills/config_help/SKILL.md",
    prompt_modules=[],
    rag_sources=["code"],
    tools=["read_file", "search_code"],
)
