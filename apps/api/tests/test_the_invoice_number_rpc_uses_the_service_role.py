"""
sweep-misc-tools-06 (the invoice-numbering half) — "Raise Invoice" could not
mint an invoice number in production at all.

WHAT WAS WRONG
    invoice_repository.generate_next_invoice_number called the atomic
    `next_invoice_number` RPC (migration 124) through `_get_db()`, which is
    `core.supabase_client.get_supabase()` — the per-user, RLS-enforced client
    under USE_USER_JWT (render.yaml's production default). Migration 124
    REVOKEs EXECUTE on that SECURITY DEFINER function from `authenticated` and
    grants it only to `service_role`, because it mutates another firm's
    counter row and must not be directly callable. So every live invoice-
    numbering call failed with a permission-denied APIError, which
    routers/invoices.py's bare `except Exception -> 400 str(e)` turned into a
    raw Postgres error string shown to the CA as the reason the invoice could
    not be raised.

WHAT THIS TEST HOLDS
    The RPC is reached through get_service_supabase(), never get_supabase() —
    same shape as
    test_staff_identity_is_written_as_the_service_for_the_callers_firm_only.py:
    get_supabase is wired to raise, so a call still reaching it fails loudly
    here instead of silently in production.
"""
import pytest

import core.supabase_client as sc
import repositories.invoice_repository as ir


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeRpc:
    def __init__(self, calls, seq):
        self._calls = calls
        self._seq = seq

    def execute(self):
        return _FakeResult(self._seq)


class _FakeServiceDb:
    def __init__(self, seq: int):
        self.seq = seq
        self.rpc_calls: list[tuple[str, dict]] = []

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return _FakeRpc(self.rpc_calls, self.seq)


@pytest.fixture
def wired(monkeypatch):
    monkeypatch.setattr(ir, "_USE_MOCK", False)
    fake = _FakeServiceDb(seq=7)

    def _downgraded(*_a, **_k):
        raise AssertionError(
            "invoice_repository reached the RPC through the downgraded "
            "per-user client (get_supabase) instead of get_service_supabase")

    monkeypatch.setattr(sc, "get_service_supabase", lambda: fake)
    monkeypatch.setattr(sc, "get_supabase", _downgraded)
    return fake


FIRM = "firm-inv-rpc-test"


def test_the_rpc_is_called_through_the_service_role_client(wired):
    number = ir.invoice_repo.generate_next_invoice_number(
        FIRM, current_date="2026-09-15")

    assert wired.rpc_calls == [("next_invoice_number", {"p_firm_id": FIRM})]
    # Fiscal year for a September date is the calendar year it falls in
    # (Apr 1 start), and the default prefix/padding are CF-YYYY-NNN.
    assert number == "CF-2026-007"


def test_a_non_integer_rpc_result_falls_back_to_one(monkeypatch):
    monkeypatch.setattr(ir, "_USE_MOCK", False)
    fake = _FakeServiceDb(seq=None)
    monkeypatch.setattr(sc, "get_service_supabase", lambda: fake)

    number = ir.invoice_repo.generate_next_invoice_number(
        FIRM, current_date="2026-09-15")

    assert number == "CF-2026-001"
