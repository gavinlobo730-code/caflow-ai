"""A payment to a supplier is ONE database transaction, in each of its four shapes (ledger POST-A-575; migration 784).

WHAT WAS WRONG
    A customer receipt has been one transaction since migration 160 (a rupee one) and 781 (a foreign one). A supplier payment was
    not. The route for one bill reserved the bill's outstanding with a compare-and-set, posted the entry through the kernel, inserted
    the payment, gave the reservation back if that failed and then recomputed the bill from its payments; the service for several
    bills posted the entry, inserted the payment, moved each bill with a compare-and-set it retried, inserted the allocations, and on
    a failure reversed the entry and deleted the payment WITHOUT rolling back a bill an earlier step had moved. The two foreign
    shapes did the same with a second paid amount and a separate insert of the realised exchange difference.

WHAT THIS HOLDS, on the in-memory double of the function (the function itself is proved against PostgreSQL in
test_784_a_supplier_payment_is_recorded_in_one_transaction_pg.py)
    * each shape calls `settle_payment_atomic` ONCE and writes nothing else: the entry, the payment, the bill and the allocation rows
      are what the function stored, and a payment that names its bill keeps the bill on its own row and writes no allocation row,
      which is what the reversal reads;
    * every refusal the route can see from a read is in a person's words and writes nothing (more than is left, another supplier's
      bill, a rupee payment against a bill billed in a foreign currency);
    * a payment that LOSES A RACE writes nothing either: a rupee payment overtaken at its bill is refused with a sentence that says
      so; a foreign payment whose bill moved is planned again from a fresh read, and refused in words after PAYMENT_ATTEMPTS whole
      attempts;
    * a number another payment took at the same moment is answered by taking the next one, and a number refused twice running is
      carried by something that is not a payment and is said so;
    * a database that does not hold the function is named as a missing migration and never mistaken for the function's own refusal.

Runs everywhere (mock mode, no real database).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.invoices import PurchaseBillIn, PurchaseBillLineIn, PurchasePaymentIn
from models.parties import VendorIn
from tests.e2e_harness import FakeDB, account_balance, coa_id, seed_standard_coa, trial_balance, wire_e2e

FIRM = "FIRM-575"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth-u1", "email": "ca@f.test", "role": "Partner"}
WRITTEN = ("journal_entries", "journal_lines", "purchase_payments", "purchase_payment_allocations", "fx_adjustments")


@pytest.fixture
def book(monkeypatch):
    import routers.purchase_bills as pb
    import routers.purchase_payments as pp
    import routers.vendors as ve
    import services.purchase_payment_service as pps
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb, pp, ve, pps])
    monkeypatch.setenv("MULTI_CURRENCY_ENABLED", "true")
    db.seed("firms", {"id": FIRM, "multi_currency_entitled": True})
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5",
                        "functional_currency": "INR", "multi_currency_enabled": True})
    db.seed("currencies", {"code": "USD", "symbol": "$", "display_name": "US Dollar", "minor_unit": 2, "is_active": True})
    db.seed("currencies", {"code": "INR", "symbol": "₹", "display_name": "Indian Rupee", "minor_unit": 2, "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI", "name": "Services", "kind": "service"})
    return db, pb, pp, ve, pps


def _vendor(ve, name="Acme Supplies"):
    return ve.create_vendor(VendorIn(client_id="CLI", name=name, state_code="27"), CALLER)["data"]


def _bill(pb, vendor, total, no, *, currency=None, rate=None):
    extra = {"currency": currency, "exchange_rate": rate} if currency else {}
    bill = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id=vendor["id"], bill_date="2026-06-01", bill_no=no, **extra,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="svc", rate_paise=total, quantity=1,
                                  gst_rate_percent=0.0)]), CALLER)["data"]
    assert pb.receive_purchase_bill(bill["id"], CALLER)["success"] is True
    return bill


def _row(db, table, row_id):
    return next(r for r in db._tables[table] if r["id"] == row_id)


def _paid(db, bill_id) -> int:
    return int(_row(db, "purchase_bills", bill_id).get("paid_paise") or 0)


def _counts(db):
    return {t: len(db._tables.get(t, [])) for t in WRITTEN}


def _settles(db, before=None):
    """Count the calls to the payment function, and run `before(call_number, params)` ahead of each (a concurrent writer, say)."""
    calls = []
    real = db.rpc

    def rpc(fn, params=None):
        if fn == "settle_payment_atomic":
            calls.append(params)
            if before:
                before(len(calls), params)
        return real(fn, params)

    db.rpc = rpc
    return calls


def _pay(pp, vendor, amount, **kw):
    return pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id=vendor["id"], payment_date="2026-06-10", amount_paise=amount, **kw), CALLER)


# ── one bill, in rupees ───────────────────────────────────────────────────────────────

def test_a_part_payment_then_the_rest_move_the_bill_post_one_entry_each_and_write_no_allocation_row(book):
    db, pb, pp, ve, _pps = book
    vendor = _vendor(ve)
    bill = _bill(pb, vendor, 500_000, "B-1")
    calls = _settles(db)
    before = _counts(db)

    made = _pay(pp, vendor, 200_000, purchase_bill_id=bill["id"])
    assert made["success"] is True, made
    assert len(calls) == 1
    assert (_row(db, "purchase_bills", bill["id"])["paid_paise"], _row(db, "purchase_bills", bill["id"])["status"]) == (200_000, "partially_paid")
    payment = _row(db, "purchase_payments", made["data"]["id"])
    assert (payment["purchase_bill_id"], payment["amount_paise"], payment["unallocated_paise"]) == (bill["id"], 200_000, 0)
    entry = _row(db, "journal_entries", payment["journal_entry_id"])
    assert (entry["source_type"], entry["source_id"], entry["reference_no"], entry["entry_type"]) == \
        ("purchase_payment", payment["id"], payment["payment_no"], "Payment")
    lines = sorted((l["debit_paise"], l["credit_paise"], l["line_order"]) for l in db._tables["journal_lines"]
                   if l["journal_entry_id"] == entry["id"])
    assert lines == [(0, 200_000, 1), (200_000, 0, 0)]
    after = _counts(db)
    assert (after["journal_entries"] - before["journal_entries"], after["purchase_payments"] - before["purchase_payments"],
            after["purchase_payment_allocations"] - before["purchase_payment_allocations"]) == (1, 1, 0)

    assert _pay(pp, vendor, 300_000, purchase_bill_id=bill["id"])["success"] is True
    assert (_row(db, "purchase_bills", bill["id"])["paid_paise"], _row(db, "purchase_bills", bill["id"])["status"]) == (500_000, "paid")
    assert account_balance(db, coa_id(db, FIRM, "ap")) == 0
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


def test_more_than_is_left_is_refused_in_words_and_nothing_is_written(book):
    db, pb, pp, ve, _pps = book
    vendor = _vendor(ve)
    bill = _bill(pb, vendor, 500_000, "B-2")
    assert _pay(pp, vendor, 400_000, purchase_bill_id=bill["id"])["success"] is True
    calls = _settles(db)
    before = _counts(db)
    with pytest.raises(HTTPException) as e:
        _pay(pp, vendor, 200_000, purchase_bill_id=bill["id"])        # each is under the bill, their sum is not
    assert e.value.status_code == 422 and "exceeds the bill's outstanding" in e.value.detail
    assert calls == [] and _counts(db) == before
    assert _row(db, "purchase_bills", bill["id"])["paid_paise"] == 400_000


def test_a_payment_overtaken_at_its_bill_is_refused_whole_with_a_sentence_that_says_so(book):
    """The race the compare-and-set reservation was built for. Both payments pass the route's check against the same read; the
    function locks the bill, finds what the other left, and refuses the second WHOLE. Nothing has to be given back."""
    from services.purchase_payment_service import PAYMENT_OVERTAKEN_SENTENCE
    db, pb, pp, ve, _pps = book
    vendor = _vendor(ve)
    bill = _bill(pb, vendor, 500_000, "B-3")

    def another_payment_lands(_n, _params):
        row = _row(db, "purchase_bills", bill["id"])
        row["paid_paise"], row["status"] = 400_000, "partially_paid"

    calls = _settles(db, another_payment_lands)
    before = _counts(db)
    with pytest.raises(HTTPException) as e:
        _pay(pp, vendor, 200_000, purchase_bill_id=bill["id"])
    assert e.value.status_code == 409 and e.value.detail == PAYMENT_OVERTAKEN_SENTENCE
    assert len(calls) == 1, "a refusal that cannot succeed by itself was sent again"
    assert _counts(db) == before, "the refused payment left an entry or a payment behind"
    assert _row(db, "purchase_bills", bill["id"])["paid_paise"] == 400_000


def test_a_bill_cancelled_between_the_check_and_the_write_is_said_in_words(book):
    from services.purchase_payment_service import BILL_NO_LONGER_PAYABLE_SENTENCE
    db, pb, pp, ve, _pps = book
    vendor = _vendor(ve)
    bill = _bill(pb, vendor, 500_000, "B-4")
    _settles(db, lambda _n, _p: _row(db, "purchase_bills", bill["id"]).update(status="cancelled"))
    before = _counts(db)
    with pytest.raises(HTTPException) as e:
        _pay(pp, vendor, 200_000, purchase_bill_id=bill["id"])
    assert e.value.status_code == 409 and e.value.detail == BILL_NO_LONGER_PAYABLE_SENTENCE
    assert _counts(db) == before


def test_a_payment_with_no_bill_is_an_advance_and_says_what_is_left_of_it(book):
    db, _pb, pp, ve, _pps = book
    vendor = _vendor(ve)
    made = _pay(pp, vendor, 150_000)
    assert made["success"] is True, made
    payment = _row(db, "purchase_payments", made["data"]["id"])
    assert (payment["purchase_bill_id"], payment["unallocated_paise"]) == (None, 150_000)


# ── several bills, in rupees ──────────────────────────────────────────────────────────

def _core(pps, db, vendor, amount, allocations, **extra):
    return pps.create_payment_core(FIRM, {"client_id": "CLI", "vendor_id": vendor["id"], "payment_date": "2026-06-10",
                                          "amount_paise": amount, "allocations": allocations, **extra}, CALLER, db)


def test_one_payment_across_two_bills_is_one_call_and_an_allocation_row_per_bill(book):
    db, pb, _pp, ve, pps = book
    vendor = _vendor(ve)
    first, second = _bill(pb, vendor, 100_000, "B-5"), _bill(pb, vendor, 100_000, "B-6")
    calls = _settles(db)
    made = _core(pps, db, vendor, 180_000, [{"purchase_bill_id": first["id"], "allocated_paise": 100_000},
                                            {"purchase_bill_id": second["id"], "allocated_paise": 50_000}])
    assert len(calls) == 1
    assert (_row(db, "purchase_bills", first["id"])["status"], _row(db, "purchase_bills", second["id"])["status"]) == ("paid", "partially_paid")
    rows = sorted((a["purchase_bill_id"], a["allocated_paise"]) for a in db._tables["purchase_payment_allocations"]
                  if a["purchase_payment_id"] == made["id"])
    assert rows == sorted([(first["id"], 100_000), (second["id"], 50_000)])
    assert sorted((a["purchase_bill_id"], a["allocated_paise"]) for a in made["allocations"]) == rows
    payment = _row(db, "purchase_payments", made["id"])
    assert (payment["purchase_bill_id"], payment["unallocated_paise"], payment["journal_entry_id"]) == (None, 30_000, made["journal_entry_id"])


def test_two_rows_for_one_bill_are_one_settlement_and_one_allocation_row(book):
    """The allocations table holds one row per payment and bill. The path used to insert one per row SENT, so the second collided
    after the entry and the bill had already been written."""
    db, pb, _pp, ve, pps = book
    vendor = _vendor(ve)
    bill = _bill(pb, vendor, 100_000, "B-7")
    made = _core(pps, db, vendor, 100_000, [{"purchase_bill_id": bill["id"], "allocated_paise": 30_000},
                                            {"purchase_bill_id": bill["id"], "allocated_paise": 70_000}])
    (row,) = [a for a in db._tables["purchase_payment_allocations"] if a["purchase_payment_id"] == made["id"]]
    assert row["allocated_paise"] == 100_000 and _row(db, "purchase_bills", bill["id"])["status"] == "paid"


def test_one_suppliers_payment_does_not_settle_another_suppliers_bill(book):
    """POST-A-580. The route for one bill has always asked; the path for several bills asked only that the bill was the client's."""
    from services.purchase_payment_service import bill_of_another_supplier
    db, pb, _pp, ve, pps = book
    vendor, other = _vendor(ve), _vendor(ve, "Somebody Else")
    mine, theirs = _bill(pb, vendor, 100_000, "B-8"), _bill(pb, other, 100_000, "B-9")
    calls = _settles(db)
    before = _counts(db)
    with pytest.raises(HTTPException) as e:
        _core(pps, db, vendor, 150_000, [{"purchase_bill_id": mine["id"], "allocated_paise": 100_000},
                                         {"purchase_bill_id": theirs["id"], "allocated_paise": 50_000}])
    assert e.value.status_code == 422 and e.value.detail == bill_of_another_supplier("B-9")
    assert calls == [] and _counts(db) == before
    assert _paid(db, mine["id"]) == 0, "the first bill was moved before the second was refused"


