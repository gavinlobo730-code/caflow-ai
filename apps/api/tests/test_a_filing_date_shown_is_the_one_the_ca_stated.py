"""A screen that prints when a GSTR-1 was filed prints the date the CA stated, and says "recorded" when that is all it has (found by seeding a filed year).

WHAT WAS WRONG
    The GSTR-3B tie-out and the GSTR-1 exception report both answered `filed_at` from `gstr1_returns.submitted_at`, which
    is the instant somebody pressed "mark filed" in this product, and the tie-out screen printed the first ten characters
    of it beside the ARN: "Tied to the filed GSTR-1 (ARN … · 2026-10-19)". For a return keyed in after the fact (every
    migrated client's first months, any return recorded the next morning) that is not the day it was filed, and a UTC
    slice is the wrong calendar day for the five and a half hours after midnight in India besides. The date the CA typed
    when recording the filing (PRE-A-007: required, never defaulted, checked against the period) lives in
    `filings.filed_date`, which is what the period lock reads, and the screen never looked at it. Seeding a filed year made
    every row read as filed on the day of the seeding.

WHAT IS HELD
    * the tie-out carries `filed_on`, the stated date, beside `filed_at`, the recording instant, under their own names
      (the exception report does not: nothing there prints a date, and the amendment build calls it once per earlier
      period);
    * the stated date is read the way the period lock reads it (the filing's window contains the period's first day, not
      deleted, a date present), for GSTR-1 only, for this client and firm only, and the EARLIEST wins;
    * a QRMP quarter's one filing answers for the quarter's key;
    * ONE FILING ROW HOLDS ONE REGISTRATION'S DATE: `filings` has no GSTIN and `record_filing` updates the row it finds
      for (client, type, period), so for a client with two registrations the row is whichever was recorded last. The
      date is stated only when the row carries THIS return's ARN or the client holds one registration; otherwise it is
      None and the screen says "recorded" instead of printing another registration's date beside this one's ARN;
    * no filing row, an unreadable one, a malformed day or period is `None`, never a made-up date and never a lost answer.
"""
from __future__ import annotations

import pytest

import services.gst_exception_service as exceptions
import services.gst_return_service as grs
import routers.gst_workspace as gw
from services import gst_filing_record_service as filing_record
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM, CLIENT = "FIRM-A", "CLI"
GSTIN = "27AAAAA0000A1Z2"
PERIOD = "082025"
RECORDED = "2026-10-19T20:15:00Z"      # 20:15 UTC is 01:45 IST on the 20th: neither calendar day is the filing day


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [gw, grs])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("firms", {"id": FIRM, "name": "F", "locked_financial_years": []})
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "gstin": GSTIN,
                       "financial_year_start": "2025-04-01", "state_code": "27"})
    d.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": CLIENT, "name": "Acme",
                         "gstin": "27BBBBB1111B1ZN", "state_code": "27", "is_active": True})
    seed_standard_coa(d, FIRM, CLIENT)
    d.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": CLIENT, "customer_id": "CUST", "invoice_no": "INV-1",
        "invoice_date": "2025-08-10", "status": "issued", "taxable_amount_paise": 100_000,
        "cgst_paise": 9_000, "sgst_paise": 9_000, "igst_paise": 0, "total_paise": 118_000,
        "is_interstate": False, "supply_state_code": "27", "supply_type": "taxable",
        "invoice_type": "Regular", "is_reverse_charge": False, "deleted_at": None})
    return d


def _return(db, *, payload=True, period=PERIOD, status="submitted"):
    return db.seed("gstr1_returns", {
        "firm_id": FIRM, "client_id": CLIENT, "period": period, "gstin": GSTIN, "status": status,
        "payload_json": grs.gstr1_from_books(db, FIRM, CLIENT, period, GSTIN)["payload"] if payload else None,
        "submitted_at": RECORDED, "arn": "AA270825000001X"})


def _filing(db, filed_date, *, start="2025-08-01", end="2025-08-31", filing_type="GSTR-1",
            client=CLIENT, firm=FIRM, deleted_at=None, ack=None):
    return db.seed("filings", {
        "firm_id": firm, "client_id": client, "filing_type": filing_type, "period_start": start,
        "period_end": end, "filed_date": filed_date, "status": "filed", "deleted_at": deleted_at,
        "acknowledgement_number": ack})


# ── the helper ──────────────────────────────────────────────────────────────

ONE = lambda: False        # noqa: E731  the client holds a single registration
SEVERAL = lambda: True     # noqa: E731


def _stated(db, day="2025-08-01", **kw):
    return filing_record.stated_filed_date(db, FIRM, CLIENT, "GSTR-1", day, **kw)


def test_the_stated_date_is_read_from_the_filing_row(db):
    _filing(db, "2025-09-12")
    assert _stated(db, client_holds_several=ONE) == "2025-09-12"


def test_no_filing_row_is_none_and_not_a_date(db):
    assert _stated(db, client_holds_several=ONE) is None


def test_the_earliest_stated_date_wins_as_it_does_for_the_period_lock(db):
    _filing(db, "2025-09-20")
    _filing(db, "2025-09-11")
    assert _stated(db, client_holds_several=ONE) == "2025-09-11"


@pytest.mark.parametrize("make", [
    lambda db: _filing(db, "2025-09-12", filing_type="GSTR-3B"),                   # the other return
    lambda db: _filing(db, "2025-09-12", client="CLI-OTHER"),                       # another client
    lambda db: _filing(db, "2025-09-12", firm="FIRM-B"),                            # another firm
    lambda db: _filing(db, "2025-09-12", deleted_at="2025-10-01T00:00:00Z"),        # withdrawn
    lambda db: _filing(db, "2025-09-12", start="2025-09-01", end="2025-09-30"),     # another month
    lambda db: _filing(db, None),                                                   # no date stated
])
def test_a_row_that_is_not_this_returns_filing_is_not_read(db, make):
    make(db)
    assert _stated(db, client_holds_several=ONE) is None


