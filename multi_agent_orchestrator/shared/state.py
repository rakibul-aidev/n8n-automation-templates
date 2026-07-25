"""
Shared LangGraph state schema — passed between all agents at every step.
"""

from __future__ import annotations
from typing import Annotated, Any, Literal
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class AgentState(BaseModel):
    """Shared state object passed through the LangGraph graph."""

    # Task
    task: str = ""
    task_id: str = ""

    # Conversation / message history (append-only via add_messages)
    messages: Annotated[list, add_messages] = Field(default_factory=list)

    # Routing
    next_agent: Literal["researcher", "writer", "reviewer", "supervisor", "end"] = "supervisor"
    iteration: int = 0
    max_iterations: int = 10

    # Agent outputs
    research_output: str = ""
    draft_output: str = ""
    review_output: str = ""
    final_output: str = ""

    # Review feedback
    approved: bool = False
    review_notes: str = ""

    # Memory (loaded at start, flushed at end)
    working_memory: dict[str, Any] = Field(default_factory=dict)

    # Status
    status: Literal["running", "completed", "escalated", "failed"] = "running"
    error: str = ""
