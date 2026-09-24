"""
A QRMP return covers a QUARTER, and the whole engine has to agree — GST-11.

WHAT WAS WRONG
    `gst_return_service._period_bounds` raised on anything but a six-digit
    MMYYYY and returned the first and last day of ONE calendar month. Both
    from-books builders opened on it, so the return engine could not express a
    quarter at all.

    Rule 61A with the proviso to CGST s.39(1) — Notifications 82, 84 and
    85/2020-Central Tax, in force 01-01-2021 — lets a registered person whose
    preceding-year aggregate turnover was up to Rs 5 crore furnish GSTR-1 and
    GSTR-3B QUARTERLY while paying tax monthly. That is a large share of a
    small Indian practice's book, and for every one of them the DUE DATES were
    already right while the return they were due could not be built: the CA was
    quoted the 13th and the 22nd/24th and then had to add three monthly
    GSTR-3Bs by hand.

WHAT THIS ASSERTS
    Six different things, because the defect had six different faces and
    getting five of them right would have been worse than getting none:

      * the window itself, month and quarter, from the one authority;
      * the FIGURES — three months of posted documents in one return;
      * the STORAGE key, which must stay a six-digit MMYYYY that nothing
        already stored collides with;
      * the PERIOD-KEYED reads — GSTR-2B is monthly for a quarterly filer too,
        so a quarter has three of them and Rule 36(4) must see all three;
      * the LOCK — journal_period_lock_reason reads `filings` and nothing else,
        so a filed quarter has to freeze three months;
      * and what the return REFUSES to say about itself.

    The monthly path is asserted unchanged throughout. A registration with no
    recorded frequency is monthly, which is what every caller predating QRMP
    meant, and `clients.gst_filing_frequency` is nullable.
"""
from __future__ import annotations

import inspect

import pytest

import routers.gst as gst_router
import services.gst_return_service as grs
import services.gst_filing_record_service as filing_record
from domain.gst import registrations, return_period
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

import routers.sales_invoices as si
import routers.purchase_bills as pb
import routers.credit_notes as cn
import routers.sales_debit_notes as sdn
import routers.purchase_credit_notes as pcn
from models.invoices import PurchaseBillIn, PurchaseBillLineIn

FIRM = "FIRM-Q"
CALLER = {"firm_id": FIRM, "id": "u-q", "auth_user_id": "auth-q",
          "email": "ca@q.test", "role": "Partner"}
GSTIN = "27AAAAA0000A1Z2"

APRIL, MAY, JUNE = "042025", "052025", "062025"
Q1_KEY = APRIL


# ══════════════════════════════════════════════════════════════════════════════
# 1. The window — the rule, from the one authority
# ══════════════════════════════════════════════════════════════════════════════

def test_a_monthly_period_is_the_month_it_always_was():
    w = return_period.resolve(JUNE, registrations.MONTHLY)
    assert (w.key, w.start, w.end) == (JUNE, "2025-06-01", "2025-06-30")
    assert w.months == (JUNE,)
    assert w.is_quarter is False


def test_an_unrecorded_frequency_is_monthly():
    """`clients.gst_filing_frequency` is nullable (migration 001) and every
    caller predating QRMP meant a month. None must not become a quarter."""
    for absent in (None, "", "   "):
        assert return_period.resolve(JUNE, absent).months == (JUNE,)


def test_a_frequency_the_act_does_not_have_is_refused_not_coerced():
    """Both columns CHECK to the two values, so a third one means the caller
    invented it — and coercing it to monthly would build a one-month return
    for somebody who asked for something else and say nothing."""
    with pytest.raises(ValueError) as e:
        return_period.resolve(JUNE, "annually")
    assert "61A" in str(e.value)