def test_a_quarters_one_filing_answers_for_the_quarter(db):
    _filing(db, "2025-10-13", start="2025-07-01", end="2025-09-30")
    assert _stated(db, "2025-07-01", client_holds_several=ONE) == "2025-10-13"


@pytest.mark.parametrize("day", [None, "", "08/2025", "2025-8", "2025-13-45", "not a date"])
def test_a_malformed_day_is_none_without_raising_or_asking_the_database(db, day):
    _filing(db, "2025-09-12")
    assert _stated(db, day, client_holds_several=ONE) is None


def test_an_unreadable_filing_table_loses_the_date_and_not_the_answer():
    class Broken:
        def table(self, name):
            raise RuntimeError("PostgREST is unreachable")
    assert filing_record.stated_filed_date(Broken(), FIRM, CLIENT, "GSTR-1", "2025-08-01",
                                           client_holds_several=ONE) is None


# ── whose date it is ────────────────────────────────────────────────────────

def test_a_row_with_this_returns_own_arn_states_its_date_even_when_the_client_holds_several(db):
    _filing(db, "2025-09-14", ack="AA-B")
    assert _stated(db, arn="AA-B", client_holds_several=SEVERAL) == "2025-09-14"


def test_another_registrations_date_is_not_stated_beside_this_returns_arn(db):
    """Registration A filed on 11 Sep; registration B was recorded after and overwrote the one row with ITS date and ARN.
    A's screen must not say "filed 14 Sep" beside A's ARN."""
    _filing(db, "2025-09-14", ack="AA-B")
    assert _stated(db, arn="AA-A", client_holds_several=SEVERAL) is None


def test_a_client_with_one_registration_states_the_date_whatever_the_arn_says(db):
    _filing(db, "2025-09-12", ack="AA-RECORDED-LATER-BY-HAND")
    assert _stated(db, arn="AA-X", client_holds_several=ONE) == "2025-09-12"


def test_not_being_able_to_tell_how_many_registrations_is_not_a_date(db):
    def cannot_tell():
        raise RuntimeError("registrations unreadable")
    _filing(db, "2025-09-12")
    assert _stated(db, client_holds_several=cannot_tell) is None


def test_with_no_way_to_ask_the_answer_is_the_cautious_one(db):
    _filing(db, "2025-09-12")
    assert _stated(db) is None


# ── the reader ──────────────────────────────────────────────────────────────

def test_the_tie_out_carries_both_the_stated_date_and_the_recording_instant(db):
    _return(db)
    _filing(db, "2025-09-12", ack="AA270825000001X")
    out = grs.gstr3b_from_books(db, FIRM, CLIENT, PERIOD, GSTIN)["gstr1_tie_out"]
    assert out["status"] == "ok"
    assert out["filed_on"] == "2025-09-12"
    assert out["filed_at"] == RECORDED, "the recording instant stays, under its own name"


def test_the_tie_out_with_no_stated_date_has_none_and_still_has_the_recording_instant(db):
    _return(db)
    out = grs.gstr3b_from_books(db, FIRM, CLIENT, PERIOD, GSTIN)["gstr1_tie_out"]
    assert out["filed_on"] is None and out["filed_at"] == RECORDED


SECOND = "29AAAAA0000A1Z5"


def _second_registration(db):
    db.seed("client_gst_registrations", {
        "firm_id": FIRM, "client_id": CLIENT, "gstin": SECOND, "state_code": "29",
        "registration_type": "regular", "filing_frequency": "monthly", "deleted_at": None})


def test_a_client_with_two_registrations_never_shows_the_other_ones_date(db):
    """The single filing row holds the registration recorded LAST (here B, ARN AA-B, 14 Sep). The tie-out for A, whose
    own ARN is AA270825000001X, must say nothing about when it was filed rather than say 14 Sep."""
    _second_registration(db)
    _return(db)                                                  # registration A's return, ARN AA270825000001X
    _filing(db, "2025-09-14", ack="AA-B")
    out = grs.gstr3b_from_books(db, FIRM, CLIENT, PERIOD, GSTIN)["gstr1_tie_out"]
    assert out["status"] == "ok"
    assert out["filed_on"] is None
    assert out["filed_at"] == RECORDED


def test_a_client_with_two_registrations_still_shows_the_date_of_the_return_the_row_belongs_to(db):
    _second_registration(db)
    _return(db)
    _filing(db, "2025-09-12", ack="AA270825000001X")
    out = grs.gstr3b_from_books(db, FIRM, CLIENT, PERIOD, GSTIN)["gstr1_tie_out"]
    assert out["filed_on"] == "2025-09-12"


def test_the_exception_report_does_not_pay_a_filing_read_for_a_date_nothing_prints(db, monkeypatch):
    """The amendment build calls `gstr1_exceptions` once per earlier period and ignores the date."""
    _return(db)
    _filing(db, "2025-09-12")
    seen = []
    real = filing_record.stated_filed_date
    monkeypatch.setattr(filing_record, "stated_filed_date", lambda *a, **k: seen.append(a) or real(*a, **k))
    out = exceptions.gstr1_exceptions(db, FIRM, CLIENT, PERIOD)
    assert out["status"] == "ok" and "filed_on" not in out
    assert seen == []


def test_a_malformed_period_has_no_filed_on_and_does_not_raise(db):
    assert exceptions.filed_on(db, FIRM, CLIENT, "2025-08") is None
