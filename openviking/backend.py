from __future__ import annotations

from typing import Any

from openviking.client import (
    HTTPError,
    URLError,
    OpenVikingClient,
    OpenVikingConfig,
    build_search_payload,
    read_http_error,
)
from openviking.mapper import OPENVIKING_BACKEND, response_to_context


class OpenVikingBackend:
    name = OPENVIKING_BACKEND

    def load(self, request: Any) -> Any:
        from ContextBackend import ContextResult

        config = OpenVikingConfig.from_env()
        if not config.url:
            return ContextResult(
                success=False,
                backend=self.name,
                error="openviking_url_not_configured",
                warnings=["缺少 OPENVIKING_URL，无法连接 OpenViking。"],
                metadata=backend_metadata(request, config),
            )

        payload = build_search_payload(request.query, request.filters, config)
        try:
            response = OpenVikingClient(config).search(payload)
        except HTTPError as exc:
            return ContextResult(
                success=False,
                backend=self.name,
                error=f"openviking_http_{exc.code}",
                warnings=[read_http_error(exc)],
                metadata={**backend_metadata(request, config), "request_payload": redact_payload(payload)},
            )
        except URLError as exc:
            return ContextResult(
                success=False,
                backend=self.name,
                error="openviking_connection_error",
                warnings=[str(exc.reason)],
                metadata={**backend_metadata(request, config), "request_payload": redact_payload(payload)},
            )

        if response.get("status") != "ok":
            error = response.get("error") if isinstance(response.get("error"), dict) else {}
            return ContextResult(
                success=False,
                backend=self.name,
                error=str(error.get("code") or "openviking_error"),
                warnings=[str(error.get("message") or response)],
                metadata={**backend_metadata(request, config), "request_payload": redact_payload(payload)},
            )

        result = response.get("result") or {}
        context = response_to_context(
            query=request.query,
            result=result,
            target_uri=config.target_uri,
            search_mode=config.search_mode,
        )
        return ContextResult(
            success=True,
            context=context,
            backend=self.name,
            metadata={
                **backend_metadata(request, config),
                "request_payload": redact_payload(payload),
                "openviking_total": result.get("total"),
                "openviking_time": response.get("time"),
            },
        )


def backend_metadata(request: Any, config: OpenVikingConfig) -> dict[str, Any]:
    return {
        "context_type": request.context_type,
        "query": request.query,
        "filters": request.filters,
        "target_uri": config.target_uri,
        "search_mode": config.search_mode,
        "node_limit": config.node_limit,
        "level": config.level,
        "use_metadata_filter": config.use_metadata_filter,
    }


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(payload)
