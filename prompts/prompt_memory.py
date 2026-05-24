"""长期记忆提取提示词。"""

from __future__ import annotations

import json
from typing import Any


MEMORY_PROCESS_SYSTEM_PROMPT = """你是 Test Agent 的长期记忆处理器。

你的任务：
1. 从一次任务摘要中判断哪些信息值得进入长期记忆。
2. 只提取跨任务可复用的信息，不保存临时过程。
3. 不要保存 token、cookie、password、api key、authorization、完整日志、完整响应体。
4. 未确认的根因只能作为任务摘要，不能写成稳定经验。
5. 只输出合法 JSON，不要输出 Markdown，不要输出解释性段落。
"""


MEMORY_PROCESS_USER_TEMPLATE = """请处理下面这次任务摘要，判断是否需要形成长期记忆。

任务摘要：
{session_summary}

允许的 action：
- save_task_summary：保存任务摘要。
- save_user_preference：保存用户偏好，例如输出语言、代码风格、用例生成偏好。
- save_feedback：保存用户反馈，例如“这类结果太泛，下次要更具体”。
- skip：不保存。

输出要求：
1. candidates 必须是列表。
2. 每个 candidate 只能使用允许的 action。
3. confidence 使用 0 到 1 之间的小数。
4. reason 写清为什么值得保存或为什么跳过。
5. 如果没有可保存内容，返回空 candidates。
6. 不要输出 save_project_profile；项目默认配置只能由显式配置流程保存。
7. generated_outputs 里的路径只能作为 task_summary 的一部分，不要自动提取成项目默认配置。

只输出如下 JSON：
{{
  "candidates": [
    {{
      "action": "save_task_summary",
      "memory_type": "task_summary",
      "scope": "task",
      "content": {{}},
      "confidence": 0.85,
      "tags": ["CASE_GENERATION"],
      "reason": "任务结果后续可能被查询"
    }}
  ]
}}
"""


def build_memory_process_prompt(session_summary: dict[str, Any]) -> list[dict[str, str]]:
    """构造长期记忆提取提示词。"""
    return [
        {"role": "system", "content": MEMORY_PROCESS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": MEMORY_PROCESS_USER_TEMPLATE.format(
                session_summary=json.dumps(session_summary, ensure_ascii=False, indent=2)
            ),
        },
    ]
