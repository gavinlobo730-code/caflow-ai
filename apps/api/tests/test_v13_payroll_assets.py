"""
V1.3 Unit tests — Payroll, Fixed Assets calculations.
All financial calculations use integer paise arithmetic — no floating point.
IT Act §192, EPF Act, ESI Act, Companies Act 2013 Schedule II.
"""
import math
import pytest
from routers.payroll import (
    _compute_pf,
    _compute_esi,
    _compute_pt,
    _compute_tds_192,
    _compute_slip,
)
from routers.fixed_assets import _compute_annual_depreciation


# ─── PF Tests (EPF Act) ────────────────────────────────────────────────────────

class TestPF:
    def test_pf_standard(self):
        """12% of basic up to ₹15,000 cap → ₹1,800 each side."""
        result = _compute_pf(1500000)  # ₹15,000
        assert result["employee"] == 180000  # ₹1,800
        assert result["employer"] == 180000

    def test_pf_capped(self):
        """Basic > ₹15,000 — capped at ₹1,800."""
        result = _compute_pf(5000000)  # ₹50,000
        assert result["employee"] == 180000
        assert result["employer"] == 180000

    def test_pf_below_cap(self):
        """Basic ₹10,000 → PF = ₹1,200 each."""
        result = _compute_pf(1000000)
        assert result["employee"] == 120000
        assert result["employer"] == 120000

    def test_pf_zero(self):
        result = _compute_pf(0)
        assert result["employee"] == 0
        assert result["employer"] == 0


# ─── ESI Tests (ESI Act) ──────────────────────────────────────────────────────

class TestESI:
    def test_esi_applicable(self):
        """Gross ₹20,000 → employee 0.75% = ₹150, employer 3.25% = ₹650."""
        result = _compute_esi(2000000)
        assert result["employee"] == 15000   # ₹150
        assert result["employer"] == 65000   # ₹650

    def test_esi_ceiling_exceeded(self):
        """Gross > ₹21,000 → ESI not applicable."""
        result = _compute_esi(2200000)
        assert result["employee"] == 0
        assert result["employer"] == 0

    def test_esi_exactly_at_ceiling(self):
        """Gross = ₹21,000 → ESI applicable."""
        result = _compute_esi(2100000)
        assert result["employee"] == 15750   # 0.75% of ₹21,000
        assert result["employer"] == 68250   # 3.25% of ₹21,000

    def test_esi_zero(self):
        result = _compute_esi(0)
        assert result["employee"] == 0
        assert result["employer"] == 0


# ─── PT Tests (state-specific slabs — R2.10) ──────────────────────────────────
# _compute_pt used to ignore its `state` argument entirely and always applied
# the Karnataka slab. These tests now pass state explicitly since an unset/
# unrecognised state correctly returns 0 (see _compute_pt's docstring).

class TestPT:
    def test_pt_below_threshold(self):
        """Karnataka: gross < ₹15,000 → no PT."""
        assert _compute_pt(1400000, "KA") == 0

    def test_pt_slab_1(self):
        """Karnataka: ₹15,000 to ₹29,999 → ₹150/month."""
        assert _compute_pt(1500000, "KA") == 15000  # ₹150
        assert _compute_pt(2500000, "KA") == 15000

    def test_pt_slab_2(self):
        """Karnataka: ₹30,000+ → ₹200/month."""
        assert _compute_pt(3000000, "KA") == 20000  # ₹200
        assert _compute_pt(10000000, "KA") == 20000

    def test_pt_maharashtra(self):
        """Maharashtra: > ₹10,000/month → ₹200; at/below → nil."""
        assert _compute_pt(1000000, "MH") == 0
        assert _compute_pt(1000001, "MH") == 20000
        assert _compute_pt(5000000, "MH") == 20000

    def test_pt_west_bengal(self):
        """West Bengal: > ₹10,000/month → ₹200; at/below → nil."""
        assert _compute_pt(1000000, "WB") == 0
        assert _compute_pt(1000001, "WB") == 20000

    def test_pt_tamil_nadu(self):
        """Tamil Nadu: > ₹21,000/month → ₹208; at/below → nil."""
        assert _compute_pt(2100000, "TN") == 0
        assert _compute_pt(2100001, "TN") == 20800

    def test_pt_unrecognised_state_is_zero_not_karnataka(self):
        """An unknown state code must not silently fall back to Karnataka's
        rate — the historical bug this replaces."""
        assert _compute_pt(10000000, "XX") == 0

    def test_pt_unset_state_is_zero(self):
        """No state set at all → 0, not a silent Karnataka default."""
        assert _compute_pt(10000000) == 0
        assert _compute_pt(10000000, None) == 0

    def test_pt_state_is_case_and_whitespace_insensitive(self):
        assert _compute_pt(10000000, " ka ") == 20000
        assert _compute_pt(10000000, "ka") == 20000


