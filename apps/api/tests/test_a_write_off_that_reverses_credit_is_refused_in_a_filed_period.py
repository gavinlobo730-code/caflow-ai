"""A stock write-off that reverses input tax credit is a document that feeds a return (POST-A-089).

WHAT WAS MISSING
    `adjust_stock` asked only the FIRM's financial-year lock. A write-off that REVERSES ITC (CGST Act s.17(5)(h);
    `reverse_itc`) posts Dr write-off / Cr GST Input and registers the reversal that GSTR-3B Table 4(B) declares for the
    month, so dated inside a month whose return had been filed it put a reversal in the books that the return never
    carried. A plain stock adjustment (a count correction, a free sample) moves inventory and the P&L and declares
    nothing, so it is deliberately NOT asked: migration 361's argument is that refusing every dated bookkeeping entry from the
    11th of the next month would stop routine work. The question is the EFFECT, not the flag: the reversal is registered only
    for a decrease, marked by the CA, on an item with a non-zero rate (`domain/inventory/adjustment_effect`), and the count sheet
    asks the same thing, so one shortage gets one answer on both doors.

WHAT IS HELD
    * a reversing write-off dated inside a filed period is refused with the return named, and nothing is recorded;
    * a plain adjustment dated in the same filed period still goes through;
    * a reversing write-off dated in an open period still goes through;
    * a write-off marked to reverse credit on an item at no GST rate declares nothing, so it is not refused either.
"""
import pytest
from fastapi import HTTPException

import routers.inventory as inv
from models.inventory import StockAdjustmentIn
from tests.test_inventory_adjustment_router import CALLER, FIRM, _seed_opening_stock, _setup


def _file_gstr3b_for_april(db):
    db.seed("filings", {
        "firm_id": FIRM, "client_id": "CLI", "filing_type": "GSTR-3B",
        "period_start": "2026-04-01", "period_end": "2026-04-30",
        "filed_date": "2026-05-20", "status": "filed", "deleted_at": None,
    })


def _adjust(date, reverse_itc):
    return inv.adjust_stock("PROD-1", StockAdjustmentIn(
        client_id="CLI", adjustment_date=date, quantity=3, direction="decrease",
        reason="destroyed", reverse_itc=reverse_itc), CALLER)


def test_a_reversing_write_off_dated_inside_a_filed_period_is_refused(monkeypatch):
    db = _setup(monkeypatch)
    _seed_opening_stock(db, qty="10")
    _file_gstr3b_for_april(db)

    with pytest.raises(HTTPException) as refused:
        _adjust("2026-04-20", reverse_itc=True)

    assert refused.value.status_code == 422
    assert "GSTR-3B" in refused.value.detail
    assert [r for r in db.rows("inventory_stock_ledger") if r.get("movement_type") == "adjustment"] == []
    assert db.rows("journal_entries") == []


def test_a_plain_adjustment_in_the_same_filed_period_still_goes_through(monkeypatch):
    db = _setup(monkeypatch)
    _seed_opening_stock(db, qty="10")
    _file_gstr3b_for_april(db)

    assert _adjust("2026-04-20", reverse_itc=False)["success"] is True
    assert len([r for r in db.rows("inventory_stock_ledger") if r.get("movement_type") == "adjustment"]) == 1


def test_a_reversing_write_off_in_an_open_period_still_goes_through(monkeypatch):
    db = _setup(monkeypatch)
    _seed_opening_stock(db, qty="10")
    _file_gstr3b_for_april(db)

    assert _adjust("2026-05-10", reverse_itc=True)["success"] is True


def test_a_reversing_write_off_of_an_item_at_no_rate_declares_nothing_so_it_goes_through(monkeypatch):
    db = _setup(monkeypatch)
    _seed_opening_stock(db, qty="10")
    _file_gstr3b_for_april(db)
    for item in db.rows("service_catalogue"):
        if item["id"] == "PROD-1":
            item["gst_rate_bps"] = 0

    assert _adjust("2026-04-20", reverse_itc=True)["success"] is True
    journals = db.rows("journal_entries")
    assert journals, "the write-off itself is still booked"
