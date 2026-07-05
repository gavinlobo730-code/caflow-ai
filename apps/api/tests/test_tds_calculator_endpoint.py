"""
TDS Calculator endpoint — regression tests (H10).

/api/tds/compute-amount already resolved TDS via the authoritative
TDSComputer.resolve_tds(), but had no way to derive is_company/has_pan from a
payee's PAN the way the real purchase-bill TDS deduction does (routers/
purchase_bills.py, via is_company_pan()/has_pan()) — a caller had to already
know whether the payee counted as a "company" for TDS purposes, which is
exactly the kind of business-rule knowledge the frontend "TDS Calculator"
tool (apps/web/app/accounting/suppliers/page.tsx) used to hardcode itself
instead of asking the authoritative source. Adding an optional `pan` field
lets the calculator delegate that derivation entirely, per section 194's
individual/HUF-vs-other split (IT Act Chapter XVII-B).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException
import pytest

import routers.tds as tds_router
from routers.tds import TDSAmountRequest, compute_tds_amount, list_tds_sections

USER = {"firm_id": "firm-1", "id": "u1"}


def _compute(**overrides):
    payload = {"section": "194J", "payment_amount_paise": 60_000_00}
    payload.update(overrides)
    return compute_tds_amount(TDSAmountRequest(**payload), USER)


def test_pan_for_individual_derives_individual_rate():
    # 4th char 'P' -> individual/HUF rate, per is_company_pan()
    result = _compute(section="194C", payment_amount_paise=50_000_00, pan="ABCPE1234F")
    assert result["data"]["applicable_rate_pct"] == 1.0  # 194C individual rate


def test_pan_for_company_derives_company_rate():
    # 4th char 'C' -> non-individual/company rate
    result = _compute(section="194C", payment_amount_paise=50_000_00, pan="ABCCE1234F")
    assert result["data"]["applicable_rate_pct"] == 2.0  # 194C company rate


def test_no_pan_floors_at_section_206aa_rate():
    result = _compute(section="194H", payment_amount_paise=1_00_000_00, pan=None, has_pan=False)
    assert result["data"]["applicable_rate_pct"] == 20.0  # 206AA floor, not 194H's normal 2%


def test_missing_pan_field_falls_back_to_explicit_is_company_flag():
    """Existing callers that never pass `pan` keep their prior contract exactly."""
    result = _compute(section="194C", payment_amount_paise=50_000_00, is_company=True)
    assert result["data"]["applicable_rate_pct"] == 2.0


def test_boundary_at_threshold_no_tds_applies():
    # 194C single-payment threshold is exactly ₹30,000 — AT threshold, TDS does not apply.
    result = _compute(section="194C", payment_amount_paise=30_000_00, pan="ABCPE1234F")
    assert result["data"]["tds_applicable"] is False
    assert result["data"]["tds_paise"] == 0


def test_boundary_above_threshold_tds_applies():
    result = _compute(section="194C", payment_amount_paise=30_000_01, pan="ABCPE1234F")
    assert result["data"]["tds_applicable"] is True
    assert result["data"]["tds_paise"] == 30_000_01 * 100 // 10000  # 1% individual rate


def test_rounding_floors_never_over_deducts():
    # An odd amount that doesn't divide evenly at 2% must floor, not round up.
    result = _compute(section="194H", payment_amount_paise=20_000_01, pan="ABCCE1234F")
    expected = 20_000_01 * 200 // 10000
    assert result["data"]["tds_paise"] == expected
    assert result["data"]["tds_paise"] < 20_000_01 * 200 // 10000 + 1


def test_multiple_financial_years_resolve_independently():
    r_2025 = _compute(section="194H", payment_amount_paise=1_00_000_00, fy="2025-26")
    r_2026 = _compute(section="194H", payment_amount_paise=1_00_000_00, fy="2026-27")
    assert r_2025["data"]["fy"] == "2025-26"
    assert r_2026["data"]["fy"] == "2026-27"
    # Same section, same rate under both currently-registered FYs (2026-27 is a
    # verified carry-forward of 2025-26) — but each call resolves its OWN FY's
    # table independently rather than defaulting to "today", proving fy is honored.
    assert r_2025["data"]["rates_verified"] is True


def test_unknown_section_rejected():
    with pytest.raises(HTTPException) as exc:
        _compute(section="999Z")
    assert exc.value.status_code == 400


def test_matches_authoritative_resolve_tds_directly():
    """The endpoint's result must be identical to calling the authoritative
    TDSComputer.resolve_tds() with the same PAN-derived inputs — no
    duplicated/divergent math in the router layer."""
    from domain.tds.tds_computer import is_company_pan, has_pan as pan_on_file

    pan = "ABCCE1234F"
    amount = 75_000_00
    section = "194J"
    endpoint_result = _compute(section=section, payment_amount_paise=amount, pan=pan)

    direct = tds_router.computer.resolve_tds(
        section, amount, is_company=is_company_pan(pan), fy=None, has_pan=pan_on_file(pan),
    )
    assert endpoint_result["data"]["tds_paise"] == direct.tds_paise
    assert endpoint_result["data"]["applicable_rate_pct"] == direct.rate_pct


def test_sections_endpoint_lists_previously_missing_sections():
    """The stale frontend calculator's dropdown only had 194C/I/J/H/A/B —
    the authoritative /sections list must include the ones it was missing."""
    result = list_tds_sections(fy=None, user=USER)
    sections = {s["section"] for s in result["data"]["sections"]}
    for missing in ("194D", "194G", "194K", "194LA", "194Q", "193", "194"):
        assert missing in sections
