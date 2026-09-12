"""
The purchase-bill TDS preview answers exactly what the save will withhold.

WHY THIS IS A TEST AND NOT A COMMENT
    The bill editor showed its own figure: `estimateForeignTds(base,
    vendor.tds_rate_bps)` — the vendor's stored rate times the taxable value,
    in the browser. The server does not compute that. It branches on RESIDENCY
    first, and then applies, for a resident, the section's threshold, the
    year's AGGREGATE and the s.206AA no-PAN floor; for a non-resident, s.195 by
    the nature of the income with surcharge and cess, or a refusal.

    So the preview and the save disagreed in every case that is not "a plain
    bill, above the threshold, PAN on file, first of the year" — which is the
    minority of real bills. A sub-threshold s.194J bill previewed tax and saved
    zero. The CA approved one number; the ledger recorded another (TDS-14).

    The fix is that both go through _compute_bill_lines_and_totals. This file
    is what holds them there: every case below asserts the PREVIEW equals the
    SAVE, computed independently through create_purchase_bill, rather than
    asserting a figure this file believes in. A test that named the numbers
    would keep passing if the two paths diverged again, so long as one of them
    still produced the expected answer.
"""
import pytest

import routers.purchase_bills as pb
from models.invoices import PurchaseBillIn, PurchaseBillLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z2"})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Services", "kind": "service"})
    return db


def _vendor(db, section, pan="ABCCD1234E", vid=None, applicable=True):
    return db.seed("vendors", {
        "id": vid or f"V-{section}-{pan}", "firm_id": FIRM, "client_id": "CLI", "name": "Vendor",
        "state_code": "27", "gstin": "27CCCCC2222C1Z5",
        "tds_applicable": applicable, "tds_section": section, "pan": pan,
        # The dead field the browser used to read. Deliberately WRONG here — it
        # is 2% (the s.194C company rate) on every vendor below, whatever their
        # section or payee type. Any assertion that passes because of it is
        # measuring the defect, not the fix.
        "tds_rate_bps": 200,
    })["id"]


def _payload(vendor_id, rate_paise, bill_no=None, bill_date="2025-06-10"):
    return PurchaseBillIn(
        client_id="CLI", vendor_id=vendor_id, bill_date=bill_date, bill_no=bill_no,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="svc",
                                  rate_paise=rate_paise, quantity=1, gst_rate_percent=18.0)],
    )


def _preview(vendor_id, rate_paise, bill_date="2025-06-10"):
    resp = pb.preview_purchase_bill_tds(_payload(vendor_id, rate_paise, bill_date=bill_date),
                                        None, CALLER)
    assert resp["success"], resp["error"]
    return resp["data"]


def _save(vendor_id, rate_paise, bill_no, bill_date="2025-06-10"):
    return pb.create_purchase_bill(_payload(vendor_id, rate_paise, bill_no, bill_date), CALLER)["data"]


def _assert_agrees(preview: dict, saved: dict):
    """The four figures a CA reads off the summary, and the section under them."""
    for field in ("tds_paise", "tds_rate_bps", "tds_section",
                  "tds_surcharge_paise", "tds_cess_paise",
                  "taxable_amount_paise", "total_paise", "net_payable_paise"):
        assert preview[field] == saved[field], (
            f"{field}: preview {preview[field]!r} but the save wrote {saved[field]!r}")


# ── The cases the browser's rate x base could not get right ─────────────────

def test_below_the_threshold_the_preview_shows_nothing_because_nothing_is_withheld(monkeypatch):
    """s.194J's limit is Rs 50,000 (FA 2025). The browser previewed 2% of
    Rs 40,000 = Rs 800 and the save wrote zero."""
    db = _setup(monkeypatch)
    v = _vendor(db, "194J")
    preview = _preview(v, 40_000_00)
    assert preview["tds_paise"] == 0
    _assert_agrees(preview, _save(v, 40_000_00, "B1"))


def test_above_the_threshold_the_rate_is_the_section_s_not_the_vendor_row_s(monkeypatch):
    """s.194J is 10%. The vendor row says 200 bps, and the browser believed it."""
    db = _setup(monkeypatch)
    v = _vendor(db, "194J")
    preview = _preview(v, 60_000_00)
    assert preview["tds_rate_bps"] == 1000, "the section's rate, not vendors.tds_rate_bps"
    assert preview["tds_paise"] == 6_000_00
    _assert_agrees(preview, _save(v, 60_000_00, "B1"))


