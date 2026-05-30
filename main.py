"""Tagent 本地运行入口。"""

from __future__ import annotations

import json
import sys

from agent.orchestrator import run_agent


DEFAULT_QUERY = ("根据我桌面的文档：song_new.pdf，生成case")

# TODO 工业化能力补齐
# 1. 数据接入
#    - 支持需求文档、接口文档、历史用例、Bug 清单、日志、测试报告的统一接入。
# 2. 自动化执行体系
#    自动化能力的搭建
# 3. 可观测性
#    token用了多少，清洗的数据的质量等等，都需要
# 4. 评测体系
#    需要把其他的评测也可以接上

def main() -> None:
    user_query = " ".join(sys.argv[1:]).strip() or DEFAULT_QUERY
    result = run_agent(user_query)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