# ─── TDS §192 Tests ───────────────────────────────────────────────────────────
# _compute_tds_192 withholds under the new regime (Section 115BAC(1A) default)
# using the FY-versioned statutory_rates registry. Tests pin fy="2025-26" (the
# last user-verified year, see statutory_rates.py) so they don't silently
# start failing once a later FY's rates are updated from carried-forward
# placeholders to real verified Finance Act figures.

class TestTDS192:
    def test_no_tax_below_4l_nil_band(self):
        """Annual taxable ≤ ₹4L (new-regime nil band) → no TDS."""
        assert _compute_tds_192(30000000, fy="2025-26") == 0  # ₹3,00,000

    def test_slab_5_percent_but_full_87a_rebate_applies(self):
        """₹4L–₹8L slab is 5%, but total income ₹5L is still under the ₹12L
        Section 87A rebate threshold, so the rebate wipes out the slab tax
        entirely -- annual TDS is zero, not just the plain 5% slab amount."""
        annual = 50000000  # ₹5,00,000
        monthly = _compute_tds_192(annual, fy="2025-26")
        assert monthly == 0

    def test_no_float_in_result(self):
        """Result must be an integer (paise), not float."""
        result = _compute_tds_192(120000000, fy="2025-26")
        assert isinstance(result, int)

    def test_high_income_above_rebate_threshold(self):
        """₹20L annual is above the ₹12L rebate threshold -- real tax applies
        across the new-regime slabs up to the 20% bracket."""
        annual = 200000000  # ₹20,00,000
        monthly = _compute_tds_192(annual, fy="2025-26")
        assert monthly > 0
        assert isinstance(monthly, int)

    def test_surcharge_applies_above_50l(self):
        """Annual taxable > ₹50L triggers Section 2(29C) surcharge on top of
        slab tax -- confirm it's actually being added, not silently skipped."""
        below = _compute_tds_192(499000000, fy="2025-26")   # ₹49.9L
        above = _compute_tds_192(600000000, fy="2025-26")   # ₹60L
        # Sanity: both should scale up with income even before comparing
        # surcharge-specific behaviour.
        assert above > below
        # At ₹60L the marginal 10% surcharge bracket applies; annual tax with
        # surcharge+cess must exceed plain slab tax with cess alone.
        from domain.income_tax.statutory_rates import rates_for, slab_tax_paise, cess_paise
        rates = rates_for("2025-26")
        plain_tax = slab_tax_paise(600000000, rates.new_regime_slabs)
        plain_with_cess = plain_tax + cess_paise(plain_tax, rates)
        assert above * 12 > plain_with_cess

    def test_new_regime_surcharge_capped_at_25_percent(self):
        """Even far above ₹5Cr (where the old regime's 37% bracket would
        apply), the new regime's surcharge never exceeds 25% (Finance Act
        2023 dropped the 37% slab for the new regime only)."""
        from domain.income_tax.statutory_rates import rates_for, slab_tax_paise
        rates = rates_for("2025-26")
        taxable = 6000000000  # ₹6 Cr
        monthly = _compute_tds_192(taxable, fy="2025-26")
        annual = monthly * 12
        plain_tax = slab_tax_paise(taxable, rates.new_regime_slabs)
        # annual (tax+surcharge+cess) must stay within a 25%-surcharge +
        # 4%-cess envelope of plain slab tax, not a 37%-surcharge envelope.
        max_with_25pct_surcharge_and_cess = math.ceil(plain_tax * 1.25 * 1.04 / 12)
        assert monthly <= max_with_25pct_surcharge_and_cess + 1  # +1 paise rounding slack


