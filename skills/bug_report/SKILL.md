# Bug 报告技能

## 目标

当用户要基于失败现象、证据和预期行为生成清晰可复现的 Bug 报告时，使用这个技能。

## 触发条件

当主意图是 `BUG_REPORT_GENERATION` 时使用。

典型请求：

```text
帮我生成 Bug 报告
把这个问题整理成缺陷单
根据这个失败现象写 bug
```

## 输入

```text
模块
环境
前置条件
复现步骤
实际结果
预期结果
截图 / 日志 / requestId / traceId
影响范围
```

## 工作流程

1. 提取失败摘要。

2. 分清实际结果和预期结果。

3. 整理可复现步骤。

4. 补充环境和证据。

5. 给出严重级别和优先级，并说明理由。

6. 输出结构化 Bug 报告。

## 计划接入的工具

```text
search_related_bugs(keyword)
get_api_contract(api_name)
query_trace_log(trace_id)
```

## 输出约定

```json
{
  "title": "...",
  "module": "...",
  "environment": "...",
  "precondition": "...",
  "steps_to_reproduce": [],
  "actual_result": "...",
  "expected_result": "...",
  "severity": "...",
  "priority": "...",
  "evidence": [],
  "impact": "...",
  "notes": []
}
```

## 质量检查

```text
标题是否清楚
步骤是否可复现
实际结果和预期结果是否分开
证据是否可追溯
严重级别是否有依据
是否遗漏环境
```

## 禁止事项

```text
不要把推测写成事实
不要输出敏感账号、token、cookie、密码
不要编造预期结果
```

## 兜底策略

如果缺少预期结果：

```text
能检索需求时先补充需求上下文
否则让用户确认预期行为
```

如果缺少复现步骤：

```text
先补充步骤，再生成最终 Bug 报告
```
