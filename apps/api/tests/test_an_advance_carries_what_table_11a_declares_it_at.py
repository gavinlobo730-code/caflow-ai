"""
An advance is declared at a rate and a place of supply, and both are recorded.

WHAT WAS WRONG
    Migration 286 added receipts.gst_rate_bps, receipts.place_of_supply and
    receipts.is_interstate, and clients.gst_advance_tax_applicable.
    gst_advance_service.table_11_sections has read all four ever since.

    NOTHING HAS EVER WRITTEN ANY OF THEM.

      * The three receipt columns were absent from ReceiptIn, from both receipt
        payloads in services/receipt_service.py and from the frontend. The only
        place they were ever set was a test fixture seeding the database
        directly — so the feature was green in CI and dead in production.
      * clients.gst_advance_tax_applicable was read in exactly one place and
        written in none: no model field, no endpoint, no screen. So the branch
        that gates Table 11 could never be true for any client, and the three
        receipt columns would have been unread even if something had written
        them.

    That is the same shape as ReceiptIn.bank_account_id (SALES-08), which the
    API accepted and the service dropped — except this one went a layer further,
    because the switch that turns the whole table on had no way to be set.

WHAT IS STILL REFUSED
    Nothing is guessed. An advance with no rate or no place of supply is
    RECORDED and REPORTED, never declared: CGST s.13(2) charges the tax when the
    advance is received, and the rate and the place of supply are what the row
    is declared at. A guessed rate is a guessed liability on a filed return.
    What changed is that the skip is now named instead of silent.

WHY THE DEFAULT STAYS OFF
    Notification 66/2017-Central Tax removed the charge on advances for GOODS,
    where the liability arises at the invoice instead (s.12(2) proviso). Most
    registered persons therefore have no Table 11 at all, and demanding a rate
    on every receipt would be three boxes of noise on every goods client.
"""
from __future__ import annotations

import pytest

import services.gst_advance_service as svc
import services.gst_return_service as grs
from models.client import ClientUpdate
from models.invoices import ReceiptIn
from tests.e2e_harness import FakeDB, wire_e2e

FIRM, CLIENT = "FIRM-A", "CLI"
PERIOD = "062025"
GSTIN = "27AAAAA0000A1Z2"


# ── The model accepts them, and checks what it can ──────────────────────────

def _receipt_in(**over):
    body = dict(client_id=CLIENT, customer_id="CUST", receipt_date="2025-06-10",
                amount_paise=1_18_000)
    body.update(over)
    return ReceiptIn(**body)


def test_the_three_table_11a_fields_are_accepted():
    r = _receipt_in(gst_rate_bps=1800, place_of_supply="27", is_interstate=False)
    assert r.gst_rate_bps == 1800
    assert r.place_of_supply == "27"
    assert r.is_interstate is False


def test_they_are_optional():
    r = _receipt_in()
    assert r.gst_rate_bps is None and r.place_of_supply is None


def test_a_rate_outside_the_possible_range_is_refused():
    """1800 is 18%. A caller sending 18 means 0.18% and one sending 180000 has
    mixed units — both produce a wrong liability rather than an error."""
    for bad in (-1, 10001):
        with pytest.raises(ValueError) as e:
            _receipt_in(gst_rate_bps=bad)
        assert "BASIS POINTS" in str(e.value)


def test_the_rate_is_bounded_and_not_enumerated():
    """CLAUDE.md: GST rate slabs are per-line on the document and deliberately
    NOT a central table here. A list of allowed rates would be the thing that
    file says not to build, and would refuse a rate a notification adds."""
    assert _receipt_in(gst_rate_bps=250).gst_rate_bps == 250     # 2.5%
    assert _receipt_in(gst_rate_bps=0).gst_rate_bps == 0
    assert _receipt_in(gst_rate_bps=10000).gst_rate_bps == 10000


def test_a_place_of_supply_that_is_not_a_state_is_refused():
    with pytest.raises(ValueError) as e:
        _receipt_in(place_of_supply="99")
    assert "state code" in str(e.value)


def test_a_blank_place_of_supply_is_absence_not_a_value():
    assert _receipt_in(place_of_supply="  ").place_of_supply is None


# ── The service writes them ─────────────────────────────────────────────────

