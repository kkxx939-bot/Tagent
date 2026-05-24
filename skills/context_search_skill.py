"""CONTEXT_SEARCH 的 Skill 元数据。"""

from __future__ import annotations

from skills.base import SkillSpec


CONTEXT_SEARCH_SKILL = SkillSpec(
    name="context_search",
    intent="CONTEXT_SEARCH",
    description="检索需求、历史用例、历史 Bug、接口文档和 chunk 上下文。",
    status="mvp_available",
    instructions_path="skills/context_search/SKILL.md",
    prompt_modules=[],
    rag_sources=["requirement", "case", "bug", "api"],
    tools=["search_knowledge", "hybrid_search"],
)