@pytest.mark.parametrize("month,key,start,end", [
    ("042025", "042025", "2025-04-01", "2025-06-30"),
    ("052025", "042025", "2025-04-01", "2025-06-30"),
    ("062025", "042025", "2025-04-01", "2025-06-30"),
    ("072025", "072025", "2025-07-01", "2025-09-30"),
    ("092025", "072025", "2025-07-01", "2025-09-30"),
    ("102025", "102025", "2025-10-01", "2025-12-31"),
    ("122025", "102025", "2025-10-01", "2025-12-31"),
    # Q4 is the one that is easy to get wrong: January to March belong to the
    # financial year that STARTED the previous April, and the months carry the
    # LATER calendar year.
    ("012026", "012026", "2026-01-01", "2026-03-31"),
    ("022026", "012026", "2026-01-01", "2026-03-31"),
    ("032026", "012026", "2026-01-01", "2026-03-31"),
])
def test_the_four_gst_quarters_run_with_the_financial_year(month, key, start, end):
    w = return_period.resolve(month, registrations.QUARTERLY)
    assert (w.key, w.start, w.end) == (key, start, end)
    assert len(w.months) == 3
    assert w.months[0] == key


def test_the_quarter_is_read_off_the_one_clock_and_not_restated():
    """`core.ist_clock.fy_quarters` already derives the four windows from
    `fy_bounds`. A second statement of Apr-Jun is what this codebase's rules
    forbid, so the module must reach for it rather than spell it."""
    src = inspect.getsource(return_period)
    assert "fy_quarters" in src
    body = inspect.getsource(return_period._quarter_containing)
    assert "fy_quarters" in body
    # Nothing in the module may assert which month a quarter starts in.
    for spelling in ("== 4", "month in (4", "[4, 7, 10", "(4, 7, 10"):
        assert spelling not in src, (
            f"{spelling!r} restates the quarter boundary that fy_quarters owns")


def test_every_month_of_the_window_is_named():
    """A period-KEYED read has to be asked for each one — the reason this is a
    tuple on the object rather than something each caller re-derives."""
    assert return_period.resolve(MAY, registrations.QUARTERLY).months == (
        APRIL, MAY, JUNE)


# ══════════════════════════════════════════════════════════════════════════════
# 2. The storage key
# ══════════════════════════════════════════════════════════════════════════════

def test_a_quarters_key_is_still_a_six_digit_mmyyyy():
    """`gstr1_returns.period` / `gstr3b_returns.period` are TEXT in MMYYYY and
    migration 390 keys both on (client_id, period, gstin). A quarter must fit
    that column without colliding with anything already stored."""
    w = return_period.resolve(JUNE, registrations.QUARTERLY)
    assert len(w.key) == 6 and w.key.isdigit()


def test_the_key_is_the_quarters_first_month_because_the_lock_path_already_is():
    """`routers/compliance.py::mark_compliance_filed` writes the filings row for
    a quarterly obligation with `period = f"{start[5:7]}{start[0:4]}"` off the
    calendar row's own period_start, and `_unsubmitted_workspace_return` looks
    the prepared return up under that same key. Keying on the quarter END here
    would have left both reading a key nothing writes."""
    import routers.compliance as compliance_router

    src = inspect.getsource(compliance_router)
    assert 'f"{start[5:7]}{start[0:4]}"' in src, (
        "the merged half of GST-11 chose the quarter's FIRST month; if that "
        "moved, this module's key has to move with it")
    assert return_period.resolve(JUNE, registrations.QUARTERLY).key == APRIL


def test_any_month_of_the_quarter_resolves_to_the_same_return():
    """A CA who types 052025 for a quarterly registration means Q1,
    unambiguously. Refusing would make them learn a convention; resolving
    silently to a different key each time would open three rows for one
    quarter."""
    keys = {return_period.resolve(m, registrations.QUARTERLY).key
            for m in (APRIL, MAY, JUNE)}
    assert keys == {APRIL}


def test_what_was_asked_for_is_reported_beside_what_was_resolved():
    w = return_period.resolve(JUNE, registrations.QUARTERLY)
    assert w.requested == JUNE and w.key == APRIL
    assert w.as_dict()["requested"] == JUNE


# ══════════════════════════════════════════════════════════════════════════════
# 3. The figures — three months of posted documents in one return
# ══════════════════════════════════════════════════════════════════════════════

