"""
Agent Runner — core agentic loop.

Usage:
    from agent_runner import AgentRunner, AgentConfig

    config = AgentConfig(
        name="email_triage",
        description="Triage incoming emails: categorise, draft reply, or escalate",
        tools=["read_email", "send_reply", "create_task"],
        escalation_conditions=["confidence < 0.7", "sender_is_vip"],
        human_queue="slack:#ops-review",
        max_steps=10,
    )
    runner = AgentRunner(config)
    result = runner.run(trigger_data={"email_id": "abc123"})
"""

from __future__ import annotations
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import anthropic
import psycopg2
import psycopg2.extras

from logger import AgentLogger, get_logger
from memory import AgentMemory
from prompts import PromptBuilder
from retry import with_retry
from tools import ToolRegistry
import handoff as handoff_module

log = get_logger(__name__)


@dataclass
class AgentConfig:
    name: str
    description: str
    tools: list[str] = field(default_factory=list)
    escalation_conditions: list[str] = field(default_factory=list)
    human_queue: str = "slack:#ops-review"
    max_steps: int = 20
    model: str = "claude-opus-4-8"
    max_tokens: int = 1024


def _db_conn():
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


class AgentRunner:
    """Executes an agent with full logging, memory, retry, and handoff support."""

    def __init__(self, config: AgentConfig, tool_registry: ToolRegistry | None = None) -> None:
        self.config = config
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.prompts = PromptBuilder(
            agent_name=config.name,
            agent_description=config.description,
            tools=config.tools + ["escalate", "complete", "remember", "recall"],
            escalation_conditions=config.escalation_conditions,
        )
        self.tool_registry = tool_registry or ToolRegistry(
            config.tools + ["escalate", "complete", "remember", "recall"]
        )

    def run(self, trigger_data: dict[str, Any], trigger_type: str = "manual") -> dict[str, Any]:
        run_id = str(uuid.uuid4())
        memory = AgentMemory(self.config.name)
        logger = AgentLogger(run_id, self.config.name)

        log.info(f"Starting run {run_id} for agent '{self.config.name}'")
        self._create_run(run_id, trigger_type, trigger_data)

        messages: list[dict] = []
        system = self.prompts.system_prompt()
        step = 0
        total_tokens = 0

        # Load semantic memory snapshot
        semantic_ctx = {}
        for key in ["last_run_summary", "known_entities", "preferences"]:
            val = memory.semantic.get(key)
            if val:
                semantic_ctx[key] = val

        try:
            while step < self.config.max_steps:
                step += 1

                # Build user prompt
                if step == 1:
                    user_content = self.prompts.user_prompt(
                        trigger_data=trigger_data,
                        working_memory=memory.working.all(),
                        semantic_memory=semantic_ctx,
                        step_history=[],
                        current_step=step,
                    )
                else:
                    user_content = self.prompts.tool_result_prompt(
                        tool_name=last_tool,
                        result=last_result,
                        step=step,
                    )

                messages.append({"role": "user", "content": user_content})

                # LLM call with retry
                with logger.time_step("llm_call", {"step": step, "model": self.config.model}) as s:
                    response = with_retry(
                        self._llm_call,
                        system=system,
                        messages=messages,
                        run_id=run_id,
                        agent_name=self.config.name,
                    )
                    total_tokens += response.usage.input_tokens + response.usage.output_tokens
                    raw_text = response.content[0].text
                    s.set_output({"raw": raw_text[:500]}, tokens=total_tokens)

                # Parse response
                try:
                    parsed = json.loads(raw_text)
                except json.JSONDecodeError:
                    # Try to extract JSON from mixed text
                    import re
                    m = re.search(r'\{.*\}', raw_text, re.DOTALL)
                    parsed = json.loads(m.group()) if m else {"action": "escalate", "escalation_reason": "Unparseable LLM response", "confidence": 0}

                messages.append({"role": "assistant", "content": raw_text})
                action = parsed.get("action", "escalate")
                confidence = float(parsed.get("confidence", 1.0))

                logger.log_step(
                    "decision",
                    {"action": action, "confidence": confidence, "reasoning": parsed.get("reasoning", "")[:500]},
                )

                # ── Handle actions ────────────────────────────────────────────
                if action == "complete":
                    summary = parsed.get("summary", "Agent completed task")
                    memory.semantic.set("last_run_summary", summary)
                    self._finish_run(run_id, "completed", total_tokens, step)
                    log.info(f"Run {run_id} completed: {summary}")
                    return {"status": "completed", "run_id": run_id, "summary": summary, "steps": step}

                elif action == "escalate" or confidence < 0.7:
                    reason = parsed.get("escalation_reason", f"Low confidence: {confidence:.2f}")
                    action_req = parsed.get("action_required", "Please review and provide guidance")
                    ctx = {
                        "trigger_data": trigger_data,
                        "working_memory": memory.working.all(),
                        "step": step,
                        "reasoning": parsed.get("reasoning", ""),
                    }
                    with logger.time_step("handoff", {"reason": reason}):
                        handoff_id = handoff_module.escalate(
                            run_id=run_id,
                            agent_name=self.config.name,
                            reason=reason,
                            context=ctx,
                            action_required=action_req,
                            route=self.config.human_queue,
                        )

                    # Wait for human response
                    human_resp = handoff_module.get_response(handoff_id)
                    if human_resp:
                        memory.working.set("human_response", human_resp)
                        last_tool = "human_handoff"
                        last_result = human_resp
                        log.info(f"Human responded to handoff {handoff_id}")
                        continue
                    else:
                        self._finish_run(run_id, "escalated", total_tokens, step)
                        return {"status": "escalated", "run_id": run_id, "handoff_id": handoff_id}

                elif action == "remember":
                    inp = parsed.get("tool_input", {})
                    memory.semantic.set(inp.get("key", ""), inp.get("value"), inp.get("tags"))
                    last_tool = "remember"
                    last_result = {"ok": True}

                elif action == "recall":
                    key = parsed.get("tool_input", {}).get("key", "")
                    val = memory.semantic.get(key)
                    memory.working.set(f"recalled_{key}", val)
                    last_tool = "recall"
                    last_result = {key: val}

                else:
                    # Execute external tool
                    tool_input = parsed.get("tool_input", {})
                    with logger.time_step("tool_call", {"tool": action, "input": tool_input}) as s:
                        result = with_retry(
                            self.tool_registry.execute,
                            action,
                            tool_input,
                            run_id=run_id,
                            agent_name=self.config.name,
                        )
                        s.set_output(result)
                    last_tool = action
                    last_result = result

            # Max steps reached
            self._finish_run(run_id, "failed", total_tokens, step, "Max steps reached")
            return {"status": "failed", "run_id": run_id, "error": "Max steps reached"}

        except Exception as e:
            log.exception(f"Run {run_id} failed with exception")
            self._finish_run(run_id, "failed", total_tokens, step, str(e))
            raise

    def _llm_call(self, system: str, messages: list[dict], **_) -> Any:
        return self.client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=system,
            messages=messages,
        )

    def _create_run(self, run_id: str, trigger_type: str, trigger_data: dict) -> None:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO agent_runs (id, agent_name, trigger_type, trigger_data) VALUES (%s, %s, %s, %s)",
                    (run_id, self.config.name, trigger_type, json.dumps(trigger_data)),
                )

    def _finish_run(self, run_id: str, status: str, tokens: int, steps: int, error: str | None = None) -> None:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE agent_runs
                       SET status = %s, finished_at = NOW(), total_tokens = %s, total_steps = %s, error = %s
                       WHERE id = %s""",
                    (status, tokens, steps, error, run_id),
                )
