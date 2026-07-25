"""
Prompt templates — structured system/user/context separation.
All agents use this module so prompts are consistent and auditable.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


FOUNDATION_SYSTEM = """You are an autonomous business-process agent. Your job is to complete the assigned process accurately and reliably.

Rules:
1. Only take actions that are explicitly in your allowed tools list.
2. If you are not confident (confidence < 0.7), escalate to a human rather than guessing.
3. Always check your working memory before making external API calls — avoid duplicate actions.
4. Log your reasoning before each action.
5. Never fabricate data. If information is missing, say so and escalate if needed.
6. When you complete a step, summarise what you did in one sentence for the audit log.

Respond in this JSON format:
{
  "reasoning": "...",
  "action": "tool_name | escalate | complete",
  "tool_input": {...},          // if action is a tool
  "escalation_reason": "...",   // if action is escalate
  "confidence": 0.0-1.0,
  "summary": "..."              // one-sentence audit summary
}"""


@dataclass
class PromptBuilder:
    agent_name: str
    agent_description: str
    tools: list[str] = field(default_factory=list)
    escalation_conditions: list[str] = field(default_factory=list)

    def system_prompt(self) -> str:
        tool_list = "\n".join(f"  - {t}" for t in self.tools) if self.tools else "  (none)"
        esc_list  = "\n".join(f"  - {c}" for c in self.escalation_conditions) if self.escalation_conditions else "  (use judgment)"
        return f"""{FOUNDATION_SYSTEM}

Agent: {self.agent_name}
Purpose: {self.agent_description}

Allowed tools:
{tool_list}

Escalate if any of these conditions apply:
{esc_list}"""

    def user_prompt(
        self,
        trigger_data: dict[str, Any],
        working_memory: dict[str, Any],
        semantic_memory: dict[str, Any],
        step_history: list[dict[str, Any]],
        current_step: int,
    ) -> str:
        history_text = ""
        if step_history:
            history_text = "\n\nStep history (most recent last):\n"
            for s in step_history[-5:]:  # last 5 steps only
                history_text += f"  Step {s['step_number']} [{s['step_type']}]: {s.get('output', {})}\n"

        return f"""Trigger data (what started this run):
{_fmt(trigger_data)}

Working memory (this run):
{_fmt(working_memory)}

Semantic memory (cross-run context):
{_fmt(semantic_memory)}
{history_text}
Current step: {current_step}
What should you do next?"""

    def tool_result_prompt(self, tool_name: str, result: Any, step: int) -> str:
        return f"""Step {step} result — tool '{tool_name}' returned:
{_fmt(result)}

What should you do next?"""


def _fmt(data: Any) -> str:
    import json
    try:
        return json.dumps(data, indent=2, default=str)[:2000]
    except Exception:
        return str(data)[:2000]