# ─── Payroll Slip Tests ───────────────────────────────────────────────────────

class TestPayrollSlip:
    def _emp(self, **kwargs):
        defaults = {
            "basic_paise": 2500000,          # ₹25,000
            "hra_percent": 40.0,
            "da_percent": 0.0,
            "lta_paise": 100000,             # ₹1,000
            "medical_paise": 125000,         # ₹1,250
            "special_allowance_paise": 50000, # ₹500
            "pf_applicable": True,
            "esi_applicable": False,         # gross > ₹21k
            "pt_applicable": True,
            "pt_state": "KA",
        }
        defaults.update(kwargs)
        return defaults

    def test_gross_calculation(self):
        emp = self._emp()
        slip = _compute_slip(emp)
        basic = 2500000
        hra   = math.floor(basic * 40 / 100)
        lta   = 100000
        medical = 125000
        special = 50000
        expected_gross = basic + hra + lta + medical + special
        assert slip["gross_paise"] == expected_gross

    def test_net_less_than_gross(self):
        slip = _compute_slip(self._emp())
        assert slip["net_paise"] < slip["gross_paise"]

    def test_lop_reduces_gross(self):
        """Loss of pay should reduce basic proportionally."""
        emp = self._emp()
        slip_full = _compute_slip(emp, {"working_days": 26, "days_present": 26, "lop_days": 0})
        slip_lop  = _compute_slip(emp, {"working_days": 26, "days_present": 23, "lop_days": 3})
        assert slip_lop["gross_paise"] < slip_full["gross_paise"]

    def test_all_paise_are_integers(self):
        slip = _compute_slip(self._emp())
        for key, val in slip.items():
            if key.endswith("_paise"):
                assert isinstance(val, int), f"{key} must be integer paise"

    def test_pf_not_applicable(self):
        emp = self._emp(pf_applicable=False)
        slip = _compute_slip(emp)
        assert slip["pf_employee_paise"] == 0
        assert slip["pf_employer_paise"] == 0


# ─── Depreciation Tests ───────────────────────────────────────────────────────

class TestDepreciation:
    def _asset(self, **kwargs):
        defaults = {
            "id": "test-asset-id",
            "asset_name": "Test Asset",
            "asset_category": "Computer",
            "purchase_cost_paise": 10000000,  # ₹1,00,000
            "salvage_value_paise": 0,
            "depreciation_method": "WDV",
            "wdv_rate_percent": 31.67,
            "accumulated_depreciation_paise": 0,
        }
        defaults.update(kwargs)
        return defaults

    def test_wdv_year1(self):
        """WDV 31.67% on ₹1,00,000 = ₹31,670/year → ₹2,639/month."""
        asset = self._asset()
        annual = _compute_annual_depreciation(asset)
        assert annual == math.floor(10000000 * 31.67 / 100)
        monthly = math.floor(annual / 12)
        assert isinstance(monthly, int)

    def test_wdv_reduces_each_year(self):
        """WDV depreciation decreases as accumulated depreciation grows."""
        asset_y1 = self._asset(accumulated_depreciation_paise=0)
        asset_y2 = self._asset(accumulated_depreciation_paise=3167000)  # after year 1
        assert _compute_annual_depreciation(asset_y1) > _compute_annual_depreciation(asset_y2)

    def test_sl_method(self):
        """SL: (cost - salvage) / useful life = constant each year."""
        asset = self._asset(
            depreciation_method="SL",
            useful_life_years=5,
            salvage_value_paise=1000000,  # ₹10,000
        )
        annual = _compute_annual_depreciation(asset)
        expected = math.floor((10000000 - 1000000) / 5)
        assert annual == expected

    def test_fully_depreciated(self):
        """Asset with WDV ≤ salvage → 0 depreciation."""
        asset = self._asset(
            accumulated_depreciation_paise=10000000,  # fully depreciated
            salvage_value_paise=0,
        )
        assert _compute_annual_depreciation(asset) == 0

    def test_sl_below_salvage_capped(self):
        """SL depreciation cannot push WDV below salvage value."""
        asset = self._asset(
            depreciation_method="SL",
            useful_life_years=5,
            salvage_value_paise=500000,     # ₹5,000
            accumulated_depreciation_paise=9700000,  # WDV = ₹3,000 < salvage
        )
        assert _compute_annual_depreciation(asset) == 0

    def test_result_is_integer(self):
        """Depreciation must always return integer paise."""
        asset = self._asset()
        result = _compute_annual_depreciation(asset)
        assert isinstance(result, int)


