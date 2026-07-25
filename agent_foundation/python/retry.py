"""
Retry with exponential backoff + dead-letter queue.
"""

from __future__ import annotations
import json
import os
import time
import uuid
from typing import Any, Callable, TypeVar
import psycopg2
import psycopg2.extras
from logger import get_logger

log = get_logger(__name__)
F = TypeVar("F", bound=Callable)

MAX_RETRIES = int(os.environ.get("AGENT_MAX_RETRIES", 3))
BASE_DELAY  = float(os.environ.get("AGENT_RETRY_BASE_DELAY", 2))


def _conn():
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def with_retry(
    fn: Callable,
    *args,
    run_id: str | None = None,
    agent_name: str = "unknown",
    max_retries: int = MAX_RETRIES,
    base_delay: float = BASE_DELAY,
    **kwargs,
) -> Any:
    """
    Call fn(*args, **kwargs) with exponential backoff.
    On final failure, writes to dead_letter table and re-raises.
    """
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                log.warning(
                    f"Attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
            else:
                log.error(f"All {max_retries + 1} attempts failed: {e}")
                _write_dead_letter(run_id, agent_name, args, kwargs, str(e), attempt + 1)

    raise last_error  # type: ignore


def _write_dead_letter(
    run_id: str | None,
    agent_name: str,
    args: tuple,
    kwargs: dict,
    error: str,
    retry_count: int,
) -> None:
    try:
        payload = {"args": str(args)[:2000], "kwargs": str(kwargs)[:2000]}
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO dead_letter (id, run_id, agent_name, payload, error, retry_count)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (str(uuid.uuid4()), run_id, agent_name, json.dumps(payload), error, retry_count),
                )
    except Exception as db_err:
        log.error(f"Failed to write dead letter: {db_err}")
