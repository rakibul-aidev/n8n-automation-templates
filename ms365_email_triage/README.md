# MS365 Email Triage — n8n Workflow

Automated email triage for Microsoft 365 Outlook using n8n + Claude AI.

**What it does:**
- Polls your Outlook inbox every 5 minutes via Microsoft Graph API
- Classifies each email: urgent / routine / spam / vip
- Drafts a reply using Claude and saves it as a draft (or auto-sends routine replies)
- Creates a task in Microsoft To Do / Planner for emails needing follow-up
- Sends a Slack alert for urgent or VIP emails
- Archives processed emails with appropriate labels

## Prerequisites

- n8n instance (self-hosted or cloud)
- Microsoft 365 account with admin consent for Graph API
- Azure App Registration (see setup below)
- Anthropic API key
- Slack workspace (optional, for alerts)

## Azure App Registration

1. Go to [portal.azure.com](https://portal.azure.com) → Azure Active Directory → App registrations → New registration
2. Name: `n8n-email-triage`
3. Supported account types: Single tenant
4. After creation, note the **Application (client) ID** and **Directory (tenant) ID**
5. Under **Certificates & secrets** → New client secret → copy the value immediately
6. Under **API permissions** → Add:
   - `Mail.Read`
   - `Mail.ReadWrite`
   - `Mail.Send`
   - `Tasks.ReadWrite` (for To Do integration)
   - `ChannelMessage.Send` (optional, for Teams alerts)
7. Click **Grant admin consent**
8. In [Microsoft To Do](https://to-do.office.com/), create (or pick) the task list you want follow-ups created in, then copy its list ID into `MS_TODO_LIST_ID` (find it via `GET https://graph.microsoft.com/v1.0/me/todo/lists` with your Graph token)

## Environment Variables

```env
AZURE_CLIENT_ID=your-client-id
AZURE_CLIENT_SECRET=your-client-secret
AZURE_TENANT_ID=your-tenant-id
ANTHROPIC_API_KEY=sk-ant-...
SLACK_BOT_TOKEN=xoxb-...
SLACK_URGENT_CHANNEL=#urgent-emails
USER_EMAIL=your@outlook.com
MS_TODO_LIST_ID=your-to-do-list-id
```

## Quick Start

1. Import `ms365_email_triage_workflow.json` into n8n
2. Set credentials: Microsoft OAuth2 + HTTP Header Auth for Anthropic
3. Configure your `USER_EMAIL` in the workflow variables
4. Activate the workflow

## Files

```
ms365_email_triage/
├── README.md
├── ms365_email_triage_workflow.json    # Main n8n workflow
├── python/
│   ├── graph_client.py                 # MS Graph API wrapper
│   └── classifier.py                   # Claude-based email classifier
└── .env.example
```

## Architecture

```
Outlook Inbox (Poll every 5min)
        │
        ▼
  Fetch unread emails (Graph API)
        │
        ▼
  Claude classification
  {urgent | routine | spam | vip}
        │
   ┌────┴────────┬──────────────┐
   ▼             ▼              ▼
 urgent/vip   routine         spam
   │             │              │
Slack alert  Draft reply     Archive
Create task  Auto-send       Label: spam
   │         Archive
   ▼
Human review
```
