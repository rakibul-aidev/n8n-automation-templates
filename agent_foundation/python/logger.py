"""
Structured logger — writes to stdout (JSON) and PostgreSQL agent_steps.
"""

from __future__ import annotations
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg2
import psycopg2.extras


def _conn():
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


class AgentLogger:
    """Per-run logger that writes structured steps to PostgreSQL."""

    def __init__(self, run_id: str, agent_name: str) -> None:
        self.run_id = run_id
        self.agent_name = agent_name
        self._step = 0
        self._log = get_logger(agent_name)

    def log_step(
        self,
        step_type: str,
        input_data: Any = None,
        output_data: Any = None,
        tokens_used: int = 0,
        duration_ms: int = 0,
        status: str = "ok",
        error: str | None = None,
    ) -> str:
        self._step += 1
        step_id = str(uuid.uuid4())
        self._log.info(
            json.dumps({
                "run_id": self.run_id,
                "step": self._step,
                "type": step_type,
                "status": status,
                "tokens": tokens_used,
                "duration_ms": duration_ms,
                "error": error,
            })
        )
        try:
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO agent_steps
                          (id, run_id, step_number, step_type, input, output,
                           tokens_used, duration_ms, status, error)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            step_id,
                            self.run_id,
                            self._step,
                            step_type,
                            json.dumps(input_data) if input_data is not None else None,
                            json.dumps(output_data) if output_data is not None else None,
                            tokens_used,
                            duration_ms,
                            status,
                            error,
                        ),
                    )
        except Exception as e:
            self._log.error(f"Failed to write step to DB: {e}")
        return step_id

    def time_step(self, step_type: str, input_data: Any = None):
        """Context manager for timing a step."""
        return _TimedStep(self, step_type, input_data)


class _TimedStep:
    def __init__(self, logger: AgentLogger, step_type: str, input_data: Any) -> None:
        self._logger = logger
        self._step_type = step_type
        self._input = input_data
        self._start = 0.0
        self._output = None
        self._tokens = 0
        self.step_id: str = ""

    def __enter__(self):
        self._start = time.monotonic()
        return self

    def set_output(self, output: Any, tokens: int = 0) -> None:
        self._output = output
        self._tokens = tokens

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = int((time.monotonic() - self._start) * 1000)
        status = "error" if exc_type else "ok"
        error = str(exc_val) if exc_val else None
        self.step_id = self._logger.log_step(
            self._step_type,
            self._input,
            self._output,
            self._tokens,
            duration_ms,
            status,
            error,
        )
        return False  # don't suppress exceptions


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(os.environ.get("AGENT_LOG_LEVEL", "INFO"))
    return logger
