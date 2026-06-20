"""
Phase 3.3A — Practice-as-Client activation, identity maintenance, state-code
derivation, and canonical CoA consolidation. Pure-logic regression tests (no DB).
"""
import re
import pytest

from core.validators import derive_state_code, INDIAN_STATE_CODES
from services.coa_seed_service import STANDARD_COA
from models.client import PracticeIdentityUpdate


# ── Part C — state_code derivation priority ──────────────────────────────────

def test_derive_prefers_explicit_valid_code():
    # explicit (1) wins over gstin (2) and name (3)
    assert derive_state_code("27", "Karnataka", "29ABCDE1234F1Z5") == "27"


def test_derive_skips_invalid_explicit_then_uses_gstin():
    assert derive_state_code("ZZ", None, "29ABCDE1234F1Z5") == "29"


def test_derive_uses_gstin_prefix():
    assert derive_state_code(None, None, "27ABCDE1234F1Z5") == "27"


def test_derive_gstin_beats_state_name():
    assert derive_state_code(None, "Karnataka", "27ABCDE1234F1Z5") == "27"


def test_derive_falls_back_to_state_name():
    assert derive_state_code(None, "Maharashtra", None) == "27"
    assert derive_state_code(None, "tamil nadu", None) == "33"  # case-insensitive


def test_derive_returns_none_when_unresolvable():
    assert derive_state_code(None, "Atlantis", None) is None
    assert derive_state_code(None, None, None) is None


def test_state_map_is_reference_data():
    assert INDIAN_STATE_CODES["maharashtra"] == "27"
    assert INDIAN_STATE_CODES["karnataka"] == "29"


# ── Part E — canonical CoA invariants ────────────────────────────────────────

# Mirrors tests/test_batch3_1_hardening.REQUIRED_PATTERNS — posting must always
# resolve every account the journal engine looks up.
_REQUIRED_PATTERNS = [
    "%Trade Receivable%", "%Sales%", "%GST Output%", "%Bank%", "%Purchase%",
    "%Expense%", "%GST Input%", "%Trade Payable%", "%TDS Payable%",
    "%TDS Payable - Salary%", "%Salaries Expense%", "%Net Salary Payable%",
    "%PF Payable%", "%ESI Payable%", "%PT Payable%", "%Plant & Machinery%",
    "%Furniture & Fixtures%", "%Computers & Software%", "%Vehicles%",
    "%Land & Building%", "%Intangible Assets%", "%Accumulated Depreciation%",
    "%Depreciation Expense%", "%Profit on Asset Disposal%", "%Loss on Asset Disposal%",
]


def test_coa_codes_are_unique():
    codes = [c for (c, _n, _t, _s) in STANDARD_COA]
    assert len(codes) == len(set(codes)), "duplicate account codes in canonical CoA"


def test_coa_types_valid_and_income_standardised_to_revenue():
    valid = {"Asset", "Liability", "Equity", "Revenue", "Expense"}
    for (_c, _n, t, _s) in STANDARD_COA:
        assert t in valid, f"invalid account_type: {t}"
    # Canonical uses 'Revenue' (frontend Schedule III buckets on 'revenue'); the
    # legacy 'Income' must be gone to avoid mis-bucketing.
    assert not any(t == "Income" for (_c, _n, t, _s) in STANDARD_COA)


def test_coa_covers_all_engine_patterns():
    names = [n for (_c, n, _t, _s) in STANDARD_COA]
    for pat in _REQUIRED_PATTERNS:
        rx = pat.replace("%", ".*")
        assert any(re.fullmatch(rx, n, re.IGNORECASE) for n in names), \
            f"canonical CoA missing an account matching {pat}"


def test_coa_includes_ca_practice_accounts():
    names = {n.lower() for (_c, n, _t, _s) in STANDARD_COA}
    # Audit gap items now present in the single canonical source.
    assert "drawings account" in names
    assert "audit fees" in names
    assert "gst consultancy fees" in names
    assert "software subscriptions" in names


def test_coa_has_revenue_and_expense_and_equity():
    types = {t for (_c, _n, t, _s) in STANDARD_COA}
    assert {"Asset", "Liability", "Equity", "Revenue", "Expense"} <= types


# ── Part B — practice identity model validation ──────────────────────────────

def test_identity_normalises_and_validates_pan():
    m = PracticeIdentityUpdate(pan="aabcu9603r")
    assert m.pan == "AABCU9603R"
    with pytest.raises(Exception):
        PracticeIdentityUpdate(pan="NOTAPAN")


def test_identity_validates_gstin():
    m = PracticeIdentityUpdate(gstin="27AABCU9603R1ZX")
    assert m.gstin == "27AABCU9603R1ZX"
    with pytest.raises(Exception):
        PracticeIdentityUpdate(gstin="BAD-GSTIN")


def test_identity_allows_partial_fields():
    m = PracticeIdentityUpdate(state="Maharashtra")
    assert m.state == "Maharashtra"
    assert m.pan is None and m.gstin is None and m.state_code is None
