"""RESULT_REVIEW 的 Skill 元数据。"""

from __future__ import annotations

from skills.base import SkillSpec


RESULT_REVIEW_SKILL = SkillSpec(
    name="result_review",
    intent="RESULT_REVIEW",
    description="查看、解释或评审生成结果文件。",
    status="planned",
    instructions_path="skills/result_review/SKILL.md",
    prompt_modules=[],
    rag_sources=[],
    tools=["read_file", "case_generation_verifier"],
)