def test_the_preview_moves_once_the_year_s_aggregate_is_crossed(monkeypatch):
    """THE CASE NO BROWSER CALCULATION CAN GET RIGHT.

    s.194C(5) charges where "the aggregate of the amounts of such sums credited
    or paid" exceeds one lakh. Below that, and with each single sum within
    Rs 30,000, nothing is deducted — and then the bill that crosses carries tax
    on the WHOLE aggregate, crediting what earlier bills withheld (s.200).

    So the same vendor and the same amount deduct DIFFERENTLY depending on what
    else was billed that year, and the browser has none of that history. It
    previewed 2% of each bill, every time.
    """
    db = _setup(monkeypatch)
    v = _vendor(db, "194C", vid="V-AGG")

    first = _preview(v, 25_000_00)
    assert first["tds_paise"] == 0, "within the single-sum limit and under the aggregate"
    _assert_agrees(first, _save(v, 25_000_00, "A1"))

    for n in range(2, 5):                      # A2..A4, taking the year to Rs 1,00,000
        _assert_agrees(_preview(v, 25_000_00), _save(v, 25_000_00, f"A{n}"))

    # The fifth crosses Rs 1,00,000, so the charge is on the aggregate.
    crossing = _preview(v, 25_000_00)
    assert crossing["tds_paise"] > 0, "the bill that crosses the aggregate must withhold"
    _assert_agrees(crossing, _save(v, 25_000_00, "A5"))


def test_no_pan_floors_the_preview_at_the_s_206aa_rate(monkeypatch):
    """s.206AA: no PAN on file floors the rate at 20%. The browser had no PAN
    awareness at all and previewed the section rate."""
    db = _setup(monkeypatch)
    v = _vendor(db, "194J", pan="", vid="V-NOPAN")
    preview = _preview(v, 60_000_00)
    assert preview["tds_rate_bps"] == 2000, "s.206AA floors it at 20%"
    _assert_agrees(preview, _save(v, 60_000_00, "B1"))


def test_a_company_payee_and_an_individual_payee_differ_on_the_same_section(monkeypatch):
    """s.194C is 1% to an individual or HUF and 2% to anyone else. The vendor
    row carried 200 bps for both."""
    db = _setup(monkeypatch)
    company = _vendor(db, "194C", pan="ABCCD1234E", vid="V-CO")     # 4th char C = company
    individual = _vendor(db, "194C", pan="ABCPD1234E", vid="V-IND")  # 4th char P = individual

    co = _preview(company, 2_00_000_00)
    ind = _preview(individual, 2_00_000_00)
    assert co["tds_rate_bps"] != ind["tds_rate_bps"], (
        "the payee type changes the rate on this section, and the browser's "
        "single stored rate could not express that")
    _assert_agrees(co, _save(company, 2_00_000_00, "C1"))
    _assert_agrees(ind, _save(individual, 2_00_000_00, "I1"))


def test_a_vendor_with_tds_switched_off_previews_nothing(monkeypatch):
    db = _setup(monkeypatch)
    v = _vendor(db, "194J", vid="V-OFF", applicable=False)
    preview = _preview(v, 60_000_00)
    assert preview["tds_paise"] == 0
    _assert_agrees(preview, _save(v, 60_000_00, "B1"))


# ── What the preview says BESIDE the figure ─────────────────────────────────

def test_the_preview_carries_the_reason_not_just_the_number(monkeypatch):
    """A number with no reason is a number a CA cannot check — and this one
    moves with the year's running total, so "why is it different from last
    month" is the first question it invites."""
    db = _setup(monkeypatch)
    v = _vendor(db, "194J")
    preview = _preview(v, 60_000_00)
    assert preview.get("tds_basis"), "the engine's own sentence must come with the figure"
    assert "tds_shortfall_paise" in preview, (
        "an under-deduction the bill was too small to carry is reported, not "
        "left to be inferred from a net payable of nil — s.201(1A) runs at 1% "
        "a month until it is deducted")


def test_the_preview_writes_nothing(monkeypatch):
    """It is a preview. A CA editing a draft triggers one on every pause in
    typing, and a preview that touched the books would post a bill per
    keystroke."""
    db = _setup(monkeypatch)
    v = _vendor(db, "194J")
    before = len(db.rows("purchase_bills"))
    _preview(v, 60_000_00)
    _preview(v, 90_000_00)
    assert len(db.rows("purchase_bills")) == before
    assert len(db.rows("journal_entries")) == 0
    assert len(db.rows("tds_deductions")) == 0


def test_an_unknown_section_is_refused_in_the_preview_as_it_is_on_save(monkeypatch):
    """The refusal is the useful half: it arrives while the CA can still act on
    it, rather than after they have pressed Save."""
    db = _setup(monkeypatch)
    v = _vendor(db, "194IB", vid="V-UNK")      # a section the engine does not hold
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as preview_err:
        pb.preview_purchase_bill_tds(_payload(v, 60_000_00), None, CALLER)
    with pytest.raises(HTTPException) as save_err:
        pb.create_purchase_bill(_payload(v, 60_000_00, "B1"), CALLER)
    assert preview_err.value.status_code == save_err.value.status_code == 422
    assert str(preview_err.value.detail) == str(save_err.value.detail), (
        "the preview must refuse with the SAME sentence the save refuses with, "
        "or a CA fixes the wrong thing")
