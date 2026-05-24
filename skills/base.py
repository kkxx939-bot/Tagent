"""Skill 的机器可读元数据。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class SkillSpec:
    """单个 Skill 的机器索引信息。"""

    name: str
    intent: str
    description: str
    status: str
    instructions_path: str | None = None
    prompt_modules: list[str] = field(default_factory=list)
    rag_sources: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
