"""
§37(3) has two limbs, and only one of them was ever asked (GST-09).

WHAT WAS WRONG
    CGST §37(3), §39(9) and §16(4) each close a period's correction window on
    30 November following the financial year **or on the date the annual return
    is furnished, whichever is EARLIER** (Finance Act 2022). The engine knew
    that: `correction_window_closes` implements it and `window_for` accepts the
    date. Nothing ever supplied one. `outstanding_amendments` declared an
    `annual_return_filed_on` parameter and no production caller passed it, so
    every window came back as the 30 November outer limit and
    `shortened_by_annual_return` was permanently False.

    A client who filed GSTR-9 for FY 2025-26 in August 2026 lost the right to
    amend that year in August. The CA was told the window ran to 30 November,
    would prepare an amendment the portal refuses — and, worse, would believe an
    unclaimed input tax credit was still available under §16(4) when it was not.

TWO THINGS THE OBVIOUS FIX GETS WRONG, BOTH PINNED BELOW
    ONE DATE PER FINANCIAL YEAR, NOT ONE PER CALL. `outstanding_amendments`
    walks every earlier filed period, and those periods straddle financial years
    — a July 2026 return can carry corrections back to March 2026, which is the
    previous FY. The parameter it replaced was a single date applied to all of
    them, which shortens the wrong year.

    THE DATE IS AN IST DATE. `submitted_at` is `timestamptz`, UTC on disk, and
    the statute counts days in India. A return furnished at 20:00 UTC on 30
    November is 01:30 IST on 1 December, and the two readings fall on opposite
    sides of the cutoff.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

import routers.gst_workspace as gw
import services.gst_amendment_service as svc
import services.gst_return_service as grs
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CLIENT = "CLI"
OTHER = "CLI-2"
GSTIN = "27AAAAA0000A1Z5"


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [gw, grs])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("firms", {"id": FIRM, "name": "F", "locked_financial_years": []})
    for cid in (CLIENT, OTHER):
        d.seed("clients", {"id": cid, "firm_id": FIRM, "gstin": GSTIN,
                           "financial_year_start": "2025-04-01", "state_code": "27"})
    d.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": CLIENT, "name": "Acme",
                         "gstin": "27BBBBB1111B1Z5", "state_code": "27", "is_active": True})
    seed_standard_coa(d, FIRM, CLIENT)
    return d


def _invoice(db, invoice_no, invoice_date, taxable, cgst, sgst):
    return db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": CLIENT, "customer_id": "CUST",
        "invoice_no": invoice_no, "invoice_date": invoice_date, "status": "issued",
        "taxable_amount_paise": taxable, "cgst_paise": cgst, "sgst_paise": sgst,
        "igst_paise": 0, "total_paise": taxable + cgst + sgst,
        "is_interstate": False, "supply_state_code": "27",
        "supply_type": "taxable", "invoice_type": "Regular", "is_reverse_charge": False,
        "deleted_at": None,
    })


def _file_gstr1(db, period):
    payload = grs.gstr1_from_books(db, FIRM, CLIENT, period, GSTIN)["payload"]
    db.seed("gstr1_returns", {
        "firm_id": FIRM, "client_id": CLIENT, "period": period, "gstin": GSTIN,
        "status": "submitted", "payload_json": payload,
        "submitted_at": "2025-01-01T00:00:00Z", "arn": f"ARN{period}",
        "return_type": "gstr1",
    })


def _file_gstr9(db, fy, submitted_at, client_id=CLIENT, status="submitted"):
    db.seed("gstr1_returns", {
        "firm_id": FIRM, "client_id": client_id, "period": f"FY{fy}", "gstin": GSTIN,
        "financial_year": fy, "return_type": "gstr9", "status": status,
        "submitted_at": submitted_at, "arn": f"ARN9{fy}",
    })


def _drifted(db, period, invoice_date):
    """A filed period with real drift in it, so it has something to amend."""
    row = _invoice(db, f"INV-{period}", invoice_date, 100_000, 9_000, 9_000)
    _file_gstr1(db, period)
    db.table("client_sales_invoices").update(
        {"taxable_amount_paise": 150_000}).eq("id", row["id"]).execute()


# ── the resolver ─────────────────────────────────────────────────────────────

def test_a_filed_gstr9_is_found_and_dated(db):
    _file_gstr9(db, "2025-26", "2026-08-15T06:30:00+00:00")
    assert svc.annual_returns_filed(db, FIRM, CLIENT) == {"2025-26": date(2026, 8, 15)}


def test_a_draft_gstr9_shuts_nothing(db):
    """§37(3) turns on the return being FURNISHED. A draft saved in the
    workspace is not furnished."""
    _file_gstr9(db, "2025-26", "2026-08-15T06:30:00+00:00", status="draft")
    assert svc.annual_returns_filed(db, FIRM, CLIENT) == {}


def test_another_clients_gstr9_shuts_nothing(db):
    _file_gstr9(db, "2025-26", "2026-08-15T06:30:00+00:00", client_id=OTHER)
    assert svc.annual_returns_filed(db, FIRM, CLIENT) == {}


def test_a_submitted_row_with_no_date_shuts_nothing(db):
    """Guessing a date would shorten the window wrongly; the 30 November limit
    still applies."""
    _file_gstr9(db, "2025-26", None)
    assert svc.annual_returns_filed(db, FIRM, CLIENT) == {}


def test_the_date_is_the_indian_calendar_date(db):
    """20:00 UTC on 30 November is 01:30 IST on 1 December. The statute counts
    days in India, and these two readings fall on opposite sides of the cutoff.
    """
    _file_gstr9(db, "2025-26", "2026-11-30T20:00:00+00:00")
    assert svc.annual_returns_filed(db, FIRM, CLIENT) == {"2025-26": date(2026, 12, 1)}


def test_a_naive_timestamp_is_read_as_utc_not_as_local(db):
    """PostgREST returns an ISO string with an offset, but a mock source or an
    older row may not carry one. Reading it as IST already would move the date
    back by a day."""
    _file_gstr9(db, "2025-26", "2026-11-30T20:00:00")
    assert svc.annual_returns_filed(db, FIRM, CLIENT) == {"2025-26": date(2026, 12, 1)}


def test_a_datetime_object_is_accepted_too(db):
    _file_gstr9(db, "2025-26", datetime(2026, 8, 15, 6, 30, tzinfo=timezone.utc))
    assert svc.annual_returns_filed(db, FIRM, CLIENT) == {"2025-26": date(2026, 8, 15)}


def test_the_earliest_submission_wins(db):
    """If a year somehow carries two, the window shut when the annual return was
    FIRST furnished."""
    _file_gstr9(db, "2025-26", "2026-10-01T00:00:00+00:00")
    db.seed("gstr1_returns", {
        "firm_id": FIRM, "client_id": CLIENT, "period": "FY2025-26", "gstin": GSTIN,
        "financial_year": "2025-26", "return_type": "gstr9", "status": "submitted",
        "submitted_at": "2026-08-15T00:00:00+00:00", "arn": "ARN9b",
    })
    assert svc.annual_returns_filed(db, FIRM, CLIENT) == {"2025-26": date(2026, 8, 15)}


def test_a_read_failure_leaves_the_statutory_limit_rather_than_raising(db):
    """Deliberately NOT fail-closed, and the direction is argued in the code:
    reporting a correction as expired because a lookup failed sends the CA to
    §16(4) relief they do not need."""
    class _Boom:
        def table(self, _name):
            raise RuntimeError("connection reset")

    assert svc.annual_returns_filed_safely(_Boom(), FIRM, CLIENT) == {}


# ── end to end, which is what the finding is about ───────────────────────────

def test_an_early_gstr9_expires_an_amendment_the_november_limit_would_allow(db):
    """The finding, stated as the CA meets it. Nothing is passed in — the date
    is resolved from the books, which is the half that was missing."""
    _drifted(db, "062025", "2025-06-10")
    _file_gstr9(db, "2025-26", "2026-08-15T00:00:00+00:00")

    out = svc.outstanding_amendments(db, FIRM, CLIENT, "072025", as_of=date(2026, 9, 1))

    assert out["counts"]["amendments"] == 0
    assert out["counts"]["expired_periods"] == 1
    window = out["expired"][0]["window"]
    assert window["closes_on"] == "2026-08-15"
    assert window["shortened_by_annual_return"] is True
    assert window["statutory_cutoff"] == "2026-11-30", (
        "the outer limit is still reported — the CA needs to see WHICH date bit"
    )


def test_without_the_annual_return_the_same_request_is_still_in_time(db):
    """The other half of the pair: proves the annual return is what closed it,
    not the date the question was asked."""
    _drifted(db, "062025", "2025-06-10")

    out = svc.outstanding_amendments(db, FIRM, CLIENT, "072025", as_of=date(2026, 9, 1))

    assert out["counts"]["amendments"] == 1
    assert out["counts"]["expired_periods"] == 0
    assert out["proposals"][0]["window"]["closes_on"] == "2026-11-30"
    assert out["proposals"][0]["window"]["shortened_by_annual_return"] is False


def test_the_annual_return_shortens_only_its_own_financial_year(db):
    """The correction this fix could have got wrong.

    Two drifted periods in DIFFERENT financial years — March 2026 (FY 2025-26)
    and June 2026 (FY 2026-27) — and a GSTR-9 filed for the earlier one only.
    A single date applied to every source period would have expired the later
    year too, three and a half years before its own window closes.
    """
    _drifted(db, "032026", "2026-03-10")
    _drifted(db, "062026", "2026-06-10")
    _file_gstr9(db, "2025-26", "2026-08-15T00:00:00+00:00")

    out = svc.outstanding_amendments(db, FIRM, CLIENT, "092026", as_of=date(2026, 9, 1))

    by_period = {p["original_period"]: p["window"] for p in out["proposals"]}
    by_period.update({e["period"]: e["window"] for e in out["expired"]})

    assert by_period["032026"]["closes_on"] == "2026-08-15", "FY 2025-26 was shut early"
    assert by_period["032026"]["shortened_by_annual_return"] is True
    assert by_period["062026"]["closes_on"] == "2027-11-30", (
        "FY 2026-27 has its own annual return and its own window — the earlier "
        "year's GSTR-9 says nothing about it"
    )
    assert by_period["062026"]["shortened_by_annual_return"] is False


def test_an_explicit_empty_map_asks_the_question_as_if_nothing_were_filed(db):
    """The escape hatch, so a caller can still ask "what if" without the books
    answering for them — and so `None` cannot be mistaken for "no returns"."""
    _drifted(db, "062025", "2025-06-10")
    _file_gstr9(db, "2025-26", "2026-08-15T00:00:00+00:00")

    out = svc.outstanding_amendments(db, FIRM, CLIENT, "072025",
                                     as_of=date(2026, 9, 1), annual_returns_filed={})

    assert out["counts"]["amendments"] == 1
    assert out["proposals"][0]["window"]["closes_on"] == "2026-11-30"
