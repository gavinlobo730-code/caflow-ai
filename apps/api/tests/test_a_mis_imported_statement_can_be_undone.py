"""BANK-06 — a statement imported by mistake can be removed, and only then.

The wrong file, the wrong client, the wrong month. Until this the only DELETE
in routers/banking.py was for a saved column mapping, so a mis-import stayed in
the register for ever and its lines kept surfacing in the match queue. Worse,
the CA could not simply import the right file over it: the import dedupes on a
unique (client_id, import_hash), so a soft delete would have made the re-import
skip every line.

The line is drawn on the LINES, not on the file. A statement nothing has been
posted, matched, ignored or reconciled from is an import; one that has is the
VOUCHER for those entries, which Companies Act s. 128(5) reaches expressly —
the same statute services/bank_erasure.py names for a bank account.

Against the previous code every test here fails: the endpoint did not exist.
"""
import pytest
from fastapi import HTTPException

import routers.banking as bank
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch, **txn_overrides):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [bank])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM})
    stmt = db.seed("bank_statements", {
        "firm_id": FIRM, "client_id": "CLI", "bank_name": "HDFC",
        "statement_from": "2025-04-01", "statement_to": "2025-04-30",
        "row_count": 3, "import_status": "pending"})
    for i in range(3):
        db.seed("bank_transactions", {
            "firm_id": FIRM, "client_id": "CLI", "statement_id": stmt["id"],
            "transaction_date": f"2025-04-0{i + 1}", "description": f"NEFT {i}",
            "debit_paise": 0, "credit_paise": 1000 * (i + 1),
            "import_hash": f"h{i}", "match_status": "unmatched",
            **(txn_overrides if i == 0 else {})})
    return db, stmt["id"]


def test_an_untouched_statement_and_all_its_lines_go(monkeypatch):
    db, stmt_id = _setup(monkeypatch)

    res = bank.delete_statement(stmt_id, CALLER)
    assert res["success"] is True
    assert res["data"]["transactions_removed"] == 3

    assert [s for s in db.rows("bank_statements") if s["id"] == stmt_id] == []
    assert [t for t in db.rows("bank_transactions") if t["statement_id"] == stmt_id] == []


def test_the_lines_go_too_so_the_right_file_can_be_imported_over_it(monkeypatch):
    """The import dedupes on a unique (client_id, import_hash). A line left
    behind under a deleted_at would silently skip its twin on the re-import —
    the exact failure this endpoint exists to end."""
    db, stmt_id = _setup(monkeypatch)
    bank.delete_statement(stmt_id, CALLER)
    assert [t.get("import_hash") for t in db.rows("bank_transactions")] == []


def test_a_posted_line_stops_the_deletion_and_the_statute_is_named(monkeypatch):
    _setup_db, stmt_id = _setup(monkeypatch, match_status="posted",
                                posted_journal_id="JE-1")
    with pytest.raises(HTTPException) as exc:
        bank.delete_statement(stmt_id, CALLER)
    assert exc.value.status_code == 422
    assert "128(5)" in exc.value.detail
    assert "1 already posted" in exc.value.detail


def test_a_reconciled_line_stops_the_deletion(monkeypatch):
    _db, stmt_id = _setup(monkeypatch, reconciliation_id="REC-1")
    with pytest.raises(HTTPException) as exc:
        bank.delete_statement(stmt_id, CALLER)
    assert exc.value.status_code == 422
    assert "reconciliation" in exc.value.detail


def test_a_matched_or_ignored_line_stops_the_deletion(monkeypatch):
    """A decision was recorded against that line. Removing the statement would
    throw the decision away with it."""
    for status in ("matched", "ignored"):
        for mp in (pytest.MonkeyPatch(),):
            _db, stmt_id = _setup(mp, match_status=status)
            with pytest.raises(HTTPException) as exc:
                bank.delete_statement(stmt_id, CALLER)
            assert exc.value.status_code == 422
            assert "matched or ignored" in exc.value.detail
            mp.undo()


def test_nothing_is_removed_when_the_deletion_is_refused(monkeypatch):
    db, stmt_id = _setup(monkeypatch, match_status="posted")
    with pytest.raises(HTTPException):
        bank.delete_statement(stmt_id, CALLER)
    assert len([s for s in db.rows("bank_statements") if s["id"] == stmt_id]) == 1
    assert len([t for t in db.rows("bank_transactions") if t["statement_id"] == stmt_id]) == 3


def test_the_whole_statement_and_every_line_reach_the_audit_log(monkeypatch):
    """The log is what is immutable, not the row — migrations 275/276's rule
    for a journal deletion, and the reason a hard delete is acceptable here."""
    db = FakeDB()
    wire_e2e(monkeypatch, db, [bank])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    logged = {}
    monkeypatch.setattr(bank, "log_event",
                        lambda *a, **k: logged.update({"args": a, "kw": k}))
    db.seed("clients", {"id": "CLI", "firm_id": FIRM})
    stmt = db.seed("bank_statements", {"firm_id": FIRM, "client_id": "CLI",
                                       "bank_name": "HDFC", "statement_to": "2025-04-30"})
    db.seed("bank_transactions", {"firm_id": FIRM, "client_id": "CLI",
                                  "statement_id": stmt["id"], "description": "NEFT",
                                  "credit_paise": 5000, "match_status": "unmatched"})

    bank.delete_statement(stmt["id"], CALLER)
    assert logged["args"][1:4] == ("bank_statement", stmt["id"], "delete")
    assert logged["kw"]["old_data"]["bank_name"] == "HDFC"
    assert logged["kw"]["metadata"]["transaction_count"] == 1
    assert logged["kw"]["metadata"]["transactions"][0]["description"] == "NEFT"


def test_another_firms_statement_is_not_found(monkeypatch):
    db, stmt_id = _setup(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        bank.delete_statement(stmt_id, {**CALLER, "firm_id": "FIRM-B"})
    assert exc.value.status_code == 404
    assert len(db.rows("bank_statements")) == 1


def test_an_unassigned_caller_cannot_reach_it(monkeypatch):
    """Row-addressed with no client_id in the request, so the mount guard never
    fires. core.authz reads its own _USE_MOCK at import and short-circuits to
    True, so what is pinned here is that the endpoint goes through the router's
    own scope helper and removes nothing when it refuses."""
    db, stmt_id = _setup(monkeypatch)

    def _refuse(user, client_id):
        raise HTTPException(status_code=404, detail="Not found")
    monkeypatch.setattr(bank, "assert_client_access", _refuse)

    with pytest.raises(HTTPException) as exc:
        bank.delete_statement(stmt_id, CALLER)
    assert exc.value.status_code == 404
    assert len(db.rows("bank_statements")) == 1
    assert len(db.rows("bank_transactions")) == 3
