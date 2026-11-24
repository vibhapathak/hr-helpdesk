"""Escalation tickets. Uses monday.com (GraphQL API) when MONDAY_API_TOKEN and MONDAY_BOARD_ID
are set; otherwise a mock that appends to a JSONL file. Ticket text is PII-redacted first, so
contact details or IDs the user typed are never copied into a third-party system."""
from __future__ import annotations

import datetime as dt
import json
import logging
import secrets
from pathlib import Path

import httpx

from .config import Settings
from .guardrails import redact_pii

log = logging.getLogger(__name__)
MONDAY_URL = "https://api.monday.com/v2"


def _mock_ticket(settings: Settings, record: dict) -> dict:
    ticket_id = f"TKT-{dt.date.today():%Y%m%d}-{secrets.token_hex(2).upper()}"
    record = {"ticket_id": ticket_id, "backend": "mock", **record}
    path = Path(settings.tickets_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return record


def _monday_ticket(settings: Settings, record: dict) -> dict:
    headers = {"Authorization": settings.monday_api_token, "API-Version": "2024-10",
               "Content-Type": "application/json"}
    create = """mutation ($board: ID!, $name: String!) {
                  create_item (board_id: $board, item_name: $name) { id } }"""
    name = f"[{record['category'].upper()}][{record['priority']}] {record['summary']}"[:250]
    with httpx.Client(timeout=15) as client:
        r = client.post(MONDAY_URL, headers=headers,
                        json={"query": create, "variables": {"board": settings.monday_board_id, "name": name}})
        r.raise_for_status()
        body = r.json()
        if body.get("errors"):
            raise RuntimeError(body["errors"])
        item_id = body["data"]["create_item"]["id"]
        update = """mutation ($item: ID!, $body: String!) { create_update (item_id: $item, body: $body) { id } }"""
        note = (f"Raised by HR/IT helpdesk agent.\nRequester: {record.get('requester_employee_id') or 'unknown'}"
                f"\n\nUser question: {record['user_question']}\n\nDetails: {record['details']}")
        client.post(MONDAY_URL, headers=headers, json={"query": update, "variables": {"item": item_id, "body": note}})
    return {"ticket_id": f"MONDAY-{item_id}", "backend": "monday.com", **record}


def create_ticket(settings: Settings, *, summary: str, details: str, category: str, priority: str,
                  user_question: str, requester_employee_id: str | None = None) -> dict:
    allow = settings.allowlisted_emails
    record = {
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "category": category, "priority": priority,
        "summary": redact_pii(summary, allow).text,
        "details": redact_pii(details, allow).text,
        "user_question": redact_pii(user_question, allow).text,
        "requester_employee_id": requester_employee_id,
        "status": "open",
    }
    if settings.monday_api_token and settings.monday_board_id:
        try:
            return _monday_ticket(settings, record)
        except Exception as exc:  # never lose an escalation: fall back to the mock store
            log.error("monday.com ticket creation failed (%s); falling back to mock", exc)
    return _mock_ticket(settings, record)