def test_a_refusal_at_the_second_bill_inside_the_function_leaves_the_first_bill_untouched(book):
    """The defect itself: the second bill has less left than the route read. Before, the first bill kept its paid amount."""
    from services.purchase_payment_service import PAYMENT_OVERTAKEN_SENTENCE
    db, pb, _pp, ve, pps = book
    vendor = _vendor(ve)
    first, second = _bill(pb, vendor, 100_000, "B-10"), _bill(pb, vendor, 100_000, "B-11")
    _settles(db, lambda _n, _p: _row(db, "purchase_bills", second["id"]).update(paid_paise=80_000, status="partially_paid"))
    before = _counts(db)
    with pytest.raises(HTTPException) as e:
        _core(pps, db, vendor, 150_000, [{"purchase_bill_id": first["id"], "allocated_paise": 100_000},
                                         {"purchase_bill_id": second["id"], "allocated_paise": 50_000}])
    assert e.value.status_code == 409 and e.value.detail == PAYMENT_OVERTAKEN_SENTENCE
    assert _counts(db) == before
    assert (_paid(db, first["id"]), _row(db, "purchase_bills", first["id"])["status"]) == (0, "received")


# ── a rupee payment against a bill billed in a foreign currency ───────────────────────

def test_a_rupee_payment_does_not_settle_a_bill_billed_in_dollars_by_either_route(book):
    from services.purchase_payment_service import rupee_payment_against_a_foreign_bill
    db, pb, pp, ve, pps = book
    vendor = _vendor(ve)
    bill = _bill(pb, vendor, 100_000, "USD-B-1", currency="USD", rate="80.0")
    calls = _settles(db)
    before = _counts(db)
    with pytest.raises(HTTPException) as one:
        _pay(pp, vendor, 100_000, purchase_bill_id=bill["id"])
    with pytest.raises(HTTPException) as several:
        _core(pps, db, vendor, 100_000, [{"purchase_bill_id": bill["id"], "allocated_paise": 100_000}])
    for e in (one, several):
        assert e.value.status_code == 422 and e.value.detail == rupee_payment_against_a_foreign_bill("USD-B-1", "USD")
    assert calls == [] and _counts(db) == before
    row = _row(db, "purchase_bills", bill["id"])
    assert (int(row.get("paid_paise") or 0), int(row.get("paid_txn") or 0)) == (0, 0)


