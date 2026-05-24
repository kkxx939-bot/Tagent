# 失败排查技能

## 目标

当用户反馈产品、接口、数据、环境或执行失败，并希望先判断排查方向时，使用这个技能。

这个技能不在缺少证据时直接下根因结论，而是先收集上下文、判断排查方向、指出缺失信息，并给出下一步检查建议。

## 触发条件

当主意图是 `FAILURE_TRIAGE` 时使用。

典型请求：

```text
登录接口返回 500，有 requestId，帮我看一下
页面提示系统异常，帮我排查
这个环境打不开，看看是什么问题
执行失败了，帮我判断可能是哪的问题
```

如果是 selector、断言失败这类自动化脚本问题，不使用这个技能，应转到 `AUTOMATION_FAILURE_FIX`。

## 输入

最小输入：

```text
错误现象或失败描述
```

可选输入：

```text
环境
接口状态码
response / 响应体
traceId / requestId
复现步骤
测试账号
前端包版本
后端分支
日志片段
截图或 HAR
```

## 工作流程

1. 先确认失败发生在哪一层。

   判断问题表现在：

   ```text
   页面 / API / 环境 / 数据 / 权限 / 依赖服务 / 自动化执行
   ```

2. 收集最小必要上下文。

   通常至少需要：

   ```text
   环境
   失败现象
   复现步骤
   状态码和响应体
   traceId 或 requestId
   受影响账号或数据
   ```

3. 判断失败方向。

   如果二级意图可用，优先调用 `Intent.failure_intent.classify_failure_intent()`。

   可能的失败分类：

   ```text
   ENV_ERROR
   BRANCH_VERSION_MISMATCH
   CONFIG_OR_GRAY_ERROR
   FRONTEND_REQUEST_ERROR
   BACKEND_API_ERROR
   CONTRACT_MISMATCH
   AUTH_OR_PERMISSION_ERROR
   DB_SCHEMA_OR_DATA_ERROR
   DEPENDENCY_SERVICE_ERROR
   AUTOMATION_SCRIPT_ERROR
   FLAKY_OR_CONCURRENCY_ERROR
   UNKNOWN
   ```

4. 选择下一步检查点。

   示例：

   ```text
   BACKEND_API_ERROR -> query_backend_logs_by_trace_id
   AUTH_OR_PERMISSION_ERROR -> check_auth_token_and_permission
   DB_SCHEMA_OR_DATA_ERROR -> check_database_schema_and_test_data
   ENV_ERROR -> check_environment_availability
   ```

5. 区分事实和推测。

   输出时这些部分要分开：

   ```text
   failure_summary
   known_context
   evidence
   suspected_causes
   missing_context
   next_action
   ```

6. 带置信度说明结论。

   不要把推测当成已经确认的根因。

## 工具

计划接入的工具：

```text
get_env_status(env)
get_deploy_version(service, env)
query_trace_log(trace_id)
query_test_account(account_id)
get_api_contract(api_name)
search_related_bugs(keyword)
analyze_har(file)
analyze_console_log(file)
```

如果工具不可用，要明确返回缺少哪些证据，以及建议人工检查什么。

## 输出约定

```json
{
  "failure_summary": "...",
  "known_context": {},
  "checked_items": [],
  "evidence": [],
  "suspected_causes": [
    {
      "cause": "...",
      "confidence": 0.0,
      "evidence": []
    }
  ],
  "missing_context": [],
  "next_action": "...",
  "needs_human_confirmation": true
}
```

## 质量检查

```text
有没有证据
有没有跳过环境检查
有没有跳过版本检查
有没有过早定责
有没有区分现象和根因
有没有给出下一步建议
是否需要人工确认
```

## 禁止事项

```text
不要无证据断言根因
不要输出 token、cookie、密码
不要自动修改环境配置
不要把自动化脚本问题误判为产品问题
```

## 兜底策略

如果上下文不足：

```text
返回 UNKNOWN 失败类别
列出 missing_context
只追问最小必要补充信息
```

如果模型或工具失败：

```text
不要阻断整个流程
返回已拿到的证据
标明不可用的工具或模型错误
给出人工检查建议
```
