"""
Microsoft Graph API client for email operations.

Handles OAuth2 client credentials flow and wraps the most common
Mail, Tasks, and User endpoints needed by the triage workflow.
"""

from __future__ import annotations
import os
from datetime import datetime, timezone
from typing import Any

import requests


class GraphClient:
    """Thin wrapper around Microsoft Graph API v1.0."""

    BASE_URL = "https://graph.microsoft.com/v1.0"
    TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        tenant_id: str | None = None,
        user_email: str | None = None,
    ) -> None:
        self.client_id = client_id or os.environ["AZURE_CLIENT_ID"]
        self.client_secret = client_secret or os.environ["AZURE_CLIENT_SECRET"]
        self.tenant_id = tenant_id or os.environ["AZURE_TENANT_ID"]
        self.user_email = user_email or os.environ["USER_EMAIL"]
        self._token: str | None = None
        self._token_expiry: datetime | None = None

    # ── Authentication ──────────────────────────────────────────────────────

    def _get_token(self) -> str:
        """Fetch or return cached access token (client credentials flow)."""
        if self._token and self._token_expiry and datetime.now(timezone.utc) < self._token_expiry:
            return self._token

        url = self.TOKEN_URL.format(tenant=self.tenant_id)
        resp = requests.post(url, data={
            "grant_type":    "client_credentials",
            "client_id":     self.client_id,
            "client_secret": self.client_secret,
            "scope":         "https://graph.microsoft.com/.default",
        }, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        # Subtract 60s buffer from expiry
        from datetime import timedelta
        self._token_expiry = datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"] - 60)
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type":  "application/json",
        }

    def _get(self, path: str, params: dict | None = None) -> Any:
        resp = requests.get(f"{self.BASE_URL}{path}", headers=self._headers(), params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> Any:
        resp = requests.post(f"{self.BASE_URL}{path}", headers=self._headers(), json=body, timeout=30)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def _patch(self, path: str, body: dict) -> Any:
        resp = requests.patch(f"{self.BASE_URL}{path}", headers=self._headers(), json=body, timeout=30)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    # ── Mail ────────────────────────────────────────────────────────────────

    def list_unread_emails(self, top: int = 20) -> list[dict]:
        """Return unread emails from inbox, newest first."""
        data = self._get(
            f"/users/{self.user_email}/mailFolders/inbox/messages",
            params={
                "$filter": "isRead eq false",
                "$orderby": "receivedDateTime desc",
                "$top": top,
                "$select": "id,subject,from,receivedDateTime,body,bodyPreview,importance",
            },
        )
        return data.get("value", [])

    def get_email(self, message_id: str) -> dict:
        return self._get(f"/users/{self.user_email}/messages/{message_id}")

    def mark_as_read(self, message_id: str) -> None:
        self._patch(f"/users/{self.user_email}/messages/{message_id}", {"isRead": True})

    def move_to_folder(self, message_id: str, folder: str = "Archive") -> dict:
        """Move email to a named folder (creates if needed)."""
        folder_id = self._get_or_create_folder(folder)
        return self._post(
            f"/users/{self.user_email}/messages/{message_id}/move",
            {"destinationId": folder_id},
        )

    def add_category(self, message_id: str, category: str) -> None:
        """Tag email with a colour category (must exist in Outlook settings)."""
        self._patch(
            f"/users/{self.user_email}/messages/{message_id}",
            {"categories": [category]},
        )

    def create_draft_reply(self, message_id: str, reply_body: str) -> dict:
        """Create a draft reply. Returns the new draft message."""
        return self._post(
            f"/users/{self.user_email}/messages/{message_id}/createReply",
            {"message": {"body": {"contentType": "Text", "content": reply_body}}},
        )

    def send_reply(self, message_id: str, reply_body: str) -> None:
        """Send a reply immediately (bypasses draft)."""
        self._post(
            f"/users/{self.user_email}/messages/{message_id}/reply",
            {"message": {"body": {"contentType": "Text", "content": reply_body}}},
        )

    # ── Tasks (Microsoft To Do) ─────────────────────────────────────────────

    def create_task(self, title: str, body: str = "", due_date: str | None = None) -> dict:
        """Create a task in the default To Do list."""
        lists = self._get(f"/users/{self.user_email}/todo/lists")
        list_id = lists["value"][0]["id"]  # Default list

        task: dict[str, Any] = {
            "title": title,
            "body": {"content": body, "contentType": "text"},
            "importance": "high",
        }
        if due_date:
            task["dueDateTime"] = {"dateTime": due_date, "timeZone": "UTC"}

        return self._post(f"/users/{self.user_email}/todo/lists/{list_id}/tasks", task)

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _get_or_create_folder(self, name: str) -> str:
        """Return folder ID by name, creating it if it doesn't exist."""
        folders = self._get(f"/users/{self.user_email}/mailFolders")
        for f in folders.get("value", []):
            if f["displayName"].lower() == name.lower():
                return f["id"]
        # Create it
        result = self._post(
            f"/users/{self.user_email}/mailFolders",
            {"displayName": name},
        )
        return result["id"]
