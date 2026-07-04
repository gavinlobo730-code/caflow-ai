"""
R2.12 fix phase — Python-level unit tests for two adversarial-review findings
that don't require a real database:

  1. _is_missing_rpc_function (services/receipt_service.py) must recognise a
     genuinely-missing settle_receipt_atomic function WITHOUT misclassifying
     the function's OWN legitimate business-rule errors (invoice-not-found,
     exceeds-outstanding) as "migration not applied" — the old bare
     substring check on the function's own name collided with those
     messages, since they are themselves prefixed with that name.
  2. create_foreign_receipt's per-invoice CAS update previously made a
     SINGLE attempt with no retry (immediate 409 on any concurrent write) —
     a materially weaker guarantee than the plain-INR path's 6-attempt retry
     loop the R2.12 atomic rewrite replaced. This proves the added retry
     loop actually retries instead of failing on the first collision.

Runs everywhere (mock-mode style, no real database).
"""
from __future__ import annotations

import os

os.environ.pop("SUPABASE_URL", None)

from types import SimpleNamespace

import pytest


# ─── 1. _is_missing_rpc_function must not misfire on the function's own errors ──

class TestIsMissingRpcFunction:
    def test_pgrst202_is_missing_function(self):
        from services.receipt_service import _is_missing_rpc_function
        err = RuntimeError("PGRST202: Could not find the function public.settle_receipt_atomic in the schema cache")
        assert _is_missing_rpc_function(err) is True

    def test_raw_postgres_does_not_exist_is_missing_function(self):
        from services.receipt_service import _is_missing_rpc_function
        err = RuntimeError("function settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb) does not exist")
        assert _is_missing_rpc_function(err) is True

    def test_own_invoice_not_found_error_is_not_misclassified(self):
        """CONFIRMED finding: this exact message (the SQL function's own
        RAISE EXCEPTION, prefixed with its own name) used to satisfy the old
        bare `"settle_receipt_atomic" in msg` check and get misdiagnosed as
        'RPC not found'."""
        from services.receipt_service import _is_missing_rpc_function
        err = RuntimeError("settle_receipt_atomic: invoice abc-123 is not part of this client's books")
        assert _is_missing_rpc_function(err) is False

    def test_own_exceeds_outstanding_error_is_not_misclassified(self):
        from services.receipt_service import _is_missing_rpc_function
        err = RuntimeError("settle_receipt_atomic: allocation to invoice abc-123 (50000 paise) exceeds its outstanding")
        assert _is_missing_rpc_function(err) is False

    def test_unrelated_error_is_not_missing_function(self):
        from services.receipt_service import _is_missing_rpc_function
        assert _is_missing_rpc_function(RuntimeError("connection reset by peer")) is False


