"""PROJECT_QA 的 Skill 元数据。"""

from __future__ import annotations

from skills.base import SkillSpec


PROJECT_QA_SKILL = SkillSpec(
    name="project_qa",
    intent="PROJECT_QA",
    description="回答项目流程、架构、设计取舍和下一步规划问题。",
    status="mvp_available",
    instructions_path="skills/project_qa/SKILL.md",
    prompt_modules=[],
    rag_sources=["code", "project_docs"],
    tools=["read_file", "search_code"],
)
