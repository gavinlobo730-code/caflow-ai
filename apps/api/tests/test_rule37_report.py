"""
The Rule 37 report finds the bills that have gone 180 days unpaid.

The arithmetic is tested in test_rule37_itc_reversal.py against the rule. This
is about the query: which bills are picked up, which are correctly left alone,
and whether a large book is read completely.
"""
from __future__ import annotations

import pytest

from services import itc_reversal_service as svc
from tests.e2e_harness import FakeDB

FIRM = "firm-1"
CLIENT = "client-1"
TODAY = "2026-07-15"          # a bill dated 1 Jan 2026 is 195 days old here


@pytest.fixture
def db():
    return FakeDB()


def _bill(db, bill_no, *, bill_date="2026-01-01", status="received",
          total=118_000_00, paid=0, tds=0, cgst=9_000_00, sgst=9_000_00,
          igst=0, client_id=CLIENT, debited=0, credit_note=0):
    return db.seed("purchase_bills", {
        "firm_id": FIRM, "client_id": client_id, "vendor_id": "V1",
        "bill_no": bill_no, "bill_date": bill_date, "status": status,
        "total_paise": total, "paid_paise": paid, "tds_paise": tds,
        "cgst_paise": cgst, "sgst_paise": sgst, "igst_paise": igst,
        "debited_paise": debited, "credit_note_paise": credit_note,
    })


def _debit_note(db, bill_id, *, total, cgst=0, sgst=0, igst=0,
                status="issued", deleted_at=None, client_id=CLIENT):
    """A purchase RETURN. Reduces the supply, and its own journal has ALREADY
    credited GST Input for the tax on the goods sent back."""
    return db.seed("debit_notes", {
        "firm_id": FIRM, "client_id": client_id, "vendor_id": "V1",
        "purchase_bill_id": bill_id, "debit_note_no": f"DN-{bill_id}",
        "total_paise": total, "cgst_paise": cgst, "sgst_paise": sgst,
        "igst_paise": igst, "status": status, "deleted_at": deleted_at,
    })


def _purchase_credit_note(db, bill_id, *, total, cgst=0, sgst=0, igst=0,
                          status="issued", client_id=CLIENT):
    """The supplier's UNDERCHARGE correction (§34(3)). Increases what is owed,
    and its journal has debited GST Input for the extra tax."""
    return db.seed("purchase_credit_notes", {
        "firm_id": FIRM, "client_id": client_id, "vendor_id": "V1",
        "purchase_bill_id": bill_id, "credit_note_no": f"PCN-{bill_id}",
        "total_paise": total, "cgst_paise": cgst, "sgst_paise": sgst,
        "igst_paise": igst, "status": status, "deleted_at": None,
    })


def _report(db, **kw):
    return svc.rule37_report(db, FIRM, CLIENT, as_of=TODAY, **kw)


# ── what gets picked up ──────────────────────────────────────────────────────

def test_an_unpaid_bill_past_180_days_is_reported(db):
    _bill(db, "B-1")

    out = _report(db)

    assert out["bill_count"] == 1
    item = out["bills"][0]
    assert item["bill_no"] == "B-1"
    assert item["days_outstanding"] == 195
    assert item["payment_due_by"] == "2026-06-30"
    assert item["reversal"]["total_paise"] == 18_000_00


def test_the_report_says_which_return_the_reversal_belongs_in(db):
    """Rule 37(1): the period AFTER the one the 180 days expired in. The dates
    do not make that obvious and it is the usual thing to get wrong."""
    _bill(db, "B-1")

    assert _report(db)["bills"][0]["reverse_in_period"] == "072026"


def test_totals_add_up_per_tax_head(db):
    """GSTR-3B table 4(B) reports the heads separately."""
    _bill(db, "B-1", cgst=9_000_00, sgst=9_000_00, igst=0)
    _bill(db, "B-2", cgst=0, sgst=0, igst=18_000_00)

    totals = _report(db)["totals"]

    assert totals["cgst_paise"] == 9_000_00
    assert totals["sgst_paise"] == 9_000_00
    assert totals["igst_paise"] == 18_000_00
    assert totals["total_paise"] == 36_000_00


def test_a_part_paid_bill_reports_only_the_unpaid_proportion(db):
    _bill(db, "B-1", paid=59_000_00)

    item = _report(db)["bills"][0]

    assert item["unpaid_paise"] == 59_000_00
    assert item["reversal"]["total_paise"] == 9_000_00


