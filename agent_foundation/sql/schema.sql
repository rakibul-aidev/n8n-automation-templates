-- Agent Foundation Schema
-- Run once on a fresh PostgreSQL database

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Agent registry ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agents (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    config      JSONB NOT NULL DEFAULT '{}',
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Execution runs ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_runs (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_name   TEXT NOT NULL,
    trigger_type TEXT NOT NULL,                  -- webhook | schedule | manual
    trigger_data JSONB,                          -- raw input payload
    status       TEXT NOT NULL DEFAULT 'running', -- running | completed | failed | escalated
    started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at  TIMESTAMPTZ,
    error        TEXT,
    total_tokens INTEGER DEFAULT 0,
    total_steps  INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_agent_name ON agent_runs(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status     ON agent_runs(status);
CREATE INDEX IF NOT EXISTS idx_agent_runs_started_at ON agent_runs(started_at);

-- ── Execution steps (full audit trail) ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_steps (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id       UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    step_number  INTEGER NOT NULL,
    step_type    TEXT NOT NULL,   -- llm_call | tool_call | decision | handoff | memory_read | memory_write
    input        JSONB,
    output       JSONB,
    tokens_used  INTEGER DEFAULT 0,
    duration_ms  INTEGER,
    status       TEXT NOT NULL DEFAULT 'ok',  -- ok | error | retry | escalated
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_steps_run_id ON agent_steps(run_id);

-- ── Cross-run semantic memory ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_memory (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_name   TEXT NOT NULL,
    memory_key   TEXT NOT NULL,
    memory_value JSONB NOT NULL,
    tags         TEXT[] DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at   TIMESTAMPTZ,                        -- NULL = never expires
    UNIQUE (agent_name, memory_key)
);

CREATE INDEX IF NOT EXISTS idx_agent_memory_agent_key ON agent_memory(agent_name, memory_key);
CREATE INDEX IF NOT EXISTS idx_agent_memory_tags       ON agent_memory USING GIN(tags);

-- ── Human handoff queue ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_handoffs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id          UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    agent_name      TEXT NOT NULL,
    reason          TEXT NOT NULL,          -- why escalation happened
    context         JSONB NOT NULL,         -- full context at point of escalation
    action_required TEXT NOT NULL,          -- plain-English instruction for human
    routed_to       TEXT NOT NULL,          -- slack:#channel | email:addr@example.com
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | resolved | timeout
    human_response  JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    timeout_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_agent_handoffs_status     ON agent_handoffs(status);
CREATE INDEX IF NOT EXISTS idx_agent_handoffs_agent_name ON agent_handoffs(agent_name);

-- ── Tool call log (for cost tracking and debugging) ───────────────────────────
CREATE TABLE IF NOT EXISTS tool_calls (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id      UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    step_id     UUID REFERENCES agent_steps(id) ON DELETE SET NULL,
    tool_name   TEXT NOT NULL,
    input       JSONB,
    output      JSONB,
    success     BOOLEAN NOT NULL DEFAULT TRUE,
    duration_ms INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_run_id    ON tool_calls(run_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_tool_name ON tool_calls(tool_name);

-- ── Retry dead-letter queue ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dead_letter (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id       UUID REFERENCES agent_runs(id) ON DELETE SET NULL,
    agent_name   TEXT NOT NULL,
    payload      JSONB NOT NULL,
    error        TEXT NOT NULL,
    retry_count  INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Useful views ──────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW recent_runs AS
SELECT
    r.id,
    r.agent_name,
    r.status,
    r.started_at,
    r.finished_at,
    EXTRACT(EPOCH FROM (COALESCE(r.finished_at, NOW()) - r.started_at))::INT AS duration_s,
    r.total_steps,
    r.total_tokens,
    r.error,
    COUNT(h.id) AS escalations
FROM agent_runs r
LEFT JOIN agent_handoffs h ON h.run_id = r.id
WHERE r.started_at > NOW() - INTERVAL '7 days'
GROUP BY r.id
ORDER BY r.started_at DESC;

CREATE OR REPLACE VIEW pending_handoffs AS
SELECT
    h.id,
    h.agent_name,
    h.reason,
    h.action_required,
    h.routed_to,
    h.created_at,
    h.timeout_at,
    r.trigger_data
FROM agent_handoffs h
JOIN agent_runs r ON r.id = h.run_id
WHERE h.status = 'pending'
ORDER BY h.created_at ASC;
