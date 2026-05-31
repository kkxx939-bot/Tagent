from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError

import requests


DEFAULT_TARGET_URI = "viking://resources"
DEFAULT_TIMEOUT = 30.0
DEFAULT_NODE_LIMIT = 12


@dataclass
class OpenVikingConfig:
    url: str
    api_key: str | None = None
    target_uri: str = DEFAULT_TARGET_URI
    search_mode: str = "find"
    node_limit: int = DEFAULT_NODE_LIMIT
    timeout: float = DEFAULT_TIMEOUT
    score_threshold: float | None = None
    level: str | None = None
    include_provenance: bool = False
    telemetry: bool = False
    session_id: str | None = None
    account: str | None = None
    user: str | None = None
    agent_id: str | None = None
    use_metadata_filter: bool = False

    @classmethod
    def from_env(cls) -> "OpenVikingConfig":
        return cls(
            url=os.getenv("OPENVIKING_URL", "").strip(),
            api_key=os.getenv("OPENVIKING_API_KEY") or None,
            target_uri=os.getenv("OPENVIKING_TARGET_URI", DEFAULT_TARGET_URI),
            search_mode=normalize_search_mode(os.getenv("OPENVIKING_SEARCH_MODE", "find")),
            node_limit=int_env("OPENVIKING_NODE_LIMIT", DEFAULT_NODE_LIMIT),
            timeout=float_env("OPENVIKING_TIMEOUT", DEFAULT_TIMEOUT),
            score_threshold=optional_float_env("OPENVIKING_SCORE_THRESHOLD"),
            level=os.getenv("OPENVIKING_LEVEL") or None,
            include_provenance=bool_env("OPENVIKING_INCLUDE_PROVENANCE", False),
            telemetry=bool_env("OPENVIKING_TELEMETRY", False),
            session_id=os.getenv("OPENVIKING_SESSION_ID") or None,
            account=os.getenv("OPENVIKING_ACCOUNT") or None,
            user=os.getenv("OPENVIKING_USER") or None,
            agent_id=os.getenv("OPENVIKING_AGENT_ID") or None,
            use_metadata_filter=bool_env("OPENVIKING_USE_METADATA_FILTER", False),
        )

    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            headers["X-API-Key"] = self.api_key
        if self.account:
            headers["X-OpenViking-Account"] = self.account
        if self.user:
            headers["X-OpenViking-User"] = self.user
        if self.agent_id:
            headers["X-OpenViking-Agent"] = self.agent_id
        return headers


class OpenVikingClient:
    def __init__(self, config: OpenVikingConfig) -> None:
        self.config = config

    def search(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.config.url.rstrip('/')}/api/v1/search/{self.config.search_mode}"
        return post_json(url=url, payload=payload, headers=self.config.headers(), timeout=self.config.timeout)


def build_search_payload(query: str, filters: dict[str, Any], config: OpenVikingConfig) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": query,
        "target_uri": config.target_uri,
        "node_limit": config.node_limit,
        "include_provenance": config.include_provenance,
        "telemetry": config.telemetry,
    }
    if config.score_threshold is not None:
        payload["score_threshold"] = config.score_threshold
    if config.level:
        payload["level"] = config.level
    if config.search_mode == "search" and config.session_id:
        payload["session_id"] = config.session_id
    if config.use_metadata_filter and filters:
        payload["filter"] = filters
    return payload


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise URLError(str(exc)) from exc
    if response.status_code >= 400:
        raise HTTPError(url, response.status_code, response.text or response.reason, response.headers, None)
    return response.json()


def read_http_error(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        body = ""
    return body or str(exc)


def normalize_search_mode(value: str) -> str:
    mode = str(value or "").strip().lower()
    if mode == "search":
        return "search"
    return "find"


def int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def optional_float_env(name: str) -> float | None:
    value = os.getenv(name)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "HTTPError",
    "URLError",
    "OpenVikingClient",
    "OpenVikingConfig",
    "build_search_payload",
    "read_http_error",
]
