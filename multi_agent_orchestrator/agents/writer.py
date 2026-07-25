"""
Writer agent — drafts content based on research output.
"""

from __future__ import annotations
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from shared.state import AgentState

WRITER_SYSTEM = """You are a professional content writer. You receive a task and research notes, and produce a high-quality draft.

Guidelines:
- Write clearly and concisely
- Use the research to back up claims — cite sources inline where relevant
- Match the tone and format specified in the task
- If the task specifies a word count, hit it within ±10%
- Do not invent facts — use only what is in the research notes
- Structure with appropriate headers if the content is longer than 200 words

Return ONLY the draft content — no preamble, no commentary.
"""


def writer_node(state: AgentState, model: Any) -> dict:
    """Writer agent produces a draft from research."""
    instruction = state.working_memory.get("supervisor_instruction", "Write the content.")
    review_notes = state.review_notes

    review_context = ""
    if review_notes:
        review_context = f"\n\nPrevious review feedback to address:\n{review_notes}"

    prompt = f"""Task: {state.task}

Instruction from supervisor: {instruction}

Research notes:
{state.research_output or "No research available — use your general knowledge."}
{review_context}

Write the draft now."""

    messages = [
        SystemMessage(content=WRITER_SYSTEM),
        HumanMessage(content=prompt),
    ]
    response = model.invoke(messages)
    draft = response.content

    print(f"[Writer] Draft produced — {len(draft.split())} words")
    return {"draft_output": draft, "next_agent": "supervisor"}
