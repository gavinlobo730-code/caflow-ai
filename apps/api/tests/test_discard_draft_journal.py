"""
A draft journal can be discarded. A posted one can only be reversed.

WHY THE TWO ARE NOT THE SAME BUTTON
    A draft is off-books: is_posted = false, in no report, in no return.
    Discarding one changes no balance, so it is a plain delete.

    A posted entry is on the books, and the ledger is append-only. The database
    enforces it — trg_journal_immutability_delete (migration 058) raises
    "Cannot delete a posted journal entry … Create a reversal instead" — and
    that trigger is live in production today. Migration 266 made a posted entry
    EDITABLE until its period locks or its return is filed; it did not make one
    deletable, deliberately.

    So the endpoint refuses a posted entry ITSELF, with a message naming the
    reversal, rather than letting the attempt reach Postgres and come back to
    the CA as an opaque 500. That distinction is the whole point of this file:
    the guard has to be reachable, not incidental.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _schema_checked_db import SchemaCheckedDB  # noqa: E402

import routers.accounting as acct  # noqa: E402
from core.auth import get_current_user  # noqa: E402

FIRM = "firm-1"
CLIENT = "client-1"
USER = {"id": "u1", "auth_user_id": "auth-u1", "firm_id": FIRM,
        "role": "Partner", "email": "p@f.in"}

DRAFT = "00000000-0000-0000-0000-0000000000d1"
POSTED = "00000000-0000-0000-0000-0000000000p1"


def _rows():
    return [
        {"id": DRAFT, "firm_id": FIRM, "client_id": CLIENT, "is_posted": False,
         "reference_no": "JNL-001", "narration": "typo", "deleted_at": None},
        {"id": POSTED, "firm_id": FIRM, "client_id": CLIENT, "is_posted": True,
         "reference_no": "JNL-002", "narration": "real", "deleted_at": None},
    ]


@pytest.fixture()
def client(monkeypatch):
    db = SchemaCheckedDB({"journal_entries": _rows()})
    monkeypatch.setattr(acct, "_prod_db", lambda: db)
    monkeypatch.setattr(acct, "_assert_journal_scope_db", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(acct.router)
    app.dependency_overrides[get_current_user] = lambda: USER
    c = TestClient(app, raise_server_exceptions=False)
    c.db = db  # type: ignore[attr-defined]
    return c


def test_a_draft_is_discarded(client):
    res = client.delete(f"/api/accounting/journal/{DRAFT}")
    assert res.status_code == 200, res.text
    assert res.json()["data"]["discarded"] is True


def test_discarding_a_draft_is_a_soft_delete(client):
    """deleted_at, not a DELETE. The journal list, the approval queue and
    _assert_journal_scope_db all filter on it, so the row leaves every surface
    at once while the record and its lines survive for audit."""
    client.delete(f"/api/accounting/journal/{DRAFT}")
    row = next(r for r in client.db.rows["journal_entries"] if r["id"] == DRAFT)
    assert row["deleted_at"], "the draft should carry a deleted_at stamp"
    assert row in client.db.rows["journal_entries"], "the row itself must survive"


def test_a_posted_entry_is_refused(client):
    res = client.delete(f"/api/accounting/journal/{POSTED}")
    assert res.status_code == 422, (
        "a posted entry must be refused by the endpoint, not by the database — "
        "the trigger's error reaches the CA as an opaque 500"
    )


def test_the_refusal_tells_the_ca_what_to_do_instead(client):
    """A CA who is told 'no' and not 'reverse it' will go looking for a way to
    force the delete."""
    detail = client.delete(f"/api/accounting/journal/{POSTED}").json()["detail"]
    assert "revers" in detail.lower(), detail
    assert "append-only" in detail.lower() or "cannot be deleted" in detail.lower()


def test_a_posted_entry_is_left_completely_untouched(client):
    before = dict(next(r for r in client.db.rows["journal_entries"] if r["id"] == POSTED))
    client.delete(f"/api/accounting/journal/{POSTED}")
    after = next(r for r in client.db.rows["journal_entries"] if r["id"] == POSTED)
    assert after == before, "the refusal must not have written anything"


def test_an_unknown_entry_is_a_404(client):
    res = client.delete("/api/accounting/journal/00000000-0000-0000-0000-00000000ffff")
    assert res.status_code == 404


def test_an_already_discarded_draft_is_a_404(client):
    """deleted_at is filtered in the lookup, so a second discard finds nothing
    rather than silently re-stamping."""
    client.delete(f"/api/accounting/journal/{DRAFT}")
    res = client.delete(f"/api/accounting/journal/{DRAFT}")
    assert res.status_code == 404