# ── a foreign payment ─────────────────────────────────────────────────────────────────

def test_a_foreign_payment_whose_bill_moved_is_planned_again_from_a_fresh_read_and_adds_to_what_landed(book):
    """A concurrent 500.00 USD payment lands between this payment's read and the function's lock. The function refuses the whole
    payment (its own state, VP001); the payment is planned again from the bill as it now stands and adds to it. Before, a
    compare-and-set on the bill was retried after the entry and the payment had already been written."""
    db, pb, pp, ve, _pps = book
    vendor = _vendor(ve)
    bill = _bill(pb, vendor, 100_000, "USD-B-2", currency="USD", rate="80.0")

    def a_concurrent_payment(n, _params):
        if n == 1:
            row = _row(db, "purchase_bills", bill["id"])
            row["paid_paise"], row["paid_txn"], row["status"] = 4_000_000, 50_000, "partially_paid"

    calls = _settles(db, a_concurrent_payment)
    before = _counts(db)
    made = _pay(pp, vendor, 30_000, purchase_bill_id=bill["id"], currency="USD", exchange_rate="80.0")
    assert made["success"] is True, made
    assert len(calls) == 2, "the payment was not planned again after the bill moved"
    assert (calls[0]["p_allocations"][0]["expect_paid_txn"], calls[1]["p_allocations"][0]["expect_paid_txn"]) == (0, 50_000)
    assert calls[0]["p_payment"]["id"] == calls[1]["p_payment"]["id"], "the retry is the same payment, sent again"
    row = _row(db, "purchase_bills", bill["id"])
    assert (row["paid_paise"], row["paid_txn"], row["status"]) == (4_000_000 + 2_400_000, 50_000 + 30_000, "partially_paid")
    after = _counts(db)
    assert (after["journal_entries"] - before["journal_entries"], after["purchase_payments"] - before["purchase_payments"]) == (1, 1), \
        "the attempt that lost left something behind"


