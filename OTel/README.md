# Tagent OpenTelemetry Collector 本地验证

这一阶段的目标不是直接接 Grafana，而是先验证：

```text
Tagent -> OpenTelemetry SDK -> OTLP HTTP -> Collector -> debug exporter
```

## 1. 启动 Collector

在项目根目录执行：

```bash
docker run --rm \
  --name tagent-otel-collector \
  -p 4317:4317 \
  -p 4318:4318 \
  -v "$PWD/OTel/collector-config.yaml:/etc/otelcol/config.yaml" \
  otel/opentelemetry-collector:0.154.0
```

说明：

- `4318` 是 OTLP HTTP，Tagent 当前用这个端口发送 trace。
- `4317` 是 OTLP gRPC，先保留，后续接其他 SDK 或服务时可能会用。
- `debug exporter` 会把收到的 span 打印在 Collector 日志里。

## 2. 让 Tagent 发到 Collector

在 `config.py` 中打开 OTel：

```python
OTEL_ENABLED = True
OTEL_EXPORTER = "otlp"
OTEL_ENDPOINT = "http://localhost:4318/v1/traces"
OTEL_SERVICE_NAME = "tagent"
```

另开一个终端，在项目根目录执行：

```bash
/opt/anaconda3/envs/Tagent/bin/python main.py "traceId abc123 的登录失败帮我排查"
```

预期现象：

- Tagent 侧不再像 `console exporter` 那样直接打印 span JSON。
- Collector 终端会打印 `tagent.agent_run`、`tagent.intent.recognize`、`tagent.llm.call`、`tagent.executor.step`、`tagent.tool.call` 等 span。
- 同一次请求里的 span 应该有相同的 `Trace ID`。

## 3. 常见问题

如果 Tagent 报连接错误，先确认 Collector 正在运行，并且 `4318` 已映射到本机。

如果 Collector 没有输出 span，先把 `config.py` 里的 `OTEL_EXPORTER` 改成 `"console"`，验证 Tagent 本身是否能生成 span，再切回 `"otlp"`。

如果后续接 Tempo/Grafana，不要删除这个配置；建议复制一份新配置，在 exporters 里追加 Tempo 的 OTLP endpoint。
