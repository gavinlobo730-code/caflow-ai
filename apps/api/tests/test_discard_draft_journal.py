"""
A manual journal can be discarded — draft always, posted while its period is open.

WHAT CHANGED, AND WHY
    A draft is off-books: is_posted = false, in no report, in no return.
    Discarding one changes no balance, so it is a plain soft delete here.

    A POSTED entry now goes to discard_posted_journal (migrations 275, 276),
    which holds the row and its counterpart FOR UPDATE, applies the limits —
    manual only, period open per journal_period_lock_reason for EACH date, and
    never half a reversal pair — writes the deletion record, and rebuilds the
    reporting passbook, all in one transaction. None of that can be split
    across the API and the database without racing itself, so the endpoint's
    job is to route, to pass the pair flag, and to surface the message.

    Migration 266 established the principle for editing: absolute immutability
    is stricter than Indian law, because Rule 3(1) of the Companies (Accounts)
    Rules 2014 requires an EDIT LOG of each change, which presumes entries can
    change. 275 gives discarding the same gate.

WHAT THIS FILE ASSERTS
    Routing and surfacing. The gate's BEHAVIOUR is proved against a real
    database in test_discard_manual_journal_pg.py — a double cannot tell you
    whether a SQL function refuses a locked period, only that it was called.
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


def test_a_posted_entry_is_routed_to_the_sql_function(client):
    """Every check lives in the function. The endpoint must not re-implement
    any of them — two copies of a rule drift, and this one decides whether a
    filed return can be edited out from under itself."""
    res = client.delete(f"/api/accounting/journal/{POSTED}")
    assert res.status_code == 200, res.text
    assert [c.fn for c in client.db.rpc_calls] == ["discard_posted_journal"]


# ── The pair flag ────────────────────────────────────────────────────────────

def test_the_pair_flag_defaults_to_off(client):
    """Deleting two rows when the CA asked for one is a surprise, so the API
    default is the conservative one and the caller opts in."""
    client.delete(f"/api/accounting/journal/{POSTED}")
    assert client.db.rpc_calls[0].params["p_with_pair"] is False


def test_the_pair_flag_is_passed_through(client):
    client.delete(f"/api/accounting/journal/{POSTED}?with_pair=true")
    assert client.db.rpc_calls[0].params["p_with_pair"] is True


def test_the_ids_the_function_actually_deleted_come_back(client, monkeypatch):
    """One call can remove two rows. A caller told only "deleted: true" refreshes
    the screen and sees a second entry gone with no explanation."""
    db = client.db
    real_rpc = db.rpc
    mate = "00000000-0000-0000-0000-0000000000p2"
    monkeypatch.setattr(db, "rpc", lambda fn, params=None: real_rpc(fn, params).returns(
        {"id": POSTED, "discarded": True, "deleted_ids": [POSTED, mate], "pair": True}))

    res = client.delete(f"/api/accounting/journal/{POSTED}?with_pair=true")
    assert res.status_code == 200, res.text
    assert res.json()["data"]["deleted_ids"] == [POSTED, mate]


def test_a_single_deletion_still_reports_its_own_id(client):
    """The double returns [] for an unstubbed rpc, which is what a real call
    returns when PostgREST gives back nothing useful. The endpoint must fall
    back to the entry it was asked about rather than reporting nothing."""
    res = client.delete(f"/api/accounting/journal/{POSTED}")
    assert res.json()["data"]["deleted_ids"] == [POSTED]


def test_the_function_is_called_with_the_callers_firm_and_the_entrys_client(client):
    client.delete(f"/api/accounting/journal/{POSTED}")
    params = client.db.rpc_calls[0].params
    assert params["p_firm"] == FIRM
    assert params["p_client"] == CLIENT
    assert params["p_entry_id"] == POSTED
    # journal_entries.created_by FKs to users.id, never the Supabase auth id.
    assert params["p_actor"] == "u1"


def test_a_posted_entry_is_not_soft_deleted_by_the_endpoint(client):
    """The function owns the write, inside the same transaction as the passbook
    rebuild. A deleted_at set out here would bypass that and leave
    account_period_balances holding the discarded entry's figures."""
    client.delete(f"/api/accounting/journal/{POSTED}")
    row = next(r for r in client.db.rows["journal_entries"] if r["id"] == POSTED)
    assert not row.get("deleted_at")