# ── what is correctly left alone ─────────────────────────────────────────────

def test_a_bill_inside_the_180_days_is_not_reported(db):
    _bill(db, "B-RECENT", bill_date="2026-06-01")

    assert _report(db)["bill_count"] == 0


def test_a_fully_paid_bill_is_not_reported_however_old(db):
    _bill(db, "B-PAID", bill_date="2024-01-01", paid=118_000_00)

    assert _report(db)["bill_count"] == 0


def test_a_bill_settled_by_tds_is_not_reported(db):
    """The interpretation from the domain module, visible at report level: TDS
    is remitted on the supplier's behalf, so this bill is settled."""
    _bill(db, "B-TDS", total=100_000_00, paid=90_000_00, tds=10_000_00)

    assert _report(db)["bill_count"] == 0


def test_a_bill_with_no_input_credit_is_not_reported(db):
    """An exempt or non-GST purchase carries no ITC, so 180 days of non-payment
    changes nothing about the return. Listing it would bury the real findings."""
    _bill(db, "B-NOITC", cgst=0, sgst=0, igst=0)

    assert _report(db)["bill_count"] == 0


@pytest.mark.parametrize("status", ["draft", "cancelled"])
def test_drafts_and_cancelled_bills_carry_no_credit_to_reverse(db, status):
    """A draft was never claimed; a cancelled bill was undone."""
    _bill(db, "B-X", status=status)

    assert _report(db)["bill_count"] == 0


def test_another_clients_bill_is_not_included(db):
    _bill(db, "B-OTHER", client_id="client-2")

    assert _report(db)["bill_count"] == 0


# ── how it reads ─────────────────────────────────────────────────────────────

def test_the_longest_overdue_bill_comes_first(db):
    """That is the one accruing the most §50 interest."""
    _bill(db, "B-NEW", bill_date="2026-01-01")
    _bill(db, "B-OLD", bill_date="2024-01-01")

    assert [b["bill_no"] for b in _report(db)["bills"]] == ["B-OLD", "B-NEW"]


def test_the_report_names_the_rule_it_applies(db):
    _bill(db, "B-1")

    out = _report(db)

    assert "Rule 37" in out["rule"]
    assert out["ca_review_required"] is True, "this reports; it does not post or file"


def test_asking_as_at_an_earlier_date_changes_the_answer(db):
    """The CA asks this at a period end, not on the day they open the screen —
    the reversal belongs in a specific return."""
    _bill(db, "B-1", bill_date="2026-01-01")

    assert svc.rule37_report(db, FIRM, CLIENT, as_of="2026-06-30")["bill_count"] == 0
    assert svc.rule37_report(db, FIRM, CLIENT, as_of="2026-07-01")["bill_count"] == 1


# ── the read itself ──────────────────────────────────────────────────────────

def test_a_book_larger_than_one_page_is_read_completely(db):
    """PostgREST caps a read at db-max-rows and returns the short page without
    complaint — this codebase has hit that six times now. Under-reading here
    under-reports the reversal, which is the direction that costs interest.
    """
    for i in range(svc.PAGE + 25):
        _bill(db, f"B-{i:05d}")

    out = _report(db)

    assert out["bill_count"] == svc.PAGE + 25
    assert out["totals"]["total_paise"] == (svc.PAGE + 25) * 18_000_00


# ── §34 notes: PUR-09, the double reversal ───────────────────────────────────
#
# A debit note's own journal credits GST Input for the tax on the returned
# goods. Rule 37 reading the bill's GROSS figures reversed that same tax a
# SECOND time — the CA under-claims credit for the month, and the compensating
# re-availment under Rule 37(4) never happens because there was no payment to
# trigger it.


def test_a_returned_bill_reverses_only_the_credit_still_availed(db):
    """The finding's own worked example. ₹1,18,000 bill, ₹59,000 of goods
    returned on a debit note, balance never paid: ₹9,000 is due, not ₹18,000."""
    bill = _bill(db, "B-1", debited=59_000_00)
    _debit_note(db, bill["id"], total=59_000_00, cgst=4_500_00, sgst=4_500_00)

    item = _report(db)["bills"][0]

    assert item["unpaid_paise"] == 59_000_00, "the return is not a debt"
    assert item["supply_value_paise"] == 59_000_00
    assert item["reversal"]["total_paise"] == 9_000_00
    assert item["reversal"]["cgst_paise"] == 4_500_00
    assert item["reversal"]["sgst_paise"] == 4_500_00


