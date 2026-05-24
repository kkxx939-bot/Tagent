"""加载外部工具配置。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "tools" / "config" / "tools.local.json"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "tools" / "config" / "tools.example.json"


def load_tool_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """读取本地工具配置；配置不存在时返回空字典。"""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def get_nested(config: dict[str, Any], path: list[str]) -> Any:
    current: Any = config
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current
