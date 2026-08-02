"""
Task #235 — audit-pass-3 banking gaps (round 2): assignment scoping on the
banking router, a settle_on_post double-settlement race, a reconcile/
unreconcile claim race, and a cross-client matching-rule leak (the rule leak
itself is covered by test_bank_matching.py::test_queue_does_not_apply_another_clients_rule).

Assignment-scoping tests mirror the established pattern in
test_r231_cross_tenant_isolation.py: monkeypatch core.authz onto the real
(non-mock) enforcement path with a fake client-ownership resolver, then call
the router functions directly.
"""
import pytest
from fastapi import HTTPException

import core.authz as authz
import routers.banking as banking_router
from models.banking import BankAccountIn, StatementImportIn, StatementImportRow, MatchingRuleIn, ReconciliationCreateIn

PARTNER_F1 = {"firm_id": "F1", "role": "Partner", "auth_user_id": "p1", "id": "u1", "email": "p1@f1.test"}


@pytest.fixture
def enforced(monkeypatch):
    """Force the real (non-mock) client-ownership enforcement path. C1
    belongs to F1 (every fixture user's firm); C-OTHER belongs to F2."""
    monkeypatch.setattr(authz, "_USE_MOCK", False)

    def fake_belongs(client_id, firm_id):
        if client_id == "C-OTHER":
            return firm_id == "F2"
        return firm_id == "F1"
    monkeypatch.setattr(authz, "_client_belongs_to_firm", fake_belongs)
    yield


# ── Router assignment scoping ────────────────────────────────────────────────
# banking.py's own _db() returns None without SUPABASE_URL (this test env), so
# these exercise the assert_client_access guard added BEFORE the db-dependent
# code path -- same precedent as test_r231's relationships.py tests.

def test_list_bank_accounts_rejects_another_firms_client(enforced):
    with pytest.raises(HTTPException) as ei:
        banking_router.list_bank_accounts(client_id="C-OTHER", current_user=PARTNER_F1)
    assert ei.value.status_code == 404


def test_list_bank_accounts_accepts_own_firms_client(enforced):
    result = banking_router.list_bank_accounts(client_id="C1", current_user=PARTNER_F1)
    assert result["success"] is True