def test_a_foreign_payment_that_keeps_losing_is_refused_in_words_after_a_fixed_number_of_whole_attempts(book):
    from services.purchase_payment_service import PAYMENT_ATTEMPTS, PAYMENT_RACE_SENTENCE
    db, pb, pp, ve, _pps = book
    vendor = _vendor(ve)
    bill = _bill(pb, vendor, 100_000, "USD-B-3", currency="USD", rate="80.0")

    def always_moving(n, _params):
        row = _row(db, "purchase_bills", bill["id"])
        row["paid_paise"], row["paid_txn"], row["status"] = 80_000 * n, 1_000 * n, "partially_paid"

    calls = _settles(db, always_moving)
    before = _counts(db)
    with pytest.raises(HTTPException) as e:
        _pay(pp, vendor, 30_000, purchase_bill_id=bill["id"], currency="USD", exchange_rate="80.0")
    assert e.value.status_code == 409 and e.value.detail == PAYMENT_RACE_SENTENCE
    assert len(calls) == PAYMENT_ATTEMPTS
    assert _counts(db) == before


def test_a_foreign_payment_across_two_bills_relieves_each_at_its_own_rate_and_records_the_difference_once(book):
    db, pb, _pp, ve, pps = book
    vendor = _vendor(ve)
    first = _bill(pb, vendor, 50_000, "USD-B-4", currency="USD", rate="80.0")
    second = _bill(pb, vendor, 50_000, "USD-B-5", currency="USD", rate="82.0")
    calls = _settles(db)
    made = _core(pps, db, vendor, 120_000, [{"purchase_bill_id": first["id"], "allocated_paise": 50_000},
                                            {"purchase_bill_id": second["id"], "allocated_paise": 50_000}],
                 currency="USD", exchange_rate="83.0")
    assert len(calls) == 1
    # 500.00 at 80 and 500.00 at 82 of payable relieved (81,000.00) for 83,000.00 of cash: a loss of 2,000.00
    assert made["realized_fx_paise"] == -200_000
    (fx,) = [f for f in db._tables["fx_adjustments"] if f["document_id"] == made["id"]]
    assert fx["base_delta_paise"] == -200_000 and fx["journal_entry_id"] == made["journal_entry_id"]
    rows = sorted((a["purchase_bill_id"], a["allocated_paise"], a["allocated_txn"]) for a in db._tables["purchase_payment_allocations"]
                  if a["purchase_payment_id"] == made["id"])
    assert rows == sorted([(first["id"], 4_000_000, 50_000), (second["id"], 4_100_000, 50_000)])
    payment = _row(db, "purchase_payments", made["id"])
    # the 200.00 USD not given to a bill is an advance carried at the payment's own rate
    assert (payment["txn_amount"], payment["amount_paise"], payment["unallocated_paise"]) == (120_000, 9_960_000, 1_660_000)
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


