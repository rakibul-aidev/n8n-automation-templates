# Multi-Agent Orchestrator — LangGraph

A production-grade multi-agent system using LangGraph, where a supervisor agent coordinates three specialised sub-agents with shared memory, tool use, and human handoff.

## Architecture

```
User Request
     │
     ▼
┌─────────────────┐
│  Supervisor     │  ← routes tasks, monitors quality, escalates
│  Agent          │
└────────┬────────┘
         │
   ┌─────┼──────┐
   ▼     ▼      ▼
[Research] [Writer] [Reviewer]
  Agent     Agent    Agent
   │          │         │
   └──────────┴─────────┘
              │
         Shared Memory
         (PostgreSQL)
```

**Supervisor** — Receives the task, decomposes it, assigns to sub-agents, checks quality, returns final output or escalates.

**Research Agent** — Searches the web, reads documents, synthesises facts. Tools: `web_search`, `read_url`.

**Writer Agent** — Drafts content based on research. Tools: `check_word_count`, `format_markdown`.

**Reviewer Agent** — Reviews drafts for accuracy, tone, and completeness via structured JSON output (approve/reject + notes) — no separate tool calls, since the review is a single reasoning pass over the draft and research brief.

## Shared Memory (PostgreSQL)

Every supervisor decision, and every sub-agent's output, is persisted to Postgres via `shared/memory.py` — not just held in the in-process LangGraph state. That means:

- Any other process with the same `POSTGRES_*` credentials can read a task's current status or full step history (`shared.memory.get_history(task_id)`) while — or after — it runs.
- If `POSTGRES_HOST` isn't set in `.env`, the pipeline still runs fine; `memory.enabled` is `False` and all persistence calls silently no-op. Useful for quick local testing without spinning up a database.
- Schema (`sql/schema.sql`) is created automatically on first run — no manual migration step needed for a fresh database.

## Quick Start

```bash
pip install langgraph langchain-anthropic psycopg2-binary python-dotenv

cp .env.example .env
# Fill in your API keys and Postgres credentials (or leave POSTGRES_HOST blank to run without persistence)

python orchestrator.py
# or, for the full worked example with step-history readback:
python -m examples.content_pipeline
```

## Files

```
multi_agent_orchestrator/
├── README.md
├── .env.example
├── orchestrator.py          # Main entry point
├── agents/
│   ├── supervisor.py        # Routing and quality control
│   ├── researcher.py        # Research sub-agent
│   ├── writer.py            # Writing sub-agent
│   └── reviewer.py          # Review sub-agent
├── shared/
│   ├── memory.py            # Shared PostgreSQL memory
│   ├── tools.py             # Shared tool definitions
│   └── state.py             # LangGraph shared state schema
└── examples/
    └── content_pipeline.py  # End-to-end example
```