def _setup(monkeypatch, frequency=None):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, pb, cn, sdn, pcn])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": GSTIN,
                        "state_code": "27",
                        "gst_filing_frequency": frequency,
                        "financial_year_start": "2025-04-01"})
    db.seed("vendors", {"id": "VEND1", "firm_id": FIRM, "client_id": "CLI",
                        "name": "Supplier", "state_code": "27",
                        "gstin": "27CCCCC2222C1Z5", "tds_applicable": False})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM,
                                  "client_id": "CLI", "name": "Materials",
                                  "kind": "good"})
    return db


def _receive_bill(db, no, rate_paise, bill_date):
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date=bill_date, bill_no=no,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1",
                                  description="mat", rate_paise=rate_paise,
                                  quantity=1, gst_rate_percent=18.0)],
    ), CALLER)
    assert res["success"] is True, res
    assert pb.receive_purchase_bill(res["data"]["id"], CALLER)["success"] is True
    return res["data"]["id"]


def _three_months_of_bills(db):
    """One bill a month, deliberately different amounts so a quarter that
    picked up only one of them cannot pass by arithmetic accident."""
    _receive_bill(db, "B-APR", 1_00000, "2025-04-10")     # Rs 1,000 -> 18000 tax
    _receive_bill(db, "B-MAY", 2_00000, "2025-05-10")     # Rs 2,000 -> 36000 tax
    _receive_bill(db, "B-JUN", 3_00000, "2025-06-10")     # Rs 3,000 -> 54000 tax


def _itc(out):
    """Table 4(A)'s CGST + SGST — what the return says it may claim."""
    w = out["working"]["itc"]
    return int(w["cgst_paise"]) + int(w["sgst_paise"])


def test_a_monthly_return_still_sees_only_its_own_month(monkeypatch):
    """The negative control for everything below: with the frequency absent,
    the engine answers exactly as it always did."""
    db = _setup(monkeypatch)
    _three_months_of_bills(db)
    assert _itc(grs.gstr3b_from_books(db, FIRM, "CLI", APRIL, GSTIN)) == 18000
    assert _itc(grs.gstr3b_from_books(db, FIRM, "CLI", MAY, GSTIN)) == 36000
    assert _itc(grs.gstr3b_from_books(db, FIRM, "CLI", JUNE, GSTIN)) == 54000


def test_a_quarterly_return_carries_all_three_months(monkeypatch):
    db = _setup(monkeypatch, registrations.QUARTERLY)
    _three_months_of_bills(db)
    out = grs.gstr3b_from_books(db, FIRM, "CLI", APRIL, GSTIN,
                                frequency=registrations.QUARTERLY)
    assert _itc(out) == 18000 + 36000 + 54000
    assert out["period"] == Q1_KEY
    assert out["period_window"]["months"] == [APRIL, MAY, JUNE]
    assert out["period_window"]["frequency"] == registrations.QUARTERLY


def test_asking_for_the_middle_month_builds_the_same_quarter(monkeypatch):
    db = _setup(monkeypatch, registrations.QUARTERLY)
    _three_months_of_bills(db)
    from_may = grs.gstr3b_from_books(db, FIRM, "CLI", MAY, GSTIN,
                                     frequency=registrations.QUARTERLY)
    assert from_may["period"] == Q1_KEY
    assert _itc(from_may) == 18000 + 36000 + 54000


def test_the_ledger_reconciliation_covers_the_same_quarter(monkeypatch):
    """The whole point of the books-vs-ledger block is that the two sides are
    derived independently. Reading the documents over a quarter and the GL over
    a month would report every quarterly client as permanently unreconciled by
    two months of tax."""
    db = _setup(monkeypatch, registrations.QUARTERLY)
    _three_months_of_bills(db)
    itc = grs.gstr3b_from_books(db, FIRM, "CLI", APRIL, GSTIN,
                                frequency=registrations.QUARTERLY
                                )["reconciliation"]["itc"]
    assert itc["books_paise"] == itc["ledger_paise"] == 18000 + 36000 + 54000
    assert itc["difference_paise"] == 0 and itc["matched"] is True


