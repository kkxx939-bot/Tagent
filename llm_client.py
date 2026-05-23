"""LLM 调用封装。

第一版默认调用 DeepSeek 的 deepseek-v4-flash。
这里不写业务逻辑，只负责把 messages 发给模型并返回文本。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from config import get_llm_config, require_llm_api_key


QUERY = "你好，请用一句话介绍你自己。"


def call_llm(
    messages: list[dict[str, str]],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """调用默认 LLM，并返回 assistant 的 content。"""
    config = get_llm_config()
    api_key = require_llm_api_key()

    payload = {
        "model": config["model"],
        "messages": messages,
        "temperature": temperature if temperature is not None else config["temperature"],
        "max_tokens": max_tokens if max_tokens is not None else config["max_tokens"],
    }

    response = post_chat_completion(
        base_url=str(config["base_url"]),
        api_key=api_key,
        payload=payload,
    )
    return extract_message_content(response)


def call_deepseek_v4_flash(messages: list[dict[str, str]]) -> str:
    """明确使用 deepseek-v4-flash，方便调试和演示。"""
    config = get_llm_config()
    api_key = require_llm_api_key()

    payload = {
        "model": "deepseek-v4-flash",
        "messages": messages,
        "temperature": config["temperature"],
        "max_tokens": config["max_tokens"],
    }

    response = post_chat_completion(
        base_url=str(config["base_url"]),
        api_key=api_key,
        payload=payload,
    )
    return extract_message_content(response)


def post_chat_completion(base_url: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    """请求 OpenAI-compatible chat completions 接口。"""
    url = build_chat_url(base_url)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url=url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM 请求失败: HTTP {exc.code} {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM 请求失败: {exc.reason}") from exc

    return json.loads(response_body)


def build_chat_url(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def extract_message_content(response: dict[str, Any]) -> str:
    """从模型响应中取出 assistant 文本。"""
    choices = response.get("choices") or []
    if not choices:
        raise RuntimeError(f"LLM 响应中没有 choices: {response}")

    message = choices[0].get("message") or {}
    content = message.get("content")
    if content is None:
        raise RuntimeError(f"LLM 响应中没有 content: {response}")
    return str(content)


def build_demo_messages(query: str = QUERY) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "你是 Test Agent 项目的测试用例生成助手。"},
        {"role": "user", "content": query},
    ]


def main() -> None:
    messages = build_demo_messages()
    try:
        print(call_deepseek_v4_flash(messages))
    except RuntimeError as exc:
        print(exc)


if __name__ == "__main__":
    main()
