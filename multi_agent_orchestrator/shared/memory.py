"""
Shared PostgreSQL memory layer.

Persists the LangGraph AgentState's working_memory to Postgres after every
supervisor step, and logs every sub-agent's output to an append-only audit
table. This is what makes memory genuinely "shared" — any process with a
connection string can read the current state of a task, or replay its full
step-by-step history, not just the in-process LangGraph state object.

Falls back to a no-op in-memory shim if POSTGRES_HOST isn't configured, so
the graph still runs without a database for local experimentation — but
`memory.enabled` tells you whether persistence is actually active.
"""

from __future__ import annotations
import os
import json
from datetime import datetime, timezone
from typing import Any, Optional

try:
    import psycopg2
    import psycopg2.extras
    _HAS_PSYCOPG2 = True
except ImportError:
    _HAS_PSYCOPG2 = False


def _config() -> Optional[dict]:
    host = os.environ.get("POSTGRES_HOST")
    if not host:
        return None
    return {
        "host": host,
        "port": os.environ.get("POSTGRES_PORT", "5432"),
        "dbname": os.environ.get("POSTGRES_DB", "agents"),
        "user": os.environ.get("POSTGRES_USER", "postgres"),
        "password": os.environ.get("POSTGRES_PASSWORD", ""),
    }


enabled = _HAS_PSYCOPG2 and _config() is not None


def get_connection():
    """Open a new connection using POSTGRES_* env vars. Caller must close it."""
    cfg = _config()
    if not cfg or not _HAS_PSYCOPG2:
        raise RuntimeError(
            "Postgres memory is not configured. Set POSTGRES_HOST/PORT/DB/USER/PASSWORD "
            "and install psycopg2-binary, or run without persistence (memory.enabled is False)."
        )
    return psycopg2.connect(**cfg)


def init_schema() -> None:
    """Create the memory tables if they don't already exist. Safe to call on every startup."""
    if not enabled:
        return
    schema_path = os.path.join(os.path.dirname(__file__), "..", "sql", "schema.sql")
    with open(schema_path) as f:
        ddl = f.read()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()
    finally:
        conn.close()


def save_state(task_id: str, state: dict, status: str = "running") -> None:
    """Upsert the full working state for a task_id. Called after every supervisor step."""
    if not enabled:
        return
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_memory (task_id, state, status, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (task_id)
                DO UPDATE SET state = EXCLUDED.state,
                              status = EXCLUDED.status,
                              updated_at = EXCLUDED.updated_at
                """,
                (task_id, json.dumps(state, default=str), status, datetime.now(timezone.utc)),
            )
        conn.commit()
    finally:
        conn.close()


def load_state(task_id: str) -> Optional[dict]:
    """Fetch a previously saved state for a task_id, or None if it doesn't exist."""
    if not enabled:
        return None
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT state, status FROM agent_memory WHERE task_id = %s", (task_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def log_agent_step(task_id: str, agent_name: str, output: str) -> None:
    """Append one sub-agent's output to the audit trail. Called by researcher/writer/reviewer nodes."""
    if not enabled:
        return
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_steps (task_id, agent_name, output, created_at)
                VALUES (%s, %s, %s, %s)
                """,
                (task_id, agent_name, output, datetime.now(timezone.utc)),
            )
        conn.commit()
    finally:
        conn.close()


def get_history(task_id: str) -> list[dict]:
    """Return the full ordered step history for a task_id — the audit trail."""
    if not enabled:
        return []
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT agent_name, output, created_at FROM agent_steps "
                "WHERE task_id = %s ORDER BY created_at ASC",
                (task_id,),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
