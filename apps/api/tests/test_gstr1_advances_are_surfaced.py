"""Advances received against no invoice are named, and no tax is invented.

WHAT WAS WRONG
    GSTR-1 Tables 11A and 11B were absent from the payload, and nothing
    anywhere told a CA that. A client who took advances saw an empty Table 11
    and had no way to tell whether that meant "no advances" or "not computed".

WHY THIS REPORTS RATHER THAN COMPUTING
    An 11A row needs the place of supply, the inter/intra split, the RATE and
    the tax — every one of them a property of a supply that has not happened
    yet. `receipts` holds an amount, a customer and a date. A guessed rate on
    an advance is a guessed tax liability on a filed return, so this names the
    advances and stops.

    Even with a rate a blanket computation would be wrong. CGST Act §13(2)
    makes an advance for SERVICES taxable when received; Notification
    66/2017-Central Tax removed the charge for GOODS, where the liability
    arises at the invoice instead (§12(2) proviso). Two clients with identical
    receipts can owe different tax, and which is which is a fact about their
    business rather than about their ledger.
"""
import pytest

import routers.gst_workspace as gw
import services.gst_advance_service as svc
from tests.e2e_harness import FakeDB, wire_e2e

FIRM, CLIENT = "FIRM-A", "CLI"
PERIOD = "062025"


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [gw])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": CLIENT,
                         "name": "Acme", "gstin": "27BBBBB1111B1Z5",
                         "state_code": "27", "is_active": True})
    return d


def _receipt(db, no, date, amount, allocated):
    return db.seed("receipts", {
        "firm_id": FIRM, "client_id": CLIENT, "customer_id": "CUST",
        "receipt_no": no, "receipt_date": date, "amount_paise": amount,
        "allocated_paise": allocated,
        "unallocated_paise": amount - allocated})


def _run(db, period=PERIOD):
    return svc.advances_report(db, FIRM, CLIENT, period)


# ── what it finds ────────────────────────────────────────────────────────────

def test_an_unallocated_receipt_is_reported_as_an_advance(db):
    _receipt(db, "RCT-1", "2025-06-10", 1_00_000, 0)
    out = _run(db)
    assert out["count"] == 1
    assert out["total_unadjusted_paise"] == 1_00_000
    a = out["unadjusted_advances"][0]
    assert a["receipt_no"] == "RCT-1"
    assert a["customer_name"] == "Acme"
    assert a["unadjusted_paise"] == 1_00_000


def test_a_partly_allocated_receipt_reports_only_what_is_left(db):
    _receipt(db, "RCT-1", "2025-06-10", 1_00_000, 40_000)
    out = _run(db)
    assert out["count"] == 1
    assert out["unadjusted_advances"][0]["unadjusted_paise"] == 60_000
    assert out["unadjusted_advances"][0]["amount_paise"] == 1_00_000


def test_a_fully_allocated_receipt_is_not_an_advance(db):
    """It paid an invoice. There is nothing outstanding to declare."""
    _receipt(db, "RCT-1", "2025-06-10", 1_00_000, 1_00_000)
    assert _run(db)["count"] == 0


def test_a_receipt_from_another_period_is_not_reported(db):
    _receipt(db, "RCT-1", "2025-05-31", 1_00_000, 0)
    _receipt(db, "RCT-2", "2025-07-01", 2_00_000, 0)
    _receipt(db, "RCT-3", "2025-06-15", 3_00_000, 0)
    out = _run(db)
    assert [a["receipt_no"] for a in out["unadjusted_advances"]] == ["RCT-3"]


def test_several_advances_are_totalled_and_ordered_by_date(db):
    _receipt(db, "RCT-B", "2025-06-20", 2_00_000, 0)
    _receipt(db, "RCT-A", "2025-06-05", 1_00_000, 0)
    out = _run(db)
    assert [a["receipt_no"] for a in out["unadjusted_advances"]] == ["RCT-A", "RCT-B"]
    assert out["total_unadjusted_paise"] == 3_00_000


def test_a_period_with_no_advances_says_so_plainly(db):
    out = _run(db)
    assert out["count"] == 0 and out["unadjusted_advances"] == []


# ── what it must NOT do ──────────────────────────────────────────────────────

def test_no_tax_figure_is_produced_anywhere(db):
    """The whole point. A rate cannot be derived from a receipt, so no tax
    field may appear — an invented one is an invented liability."""
    _receipt(db, "RCT-1", "2025-06-10", 1_00_000, 0)
    out = _run(db)
    forbidden = {"iamt", "camt", "samt", "csamt", "rt", "rate", "tax_paise",
                 "igst_paise", "cgst_paise", "sgst_paise", "pos",
                 "place_of_supply"}
    assert not (forbidden & set(out)), sorted(forbidden & set(out))
    for a in out["unadjusted_advances"]:
        assert not (forbidden & set(a)), sorted(forbidden & set(a))


def test_it_states_that_table_11_is_not_computed(db):
    """An empty Table 11 is ambiguous — no advances, or nothing computing it.
    The answer has to travel with the data, not live in a docstring."""
    out = _run(db)
    assert out["table_11_computed"] is False
    assert "66/2017" in out["why"], out["why"]
    assert "13(2)" in out["why"]
    assert out["ca_review_required"] is True


def test_another_firms_receipt_is_not_visible(db):
    r = _receipt(db, "RCT-X", "2025-06-10", 5_00_000, 0)
    db.table("receipts").update({"firm_id": "FIRM-B"}).eq("id", r["id"]).execute()
    assert _run(db)["count"] == 0


def test_another_clients_receipt_is_not_visible(db):
    r = _receipt(db, "RCT-Y", "2025-06-10", 5_00_000, 0)
    db.table("receipts").update({"client_id": "CLI-2"}).eq("id", r["id"]).execute()
    assert _run(db)["count"] == 0


# ── the route ────────────────────────────────────────────────────────────────

def test_the_route_is_registered():
    from main import app
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/api/gst-workspace/gstr1/advances" in paths