# ─── PF Boundary Tests ────────────────────────────────────────────────────────

class TestPFBoundary:
    def test_pf_exactly_at_cap(self):
        """Basic exactly ₹15,000 → PF = ₹1,800 (not capped, exactly at boundary)."""
        result = _compute_pf(1500000)
        assert result["employee"] == 180000
        assert result["employer"] == 180000

    def test_pf_one_paise_above_cap(self):
        """Basic ₹15,001 → still capped at ₹1,800 (cap applies above ₹15,000)."""
        result = _compute_pf(1500100)
        assert result["employee"] == 180000
        assert result["employer"] == 180000

    def test_pf_one_paise_below_cap(self):
        """Basic ₹14,999 → PF = 12% of ₹14,999 (not capped)."""
        result = _compute_pf(1499900)
        assert result["employee"] == 179988  # floor(1499900 * 12 / 100)
        assert result["employer"] == 179988

    def test_pf_symmetry(self):
        """Employee and employer PF must always be equal."""
        for basic in [500000, 1000000, 1500000, 2000000, 5000000]:
            r = _compute_pf(basic)
            assert r["employee"] == r["employer"], f"PF asymmetric at basic={basic}"

    def test_pf_integer_result(self):
        """PF must always be integer paise — no float."""
        result = _compute_pf(1234567)
        assert isinstance(result["employee"], int)
        assert isinstance(result["employer"], int)


# ─── ESI Boundary Tests ───────────────────────────────────────────────────────

class TestESIBoundary:
    def test_esi_one_paise_above_ceiling(self):
        """Gross ₹21,001 → ESI not applicable (above ceiling)."""
        result = _compute_esi(2100100)
        assert result["employee"] == 0
        assert result["employer"] == 0

    def test_esi_one_paise_below_ceiling(self):
        """Gross ₹20,999 → ESI applicable."""
        result = _compute_esi(2099900)
        assert result["employee"] > 0
        assert result["employer"] > 0

    def test_esi_rates_correct(self):
        """ESI Act §2(9): employee 0.75%, employer 3.25% of gross."""
        gross = 1800000  # ₹18,000
        result = _compute_esi(gross)
        assert result["employee"] == 13500   # 0.75% of 1800000 = 13500
        assert result["employer"] == 58500   # 3.25% of 1800000 = 58500

    def test_esi_total_is_4_percent(self):
        """Total ESI = employee + employer = 4% of gross."""
        gross = 2000000
        result = _compute_esi(gross)
        total = result["employee"] + result["employer"]
        expected = gross * 4 // 100
        assert abs(total - expected) <= 1  # allow 1 paise rounding tolerance

    def test_esi_integer_result(self):
        result = _compute_esi(1500000)
        assert isinstance(result["employee"], int)
        assert isinstance(result["employer"], int)


# ─── TDS §192 Boundary Tests ─────────────────────────────────────────────────

