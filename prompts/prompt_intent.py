"""主意图识别的提示词模板。"""

from __future__ import annotations

import json
from typing import Any


MAIN_INTENT_OPTIONS = {
    "CASE_GENERATION": "生成测试用例、测试点、测试场景",
    "AUTOMATION_WRITING": "编写 Playwright/Selenium/Appium/Pytest/Cypress 等自动化测试代码",
    "EXECUTION_ASSISTANT": "辅助执行测试、跑用例、整理执行结果",
    "FAILURE_TRIAGE": "对业务功能、接口、页面、环境失败做初步排查",
    "AUTOMATION_FAILURE_FIX": "修复自动化脚本失败、定位不到元素、断言失败、等待超时等问题",
    "BUG_REPORT_GENERATION": "根据失败现象、证据、复现步骤生成 Bug/缺陷报告",
    "REGRESSION_ANALYSIS": "分析需求、代码、缺陷修复对回归范围和用例的影响",
    "CONFIG_HELP": "解释或处理模型、API Key、环境变量、base_url 等项目配置问题",
    "CONTEXT_SEARCH": "检索需求、历史用例、历史 Bug、接口文档、chunk、RAG 上下文",
    "RESULT_REVIEW": "查看、解释、评审已生成结果或输出文件",
    "PROJECT_QA": "回答项目流程、架构设计、下一步规划、实现逻辑等问题",
    "UNKNOWN": "无法判断用户主意图，需要追问澄清",
}


MAIN_INTENT_FALLBACK_SYSTEM_PROMPT = """你是 Test Agent 的主意图识别器。

你的任务：
1. 判断用户输入的主意图，并输出结构化 JSON。
2. 只能从给定 intent 枚举中选择一个，不允许创造新 intent。
3. 如果用户同时表达多个任务，选择最主要、最应该先执行的主意图，并把其他可能意图放入 alternative_intents。
4. 如果无法可靠判断，必须返回 UNKNOWN。
5. 只输出合法 JSON，不要输出 Markdown，不要输出解释性段落。
"""


MAIN_INTENT_FALLBACK_USER_TEMPLATE = """请识别用户输入的主意图。

可选 intent：
{intent_options}

用户输入：
{user_input}

规则路由结果（可选，仅供参考，可能为空）：
{rule_result}

规则候选（可选，仅供参考，可能为空）：
{rule_candidates}

判断要求：
1. 优先尊重用户显式动词，例如“生成用例”“写自动化”“修复脚本”“生成 Bug 报告”“分析回归影响”。
2. 不要因为出现“失败、报错、500、超时”就一定判断为 FAILURE_TRIAGE；如果用户明确要求写用例，应判断为 CASE_GENERATION。
3. 不要因为出现 Playwright/Selenium 就一定判断为 AUTOMATION_WRITING；如果用户说脚本失败、断言失败、定位不到，应判断为 AUTOMATION_FAILURE_FIX。
4. confidence 使用 0 到 1 之间的小数：
   - 0.80 以上：用户意图明确
   - 0.55 到 0.79：可以判断但有歧义
   - 0.55 以下：应返回 UNKNOWN 或低置信结果
5. evidence 必须引用用户输入中的具体词语或短语。

只输出如下 JSON 格式：
{{
  "intent": "CASE_GENERATION",
  "confidence": 0.82,
  "evidence": ["用户提到：生成测试用例"],
  "alternative_intents": [
    {{
      "intent": "AUTOMATION_WRITING",
      "confidence": 0.41,
      "reason": "用户也提到 Playwright"
    }}
  ],
  "reason": "用户主要是在请求生成测试用例"
}}
"""


def build_main_intent_prompt(context: dict[str, Any]) -> list[dict[str, str]]:
    """构造主意图识别需要的消息列表。"""
    user_input = str(context.get("user_input") or "")
    rule_result = format_json_block(context.get("rule_result") or {})
    rule_candidates = format_json_block(context.get("rule_candidates") or [])

    user_prompt = MAIN_INTENT_FALLBACK_USER_TEMPLATE.format(
        intent_options=format_intent_options(MAIN_INTENT_OPTIONS),
        user_input=user_input,
        rule_result=rule_result,
        rule_candidates=rule_candidates,
    )
    return [
        {"role": "system", "content": MAIN_INTENT_FALLBACK_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def build_main_intent_prompt_text(context: dict[str, Any]) -> str:
    messages = build_main_intent_prompt(context)
    return "\n\n".join(f"[{message['role']}]\n{message['content']}" for message in messages)


def format_intent_options(intent_options: dict[str, str]) -> str:
    return "\n".join(f"- {intent}: {description}" for intent, description in intent_options.items())


def format_json_block(value: Any) -> str:
    if value in (None, "", [], {}):
        return "无"
    return json.dumps(value, ensure_ascii=False, indent=2)
