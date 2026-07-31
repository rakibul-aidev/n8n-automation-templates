"""
Multi-Agent Orchestrator — LangGraph entry point.

Builds the agent graph and exposes a simple run() interface.
"""

from __future__ import annotations
import uuid
from typing import Any

from dotenv import load_dotenv
load_dotenv()

from langchain_anthropic import ChatAnthropic
from langgraph.graph import StateGraph, END

from shared.state import AgentState
from shared import memory
from agents.supervisor import supervisor_node, route_from_supervisor
from agents.researcher import researcher_node
from agents.writer import writer_node
from agents.reviewer import reviewer_node, route_from_reviewer


def build_graph() -> Any:
    """Construct and compile the multi-agent LangGraph."""
    model = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0)

    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("supervisor", lambda state: supervisor_node(state, model))
    graph.add_node("researcher", lambda state: researcher_node(state, model))
    graph.add_node("writer",     lambda state: writer_node(state, model))
    graph.add_node("reviewer",   lambda state: reviewer_node(state, model))

    # Entry point
    graph.set_entry_point("supervisor")

    # Supervisor routes to sub-agents
    graph.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "researcher": "researcher",
            "writer":     "writer",
            "reviewer":   "reviewer",
            "end":        END,
        },
    )

    # Sub-agents all return to supervisor
    graph.add_edge("researcher", "supervisor")
    graph.add_edge("writer",     "supervisor")

    # Reviewer can approve (→ END) or send back (→ writer)
    graph.add_conditional_edges(
        "reviewer",
        route_from_reviewer,
        {
            "writer":     "writer",
            "supervisor": "supervisor",
            "end":        END,
        },
    )

    return graph.compile()


def run(task: str, max_iterations: int = 10) -> dict[str, Any]:
    """Run the multi-agent pipeline for a given task."""
    app = build_graph()

    task_id = str(uuid.uuid4())
    initial_state = AgentState(
        task=task,
        task_id=task_id,
        max_iterations=max_iterations,
    )

    print(f"\n{'='*60}")
    print(f"Task: {task}")
    print(f"Task ID: {task_id}")
    if memory.enabled:
        print("Shared memory: PostgreSQL (persisting every step)")
    else:
        print("Shared memory: disabled (set POSTGRES_HOST in .env to enable)")
    print(f"{'='*60}\n")

    if memory.enabled:
        memory.init_schema()
        memory.save_state(task_id, initial_state.model_dump(), status="running")

    final_state = app.invoke(initial_state)

    if memory.enabled:
        memory.save_state(task_id, dict(final_state), status=final_state["status"])

    print(f"\n{'='*60}")
    print(f"Status: {final_state['status']}")
    print(f"Iterations: {final_state['iteration']}")
    if final_state.get("final_output"):
        print(f"\nFinal Output:\n{final_state['final_output']}")
    if memory.enabled:
        print(f"\nFull step history persisted under task_id={task_id}")
        print("Retrieve it any time with: shared.memory.get_history(task_id)")
    print(f"{'='*60}\n")

    return {
        "status":       final_state["status"],
        "task_id":      final_state["task_id"],
        "final_output": final_state.get("final_output", ""),
        "iterations":   final_state["iteration"],
    }


if __name__ == "__main__":
    result = run(
        task="Research the top 3 benefits of n8n over Zapier for enterprise automation, "
             "then write a 300-word blog section on the topic.",
    )
