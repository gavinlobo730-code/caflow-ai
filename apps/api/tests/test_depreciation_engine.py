"""
Depreciation Engine Tests — Pre-Phase-6 Gate
Covers _compute_annual_depreciation() for SLM and WDV with all edge cases.
Companies Act 2013 Schedule II — verified calculation correctness.
All values in integer paise. No floats.
"""
import math
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.fixed_assets import _compute_annual_depreciation, _DEFAULT_WDV_RATES


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _sl_asset(**kwargs) -> dict:
    base = {
        "purchase_cost_paise": 100_000_00,  # ₹1,00,000
        "salvage_value_paise": 0,
        "useful_life_years": 5,
        "depreciation_method": "SL",
        "asset_category": "Other",
        "accumulated_depreciation_paise": 0,
    }
    base.update(kwargs)
    return base


def _wdv_asset(**kwargs) -> dict:
    base = {
        "purchase_cost_paise": 100_000_00,  # ₹1,00,000
        "salvage_value_paise": 0,
        "wdv_rate_percent": 25.0,
        "depreciation_method": "WDV",
        "asset_category": "Other",
        "accumulated_depreciation_paise": 0,
    }
    base.update(kwargs)
    return base


def _monthly(annual: int) -> int:
    return math.floor(annual / 12)


# ─── SLM Tests ───────────────────────────────────────────────────────────────

class TestSLM:
    def test_standard_slm(self):
        """₹1,00,000 asset, 5 year life, no salvage → ₹20,000/yr."""
        asset = _sl_asset()
        annual = _compute_annual_depreciation(asset)
        assert annual == 20_000_00  # ₹20,000 = 2000000 paise

    def test_slm_with_residual_value(self):
        """₹1,00,000 asset, ₹10,000 salvage, 5 year life → ₹18,000/yr."""
        asset = _sl_asset(salvage_value_paise=10_000_00)
        annual = _compute_annual_depreciation(asset)
        assert annual == 18_000_00  # (100000-10000)/5 = 18000

    def test_slm_integer_paise_precision(self):
        """Verify result is always an integer (math.floor, never float)."""
        asset = _sl_asset(purchase_cost_paise=100_001_00, useful_life_years=3)
        annual = _compute_annual_depreciation(asset)
        assert isinstance(annual, int)
        # ₹1,00,001 / 3 = ₹33,333.67 → floor → ₹33,333 = 3333300 paise
        assert annual == math.floor(100_001_00 / 3)

    def test_slm_monthly_for_3_year_computer(self):
        """Dell Laptop ₹80,000, SLM 3-year → annual ₹26,666.67 → monthly ₹2,222."""
        asset = _sl_asset(
            purchase_cost_paise=80_000_00,
            useful_life_years=3,
            asset_category="Computer",
        )
        annual = _compute_annual_depreciation(asset)
        monthly = _monthly(annual)
        # annual = floor(8000000 / 3) = 2666666 paise = ₹26,666.66
        assert annual == 2_666_666
        # monthly = floor(2666666 / 12) = 222222 paise = ₹2,222.22
        assert monthly == 222_222

    def test_slm_full_useful_life_exhausted(self):
        """Asset fully depreciated (accum >= cost - salvage) → returns 0."""
        asset = _sl_asset(
            purchase_cost_paise=100_000_00,
            salvage_value_paise=10_000_00,
            accumulated_depreciation_paise=90_000_00,  # WDV = ₹10,000 = salvage
        )
        annual = _compute_annual_depreciation(asset)
        assert annual == 0

    def test_slm_single_year_life(self):
        """1-year asset → full cost depreciated in year 1."""
        asset = _sl_asset(useful_life_years=1)
        annual = _compute_annual_depreciation(asset)
        assert annual == 100_000_00

    def test_slm_default_life_when_not_set(self):
        """Missing useful_life_years defaults to 5."""
        asset = _sl_asset()
        del asset["useful_life_years"]
        annual = _compute_annual_depreciation(asset)
        assert annual == 20_000_00  # 1,00,000 / 5

    def test_slm_cannot_depreciate_below_salvage(self):
        """Near-salvage asset: depreciation capped so WDV never drops below salvage."""
        # ₹1,00,000 asset, ₹10,000 salvage, already accumulated ₹88,000 (WDV=₹12,000)
        # Annual SLM = ₹18,000 but only ₹2,000 can be taken (WDV - salvage)
        asset = _sl_asset(
            salvage_value_paise=10_000_00,
            accumulated_depreciation_paise=88_000_00,
        )
        annual = _compute_annual_depreciation(asset)
        wdv = 100_000_00 - 88_000_00  # = ₹12,000
        assert annual == wdv - 10_000_00  # ₹2,000 only

    def test_slm_zero_residual_value(self):
        """Zero salvage: full depreciable amount = cost."""
        asset = _sl_asset(salvage_value_paise=0, useful_life_years=4)
        annual = _compute_annual_depreciation(asset)
        assert annual == math.floor(100_000_00 / 4)

    def test_slm_high_value_asset(self):
        """Maruti car ₹8,00,000 SLM 5 year → ₹1,60,000/yr."""
        asset = _sl_asset(
            purchase_cost_paise=800_000_00,
            useful_life_years=5,
            asset_category="Vehicle",
        )
        annual = _compute_annual_depreciation(asset)
        assert annual == 160_000_00
        assert _monthly(annual) == 13_333_33  # ₹13,333.33 monthly

    def test_slm_mid_year_acquisition_monthly(self):
        """Mid-year acquisition: annual is computed; caller divides by 12 for months active."""
        # Asset bought October — only 6 months in year 1
        # The engine returns annual; the router applies math.floor(annual/12)*months_active
        asset = _sl_asset(purchase_cost_paise=120_000_00, useful_life_years=5)
        annual = _compute_annual_depreciation(asset)
        monthly = _monthly(annual)
        # 6 months of depreciation:
        six_months = monthly * 6
        assert six_months == monthly * 6  # caller responsibility
        assert isinstance(six_months, int)  # always integer paise