def test_the_gstr1_payload_covers_the_quarter_too(monkeypatch):
    db = _setup(monkeypatch, registrations.QUARTERLY)
    _three_months_of_bills(db)
    out = grs.gstr1_from_books(db, FIRM, "CLI", MAY, GSTIN,
                               frequency=registrations.QUARTERLY)
    assert out["period"] == Q1_KEY
    assert out["period_window"]["months_covered"] == 3
    # The GSTN payload's own period field is the canonical key, not what was
    # asked for — a return filed under two different `fp` values for one
    # quarter is two returns to the portal.
    assert out["payload"]["fp"] == Q1_KEY


def test_the_drill_down_lists_the_same_window_as_the_summary(monkeypatch):
    """A quarter's figure with one month of documents behind it reads as a
    return that does not agree with itself."""
    db = _setup(monkeypatch, registrations.QUARTERLY)
    _three_months_of_bills(db)
    detail = grs.gstr3b_detail(db, FIRM, "CLI", JUNE, "4A",
                               frequency=registrations.QUARTERLY)
    assert detail["period"] == Q1_KEY
    assert {r["document_no"] for r in detail["rows"]} == {"B-APR", "B-MAY", "B-JUN"}


# ══════════════════════════════════════════════════════════════════════════════
# 4. The period-KEYED reads — a quarter has three GSTR-2Bs
# ══════════════════════════════════════════════════════════════════════════════