# ── the number ────────────────────────────────────────────────────────────────────────

def test_a_number_another_payment_took_at_the_same_moment_is_answered_by_taking_the_next_one(book):
    """Two payments recorded at the same moment both read the same last number. The second is refused for the duplicate before any
    bill is looked at, and taking the next number is all it needs. This used to be a 409 asking the person to retry, after the entry
    had been posted and reversed."""
    db, pb, pp, ve, _pps = book
    vendor = _vendor(ve)
    bill = _bill(pb, vendor, 500_000, "B-12")

    def the_other_payment_takes_the_number(n, params):
        if n == 1:
            db._tables.setdefault("purchase_payments", []).append({
                "id": "other", "firm_id": FIRM, "client_id": "CLI", "vendor_id": vendor["id"], "amount_paise": 1,
                "payment_no": params["p_payment"]["payment_no"], "payment_date": "2026-06-10"})

    calls = _settles(db, the_other_payment_takes_the_number)
    made = _pay(pp, vendor, 200_000, purchase_bill_id=bill["id"])
    assert made["success"] is True, made
    assert len(calls) == 2 and calls[0]["p_payment"]["payment_no"] != calls[1]["p_payment"]["payment_no"]
    assert made["data"]["payment_no"] == calls[1]["p_payment"]["payment_no"]
    assert calls[1]["p_journal_entry"]["reference_no"] == made["data"]["payment_no"]
    assert _row(db, "purchase_bills", bill["id"])["paid_paise"] == 200_000
    assert len([e for e in db._tables["journal_entries"] if e.get("source_id") == made["data"]["id"]]) == 1


def test_a_number_refused_twice_running_is_carried_by_something_that_is_not_a_payment_and_is_said_so(book):
    from services.purchase_payment_service import payment_number_carried_elsewhere
    db, pb, pp, ve, _pps = book
    vendor = _vendor(ve)
    bill = _bill(pb, vendor, 500_000, "B-13")
    real = db.rpc
    sent = []

    class _Dup:
        def execute(self):
            raise RuntimeError('duplicate key value violates unique constraint "uq_journal_entries_reference" (23505)')

    def rpc(fn, params=None):
        if fn == "settle_payment_atomic":
            sent.append(params["p_payment"]["payment_no"])
            return _Dup()
        return real(fn, params)

    db.rpc = rpc
    before = _counts(db)
    with pytest.raises(HTTPException) as e:
        _pay(pp, vendor, 200_000, purchase_bill_id=bill["id"])
    assert len(sent) == 2 and sent[0] == sent[1], sent
    assert e.value.status_code == 409 and e.value.detail == payment_number_carried_elsewhere(sent[0])
    assert _counts(db) == before and _paid(db, bill["id"]) == 0


# ── the function is not there, or says something else ─────────────────────────────────

class _Raising:
    def __init__(self, error):
        self._error = error

    def execute(self):
        raise self._error


def _function_raises(db, error):
    real = db.rpc
    db.rpc = lambda fn, params=None: _Raising(error) if fn == "settle_payment_atomic" else real(fn, params)


def test_a_database_without_the_function_is_named_as_a_missing_migration_and_never_as_a_refusal(book):
    db, pb, _pp, ve, pps = book
    vendor = _vendor(ve)
    bill = _bill(pb, vendor, 100_000, "B-14")
    _function_raises(db, RuntimeError("PGRST202: Could not find the function public.settle_payment_atomic in the schema cache"))
    with pytest.raises(RuntimeError) as e:
        _core(pps, db, vendor, 100_000, [{"purchase_bill_id": bill["id"], "allocated_paise": 100_000}])
    assert "migration 784" in str(e.value) and "784_a_supplier_payment_is_recorded_in_one_transaction.sql" in str(e.value)


