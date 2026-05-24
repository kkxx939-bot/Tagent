"""当前任务的短期记忆。

短期记忆只记录一次任务运行过程中的状态，不直接承担长期保存。
任务结束后可以通过 `freeze_summary()` 生成摘要，再由长期记忆模块决定是否沉淀。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class MemoryEvent:
    """短期记忆里的事件记录。"""

    event_type: str
    payload: dict[str, Any]
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SessionMemory:
    """一次任务的运行态上下文。

    这里不存模型推理过程，只存后续步骤需要继续使用的信息。
    """

    session_id: str = field(default_factory=lambda: f"session_{uuid4().hex[:12]}")
    task_id: str | None = None
    user_query: str | None = None
    status: str = "idle"
    current_step: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    completed_at: str | None = None

    intent_result: dict[str, Any] | None = None
    selected_skill: dict[str, Any] | None = None
    relevant_long_term_memories: list[dict[str, Any]] = field(default_factory=list)
    retrieved_context: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    generated_outputs: list[dict[str, Any]] = field(default_factory=list)
    missing_context: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    events: list[MemoryEvent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def start_task(
        self,
        user_query: str,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.user_query = user_query
        self.task_id = task_id or f"task_{uuid4().hex[:12]}"
        self.status = "running"
        self.current_step = "task_started"
        if metadata:
            self.metadata.update(metadata)
        self._record_event("task_started", {"user_query": user_query, "task_id": self.task_id})

    def set_intent_result(self, intent_result: dict[str, Any]) -> None:
        self.intent_result = dict(intent_result)
        self.current_step = "intent_classified"
        self._record_event("intent_classified", self.intent_result)

    def set_selected_skill(self, skill: str | dict[str, Any]) -> None:
        if isinstance(skill, str):
            self.selected_skill = {"name": skill}
        else:
            self.selected_skill = dict(skill)
        self.current_step = "skill_selected"
        self._record_event("skill_selected", self.selected_skill)

    def add_relevant_memory(self, memory: dict[str, Any]) -> None:
        self.relevant_long_term_memories.append(dict(memory))
        self._record_event("long_term_memory_loaded", memory)

    def add_retrieved_context(self, context: dict[str, Any]) -> None:
        self.retrieved_context.append(dict(context))
        self.current_step = "context_retrieved"
        self._record_event("context_retrieved", context)

    def add_tool_result(self, tool_name: str, result: dict[str, Any]) -> None:
        payload = {"tool_name": tool_name, "result": dict(result)}
        self.tool_results.append(payload)
        self.current_step = "tool_called"
        self._record_event("tool_called", payload)

    def add_generated_output(
        self,
        output_path: str,
        output_type: str,
        summary: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "output_path": output_path,
            "output_type": output_type,
            "summary": summary,
            "metadata": metadata or {},
        }
        self.generated_outputs.append(payload)
        self.current_step = "output_generated"
        self._record_event("output_generated", payload)

    def set_missing_context(self, missing_context: list[str]) -> None:
        self.missing_context = list(missing_context)
        self._record_event("missing_context_updated", {"missing_context": self.missing_context})

    def add_note(self, note: str) -> None:
        self.notes.append(note)
        self._record_event("note_added", {"note": note})

    def mark_step(self, step: str, payload: dict[str, Any] | None = None) -> None:
        self.current_step = step
        self._record_event("step_changed", {"step": step, **(payload or {})})

    def complete(self, summary: str | None = None) -> None:
        self.status = "completed"
        self.current_step = "task_completed"
        self.completed_at = _now()
        payload = {"summary": summary} if summary else {}
        self._record_event("task_completed", payload)

    def fail(self, reason: str) -> None:
        self.status = "failed"
        self.current_step = "task_failed"
        self.completed_at = _now()
        self._record_event("task_failed", {"reason": reason})

    def freeze_summary(self) -> dict[str, Any]:
        """生成可交给长期记忆模块判断的任务摘要。"""
        return {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "user_query": self.user_query,
            "status": self.status,
            "intent": self._intent_name(),
            "selected_skill": self._skill_name(),
            "generated_outputs": list(self.generated_outputs),
            "missing_context": list(self.missing_context),
            "notes": list(self.notes),
            "started_at": self.created_at,
            "completed_at": self.completed_at,
        }

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["events"] = [event.to_dict() for event in self.events]
        return data

    def clear_runtime(self) -> None:
        """清理运行态内容，保留 session_id 便于排查。"""
        self.task_id = None
        self.user_query = None
        self.status = "idle"
        self.current_step = None
        self.completed_at = None
        self.intent_result = None
        self.selected_skill = None
        self.relevant_long_term_memories.clear()
        self.retrieved_context.clear()
        self.tool_results.clear()
        self.generated_outputs.clear()
        self.missing_context.clear()
        self.notes.clear()
        self.events.clear()
        self.metadata.clear()
        self._touch()

    def _intent_name(self) -> str | None:
        if not self.intent_result:
            return None
        intent = self.intent_result.get("intent")
        return str(intent) if intent else None

    def _skill_name(self) -> str | None:
        if not self.selected_skill:
            return None
        name = self.selected_skill.get("name")
        return str(name) if name else None

    def _record_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append(MemoryEvent(event_type=event_type, payload=dict(payload)))
        self._touch()

    def _touch(self) -> None:
        self.updated_at = _now()
