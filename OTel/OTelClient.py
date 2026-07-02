"""Tagent OpenTelemetry client.

这一层只负责 OpenTelemetry SDK 的初始化和 span 操作，不负责定义业务字段。
业务字段由 OTel.TraceScheme 提供，业务代码只需要调用这里的 start_span、
set_span_attributes、record_exception 等辅助函数。

设计原则：
- 默认关闭，避免影响本地开发和现有测试。
- OpenTelemetry 是项目依赖，缺失时应在环境安装阶段暴露问题。
- 第一阶段支持 console exporter，方便学习和本地验证。
- 预留 OTLP HTTP exporter，后续可以接 OpenTelemetry Collector。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.trace import Status, StatusCode

from OTel.TraceScheme import AGENT_NAME, SCHEMA_VERSION, SERVICE_NAME, clean_attributes


DEFAULT_EXPORTER = "console"
DEFAULT_ENDPOINT = "http://localhost:4318/v1/traces"

_INITIALIZED = False
_TRACER: Any | None = None


class NoopSpan:
    """OpenTelemetry 未启用时使用的空 span。

    它提供和真实 span 相近的最小方法集合，让业务代码不用到处判断
    span 是否存在。
    """

    def set_attribute(self, key: str, value: Any) -> None:
        return None

    def set_attributes(self, attributes: dict[str, Any]) -> None:
        return None

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        return None

    def record_exception(self, exception: BaseException) -> None:
        return None

    def set_status(self, status: Any) -> None:
        return None

    def end(self) -> None:
        return None


def configure_otel(
    force: bool = False,
    *,
    enabled: bool = False,
    exporter: str | None = None,
    endpoint: str | None = None,
    service_name: str | None = None,
) -> bool:
    """初始化 OpenTelemetry tracer provider。

    只接受显式参数，不读取环境变量。
    返回 True 表示真实 OTel tracer 可用；False 表示当前未启用 OTel。
    这个函数是幂等的，可以被多次调用。
    """

    global _INITIALIZED, _TRACER

    if not enabled:
        return False
    if _INITIALIZED and not force:
        return _TRACER is not None

    resolved_service_name = (service_name or SERVICE_NAME).strip() or SERVICE_NAME
    exporter_name = (exporter or DEFAULT_EXPORTER).strip().lower() or DEFAULT_EXPORTER
    resolved_endpoint = (endpoint or DEFAULT_ENDPOINT).strip() or DEFAULT_ENDPOINT

    resource = Resource.create(
        {
            "service.name": resolved_service_name,
            "service.namespace": "tagent",
            "service.version": "local",
            "tagent.schema.version": SCHEMA_VERSION,
            "agent.name": AGENT_NAME,
        }
    )
    provider = TracerProvider(resource=resource)

    if exporter_name == "console":
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    elif exporter_name in {"otlp", "otlp_http"}:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=resolved_endpoint)))
    elif exporter_name in {"none", "noop"}:
        _TRACER = None
        _INITIALIZED = True
        return False
    else:
        raise ValueError(f"unsupported exporter: {exporter_name}")

    trace.set_tracer_provider(provider)
    _TRACER = trace.get_tracer("tagent", SCHEMA_VERSION)
    _INITIALIZED = True
    return True


def get_tracer() -> Any | None:
    """获取真实 tracer；未显式初始化时返回 None。"""

    return _TRACER


@contextmanager
def start_span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """创建一个 span 上下文。

    用法：

        with start_span("tagent.agent_run", attrs) as span:
            ...

    如果 OTel 未启用，返回 NoopSpan，业务逻辑照常执行。
    如果 with 块内部抛异常，会自动记录 exception 并把 span 标记为 error。
    """

    tracer = get_tracer()
    if tracer is None:
        yield NoopSpan()
        return

    with tracer.start_as_current_span(name) as span:
        set_span_attributes(span, attributes)
        try:
            yield span
        except Exception as exc:
            record_exception(span, exc)
            mark_span_error(span, exc)
            raise


def set_span_attributes(span: Any, attributes: dict[str, Any] | None) -> None:
    """批量写入 span attributes。

    attributes 会先经过 TraceScheme.clean_attributes，过滤 None 并规整成
    OTel 支持的基础类型。
    """

    if span is None or attributes is None:
        return
    for key, value in clean_attributes(attributes).items():
        try:
            span.set_attribute(key, value)
        except Exception:
            continue


def add_event(span: Any, name: str, attributes: dict[str, Any] | None = None) -> None:
    """给 span 添加事件。"""

    if span is None:
        return
    try:
        span.add_event(name, clean_attributes(attributes or {}))
    except Exception:
        return


def record_exception(span: Any, exc: BaseException) -> None:
    """记录异常对象。"""

    if span is None:
        return
    try:
        span.record_exception(exc)
    except Exception:
        return


def mark_span_error(span: Any, error: BaseException | str | None = None) -> None:
    """把 span 标记为 error。

    这个函数只负责设置 OTel status，不负责抛异常。
    """

    if span is None:
        return

    description = str(error) if error else None
    try:
        span.set_status(Status(StatusCode.ERROR, description))
    except Exception:
        return


def mark_span_ok(span: Any) -> None:
    """显式把 span 标记为 OK。"""

    if span is None:
        return

    try:
        span.set_status(Status(StatusCode.OK))
    except Exception:
        return


__all__ = [
    "NoopSpan",
    "add_event",
    "configure_otel",
    "get_tracer",
    "mark_span_error",
    "mark_span_ok",
    "record_exception",
    "set_span_attributes",
    "start_span",
]
