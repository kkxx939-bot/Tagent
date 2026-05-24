"""失败排查二级意图识别的提示词模板。"""

from __future__ import annotations

import json
from typing import Any


FAILURE_INTENT_OPTIONS = {
    "ENV_ERROR": "环境不可用、域名/DNS/网关/服务状态异常",
    "BRANCH_VERSION_MISMATCH": "前端包、后端分支、版本、commit 或部署不匹配",
    "CONFIG_OR_GRAY_ERROR": "配置、开关、灰度、白名单、黑名单导致的问题",
    "FRONTEND_REQUEST_ERROR": "前端请求未发出、Network/Console/CORS/XHR/fetch 异常",
    "BACKEND_API_ERROR": "后端接口状态码、响应体、traceId/requestId、服务端异常",
    "CONTRACT_MISMATCH": "前后端协议、字段、入参、出参、schema、枚举不一致",
    "AUTH_OR_PERMISSION_ERROR": "登录态、token、cookie、鉴权、权限、401/403、越权问题",
    "DB_SCHEMA_OR_DATA_ERROR": "数据库表结构、字段、测试数据、账号状态、数据状态问题",
    "DEPENDENCY_SERVICE_ERROR": "下游、三方、RPC、MQ、Redis、缓存等依赖服务异常",
    "AUTOMATION_SCRIPT_ERROR": "自动化脚本自身问题，而不是被测业务功能问题",
    "FLAKY_OR_CONCURRENCY_ERROR": "偶现、并发、时序、重试后通过、不稳定问题",
    "UNKNOWN": "无法判断具体失败类别，需要补充信息",
}


FAILURE_INTENT_SYSTEM_PROMPT = """你是 Test Agent 的失败排查二级意图识别器。

你的任务：
1. 用户主意图已经确定为 FAILURE_TRIAGE。
2. 你只需要判断失败更像哪一类问题。
3. 只能从给定 failure intent 枚举中选择一个 primary_category，不允许创造新类别。
4. 如果可能存在多个类别，把次要类别放入 secondary_categories。
5. 如果证据不足，primary_category 必须返回 UNKNOWN。
6. 只输出合法 JSON，不要输出 Markdown，不要输出解释性段落。
"""


FAILURE_INTENT_USER_TEMPLATE = """请识别失败排查的二级意图。

可选 failure intent：
{failure_intent_options}

用户输入：
{user_input}

已知上下文：
{known_context}

判断要求：
1. 如果出现 500、502、503、504、traceId、requestId、response、响应体，优先考虑 BACKEND_API_ERROR。
2. 如果出现 401、403、token、cookie、登录态、无权限、越权，优先考虑 AUTH_OR_PERMISSION_ERROR。
3. 如果出现 Network、Console、CORS、请求没发出、XHR、fetch，优先考虑 FRONTEND_REQUEST_ERROR。
4. 如果出现字段不一致、传参不一致、schema、入参、出参、枚举，优先考虑 CONTRACT_MISMATCH。
5. 如果出现数据库、SQL、表结构、测试数据、账号状态、数据状态，优先考虑 DB_SCHEMA_OR_DATA_ERROR。
6. 如果出现分支、版本、部署、前端包、后端分支、commit，优先考虑 BRANCH_VERSION_MISMATCH。
7. 如果出现配置、开关、灰度、白名单、黑名单，优先考虑 CONFIG_OR_GRAY_ERROR。
8. 如果出现下游、三方、RPC、MQ、Redis、缓存，优先考虑 DEPENDENCY_SERVICE_ERROR。
9. 如果出现偶现、偶发、时好时坏、并发、时序、重试通过，优先考虑 FLAKY_OR_CONCURRENCY_ERROR。
10. 如果证据只表明“失败了”，但无法判断类别，返回 UNKNOWN。

只输出如下 JSON 格式：
{{
  "primary_category": "BACKEND_API_ERROR",
  "secondary_categories": ["DB_SCHEMA_OR_DATA_ERROR"],
  "confidence": 0.82,
  "evidence": ["用户提到：登录接口返回 500", "用户提供了 traceId"],
  "missing_context": ["环境", "response/响应体", "复现步骤"],
  "next_action": "query_backend_logs_by_trace_id",
  "reason": "状态码和 traceId 指向后端接口错误"
}}
"""


def build_failure_intent_prompt(context: dict[str, Any]) -> list[dict[str, str]]:
    """构造失败排查二级意图识别需要的消息列表。"""
    user_input = str(context.get("user_input") or "")
    known_context = format_json_block(context.get("known_context") or {})

    user_prompt = FAILURE_INTENT_USER_TEMPLATE.format(
        failure_intent_options=format_failure_intent_options(FAILURE_INTENT_OPTIONS),
        user_input=user_input,
        known_context=known_context,
    )
    return [
        {"role": "system", "content": FAILURE_INTENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def build_failure_intent_prompt_text(context: dict[str, Any]) -> str:
    messages = build_failure_intent_prompt(context)
    return "\n\n".join(f"[{message['role']}]\n{message['content']}" for message in messages)


def format_failure_intent_options(intent_options: dict[str, str]) -> str:
    return "\n".join(f"- {intent}: {description}" for intent, description in intent_options.items())


def format_json_block(value: Any) -> str:
    if value in (None, "", [], {}):
        return "无"
    return json.dumps(value, ensure_ascii=False, indent=2)
