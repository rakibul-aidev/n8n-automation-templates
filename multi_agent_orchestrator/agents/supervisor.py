"""
Supervisor agent — routes tasks, monitors progress, controls quality.
"""

from __future__ import annotations
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage

from shared.state import AgentState
from shared import memory

SUPERVISOR_SYSTEM = """You are a supervisor coordinating a team of agents to complete a task.

Your team:
- researcher: searches the web and reads URLs to gather facts and data
- writer: drafts content based on the research
- reviewer: reviews drafts for quality, accuracy, and completeness

Given the current state of the task, decide what to do next.

Respond in JSON:
{
  "reasoning": "what has been done so far and what needs to happen next",
  "next_agent": "researcher|writer|reviewer|end",
  "instruction": "specific instruction for the next agent",
  "status": "running|completed|failed"
}

Rules:
- Always start with researcher if no research has been done
- Send to writer after research is complete
- Send to reviewer after a draft exists
- Only send to "end" when the reviewer has approved the output
- If max_iterations is reached, set status to "failed" and next_agent to "end"
"""


def supervisor_node(state: AgentState, model: Any) -> dict:
    """Supervisor decides what to do next."""
    import json, re

    if state.iteration >= state.max_iterations:
        return {"status": "failed", "next_agent": "end", "error": "Max iterations reached"}

    context = f"""Task: {state.task}

Research done: {"Yes" if state.research_output else "No"}
Draft exists: {"Yes" if state.draft_output else "No"}
Review done: {"Yes" if state.review_output else "No"}
Approved: {state.approved}
Review notes: {state.review_notes or "None"}
Iteration: {state.iteration + 1}/{state.max_iterations}"""

    messages = [
        SystemMessage(content=SUPERVISOR_SYSTEM),
        HumanMessage(content=context),
    ]
    response = model.invoke(messages)
    raw = response.content

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        data = json.loads(m.group()) if m else {"next_agent": "end", "status": "failed"}

    print(f"[Supervisor] → {data.get('next_agent')} | {data.get('reasoning', '')[:80]}")

    new_working_memory = {
        **state.working_memory,
        "supervisor_instruction": data.get("instruction", ""),
    }

    # Persist the routing decision to the shared Postgres memory table so any
    # other process (a dashboard, a retry job, another worker) can see where
    # this task stands without holding the LangGraph state in memory.
    memory.save_state(
        state.task_id,
        {**state.model_dump(), "working_memory": new_working_memory, "next_agent": data.get("next_agent", "end")},
        status=data.get("status", "running"),
    )
    memory.log_agent_step(state.task_id, "supervisor", raw)

    return {
        "next_agent":  data.get("next_agent", "end"),
        "iteration":   state.iteration + 1,
        "status":      data.get("status", "running"),
        "working_memory": new_working_memory,
    }


def route_from_supervisor(state: AgentState) -> Literal["researcher", "writer", "reviewer", "end"]:
    return state.next_agent  # type: ignore
