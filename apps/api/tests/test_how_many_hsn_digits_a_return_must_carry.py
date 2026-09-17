"""
GST-17 — the HSN digit requirement on GSTR-1 Table 12.

WHAT WAS WRONG
    `gstr1_builder._required_hsn_digits` returned 6 above ₹5 crore, 4 above
    ₹1.5 crore and 0 below — a HYBRID that existed in no notification. The
    ₹1.5 crore rung belongs to the PRE-2021 table and the digit counts beside
    it to the POST-2021 one. A client with ₹1 crore of turnover was told HSN
    was optional, where Notification 78/2020-Central Tax requires four digits
    on every B2B supply however small the turnover.

    And nothing enforced or even reported it: the one consumer sliced the code
    to `max(required, len(code))`, whose length is the larger of the two, so a
    2-digit HSN at ₹10 crore came back unchanged, was filed, and appeared in no
    gap list.

⚠️  EVERY THRESHOLD AND DIGIT COUNT BELOW IS PINNED EXACTLY, because
    `hsn_digits` is `[S]`-graded — every `.gov.in` is refused at this
    environment's egress proxy, so the two tables are written from knowledge.
    A test that merely re-ran the module's own arithmetic would prove nothing;
    these assert the NUMBERS, so changing one is a deliberate act.
"""
from __future__ import annotations

import pytest

from domain.gst import hsn_digits as h
from domain.gst.gstr1_builder import (
    GAP_HSN_DIGITS, GAP_HSN_TURNOVER_NOT_RECORDED, GSTInvoiceCategory,
    InvoiceForGSTR1, InvoiceLine, build_gstr1,
)

CRORE = 1_00_00_000_00   # ₹1 crore in paise
POST = "2026-06-01"      # any period on or after the commencement
PRE = "2019-06-01"       # before it


# ── The two tables, pinned ───────────────────────────────────────────────────

def test_the_commencement_is_the_notifications_own_date():
    assert h.COMMENCEMENT == "2021-04-01"


def test_the_five_crore_threshold_is_five_crore_in_paise():
    assert h.AATO_5CR_PAISE == 5_00_00_000_00
    assert h.AATO_1_5CR_PAISE == 1_50_00_000_00


@pytest.mark.parametrize("aato,is_b2b,expected", [
    # Above ₹5 crore: six digits on EVERY supply, B2C included.
    (10 * CRORE, True, 6),
    (10 * CRORE, False, 6),
    # Exactly ₹5 crore is NOT above it — the notification reads "above".
    (5 * CRORE, True, 4),
    (5 * CRORE, False, 0),
    # At or below ₹5 crore: four on B2B, optional on B2C. THIS IS THE ROW THE
    # OLD TABLE GOT WRONG — it returned 0 here for everything under ₹1.5 crore.
    (1 * CRORE, True, 4),
    (1 * CRORE, False, 0),
    (0, True, 4),
    (0, False, 0),
])
def test_notification_78_2020(aato, is_b2b, expected):
    r = h.required_digits(aato, is_b2b=is_b2b, period_start=POST)
    assert r.digits == expected
    assert "78/2020" in r.citation
    assert r.turnover_unknown is False


@pytest.mark.parametrize("aato,expected", [
    (10 * CRORE, 4),
    (5 * CRORE, 2),
    (2 * CRORE, 2),
    (1 * CRORE, 0),
    (0, 0),
])
def test_the_pre_2021_table_still_governs_an_earlier_period(aato, expected):
    # A belated GSTR-1 for a 2019 period is filed under the rule in force for
    # that period — the same "fork, not migration" shape as the TDS vocabulary.
    r = h.required_digits(aato, is_b2b=True, period_start=PRE)
    assert r.digits == expected
    assert "12/2017" in r.citation


def test_the_pre_2021_table_did_not_split_b2b_from_b2c():
    # The B2B/B2C split arrived WITH Notification 78/2020. Applying it
    # backwards would under-report on a pre-2021 B2C supply.
    for aato in (10 * CRORE, 2 * CRORE, 0):
        assert (h.required_digits(aato, is_b2b=True, period_start=PRE).digits
                == h.required_digits(aato, is_b2b=False, period_start=PRE).digits)


def test_the_fork_is_on_the_commencement_date_itself():
    assert "78/2020" in h.required_digits(
        10 * CRORE, is_b2b=True, period_start=h.COMMENCEMENT).citation
    assert "12/2017" in h.required_digits(
        10 * CRORE, is_b2b=True, period_start="2021-03-31").citation


# ── An unrecorded turnover is a THIRD state ──────────────────────────────────

def test_an_unrecorded_turnover_is_not_zero():
    # Zero is a client who turned over nothing, which makes B2C optional.
    # None is nobody having said, which must not.
    unknown = h.required_digits(None, is_b2b=False, period_start=POST)
    zero = h.required_digits(0, is_b2b=False, period_start=POST)
    assert unknown.digits == 6 and unknown.turnover_unknown is True
    assert zero.digits == 0 and zero.turnover_unknown is False


