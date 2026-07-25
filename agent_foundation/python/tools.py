"""
Tool registry — define, register, and execute tools safely.
Each tool is a plain Python function decorated with @tool.
The registry validates tool calls before execution.
"""

from __future__ import annotations
import functools
from typing import Any, Callable

_REGISTRY: dict[str, dict] = {}


def tool(name: str, description: str, schema: dict | None = None):
    """Decorator to register a function as an agent tool."""
    def decorator(fn: Callable) -> Callable:
        _REGISTRY[name] = {
            "fn": fn,
            "description": description,
            "schema": schema or {},
        }
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def list_tools() -> list[dict]:
    """Return tool names and descriptions (for prompt building)."""
    return [
        {"name": k, "description": v["description"]}
        for k, v in _REGISTRY.items()
    ]


def execute_tool(name: str, input_data: dict[str, Any]) -> Any:
    """Execute a registered tool by name. Raises ValueError if unknown."""
    if name not in _REGISTRY:
        raise ValueError(f"Unknown tool: '{name}'. Available: {list(_REGISTRY.keys())}")
    fn = _REGISTRY[name]["fn"]
    return fn(**input_data)


def restrict_tools(allowed: list[str]) -> "ToolRegistry":
    """Return a registry view restricted to allowed tool names."""
    return ToolRegistry(allowed)


class ToolRegistry:
    """A scoped view of the global tool registry for a specific agent."""

    def __init__(self, allowed: list[str]) -> None:
        self.allowed = set(allowed)

    def list(self) -> list[dict]:
        return [t for t in list_tools() if t["name"] in self.allowed]

    def execute(self, name: str, input_data: dict[str, Any]) -> Any:
        if name not in self.allowed:
            raise ValueError(f"Tool '{name}' not in allowed list for this agent")
        return execute_tool(name, input_data)


# ── Built-in foundation tools ─────────────────────────────────────────────────

@tool("escalate", "Escalate to a human when confidence is low or conditions require review")
def _escalate_tool(reason: str, action_required: str) -> dict:
    # Handled by agent_runner — this is a sentinel
    return {"action": "escalate", "reason": reason, "action_required": action_required}


@tool("complete", "Mark the current task as successfully completed")
def _complete_tool(summary: str, result: dict | None = None) -> dict:
    # Handled by agent_runner — this is a sentinel
    return {"action": "complete", "summary": summary, "result": result or {}}


@tool("remember", "Save a value to cross-run semantic memory")
def _remember_tool(key: str, value: Any, tags: list[str] | None = None) -> dict:
    # Handled by agent_runner with access to memory object
    return {"action": "remember", "key": key, "value": value, "tags": tags}


@tool("recall", "Retrieve a value from cross-run semantic memory")
def _recall_tool(key: str) -> dict:
    # Handled by agent_runner with access to memory object
    return {"action": "recall", "key": key}
