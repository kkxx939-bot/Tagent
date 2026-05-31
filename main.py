"""Tagent 本地运行入口。"""

from __future__ import annotations

import json
import os
import sys

from agent.orchestrator import run_agent
from observability.main_observation import record_main_run

DEFAULT_QUERY = "检索登录相关需求资料"
OPENVIKING_LOCAL_DEFAULTS = {
    "OPENVIKING_URL": "http://localhost:1933",
    "OPENVIKING_API_KEY": "tagent-local-dev-key",
    "OPENVIKING_ACCOUNT": "default",
    "OPENVIKING_USER": "tagent",
    "OPENVIKING_TARGET_URI": "viking://resources/tagent",
    "CONTEXT_BACKEND": "openviking",
}

def run_native_rag(user_query: str = DEFAULT_QUERY) -> None:
    """使用 Tagent 原生本地 RAG 执行一次 Agent 请求。"""
    os.environ["CONTEXT_BACKEND"] = "local"
    result = run_agent(user_query)
    result_dict = result.to_dict()
    record_main_run(result_dict, "native_rag")
    print(json.dumps(result_dict, ensure_ascii=False, indent=2))


def run_openviking(user_query: str = DEFAULT_QUERY) -> None:
    """使用本地 OpenViking 服务执行一次 Agent 请求。"""
    for key, value in OPENVIKING_LOCAL_DEFAULTS.items():
        if key == "CONTEXT_BACKEND":
            os.environ[key] = value
        else:
            os.environ.setdefault(key, value)
    result = run_agent(user_query)
    result_dict = result.to_dict()
    record_main_run(result_dict, "openviking")
    print(json.dumps(result_dict, ensure_ascii=False, indent=2))


def main() -> None:
    argv = sys.argv[1:]
    # run_openviking(" ".join(argv).strip() or DEFAULT_QUERY)
    run_native_rag(" ".join(argv).strip() or DEFAULT_QUERY)

if __name__ == '__main__':
    main()
