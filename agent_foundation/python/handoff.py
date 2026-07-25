"""
Human escalation handoff — routes to Slack or email with a structured card.
Humans never receive a raw LLM dump; they get: what happened, what was tried,
why it escalated, and a clear action required.
"""

from __future__ import annotations
import json
import os
import smtplib
import uuid
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import psycopg2
import psycopg2.extras
import requests
from logger import get_logger

log = get_logger(__name__)

ESCALATION_TIMEOUT = int(os.environ.get("AGENT_ESCALATION_TIMEOUT", 3600))


def _conn():
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def escalate(
    run_id: str,
    agent_name: str,
    reason: str,
    context: dict[str, Any],
    action_required: str,
    route: str | None = None,
) -> str:
    """
    Escalate to a human. Returns the handoff_id.

    route examples:
      "slack:#ops-review"
      "email:ops@company.com"
      None  → uses SLACK_ESCALATION_CHANNEL env var
    """
    handoff_id = str(uuid.uuid4())
    route = route or f"slack:{os.environ.get('SLACK_ESCALATION_CHANNEL', '#ops-review')}"
    timeout_at = datetime.now(timezone.utc) + timedelta(seconds=ESCALATION_TIMEOUT)

    # Persist to DB
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_handoffs
                  (id, run_id, agent_name, reason, context, action_required,
                   routed_to, status, timeout_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s)
                """,
                (
                    handoff_id, run_id, agent_name, reason,
                    json.dumps(context), action_required, route, timeout_at,
                ),
            )

    log.warning(f"ESCALATION [{handoff_id}] {agent_name}: {reason}")

    # Send notification
    if route.startswith("slack:"):
        channel = route.split(":", 1)[1]
        _notify_slack(handoff_id, agent_name, reason, context, action_required, channel)
    elif route.startswith("email:"):
        email = route.split(":", 1)[1]
        _notify_email(handoff_id, agent_name, reason, context, action_required, email)

    return handoff_id


def resolve(handoff_id: str, human_response: dict[str, Any]) -> None:
    """Mark a handoff as resolved and store the human's response."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agent_handoffs
                SET status = 'resolved', human_response = %s, resolved_at = NOW()
                WHERE id = %s
                """,
                (json.dumps(human_response), handoff_id),
            )
    log.info(f"Handoff {handoff_id} resolved")


def get_response(handoff_id: str, poll_interval: int = 30, timeout: int = ESCALATION_TIMEOUT) -> dict | None:
    """Poll DB until the handoff is resolved or times out. Returns human_response or None."""
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status, human_response FROM agent_handoffs WHERE id = %s",
                    (handoff_id,),
                )
                row = cur.fetchone()
        if row and row["status"] == "resolved":
            return row["human_response"]
        time.sleep(poll_interval)
    log.warning(f"Handoff {handoff_id} timed out after {timeout}s")
    return None


def _notify_slack(handoff_id: str, agent: str, reason: str, ctx: dict, action: str, channel: str) -> None:
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        log.warning("SLACK_BOT_TOKEN not set — skipping Slack notification")
        return
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"🚨 Agent Escalation: {agent}"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Reason:*\n{reason}"},
            {"type": "mrkdwn", "text": f"*Handoff ID:*\n`{handoff_id}`"},
        ]},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Action Required:*\n{action}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Context snapshot:*\n```{json.dumps(ctx, indent=2)[:1500]}```"}},
        {"type": "divider"},
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"Reply to this thread with your decision. Reference ID: `{handoff_id}`"}
        ]},
    ]
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"channel": channel, "blocks": blocks},
        timeout=10,
    )
    if not resp.ok or not resp.json().get("ok"):
        log.error(f"Slack notification failed: {resp.text}")


def _notify_email(handoff_id: str, agent: str, reason: str, ctx: dict, action: str, to_email: str) -> None:
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASSWORD", "")
    if not smtp_user:
        log.warning("SMTP_USER not set — skipping email notification")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Agent Escalation] {agent}: {reason[:80]}"
    msg["From"] = smtp_user
    msg["To"] = to_email
    body = f"""Agent Escalation — {agent}

Reason: {reason}
Handoff ID: {handoff_id}

Action Required:
{action}

Context:
{json.dumps(ctx, indent=2)[:3000]}
"""
    msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP(smtp_host, smtp_port) as s:
            s.starttls()
            s.login(smtp_user, smtp_pass)
            s.sendmail(smtp_user, to_email, msg.as_string())
    except Exception as e:
        log.error(f"Email notification failed: {e}")
