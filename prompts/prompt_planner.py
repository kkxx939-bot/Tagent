
"""模型 Planner 提示词。"""

from __future__ import annotations

import json
from typing import Any


PLANNER_SYSTEM_PROMPT = """你是 Test Agent 的 Planner。

你的任务是把用户请求、意图识别结果和可用 action 转成可执行计划。

约束：
1. 只规划步骤，不执行步骤。
2. 只能使用 allowed_actions 里的 action，不允许创造新 action。
3. 不要调用未提供的工具。
4. 计划要尽量简洁，通常 3 到 6 步。
5. 复合任务要标记 is_composite=true，并写清 sub_tasks。
6. 如果缺少执行上下文，写入 missing_context，不要假设。
7. 只输出合法 JSON，不要输出 Markdown 或解释性段落。
8. JSON 必须使用双引号，不能使用单引号。
9. JSON 只能使用 true、false、null，不能使用 True、False、None。
10. JSON 对象和数组最后一项不能有尾逗号。
11. JSON 里不能写注释。
12. step_id 必须从 step_1 开始连续递增。
13. action 只表达通用执行动作；具体业务类型放到 inputs.artifact_type、inputs.context_type、tool_name。
14. 生成测试用例、自动化代码、排查报告等内容时，统一使用 generate_artifact。
15. 校验产物时，统一使用 validate_artifact。
16. 结束任务时，统一使用 finish。
"""


PLANNER_USER_TEMPLATE = """请生成任务计划。

用户输入：
{user_query}

意图识别结果：
{intent_result}

已选择的 skill：
{selected_skill}

可用 action：
{allowed_actions}

输出要求：
1. 只能输出一个 JSON 对象。
2. 不要用 ```json 包裹。
3. 不要在 JSON 前后输出任何说明。
4. 每个 step 的 action 必须来自 allowed_actions。
5. depends_on 只能引用前面已经出现的 step_id。
6. requires_permission 必须是 true 或 false。
7. tool_name 没有工具时必须是 null。
8. steps 至少包含 1 个步骤。
9. generate_artifact 和 validate_artifact 必须在 inputs 里写 artifact_type。
10. call_tool 必须写 tool_name。

输出 JSON 格式：
{{
  "intent": "CASE_GENERATION",
  "is_composite": false,
  "sub_tasks": [],
  "missing_context": [],
  "warnings": [],
  "steps": [
    {{
      "step_id": "step_1",
      "name": "检索相关上下文",
      "action": "load_context",
      "depends_on": [],
      "inputs": {{}},
      "requires_permission": false,
      "tool_name": null
    }}
  ]
}}

合法 JSON 示例：
{{
  "intent": "CASE_GENERATION",
  "is_composite": true,
  "sub_tasks": ["CASE_GENERATION", "AUTOMATION_WRITING"],
  "missing_context": ["自动化框架", "自动化项目路径"],
  "warnings": [],
  "steps": [
    {{
      "step_id": "step_1",
      "name": "检索需求文档和历史测试资产",
      "action": "load_context",
      "depends_on": [],
      "inputs": {{}},
      "requires_permission": false,
      "tool_name": null
    }},
    {{
      "step_id": "step_2",
      "name": "生成测试用例",
      "action": "generate_artifact",
      "depends_on": ["step_1"],
      "inputs": {{"artifact_type": "test_case"}},
      "requires_permission": false,
      "tool_name": null
    }},
    {{
      "step_id": "step_3",
      "name": "基于测试用例生成自动化代码",
      "action": "generate_artifact",
      "depends_on": ["step_2"],
      "inputs": {{"artifact_type": "automation_code"}},
      "requires_permission": false,
      "tool_name": null
    }}
  ]
}}
"""


def build_planner_prompt(context: dict[str, Any]) -> list[dict[str, str]]:
    """构造模型 Planner 消息。"""
    return [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": PLANNER_USER_TEMPLATE.format(
                user_query=str(context.get("user_query") or ""),
                intent_result=json.dumps(context.get("intent_result") or {}, ensure_ascii=False, indent=2),
                selected_skill=json.dumps(context.get("selected_skill") or {}, ensure_ascii=False, indent=2),
                allowed_actions=json.dumps(context.get("allowed_actions") or [], ensure_ascii=False, indent=2),
            ),
        },
    ]
