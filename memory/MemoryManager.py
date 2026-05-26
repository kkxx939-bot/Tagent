"""记忆管理入口。

这个模块负责把短期记忆和长期记忆串起来：
新任务开始时创建短期记忆，并从长期记忆里召回相关背景；
任务结束时生成任务摘要，再写入长期记忆。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from memory.LongTermMemory import LongTermMemory, MemoryRecord
from memory.MemoryProcessor import MemoryProcessor
from memory.SessionMemory import SessionMemory


class MemoryManager:
    """记忆层统一入口。"""

    def __init__(
        self,
        long_term_memory: LongTermMemory | None = None,
        memory_processor: MemoryProcessor | None = None,
        data_dir: str | Path | None = None,
    ) -> None:
        self.long_term_memory = long_term_memory or LongTermMemory(data_dir=data_dir)
        # TODO(记忆优化): balanced 模式会尝试模型提取；生产环境后续可改成异步执行。
        self.memory_processor = memory_processor or MemoryProcessor()
        self.current_session: SessionMemory | None = None
        self.last_task_summary: dict[str, Any] | None = None

    def start_task(
        self,
        user_query: str,
        task_id: str | None = None,
        intent_result: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        memory_query: str | None = None,
        memory_types: list[str] | None = None,
        memory_limit: int = 5,
        include_project_profile: bool = True,
    ) -> SessionMemory:
        """开始一次任务，并把相关长期记忆写入短期记忆。"""
        session = SessionMemory()
        session.start_task(user_query=user_query, task_id=task_id, metadata=metadata)

        if include_project_profile:
            project_profile = self.long_term_memory.load_project_profile()
            if project_profile:
                session.add_relevant_memory(
                    {
                        "memory_type": "project_profile",
                        "content": project_profile,
                        "source": project_profile.get("source", "local"),
                    }
                )

        for memory in self.load_relevant_memories(
            query=memory_query or user_query,
            memory_types=memory_types,
            limit=memory_limit,
        ):
            session.add_relevant_memory(memory)

        if intent_result:
            session.set_intent_result(intent_result)

        self.current_session = session
        return session

    def load_relevant_memories(
        self,
        query: str,
        memory_types: list[str] | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """从长期记忆中召回当前任务相关内容。"""
        return self.long_term_memory.search(query=query, memory_types=memory_types, limit=limit)

    def set_intent_result(self, intent_result: dict[str, Any]) -> None:
        self._require_session().set_intent_result(intent_result)

    def set_selected_skill(self, skill: str | dict[str, Any]) -> None:
        self._require_session().set_selected_skill(skill)

    def add_retrieved_context(self, context: dict[str, Any]) -> None:
        self._require_session().add_retrieved_context(context)

    def add_tool_result(self, tool_name: str, result: dict[str, Any]) -> None:
        self._require_session().add_tool_result(tool_name=tool_name, result=result)

    def add_generated_output(
        self,
        output_path: str,
        output_type: str,
        summary: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._require_session().add_generated_output(
            output_path=output_path,
            output_type=output_type,
            summary=summary,
            metadata=metadata,
        )

    def set_missing_context(self, missing_context: list[str]) -> None:
        self._require_session().set_missing_context(missing_context)

    def add_note(self, note: str) -> None:
        self._require_session().add_note(note)

    def complete_task(
        self,
        summary: str | None = None,
        final_status: str | None = None,
        persist_summary: bool = True,
        clear_runtime: bool = True,
    ) -> dict[str, Any]:
        """完成任务，并按需把任务摘要写入长期记忆。"""
        session = self._require_session()
        session.complete(summary=summary)
        session_summary = session.freeze_summary()
        if final_status:
            session_summary["status"] = final_status
        self.last_task_summary = session_summary

        persisted_records = []
        if persist_summary:
            candidates = self.memory_processor.build_candidates(session_summary)
            persisted_records = self.memory_processor.persist_candidates(self.long_term_memory, candidates)

        if clear_runtime:
            session.clear_runtime()
            self.current_session = None

        return {
            "session_summary": session_summary,
            "persisted_record": self._first_record(persisted_records),
            "persisted_records": persisted_records,
        }

    def fail_task(
        self,
        reason: str,
        persist_summary: bool = True,
        clear_runtime: bool = True,
    ) -> dict[str, Any]:
        """标记任务失败，并按需保存失败摘要。"""
        session = self._require_session()
        session.fail(reason=reason)
        session_summary = session.freeze_summary()
        session_summary["failure_reason"] = reason
        self.last_task_summary = session_summary

        persisted_records = []
        if persist_summary:
            candidates = self.memory_processor.build_candidates(session_summary)
            persisted_records = self.memory_processor.persist_candidates(self.long_term_memory, candidates)

        if clear_runtime:
            session.clear_runtime()
            self.current_session = None

        return {
            "session_summary": session_summary,
            "persisted_record": self._first_record(persisted_records),
            "persisted_records": persisted_records,
        }

    def save_user_preference(
        self,
        scope: str,
        content: str | dict[str, Any],
        source: str = "user",
        confidence: float = 0.9,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord:
        return self.long_term_memory.save_user_preference(
            scope=scope,
            content=content,
            source=source,
            confidence=confidence,
            tags=tags,
            metadata=metadata,
        )

    def save_feedback(
        self,
        target: str,
        feedback: str,
        action: str | None = None,
        source: str = "user",
        confidence: float = 0.9,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord:
        return self.long_term_memory.save_feedback(
            target=target,
            feedback=feedback,
            action=action,
            source=source,
            confidence=confidence,
            tags=tags,
            metadata=metadata,
        )

    def save_project_profile(self, updates: dict[str, Any], source: str = "user") -> dict[str, Any]:
        return self.long_term_memory.save_project_profile(updates=updates, source=source)

    def get_current_session(self) -> SessionMemory | None:
        return self.current_session

    def get_last_task_summary(self) -> dict[str, Any] | None:
        return self.last_task_summary

    def _require_session(self) -> SessionMemory:
        if not self.current_session:
            raise RuntimeError("当前没有运行中的 SessionMemory，请先调用 start_task()")
        return self.current_session

    def _record_to_dict(self, record: MemoryRecord | None) -> dict[str, Any] | None:
        if not record:
            return None
        return record.to_dict()

    def _first_record(self, records: list[dict[str, Any]]) -> dict[str, Any] | None:
        return records[0] if records else None
