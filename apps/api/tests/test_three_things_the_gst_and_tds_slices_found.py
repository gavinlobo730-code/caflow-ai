"""
GST-29, TDS-28 and TDS-12 — from the 12 September probe pass.

  GST-29  the check digit was enforced wherever a human TYPES a GSTIN and
          nowhere on the paths that FILE with one.
  TDS-28  the server has read the deductor block from the client's own record
          since it stopped being invented, and no endpoint served it — so the
          compliance screen made the CA type the TAN every quarter.
  TDS-12  the monthly Rule 30(2) deposit existed for SALARY and for nothing
          else, so a TDS engagement was reminded of four statements a year and
          none of its twelve deposits.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from domain.gst.gstin import checksum_char
from domain.gst.validator import GSTValidator, InvoiceToValidate

WEB = Path("../web")

GOOD = "27AAPFU0939F1ZV"
TRANSPOSED = "27AAPFU0939F1ZX"          # one character off; the shape is fine


# ── GST-29: the return paths compute the check digit ─────────────────────────

def test_the_shape_alone_is_no_longer_enough_for_the_clients_own_gstin():
    """The return is FILED under this number. A valid-shaped wrong one files
    the quarter against a registration belonging to somebody else."""
    errs = GSTValidator().validate_gstin(TRANSPOSED)
    assert errs, "a transposed GSTIN passed the shape regex and was accepted"
    assert "check digit" in errs[0].message


def test_a_real_gstin_still_passes():
    assert GSTValidator().validate_gstin(GOOD) == []


def test_an_empty_own_gstin_is_still_required():
    """`problem_with` treats blank as "unregistered", which is right for a
    customer and wrong for the taxpayer filing the return."""
    errs = GSTValidator().validate_gstin("")
    assert errs and "required" in errs[0].message


def _invoice(**over) -> InvoiceToValidate:
    row = dict(reference_no="INV-1", transaction_date="2025-06-01",
               party_gstin=GOOD, place_of_supply="27",
               taxable_amount_paise=100_00,
               cgst_paise=9_00, sgst_paise=9_00, igst_paise=0,
               is_interstate=False, gst_rate=18.0)
    row.update(over)
    return InvoiceToValidate(**row)


def test_a_counterparty_gstin_is_checked_too():
    """§16(2)(aa) sends the credit to whoever the GSTIN names, so a
    valid-shaped wrong one hands a customer's ITC to a stranger."""
    errs = GSTValidator().validate_invoice(_invoice(party_gstin=TRANSPOSED), "062025")
    assert any(e.field == "party_gstin" and "check digit" in e.message for e in errs)


def test_a_counterparty_failure_is_reported_and_not_refused():
    """One invoice among hundreds. The error rides in the return's own
    exception list, where a CA fixes the master and rebuilds; refusing the
    whole build for one wrong counterparty is how a CA learns to skip the
    validator."""
    errs = GSTValidator().validate_invoice(_invoice(party_gstin=TRANSPOSED), "062025")
    assert isinstance(errs, list)          # returned, never raised
    assert all(e.invoice_ref for e in errs if e.field == "party_gstin"), (
        "the error must name the invoice, or a CA cannot find it")


def test_the_core_validator_computes_the_check_digit_too():
    """`routers/gst_workspace.py` records a filed return through this one."""
    from core.validators import validate_gstin
    assert validate_gstin(GOOD) is None
    problem = validate_gstin(TRANSPOSED)
    assert problem and "check digit" in problem


def test_no_gstin_shape_regex_survives_in_core_validators():
    """The pattern is an invitation to answer the question the cheap way."""
    src = Path("core/validators.py").read_text()
    assert "_GSTIN_RE" not in src.replace("# NO GSTIN REGEX HERE", "")


def test_the_two_state_lists_are_deliberately_different():
    """A place of supply may be 96 — outside India, which is where an export
    goes — and a GSTIN never begins 96, because it is a registration in a
    state. Collapsing them would either refuse every export or accept a GSTIN
    that cannot exist."""
    from domain.gst.gstin import VALID_STATE_CODES as GSTIN_STATES
    from domain.gst.validator import VALID_STATE_CODES as POS_STATES
    assert "96" in POS_STATES
    assert "96" not in GSTIN_STATES


def test_the_fixture_gstins_are_now_real_ones():
    """Correcting the FIXTURES rather than relaxing the guard, which is the
    call CLAUDE.md already records for the bulk-import door: the import path
    had only ever been exercised with GSTINs the portal would reject."""
    for g in ("27AAAAA0000A1Z2", "27AABCU9603R1ZN", "27BBBBB1111B1ZN"):
        assert g[14] == checksum_char(g[:14]), f"{g} is not a real GSTIN"


# ── TDS-28: the deductor block is served, not re-typed ───────────────────────

def test_the_deductor_endpoint_exists_and_reads_the_clients_own_record():
    import inspect
    import routers.tds as t
    src = inspect.getsource(t.deductor_block)
    assert "tds_deductor.resolve(identity, client)" in src, (
        "the block must come from client_statutory_identity and the client, "
        "not from anything the caller sends")
    assert "resolved" in src and "statutory_gaps" in src