def _seed_2b(db, period, tax_paise):
    db.seed("gstr2b_reconciliations", {
        "id": f"REC-{period}", "firm_id": FIRM, "client_id": "CLI",
        "return_period": period})
    db.seed("gstr2a_records", {
        "id": f"2A-{period}", "firm_id": FIRM, "client_id": "CLI",
        "return_period": period, "taxable_value_paise": 0,
        "igst_paise": 0, "cgst_paise": tax_paise // 2,
        "sgst_paise": tax_paise // 2, "itc_available": "Y"})


def test_rule_36_4_caps_a_quarter_against_all_three_2bs(monkeypatch):
    """GSTR-2B is generated MONTHLY for a quarterly filer too. Capping three
    months of book ITC against one month's 2B would withhold credit the
    supplier HAS filed — s.16(2)(aa) withholds what was not communicated, and
    April's and May's were."""
    db = _setup(monkeypatch, registrations.QUARTERLY)
    _three_months_of_bills(db)
    for period, tax in ((APRIL, 18000), (MAY, 36000), (JUNE, 54000)):
        _seed_2b(db, period, tax)

    out = grs.gstr3b_from_books(db, FIRM, "CLI", APRIL, GSTIN,
                                frequency=registrations.QUARTERLY)
    assert out["months_without_gstr2b"] == []
    w = out["working"]["itc"]
    assert int(w["net_cgst_paise"]) + int(w["net_sgst_paise"]) == 18000 + 36000 + 54000


def test_a_quarter_missing_one_months_2b_says_which(monkeypatch):
    """THE CAP RULE IS UNCHANGED AND THE GAP IS REPORTED. Rule 36(4) caps
    against what 2B communicated, and with May's file absent the ceiling is
    built from two months — which is exactly what a MONTHLY filer gets when
    they have not uploaded that month, and is not a rule this finding may
    quietly loosen. What is new is that a quarter can be PART-uploaded at all,
    so the months with nothing on file are NAMED: a CA looking at a ceiling
    that is short by a month has to be able to see why."""
    db = _setup(monkeypatch, registrations.QUARTERLY)
    _three_months_of_bills(db)
    _seed_2b(db, APRIL, 18000)
    _seed_2b(db, JUNE, 54000)

    out = grs.gstr3b_from_books(db, FIRM, "CLI", APRIL, GSTIN,
                                frequency=registrations.QUARTERLY)
    assert out["months_without_gstr2b"] == [MAY]
    w = out["working"]["itc"]
    # April's and June's eligible credit, and no more.
    assert int(w["net_cgst_paise"]) + int(w["net_sgst_paise"]) == 18000 + 54000


def test_a_quarter_with_no_2b_at_all_is_not_capped(monkeypatch):
    """`have_2b` is the question "is a 2B ON FILE", and for a quarter it is
    asked of every month. Nothing on file leaves book ITC alone — the engine's
    existing rule — rather than capping a three-month return at nil."""
    db = _setup(monkeypatch, registrations.QUARTERLY)
    _three_months_of_bills(db)
    out = grs.gstr3b_from_books(db, FIRM, "CLI", JUNE, GSTIN,
                                frequency=registrations.QUARTERLY)
    assert out["months_without_gstr2b"] == [APRIL, MAY, JUNE]
    w = out["working"]["itc"]
    assert int(w["net_cgst_paise"]) + int(w["net_sgst_paise"]) == 18000 + 36000 + 54000


def test_the_reversal_register_is_read_for_every_month_of_the_quarter(monkeypatch):
    """A row is registered against the MMYYYY of the return it is declared in.
    A quarterly return declares all three months, so asking for one would leave
    two months of s.17(5) and Rule 37 reversals off a filed return."""
    db = _setup(monkeypatch, registrations.QUARTERLY)
    for period, amount in ((APRIL, 1000), (MAY, 2000), (JUNE, 4000)):
        db.seed("itc_reversal_register", {
            "id": f"REG-{period}", "firm_id": FIRM, "client_id": "CLI",
            "period": period, "kind": "reversal", "reason_code": "section_17_5",
            "igst_paise": 0, "cgst_paise": amount, "sgst_paise": amount,
            "cess_paise": 0})

    out = grs.gstr3b_from_books(db, FIRM, "CLI", JUNE, GSTIN,
                                frequency=registrations.QUARTERLY)
    perm = out["working"]["itc_reversal"]["permanent_paise"]
    assert perm["cgst_paise"] == 1000 + 2000 + 4000
    assert perm["sgst_paise"] == 1000 + 2000 + 4000

    monthly = grs.gstr3b_from_books(db, FIRM, "CLI", JUNE, GSTIN)
    assert monthly["working"]["itc_reversal"]["permanent_paise"]["cgst_paise"] == 4000


# ══════════════════════════════════════════════════════════════════════════════
# 5. The lock — a filed quarter freezes three months
# ══════════════════════════════════════════════════════════════════════════════

def test_a_monthly_filing_still_locks_one_month():
    assert filing_record.period_bounds(JUNE) == ("2025-06-01", "2025-06-30")


def test_a_quarterly_filing_locks_the_whole_quarter():
    """journal_period_lock_reason (migration 266) reads `filings` and nothing
    else, matching `p_date BETWEEN period_start AND period_end`. A quarterly
    return whose row covered April would leave May and June editable after a
    return declaring them had gone to the government."""
    assert filing_record.period_bounds(
        JUNE, registrations.QUARTERLY) == ("2025-04-01", "2025-06-30")


def test_the_filings_row_a_quarterly_return_writes_covers_three_months():
    row = filing_record.build_filings_row(
        firm_id=FIRM, client_id="CLI", filing_type=filing_record.FILING_TYPE_GSTR3B,
        period=JUNE, filed_date="2025-07-22",
        frequency=registrations.QUARTERLY)
    assert row["period_start"] == "2025-04-01"
    assert row["period_end"] == "2025-06-30"


def test_recorded_bounds_beat_a_derived_frequency():
    """`bounds` is a window somebody RECORDED — the compliance calendar's own
    obligation. The frequency is only the rule for deriving one, so where a
    caller holds both, what the obligation says the return covered wins."""
    row = filing_record.build_filings_row(
        firm_id=FIRM, client_id="CLI", filing_type=filing_record.FILING_TYPE_GSTR1,
        period=JUNE, filed_date="2025-07-13",
        bounds=("2025-04-01", "2025-06-30"), frequency=registrations.MONTHLY)
    assert (row["period_start"], row["period_end"]) == ("2025-04-01", "2025-06-30")


def test_the_two_period_bounds_are_one_rule_and_not_two_copies():
    """They were deliberate duplicates while both were 'the first and last day
    of a calendar month'. A quarter is a rule with a fork in it, and two copies
    of that is how one path locks three months and the other locks one."""
    src = inspect.getsource(filing_record.period_bounds)
    assert "return_period.bounds" in src
    assert "monthrange" not in src, "the month arithmetic is stated once"
    assert "return_period.bounds" in inspect.getsource(grs._period_bounds)


# ══════════════════════════════════════════════════════════════════════════════
# 6. The due date the interest runs from
# ══════════════════════════════════════════════════════════════════════════════

def test_a_quarterly_returns_interest_runs_from_its_own_due_date(monkeypatch):
    """Rule 61 gives a QRMP filer the 22nd or 24th of the month after the
    QUARTER. Charging s.50(1) from the 20th of the month after `period` would
    demand interest from a taxpayer who is not late — money they do not owe."""
    from datetime import date

    db = _setup(monkeypatch, registrations.QUARTERLY)
    quarterly = grs.gstr3b_from_books(
        db, FIRM, "CLI", APRIL, GSTIN, filed_on=date(2025, 7, 25),
        frequency=registrations.QUARTERLY, state_code="27")
    # State 27 is Maharashtra — category X, the 22nd.
    assert quarterly["late_filing"]["due_date"] == "2025-07-22"

    monthly = grs.gstr3b_from_books(
        db, FIRM, "CLI", APRIL, GSTIN, filed_on=date(2025, 7, 25))
    assert monthly["late_filing"]["due_date"] == "2025-05-20"


def test_an_unknown_state_takes_the_earlier_date_and_says_so(monkeypatch):
    """`gstr3b_due_date`'s own rule is that an unknown state gets the EARLIER
    of the two — right for s.47, and the generous-to-the-revenue direction for
    interest. So it is NAMED rather than left reading as computed."""
    from datetime import date

    db = _setup(monkeypatch, registrations.QUARTERLY)
    out = grs.gstr3b_from_books(
        db, FIRM, "CLI", APRIL, GSTIN, filed_on=date(2025, 7, 25),
        frequency=registrations.QUARTERLY, state_code=None)
    assert out["late_filing"]["due_date"] == "2025-07-22"
    assert any("22nd" in c for c in out["late_filing"]["caveats"]), (
        out["late_filing"]["caveats"])


# ══════════════════════════════════════════════════════════════════════════════
# 7. What a quarterly return refuses to say about itself
# ══════════════════════════════════════════════════════════════════════════════

def test_a_quarterly_gstr1_names_the_two_things_it_cannot_answer(monkeypatch):
    """Both REPORTED rather than resolved: the form's own `fp` for a quarter
    could not be verified from this environment, and CGST Rule 59(2)'s Invoice
    Furnishing Facility for months 1 and 2 is not produced by this product —
    without which the RECIPIENT's credit waits for the quarter."""
    db = _setup(monkeypatch, registrations.QUARTERLY)
    gaps = grs.gstr1_from_books(db, FIRM, "CLI", APRIL, GSTIN,
                                frequency=registrations.QUARTERLY)["payload_gaps"]
    reasons = " ".join(g["reason"] for g in gaps)
    assert "Invoice Furnishing Facility" in reasons and "59(2)" in reasons
    assert "fp" in reasons and "first" in reasons


def test_a_monthly_gstr1_owes_neither_sentence(monkeypatch):
    db = _setup(monkeypatch)
    gaps = grs.gstr1_from_books(db, FIRM, "CLI", APRIL, GSTIN)["payload_gaps"]
    reasons = " ".join(g["reason"] for g in gaps)
    assert "Invoice Furnishing Facility" not in reasons
    assert "QRMP quarter" not in reasons


def test_the_two_sentences_are_different_sentences():
    """A shared paragraph would say the wrong thing about one of them: one is
    about the field this return files under, the other about a return it does
    not replace.

    The second stopped being a REFUSAL when `domain/gst/iff.py` was written —
    it now says the facility is available and where to prepare it — so this
    asserts the pair are distinct rather than that either declines anything.
    """
    assert (return_period.PAYLOAD_PERIOD_CAVEAT.format(key=APRIL)
            != return_period.IFF_AVAILABLE)
    assert "Rule 59(2)" in return_period.IFF_AVAILABLE
    assert "61A" in return_period.PAYLOAD_PERIOD_CAVEAT


def test_the_windows_are_written_from_knowledge_and_say_so():
    """Egress is refused at this environment's proxy, so every date in the
    module is `[S]`-graded and pinned by the parametrised test above."""
    assert return_period.VERIFIED is False


# ══════════════════════════════════════════════════════════════════════════════
# 8. The registration is where the frequency comes from
# ══════════════════════════════════════════════════════════════════════════════

def test_the_compute_path_reads_the_registrations_own_frequency(monkeypatch):
    """`domain/gst/registrations.Registration` has carried `filing_frequency`
    since GST-20 and the return engine threw it away — which is why a QRMP
    client was quoted the quarterly due date by one layer and handed a
    one-month return by the next."""
    seen = {}
    monkeypatch.setattr(gst_router, "_client_registration",
                        lambda *a, **k: registrations.Registration(
                            gstin=GSTIN, state_code="27", is_primary=True,
                            filing_frequency=registrations.QUARTERLY))
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: object())
    monkeypatch.setattr(gst_router.gst_return_service, "gstr3b_from_books",
                        lambda *a, **k: seen.update(k) or {})
    gst_router.gstr3b_from_books_endpoint(
        gst_router.FromBooksRequest(client_id="CLI", period=JUNE),
        current_user=CALLER)
    assert seen["frequency"] == registrations.QUARTERLY
    assert seen["state_code"] == "27"


def test_a_caller_may_state_the_frequency_and_wins(monkeypatch):
    """`filing_frequency` is the position TODAY and a return may be rebuilt for
    an earlier period; a client who moved off QRMP last April would otherwise
    have last year's quarters recomputed as months. There is no history
    column, so the caller may SAY — the `domain/tds/deductor.resolve` shape."""
    seen = {}
    monkeypatch.setattr(gst_router, "_client_registration",
                        lambda *a, **k: registrations.Registration(
                            gstin=GSTIN, state_code="27", is_primary=True,
                            filing_frequency=registrations.MONTHLY))
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: object())
    monkeypatch.setattr(gst_router.gst_return_service, "gstr3b_from_books",
                        lambda *a, **k: seen.update(k) or {})
    gst_router.gstr3b_from_books_endpoint(
        gst_router.FromBooksRequest(client_id="CLI", period=JUNE,
                                    filing_frequency=registrations.QUARTERLY),
        current_user=CALLER)
    assert seen["frequency"] == registrations.QUARTERLY