def test_the_functions_refusal_reaches_the_ca_verbatim(client, monkeypatch):
    """"GSTR-3B covering this date was filed on 18 Jul 2026" is the difference
    between a rule that reads as protective and one that reads as broken. It
    must not be replaced with something vaguer."""
    import routers.accounting as acct
    db = client.db
    real_rpc = db.rpc

    def failing_rpc(fn, params=None):
        return real_rpc(fn, params).raise_with(
            RuntimeError("GSTR-3B covering this date was filed on 18 Jul 2026."))

    monkeypatch.setattr(db, "rpc", failing_rpc)
    res = client.delete(f"/api/accounting/journal/{POSTED}")
    assert res.status_code == 422
    assert "GSTR-3B covering this date was filed on 18 Jul 2026." in res.json()["detail"]


# ── The deletion record ──────────────────────────────────────────────────────
# A soft delete is an UPDATE on journal_entries alone. trg_audit_capture fires
# with the HEADER; trg_audit_capture_line does not fire at all, because the
# lines are never touched. Without a snapshot the trail says an entry was
# deleted and nothing about what was in it.

def test_a_draft_deletion_snapshots_the_entry_first(client):
    client.delete(f"/api/accounting/journal/{DRAFT}")
    assert [c.fn for c in client.db.rpc_calls] == ["journal_entry_snapshot"]
    assert client.db.rpc_calls[0].params["p_entry_id"] == DRAFT


def test_the_snapshot_goes_into_the_audit_record(client, monkeypatch):
    logged: list[dict] = []
    monkeypatch.setattr(acct, "log_event",
                        lambda *a, **k: logged.append({"args": a, "kw": k}))
    db = client.db
    real_rpc = db.rpc
    full = {"id": DRAFT, "reference_no": "JNL-001",
            "lines": [{"account_code": "1000", "debit_paise": 5000}]}
    monkeypatch.setattr(db, "rpc",
                        lambda fn, params=None: real_rpc(fn, params).returns(full))

    client.delete(f"/api/accounting/journal/{DRAFT}")
    assert logged, "a draft deletion must be logged"
    assert logged[0]["kw"]["old_data"] == full, "the log got the thin row, not the snapshot"


def test_a_failed_snapshot_does_not_refuse_the_draft_deletion(client, monkeypatch):
    """A draft is in no report and no return. A thinner record is not worth
    refusing over — but it is reported, not swallowed."""
    seen: list[str] = []
    monkeypatch.setattr(acct, "capture_soft_failure",
                        lambda exc, **k: seen.append(k.get("operation", "")))
    db = client.db
    real_rpc = db.rpc
    monkeypatch.setattr(db, "rpc", lambda fn, params=None: real_rpc(fn, params).raise_with(
        RuntimeError("snapshot unavailable")))

    res = client.delete(f"/api/accounting/journal/{DRAFT}")
    assert res.status_code == 200, res.text
    assert seen == ["accounting.draft_discard_snapshot"], seen


def test_a_posted_deletion_is_not_logged_twice(client, monkeypatch):
    """discard_posted_journal writes the record inside the transaction that
    performs the deletion. A second log_event out here would put a thinner row
    in the trail for the same action, under a different verb."""
    logged: list[tuple] = []
    monkeypatch.setattr(acct, "log_event", lambda *a, **k: logged.append(a))
    client.delete(f"/api/accounting/journal/{POSTED}")
    assert logged == [], "the endpoint logged a posted deletion the function already logged"


def test_an_unknown_entry_is_a_404(client):
    res = client.delete("/api/accounting/journal/00000000-0000-0000-0000-00000000ffff")
    assert res.status_code == 404


def test_an_already_discarded_draft_is_a_404(client):
    """deleted_at is filtered in the lookup, so a second discard finds nothing
    rather than silently re-stamping."""
    client.delete(f"/api/accounting/journal/{DRAFT}")
    res = client.delete(f"/api/accounting/journal/{DRAFT}")
    assert res.status_code == 404
