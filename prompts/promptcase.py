"""测试用例生成的提示词模板。"""

from __future__ import annotations

from typing import Any


CASE_GENERATION_SYSTEM_PROMPT = """你是一名资深测试工程师，负责根据需求、历史用例、历史 Bug 和接口资料生成高质量测试用例。

你必须遵守以下原则：
1. 只基于提供的上下文生成，不要编造上下文中没有的业务规则。
2. 优先覆盖需求中的核心流程、字段规则、状态流转和验收标准。
3. 结合历史用例，避免重复低价值用例，补充缺失场景。
4. 结合历史 Bug，补充回归测试和高风险异常场景。
5. 结合接口资料，补充参数校验、错误码、鉴权、幂等和边界场景。
6. 每条用例必须可执行，步骤和预期结果要清楚。
"""


CASE_GENERATION_USER_TEMPLATE = """请根据以下检索上下文，为用户问题生成测试用例。

用户问题：
{query}

需求上下文：
{requirements}

历史用例上下文：
{cases}

历史 Bug 上下文：
{bugs}

接口上下文：
{apis}

生成要求：
1. 输出 8 到 15 条测试用例。
2. 至少包含正常流、异常流、边界值、权限/鉴权、历史 Bug 回归这几类场景。
3. 如果上下文不足以支持某类场景，在 case_basis 中说明“上下文不足，仅给出通用测试方向”。
4. 不要输出解释性段落，只输出 JSON。
5. JSON 字符串内不要使用未转义的英文双引号。

输出 JSON 格式：
{{
  "cases": [
    {{
      "case_id": "TC-001",
      "module": "模块名称",
      "title": "用例标题",
      "priority": "P0/P1/P2",
      "case_type": "正常流/异常流/边界值/权限/接口/历史Bug回归",
      "precondition": "前置条件",
      "steps": [
        "步骤1",
        "步骤2"
      ],
      "expected_result": "预期结果",
      "case_basis": "引用的需求/历史用例/Bug/API依据",
      "source_chunk_ids": ["chunk_id_1", "chunk_id_2"]
    }}
  ]
}}
"""


def build_case_generation_prompt(context: dict[str, Any]) -> list[dict[str, str]]:
    query = context.get("query") or ""
    requirements = context.get("requirements") or "无"
    cases = context.get("cases") or "无"
    bugs = context.get("bugs") or "无"
    apis = context.get("apis") or "无"

    user_prompt = CASE_GENERATION_USER_TEMPLATE.format(
        query=query,
        requirements=requirements,
        cases=cases,
        bugs=bugs,
        apis=apis,
    )
    return [
        {"role": "system", "content": CASE_GENERATION_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def build_case_generation_prompt_text(context: dict[str, Any]) -> str:
    messages = build_case_generation_prompt(context)
    return "\n\n".join(f"[{message['role']}]\n{message['content']}" for message in messages)
