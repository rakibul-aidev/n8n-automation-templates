"""
Email Triage Agent — reference implementation using Agent Foundation.

This agent:
  1. Reads an incoming email (via trigger_data)
  2. Classifies it (urgent / routine / spam / vip)
  3. Drafts an appropriate reply or escalates to a human
  4. Creates a task in the task tracker if action is needed
  5. Archives the email

Run manually:
    python email_triage_agent.py

Trigger via n8n webhook (POST /webhook/email-triage) with JSON body:
    {
        "email_id":   "msg_abc123",
        "sender":     "client@acme.com",
        "subject":    "Urgent: API down",
        "body":       "Our production integration stopped working at 3am...",
        "received_at": "2026-07-25T03:12:00Z"
    }
"""

from __future__ import annotations
import os
import sys

# Add parent dir to path so we can import from python/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..","python"))

from tools import tool
from agent_runner import AgentRunner, AgentConfig


# ── Define tools this agent is allowed to use ─────────────────────────────────

@tool(
    name="classify_email",
    description="Classify the email into a category: urgent, routine, spam, or vip",
    schema={
        "type": "object",
        "properties": {
            "email_id":  {"type": "string"},
            "reasoning": {"type": "string"},
            "category":  {"type": "string", "enum": ["urgent", "routine", "spam", "vip"]},
        },
        "required": ["email_id", "category", "reasoning"],
    },
)
def classify_email(email_id: str, reasoning: str, category: str) -> dict:
    """Stub — in production, write classification to DB or tagging API."""
    print(f"[classify_email] {email_id} → {category} ({reasoning})")
    return {"ok": True, "email_id": email_id, "category": category}


@tool(
    name="draft_reply",
    description="Draft a reply to the email for human review or auto-send",
    schema={
        "type": "object",
        "properties": {
            "email_id": {"type": "string"},
            "reply":    {"type": "string"},
            "auto_send": {"type": "boolean", "description": "True only for routine/spam"},
        },
        "required": ["email_id", "reply"],
    },
)
def draft_reply(email_id: str, reply: str, auto_send: bool = False) -> dict:
    """Stub — in production, call Gmail/Outlook API."""
    action = "SENT" if auto_send else "SAVED AS DRAFT"
    print(f"[draft_reply] {action} for {email_id}:\n{reply[:200]}...")
    return {"ok": True, "action": action, "email_id": email_id}


@tool(
    name="create_task",
    description="Create a follow-up task in the task tracker",
    schema={
        "type": "object",
        "properties": {
            "title":       {"type": "string"},
            "description": {"type": "string"},
            "priority":    {"type": "string", "enum": ["low", "medium", "high", "critical"]},
            "due_date":    {"type": "string", "description": "ISO 8601 date, e.g. 2026-07-26"},
        },
        "required": ["title", "priority"],
    },
)
def create_task(title: str, priority: str, description: str = "", due_date: str = "") -> dict:
    """Stub — in production, call Linear/Asana/Jira API."""
    print(f"[create_task] [{priority.upper()}] {title}")
    return {"ok": True, "task_id": f"TASK-{abs(hash(title)) % 9999}", "title": title}


@tool(
    name="archive_email",
    description="Archive the email after processing",
    schema={
        "type": "object",
        "properties": {
            "email_id": {"type": "string"},
            "label":    {"type": "string", "description": "Label to apply before archiving"},
        },
        "required": ["email_id"],
    },
)
def archive_email(email_id: str, label: str = "processed") -> dict:
    """Stub — in production, call Gmail/Outlook API."""
    print(f"[archive_email] {email_id} → labelled '{label}' and archived")
    return {"ok": True, "email_id": email_id}


# ── Agent configuration ────────────────────────────────────────────────────────

EMAIL_TRIAGE_CONFIG = AgentConfig(
    name="email_triage",
    description=(
        "Triage incoming business emails: classify urgency, draft a reply, "
        "create a follow-up task if needed, and archive. "
        "Escalate if the sender is a VIP, or the email threatens churn/legal action."
    ),
    tools=["classify_email", "draft_reply", "create_task", "archive_email"],
    escalation_conditions=[
        "Sender is a known VIP or executive",
        "Email mentions legal action, contract termination, or data breach",
        "Subject contains 'urgent' and no similar email has been seen before",
        "Confidence in the correct action is below 0.7",
    ],
    human_queue=f"slack:{os.environ.get('SLACK_ESCALATION_CHANNEL', '#ops-review')}",
    max_steps=12,
)


# ── Entry point ────────────────────────────────────────────────────────────────

def run_agent(trigger_data: dict) -> dict:
    runner = AgentRunner(EMAIL_TRIAGE_CONFIG)
    result = runner.run(trigger_data=trigger_data, trigger_type="email_webhook")
    return result


if __name__ == "__main__":
    # Example: run with a sample email
    sample_email = {
        "email_id":    "msg_demo_001",
        "sender":      "client@acme.com",
        "subject":     "Integration stopped working — urgent",
        "body": (
            "Hi team,\n\n"
            "Our production Zapier integration with your API has been failing since 3am. "
            "We're losing orders. Please advise urgently.\n\n"
            "Thanks, John"
        ),
        "received_at": "2026-07-25T03:14:00Z",
    }

    print("=" * 60)
    print("Email Triage Agent — Demo Run")
    print("=" * 60)

    result = run_agent(sample_email)

    print("\n" + "=" * 60)
    print(f"Status : {result['status']}")
    print(f"Run ID : {result['run_id']}")
    if result.get("summary"):
        print(f"Summary: {result['summary']}")
    if result.get("handoff_id"):
        print(f"Handoff: {result['handoff_id']}")
    print("=" * 60)
