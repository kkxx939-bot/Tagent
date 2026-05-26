"""Tagent 本地运行入口。"""

from __future__ import annotations

import json
import sys

from agent.orchestrator import run_agent


DEFAULT_QUERY = ("根据我桌面的文档：song_new.pdf，生成case")


def main() -> None:
    user_query = " ".join(sys.argv[1:]).strip() or DEFAULT_QUERY
    result = run_agent(user_query)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
