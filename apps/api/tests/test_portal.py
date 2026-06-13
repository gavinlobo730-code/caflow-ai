"""
Tests for the client portal domain service — document requests, messages, and dues.

Tests call domain.portal_service directly (no FastAPI/HTTP layer needed),
consistent with the project's unit test pattern (see test_accounting_journal.py).

Financial calculations use integer paise — never float.
"""
import pytest
from domain.portal_service import (
    reset_mock_stores,
    create_document_request,
    list_document_requests,
    complete_document_request,
    send_message,
    list_messages,
    compute_dues_summary,
)

FIRM_ID = "firm-unit-001"
CLIENT_ID = "client-unit-001"


@pytest.fixture(autouse=True)
def clear_stores():
    """Reset in-memory mock stores before each test to isolate state."""
    reset_mock_stores()
    yield
    reset_mock_stores()


# ── Document Request tests ────────────────────────────────────────────────────

def test_create_document_request_returns_correct_fields():
    """Created document request must have correct fields and pending status."""
    record = create_document_request(
        firm_id=FIRM_ID,
        client_id=CLIENT_ID,
        title="Upload bank statement",
        description="For the period Jan–Mar 2026",
    )
    assert record["title"] == "Upload bank statement"
    assert record["status"] == "pending"
    assert record["fulfilled_at"] is None
    assert record["firm_id"] == FIRM_ID
    assert record["client_id"] == CLIENT_ID
    assert "id" in record
    assert "created_at" in record


def test_list_document_requests_includes_created_record():
    """A created document request must appear in the list for the same firm/client."""
    create_document_request(FIRM_ID, CLIENT_ID, "Upload Form 16 for FY 2025-26")
    rows = list_document_requests(FIRM_ID, CLIENT_ID)
    titles = [r["title"] for r in rows]
    assert "Upload Form 16 for FY 2025-26" in titles


def test_complete_document_request_marks_fulfilled():
    """
    Completing a request must update status to 'fulfilled' and set fulfilled_at.
    Verifies the CRUD cycle: create → complete → verify.
    """
    record = create_document_request(FIRM_ID, CLIENT_ID, "Upload ITR acknowledgement")
    req_id = record["id"]

    updated = complete_document_request(req_id)
    assert updated is not None
    assert updated["status"] == "fulfilled"
    assert updated["fulfilled_at"] is not None


def test_urgent_flag_is_persisted():
    """is_urgent=True should be stored and returned in the record."""
    record = create_document_request(FIRM_ID, CLIENT_ID, "Urgent: Upload invoices", is_urgent=True)
    assert record["is_urgent"] is True


def test_list_document_requests_filters_by_client():
    """Requests created for CLIENT_ID must not appear in another client's list."""
    create_document_request(FIRM_ID, CLIENT_ID, "Upload PAN card copy")
    rows = list_document_requests(FIRM_ID, "other-client-999")
    titles = [r["title"] for r in rows]
    assert "Upload PAN card copy" not in titles


def test_complete_nonexistent_request_returns_none():
    """Completing a non-existent request must return None without raising."""
    result = complete_document_request("does-not-exist")
    assert result is None


# ── Message tests ─────────────────────────────────────────────────────────────

def test_send_message_returns_record_with_correct_fields():
    """Sending a portal message should return a record with from_ca=True."""
    record = send_message(FIRM_ID, CLIENT_ID, "Advance tax due on 15 Sep.", from_ca=True)
    assert record["text"] == "Advance tax due on 15 Sep."
    assert record["from_ca"] is True
    assert record["firm_id"] == FIRM_ID
    assert record["client_id"] == CLIENT_ID
    assert "id" in record
    assert "created_at" in record


def test_list_messages_includes_sent_message():
    """A sent message must appear when listing messages for the same client."""
    send_message(FIRM_ID, CLIENT_ID, "Your TDS return 26Q for Q1 has been filed.")
    rows = list_messages(FIRM_ID, CLIENT_ID)
    texts = [m["text"] for m in rows]
    assert "Your TDS return 26Q for Q1 has been filed." in texts


# ── Dues tests ────────────────────────────────────────────────────────────────

def test_compute_dues_summary_integer_paise_arithmetic():
    """
    compute_dues_summary must use integer paise arithmetic — never float.
    (CAflow rule: every rupee calculation must use integer paise.)
    """
    dues = [
        {"id": "1", "total_paise": 1800000, "status": "unpaid"},   # ₹18,000
        {"id": "2", "total_paise": 250000,  "status": "overdue"},  # ₹2,500
    ]
    summary = compute_dues_summary(dues)
    assert isinstance(summary["total_paise"], int), "total_paise must be int, not float"
    assert summary["total_paise"] == 2050000  # ₹20,500 in paise
    assert summary["overdue_count"] == 1
    assert len(summary["dues"]) == 2


def test_compute_dues_summary_empty_list():
    """Empty dues list must yield total_paise=0 and overdue_count=0, both ints."""
    summary = compute_dues_summary([])
    assert summary["total_paise"] == 0
    assert isinstance(summary["total_paise"], int)
    assert summary["overdue_count"] == 0
    assert summary["dues"] == []