def test_the_receipt_payload_carries_all_three():
    """The defect, at the layer it lived in: the model accepted them and the
    payload dropped them."""
    import inspect
    src = inspect.getsource(__import__("services.receipt_service", fromlist=["x"]))
    for field in ("gst_rate_bps", "place_of_supply", "is_interstate"):
        assert src.count(f'"{field}"') >= 2, (
            f"{field} must be written by BOTH receipt payloads — the rupee path "
            f"and the foreign-currency one. A s.13(2) advance can be in either.")


# ── The client switch can be set at all ─────────────────────────────────────

def test_the_client_flag_is_a_settable_field():
    assert ClientUpdate(gst_advance_tax_applicable=True).gst_advance_tax_applicable is True


def test_switching_it_OFF_is_not_the_same_as_not_saying():
    """update_client filters on `is not None`, so False survives and None does
    not. A client who stops supplying services has to be able to turn it off."""
    assert ClientUpdate(gst_advance_tax_applicable=False).gst_advance_tax_applicable is False
    assert ClientUpdate().gst_advance_tax_applicable is None


# ── What cannot be declared is named ────────────────────────────────────────

@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [svc, grs])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": CLIENT,
                         "name": "Acme", "gstin": "27BBBBB1111B1ZN",
                         "state_code": "27", "is_active": True})
    return d


def _client(db, *, applicable):
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM, "gstin": GSTIN,
                        "state_code": "27", "financial_year_start": "2025-04-01",
                        "gst_advance_tax_applicable": applicable})


def _advance(db, no, **over):
    row = {"firm_id": FIRM, "client_id": CLIENT, "customer_id": "CUST",
           "receipt_no": no, "receipt_date": "2025-06-10",
           "amount_paise": 1_18_000, "allocated_paise": 0,
           "unallocated_paise": 1_18_000,
           "gst_rate_bps": 1800, "place_of_supply": "27", "is_interstate": False}
    row.update(over)
    return db.seed("receipts", row)


def test_an_advance_with_no_rate_is_named_rather_than_skipped(db):
    _client(db, applicable=True)
    _advance(db, "RCT-1", gst_rate_bps=None)
    out = svc.table_11_sections(db, FIRM, CLIENT, PERIOD)
    assert out["at"] == []
    assert len(out["gaps"]) == 1
    assert out["gaps"][0]["kind"] == "TABLE_11A"
    assert "no GST rate" in out["gaps"][0]["reason"]
    assert "13(2)" in out["gaps"][0]["reason"]


def test_an_advance_with_no_place_of_supply_is_named(db):
    _client(db, applicable=True)
    _advance(db, "RCT-1", place_of_supply=None)
    gaps = svc.table_11_sections(db, FIRM, CLIENT, PERIOD)["gaps"]
    assert len(gaps) == 1 and "no place of supply" in gaps[0]["reason"]


def test_an_advance_missing_both_says_both(db):
    _client(db, applicable=True)
    _advance(db, "RCT-1", gst_rate_bps=None, place_of_supply=None)
    reason = svc.table_11_sections(db, FIRM, CLIENT, PERIOD)["gaps"][0]["reason"]
    assert "no GST rate" in reason and "no place of supply" in reason


def test_a_complete_advance_is_declared_and_not_reported(db):
    _client(db, applicable=True)
    _advance(db, "RCT-1")
    out = svc.table_11_sections(db, FIRM, CLIENT, PERIOD)
    assert out["at"] and out["gaps"] == []


def test_a_goods_client_gets_neither_a_row_nor_a_gap(db):
    """Notification 66/2017. An advance for goods is not undeclared, it is not
    chargeable — a warning here would land on every receipt of every goods
    client on the platform."""
    _client(db, applicable=False)
    _advance(db, "RCT-1", gst_rate_bps=None, place_of_supply=None)
    out = svc.table_11_sections(db, FIRM, CLIENT, PERIOD)
    assert out["applicable"] is False and out["gaps"] == []


def test_the_gap_reaches_the_return_the_ca_looks_at(db):
    """A figure the service gets right and no screen shows is not a fixed bug.
    gstr1_from_books folds these into the same payload_gaps list the builder's
    own omissions use."""
    _client(db, applicable=True)
    _advance(db, "RCT-1", gst_rate_bps=None)
    out = grs.gstr1_from_books(db, FIRM, CLIENT, PERIOD, GSTIN)
    assert [g["kind"] for g in out["payload_gaps"]] == ["TABLE_11A"]
