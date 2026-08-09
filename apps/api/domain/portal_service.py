"""
Portal service — in-memory business logic for the client portal.

Handles document requests, messages, and dues without any FastAPI dependency,
so it can be tested with pure pytest.

All monetary values use integer paise — never float.
"""
from datetime import datetime, timezone
import uuid


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── In-memory mock stores (shared state within a process) ─────────────────────

_MOCK_DOC_REQUESTS: list[dict] = []
_MOCK_MESSAGES: list[dict] = []


def reset_mock_stores() -> None:
    """Clear all mock stores. Used in tests to isolate state."""
    _MOCK_DOC_REQUESTS.clear()
    _MOCK_MESSAGES.clear()


# ── Document Requests ─────────────────────────────────────────────────────────

def create_document_request(
    firm_id: str,
    client_id: str,
    title: str,
    description: str | None = None,
    due_date: str | None = None,
    is_urgent: bool = False,
) -> dict:
    """Create and store a document request in the mock store."""
    record = {
        "id": str(uuid.uuid4()),
        "firm_id": firm_id,
        "client_id": client_id,
        "title": title,
        "description": description,
        "due_date": due_date,
        "is_urgent": is_urgent,
        "status": "pending",
        "fulfilled_at": None,
        "created_at": _now(),
    }
    _MOCK_DOC_REQUESTS.append(record)
    return record


def list_document_requests(firm_id: str, client_id: str) -> list[dict]:
    """List document requests filtered by firm and client, newest first."""
    rows = [
        r for r in _MOCK_DOC_REQUESTS
        if r["firm_id"] == firm_id and r["client_id"] == client_id
    ]
    return sorted(rows, key=lambda r: r["created_at"], reverse=True)


def get_document_request(request_id: str) -> dict | None:
    """Fetch a document request by id, without mutating it. Used by the
    router to resolve the request's client before checking assignment scope."""
    return next((r for r in _MOCK_DOC_REQUESTS if r["id"] == request_id), None)


def complete_document_request(request_id: str) -> dict | None:
    """Mark a document request as fulfilled. Returns the updated record or None."""
    now = _now()
    for r in _MOCK_DOC_REQUESTS:
        if r["id"] == request_id:
            r["status"] = "fulfilled"
            r["fulfilled_at"] = now
            return r
    return None


# ── Messages ──────────────────────────────────────────────────────────────────

def send_message(
    firm_id: str,
    client_id: str,
    text: str,
    from_ca: bool = True,
) -> dict:
    """Store a portal message and return it."""
    record = {
        "id": str(uuid.uuid4()),
        "firm_id": firm_id,
        "client_id": client_id,
        "text": text,
        "from_ca": from_ca,
        "created_at": _now(),
    }
    _MOCK_MESSAGES.append(record)
    return record


def list_messages(firm_id: str, client_id: str) -> list[dict]:
    """List messages filtered by firm and client, newest first."""
    rows = [
        m for m in _MOCK_MESSAGES
        if m["firm_id"] == firm_id and m["client_id"] == client_id
    ]
    return sorted(rows, key=lambda m: m["created_at"], reverse=True)


# ── Dues ──────────────────────────────────────────────────────────────────────

def compute_dues_summary(dues: list[dict]) -> dict:
    """
    Compute total outstanding dues in paise from a list of transaction rows.
    Uses integer paise arithmetic — never float. (CAflow rule: every rupee
    calculation must use integer paise.)
    """
    total_paise: int = sum(int(d.get("total_paise") or 0) for d in dues)
    overdue_count: int = sum(1 for d in dues if d.get("status") == "overdue")
    return {
        "dues": dues,
        "total_paise": total_paise,
        "overdue_count": overdue_count,
    }
