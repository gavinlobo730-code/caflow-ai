"""
Tests for the client portal router — document requests, messages, and dues.

These tests call the router functions directly (no HTTP layer required),
consistent with the project's unit test pattern.

Financial calculations use integer paise — never float.
"""
import pytest
import os

# Ensure SUPABASE_URL is unset so the in-memory mock path is used
os.environ.pop("SUPABASE_URL", None)

import routers.portal as portal_mod
from routers.portal import (
    list_document_requests,
    create_document_request,
    complete_document_request,
    list_messages,
    send_message,
    get_dues,
    CreateDocRequestBody,
    SendMessageBody,
)


FIRM_ID = "firm-unit-001"
CLIENT_ID = "client-unit-001"


def _make_doc_req_body(title: str = "Upload bank statement", is_urgent: bool = False) -> CreateDocRequestBody:
    return CreateDocRequestBody(
        firm_id=FIRM_ID,
        client_id=CLIENT_ID,
        title=title,
        description="For the period Jan–Mar 2026",
        is_urgent=is_urgent,
    )


def _make_msg_body(text: str = "GSTR-1 filed.", from_ca: bool = True) -> SendMessageBody:
    return SendMessageBody(
        firm_id=FIRM_ID,
        client_id=CLIENT_ID,
        text=text,
        from_ca=from_ca,
    )


# ── Document Request tests ────────────────────────────────────────────────────

def test_create_document_request_returns_success():
    """Creating a document request should return success=True with correct fields."""
    result = create_document_request(_make_doc_req_body("Upload GST certificate"))
    assert result["success"] is True
    assert result["data"]["title"] == "Upload GST certificate"
    assert result["data"]["status"] == "pending"
    assert result["data"]["fulfilled_at"] is None
    assert result["error"] is None


def test_list_document_requests_includes_created_record():
    """A created document request must appear in the list for the same firm/client."""
    create_document_request(_make_doc_req_body("Upload Form 16 for FY 2025-26"))
    result = list_document_requests(firm_id=FIRM_ID, client_id=CLIENT_ID)
    assert result["success"] is True
    titles = [r["title"] for r in result["data"]]
    assert "Upload Form 16 for FY 2025-26" in titles


def test_complete_document_request_marks_fulfilled():
    """
    Completing a request must update status to 'fulfilled' and set fulfilled_at.
    This verifies the CRUD cycle: create → complete → verify.
    """
    created = create_document_request(_make_doc_req_body("Upload ITR acknowledgement"))
    req_id = created["data"]["id"]

    result = complete_document_request(req_id)
    assert result["success"] is True
    assert result["data"]["status"] == "fulfilled"
    assert result["data"]["fulfilled_at"] is not None


def test_urgent_flag_is_persisted():
    """is_urgent=True should be stored and returned in the record."""
    result = create_document_request(_make_doc_req_body("Urgent: Upload invoices", is_urgent=True))
    assert result["data"]["is_urgent"] is True


def test_list_document_requests_filters_by_client():
    """Requests created for CLIENT_ID must not appear in another client's list."""
    create_document_request(_make_doc_req_body("Upload PAN card copy"))
    result = list_document_requests(firm_id=FIRM_ID, client_id="other-client-999")
    titles = [r["title"] for r in result["data"]]
    assert "Upload PAN card copy" not in titles


# ── Message tests ─────────────────────────────────────────────────────────────

def test_send_message_returns_success():
    """Sending a portal message should return success=True with the message text."""
    result = send_message(_make_msg_body("Advance tax due on 15 Sep — pay 45% of estimated liability."))
    assert result["success"] is True
    assert result["data"]["text"] == "Advance tax due on 15 Sep — pay 45% of estimated liability."
    assert result["data"]["from_ca"] is True
    assert result["error"] is None


def test_list_messages_includes_sent_message():
    """A sent message must appear when listing messages for the same client."""
    send_message(_make_msg_body("Your TDS return 26Q for Q1 has been filed."))
    result = list_messages(firm_id=FIRM_ID, client_id=CLIENT_ID)
    assert result["success"] is True
    texts = [m["text"] for m in result["data"]]
    assert "Your TDS return 26Q for Q1 has been filed." in texts


# ── Dues tests ────────────────────────────────────────────────────────────────

def test_get_dues_returns_success_with_integer_paise():
    """
    Dues endpoint must return success=True. In mock mode dues list is empty.
    Critical rule: total_paise MUST be an integer — never a float.
    (Every rupee calculation must use integer paise arithmetic.)
    """
    result = get_dues(firm_id=FIRM_ID, client_id=CLIENT_ID)
    assert result["success"] is True
    assert isinstance(result["data"]["dues"], list)
    # All monetary totals must be integers, not floats
    assert isinstance(result["data"]["total_paise"], int), "total_paise must be int, not float"
    assert result["data"]["total_paise"] >= 0
    assert isinstance(result["data"]["overdue_count"], int)
