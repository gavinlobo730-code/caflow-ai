"""
R2.12 fix phase — Python-level unit tests for two adversarial-review findings
that don't require a real database:

  1. _is_missing_rpc_function (services/receipt_service.py) must recognise a
     genuinely-missing settle_receipt_atomic function WITHOUT misclassifying
     the function's OWN legitimate business-rule errors (invoice-not-found,
     exceeds-outstanding) as "migration not applied" — the old bare
     substring check on the function's own name collided with those
     messages, since they are themselves prefixed with that name.
  2. create_foreign_receipt once made a SINGLE attempt at its per-invoice
     compare-and-set (immediate 409 on any concurrent write), then a retry
     loop per invoice. Since POST-A-095 (migration 781) the whole receipt is
     one database transaction that compares what was read of each invoice
     with the locked row and refuses the receipt if it moved. The guarantee
     kept here is the same one in the new shape: a receipt that lost the
     race is planned again from a FRESH read and sent again whole, and one
     that keeps losing is refused with a 409 in words after a fixed number
     of whole attempts, having written nothing.

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


# ─── 2. a foreign receipt that lost the race is planned again from a fresh read ──

class _Table:
    """Minimal fake supabase-py query builder for one table. `on_execute` is
    called with (name, verb, filters, payload) and returns the SimpleNamespace to
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

    # _next_receipt_seq reads the highest receipt_no back rather than
    # counting rows (SALES-04), so it filters and orders as well.
    def like(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def execute(self):
        return self._on_execute(self.name, self._verb, dict(self._filters), self._payload)


class _Moved(Exception):
    """The function's refusal of a receipt whose invoice moved after it was read, as the client surfaces it."""
    code = "RC001"

    def __init__(self):
        super().__init__("settle_receipt_atomic: invoice inv-1 changed while this receipt was being prepared")


def _foreign_world(monkeypatch, invoice, on_call):
    """A database double for one foreign receipt: `invoice` is the row every read returns AT THAT MOMENT (the test mutates it between
    attempts), `on_call(params)` is the receipt function. Returns (db, the list of every table write, the list of every function call)."""
    import domain.currency.currency_service as currency_service_mod
    import domain.currency.policy as policy_mod
    import services.phase2_journal_service as journal_mod

    monkeypatch.setattr(policy_mod, "resolve_currency_policy", lambda firm, client: SimpleNamespace(active=True))
    monkeypatch.setattr(currency_service_mod, "get_currency", lambda db, ccy: {"minor_unit": 2, "is_active": True})
    monkeypatch.setattr(journal_mod.phase2_journal_service, "_find_account", lambda *a, **k: "acc-1")

    writes, calls = [], []
    numbers_taken: list = []

    def on_execute(name, verb, _filters, payload):
        if verb != "select":
            writes.append((name, verb, payload))
        if name == "firms":
            return SimpleNamespace(data=[{"id": "firm-1", "multi_currency_entitled": True}])
        if name == "clients":
            return SimpleNamespace(data=[{"id": "CLI", "functional_currency": "INR", "multi_currency_enabled": True}])
        if name == "client_sales_invoices":
            return SimpleNamespace(data=[dict(invoice)])
        if name == "receipts":
            # the read of the series' last number (`numbering.next_sequence`): the receipts that exist AT THAT MOMENT
            return SimpleNamespace(data=[{"receipt_no": n} for n in numbers_taken])
        return SimpleNamespace(data=[])

    class _Rpc:
        def __init__(self, params):
            self._params = params

        def execute(self):
            calls.append(self._params)
            return on_call(self._params)

    class _DB:
        def table(self, name):
            return _Table(name, on_execute)

        def rpc(self, fn, params):
            if fn in ("period_closure_reason", "period_lock_reason"):
                return SimpleNamespace(execute=lambda: SimpleNamespace(data=None))        # the period is open
            assert fn == "settle_receipt_atomic", fn
            return _Rpc(params)

    db = _DB()
    db.numbers_taken = numbers_taken
    return db, writes, calls


_RECEIPT = {
    "client_id": "CLI", "customer_id": "cust-1", "currency": "USD",
    "receipt_date": "2026-04-05", "amount_paise": 4000, "exchange_rate": "80",
    "allocations": [{"sales_invoice_id": "inv-1", "allocated_paise": 4000}],
}
_ACTOR = {"id": "u1", "auth_user_id": "u1", "email": "a@b.com"}


def test_a_foreign_receipt_that_lost_the_race_is_planned_again_from_a_fresh_read(monkeypatch):
    """Another receipt lands on the invoice between this one's read and the function's lock. The function refuses the whole receipt
    (nothing written); the service reads the invoice again, plans again and sends the whole receipt again, with the same number and id
    and with expectations that are the SECOND read's."""
    import services.receipt_service as mod

    invoice = {"id": "inv-1", "customer_id": "cust-1", "status": "issued", "txn_currency": "USD", "exchange_rate": "80", "total_paise": 800000,
               "paid_paise": 0, "paid_txn": 0, "credited_paise": 0, "txn_total": 10000}

    def on_call(params):
        if len(calls) == 1:
            # the concurrent receipt: 20.00 USD lands before this one's lock
            invoice.update(paid_paise=160000, paid_txn=2000, status="partially_paid")
            raise _Moved()
        return SimpleNamespace(data={"receipt_id": params["p_receipt"]["id"], "journal_entry_id": "journal-1",
                                     "receipt": {}, "allocations": [], "realized_fx_paise": 0})

    db, writes, calls = _foreign_world(monkeypatch, invoice, on_call)
    result = mod.create_foreign_receipt(firm_id="firm-1", data=dict(_RECEIPT), actor=_ACTOR, db=db)

    assert len(calls) == 2, "must plan again after a moved invoice instead of failing immediately"
    first, second = (c["p_allocations"][0] for c in calls)
    assert (first["expect_paid_paise"], first["expect_paid_txn"]) == (0, 0)
    assert (second["expect_paid_paise"], second["expect_paid_txn"]) == (160000, 2000), "the second attempt did not read the invoice again"
    assert calls[0]["p_receipt"]["id"] == calls[1]["p_receipt"]["id"]
    assert all(c["p_journal_entry"]["reference_no"] == c["p_receipt"]["receipt_no"] for c in calls)
    assert all(c["p_journal_entry"]["source_id"] == c["p_receipt"]["id"] for c in calls)
    assert result["journal_entry_id"] == "journal-1"
    assert writes == [], f"the service wrote a table itself, outside the receipt's transaction: {writes}"


def test_two_receipts_that_took_the_same_number_the_second_takes_the_next_one_and_is_recorded(monkeypatch):
    """The commonest race: two receipts of one client recorded at the same moment both read the same last number. The second is refused
    for the duplicate before any invoice is looked at (the function wrote nothing); it reads the series again, takes the next number and
    is sent again whole. Before this it was a 409 asking the person to retry, and the re-plan below never ran for that race."""
    import services.receipt_service as mod

    invoice = {"id": "inv-1", "customer_id": "cust-1", "status": "issued", "txn_currency": "USD", "exchange_rate": "80", "total_paise": 800000,
               "paid_paise": 0, "paid_txn": 0, "credited_paise": 0, "txn_total": 10000}

    def on_call(params):
        if len(calls) == 1:
            db.numbers_taken.append(params["p_receipt"]["receipt_no"])        # the other receipt committed under this number first
            raise RuntimeError('duplicate key value violates unique constraint "uq_receipts_client_receipt_no"')
        return SimpleNamespace(data={"receipt_id": params["p_receipt"]["id"], "journal_entry_id": "journal-1",
                                     "receipt": {}, "allocations": [], "realized_fx_paise": 0})

    db, writes, calls = _foreign_world(monkeypatch, invoice, on_call)
    result = mod.create_foreign_receipt(firm_id="firm-1", data=dict(_RECEIPT), actor=_ACTOR, db=db)

    assert len(calls) == 2
    first, second = (c["p_receipt"]["receipt_no"] for c in calls)
    assert first.endswith("-0001") and second.endswith("-0002") and first[:-4] == second[:-4], (first, second)
    assert calls[1]["p_journal_entry"]["reference_no"] == second and second in calls[1]["p_journal_entry"]["narration"]
    assert result["receipt_no"] == second and result["journal_entry_id"] == "journal-1"
    assert writes == []


def test_a_foreign_receipt_whose_number_keeps_being_taken_by_other_receipts_is_refused_with_the_collision_sentence(monkeypatch):
    """Every attempt loses its number to another receipt (the series moves on each time): after the last attempt the person is asked
    to try again, which can work."""
    from fastapi import HTTPException
    import services.receipt_service as mod

    invoice = {"id": "inv-1", "customer_id": "cust-1", "status": "issued", "txn_currency": "USD", "exchange_rate": "80", "total_paise": 800000,
               "paid_paise": 0, "paid_txn": 0, "credited_paise": 0, "txn_total": 10000}

    def on_call(params):
        db.numbers_taken.append(params["p_receipt"]["receipt_no"])
        raise RuntimeError('duplicate key value violates unique constraint "uq_receipts_client_receipt_no"')

    db, writes, calls = _foreign_world(monkeypatch, invoice, on_call)
    with pytest.raises(HTTPException) as exc_info:
        mod.create_foreign_receipt(firm_id="firm-1", data=dict(_RECEIPT), actor=_ACTOR, db=db)
    assert exc_info.value.status_code == 409 and "numbering collision" in exc_info.value.detail
    assert len(calls) == mod.FOREIGN_RECEIPT_ATTEMPTS and writes == []
    assert len({c["p_receipt"]["receipt_no"] for c in calls}) == mod.FOREIGN_RECEIPT_ATTEMPTS


def test_a_number_refused_twice_running_is_carried_by_something_that_is_not_a_receipt_and_the_person_is_told_so(monkeypatch):
    """A journal typed with the reference the receipt would take: the series of RECEIPTS still offers that number, so taking it again
    cannot work. The second refusal of the same number stops the attempts and names the clash; "please retry" would be untrue."""
    from fastapi import HTTPException
    import services.receipt_service as mod

    invoice = {"id": "inv-1", "customer_id": "cust-1", "status": "issued", "txn_currency": "USD", "exchange_rate": "80", "total_paise": 800000,
               "paid_paise": 0, "paid_txn": 0, "credited_paise": 0, "txn_total": 10000}

    def on_call(_params):
        raise RuntimeError('duplicate key value violates unique constraint "uq_journal_entries_client_reference_date"')

    db, writes, calls = _foreign_world(monkeypatch, invoice, on_call)
    with pytest.raises(HTTPException) as exc_info:
        mod.create_foreign_receipt(firm_id="firm-1", data=dict(_RECEIPT), actor=_ACTOR, db=db)
    assert exc_info.value.status_code == 409
    number = calls[0]["p_receipt"]["receipt_no"]
    assert exc_info.value.detail == mod.receipt_number_carried_elsewhere(number)
    assert number in exc_info.value.detail and "Nothing was recorded" in exc_info.value.detail and "retry" not in exc_info.value.detail
    assert len(calls) == 2 and writes == [], "it went on taking a number that cannot be taken"


def test_the_rupees_a_part_settlement_would_relieve_must_still_be_owed_and_the_refusal_says_so_in_rupees(monkeypatch):
    """A credit note on a foreign invoice lowers what is owed in rupees and not the foreign outstanding. A part settlement at the
    invoice's own rate can then relieve more rupees than are left; the database function refuses that in a log's words, so the plan
    refuses it first, in a person's, and the function is never called."""
    from fastapi import HTTPException
    import services.receipt_service as mod

    # 100.00 USD at 80 = 8,000.00; a credit note of 5,000.00 leaves 3,000.00 owed in rupees and still 100.00 USD outstanding
    invoice = {"id": "inv-1", "customer_id": "cust-1", "status": "issued", "txn_currency": "USD", "exchange_rate": "80", "total_paise": 800000,
               "paid_paise": 0, "paid_txn": 0, "credited_paise": 500000, "debit_note_paise": 0, "txn_total": 10000}
    db, writes, calls = _foreign_world(monkeypatch, invoice, lambda _p: None)
    with pytest.raises(HTTPException) as exc_info:
        mod.create_foreign_receipt(firm_id="firm-1", data={**_RECEIPT, "amount_paise": 5000,
                                   "allocations": [{"sales_invoice_id": "inv-1", "allocated_paise": 5000}]}, actor=_ACTOR, db=db)
    assert exc_info.value.status_code == 422
    assert "left to settle in rupees" in exc_info.value.detail and "A credit note has reduced what is owed." in exc_info.value.detail
    assert "₹3,000.00" in exc_info.value.detail and "₹4,000.00" in exc_info.value.detail, exc_info.value.detail
    assert calls == [] and writes == []


def test_the_function_never_raises_a_state_the_gateway_re_runs_by_itself():
    """PostgREST runs a request in a transaction that its library re-runs when the server answers serialization_failure (40001) or
    deadlock_detected (40P01). The receipt function's "the invoice moved" refusal is permanent for its payload, so it carries the
    function's own state, which the service matches."""
    import re
    from pathlib import Path
    import services.receipt_service as mod
    from tests import _receipt_function_source as src

    name, body = src.body_definitions(src.migration_files())[-1]
    states = set(re.findall(r"ERRCODE\s*=\s*'([0-9A-Z]{5})'", body))
    assert mod.INVOICE_MOVED_STATE in states, (name, states)
    assert not states & {"40001", "40P01"}, f"{name} raises a state PostgREST re-runs by itself: {states}"
    assert not mod.INVOICE_MOVED_STATE.startswith(("PT", "40", "08", "53", "57")), "a state the gateway or the driver gives a meaning of its own"
    assert Path(mod.__file__).read_text(encoding="utf-8").count('"40001"') == 0


def test_a_foreign_receipt_that_keeps_losing_is_refused_in_words_having_written_nothing(monkeypatch):
    """The retry is bounded: when every attempt finds the invoice moved, the receipt is refused with a 409 that says what happened and
    what to do, after exactly FOREIGN_RECEIPT_ATTEMPTS whole attempts, and the service has written no table."""
    from fastapi import HTTPException
    import services.receipt_service as mod

    invoice = {"id": "inv-1", "customer_id": "cust-1", "status": "issued", "txn_currency": "USD", "exchange_rate": "80", "total_paise": 800000,
               "paid_paise": 0, "paid_txn": 0, "credited_paise": 0, "txn_total": 10000}

    def on_call(_params):
        raise _Moved()

    db, writes, calls = _foreign_world(monkeypatch, invoice, on_call)
    with pytest.raises(HTTPException) as exc_info:
        mod.create_foreign_receipt(firm_id="firm-1", data=dict(_RECEIPT), actor=_ACTOR, db=db)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == mod.FOREIGN_RECEIPT_RACE_SENTENCE
    assert "Nothing was recorded" in exc_info.value.detail
    assert len(calls) == mod.FOREIGN_RECEIPT_ATTEMPTS == 3
    assert writes == []


def test_a_foreign_receipt_whose_fresh_read_no_longer_fits_is_refused_for_that_and_not_sent_again(monkeypatch):
    """The concurrent receipt settled the invoice in full. The second plan finds nothing left to settle and says so (422, the
    over-allocation sentence); the receipt is not sent a second time."""
    from fastapi import HTTPException
    import services.receipt_service as mod

    invoice = {"id": "inv-1", "customer_id": "cust-1", "status": "issued", "txn_currency": "USD", "exchange_rate": "80", "total_paise": 800000,
               "paid_paise": 0, "paid_txn": 0, "credited_paise": 0, "txn_total": 10000}

    def on_call(_params):
        invoice.update(paid_paise=800000, paid_txn=10000, status="paid")
        raise _Moved()

    db, writes, calls = _foreign_world(monkeypatch, invoice, on_call)
    with pytest.raises(HTTPException) as exc_info:
        mod.create_foreign_receipt(firm_id="firm-1", data=dict(_RECEIPT), actor=_ACTOR, db=db)

    assert exc_info.value.status_code == 422 and "exceeds invoice inv-1 outstanding" in exc_info.value.detail
    assert len(calls) == 1 and writes == []


@pytest.mark.parametrize("error, status, words, sent", [
    (RuntimeError("PGRST202: Could not find the function public.settle_receipt_atomic in the schema cache"), None, "781", 1),
    # a number collision is prepared again (the tests above); the same number refused twice is named as carried elsewhere
    (RuntimeError('duplicate key value violates unique constraint "receipts_firm_receipt_no_key"'), 409, "already carried by another entry", 2),
])
def test_a_foreign_receipt_names_a_missing_function_and_a_number_collision(monkeypatch, error, status, words, sent):
    from fastapi import HTTPException
    import services.receipt_service as mod

    invoice = {"id": "inv-1", "customer_id": "cust-1", "status": "issued", "txn_currency": "USD", "exchange_rate": "80", "total_paise": 800000,
               "paid_paise": 0, "paid_txn": 0, "credited_paise": 0, "txn_total": 10000}

    def on_call(_params):
        raise error

    db, writes, calls = _foreign_world(monkeypatch, invoice, on_call)
    with pytest.raises((HTTPException, RuntimeError)) as exc_info:
        mod.create_foreign_receipt(firm_id="firm-1", data=dict(_RECEIPT), actor=_ACTOR, db=db)
    if status is None:
        assert isinstance(exc_info.value, RuntimeError) and words in str(exc_info.value)
    else:
        assert exc_info.value.status_code == status and words in exc_info.value.detail
    assert len(calls) == sent and writes == []