def test_the_request_refuses_a_frequency_the_act_does_not_have():
    """At the BOUNDARY, against the engine's own vocabulary rather than a
    second list. A value neither column's CHECK allows means the caller
    invented it, and coercing it to monthly would build a one-month return for
    somebody who asked for a quarter."""
    import pydantic

    ok = gst_router.FromBooksRequest(client_id="CLI", period=JUNE,
                                     filing_frequency="QUARTERLY")
    assert ok.filing_frequency == registrations.QUARTERLY
    assert gst_router.FromBooksRequest(
        client_id="CLI", period=JUNE).filing_frequency is None
    with pytest.raises(pydantic.ValidationError):
        gst_router.FromBooksRequest(client_id="CLI", period=JUNE,
                                    filing_frequency="annually")


def test_the_engine_never_reads_the_frequency_itself():
    """It is TOLD. `domain/gst/return_period` reads nothing and writes nothing,
    and the service takes the answer as a parameter — otherwise the historical
    case above could not be expressed at all, and the rule would have to know
    which of `clients` and `client_gst_registrations` a registration came from.

    Asserted on the READ rather than on the column's name, which appears in
    both modules' prose."""
    for mod in (return_period, grs):
        src = inspect.getsource(mod)
        assert 'select("gst_filing_frequency' not in src
        assert '"gst_filing_frequency"' not in src, (
            f"{mod.__name__} resolves the frequency itself instead of being told")