def test_create_bank_account_rejects_another_firms_client(enforced):
    body = BankAccountIn(client_id="C-OTHER", bank_name="Sneaky Bank", account_no="0001")
    with pytest.raises(HTTPException) as ei:
        banking_router.create_bank_account(body, current_user=PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_bank_account_accepts_own_firms_client(enforced):
    body = BankAccountIn(client_id="C1", bank_name="Legit Bank", account_no="0001")
    result = banking_router.create_bank_account(body, current_user=PARTNER_F1)
    assert result["success"] is True


def test_import_statement_rejects_another_firms_client(enforced):
    body = StatementImportIn(
        client_id="C-OTHER", bank_name="Bank",
        rows=[StatementImportRow(transaction_date="2026-04-01", description="x",
                                  debit_paise=0, credit_paise=100, balance_paise=100)],
    )
    with pytest.raises(HTTPException) as ei:
        banking_router.import_statement(body, current_user=PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_reconciliation_rejects_another_firms_client(enforced):
    body = ReconciliationCreateIn(
        client_id="C-OTHER", bank_account_id="ba-1",
        statement_start_date="2026-04-01", statement_end_date="2026-04-30",
    )
    with pytest.raises(HTTPException) as ei:
        banking_router.create_reconciliation(body, current_user=PARTNER_F1)
    assert ei.value.status_code == 404


def test_list_rules_rejects_another_firms_client(enforced):
    with pytest.raises(HTTPException) as ei:
        banking_router.list_rules(client_id="C-OTHER", current_user=PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_rule_rejects_another_firms_client(enforced):
    body = MatchingRuleIn(client_id="C-OTHER", rule_name="Sneaky Rule",
                          description_pattern="NEFT", suggested_category="Expense")
    with pytest.raises(HTTPException) as ei:
        banking_router.create_rule(body, current_user=PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_rule_accepts_own_firms_client(enforced):
    body = MatchingRuleIn(client_id="C1", rule_name="Legit Rule",
                          description_pattern="NEFT", suggested_category="Expense")
    result = banking_router.create_rule(body, current_user=PARTNER_F1)
    assert result["success"] is True


# ── Optional-client_id list endpoints: M2 assignment-scope fallback ─────────

def test_scope_rows_asserts_when_client_id_given(enforced):
    with pytest.raises(HTTPException) as ei:
        banking_router._scope_rows(PARTNER_F1, "C-OTHER", [{"client_id": "C-OTHER"}])
    assert ei.value.status_code == 404
    assert banking_router._scope_rows(PARTNER_F1, "C1", [{"client_id": "C1"}]) == [{"client_id": "C1"}]


def test_scope_rows_filters_by_assignment_when_no_client_id(monkeypatch):
    """Firm-wide view (no client_id) must narrow to the caller's assigned
    clients, not silently return every client in the firm's banking data."""
    monkeypatch.setattr(authz, "is_firmwide", lambda user: False)
    monkeypatch.setattr(authz, "_USE_MOCK", False)
    monkeypatch.setattr(authz, "assigned_client_ids", lambda user: {"C1"})
    rows = [{"client_id": "C1", "id": "a"}, {"client_id": "C-OTHER", "id": "b"}]
    scoped = banking_router._scope_rows(PARTNER_F1, None, rows)
    assert scoped == [{"client_id": "C1", "id": "a"}]


# ── settle_on_post concurrency guard ─────────────────────────────────────────

def test_settle_on_post_does_not_double_settle_on_concurrent_call(monkeypatch):
    """Simulates the exact race: two near-simultaneous settle_on_post calls
    both read match_status as not-yet-posted before either write lands. The
    second caller's CAS-guarded UPDATE must find zero rows and must NOT
    re-run _settle (which would double-allocate paid_paise / double-grant
    party credit on an overpayment)."""
    import services.bank_posting_service as bps_mod
    from tests.e2e_harness import FakeDB

    db = FakeDB()
    db.seed("bank_transactions", {
        "id": "txn-1", "firm_id": "F1", "client_id": "C1",
        "match_status": "matched", "category": "sales_receipt",
        "matched_entity_type": "sales_invoice", "matched_entity_id": "inv-1",
        "debit_paise": 0, "credit_paise": 500000,
    })
    svc = bps_mod.bank_posting_service

    # First call: reads match_status="matched", claims it via CAS, proceeds to settle.
    monkeypatch.setattr(svc, "_settle", lambda *a, **k: {"settled": True})
    result1 = svc.settle_on_post(db, "F1", "txn-1", "je-1", actor_id="u1")
    assert result1 == {"settled": True}
    assert db.rows("bank_transactions")[0]["match_status"] == "posted"

    # Second call for the SAME transaction: since the row is now genuinely
    # "posted", the fast idempotency check at the top already catches this in
    # the non-concurrent case -- but the point under test is the CAS guard
    # itself, exercised directly: a call whose _get_txn snapshot is stale
    # (reads "matched", not yet aware of the first call's write) must still
    # find the real row already changed and get zero rows back from the
    # claiming UPDATE, never reaching _settle a second time.
    calls = {"count": 0}
    def _settle_spy(*a, **k):
        calls["count"] += 1
        return {"settled": True}
    monkeypatch.setattr(svc, "_settle", _settle_spy)
    monkeypatch.setattr(svc, "_get_txn", lambda db, firm_id, txn_id: {
        "id": "txn-1", "firm_id": "F1", "client_id": "C1",
        "match_status": "matched",  # stale snapshot -- real row is already "posted"
        "category": "sales_receipt", "matched_entity_type": "sales_invoice",
        "matched_entity_id": "inv-1", "debit_paise": 0, "credit_paise": 500000,
    })
    result2 = svc.settle_on_post(db, "F1", "txn-1", "je-2", actor_id="u1")
    assert result2 is None
    assert calls["count"] == 0  # _settle must never run for the race loser
    assert db.rows("bank_transactions")[0]["posted_journal_id"] == "je-1"  # unchanged


# ── reconcile / unreconcile concurrency guard ────────────────────────────────

def test_reconcile_rejects_when_transaction_claimed_between_read_and_write(monkeypatch):
    """Simulates two overlapping reconciliation sessions racing to claim the
    same transaction: session B's pre-check reads a stale (unclaimed)
    snapshot, but by the time its write runs the real row already belongs to
    session A. The CAS-guarded update must find zero rows and raise 409
    instead of silently overwriting session A's claim."""
    import services.bank_reconciliation_service as brs_mod
    from tests.e2e_harness import FakeDB

    db = FakeDB()
    db.seed("bank_accounts", {"id": "ba-1", "firm_id": "F1", "client_id": "C1",
                               "bank_name": "HDFC", "account_no": "0001"})
    db.seed("bank_transactions", {
        "id": "txn-1", "firm_id": "F1", "bank_account_id": "ba-1",
        "transaction_date": "2026-04-10", "match_status": "posted",
        "posted_journal_id": "je-1", "reconciliation_id": "recon-A",  # already claimed
        "reconciled": True,
    })
    svc = brs_mod.bank_reconciliation_service
    monkeypatch.setattr(brs_mod.timeline_service, "log", lambda *a, **k: None)

    session_b = {
        "id": "recon-B", "firm_id": "F1", "client_id": "C1", "bank_account_id": "ba-1",
        "period_start": "2026-04-01", "period_end": "2026-04-30", "status": "open",
    }
    monkeypatch.setattr(svc, "_get_session", lambda db, firm_id, recon_id: session_b)
    monkeypatch.setattr(svc, "_require_mutable", lambda session: None)
    # Stale pre-check snapshot: session B's read sees the transaction as UNCLAIMED
    # (reconciliation_id=None), even though the real FakeDB row already has it
    # claimed by session A -- this is the race window.
    monkeypatch.setattr(svc, "_index_account_txns", lambda db, firm_id, session: {
        "txn-1": {**db.rows("bank_transactions")[0], "reconciliation_id": None},
    })

    with pytest.raises(HTTPException) as ei:
        svc.reconcile(db, "F1", "recon-B", ["txn-1"], actor_id="u1")
    assert ei.value.status_code == 409
    # Session A's claim must survive untouched.
    assert db.rows("bank_transactions")[0]["reconciliation_id"] == "recon-A"


def test_unreconcile_rejects_when_transaction_already_moved(monkeypatch):
    """Same race for unreconcile: the pre-check's stale snapshot says the
    transaction still belongs to this session, but the real row has already
    moved (e.g. a concurrent unreconcile already cleared it, or a concurrent
    reconcile re-claimed it for a different session). The CAS-guarded update
    must find zero rows and raise 409 rather than silently succeeding."""
    import services.bank_reconciliation_service as brs_mod
    from tests.e2e_harness import FakeDB

    db = FakeDB()
    db.seed("bank_accounts", {"id": "ba-1", "firm_id": "F1", "client_id": "C1",
                               "bank_name": "HDFC", "account_no": "0001"})
    db.seed("bank_transactions", {
        "id": "txn-1", "firm_id": "F1", "bank_account_id": "ba-1",
        "transaction_date": "2026-04-10", "match_status": "posted",
        "posted_journal_id": "je-1", "reconciliation_id": None,  # already unreconciled
        "reconciled": False,
    })
    svc = brs_mod.bank_reconciliation_service
    monkeypatch.setattr(brs_mod.timeline_service, "log", lambda *a, **k: None)

    session_a = {
        "id": "recon-A", "firm_id": "F1", "client_id": "C1", "bank_account_id": "ba-1",
        "period_start": "2026-04-01", "period_end": "2026-04-30", "status": "in_progress",
    }
    monkeypatch.setattr(svc, "_get_session", lambda db, firm_id, recon_id: session_a)
    monkeypatch.setattr(svc, "_require_mutable", lambda session: None)
    # Stale pre-check snapshot: reads the transaction as still reconciled to
    # recon-A, even though the real row already has it cleared.
    monkeypatch.setattr(svc, "_index_account_txns", lambda db, firm_id, session: {
        "txn-1": {**db.rows("bank_transactions")[0], "reconciliation_id": "recon-A"},
    })

    with pytest.raises(HTTPException) as ei:
        svc.unreconcile(db, "F1", "recon-A", ["txn-1"], actor_id="u1")
    assert ei.value.status_code == 409