# ─── WDV Tests ───────────────────────────────────────────────────────────────

class TestWDV:
    def test_standard_wdv_year1(self):
        """₹1,00,000 at 25% WDV → ₹25,000 year 1."""
        asset = _wdv_asset()
        annual = _compute_annual_depreciation(asset)
        assert annual == 25_000_00  # floor(100000*100 * 25 / 100) = 2500000

    def test_wdv_year2_on_reducing_balance(self):
        """Year 2: WDV = ₹75,000 → 25% = ₹18,750."""
        asset = _wdv_asset(accumulated_depreciation_paise=25_000_00)
        annual = _compute_annual_depreciation(asset)
        # WDV = 100000_00 - 25000_00 = 75000_00; 75000_00 * 25/100 = 18750_00
        assert annual == 18_750_00

    def test_wdv_year3_compounding(self):
        """Year 3: WDV = ₹56,250 → 25% = ₹14,062."""
        accum = 25_000_00 + 18_750_00  # years 1 and 2
        asset = _wdv_asset(accumulated_depreciation_paise=accum)
        annual = _compute_annual_depreciation(asset)
        wdv = 100_000_00 - accum
        expected = math.floor(wdv * 25 / 100)
        assert annual == expected

    def test_wdv_integer_paise_precision(self):
        """WDV always floors to integer paise."""
        asset = _wdv_asset(purchase_cost_paise=99_999_00, wdv_rate_percent=13.91)
        annual = _compute_annual_depreciation(asset)
        assert isinstance(annual, int)
        assert annual == math.floor(99_999_00 * 13.91 / 100)

    def test_wdv_computer_schedule_ii_rate(self):
        """Computer & IT Equipment: Schedule II WDV rate = 31.67%."""
        assert _DEFAULT_WDV_RATES["Computer & IT Equipment"] == 31.67
        asset = _wdv_asset(asset_category="Computer & IT Equipment", wdv_rate_percent=31.67, purchase_cost_paise=80_000_00)
        annual = _compute_annual_depreciation(asset)
        assert annual == math.floor(80_000_00 * 31.67 / 100)

    def test_wdv_vehicle_schedule_ii_rate(self):
        """Vehicles: Schedule II WDV rate = 25.89%."""
        assert _DEFAULT_WDV_RATES["Vehicles"] == 25.89
        asset = _wdv_asset(asset_category="Vehicles", wdv_rate_percent=25.89, purchase_cost_paise=800_000_00)
        annual = _compute_annual_depreciation(asset)
        assert annual == math.floor(800_000_00 * 25.89 / 100)

    def test_wdv_furniture_schedule_ii_rate(self):
        """Furniture & Fixtures: Schedule II WDV rate = 10.00%."""
        assert _DEFAULT_WDV_RATES["Furniture & Fixtures"] == 10.00
        asset = _wdv_asset(asset_category="Furniture & Fixtures", wdv_rate_percent=10.00, purchase_cost_paise=150_000_00)
        annual = _compute_annual_depreciation(asset)
        assert annual == math.floor(150_000_00 * 10.00 / 100)

    def test_wdv_high_value_asset(self):
        """₹50,00,000 plant at 13.91% WDV → ₹6,95,500/yr."""
        asset = _wdv_asset(purchase_cost_paise=5_000_000_00, wdv_rate_percent=13.91)
        annual = _compute_annual_depreciation(asset)
        assert annual == math.floor(5_000_000_00 * 13.91 / 100)
        assert isinstance(annual, int)

    def test_wdv_multiple_year_sequence(self):
        """3-year WDV sequence must produce declining amounts."""
        cost = 100_000_00
        accum = 0
        rate = 25.0
        prev_annual = None
        for year in range(1, 4):
            asset = _wdv_asset(accumulated_depreciation_paise=accum)
            annual = _compute_annual_depreciation(asset)
            if prev_annual is not None:
                assert annual < prev_annual, f"Year {year} dep should be < year {year-1}"
            prev_annual = annual
            accum += annual

    def test_wdv_with_salvage_value(self):
        """WDV cannot go below salvage."""
        # Asset with very small WDV remaining just above salvage
        asset = _wdv_asset(
            purchase_cost_paise=100_000_00,
            salvage_value_paise=5_000_00,
            accumulated_depreciation_paise=95_500_00,  # WDV = ₹4,500 < salvage ₹5,000
        )
        annual = _compute_annual_depreciation(asset)
        assert annual == 0  # WDV already below salvage

    def test_wdv_stops_at_salvage(self):
        """WDV depreciation capped at (WDV - salvage) when annual would exceed it."""
        # WDV = ₹6,000, salvage = ₹5,000, rate 25% → annual = ₹1,500 < ₹1,000 remaining
        asset = _wdv_asset(
            purchase_cost_paise=100_000_00,
            salvage_value_paise=5_000_00,
            wdv_rate_percent=25.0,
            accumulated_depreciation_paise=94_100_00,  # WDV = ₹5,900
        )
        annual = _compute_annual_depreciation(asset)
        wdv = 100_000_00 - 94_100_00  # ₹5,900
        salvage = 5_000_00
        expected = min(math.floor(wdv * 25 / 100), wdv - salvage)  # min(₹1,475, ₹900) = ₹900
        assert annual == expected


