"""
TDS deducted on a bill has to reach the register a CA files 26Q from.

WHAT WAS BROKEN
    The deduction was computed correctly — the section resolved, the s.194C FY
    aggregate honoured, the rate floored at 20% under s.206AA for a vendor with
    no PAN — and then stopped at purchase_bills.tds_paise. Nothing in this
    codebase had ever written a row to tds_deductions. So the money was
    withheld from the vendor in the books and invisible to compliance: no
    challan to pay by the 7th (Rule 30), nothing to assemble 26Q from
    (Rule 31A), and GET /api/tds/deductions/{client_id} returning an empty list.

    Found by driving one client through a full financial year: twelve job-work
    bills, seven of them deducting, and an empty register.

WHAT IS ASSERTED HERE
    The rule, not the plumbing: WHEN a row exists, what is on it, and that it
    follows the bill rather than snapshotting it.
"""
from datetime import date

import pytest

from services.tds_register_service import IN_THE_BOOKS, fy_quarter, sync_for_bill


class _DB:
    """Records what the service asked the database to do."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.deleted: list[str] = []
        self._pending_delete = False
        self._filters: dict = {}

    def table(self, name):
        assert name == "tds_deductions", name
        self._pending_delete = False
        self._filters = {}
        return self

    def upsert(self, payload, on_conflict=None):
        assert on_conflict == "purchase_bill_id", on_conflict
        self.rows[payload["purchase_bill_id"]] = payload
        return self

    def delete(self):
        self._pending_delete = True
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def execute(self):
        if self._pending_delete:
            bid = self._filters.get("purchase_bill_id")
            self.deleted.append(bid)
            self.rows.pop(bid, None)
        return type("R", (), {"data": []})()


VENDOR = {"id": "v1", "name": "Pinnacle Engineering Services", "pan": "AAGCP7788R"}


def bill(**over):
    base = {
        "id": "b1", "client_id": "c1", "vendor_id": "v1", "status": "received",
        "bill_date": "2025-10-25", "taxable_amount_paise": 18_000_00,
        "total_paise": 21_240_00, "tds_paise": 360_00, "tds_rate_bps": 200,
        "tds_section": "194C",
    }
    base.update(over)
    return base


# ── When a row exists ────────────────────────────────────────────────────────

def test_a_received_bill_that_deducted_gets_a_register_row():
    db = _DB()
    out = sync_for_bill(db, "f1", "c1", bill(), VENDOR)
    assert out["action"] == "recorded"
    assert db.rows["b1"]["tds_paise"] == 360_00


def test_a_draft_bill_gets_no_row_because_nothing_has_been_credited():
    """s.194C(3) and its neighbours: deduct at CREDIT to the payee's account or
    at payment, whichever is earlier. A draft posts no journal entry, so the
    vendor's account has not been credited and no liability has arisen."""
    db = _DB()
    out = sync_for_bill(db, "f1", "c1", bill(status="draft"), VENDOR)
    assert out["action"] == "removed"
    assert db.rows == {}


def test_a_cancelled_bill_loses_its_row():
    """The credit is undone. Leaving the row would file 26Q on tax the books no
    longer say was withheld, and leave a challan to pay for a bill that is gone."""
    db = _DB()
    sync_for_bill(db, "f1", "c1", bill(), VENDOR)
    assert db.rows
    sync_for_bill(db, "f1", "c1", bill(status="cancelled"), VENDOR)
    assert db.rows == {}
    assert "b1" in db.deleted


def test_a_bill_below_the_threshold_gets_no_row():
    """Bills 1-5 of the walkthrough deducted nothing because the s.194C FY
    aggregate was unmet. A zero-value register row would be a nil deduction
    reported to the department."""
    db = _DB()
    out = sync_for_bill(db, "f1", "c1", bill(tds_paise=0, tds_rate_bps=0), VENDOR)
    assert out["action"] == "removed"
    assert db.rows == {}


def test_an_edited_bill_updates_its_row_rather_than_adding_a_second():
    db = _DB()
    sync_for_bill(db, "f1", "c1", bill(), VENDOR)
    sync_for_bill(db, "f1", "c1", bill(tds_paise=720_00, taxable_amount_paise=36_000_00), VENDOR)
    assert len(db.rows) == 1
    assert db.rows["b1"]["tds_paise"] == 720_00


# ── What is on the row ───────────────────────────────────────────────────────