class TestSettleReceiptViaAtomicRpcErrorHandling:
    """End-to-end through _settle_receipt_via_atomic_rpc: a legitimate
    business-rule rejection from the RPC must propagate as itself (or a
    clearly-labelled error), never as the misleading 'migration not applied'
    RuntimeError."""

    def _fake_db_raising(self, error):
        class _RaisingRpc:
            def execute(self):
                raise error

        class _DB:
            def rpc(self, _fn, _params):
                return _RaisingRpc()

        return _DB()

    def test_genuine_business_rule_error_does_not_become_missing_migration_error(self, monkeypatch):
        import services.receipt_service as mod
        import services.phase2_journal_service as journal_mod

        monkeypatch.setattr(
            journal_mod.phase2_journal_service, "receipt_journal_lines",
            lambda *a, **k: [{"account_id": "acc-1", "debit_paise": 100, "credit_paise": 0}],
        )
        db = self._fake_db_raising(
            RuntimeError("settle_receipt_atomic: allocation to invoice X (100 paise) exceeds its outstanding")
        )
        receipt_payload = {
            "id": "r1", "receipt_no": "RCPT-1", "receipt_date": "2026-04-05", "amount_paise": 100,
        }
        with pytest.raises(RuntimeError) as exc_info:
            mod._settle_receipt_via_atomic_rpc(db, "firm-1", "client-1", receipt_payload, [], {"id": "u1"})
        assert "exceeds its outstanding" in str(exc_info.value)
        assert "migration" not in str(exc_info.value).lower()

    def test_genuinely_missing_function_raises_clear_diagnostic(self, monkeypatch):
        import services.receipt_service as mod
        import services.phase2_journal_service as journal_mod

        monkeypatch.setattr(
            journal_mod.phase2_journal_service, "receipt_journal_lines",
            lambda *a, **k: [{"account_id": "acc-1", "debit_paise": 100, "credit_paise": 0}],
        )
        db = self._fake_db_raising(RuntimeError("PGRST202: Could not find the function"))
        receipt_payload = {
            "id": "r1", "receipt_no": "RCPT-1", "receipt_date": "2026-04-05", "amount_paise": 100,
        }
        with pytest.raises(RuntimeError) as exc_info:
            mod._settle_receipt_via_atomic_rpc(db, "firm-1", "client-1", receipt_payload, [], {"id": "u1"})
        assert "migration" in str(exc_info.value).lower()


# ─── 2. create_foreign_receipt's CAS must retry, not fail on the first race ──

class _Table:
    """Minimal fake supabase-py query builder for one table. `on_execute` is
    called with (verb, filters, payload) and returns the SimpleNamespace to
    hand back from .execute()."""

    def __init__(self, name, on_execute):
        self.name = name
        self._on_execute = on_execute
        self._verb = "select"
        self._payload = None
        self._filters = {}

    def select(self, *_a, **_k):
        self._verb = "select"
        return self

    def insert(self, payload):
        self._verb = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._verb = "update"
        self._payload = payload
        return self

    def eq(self, k, v):
        self._filters[k] = v
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return self._on_execute(self.name, self._verb, dict(self._filters), self._payload)


def test_create_foreign_receipt_cas_retries_instead_of_failing_immediately(monkeypatch):
    """CONFIRMED finding: create_foreign_receipt's invoice settlement CAS
    previously made exactly one attempt (no retry loop at all), immediately
    raising 409 on any concurrent write — a materially weaker guarantee than
    the plain-INR legacy path's 6-attempt retry the R2.12 atomic rewrite
    replaced. This proves a first stale CAS attempt now retries (with a
    fresh read) instead of failing outright."""
    import services.receipt_service as mod
    import domain.currency.policy as policy_mod
    import domain.currency.currency_service as currency_service_mod
    import services.phase2_journal_service as journal_mod

    monkeypatch.setattr(policy_mod, "resolve_currency_policy", lambda firm, client: SimpleNamespace(active=True))
    monkeypatch.setattr(
        currency_service_mod, "get_currency",
        lambda db, ccy: {"minor_unit": 2, "is_active": True},
    )
    monkeypatch.setattr(journal_mod.phase2_journal_service, "_find_account", lambda *a, **k: "acc-1")
    monkeypatch.setattr(journal_mod.phase2_journal_service, "_create_journal", lambda **k: "journal-1")

    INV_ID = "inv-1"
    # The invoice as it exists "live" in the DB by the time any read in this
    # test happens — simulates a concurrent writer having already landed
    # paid_paise=160000/paid_txn=2000 before this receipt even starts.
    live_invoice = {
        "id": INV_ID, "txn_currency": "USD", "exchange_rate": "80", "total_paise": 800000,
        "paid_paise": 160000, "paid_txn": 2000, "credited_paise": 0, "txn_total": 10000,
    }
    state = {"cas_attempts": 0}

    def on_execute(name, verb, _filters, payload):
        if name == "firms":
            return SimpleNamespace(data=[{"id": "firm-1", "multi_currency_entitled": True}])
        if name == "clients":
            return SimpleNamespace(data=[{"id": "CLI", "functional_currency": "INR", "multi_currency_enabled": True}])
        if name == "client_sales_invoices":
            if verb == "update":
                state["cas_attempts"] += 1
                # First attempt loses the race (0 rows matched); second succeeds.
                return SimpleNamespace(data=[] if state["cas_attempts"] == 1 else [{"id": INV_ID}])
            return SimpleNamespace(data=[live_invoice])
        if name == "receipts":
            return SimpleNamespace(data=[dict(payload)])
        return SimpleNamespace(data=[])

    class _DB:
        def table(self, name):
            return _Table(name, on_execute)

    result = mod.create_foreign_receipt(
        firm_id="firm-1",
        data={
            "client_id": "CLI", "customer_id": "cust-1", "currency": "USD",
            "receipt_date": "2026-04-05", "amount_paise": 4000, "exchange_rate": "80",
            "allocations": [{"sales_invoice_id": INV_ID, "allocated_paise": 4000}],
        },
        actor={"id": "u1", "auth_user_id": "u1", "email": "a@b.com"},
        db=_DB(),
    )

    assert state["cas_attempts"] == 2, "must retry after a stale first CAS instead of failing immediately"
    assert result["journal_entry_id"] == "journal-1"