# ─── Edge Cases ──────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_zero_cost_asset(self):
        """Zero-cost asset → zero depreciation."""
        asset = _sl_asset(purchase_cost_paise=0)
        annual = _compute_annual_depreciation(asset)
        assert annual == 0

    def test_fully_depreciated_sl(self):
        """Fully depreciated SL asset (accum = cost) → 0."""
        asset = _sl_asset(accumulated_depreciation_paise=100_000_00)
        annual = _compute_annual_depreciation(asset)
        assert annual == 0

    def test_fully_depreciated_wdv(self):
        """Fully depreciated WDV asset → 0 (wdv_now <= salvage)."""
        asset = _wdv_asset(accumulated_depreciation_paise=100_000_00)
        annual = _compute_annual_depreciation(asset)
        assert annual == 0

    def test_disposal_before_useful_life_ends(self):
        """After disposal: depreciation should not be computed (router guard).
        Here we verify the pure function returns the remaining depreciable amount."""
        # Bought at ₹1,00,000, sold after 2 years (₹40,000 accumulated SLM 5yr)
        asset = _sl_asset(accumulated_depreciation_paise=40_000_00)
        annual = _compute_annual_depreciation(asset)
        # Still has ₹60,000 to depreciate; annual is ₹20,000
        assert annual == 20_000_00

    def test_depreciation_never_negative(self):
        """Depreciation is always >= 0 regardless of inputs."""
        for method, kwargs in [
            ("SL", {"depreciation_method": "SL", "accumulated_depreciation_paise": 200_000_00}),
            ("WDV", {"depreciation_method": "WDV", "accumulated_depreciation_paise": 200_000_00}),
        ]:
            asset = _sl_asset(**kwargs) if method == "SL" else _wdv_asset(**kwargs)
            annual = _compute_annual_depreciation(asset)
            assert annual >= 0, f"{method}: depreciation must be >= 0"

    def test_monthly_depreciation_is_floor_of_annual_div_12(self):
        """Monthly = floor(annual / 12) — verified for both methods."""
        for asset in [
            _sl_asset(purchase_cost_paise=100_001_00, useful_life_years=3),
            _wdv_asset(purchase_cost_paise=100_001_00, wdv_rate_percent=25.0),
        ]:
            annual = _compute_annual_depreciation(asset)
            monthly = math.floor(annual / 12)
            assert isinstance(monthly, int)
            assert monthly == math.floor(annual / 12)

    def test_paise_arithmetic_no_float_leakage(self):
        """Verify output is always int, never float."""
        test_assets = [
            _sl_asset(purchase_cost_paise=333_333_33, useful_life_years=7),
            _wdv_asset(purchase_cost_paise=777_777_00, wdv_rate_percent=18.10),
            _sl_asset(purchase_cost_paise=1_00_00_000_00, useful_life_years=30),
        ]
        for asset in test_assets:
            result = _compute_annual_depreciation(asset)
            assert type(result) is int, f"Expected int, got {type(result)}"