def test_the_endpoint_names_the_gaps_rather_than_refusing():
    """The compute path REFUSES with these sentences, which is right at the
    moment a statement is built. A screen opening a form needs to say what to
    go and record, not fail."""
    import inspect
    import routers.tds as t
    src = inspect.getsource(t.deductor_block)
    assert "HTTPException" not in src
    assert "gaps_with_messages" in src


def test_both_readers_share_one_source_function():
    """The compute path and the new endpoint must read the same two rows, or
    a screen can pre-fill something the build then refuses."""
    import inspect
    import routers.tds as t
    for fn in (t.deductor_block, t._deductor_for):
        assert "_deductor_sources(" in inspect.getsource(fn)


def test_the_screen_prefills_instead_of_asking():
    page = (WEB / "app/clients/[id]/compliance/tds/page.tsx").read_text()
    assert "/api/tds/deductor?client_id=" in page, (
        "the TAN, legal name and PAN were typed again every quarter, for "
        "every client — and a quarter filed under a mistyped TAN is filed "
        "against somebody else's account")
    assert "loadDeductor()" in page


def test_the_prefill_does_not_overwrite_a_correction():
    """`_deductor_for` lets a caller-supplied value win, so the boxes stay
    editable — and reopening the panel must not discard a correction."""
    page = (WEB / "app/clients/[id]/compliance/tds/page.tsx").read_text()
    assert "tan: f.tan || d.tan" in page


def test_the_screen_shows_what_is_missing():
    page = (WEB / "app/clients/[id]/compliance/tds/page.tsx").read_text()
    assert "deductorGaps.map" in page


# ── TDS-12: the monthly non-salary deposit ───────────────────────────────────

def _tds_specs(fy="2025-26"):
    from services import compliance_obligation_service as ob
    return ob._tds_obligations(fy)


def test_a_tds_engagement_owes_twelve_monthly_deposits():
    """Rule 30(2) binds every deductor other than an office of the government.
    `compliance_engine.tds_deposit_due_date` computed this from the day the
    payroll module was built and was called from ONE place, so the calendar
    carried a monthly deposit for SALARY and nothing at all for the §194
    series."""
    deposits = [s for s in _tds_specs()
                if s["obligation_type"] == "TDS_NON_SALARY_DEPOSIT"]
    assert len(deposits) == 12


def test_the_seventh_of_the_following_month():
    deposits = {s["period_start"]: s["due_date"] for s in _tds_specs()
                if s["obligation_type"] == "TDS_NON_SALARY_DEPOSIT"}
    assert deposits["2025-04-01"] == "2025-05-07"
    assert deposits["2025-12-01"] == "2026-01-07"


def test_march_is_the_thirtieth_of_april():
    """The exception that catches people out, and §201(1A)(ii) charges from the
    date of DEDUCTION, so three weeks late on March costs two months."""
    deposits = {s["period_start"]: s["due_date"] for s in _tds_specs()
                if s["obligation_type"] == "TDS_NON_SALARY_DEPOSIT"}
    assert deposits["2026-03-01"] == "2026-04-30"


def test_it_is_its_own_obligation_type_and_not_a_second_salary_row():
    """Two deposits: different section codes on the challan, different
    registers behind them, and one is generated for a PAYROLL engagement while
    this is generated for a TDS one. The dedup key is (obligation_type,
    period_start), so sharing a type would silently drop one."""
    from services import compliance_obligation_service as ob
    assert "TDS_NON_SALARY_DEPOSIT" not in ob._PAYROLL_OBLIGATION_TYPE.values()
    assert "TDS_SALARY_DEPOSIT" in ob._PAYROLL_OBLIGATION_TYPE.values()
    types = {s["obligation_type"] for s in _tds_specs()}
    assert "TDS_SALARY_DEPOSIT" not in types, (
        "the salary deposit belongs to the payroll engagement; emitting it "
        "here too would double it for a client where the firm does both")


def test_the_due_date_comes_from_the_one_authority():
    import inspect
    from services import compliance_obligation_service as ob
    src = inspect.getsource(ob._tds_obligations)
    assert "ce.tds_deposit_due_date(y, m)" in src, (
        "the seventh-and-March arithmetic has one implementation and this is "
        "not allowed to be a second")


def test_a_deposit_period_is_a_month_not_a_quarter():
    deposits = [s for s in _tds_specs()
                if s["obligation_type"] == "TDS_NON_SALARY_DEPOSIT"]
    assert {s["period_start"] for s in deposits} == {
        f"2025-{m:02d}-01" for m in range(4, 13)
    } | {f"2026-{m:02d}-01" for m in range(1, 4)}


@pytest.mark.parametrize("fy", ["2025-26", "2026-27"])
def test_it_is_generated_for_every_year_the_statements_are(fy):
    deposits = [s for s in _tds_specs(fy)
                if s["obligation_type"] == "TDS_NON_SALARY_DEPOSIT"]
    assert len(deposits) == 12