def test_a_bill_returned_in_full_reverses_nothing(db):
    """Nothing is owed and no credit is still availed, so Rule 37 has no work.
    Reporting it would send the CA to reverse credit already reversed."""
    bill = _bill(db, "B-1", debited=118_000_00)
    _debit_note(db, bill["id"], total=118_000_00, cgst=9_000_00, sgst=9_000_00)

    assert _report(db)["bill_count"] == 0


def test_an_undercharge_credit_note_increases_what_must_be_reversed(db):
    """§34(3) the other way: the supplier billed too little and corrected it.
    More is owed and more credit was taken, so more falls to be reversed."""
    bill = _bill(db, "B-1", credit_note=11_800_00)
    _purchase_credit_note(db, bill["id"], total=11_800_00, cgst=900_00, sgst=900_00)

    item = _report(db)["bills"][0]

    assert item["unpaid_paise"] == 129_800_00
    assert item["reversal"]["total_paise"] == 19_800_00


def test_a_cancelled_note_adjusts_nothing(db):
    """A cancelled note has no journal behind it, so netting it would
    under-reverse — the direction that carries §50 interest."""
    bill = _bill(db, "B-1")
    _debit_note(db, bill["id"], total=59_000_00, cgst=4_500_00, sgst=4_500_00,
                status="cancelled")

    assert _report(db)["bills"][0]["reversal"]["total_paise"] == 18_000_00


def test_a_deleted_note_adjusts_nothing(db):
    bill = _bill(db, "B-1")
    _debit_note(db, bill["id"], total=59_000_00, cgst=4_500_00, sgst=4_500_00,
                deleted_at="2026-02-01T00:00:00Z")

    assert _report(db)["bills"][0]["reversal"]["total_paise"] == 18_000_00


def test_a_note_against_another_bill_does_not_reach_this_one(db):
    b1 = _bill(db, "B-1")
    b2 = _bill(db, "B-2")
    _debit_note(db, b2["id"], total=59_000_00, cgst=4_500_00, sgst=4_500_00)

    by_no = {i["bill_no"]: i for i in _report(db)["bills"]}
    assert by_no["B-1"]["reversal"]["total_paise"] == 18_000_00


def test_a_note_with_no_bill_link_is_a_vendor_adjustment_not_this_supply(db):
    """It moves the vendor account, so there is no supply for Rule 37 to net it
    against — netting it would under-reverse a bill it says nothing about."""
    _bill(db, "B-1")
    _debit_note(db, None, total=59_000_00, cgst=4_500_00, sgst=4_500_00)

    assert _report(db)["bills"][0]["reversal"]["total_paise"] == 18_000_00


def test_part_paid_and_part_returned_together(db):
    """Both adjustments at once, which is where taking only one of them shows.

    ₹1,18,000 billed, ₹59,000 returned, ₹29,500 paid against the balance. The
    supplier is owed ₹29,500 of a ₹59,000 supply carrying ₹9,000 of credit still
    availed, so half of that ₹9,000 reverses.
    """
    bill = _bill(db, "B-1", debited=59_000_00, paid=29_500_00)
    _debit_note(db, bill["id"], total=59_000_00, cgst=4_500_00, sgst=4_500_00)

    item = _report(db)["bills"][0]

    assert item["unpaid_paise"] == 29_500_00
    assert item["supply_value_paise"] == 59_000_00
    assert item["reversal"]["total_paise"] == 4_500_00


def test_the_notes_are_read_in_bulk_not_once_per_bill(db):
    """CLAUDE.md's reporting rule. A per-bill lookup would be a Singapore-to-
    Mumbai round trip each, on a report that already walks every live bill."""
    for i in range(1, 26):
        b = _bill(db, f"B-{i:02d}")
        _debit_note(db, b["id"], total=1_000_00, cgst=100_00)

    calls = {"n": 0}
    real = db.table

    def counting(name):
        if name in ("debit_notes", "purchase_credit_notes"):
            calls["n"] += 1
        return real(name)

    db.table = counting
    out = _report(db)

    assert out["bill_count"] == 25
    assert calls["n"] == 2, (
        f"{calls['n']} note reads for 25 bills — one per note table is the "
        "budget, whatever the book size"
    )