def test_an_unrecorded_turnover_takes_the_STRICTEST_reading():
    # Under-reporting the requirement files a return the portal rejects;
    # over-reporting costs the CA a glance. Only one of those is recoverable
    # inside the s.37(3) window.
    assert h.required_digits(None, is_b2b=True, period_start=POST).digits == 6
    assert h.required_digits(None, is_b2b=True, period_start=PRE).digits == 4


# ── problem_with: the one shape ──────────────────────────────────────────────

def _req(digits: int) -> h.DigitRequirement:
    return h.DigitRequirement(digits=digits, citation="x")


def test_a_code_at_or_above_the_minimum_is_fine():
    assert h.problem_with("8471", _req(4)) is None
    assert h.problem_with("847130", _req(4)) is None      # longer is a FLOOR
    assert h.problem_with("84713010", _req(6)) is None


def test_a_short_code_names_both_numbers():
    msg = h.problem_with("99", _req(6))
    assert msg is not None and "99" in msg and "2 digits" in msg and "6" in msg


def test_an_absent_code_is_its_own_sentence():
    msg = h.problem_with("", _req(4))
    assert msg is not None and "no HSN" in msg
    assert h.problem_with(None, _req(4)) is not None


def test_nothing_is_wrong_where_HSN_is_optional():
    assert h.problem_with("", _req(0)) is None
    assert h.problem_with("9", _req(0)) is None


# ── The preceding-year hop ───────────────────────────────────────────────────

@pytest.mark.parametrize("period_start,governing", [
    ("2026-04-01", "2025-26"),   # first month of FY 2026-27
    ("2026-06-01", "2025-26"),
    ("2027-03-01", "2025-26"),   # March still belongs to FY 2026-27
    ("2026-03-01", "2024-25"),   # March 2026 is FY 2025-26
])
def test_the_governing_year_is_the_preceding_one(period_start, governing):
    assert h.governing_financial_year(period_start) == governing


# ── The builder REPORTS and never truncates ──────────────────────────────────

def _line(hsn="847130", unit="PCS"):
    return InvoiceLine(hsn_sac_code=hsn, description="Widget", quantity=1.0,
                       unit=unit, rate_paise=100_000, taxable_paise=100_000,
                       gst_rate=18.0, cgst_paise=9_000, sgst_paise=9_000,
                       igst_paise=0, cess_paise=0)


def _invoice(ref, lines, category=GSTInvoiceCategory.B2B):
    return InvoiceForGSTR1(
        id=ref, transaction_type="sales_invoice", reference_no=ref,
        transaction_date="2026-06-10", party_gstin="27AAACI1195H1ZT",
        party_name="Acme", place_of_supply="27", is_interstate=False,
        taxable_amount_paise=sum(l.taxable_paise for l in lines),
        cgst_paise=sum(l.cgst_paise for l in lines),
        sgst_paise=sum(l.sgst_paise for l in lines),
        igst_paise=0, cess_paise=0, is_reverse_charge=False,
        invoice_type="Regular", supply_type="B2B",
        gst_invoice_category=category,
        original_invoice_ref=None, original_invoice_date=None, lines=lines)


def _build(invoices, aato=10 * CRORE, period="062026"):
    return build_gstr1(invoices, gstin="27AAACI1195H1ZT", period=period,
                       aggregate_turnover_paise=aato)


def _kinds(out):
    return {g["kind"] for g in out.gaps}


def test_a_short_code_is_filed_AS_RECORDED_and_reported():
    # The whole defect: this used to come back as '99', filed, with no gap.
    out = _build([_invoice("INV/1", [_line(hsn="99")])])
    assert out.payload["hsn"]["data"][0]["hsn_sc"] == "99"
    assert GAP_HSN_DIGITS in _kinds(out)


def test_a_LONGER_code_is_never_cut_down():
    out = _build([_invoice("INV/1", [_line(hsn="84713010")])])
    assert out.payload["hsn"]["data"][0]["hsn_sc"] == "84713010"
    assert GAP_HSN_DIGITS not in _kinds(out)


def test_a_B2C_supply_below_five_crore_owes_nothing():
    out = _build([_invoice("INV/1", [_line(hsn="99")],
                           category=GSTInvoiceCategory.B2CS)], aato=1 * CRORE)
    assert GAP_HSN_DIGITS not in _kinds(out)


def test_a_B2B_supply_below_five_crore_owes_four():
    # The row the old table got wrong: it said "optional" here.
    out = _build([_invoice("INV/1", [_line(hsn="99")])], aato=1 * CRORE)
    assert GAP_HSN_DIGITS in _kinds(out)
    assert "4 are required" in next(
        g for g in out.gaps if g["kind"] == GAP_HSN_DIGITS)["reason"]


def test_the_split_is_per_SUPPLY_not_per_return():
    # One period, one turnover, two invoices — and only the B2B one owes.
    out = _build([
        _invoice("B2B/1", [_line(hsn="99")]),
        _invoice("B2C/1", [_line(hsn="99")], category=GSTInvoiceCategory.B2CS),
    ], aato=1 * CRORE)
    refs = {g["reference_no"] for g in out.gaps if g["kind"] == GAP_HSN_DIGITS}
    assert refs == {"B2B/1"}


