"""Agent 对外入口。"""

from agent.orchestrator import run_agent
from agent.result import AgentResult

__all__ = ["AgentResult", "run_agent"]
