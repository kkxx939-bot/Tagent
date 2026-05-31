from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol


LOCAL_BACKEND = "local"
OPENVIKING_BACKEND = "openviking"


@dataclass
class ContextRequest:
    context_type: str
    query: str
    inputs: dict[str, Any] = field(default_factory=dict)
    variables: dict[str, Any] = field(default_factory=dict)
    filters: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContextResult:
    success: bool
    context: dict[str, Any] = field(default_factory=dict)
    backend: str = LOCAL_BACKEND
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ContextBackend(Protocol):
    name: str

    def load(self, request: ContextRequest) -> ContextResult:
        ...


class LocalRagBackend:
    name = LOCAL_BACKEND

    def load(self, request: ContextRequest) -> ContextResult:
        from context import build_case_context

        context = build_case_context(request.query)
        return ContextResult(
            success=True,
            context=context,
            backend=self.name,
            metadata={
                "context_type": request.context_type,
                "query": request.query,
                "filters": request.filters,
            },
        )


def get_context_backend(name: str | None = None) -> ContextBackend:
    backend_name = normalize_backend_name(name or os.getenv("CONTEXT_BACKEND") or LOCAL_BACKEND)
    if backend_name == OPENVIKING_BACKEND:
        from openviking import OpenVikingBackend

        return OpenVikingBackend()
    return LocalRagBackend()


def load_context_from_backend(request: ContextRequest, backend_name: str | None = None) -> ContextResult:
    backend = get_context_backend(backend_name)
    return backend.load(request)


def normalize_backend_name(name: str) -> str:
    value = str(name or "").strip().lower()
    if value in {"openviking", "viking"}:
        return OPENVIKING_BACKEND
    return LOCAL_BACKEND
