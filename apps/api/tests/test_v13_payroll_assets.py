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


# ─── PT Tests (Karnataka slab) ────────────────────────────────────────────────

class TestPT:
    def test_pt_below_threshold(self):
        """Gross < ₹15,000 → no PT."""
        assert _compute_pt(1400000) == 0

    def test_pt_slab_1(self):
        """₹15,000 to ₹29,999 → ₹150/month."""
        assert _compute_pt(1500000) == 15000  # ₹150
        assert _compute_pt(2500000) == 15000

    def test_pt_slab_2(self):
        """₹30,000+ → ₹200/month."""
        assert _compute_pt(3000000) == 20000  # ₹200
        assert _compute_pt(10000000) == 20000


# ─── TDS §192 Tests ───────────────────────────────────────────────────────────

class TestTDS192:
    def test_no_tax_below_300k(self):
        """Annual taxable ≤ ₹3L → no TDS."""
        assert _compute_tds_192(30000000) == 0  # ₹3,00,000

    def test_slab_5_percent(self):
        """₹3L–₹7L: 5% on excess. Annual ₹5L → tax = ₹10,000 + cess."""
        annual = 50000000  # ₹5,00,000
        monthly = _compute_tds_192(annual)
        # tax = (500000 - 300000) * 0.05 = 10000, +4% cess = 10400
        expected_monthly = math.floor(10400 * 100 / 12)  # paise / 12
        assert monthly == expected_monthly

    def test_no_float_in_result(self):
        """Result must be an integer (paise), not float."""
        result = _compute_tds_192(120000000)
        assert isinstance(result, int)

    def test_high_income(self):
        """₹20L annual → 30% slab applies."""
        annual = 200000000  # ₹20,00,000
        monthly = _compute_tds_192(annual)
        assert monthly > 0
        assert isinstance(monthly, int)


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
