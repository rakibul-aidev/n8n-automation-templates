"""
Agent Memory — PostgreSQL-backed cross-run memory for autonomous agents.

Three layers:
  working   — in-process dict, lives for one run
  episodic  — agent_steps table, per-run audit trail
  semantic  — agent_memory table, cross-run key/value store
"""

from __future__ import annotations
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any
import psycopg2
import psycopg2.extras
from logger import get_logger

log = get_logger(__name__)


def _conn():
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


class WorkingMemory:
    """In-process dict scoped to a single agent run."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        self._store[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._store.get(key, default)

    def update(self, data: dict) -> None:
        self._store.update(data)

    def all(self) -> dict:
        return dict(self._store)

    def clear(self) -> None:
        self._store.clear()


class SemanticMemory:
    """Cross-run persistent memory stored in PostgreSQL agent_memory table."""

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name

    def set(self, key: str, value: Any, tags: list[str] | None = None, ttl_days: int | None = None) -> None:
        expires_at = None
        if ttl_days:
            expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)

        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_memory (agent_name, memory_key, memory_value, tags, expires_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (agent_name, memory_key)
                    DO UPDATE SET
                        memory_value = EXCLUDED.memory_value,
                        tags         = EXCLUDED.tags,
                        expires_at   = EXCLUDED.expires_at,
                        updated_at   = NOW()
                    """,
                    (self.agent_name, key, json.dumps(value), tags or [], expires_at),
                )
        log.debug(f"Memory SET {self.agent_name}:{key}")

    def get(self, key: str, default: Any = None) -> Any:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT memory_value FROM agent_memory
                    WHERE agent_name = %s AND memory_key = %s
                      AND (expires_at IS NULL OR expires_at > NOW())
                    """,
                    (self.agent_name, key),
                )
                row = cur.fetchone()
        if row is None:
            return default
        return row["memory_value"]

    def search_by_tags(self, tags: list[str]) -> list[dict]:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT memory_key, memory_value, tags, updated_at
                    FROM agent_memory
                    WHERE agent_name = %s AND tags && %s
                      AND (expires_at IS NULL OR expires_at > NOW())
                    ORDER BY updated_at DESC
                    """,
                    (self.agent_name, tags),
                )
                return cur.fetchall()

    def delete(self, key: str) -> None:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM agent_memory WHERE agent_name = %s AND memory_key = %s",
                    (self.agent_name, key),
                )

    def prune_expired(self) -> int:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM agent_memory WHERE agent_name = %s AND expires_at <= NOW()",
                    (self.agent_name,),
                )
                return cur.rowcount


class AgentMemory:
    """Combined memory interface for an agent run."""

    def __init__(self, agent_name: str) -> None:
        self.working = WorkingMemory()
        self.semantic = SemanticMemory(agent_name)
