"""
POST /api/accounting/journal must not turn a server-side failure into either an
opaque 500 or, worse, a silent success.

WHAT THIS PINS

1.  A failure must stay NON-2XX.
    apps/web/lib/api/index.ts `request()` throws only on `!res.ok`. The
    200 + {"success": false} shape used elsewhere in this codebase (see
    routers/receipts.py) would therefore be read by the journal editor as a
    SUCCESS: it would call done(), announce "Journal entry posted", write a
    timeline event and navigate to the journal list — having posted nothing.
    A wrong ledger the CA believes is right is worse than an error.

2.  The failure must be REPORTED, not just raised.
    The 42501 permission error behind task #270 reached the CA as a bare
    "Internal server error" with nothing but a traceback behind it, which is
    why identifying it took a dive through the database logs.
    core/observability.capture_posting_failure exists for exactly this class of
    failure — it is what main.py's Sentry install is for — and this endpoint
    never called it.

3.  A failed AUDIT write must not be reported as a failed POST.
    log_event ran inside the same try, so an audit failure after a successful
    post told the CA the post had failed. It has not: the entry is on the books.
    Inviting a retry of something that already happened is the opposite of what
    should happen.

4.  Deliberate HTTPExceptions still pass through untouched (no-regression).
"""
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import routers.accounting as acct
from routers.accounting import router as accounting_router
from core.auth import get_current_user

PARTNER = {"id": "u1", "auth_user_id": "auth-u1", "firm_id": "F1",
           "role": "Partner", "email": "p@f.in"}

PAYLOAD = {
    "client_id": "C1",
    "entry_date": "2026-08-20",
    "reference_no": "JNL-001",
    "narration": "Credit Sales",
    "entry_type": "Journal",
    "status": "posted",
    "lines": [
        {"account_id": "A-AR",    "debit_paise": 5000000, "credit_paise": 0},
        {"account_id": "A-SALES", "debit_paise": 0,       "credit_paise": 5000000},
    ],
}


def _client():
    app = FastAPI()
    app.include_router(accounting_router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def captured(monkeypatch):
    """Collect capture_posting_failure calls instead of shipping them to Sentry.

    raising=False on purpose: against a build where the endpoint does not import
    capture_posting_failure at all, this fixture must still set up cleanly so the
    ASSERTIONS below report the gap. Without it every test in the module errors
    on the fixture instead, which is not a negative control — it says only that
    the name is missing, not that the behaviour is wrong.
    """
    calls = []
    monkeypatch.setattr(acct, "capture_posting_failure",
                        lambda exc, **kw: calls.append((exc, kw)), raising=False)
    return calls


# ── 1 + 2: an unexpected failure is non-2xx AND reported ─────────────────────

def test_unexpected_posting_failure_is_handled_not_left_to_escape(monkeypatch, captured):
    """The production shape: the DB refuses the write with something that is not
    an HTTPException. 42501 arrived exactly like this.

    Note what is NOT asserted here: "status is 500". An unhandled exception also
    produces a 500 (main.py's _errors_with_cors converts it), which is precisely
    what the CA saw. The status was never the defect. What distinguishes a
    handled failure is that the endpoint answers with a body it chose."""
    def boom(*a, **k):
        raise RuntimeError("permission denied for table journal_entries")
    monkeypatch.setattr(acct.accounting_service, "create_journal_entry", boom)

    res = _client().post("/api/accounting/journal", json=PAYLOAD)

    assert res.status_code == 500
    assert res.headers.get("content-type", "").startswith("application/json"), (
        "the exception escaped the endpoint instead of being handled — there is no "
        "JSON body, so nothing chose what the CA is told"
    )
    assert "detail" in res.json(), (
        "a failed post must answer with a message, not an unhandled crash; "
        "lib/api surfaces the body verbatim to the CA"
    )


def test_unexpected_posting_failure_is_captured_with_document_context(monkeypatch, captured):
    def boom(*a, **k):
        raise RuntimeError("permission denied for table journal_entries")
    monkeypatch.setattr(acct.accounting_service, "create_journal_entry", boom)

    _client().post("/api/accounting/journal", json=PAYLOAD)

    assert len(captured) == 1, "the failure was never reported to capture_posting_failure"
    exc, ctx = captured[0]
    assert isinstance(exc, RuntimeError)
    assert ctx["operation"] == "create_journal_entry"
    # Tags are what make the next one traceable to a document rather than a stack.
    assert ctx["firm_id"] == "F1"
    assert ctx["client_id"] == "C1"
    assert ctx["reference_no"] == "JNL-001"
    assert ctx["entry_date"] == "2026-08-20"


def test_failure_message_does_not_leak_internals_but_says_what_happened(monkeypatch, captured):
    def boom(*a, **k):
        raise RuntimeError("permission denied for table journal_entries")
    monkeypatch.setattr(acct.accounting_service, "create_journal_entry", boom)

    detail = _client().post("/api/accounting/journal", json=PAYLOAD).json()["detail"]

    assert "permission denied" not in detail, "raw database text must not reach the CA"
    # The one fact a CA needs in order to know whether to retry. Safe to assert:
    # post_journal_atomic is a single transaction, so a failure wrote nothing.
    assert "ledger" in detail.lower()


# ── 3: a failed audit write must not sink a completed post ───────────────────

def test_audit_failure_does_not_fail_a_completed_post(monkeypatch, captured):
    monkeypatch.setattr(acct.accounting_service, "create_journal_entry",
                        lambda payload: {"id": "JE-1", **payload})

    def audit_boom(*a, **k):
        raise RuntimeError("audit_log unreachable")
    monkeypatch.setattr(acct, "log_event", audit_boom)

    res = _client().post("/api/accounting/journal", json=PAYLOAD)

    assert res.status_code == 200, (
        "the entry posted; an audit-write failure must not tell the CA it did not, "
        "or they will retry a post that already happened"
    )
    assert res.json()["success"] is True
    assert res.json()["data"]["id"] == "JE-1"
    # Still reported — swallowed silently is how the audit trail rots unnoticed.
    assert [c for c in captured if c[1]["operation"] == "create_journal_entry.audit"]


# ── 4: no-regression — deliberate errors are unchanged ───────────────────────

def test_http_exceptions_from_the_service_pass_through(monkeypatch, captured):
    """A locked FY, an unbalanced entry, a filed return: these messages are
    written for the CA and must reach them with their own status code."""
    def locked(*a, **k):
        raise HTTPException(status_code=422, detail="Cannot post to a locked financial year: 2025-26.")
    monkeypatch.setattr(acct.accounting_service, "create_journal_entry", locked)

    res = _client().post("/api/accounting/journal", json=PAYLOAD)

    assert res.status_code == 422
    assert "locked financial year" in res.json()["detail"]
    assert captured == [], "a deliberate 422 is not a posting failure and must not page anyone"


def test_a_successful_post_is_unchanged(monkeypatch, captured):
    monkeypatch.setattr(acct.accounting_service, "create_journal_entry",
                        lambda payload: {"id": "JE-2", **payload})
    monkeypatch.setattr(acct, "log_event", lambda *a, **k: None)

    res = _client().post("/api/accounting/journal", json=PAYLOAD)

    assert res.status_code == 200
    assert res.json()["success"] is True
    assert res.json()["data"]["id"] == "JE-2"
    assert captured == []