def test_the_functions_own_refusals_are_never_mistaken_for_a_missing_migration(book):
    from services.purchase_payment_service import _payment_refusal
    for words in ("settle_payment_atomic: bill abc is not part of this client's books",
                  "settle_payment_atomic: allocation to bill abc (5 paise) exceeds its outstanding",
                  "settle_payment_atomic: bill abc changed while this payment was being prepared"):
        refusal = _payment_refusal(RuntimeError(words))
        assert not (isinstance(refusal, RuntimeError) and "migration" in str(refusal)), words


def test_an_error_that_is_not_a_known_refusal_is_raised_as_itself_and_sent_once(book):
    db, pb, _pp, ve, pps = book
    vendor = _vendor(ve)
    bill = _bill(pb, vendor, 100_000, "B-15")
    boom = ConnectionError("connection reset by peer")
    sent = []
    real = db.rpc

    def rpc(fn, params=None):
        if fn == "settle_payment_atomic":
            sent.append(1)
            return _Raising(boom)
        return real(fn, params)

    db.rpc = rpc
    with pytest.raises(ConnectionError) as e:
        _core(pps, db, vendor, 100_000, [{"purchase_bill_id": bill["id"], "allocated_paise": 100_000}])
    assert e.value is boom and len(sent) == 1


def test_the_closures_own_sentence_reaches_the_person_as_a_refusal(book, monkeypatch):
    """The function's door asks the closure (the firm's locked year, the client's finalised year-end). When it is the one that
    speaks, the person reads its sentence and not a failure."""
    from services import period_lock_service
    db, pb, _pp, ve, pps = book
    vendor = _vendor(ve)
    bill = _bill(pb, vendor, 100_000, "B-16")
    sentence = "The financial year 2026-27 of this client has been finalised."
    monkeypatch.setattr(period_lock_service, "closure_sentence_in", lambda e: sentence if "finalised" in str(e) else None)
    _function_raises(db, RuntimeError(sentence))
    with pytest.raises(HTTPException) as e:
        _core(pps, db, vendor, 100_000, [{"purchase_bill_id": bill["id"], "allocated_paise": 100_000}])
    assert e.value.status_code == 422 and e.value.detail == sentence


# ── every key the payment payload sends is a column ───────────────────────────────────

def test_every_key_a_payment_sends_is_a_column_of_the_table_or_the_one_key_that_is_not_the_rows(book):
    """The function builds its INSERT from the payload's own keys, so a key that is no column fails the whole payment in production.
    The four shapes are driven and every payload they hand the function is read. (The double refuses an unknown key as well, so a
    new one fails every payment test; this says which.)"""
    from tests._payment_function_source import NOT_THE_ROWS, PURCHASE_PAYMENT_COLUMNS
    db, pb, pp, ve, pps = book
    vendor = _vendor(ve)
    calls = _settles(db)
    rupee, usd, usd2 = _bill(pb, vendor, 100_000, "B-17"), _bill(pb, vendor, 100_000, "USD-B-6", currency="USD", rate="80.0"), \
        _bill(pb, vendor, 100_000, "USD-B-7", currency="USD", rate="80.0")
    _pay(pp, vendor, 50_000, purchase_bill_id=rupee["id"])
    _core(pps, db, vendor, 60_000, [{"purchase_bill_id": rupee["id"], "allocated_paise": 50_000}])
    _pay(pp, vendor, 100_000, purchase_bill_id=usd["id"], currency="USD", exchange_rate="83.0")
    _core(pps, db, vendor, 100_000, [{"purchase_bill_id": usd2["id"], "allocated_paise": 100_000}], currency="USD", exchange_rate="83.0")
    assert len(calls) == 4
    for params in calls:
        stray = set(params["p_payment"]) - PURCHASE_PAYMENT_COLUMNS - NOT_THE_ROWS
        assert not stray, stray
        assert params["p_journal_entry"]["source_id"] == params["p_payment"]["id"]
        assert {"firm_id", "client_id", "vendor_id", "payment_no", "payment_date", "amount_paise", "id"} <= set(params["p_payment"])


# ── re-allocating a payment (still its own statements; what it may be moved onto) ─────

def _re_allocate(pp, payment_id, bill_id, amount):
    from models.invoices import PurchasePaymentAllocationIn, PurchasePaymentAllocationsUpdateIn
    return pp.update_purchase_payment_allocations(payment_id, PurchasePaymentAllocationsUpdateIn(
        allocations=[PurchasePaymentAllocationIn(purchase_bill_id=bill_id, allocated_paise=amount)]), CALLER)


