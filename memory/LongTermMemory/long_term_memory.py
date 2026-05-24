"""轻量长期记忆。

长期记忆只保存跨任务可复用的信息，例如项目画像、用户偏好、任务摘要和用户反馈。
原始日志、token、cookie、完整工具输出这类临时或敏感内容不应该直接写入这里。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    from tools.redaction import redact_value
except ModuleNotFoundError:
    def redact_value(value: Any) -> Any:
        return value


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _default_data_dir() -> Path:
    return Path(__file__).resolve().parent / "data"


@dataclass
class MemoryRecord:
    """长期记忆里的单条记录。"""

    memory_type: str
    content: dict[str, Any]
    source: str
    memory_id: str = field(default_factory=lambda: f"mem_{uuid4().hex[:12]}")
    tags: list[str] = field(default_factory=list)
    confidence: float = 1.0
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    expires_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LongTermMemory:
    """本地文件版长期记忆管理器。"""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir else _default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.project_profile_path = self.data_dir / "project_profile.json"
        self.user_preferences_path = self.data_dir / "user_preferences.json"
        self.task_history_path = self.data_dir / "task_history.jsonl"
        self.feedback_path = self.data_dir / "feedback.jsonl"

    def save_project_profile(
        self,
        updates: dict[str, Any],
        source: str = "user",
    ) -> dict[str, Any]:
        """合并保存项目默认信息。"""
        profile = self.load_project_profile()
        profile.update(redact_value(updates))
        profile["updated_at"] = _now()
        profile["source"] = source
        self._write_json(self.project_profile_path, profile)
        return profile

    def load_project_profile(self) -> dict[str, Any]:
        return self._read_json(self.project_profile_path, default={})

    def save_user_preference(
        self,
        scope: str,
        content: str | dict[str, Any],
        source: str = "user",
        confidence: float = 0.9,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord:
        """按 scope 保存或更新用户偏好。"""
        preferences = self.load_user_preferences()
        old_record = preferences.get(scope)
        if isinstance(old_record, dict):
            memory_id = str(old_record.get("memory_id") or f"mem_{uuid4().hex[:12]}")
            created_at = str(old_record.get("created_at") or _now())
        else:
            memory_id = f"mem_{uuid4().hex[:12]}"
            created_at = _now()

        record = MemoryRecord(
            memory_id=memory_id,
            memory_type="user_preference",
            content={"scope": scope, "preference": redact_value(content)},
            source=source,
            tags=tags or [],
            confidence=confidence,
            created_at=created_at,
            metadata=metadata or {},
        )
        preferences[scope] = record.to_dict()
        self._write_json(self.user_preferences_path, preferences)
        return record

    def load_user_preferences(self) -> dict[str, dict[str, Any]]:
        return self._read_json(self.user_preferences_path, default={})

    def save_task_summary(
        self,
        task_summary: dict[str, Any],
        source: str = "session_memory",
        confidence: float = 0.85,
        tags: list[str] | None = None,
    ) -> MemoryRecord:
        """保存任务结束后的摘要，不保存完整运行态。"""
        record = MemoryRecord(
            memory_type="task_summary",
            content=redact_value(task_summary),
            source=source,
            tags=tags or self._build_task_tags(task_summary),
            confidence=confidence,
        )
        self._append_jsonl(self.task_history_path, record.to_dict())
        return record

    def list_recent_tasks(self, limit: int = 10) -> list[dict[str, Any]]:
        tasks = self._read_jsonl(self.task_history_path)
        return tasks[-limit:][::-1]

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
        """保存用户对结果或流程的反馈。"""
        record = MemoryRecord(
            memory_type="feedback",
            content=redact_value(
                {
                    "target": target,
                    "feedback": feedback,
                    "action": action,
                }
            ),
            source=source,
            tags=tags or [target],
            confidence=confidence,
            metadata=metadata or {},
        )
        self._append_jsonl(self.feedback_path, record.to_dict())
        return record

    def list_feedback(self, limit: int = 20) -> list[dict[str, Any]]:
        feedback = self._read_jsonl(self.feedback_path)
        return feedback[-limit:][::-1]

    def search(
        self,
        query: str,
        memory_types: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """简单关键词检索，后续可以替换成向量检索。"""
        normalized_query = " ".join((query or "").lower().split())
        if not normalized_query:
            return []

        allowed_types = set(memory_types or [])
        candidates = self._load_all_records()
        matched = []
        for record in candidates:
            memory_type = str(record.get("memory_type") or "")
            if allowed_types and memory_type not in allowed_types:
                continue

            searchable = json.dumps(record, ensure_ascii=False).lower()
            score = self._match_score(normalized_query, searchable)
            if score > 0:
                matched.append((score, record))

        matched.sort(
            key=lambda item: (
                item[0],
                str(item[1].get("updated_at") or item[1].get("created_at") or ""),
            ),
            reverse=True,
        )
        return [record for _, record in matched[:limit]]

    def _load_all_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []

        profile = self.load_project_profile()
        if profile:
            records.append(
                MemoryRecord(
                    memory_type="project_profile",
                    content=profile,
                    source=str(profile.get("source") or "local"),
                    confidence=1.0,
                ).to_dict()
            )

        records.extend(self.load_user_preferences().values())
        records.extend(self._read_jsonl(self.task_history_path))
        records.extend(self._read_jsonl(self.feedback_path))
        return records

    def _build_task_tags(self, task_summary: dict[str, Any]) -> list[str]:
        tags = []
        intent = task_summary.get("intent")
        skill = task_summary.get("selected_skill")
        status = task_summary.get("status")
        if intent:
            tags.append(str(intent))
        if skill:
            tags.append(str(skill))
        if status:
            tags.append(str(status))
        return tags

    def _match_score(self, normalized_query: str, searchable: str) -> int:
        if normalized_query in searchable:
            return 100

        score = 0
        for term in self._query_terms(normalized_query):
            if term in searchable:
                score += max(len(term), 1)
        return score

    def _query_terms(self, normalized_query: str) -> set[str]:
        terms = set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{2,}", normalized_query))
        for term in list(terms):
            if re.fullmatch(r"[\u4e00-\u9fff]{4,}", term):
                terms.update(term[index : index + 2] for index in range(len(term) - 1))
        return {term for term in terms if len(term) >= 2}

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default

    def _write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _append_jsonl(self, path: Path, record: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []

        records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records
