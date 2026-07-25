"""
Claude-based email classifier and reply drafter.

Classifies emails into: urgent | routine | spam | vip
Then drafts an appropriate reply based on classification.
"""

from __future__ import annotations
import json
import os
from dataclasses import dataclass
from typing import Literal

import anthropic

Category = Literal["urgent", "routine", "spam", "vip"]

SYSTEM_PROMPT = """You are an email triage assistant. Given an email, you:
1. Classify it into exactly one category: urgent, routine, spam, or vip
2. Draft an appropriate reply (or explain why no reply is needed)
3. Suggest a task title if follow-up is required

Categories:
- urgent: Production issues, time-sensitive requests, complaints threatening to leave, anything requiring same-day action
- vip: Emails from known executives, enterprise clients, investors, or strategic partners — even if not time-sensitive
- routine: Normal business correspondence, meeting requests, FYI emails, regular client updates
- spam: Unsolicited marketing, phishing attempts, irrelevant automated emails

Respond in JSON:
{
  "category": "urgent|routine|spam|vip",
  "confidence": 0.0-1.0,
  "reasoning": "one sentence explaining the classification",
  "reply_needed": true|false,
  "draft_reply": "the reply text if reply_needed, else null",
  "task_title": "short task description if follow-up needed, else null",
  "auto_sendable": true|false  // true only for simple routine replies
}"""


@dataclass
class ClassificationResult:
    category: Category
    confidence: float
    reasoning: str
    reply_needed: bool
    draft_reply: str | None
    task_title: str | None
    auto_sendable: bool


class EmailClassifier:
    def __init__(self, api_key: str | None = None, model: str = "claude-haiku-4-5-20251001") -> None:
        # Use Haiku for speed and cost — classification doesn't need Opus
        self.client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self.model = model

    def classify(self, subject: str, sender: str, body: str, vip_senders: list[str] | None = None) -> ClassificationResult:
        """Classify an email and generate a draft reply."""
        vip_note = ""
        if vip_senders:
            vip_note = f"\nKnown VIP senders (treat these as vip regardless of content): {', '.join(vip_senders)}"

        user_prompt = f"""Classify this email:{vip_note}

From: {sender}
Subject: {subject}

Body:
{body[:3000]}"""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw = response.content[0].text
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            import re
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            data = json.loads(m.group()) if m else {}

        return ClassificationResult(
            category=data.get("category", "routine"),
            confidence=float(data.get("confidence", 0.8)),
            reasoning=data.get("reasoning", ""),
            reply_needed=data.get("reply_needed", False),
            draft_reply=data.get("draft_reply"),
            task_title=data.get("task_title"),
            auto_sendable=data.get("auto_sendable", False),
        )

    def batch_classify(self, emails: list[dict], vip_senders: list[str] | None = None) -> list[tuple[dict, ClassificationResult]]:
        """Classify a list of email dicts (from Graph API response)."""
        results = []
        for email in emails:
            subject = email.get("subject", "(no subject)")
            sender  = email.get("from", {}).get("emailAddress", {}).get("address", "unknown")
            body    = email.get("body", {}).get("content", email.get("bodyPreview", ""))
            result  = self.classify(subject, sender, body, vip_senders)
            results.append((email, result))
        return results


if __name__ == "__main__":
    # Quick smoke test
    classifier = EmailClassifier()
    result = classifier.classify(
        subject="Production API returning 500 errors since 2am",
        sender="ops@bigclient.com",
        body="Hi team, our integration has been failing for 3 hours. Orders are stuck. Please advise urgently.",
    )
    print(f"Category:   {result.category} (confidence: {result.confidence:.0%})")
    print(f"Reasoning:  {result.reasoning}")
    print(f"Draft reply:\n{result.draft_reply}")
    if result.task_title:
        print(f"Task:       {result.task_title}")