def test_an_advance_is_not_re_allocated_onto_another_suppliers_bill_or_a_bill_billed_in_dollars(book):
    """POST-A-580 and the rupee-against-foreign rule, at the one other door that moves a payment onto a bill."""
    from services.purchase_payment_service import bill_of_another_supplier, rupee_payment_against_a_foreign_bill
    db, pb, pp, ve, pps = book
    vendor, other = _vendor(ve), _vendor(ve, "Somebody Else")
    theirs = _bill(pb, other, 100_000, "B-20")
    dollars = _bill(pb, vendor, 100_000, "USD-B-8", currency="USD", rate="80.0")
    mine = _bill(pb, vendor, 100_000, "B-21")
    advance = _core(pps, db, vendor, 100_000, [])
    for bill, sentence in ((theirs, bill_of_another_supplier("B-20")), (dollars, rupee_payment_against_a_foreign_bill("USD-B-8", "USD"))):
        with pytest.raises(HTTPException) as e:
            _re_allocate(pp, advance["id"], bill["id"], 50_000)
        assert e.value.status_code == 422 and e.value.detail == sentence
        assert _paid(db, bill["id"]) == 0
    assert _row(db, "purchase_payments", advance["id"])["unallocated_paise"] == 100_000
    # its own supplier's rupee bill still takes it
    assert _re_allocate(pp, advance["id"], mine["id"], 50_000)["success"] is True
    assert _paid(db, mine["id"]) == 50_000 and _row(db, "purchase_payments", advance["id"])["unallocated_paise"] == 50_000


def test_a_payment_made_in_a_foreign_currency_is_not_re_allocated(book):
    from services.purchase_payment_service import FOREIGN_PAYMENT_IS_NOT_REALLOCATED
    db, pb, pp, ve, pps = book
    vendor = _vendor(ve)
    first = _bill(pb, vendor, 100_000, "USD-B-9", currency="USD", rate="80.0")
    second = _bill(pb, vendor, 100_000, "USD-B-10", currency="USD", rate="80.0")
    made = _core(pps, db, vendor, 100_000, [{"purchase_bill_id": first["id"], "allocated_paise": 100_000}], currency="USD", exchange_rate="83.0")
    before = (dict(_row(db, "purchase_bills", first["id"])), dict(_row(db, "purchase_bills", second["id"])))
    with pytest.raises(HTTPException) as e:
        _re_allocate(pp, made["id"], second["id"], 100_000)
    assert e.value.status_code == 422 and e.value.detail == FOREIGN_PAYMENT_IS_NOT_REALLOCATED.format(currency="USD")
    assert (_row(db, "purchase_bills", first["id"]), _row(db, "purchase_bills", second["id"])) == before


# ── what the independent review of this change asked to be held ───────────────────────

def test_a_payment_that_names_its_bill_and_a_reversed_payment_are_not_re_allocated(book):
    """Both needed a hand-made request (the screen offers "Apply" only for a live payment with something left). A payment recorded
    against one bill has given that bill its whole amount: moving it would settle twice with one payment, and its reversal rolls
    back only the bill it names. A reversed payment's money went back."""
    from models.accounting import JournalReversalIn
    from services.purchase_payment_service import PAYMENT_THAT_NAMES_ITS_BILL_IS_NOT_REALLOCATED, REVERSED_PAYMENT_IS_NOT_REALLOCATED
    db, pb, pp, ve, pps = book
    vendor = _vendor(ve)
    first, second = _bill(pb, vendor, 100_000, "B-30"), _bill(pb, vendor, 100_000, "B-31")
    named = _pay(pp, vendor, 100_000, purchase_bill_id=first["id"])["data"]
    with pytest.raises(HTTPException) as e:
        _re_allocate(pp, named["id"], second["id"], 100_000)
    assert e.value.status_code == 422 and e.value.detail == PAYMENT_THAT_NAMES_ITS_BILL_IS_NOT_REALLOCATED
    assert (_paid(db, first["id"]), _paid(db, second["id"])) == (100_000, 0)

    advance = _core(pps, db, vendor, 60_000, [{"purchase_bill_id": second["id"], "allocated_paise": 60_000}])
    assert pp.reverse_purchase_payment(advance["id"], JournalReversalIn(reversal_date="2026-06-20"), CALLER)["success"] is True
    assert _paid(db, second["id"]) == 0
    with pytest.raises(HTTPException) as e:
        _re_allocate(pp, advance["id"], second["id"], 60_000)
    assert e.value.status_code == 409 and e.value.detail == REVERSED_PAYMENT_IS_NOT_REALLOCATED
    assert _paid(db, second["id"]) == 0, "a reversed payment's money was applied to a bill again"


def test_a_duplicate_is_read_from_the_state_and_a_bill_id_that_holds_those_digits_is_not_one():
    """Every refusal of the function names a bill by its id. The bare digits 23505 inside an id used to make an ordinary refusal a
    number collision, answered with a second attempt and then with "the number is carried by another entry"."""
    from services.purchase_payment_service import _is_unique_violation

    class _Refusal(Exception):
        def __init__(self, message, code=None):
            super().__init__(message)
            self.code = code

    ordinary = "settle_payment_atomic: allocation to bill 0f23505a-1111-4222-8333-444455556666 (5 paise) exceeds its outstanding"
    assert _is_unique_violation(_Refusal(ordinary)) is False
    assert _is_unique_violation(_Refusal(ordinary, code="P0001")) is False
    assert _is_unique_violation(_Refusal("whatever the words are", code="23505")) is True
    assert _is_unique_violation(_Refusal('duplicate key value violates unique constraint "purchase_payments_firm_payment_no_key"')) is True
    # a state that is not a duplicate decides, whatever the words say
    assert _is_unique_violation(_Refusal("duplicate key value (in a message about something else)", code="VP001")) is False


