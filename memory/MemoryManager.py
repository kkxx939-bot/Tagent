"""记忆管理入口。

这个模块负责把短期记忆和长期记忆串起来：
新任务开始时创建短期记忆，并从长期记忆里召回相关背景；
任务结束时生成任务摘要，再写入长期记忆。
"""

from __future__ import annotations

import atexit
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from memory.LongTermMemory import LongTermMemory, MemoryRecord
from memory.MemoryProcessor import MemoryProcessor
from memory.SessionMemory import SessionMemory


_MEMORY_PERSIST_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tagent-memory-persist")


def _shutdown_memory_persist_executor() -> None:
    _MEMORY_PERSIST_EXECUTOR.shutdown(wait=True)


atexit.register(_shutdown_memory_persist_executor)


def _persist_candidates_background(
    memory_processor: MemoryProcessor,
    long_term_memory: LongTermMemory,
    session_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates = memory_processor.build_candidates(session_summary)
    return memory_processor.persist_candidates(long_term_memory, candidates)


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
        final_output: dict[str, Any] | None = None,
        error: str | None = None,
        persist_summary: bool = True,
        persist_async: bool = False,
        clear_runtime: bool = True,
    ) -> dict[str, Any]:
        """完成任务，并按需把任务摘要写入长期记忆。"""
        session = self._require_session()
        status = final_status or "completed"
        session.set_result_quality(
            final_output_summary=_summarize_final_output(final_output or {}, status=status, error=error),
            result_quality=_build_result_quality(final_output or {}, status=status, error=error),
        )
        session.complete(summary=summary)
        session_summary = session.freeze_summary()
        session_summary["status"] = status
        self.last_task_summary = session_summary

        persisted_records = []
        persist_future: Future[list[dict[str, Any]]] | None = None
        persistence_status = "skipped"
        if persist_summary:
            if persist_async:
                persist_future = _MEMORY_PERSIST_EXECUTOR.submit(
                    _persist_candidates_background,
                    self.memory_processor,
                    self.long_term_memory,
                    dict(session_summary),
                )
                persistence_status = "scheduled"
            else:
                candidates = self.memory_processor.build_candidates(session_summary)
                persisted_records = self.memory_processor.persist_candidates(self.long_term_memory, candidates)
                persistence_status = "completed"

        if clear_runtime:
            session.clear_runtime()
            self.current_session = None

        return {
            "session_summary": session_summary,
            "persisted_record": self._first_record(persisted_records),
            "persisted_records": persisted_records,
            "persistence": {
                "mode": "async" if persist_async else "sync",
                "status": persistence_status,
                "future_id": id(persist_future) if persist_future else None,
            },
        }

    def fail_task(
        self,
        reason: str,
        final_output: dict[str, Any] | None = None,
        persist_summary: bool = True,
        clear_runtime: bool = True,
    ) -> dict[str, Any]:
        """标记任务失败，并按需保存失败摘要。"""
        session = self._require_session()
        session.set_result_quality(
            final_output_summary=_summarize_final_output(final_output or {}, status="failed", error=reason),
            result_quality=_build_result_quality(final_output or {}, status="failed", error=reason),
        )
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


def _summarize_final_output(
    final_output: dict[str, Any],
    *,
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    artifacts = final_output.get("artifacts") if isinstance(final_output, dict) else []
    tool_results = final_output.get("tool_results") if isinstance(final_output, dict) else []
    warnings = final_output.get("warnings") if isinstance(final_output, dict) else []
    grounding_reports = _grounding_reports_from_final_output(final_output)
    summary = {
        "status": status,
        "error": error,
        "artifact_count": len(artifacts) if isinstance(artifacts, list) else 0,
        "tool_result_count": len(tool_results) if isinstance(tool_results, list) else 0,
        "warning_count": len(warnings) if isinstance(warnings, list) else 0,
        "has_capability_gap": bool(final_output.get("capability_gap")) if isinstance(final_output, dict) else False,
        "missing_context": list(final_output.get("missing_context") or []) if isinstance(final_output, dict) else [],
    }
    if grounding_reports:
        summary["grounding"] = _compact_grounding_reports(grounding_reports)
    return summary


def _build_result_quality(
    final_output: dict[str, Any],
    *,
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    reasons = []
    grounding_reports = _grounding_reports_from_final_output(final_output)
    grounding = _compact_grounding_reports(grounding_reports) if grounding_reports else {}

    reusable = status == "completed" and not error
    quality = "usable" if reusable else "not_reusable"
    confidence = 0.85 if reusable else 0.2

    if error:
        reasons.append("execution_error")
    if status in {"failed", "waiting_for_user", "capability_gap"}:
        reasons.append(status)
        reusable = False
        quality = "not_reusable"
        confidence = 0.2
    if isinstance(final_output, dict) and final_output.get("capability_gap"):
        reasons.append("capability_gap")
        reusable = False
        quality = "not_reusable"
        confidence = 0.2
    if grounding:
        if grounding.get("invalid_source_ref_count") or grounding.get("unsupported_case_count"):
            reasons.append("grounding_failed")
            reusable = False
            quality = "not_reusable"
            confidence = 0.2
        elif grounding.get("warning_count"):
            reasons.append("grounding_warning")
            quality = "weakly_supported"
            confidence = min(confidence, 0.65)

    return {
        "quality": quality,
        "should_reuse": reusable,
        "confidence": confidence,
        "reasons": _dedupe_text(reasons),
        "grounding": grounding,
    }


def _grounding_reports_from_final_output(final_output: dict[str, Any]) -> list[dict[str, Any]]:
    reports = []
    if not isinstance(final_output, dict):
        return reports

    summary = final_output.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("grounding_report"), dict):
        reports.append(summary["grounding_report"])

    for artifact in final_output.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        metadata = artifact.get("metadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("grounding_report"), dict):
            reports.append(metadata["grounding_report"])
    return reports


def _compact_grounding_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    compact = {
        "report_count": 0,
        "status": "not_applicable",
        "case_count": 0,
        "grounded_case_count": 0,
        "weakly_supported_case_count": 0,
        "unsupported_case_count": 0,
        "invalid_source_ref_count": 0,
        "warning_count": 0,
    }
    for report in reports:
        if not isinstance(report, dict):
            continue
        compact["report_count"] += 1
        compact["case_count"] += int(report.get("case_count") or 0)
        compact["grounded_case_count"] += int(report.get("grounded_case_count") or 0)
        compact["weakly_supported_case_count"] += int(report.get("weakly_supported_case_count") or 0)
        compact["unsupported_case_count"] += int(report.get("unsupported_case_count") or 0)
        compact["invalid_source_ref_count"] += int(report.get("invalid_source_ref_count") or 0)
        compact["warning_count"] += len(report.get("warnings") or [])
    if compact["report_count"]:
        compact["status"] = "warning" if compact["warning_count"] else "ok"
    return compact


def _dedupe_text(items: list[str]) -> list[str]:
    result = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result
