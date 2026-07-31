"""
Reviewer agent — checks draft quality and either approves or sends back with notes.
"""

from __future__ import annotations
from typing import Any, Literal
import json, re

from langchain_core.messages import HumanMessage, SystemMessage

from shared.state import AgentState
from shared import memory

REVIEWER_SYSTEM = """You are a quality reviewer. Given a task brief and a draft, assess whether the draft meets the requirements.

Evaluate on:
1. Accuracy — does it match the research? Are there any unsupported claims?
2. Completeness — does it address everything in the task?
3. Quality — is the writing clear, well-structured, and on-tone?
4. Length — is it within the specified word count (±10%)?

Respond in JSON:
{
  "approved": true|false,
  "score": 1-10,
  "notes": "specific feedback if not approved, else 'Approved'",
  "final_output": "the approved draft text if approved, else null"
}

Be strict — only approve if the draft genuinely meets all requirements.
If approving, copy the full draft into final_output unchanged.
"""


def reviewer_node(state: AgentState, model: Any) -> dict:
    """Reviewer checks the draft and approves or sends back."""
    prompt = f"""Task: {state.task}

Draft to review:
{state.draft_output}

Research used:
{state.research_output[:2000] if state.research_output else "None"}

Review the draft now."""

    messages = [
        SystemMessage(content=REVIEWER_SYSTEM),
        HumanMessage(content=prompt),
    ]
    response = model.invoke(messages)
    raw = response.content

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        data = json.loads(m.group()) if m else {"approved": False, "notes": "Review parse failed"}

    approved = data.get("approved", False)
    notes    = data.get("notes", "")
    score    = data.get("score", 0)

    print(f"[Reviewer] Score: {score}/10 | Approved: {approved} | Notes: {notes[:80]}")
    memory.log_agent_step(state.task_id, "reviewer", raw)

    update: dict = {
        "approved":      approved,
        "review_output": raw,
        "review_notes":  notes,
        "next_agent":    "supervisor",
    }
    if approved and data.get("final_output"):
        update["final_output"] = data["final_output"]
        update["status"]       = "completed"

    return update


def route_from_reviewer(state: AgentState) -> Literal["writer", "supervisor", "end"]:
    if state.approved:
        return "end"
    if state.iteration >= state.max_iterations:
        return "end"
    return "writer"  # Send back for revision