def test_the_amount_is_the_taxable_value_not_the_gross():
    """CBDT Circular 23/2017 of 19-07-2017: where GST is shown separately on the
    invoice, TDS is deducted on the amount EXCLUDING GST. Recording the gross
    would over-state the payment in 26Q and mismatch the vendor's own 26AS."""
    db = _DB()
    sync_for_bill(db, "f1", "c1", bill(), VENDOR)
    row = db.rows["b1"]
    assert row["payment_amount_paise"] == 18_000_00, "the taxable value"
    assert row["payment_amount_paise"] != 21_240_00, "not the GST-inclusive total"


def test_the_rate_is_carried_as_a_percentage_not_basis_points():
    """tds_rate_pct is NUMERIC(5,2). 2,000 bps is 20.00%, and writing 2000 into
    that column would overflow rather than merely mislead."""
    db = _DB()
    sync_for_bill(db, "f1", "c1", bill(tds_rate_bps=2000), VENDOR)
    assert db.rows["b1"]["tds_rate_pct"] == 20.0


def test_the_deductee_is_the_vendor_with_their_pan():
    db = _DB()
    sync_for_bill(db, "f1", "c1", bill(), VENDOR)
    row = db.rows["b1"]
    assert row["deductee_name"] == "Pinnacle Engineering Services"
    assert row["deductee_pan"] == "AAGCP7788R"


def test_a_vendor_with_no_pan_records_no_pan_rather_than_a_blank_string():
    """s.206AA already floored the rate at 20% for this vendor. The register has
    to carry the absence too — 26Q reports a no-PAN deductee differently."""
    db = _DB()
    sync_for_bill(db, "f1", "c1", bill(), {"id": "v1", "name": "X", "pan": ""})
    assert db.rows["b1"]["deductee_pan"] is None


def test_the_transaction_date_is_the_bill_date():
    db = _DB()
    sync_for_bill(db, "f1", "c1", bill(), VENDOR)
    assert db.rows["b1"]["transaction_date"] == "2025-10-25"


def test_it_is_reported_as_26Q():
    """Non-salary payments to residents. 27Q is for non-residents and nothing in
    this schema records a vendor's residency — see the service docstring."""
    db = _DB()
    sync_for_bill(db, "f1", "c1", bill(), VENDOR)
    assert db.rows["b1"]["return_type"] == "26Q"


# ── The quarter, which decides which return it lands in ──────────────────────

@pytest.mark.parametrize("day,expected", [
    ("2025-04-01", "Q1 2025-26"), ("2025-06-30", "Q1 2025-26"),
    ("2025-07-01", "Q2 2025-26"), ("2025-09-30", "Q2 2025-26"),
    ("2025-10-01", "Q3 2025-26"), ("2025-12-31", "Q3 2025-26"),
    ("2026-01-01", "Q4 2025-26"), ("2026-03-31", "Q4 2025-26"),
    ("2026-04-01", "Q1 2026-27"),
])
def test_the_quarter_follows_the_indian_financial_year(day, expected):
    """The FY runs 1 April to 31 March, so Q1 is Apr-Jun — not Jan-Mar. A bill
    dated 31 March belongs in Q4 of the year that is ending, and one dated
    1 April in Q1 of the year beginning; getting that boundary wrong files a
    deduction in the wrong quarter's return."""
    assert fy_quarter(date.fromisoformat(day)) == expected


def test_the_row_carries_the_quarter_it_will_be_filed_in():
    db = _DB()
    sync_for_bill(db, "f1", "c1", bill(bill_date="2026-01-15"), VENDOR)
    assert db.rows["b1"]["quarter"] == "Q4 2025-26"


# ── Failure must not take the bill down with it ──────────────────────────────

def test_a_register_failure_is_reported_not_raised():
    """A bill that posted its journal correctly must not be rolled back because
    the register row could not be written. The deduction is still in the books;
    the register is repaired on the next transition."""
    class _Broken(_DB):
        def execute(self):
            raise RuntimeError("permission denied for table tds_deductions")

    out = sync_for_bill(_Broken(), "f1", "c1", bill(), VENDOR)
    assert out["synced"] is False
    assert "permission denied" in out["reason"]


def test_no_database_is_not_an_error():
    assert sync_for_bill(None, "f1", "c1", bill(), VENDOR)["synced"] is False


def test_the_in_the_books_states_exclude_draft_and_cancelled():
    assert "draft" not in IN_THE_BOOKS and "cancelled" not in IN_THE_BOOKS
    assert "received" in IN_THE_BOOKS and "paid" in IN_THE_BOOKS
