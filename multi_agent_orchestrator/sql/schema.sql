-- Multi-Agent Orchestrator — shared memory schema
-- Run automatically by shared/memory.py:init_schema(), or manually via:
--   psql -h $POSTGRES_HOST -U $POSTGRES_USER -d $POSTGRES_DB -f sql/schema.sql

CREATE TABLE IF NOT EXISTS agent_memory (
    task_id     UUID PRIMARY KEY,
    state       JSONB NOT NULL,
    status      TEXT NOT NULL DEFAULT 'running',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_steps (
    id          SERIAL PRIMARY KEY,
    task_id     UUID NOT NULL REFERENCES agent_memory (task_id) ON DELETE CASCADE,
    agent_name  TEXT NOT NULL,
    output      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_steps_task_id ON agent_steps (task_id);
CREATE INDEX IF NOT EXISTS idx_agent_memory_status ON agent_memory (status);