def test_an_unrecorded_turnover_says_so_ONCE_beside_the_shortfall():
    out = _build([_invoice("INV/1", [_line(hsn="99")]),
                  _invoice("INV/2", [_line(hsn="99")])], aato=None)
    flags = [g for g in out.gaps if g["kind"] == GAP_HSN_TURNOVER_NOT_RECORDED]
    assert len(flags) == 1
    assert "aggregate turnover" in flags[0]["reason"]


def test_an_unrecorded_turnover_is_SILENT_when_nothing_falls_short():
    # Six digits everywhere: the client owes nothing whatever their turnover
    # was, so telling them to go and record it is noise.
    out = _build([_invoice("INV/1", [_line(hsn="847130")])], aato=None)
    assert GAP_HSN_TURNOVER_NOT_RECORDED not in _kinds(out)
    assert GAP_HSN_DIGITS not in _kinds(out)


def test_an_invoice_with_no_lines_is_reported_rather_than_passed_by_OTH():
    # The no-line fallback files the placeholder 'OTH', which is not an HSN.
    out = _build([_invoice("INV/1", [])])
    assert out.payload["hsn"]["data"][0]["hsn_sc"] == "OTH"
    assert GAP_HSN_DIGITS in _kinds(out)


def test_a_pre_2021_period_is_judged_by_the_pre_2021_table():
    # 4 digits at ₹10 crore then, 6 now — so '8471' is a gap in 2026 and not
    # in 2019.
    now = _build([_invoice("INV/1", [_line(hsn="8471")])], period="062026")
    then = _build([_invoice("INV/1", [_line(hsn="8471")])], period="062019")
    assert GAP_HSN_DIGITS in _kinds(now)
    assert GAP_HSN_DIGITS not in _kinds(then)


def test_the_gaps_ride_the_list_the_screen_already_renders():
    # `payload_gaps` is what app/gst/gstr1/page.tsx renders. A separate list
    # would be a second panel nobody built.
    out = _build([_invoice("INV/1", [_line(hsn="99")])])
    assert any(g["kind"] == GAP_HSN_DIGITS for g in out.gaps)


# ── The figure is STORED per financial year, and an absence is not a zero ─────

def test_the_service_answers_None_for_a_year_nobody_recorded():
    from tests.e2e_harness import FakeDB
    from services import client_gst_turnover_service as svc

    db = FakeDB()
    assert svc.turnover_for_fy(db, "firm-1", "client-1", "2025-26") is None


def test_a_recorded_zero_is_zero_and_not_an_absence():
    # The whole point of the third state: a client who genuinely turned over
    # nothing makes B2C optional, and a client nobody has asked about does not.
    from tests.e2e_harness import FakeDB
    from services import client_gst_turnover_service as svc

    db = FakeDB()
    svc.record(db, "firm-1", "client-1", "2025-26", 0)
    assert svc.turnover_for_fy(db, "firm-1", "client-1", "2025-26") == 0


def test_recording_the_same_year_twice_CORRECTS_it():
    # (client, financial_year) is migration 401's unique key: a second figure
    # for one year would make the read depend on insertion order.
    from tests.e2e_harness import FakeDB
    from services import client_gst_turnover_service as svc

    db = FakeDB()
    svc.record(db, "firm-1", "client-1", "2025-26", 3 * CRORE)
    svc.record(db, "firm-1", "client-1", "2025-26", 7 * CRORE)
    assert svc.turnover_for_fy(db, "firm-1", "client-1", "2025-26") == 7 * CRORE
    assert len(svc.list_for_client(db, "firm-1", "client-1")) == 1


def test_the_service_reads_the_PRECEDING_year_for_a_period():
    from tests.e2e_harness import FakeDB
    from services import client_gst_turnover_service as svc

    db = FakeDB()
    svc.record(db, "firm-1", "client-1", "2025-26", 7 * CRORE)
    svc.record(db, "firm-1", "client-1", "2026-27", 1 * CRORE)
    # A June 2026 return is inside FY 2026-27 and is governed by FY 2025-26.
    assert svc.turnover_governing_period(
        db, "firm-1", "client-1", "2026-06-01") == 7 * CRORE


def test_a_negative_turnover_is_refused():
    import pytest as _pytest
    from tests.e2e_harness import FakeDB
    from services import client_gst_turnover_service as svc

    db = FakeDB()
    with _pytest.raises(ValueError):
        svc.record(db, "firm-1", "client-1", "2025-26", -1)


def test_the_service_never_derives_the_figure_from_the_books():
    # CGST s.2(6) is computed on the PAN, all-India, and includes exempt
    # supplies and exports — a second registration's supplies count toward it.
    # Summing this client's outward supplies would produce a smaller number
    # that looks authoritative, which is the whole finding.
    import inspect
    from services import client_gst_turnover_service as svc

    src = inspect.getsource(svc)
    for table in ("client_sales_invoices", "journal_lines", "gstr1_returns"):
        assert table not in src, (
            f"the turnover service reads {table} — it must be RECORDED, "
            "because s.2(6) turnover cannot be derived from one client's books")
