"""长期记忆处理器。

这里把“记忆策略、记忆提取、记忆校验”放在一个类里：
规则负责边界，模型负责总结，校验负责过滤和脱敏。
"""

from __future__ import annotations

import json
import re
from typing import Any

from memory.LongTermMemory import LongTermMemory
from prompts.prompt_memory import build_memory_process_prompt
from tools.redaction import redact_value

try:
    from llm_client import call_llm
except ModuleNotFoundError:
    call_llm = None


ALLOWED_ACTIONS = {
    "save_task_summary",
    "save_user_preference",
    "save_feedback",
    "save_project_profile",
    "skip",
}

MODE_CONFIGS = {
    "safe": {
        "use_llm": False,
        "min_confidence": 0.65,
        "allowed_persist_actions": {"save_task_summary", "save_user_preference", "save_feedback"},
    },
    "balanced": {
        "use_llm": True,
        "min_confidence": 0.85,
        "allowed_persist_actions": {"save_task_summary", "save_user_preference", "save_feedback"},
    },
}

SENSITIVE_KEYS = {
    "token",
    "cookie",
    "password",
    "passwd",
    "secret",
    "authorization",
    "api_key",
    "apikey",
    "llm_api_key",
}


class MemoryProcessor:
    """任务结束时使用的长期记忆处理器。"""


    # TODO(记忆优化): 当前不做 enabled/disabled；后续需要记忆治理时，再加禁用、恢复和删除能力。
    def __init__(
        self,
        mode: str = "balanced",
        use_llm: bool | None = None,
        min_confidence: float | None = None,
        allowed_persist_actions: set[str] | None = None,
        persist_task_statuses: set[str] | None = None,
        skip_task_intents: set[str] | None = None,
    ) -> None:
        config = self._resolve_mode_config(mode)
        self.mode = mode
        self.use_llm = config["use_llm"] if use_llm is None else use_llm
        self.min_confidence = config["min_confidence"] if min_confidence is None else min_confidence
        self.allowed_persist_actions = set(allowed_persist_actions or config["allowed_persist_actions"])
        self.persist_task_statuses = persist_task_statuses or {"completed"}
        self.skip_task_intents = skip_task_intents or {"UNKNOWN"}

    def build_candidates(self, session_summary: dict[str, Any]) -> list[dict[str, Any]]:
        """从任务摘要中提取候选长期记忆。"""
        safe_summary = self._safe_summary(session_summary)
        if self.use_llm:
            llm_candidates = self._build_candidates_with_llm(safe_summary)
            validated = self.validate_candidates(llm_candidates, safe_summary)
            if validated:
                return validated

        return self.validate_candidates(self._build_rule_candidates(safe_summary), safe_summary)

    def persist_candidates(
        self,
        long_term_memory: LongTermMemory,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """把候选记忆写入长期记忆。"""
        persisted = []
        for candidate in candidates:
            action = candidate["action"]
            content = candidate.get("content") or {}
            confidence = float(candidate.get("confidence") or 0.0)
            tags = list(candidate.get("tags") or [])

            if action == "save_task_summary":
                record = long_term_memory.save_task_summary(
                    task_summary=content,
                    source="memory_processor",
                    confidence=confidence,
                    tags=tags,
                )
                persisted.append(record.to_dict())
            elif action == "save_user_preference":
                record = long_term_memory.save_user_preference(
                    scope=str(candidate.get("scope") or content.get("scope") or "general"),
                    content=content.get("preference", content),
                    source="memory_processor",
                    confidence=confidence,
                    tags=tags,
                    metadata={"reason": candidate.get("reason")},
                )
                persisted.append(record.to_dict())
            elif action == "save_feedback":
                record = long_term_memory.save_feedback(
                    target=str(candidate.get("scope") or content.get("target") or "general"),
                    feedback=str(content.get("feedback") or content),
                    action=content.get("action"),
                    source="memory_processor",
                    confidence=confidence,
                    tags=tags,
                    metadata={"reason": candidate.get("reason")},
                )
                persisted.append(record.to_dict())
            elif action == "save_project_profile":
                profile = long_term_memory.save_project_profile(
                    updates=content,
                    source="memory_processor",
                )
                persisted.append(
                    {
                        "memory_type": "project_profile",
                        "content": profile,
                        "source": "memory_processor",
                        "confidence": confidence,
                        "tags": tags,
                    }
                )

        return persisted

    def validate_candidates(
        self,
        candidates: list[dict[str, Any]],
        session_summary: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """校验候选记忆，过滤敏感、低置信和非法结构。"""
        validated = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue

            action = str(candidate.get("action") or "")
            if action not in ALLOWED_ACTIONS or action == "skip":
                continue
            if action not in self.allowed_persist_actions:
                continue
            if action == "save_task_summary" and not self._should_save_task_summary(session_summary):
                continue

            confidence = self._safe_confidence(candidate.get("confidence"))
            if action != "save_task_summary" and confidence < self.min_confidence:
                continue

            raw_content = candidate.get("content") or {}
            if not isinstance(raw_content, dict):
                raw_content = {"value": str(raw_content)}
            content = self._sanitize_value(raw_content)
            if self._contains_sensitive_key(content):
                continue

            if action == "save_task_summary":
                content = self._normalize_task_summary(content, session_summary)
            elif action == "save_project_profile" and not self._has_explicit_project_profile_signal(
                session_summary, candidate
            ):
                continue

            validated.append(
                {
                    "action": action,
                    "memory_type": candidate.get("memory_type") or self._memory_type_by_action(action),
                    "scope": candidate.get("scope"),
                    "content": content,
                    "confidence": confidence,
                    "tags": self._normalize_tags(candidate.get("tags")),
                    "reason": str(candidate.get("reason") or ""),
                }
            )

        if self._should_save_task_summary(session_summary) and not any(
            item["action"] == "save_task_summary" for item in validated
        ):
            validated.insert(0, self._task_summary_candidate(session_summary))

        return validated

    def _build_candidates_with_llm(self, session_summary: dict[str, Any]) -> list[dict[str, Any]]:
        if call_llm is None:
            return []

        try:
            response = call_llm(
                build_memory_process_prompt(session_summary),
                temperature=0.1,
                max_tokens=1200,
                llm_task="memory_summary",
            )
            payload = self._parse_json_response(response)
        except Exception:
            return []

        candidates = payload.get("candidates") if isinstance(payload, dict) else None
        return candidates if isinstance(candidates, list) else []

    def _resolve_mode_config(self, mode: str) -> dict[str, Any]:
        if mode not in MODE_CONFIGS:
            raise ValueError(f"未知记忆处理模式：{mode}")
        return MODE_CONFIGS[mode]

    def _build_rule_candidates(self, session_summary: dict[str, Any]) -> list[dict[str, Any]]:
        candidates = []
        if self._should_save_task_summary(session_summary):
            candidates.append(self._task_summary_candidate(session_summary))

        for note in session_summary.get("notes") or []:
            note_text = str(note)
            if self._looks_like_preference(note_text):
                candidates.append(
                    {
                        "action": "save_user_preference",
                        "memory_type": "user_preference",
                        "scope": "general",
                        "content": {"preference": note_text},
                        "confidence": 0.72,
                        "tags": ["preference"],
                        "reason": "任务备注中出现用户偏好表达",
                    }
                )

        return candidates

    def _task_summary_candidate(self, session_summary: dict[str, Any]) -> dict[str, Any]:
        return {
            "action": "save_task_summary",
            "memory_type": "task_summary",
            "scope": "task",
            "content": self._safe_summary(session_summary),
            "confidence": 0.85,
            "tags": self._task_tags(session_summary),
            "reason": "任务摘要可用于后续查询历史任务",
        }

    def _should_save_task_summary(self, session_summary: dict[str, Any]) -> bool:
        status = str(session_summary.get("status") or "").lower()
        intent = str(session_summary.get("intent") or "")
        if status not in self.persist_task_statuses:
            return False
        if intent in self.skip_task_intents:
            return False
        result_quality = session_summary.get("result_quality")
        if isinstance(result_quality, dict) and result_quality.get("should_reuse") is False:
            return False
        return True

    def _safe_summary(self, session_summary: dict[str, Any]) -> dict[str, Any]:
        allowed_keys = {
            "session_id",
            "task_id",
            "user_query",
            "status",
            "intent",
            "selected_skill",
            "generated_outputs",
            "missing_context",
            "final_output_summary",
            "result_quality",
            "notes",
            "started_at",
            "completed_at",
            "failure_reason",
        }
        return self._sanitize_value({key: session_summary.get(key) for key in allowed_keys if key in session_summary})

    def _normalize_task_summary(
        self,
        content: dict[str, Any],
        session_summary: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(content, dict):
            return self._safe_summary(session_summary)
        normalized = self._safe_summary({**session_summary, **content})
        if not normalized.get("task_id"):
            normalized["task_id"] = session_summary.get("task_id")
        if not normalized.get("status"):
            normalized["status"] = session_summary.get("status")
        return normalized

    def _parse_json_response(self, response: str) -> dict[str, Any]:
        text = response.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text).strip()
            text = re.sub(r"```$", "", text).strip()
        return json.loads(text)

    def _safe_confidence(self, value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(confidence, 1.0))

    def _contains_sensitive_key(self, value: Any) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                normalized_key = str(key).lower().replace("-", "_")
                if normalized_key in SENSITIVE_KEYS:
                    return True
                if self._contains_sensitive_key(item):
                    return True
        if isinstance(value, list):
            return any(self._contains_sensitive_key(item) for item in value)
        return False

    def _sanitize_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            cleaned = {}
            for key, item in value.items():
                normalized_key = str(key).lower().replace("-", "_")
                if normalized_key in SENSITIVE_KEYS:
                    continue
                cleaned[key] = self._sanitize_value(item)
            return redact_value(cleaned)
        if isinstance(value, list):
            return [self._sanitize_value(item) for item in value]
        return redact_value(value)

    def _looks_like_preference(self, text: str) -> bool:
        keywords = ("以后", "下次", "默认", "偏好", "优先", "不要", "需要", "保持", "统一")
        return any(keyword in text for keyword in keywords)

    def _has_explicit_project_profile_signal(
        self,
        session_summary: dict[str, Any],
        candidate: dict[str, Any],
    ) -> bool:
        text_parts = [
            str(session_summary.get("user_query") or ""),
            " ".join(str(note) for note in session_summary.get("notes") or []),
            str(candidate.get("reason") or ""),
        ]
        text = " ".join(text_parts)
        explicit_keywords = ("以后默认", "默认保存", "作为默认", "项目默认", "设为默认", "固定使用")
        return any(keyword in text for keyword in explicit_keywords)

    def _normalize_tags(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if item]

    def _task_tags(self, session_summary: dict[str, Any]) -> list[str]:
        tags = []
        for key in ("intent", "selected_skill", "status"):
            value = session_summary.get(key)
            if value:
                tags.append(str(value))
        return tags

    def _memory_type_by_action(self, action: str) -> str:
        return {
            "save_task_summary": "task_summary",
            "save_user_preference": "user_preference",
            "save_feedback": "feedback",
            "save_project_profile": "project_profile",
        }.get(action, "unknown")
