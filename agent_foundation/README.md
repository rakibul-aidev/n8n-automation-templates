# Agent Foundation

A shared foundation pattern for building production-grade autonomous business-process agents on n8n + Python.

Every agent built on this foundation gets:
- Consistent prompt structure with system/user/context separation
- Persistent memory via PostgreSQL
- Structured logging with execution trace
- Automatic retry with exponential backoff
- Human escalation handoff with clear reason
- Secret management via environment variables

## Structure

```
agent_foundation/
├── README.md
├── docker-compose.yml          # Self-hosted n8n + PostgreSQL + Redis
├── .env.example                # All required environment variables
├── foundation_workflow.json    # n8n workflow: the shared agent runner
├── python/
│   ├── agent_runner.py         # Core agent loop with tool calling
│   ├── memory.py               # PostgreSQL-backed agent memory
│   ├── tools.py                # Tool registry and executor
│   ├── prompts.py              # Prompt templates (system/user/context)
│   ├── logger.py               # Structured logging to DB + stdout
│   ├── retry.py                # Exponential backoff with dead-letter
│   └── handoff.py              # Human escalation logic
├── sql/
│   └── schema.sql              # DB tables: runs, steps, memory, handoffs
└── examples/
    └── email_triage_agent.py   # Reference agent using the foundation
```

## Quick Start

```bash
# 1. Clone and configure
cp .env.example .env
# Fill in your API keys and DB credentials

# 2. Start infrastructure
docker-compose up -d

# 3. Import workflow into n8n
# Open n8n → Import → Select foundation_workflow.json

# 4. Run the reference agent
python python/examples/email_triage_agent.py
```

## Foundation Workflow (n8n)

The `foundation_workflow.json` provides:
1. **Trigger** — webhook, schedule, or manual
2. **Context loader** — pulls agent memory from PostgreSQL
3. **LLM call** — Claude API with structured prompt
4. **Tool executor** — runs approved tools based on LLM output
5. **Decision gate** — proceed / retry / escalate
6. **Logger** — writes step result to DB
7. **Handoff** — routes to human queue if needed
8. **Memory update** — saves new context to DB

## Agent Definition Contract

Each agent built on this foundation defines:

```python
AGENT = {
    "name": "email_triage",
    "description": "Triage incoming emails: categorise, draft reply, or escalate",
    "trigger": "webhook",          # webhook | schedule | event
    "tools": ["read_email", "send_reply", "create_task", "escalate"],
    "max_retries": 3,
    "escalation_conditions": [
        "confidence < 0.7",
        "contains_legal_language",
        "sender_is_vip"
    ],
    "human_queue": "slack:#ops-review"
}
```

## Memory Model

Agents maintain three layers of memory:

| Layer | Storage | Scope | TTL |
|-------|---------|-------|-----|
| Working | In-process dict | Single run | None |
| Episodic | PostgreSQL `agent_steps` | Per agent | 90 days |
| Semantic | PostgreSQL `agent_memory` | Cross-run | Indefinite |

## Escalation Flow

When an agent cannot confidently complete a step, it:
1. Writes the escalation reason and full context to `agent_handoffs`
2. Posts a structured summary to the configured human queue (Slack / email)
3. Pauses execution and waits for human response
4. Resumes with the human's decision injected into context

Humans never receive a raw LLM dump — they receive a structured card with: what happened, what the agent tried, why it escalated, and a clear action required.
