"""
A §17(5)(h) reversal that the GL makes and the return never declares (INV-06).

WHAT WAS WRONG
    A CA writes off ₹2,00,000 of damaged stock and ticks "reverse ITC".
    `post_stock_writeoff_journal_entry` posts Dr Write-off / Cr GST Input,
    citing CGST Act §17(5)(h), and the books show the ₹36,000 credit given
    back. GSTR-3B Table 4(B)(1) showed NOTHING.

    There was no route by which it could. 4(B)(1) is built from cancelled bills
    and blocked credit on bill lines, and the ITC reversal register refused
    permanent grounds outright — migration 285's CHECK listed only reclaimable
    reason codes, and the service's own docstring said Rules 38/42/43 and
    §17(5) "are derived from the documents, not registered here".

    That reasoning is right about a cancelled purchase and WRONG about a stock
    write-off: the supply happened, the credit was taken, and what changed is
    that the goods were destroyed. There is no document to derive it from.

    So the prepared return claimed credit the books had already given back —
    an under-declared reversal, which is exactly the mismatch the electronic
    credit reversal statement at the portal exists to surface.

WHAT THIS FILE PINS
    That the reversal reaches 4(B)(1) and not 4(B)(2) — the two boxes mean
    different things, and a permanent reversal declared as reclaimable leaves a
    balance in that statement which never clears — and that the approximation
    the amount rests on travels with the row instead of being lost.
"""
from __future__ import annotations

import pytest

import services.itc_register_service as reg
from domain import inventory_service as inv
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CLIENT = "CLI"


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    import routers.inventory as inv_router
    wire_e2e(monkeypatch, d, [inv_router])
    d.seed("firms", {"id": FIRM, "name": "F", "locked_financial_years": []})
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM})
    seed_standard_coa(d, FIRM, CLIENT)
    # seed_standard_coa carries GST Input; the write-off needs an Inventory
    # asset and a write-off expense as well.
    d.seed("chart_of_accounts", {
        "id": "acc-woff", "firm_id": FIRM, "client_id": CLIENT,
        "account_code": "5900", "account_name": "Stock Write-off Expense",
        "account_type": "Expense", "is_active": True})
    d.seed("chart_of_accounts", {
        "id": "acc-inv", "firm_id": FIRM, "client_id": CLIENT,
        "account_code": "1400", "account_name": "Inventory",
        "account_type": "Asset", "system_account_key": "inventory",
        "is_active": True})
    return d


def _writeoff(db, *, value=2_00_000_00, rate_bps=1800, reverse=True,
              interstate=False, date="2026-06-15", ref="ADJ-1"):
    return inv.post_stock_writeoff_journal_entry(
        db, firm_id=FIRM, client_id=CLIENT, movement_date=date,
        item_name="Damaged widgets", value_paise=value, gst_rate_bps=rate_bps,
        reverse_itc=reverse, reference_no=ref,
        itc_reversal_is_interstate=interstate,
    )


def _register(db, period="062026"):
    return reg.for_period(db, FIRM, CLIENT, period)


# ── the finding ──────────────────────────────────────────────────────────────

def test_the_reversal_is_declared_in_table_4B1(db):
    """₹2,00,000 of stock at 18% is ₹36,000 of credit given back, and the
    return has to say so."""
    assert _writeoff(db)

    out = _register(db)

    assert len(out["permanent_reversals"]) == 1
    row = out["permanent_reversals"][0]
    assert row["reason_code"] == "section_17_5_h"
    assert out["permanent_reversal_totals"]["cgst_paise"] == 18_000_00
    assert out["permanent_reversal_totals"]["sgst_paise"] == 18_000_00


def test_it_is_not_declared_as_reclaimable(db):
    """4(B)(2) is "ITC that is to be reclaimed ... on a future date". §17(5)(h)
    credit never comes back, and declaring it there would leave a balance in
    the electronic credit reversal statement that never clears."""
    _writeoff(db)

    out = _register(db)

    assert out["reversals"] == []
    assert out["reversal_totals"]["cgst_paise"] == 0


def test_an_interstate_purchase_is_declared_as_igst(db):
    _writeoff(db, interstate=True)

    out = _register(db)

    assert out["permanent_reversal_totals"]["igst_paise"] == 36_000_00
    assert out["permanent_reversal_totals"]["cgst_paise"] == 0


def test_the_two_heads_add_back_to_what_the_journal_moved(db):
    """An odd number of paise must not vanish in the halving: the register
    checks every row against its own journal, so a rounding leak would refuse
    the row outright and put us back where we started."""
    # 1 paise at 18% would round to nothing; ₹333.33 at 18% gives an odd figure.
    assert _writeoff(db, value=33_333, rate_bps=1800)

    row = _register(db)["permanent_reversals"][0]

    assert row["cgst_paise"] + row["sgst_paise"] == 6_000
    assert abs(row["cgst_paise"] - row["sgst_paise"]) <= 1


def test_not_ticking_reverse_itc_declares_nothing(db):
    """The reversal is a CA judgement (§17(5)(h) applies to loss, theft,
    destruction and free samples — not to every decrease). Registering one
    nobody asked for would put a figure on a return the CA never decided."""
    assert _writeoff(db, reverse=False)

    assert _register(db)["permanent_reversals"] == []


def test_the_approximation_travels_with_the_row(db):
    """The amount is derived from the ITEM's own rate, not from the purchase
    invoices, and the head split is a default. Both are caveats a CA needs at
    the point they read the figure — losing them is how an approximation
    becomes a number somebody trusts."""
    _writeoff(db)

    notes = _register(db)["permanent_reversals"][0]["notes"]

    assert "APPROXIMATED" in notes
    assert "18%" in notes
    assert "CGST + SGST" in notes
    assert "Damaged widgets" in notes


def test_the_row_points_at_the_journal_that_moved_the_credit(db):
    """The register's whole integrity check is that a declared figure is backed
    by a posting. A row with no journal is a return figure the ledger cannot
    support."""
    journal_id = _writeoff(db)

    assert _register(db)["permanent_reversals"][0]["journal_entry_id"] == journal_id


def test_the_period_is_the_month_the_stock_was_written_off(db):
    """Not the month the CA happens to be preparing. Rule 42/43's timing is per
    tax period, and a reversal declared in the wrong month is a wrong return in
    two months rather than one."""
    _writeoff(db, date="2026-03-31")

    assert _register(db, "032026")["permanent_reversals"] != []
    assert _register(db, "062026")["permanent_reversals"] == []


def test_a_failed_registration_does_not_take_the_write_off_down(db, monkeypatch):
    """Fail-soft, like everything else on this path. The stock movement and its
    journal are the FACT; the declaration can be added by hand. Losing the
    write-off because a register row would not write is the worse trade."""
    def _boom(*_a, **_k):
        raise RuntimeError("register unavailable")

    monkeypatch.setattr(reg, "record_reversal", _boom)

    assert _writeoff(db), "the journal must still post"