class TestTDS192Boundary:
    def test_exactly_at_300k_threshold(self):
        """Annual ₹3,00,000 exactly (below the new-regime ₹4L nil band) → no TDS."""
        assert _compute_tds_192(30000000, fy="2025-26") == 0

    def test_one_rupee_above_threshold(self):
        """Annual ₹3,00,001 → still nil (well below the ₹4L nil band)."""
        monthly = _compute_tds_192(30000100, fy="2025-26")
        assert monthly >= 0  # may be 0 due to floor division
        assert isinstance(monthly, int)

    def test_tds_monotonic_with_income(self):
        """Monthly TDS must never decrease as projected annual income rises,
        across every new-regime slab boundary (4L/8L/12L/16L/20L/24L) and
        through the Section 87A rebate zone below ₹12L."""
        incomes = [30000000, 50000000, 80000000, 120000000, 121000000,
                   160000000, 200000000, 240000000, 300000000]
        monthlies = [_compute_tds_192(inc, fy="2025-26") for inc in incomes]
        assert monthlies == sorted(monthlies)

    def test_cess_is_4_percent_of_tax_when_no_surcharge(self):
        """Health & Education Cess is 4% of tax (+ surcharge, but there's none
        here). At ₹20L annual -- above the Section 87A rebate threshold so
        rebate doesn't zero out the tax, and below the ₹50L surcharge
        threshold -- cess should be exactly 4% of plain slab tax."""
        from domain.income_tax.statutory_rates import rates_for, slab_tax_paise
        rates = rates_for("2025-26")
        taxable = 200000000  # ₹20,00,000
        tax = slab_tax_paise(taxable, rates.new_regime_slabs)
        expected_annual = tax + (tax * 4 // 100)
        monthly = _compute_tds_192(taxable, fy="2025-26")
        annual = monthly * 12
        # Floor-dividing by 12 then re-multiplying can lose up to 11 paise.
        assert abs(annual - expected_annual) <= 11

    def test_tds_never_negative(self):
        """TDS must always be non-negative."""
        for gross in [0, 100000, 2999999, 30000000, 100000000]:
            assert _compute_tds_192(gross, fy="2025-26") >= 0


# ─── Validator Tests ──────────────────────────────────────────────────────────

class TestValidators:
    """Tests for core/validators.py — Indian tax identifier validation."""

    def test_valid_gstin(self):
        from core.validators import validate_gstin
        assert validate_gstin("27AAAAA0000A1Z5") is None

    def test_invalid_gstin_format(self):
        from core.validators import validate_gstin
        assert validate_gstin("INVALID") is not None
        assert validate_gstin("00AAAAA0000A1Z5") is not None  # state 00 invalid

    def test_gstin_required(self):
        from core.validators import validate_gstin
        err = validate_gstin(None)
        assert err is not None
        assert "required" in err.lower()

    def test_valid_pan(self):
        from core.validators import validate_pan
        assert validate_pan("ABCDE1234F") is None

    def test_invalid_pan(self):
        from core.validators import validate_pan
        assert validate_pan("123AB456CD") is not None
        assert validate_pan("ABCDE12345") is not None  # digit at end

    def test_pan_optional(self):
        from core.validators import validate_pan
        assert validate_pan(None) is None

    def test_valid_phone(self):
        from core.validators import validate_phone
        assert validate_phone("9876543210") is None
        assert validate_phone("+919876543210") is None

    def test_invalid_phone(self):
        from core.validators import validate_phone
        assert validate_phone("123") is not None  # too short

    def test_valid_pincode(self):
        from core.validators import validate_pincode
        assert validate_pincode("400001") is None

    def test_invalid_pincode(self):
        from core.validators import validate_pincode
        assert validate_pincode("000001") is not None  # starts with 0
        assert validate_pincode("12345") is not None   # only 5 digits

    def test_collect_errors_aggregates(self):
        from core.validators import collect_errors, validate_gstin, validate_pan
        errors = collect_errors(
            gstin=(validate_gstin, "BAD"),
            pan=(validate_pan, "BADPAN"),
        )
        assert len(errors) == 2

    def test_collect_errors_empty_on_valid(self):
        from core.validators import collect_errors, validate_gstin, validate_pan
        errors = collect_errors(
            gstin=(validate_gstin, "27AAAAA0000A1Z5"),
            pan=(validate_pan, "ABCDE1234F"),
        )
        assert errors == []