def test_a_supplier_named_in_capitals_is_the_same_supplier(book):
    db, pb, _pp, ve, pps = book
    vendor = _vendor(ve)
    bill = _bill(pb, vendor, 100_000, "B-32")
    # the vendor row is looked up by the id as sent; the comparison with the bill's own vendor must not turn on its spelling
    from services.purchase_payment_service import _bills_a_rupee_payment_may_settle, _same_id
    assert _same_id(vendor["id"].upper(), vendor["id"]) and not _same_id("", "") and not _same_id(vendor["id"], "another")
    _bills_a_rupee_payment_may_settle(db, FIRM, "CLI", vendor["id"].upper(), {bill["id"]: 100_000})       # does not raise
    made = _core(pps, db, vendor, 100_000, [{"purchase_bill_id": bill["id"], "allocated_paise": 100_000}])
    assert _row(db, "purchase_bills", bill["id"])["status"] == "paid" and made["id"]


def test_a_foreign_payment_that_would_relieve_more_rupees_than_are_owed_is_refused_in_words(book):
    """The third refusal this change adds, with the two in the record. A debit note on a foreign bill lowers what is owed in rupees
    and not the foreign amount outstanding, so a part payment at the bill's own rate can ask to relieve more rupees than are left.
    The old foreign paths had no rupee ceiling: the bill's rupee paid amount ran past what was payable."""
    db, pb, pp, ve, _pps = book
    vendor = _vendor(ve)
    bill = _bill(pb, vendor, 100_000, "USD-B-11", currency="USD", rate="80.0")          # 1,000.00 USD, 80,000.00 rupees
    _row(db, "purchase_bills", bill["id"])["debited_paise"] = 7_000_000                 # a debit note took 70,000.00 off in rupees
    calls = _settles(db)
    before = _counts(db)
    with pytest.raises(HTTPException) as e:
        _pay(pp, vendor, 50_000, purchase_bill_id=bill["id"], currency="USD", exchange_rate="80.0")   # 500.00 USD = 40,000.00 at the bill's rate
    assert e.value.status_code == 422
    assert "left to pay in rupees" in e.value.detail and "A debit note has reduced what is owed" in e.value.detail
    assert calls == [] and _counts(db) == before


def test_a_payment_in_a_year_the_client_has_closed_is_refused_in_the_closures_own_sentence_before_anything_is_sent(book):
    """The posting kernel asked the closure for a payment until it stopped being the one that posts it. The service asks it now,
    before a number is taken, with the real reader (services/period_lock_service), and the function's door asks it again."""
    from services import period_lock_service
    db, pb, pp, ve, _pps = book
    vendor = _vendor(ve)
    bill = _bill(pb, vendor, 100_000, "B-33")
    db.seed("client_year_locks", {"firm_id": FIRM, "client_id": "CLI", "financial_year": "2026-27", "reason": "year end finalised"})
    reason = period_lock_service.closure_reason(db, FIRM, "CLI", "2026-06-10")
    assert reason, "the fixture did not close the client's year: the test would pass for any code"
    calls = _settles(db)
    before = _counts(db)
    with pytest.raises(HTTPException) as e:
        _pay(pp, vendor, 50_000, purchase_bill_id=bill["id"])
    assert e.value.status_code == 422 and e.value.detail == reason
    assert calls == [] and _counts(db) == before and _paid(db, bill["id"]) == 0
    # and when the FUNCTION is the one that says it (a year closed between the two), the same sentence reaches the person
    assert period_lock_service.closure_sentence_in(RuntimeError(reason)) == reason


def test_a_payment_against_one_bill_keeps_the_bank_account_the_money_left(book):
    """The entry's cash leg is posted from the chosen account; the payment row did not say which until this change."""
    db, pb, pp, ve, _pps = book
    vendor = _vendor(ve)
    bill = _bill(pb, vendor, 100_000, "B-34")
    db.seed("bank_accounts", {"id": "BA-575", "firm_id": FIRM, "client_id": "CLI", "bank_name": "HDFC", "is_active": True,
                              "coa_account_id": coa_id(db, FIRM, "bank")})
    calls = _settles(db)
    made = _pay(pp, vendor, 100_000, purchase_bill_id=bill["id"], bank_account_id="BA-575")
    assert made["success"] is True, made
    assert calls[0]["p_payment"]["bank_account_id"] == "BA-575"
    assert _row(db, "purchase_payments", made["data"]["id"])["bank_account_id"] == "BA-575"
