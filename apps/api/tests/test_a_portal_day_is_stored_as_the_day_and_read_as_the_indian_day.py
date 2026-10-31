"""POST-A-251 — a day a portal prints is stored as a day, and a stored stamp is read as the Indian day it fell on.

WHAT WAS WRONG
    Three sites cut a `timestamptz` column to its first ten characters, which is the UTC day, and the rule that finds such cuts only knew
    columns named `..._at`: `ewb_date` and `ewb_valid_upto` in the e-way bill router, and `ack_date` on the printed tax invoice. Which
    of the two readings was right depended on what the column held, and nothing said: the doors took any string, so a value with a time
    of day kept it, and nobody could tell Indian wall-clock labelled UTC from a true instant.

WHAT THIS PINS
    PORTAL DAY   `core.ist_clock.portal_day` reads what a person typed or pasted as the day the portal PRINTED: a bare date is the day, a
                 value with no offset is Indian wall-clock and its date part is the day, a value with an offset is converted; junk is None.
    DOORS        the e-way bill record and the e-invoice record store that day as a bare date, and refuse text that is not a date in words.
    READERS      a stored instant is read as the Indian day (the e-way bill's validity, the extension check, the printed Ack Date), so the
                 same instant is the same day to all of them, and a value stored as a day is unchanged.
"""
import pytest
from pydantic import ValidationError

from core.ist_clock import portal_day
from datetime import date, datetime, timezone


# ── the helper ───────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("value, expected", [
    ("2026-07-15", date(2026, 7, 15)),                              # what every screen sends
    ("2026-07-15T23:10:00", date(2026, 7, 15)),                     # no offset: Indian wall-clock, the date part is the day
    ("2026-07-15 23:10:00", date(2026, 7, 15)),
    ("2026-07-15T23:10:00+05:30", date(2026, 7, 15)),               # an offset: an instant, converted
    ("2026-07-15T20:00:00+00:00", date(2026, 7, 16)),               # 01:30 IST the next day
    ("2026-07-15T20:00:00Z", date(2026, 7, 16)),
    (" 2026-07-15 ", date(2026, 7, 15)),
    (date(2026, 7, 15), date(2026, 7, 15)),
    (datetime(2026, 7, 15, 23, 10), date(2026, 7, 15)),
    (datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc), date(2026, 7, 16)),
])
def test_portal_day_reads_what_the_portal_printed(value, expected):
    assert portal_day(value) == expected


@pytest.mark.parametrize("value", [None, "", "15/07/2026", "July 15", "2026-13-40", "x", 5])
def test_portal_day_is_none_for_anything_it_cannot_read(value):
    assert portal_day(value) is None


# ── the doors ────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_e_way_bill_record_stores_the_day_the_portal_printed():
    from routers.eway_bill import RecordEWBGeneratedRequest
    r = RecordEWBGeneratedRequest(ewb_number="141000000001", ewb_date="2026-07-15T23:10:00", ewb_valid_upto="2026-07-16T20:00:00+00:00")
    assert r.ewb_date == "2026-07-15" and r.ewb_valid_upto == "2026-07-17", "a bare date each: no time of day is kept to be guessed at"


@pytest.mark.parametrize("field", ["ewb_date", "ewb_valid_upto"])
def test_the_e_way_bill_record_refuses_text_that_is_not_a_date(field):
    from routers.eway_bill import RecordEWBGeneratedRequest
    body = {"ewb_number": "141000000001", "ewb_date": "2026-07-15", "ewb_valid_upto": "2026-07-16", field: "15/07/2026"}
    with pytest.raises(ValidationError) as refused:
        RecordEWBGeneratedRequest(**body)
    assert "must be a date, YYYY-MM-DD" in str(refused.value) and field in str(refused.value)


def test_the_e_invoice_record_stores_the_day_the_portal_printed_and_refuses_junk():
    from routers.einvoice import RecordIRNRequest
    ok = RecordIRNRequest(irn="a" * 64, ack_number="112600000001", ack_date="2026-07-15 23:10:00")
    assert ok.ack_date == "2026-07-15"
    with pytest.raises(ValidationError) as refused:
        RecordIRNRequest(irn="a" * 64, ack_number="112600000001", ack_date="yesterday")
    assert "must be a date, YYYY-MM-DD" in str(refused.value)


# ── the readers ──────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_validity_check_reads_a_stored_instant_as_the_indian_day():
    from routers.eway_bill import _computed_validity
    rec = {"distance_km": 100}
    stored_instant = "2026-07-15T20:00:00+00:00"                     # 01:30 IST on the 16th
    as_the_16th = _computed_validity(rec, "2026-07-16")
    assert as_the_16th["valid_upto"], "a 100 km bill has a computed validity"
    assert _computed_validity(rec, stored_instant) == as_the_16th, "the stored instant is the 16th in India"
    assert _computed_validity(rec, "2026-07-15")["valid_upto"] != as_the_16th["valid_upto"], "and not the UTC day, the 15th"
    assert _computed_validity(rec, "2026-07-16T00:00:00+00:00") == as_the_16th, "a day stored as midnight UTC is that same day"


def test_a_validity_with_no_readable_date_says_so_in_words():
    from routers.eway_bill import _computed_validity
    for bad in (None, "", "soon"):
        answer = _computed_validity({"distance_km": 100}, bad)
        assert answer["valid_upto"] is None and "e-way bill's own date is needed" in answer["gap"]


def test_the_printed_ack_date_is_the_indian_day_of_the_stored_instant():
    from services.invoice_pdf_service import _einvoice_particulars
    record = {"status": "generated", "irn": "a" * 64, "ack_number": "112600000001", "qr_data": None}
    assert _einvoice_particulars({**record, "ack_date": "2026-07-15T20:00:00+00:00"})["ack_date"] == "2026-07-16"
    assert _einvoice_particulars({**record, "ack_date": "2026-07-15T00:00:00+00:00"})["ack_date"] == "2026-07-15", "a day stored as midnight UTC"
    assert _einvoice_particulars({**record, "ack_date": None})["ack_date"] == ""
