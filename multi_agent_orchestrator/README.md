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

**Research Agent** — Searches the web, reads documents, synthesises facts. Tools: web_search, read_url, extract_data.

**Writer Agent** — Drafts content based on research. Tools: write_draft, format_output, check_length.

**Reviewer Agent** — Reviews drafts for accuracy, tone, completeness. Tools: review_draft, suggest_edits, approve.

## Quick Start

```bash
pip install langgraph langchain-anthropic psycopg2-binary python-dotenv

cp .env.example .env
# Fill in your API keys

python orchestrator.py
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
