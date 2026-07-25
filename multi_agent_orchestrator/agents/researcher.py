"""
Research agent — gathers facts using web search and URL reading.
"""

from __future__ import annotations
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from shared.state import AgentState
from shared.tools import RESEARCHER_TOOLS

RESEARCHER_SYSTEM = """You are a research specialist. Your job is to gather accurate, relevant information to support a writing task.

Available tools:
- web_search(query, max_results): search the web
- read_url(url): read the full text of a URL

Research process:
1. Identify 2-3 key search queries from the task
2. Search for each and read the most relevant results
3. Synthesise findings into a structured research summary

Return your research as a well-structured summary with:
- Key facts and data points
- Source URLs
- Any important caveats or conflicting information

Do NOT write the final content — only gather and summarise facts.
"""


def researcher_node(state: AgentState, model: Any) -> dict:
    """Research agent gathers information for the task."""
    instruction = state.working_memory.get("supervisor_instruction", state.task)

    # Bind tools to model
    model_with_tools = model.bind_tools(RESEARCHER_TOOLS)

    messages = [
        SystemMessage(content=RESEARCHER_SYSTEM),
        HumanMessage(content=f"Research task: {instruction}\n\nOriginal task: {state.task}"),
    ]

    # Agentic tool loop
    tool_map = {t.name: t for t in RESEARCHER_TOOLS}
    research_log = []

    for _ in range(5):  # max 5 tool calls
        response = model_with_tools.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        for tc in response.tool_calls:
            tool: BaseTool = tool_map.get(tc["name"])
            if tool:
                result = tool.invoke(tc["args"])
                research_log.append(f"[{tc['name']}({tc['args']})]\n{result[:1000]}")
                from langchain_core.messages import ToolMessage
                messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))

    research_output = response.content
    print(f"[Researcher] Completed — {len(research_log)} tool calls, {len(research_output)} chars")

    return {"research_output": research_output, "next_agent": "supervisor"}