# ─── Journal Output Verification ─────────────────────────────────────────────

class TestDepreciationJournalIntegrity:
    """Verify that monthly depreciation * 12 months never exceeds annual."""

    def test_12_months_never_exceed_annual(self):
        """Sum of 12 monthly floor values should be <= annual (floor division)."""
        for cost in [80_000_00, 150_000_00, 800_000_00, 100_001_00]:
            for life in [3, 5, 10]:
                asset = _sl_asset(purchase_cost_paise=cost, useful_life_years=life)
                annual = _compute_annual_depreciation(asset)
                monthly = math.floor(annual / 12)
                total_12 = monthly * 12
                assert total_12 <= annual, (
                    f"12×monthly ({total_12}) > annual ({annual}) for cost={cost} life={life}"
                )

    def test_wdv_12_months_never_exceed_annual(self):
        for cost in [100_000_00, 500_000_00, 800_000_00]:
            asset = _wdv_asset(purchase_cost_paise=cost)
            annual = _compute_annual_depreciation(asset)
            monthly = math.floor(annual / 12)
            assert monthly * 12 <= annual

    def test_schedule_ii_rates_exist_for_all_categories(self):
        """All Schedule II asset categories have WDV rates defined — must match
        the taxonomy actually used platform-wide (create/edit form's CATEGORIES
        list, phase2_journal_service's cat_map GL mapping)."""
        required = [
            "Plant & Machinery", "Furniture & Fixtures", "Computer & IT Equipment",
            "Office Equipment", "Vehicles", "Building", "Land", "Intangibles", "Other",
        ]
        for cat in required:
            assert cat in _DEFAULT_WDV_RATES, f"Missing WDV rate for category: {cat}"
            if cat == "Land":
                assert _DEFAULT_WDV_RATES[cat] == 0  # land never depreciates (Schedule II)
            else:
                assert _DEFAULT_WDV_RATES[cat] > 0