def test_create_foreign_receipt_cas_gives_up_after_max_attempts(monkeypatch):
    """The retry loop must still eventually fail loudly (409) rather than
    retry forever, when every attempt loses the race."""
    from fastapi import HTTPException
    import services.receipt_service as mod
    import domain.currency.policy as policy_mod
    import domain.currency.currency_service as currency_service_mod
    import services.phase2_journal_service as journal_mod

    monkeypatch.setattr(policy_mod, "resolve_currency_policy", lambda firm, client: SimpleNamespace(active=True))
    monkeypatch.setattr(
        currency_service_mod, "get_currency",
        lambda db, ccy: {"minor_unit": 2, "is_active": True},
    )
    monkeypatch.setattr(journal_mod.phase2_journal_service, "_find_account", lambda *a, **k: "acc-1")
    monkeypatch.setattr(journal_mod.phase2_journal_service, "_create_journal", lambda **k: "journal-1")

    INV_ID = "inv-1"
    live_invoice = {
        "id": INV_ID, "txn_currency": "USD", "exchange_rate": "80", "total_paise": 800000,
        "paid_paise": 0, "paid_txn": 0, "credited_paise": 0, "txn_total": 10000,
    }
    state = {"cas_attempts": 0}

    def on_execute(name, verb, _filters, payload):
        if name == "firms":
            return SimpleNamespace(data=[{"id": "firm-1", "multi_currency_entitled": True}])
        if name == "clients":
            return SimpleNamespace(data=[{"id": "CLI", "functional_currency": "INR", "multi_currency_enabled": True}])
        if name == "client_sales_invoices":
            if verb == "update":
                state["cas_attempts"] += 1
                return SimpleNamespace(data=[])   # every attempt loses the race
            return SimpleNamespace(data=[live_invoice])
        if name == "receipts":
            return SimpleNamespace(data=[dict(payload)])
        return SimpleNamespace(data=[])

    class _DB:
        def table(self, name):
            return _Table(name, on_execute)

    with pytest.raises(HTTPException) as exc_info:
        mod.create_foreign_receipt(
            firm_id="firm-1",
            data={
                "client_id": "CLI", "customer_id": "cust-1", "currency": "USD",
                "receipt_date": "2026-04-05", "amount_paise": 4000, "exchange_rate": "80",
                "allocations": [{"sales_invoice_id": INV_ID, "allocated_paise": 4000}],
            },
            actor={"id": "u1", "auth_user_id": "u1", "email": "a@b.com"},
            db=_DB(),
        )

    assert exc_info.value.status_code == 409
    assert state["cas_attempts"] == 6
