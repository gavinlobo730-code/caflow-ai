"""
Fixed assets: the Schedule II table, and the two ways a monthly posting could
not complete.

THREE DEFECTS, ALL REPRODUCED BEFORE THEY WERE FIXED.

1. The "Companies Act 2013 Schedule II" default WDV rates were not Schedule II
   rates. Schedule II Part C prescribes useful LIVES; the WDV rate is derived
   from a life by R = 1 − (residual/cost)^(1/n), at the 5% residual cap of
   Part C Note 5. Of the nine categories shipped, only Building was close
   (5.00% against 4.87%), and the provenance of the wrong ones was visible in
   the numbers: Furniture 10.00% and Intangibles 25.00% are INCOME TAX ACT
   block rates, and 25.89% — the correct ten-year figure — sat against
   Vehicles, which Schedule II gives eight years. Office Equipment was out by
   31 percentage points. Every wrong entry UNDER-depreciated, on a form that
   told the CA the figure was Schedule II's.

2. fixed_assets.depreciation_posted_through is a DATE. The router wrote the
   'YYYY-MM' period label into it, which Postgres rejects (22007
   invalid_input_syntax_for_type_date) — and it rejects the whole UPDATE, so
   the depreciation journal landed on the ledger and the register never moved:
   accumulated depreciation stayed at 0 and the WDV stayed at cost, for ever.
   The posting kernel's dedupe on (client_id, reference_no, entry_date) then
   made every retry look like a duplicate, so the loss was silent.

   The guard against a THIRD one of these is _TypeCheckedFakeDB below: it
   checks every write against the production column types recorded in
   tests/fixtures/production_schema_2026-09-03.json, so a value Postgres would
   reject fails in the mock suite, with no database and no HARNESS_PG.

3. Depreciation was monthly-only with no catch-up. Posting Apr–Aug and then
   Oct charged one month for October and moved posted-through with it;
   September was then unreachable for ever, because the idempotency check only
   compares against the furthest month reached. The year was short a month's
   depreciation and nothing said so.
"""
import json
import os
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import routers.fixed_assets as fa
from routers.fixed_assets import (
    SCHEDULE_II_CATEGORIES,
    SCHEDULE_II_RESIDUAL_FRACTION,
    _DEFAULT_WDV_RATES,
    _compute_annual_depreciation,
    _month_label,
    _months_missing_before,
    _wdv_rate_for_life,
)
from models.accounting import DepreciationIn, FixedAssetIn
from tests.production_types import assert_write_fits_production_types

FIRM, CLIENT = "firm-1", "client-1"
USER = {"firm_id": FIRM, "id": "u1"}


# ── A fake Supabase that refuses what Postgres would refuse ─────────────────
#
# The production schema fixture records every column's type. Checking each
# written value against it turns "the column is a date and the code writes a
# month label" from a defect only production can find into a mock-mode test
# failure. Deliberately general: any router can post its writes through
# assert_write_fits_production_types() — routers/year_end_adjustments.py has a
# defect of exactly this shape.

# The check itself now lives in tests/production_types.py and is wired into
# the shared e2e harness, so every FakeDB write in the suite goes through it —
# this file had the only copy, and two implementations of one rule drift. What
# stays here is the local fake, which predates the shared harness.
class _Resp:
    def __init__(self, data, count=None):
        self.data, self.count = data, count


class _Q:
    """Same shape and semantics as the fake in test_r232_fixed_asset_depreciation
    (the house pattern for this router), with the type check on every write."""

    def __init__(self, store, table):
        self.s, self.t = store, table
        self.op, self.payload, self.f = "select", None, []
        self.single_ = False
        self._count_mode = None

    def insert(self, p):
        self.op, self.payload = "insert", p
        return self

    def update(self, p):
        self.op, self.payload = "update", p
        return self

    def select(self, *a, count=None, **k):
        self.op, self._count_mode = "select", count
        return self

    def eq(self, k, v):
        self.f.append((k, v))
        return self

    def order(self, *a, **k):
        return self

    def single(self):
        self.single_ = True
        return self

    def _match(self):
        return [r for r in self.s.setdefault(self.t, []) if all(r.get(k) == v for k, v in self.f)]

    def execute(self):
        if self.op == "insert":
            rows = self.s.setdefault(self.t, [])
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            out = []
            for p in items:
                assert_write_fits_production_types(self.t, p)
                rec = dict(p)
                rec.setdefault("id", f"{self.t}-{len(rows) + 1}")
                rows.append(rec)
                out.append(rec)
            return _Resp(out)
        m = self._match()
        if self.op == "update":
            assert_write_fits_production_types(self.t, self.payload)
            for r in m:
                r.update(self.payload)
            return _Resp(m)
        if self._count_mode:
            return _Resp(m, count=len(m))
        if self.single_:
            return _Resp(m[0] if m else None)
        return _Resp(m)


class TypeCheckedFakeDB:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return _Q(self.store, name)


def _seed_asset(db, **overrides):
    asset = {
        "id": "asset-1", "firm_id": FIRM, "client_id": CLIENT,
        "asset_name": "Test Machine", "asset_code": "FA-001",
        "asset_category": "Plant & Machinery", "is_disposed": False,
        "purchase_date": "2026-04-01",
        "purchase_cost_paise": 100_000_00, "salvage_value_paise": 0,
        "depreciation_method": "WDV", "wdv_rate_percent": 24.0,
        "accumulated_depreciation_paise": 0,
        "depreciation_posted_through": None,
        "depreciation_fy": None, "depreciation_fy_start_accum_paise": None,
    }
    asset.update(overrides)
    db.store.setdefault("fixed_assets", []).append(asset)
    return asset


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch):
    monkeypatch.setattr(fa.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(fa._journal_svc, "journal_for_depreciation", lambda *a, **k: "je-1")
    monkeypatch.setattr(fa._journal_svc, "journal_for_asset_acquisition", lambda *a, **k: "je-acq")
    yield


# ── 1. The rates are DERIVED from Schedule II lives ─────────────────────────

def test_a_life_of_none_has_no_rate_and_a_ten_year_life_has_25_89():
    """The derivation itself, at its two ends."""
    assert _wdv_rate_for_life(None) is None
    assert _wdv_rate_for_life(0) is None
    assert _wdv_rate_for_life(10) == Decimal("25.89")


def test_the_residual_cap_is_the_five_percent_schedule_ii_allows():
    """Part C Note 5: the residual value "should generally be not more than 5%
    of the original cost". It is the one term in the derivation that is a
    statutory cap rather than an input, so it is named, not a literal."""
    assert SCHEDULE_II_RESIDUAL_FRACTION == Decimal("0.05")


def test_every_rate_is_the_life_put_through_the_formula():
    """R = 1 − (residual/cost)^(1/n), recomputed here independently. No rate is
    written down anywhere — the LIFE is the datum, which is what the Schedule
    actually prescribes."""
    for category, classes in SCHEDULE_II_CATEGORIES.items():
        for cls in classes:
            n = cls["useful_life_years"]
            if n is None:
                continue
            expected = ((1 - Decimal("0.05") ** (Decimal(1) / Decimal(n))) * 100).quantize(Decimal("0.01"))
            assert cls["wdv_rate_percent"] == expected, f"{category}: {cls['label']}"


@pytest.mark.parametrize("category,life,rate", [
    ("Building",                60, Decimal("4.87")),
    ("Plant & Machinery",       15, Decimal("18.10")),
    ("Furniture & Fixtures",    10, Decimal("25.89")),
    ("Office Equipment",         5, Decimal("45.07")),
    ("Computer & IT Equipment",  3, Decimal("63.16")),
    ("Vehicles",                 8, Decimal("31.23")),
])
def test_the_default_class_is_the_schedule_ii_life_and_its_rate(category, life, rate):
    default = SCHEDULE_II_CATEGORIES[category][0]
    assert default["useful_life_years"] == life
    assert default["wdv_rate_percent"] == rate
    assert _DEFAULT_WDV_RATES[category] == rate


@pytest.mark.parametrize("category,retired", [
    ("Plant & Machinery",       Decimal("15.33")),
    ("Furniture & Fixtures",    Decimal("10.00")),   # Income-tax Act block rate
    ("Computer & IT Equipment", Decimal("31.67")),
    ("Office Equipment",        Decimal("13.91")),
    ("Vehicles",                Decimal("25.89")),   # the TEN-year figure, on an 8-year class
    ("Intangibles",             Decimal("25.00")),   # Income-tax Act block rate
    ("Other",                   Decimal("15.33")),
])
def test_the_rates_that_were_not_schedule_ii_are_gone(category, retired):
    assert _DEFAULT_WDV_RATES[category] != retired


def test_computers_carry_both_schedule_ii_lives():
    """Part C gives servers and networks six years and end user devices three.
    A laptop and a rack are not the same asset and the CA picks; the end user
    device is only the DEFAULT because it is the ordinary purchase."""
    classes = SCHEDULE_II_CATEGORIES["Computer & IT Equipment"]
    by_life = {c["useful_life_years"]: c["wdv_rate_percent"] for c in classes}
    assert by_life == {3: Decimal("63.16"), 6: Decimal("39.30")}
    assert classes[0]["useful_life_years"] == 3


def test_land_is_not_depreciated_by_either_method():
    """Schedule II spreads a cost over a useful life; land has none. The old
    table gave it a 0.00 rate, which the WDV path honoured and the SL path did
    not — SL fell through to a made-up five-year life."""
    assert _DEFAULT_WDV_RATES["Land"] == 0
    for method in ("WDV", "SL"):
        asset = {
            "purchase_cost_paise": 50_00_000_00, "salvage_value_paise": 0,
            "asset_category": "Land", "depreciation_method": method,
            "useful_life_years": 5, "accumulated_depreciation_paise": 0,
        }
        assert _compute_annual_depreciation(asset) == 0


def test_a_category_schedule_ii_does_not_reach_refuses_rather_than_guessing():
    """Intangibles are amortised under AS 26 / Ind AS 38 (Schedule II Part A),
    which is the CA's judgement. The old table answered 25.00% — the
    Income-tax Act's answer to a different question."""
    assert _DEFAULT_WDV_RATES["Intangibles"] is None
    assert _DEFAULT_WDV_RATES["Other"] is None
    asset = {
        "purchase_cost_paise": 10_00_000_00, "salvage_value_paise": 0,
        "asset_category": "Intangibles", "depreciation_method": "WDV",
        "wdv_rate_percent": None, "accumulated_depreciation_paise": 0,
    }
    with pytest.raises(ValueError, match="prescribes no useful life"):
        _compute_annual_depreciation(asset)


def test_a_recorded_rate_is_never_overridden_by_the_default():
    """The fix is to the DEFAULT offered for a new asset. An asset that already
    carries a rate keeps charging on it — depreciation already posted must not
    move because the table under it was corrected."""
    asset = {
        "purchase_cost_paise": 100_000_00, "salvage_value_paise": 0,
        "asset_category": "Furniture & Fixtures", "depreciation_method": "WDV",
        "wdv_rate_percent": 10.00,          # the retired Income-tax rate, as stored
        "accumulated_depreciation_paise": 0,
    }
    assert _compute_annual_depreciation(asset) == 10_000_00


def test_the_categories_endpoint_serves_the_one_table():
    """The create form used to hold its own copy of the rates. It now reads
    them from here, so there is one table (CLAUDE.md: zero business logic in
    the frontend)."""
    body = fa.asset_categories(client_id=CLIENT, current_user=USER)
    assert body["success"] is True
    served = {row["category"]: row for row in body["data"]}
    assert set(served) == set(SCHEDULE_II_CATEGORIES)
    computers = served["Computer & IT Equipment"]
    assert computers["depreciable"] is True
    assert [c["useful_life_years"] for c in computers["classes"]] == [3, 6]
    assert computers["classes"][0]["wdv_rate_percent"] == 63.16
    assert served["Land"]["depreciable"] is False
    assert served["Intangibles"]["classes"][0]["wdv_rate_percent"] is None


def test_every_category_has_a_gl_account_mapping():
    """A category here that phase2_journal_service's cat_map does not know
    books the asset to Plant & Machinery instead — silently, in the ledger.
    task #232 fixed that mismatch once; this stops it coming back through a
    category added on this side alone."""
    source = (Path(fa.__file__).resolve().parents[1] / "services" / "phase2_journal_service.py").read_text(encoding="utf-8")
    for category in SCHEDULE_II_CATEGORIES:
        if category == "Other":
            continue  # deliberately the fallback
        assert f'"{category}"' in source, f"{category} has no GL account mapping"


# ── create_asset: what a new asset is given ─────────────────────────────────

def _create(db, **overrides):
    body = dict(client_id=CLIENT, asset_name="Thing", purchase_date="2026-04-01",
                purchase_cost_paise=100_000_00)
    body.update(overrides)
    return fa.create_asset(FixedAssetIn(**body), USER)


def test_a_new_asset_gets_the_schedule_ii_rate_and_the_life_behind_it(monkeypatch):
    db = TypeCheckedFakeDB()
    monkeypatch.setattr(fa, "_db", lambda: db)
    monkeypatch.setattr(fa.period_validation_service, "validate_posting_date", lambda *a: None)

    _create(db, asset_category="Vehicles")
    row = db.store["fixed_assets"][0]
    assert row["wdv_rate_percent"] == 31.23      # 8 years, not the 25.89 shipped
    assert row["useful_life_years"] == 8         # the life is stored, not just the rate


def test_the_ca_may_depart_from_the_schedule_ii_default(monkeypatch):
    """Schedule II permits a different useful life — it has to be DISCLOSED in
    the accounts, not forbidden. An explicit rate is taken as given."""
    db = TypeCheckedFakeDB()
    monkeypatch.setattr(fa, "_db", lambda: db)
    monkeypatch.setattr(fa.period_validation_service, "validate_posting_date", lambda *a: None)

    _create(db, asset_category="Computer & IT Equipment", wdv_rate_percent=39.30,
            useful_life_years=6)
    row = db.store["fixed_assets"][0]
    assert row["wdv_rate_percent"] == 39.30      # the servers-and-networks class
    assert row["useful_life_years"] == 6


def test_creating_an_asset_schedule_ii_prescribes_nothing_for_is_refused(monkeypatch):
    db = TypeCheckedFakeDB()
    monkeypatch.setattr(fa, "_db", lambda: db)
    monkeypatch.setattr(fa.period_validation_service, "validate_posting_date", lambda *a: None)

    with pytest.raises(HTTPException) as exc:
        _create(db, asset_category="Intangibles")
    assert exc.value.status_code == 422
    assert "prescribes no useful life" in exc.value.detail
    assert db.store.get("fixed_assets", []) == []   # nothing written, no journal


def test_an_intangible_with_a_recorded_rate_is_accepted(monkeypatch):
    db = TypeCheckedFakeDB()
    monkeypatch.setattr(fa, "_db", lambda: db)
    monkeypatch.setattr(fa.period_validation_service, "validate_posting_date", lambda *a: None)

    _create(db, asset_category="Intangibles", wdv_rate_percent=20.0)
    assert db.store["fixed_assets"][0]["wdv_rate_percent"] == 20.0


# ── 2. The posted-through column is a DATE ──────────────────────────────────

def test_posting_writes_a_real_date_and_the_register_actually_moves(monkeypatch):
    """The whole defect in one test: with 'YYYY-MM' the write is rejected by
    Postgres, so accumulated depreciation never moves. _TypeCheckedFakeDB
    rejects it the same way, and the assertions below are what the register
    must look like afterwards."""
    db = TypeCheckedFakeDB()
    _seed_asset(db, wdv_rate_percent=24.0)
    monkeypatch.setattr(fa, "_db", lambda: db)
    monkeypatch.setattr(fa.period_validation_service, "validate_posting_date", lambda *a: None)

    result = fa.post_depreciation("asset-1", DepreciationIn(period="2026-05"), USER)
    monthly = result["data"]["depreciation_paise"]
    assert monthly > 0

    row = db.store["fixed_assets"][0]
    assert row["depreciation_posted_through"] == "2026-05-31"   # month end, the entry's own date
    assert row["accumulated_depreciation_paise"] == monthly     # ₹0 for ever, before the fix
    assert row["current_wdv_paise"] == 100_000_00 - monthly


def test_month_end_is_the_date_the_journal_carries(monkeypatch):
    """Not an arbitrary date in the month: the depreciation entry is dated to
    the last day of the period (_period_end_date), and "posted through
    31-05-2026" is exactly what the column claims."""
    db = TypeCheckedFakeDB()
    _seed_asset(db)
    monkeypatch.setattr(fa, "_db", lambda: db)
    monkeypatch.setattr(fa.period_validation_service, "validate_posting_date", lambda *a: None)
    seen = {}
    monkeypatch.setattr(fa._journal_svc, "journal_for_depreciation",
                        lambda asset, amount, period, firm, client: seen.setdefault("period", period) or "je-1")

    fa.post_depreciation("asset-1", DepreciationIn(period="2026-06"), USER)
    row = db.store["fixed_assets"][0]
    assert row["depreciation_posted_through"] == fa._period_end_date(seen["period"])


def test_the_month_is_read_back_out_of_the_stored_date():
    assert _month_label("2026-05-31") == "2026-05"
    assert _month_label(date(2026, 5, 31)) == "2026-05"
    assert _month_label(None) is None
    assert _month_label("") is None


def test_reposting_the_same_month_is_still_refused_after_the_date_fix(monkeypatch):
    """Idempotency has to survive the column now holding '2026-05-31' rather
    than '2026-05' — a naive string compare would let June through and then
    refuse July."""
    db = TypeCheckedFakeDB()
    _seed_asset(db)
    monkeypatch.setattr(fa, "_db", lambda: db)
    monkeypatch.setattr(fa.period_validation_service, "validate_posting_date", lambda *a: None)

    fa.post_depreciation("asset-1", DepreciationIn(period="2026-05"), USER)
    with pytest.raises(HTTPException) as exc:
        fa.post_depreciation("asset-1", DepreciationIn(period="2026-05"), USER)
    assert exc.value.status_code == 409
    assert "2026-05" in exc.value.detail

    # and an earlier month is still closed, and the next month still opens
    with pytest.raises(HTTPException) as earlier:
        fa.post_depreciation("asset-1", DepreciationIn(period="2026-04"), USER)
    assert earlier.value.status_code == 409
    assert fa.post_depreciation("asset-1", DepreciationIn(period="2026-06"), USER)["success"] is True


def test_a_full_year_of_postings_accumulates_month_by_month(monkeypatch):
    db = TypeCheckedFakeDB()
    _seed_asset(db, purchase_date="2026-04-01", wdv_rate_percent=24.0)
    monkeypatch.setattr(fa, "_db", lambda: db)
    monkeypatch.setattr(fa.period_validation_service, "validate_posting_date", lambda *a: None)

    total = 0
    for period in [f"2026-{m:02d}" for m in range(4, 13)] + [f"2027-{m:02d}" for m in (1, 2, 3)]:
        total += fa.post_depreciation("asset-1", DepreciationIn(period=period), USER)["data"]["depreciation_paise"]

    row = db.store["fixed_assets"][0]
    assert row["accumulated_depreciation_paise"] == total
    assert row["depreciation_posted_through"] == "2027-03-31"
    assert total > 0


# ── 3. A skipped month is refused, and named ────────────────────────────────

def test_months_missing_before_is_exclusive_at_both_ends():
    assert _months_missing_before("2026-08", "2026-09") == []
    assert _months_missing_before("2026-08", "2026-10") == ["2026-09"]
    assert _months_missing_before("2026-11", "2027-02") == ["2026-12", "2027-01"]
    assert _months_missing_before("2026-08", "2026-08") == []


def test_skipping_september_is_refused_and_september_is_named(monkeypatch):
    db = TypeCheckedFakeDB()
    _seed_asset(db, purchase_date="2026-04-01")
    monkeypatch.setattr(fa, "_db", lambda: db)
    monkeypatch.setattr(fa.period_validation_service, "validate_posting_date", lambda *a: None)

    for period in ("2026-04", "2026-05", "2026-06", "2026-07", "2026-08"):
        fa.post_depreciation("asset-1", DepreciationIn(period=period), USER)

    with pytest.raises(HTTPException) as exc:
        fa.post_depreciation("asset-1", DepreciationIn(period="2026-10"), USER)
    assert exc.value.status_code == 422
    assert "2026-09" in exc.value.detail

    # The refusal changed nothing: September is still postable, and October
    # after it. Before the fix October went through, and September then 409'd
    # ("already posted through 2026-10") for ever.
    row = db.store["fixed_assets"][0]
    assert row["depreciation_posted_through"] == "2026-08-31"
    assert fa.post_depreciation("asset-1", DepreciationIn(period="2026-09"), USER)["success"] is True
    assert fa.post_depreciation("asset-1", DepreciationIn(period="2026-10"), USER)["success"] is True


def test_a_multi_month_gap_names_every_missing_month(monkeypatch):
    db = TypeCheckedFakeDB()
    _seed_asset(db, purchase_date="2026-04-01")
    monkeypatch.setattr(fa, "_db", lambda: db)
    monkeypatch.setattr(fa.period_validation_service, "validate_posting_date", lambda *a: None)

    fa.post_depreciation("asset-1", DepreciationIn(period="2026-04"), USER)
    with pytest.raises(HTTPException) as exc:
        fa.post_depreciation("asset-1", DepreciationIn(period="2026-08"), USER)
    for month in ("2026-05", "2026-06", "2026-07"):
        assert month in exc.value.detail


def test_the_first_ever_posting_may_start_at_any_month(monkeypatch):
    """The gap is measured from what this register has POSTED, never from the
    purchase date. An asset brought over from Tally mid-life already carries
    its accumulated depreciation, and its first posting here is whatever month
    the CA takes over in — refusing that would refuse every migrated asset."""
    db = TypeCheckedFakeDB()
    _seed_asset(db, purchase_date="2024-04-01", accumulated_depreciation_paise=40_000_00)
    monkeypatch.setattr(fa, "_db", lambda: db)
    monkeypatch.setattr(fa.period_validation_service, "validate_posting_date", lambda *a: None)

    assert fa.post_depreciation("asset-1", DepreciationIn(period="2026-09"), USER)["success"] is True


# ── The schedule endpoint reports a gap instead of failing ──────────────────

def test_an_asset_with_no_statutory_basis_is_a_named_gap_not_a_broken_report(monkeypatch):
    db = TypeCheckedFakeDB()
    _seed_asset(db)                                            # ordinary, has a rate
    _seed_asset(db, id="asset-2", asset_code="FA-002", asset_name="Goodwill",
                asset_category="Intangibles", wdv_rate_percent=None)
    monkeypatch.setattr(fa, "_db", lambda: db)

    rows = fa.depreciation_schedule(client_id=CLIENT, current_user=USER)["data"]
    by_id = {r["asset_id"]: r for r in rows}
    assert by_id["asset-1"]["statutory_gap"] is None
    assert by_id["asset-1"]["annual_depreciation_paise"] > 0
    assert "prescribes no useful life" in by_id["asset-2"]["statutory_gap"]
    assert by_id["asset-2"]["annual_depreciation_paise"] == 0


def test_posting_an_asset_with_no_statutory_basis_is_refused(monkeypatch):
    db = TypeCheckedFakeDB()
    _seed_asset(db, asset_category="Intangibles", wdv_rate_percent=None)
    monkeypatch.setattr(fa, "_db", lambda: db)
    monkeypatch.setattr(fa.period_validation_service, "validate_posting_date", lambda *a: None)

    with pytest.raises(HTTPException) as exc:
        fa.post_depreciation("asset-1", DepreciationIn(period="2026-05"), USER)
    assert exc.value.status_code == 422
    assert "prescribes no useful life" in exc.value.detail
    assert db.store["fixed_assets"][0]["accumulated_depreciation_paise"] == 0


def test_the_schedule_carries_the_basis_the_screen_shows(monkeypatch):
    """The depreciation screen used to recompute the annual charge in the
    browser off its own copy of the rate. It now shows what the backend will
    actually post, so the basis has to travel with it."""
    db = TypeCheckedFakeDB()
    _seed_asset(db, wdv_rate_percent=18.10, useful_life_years=15,
                depreciation_posted_through="2026-05-31")
    monkeypatch.setattr(fa, "_db", lambda: db)

    row = fa.depreciation_schedule(client_id=CLIENT, current_user=USER)["data"][0]
    assert row["wdv_rate_percent"] == 18.10
    assert row["useful_life_years"] == 15
    assert row["depreciation_posted_through"] == "2026-05"
    assert row["monthly_depreciation_paise"] == row["annual_depreciation_paise"] // 12


def test_the_type_checked_fake_catches_the_defect_it_exists_for():
    """The guard's own negative control: the exact write the router used to
    make must fail, or the tests above prove nothing."""
    with pytest.raises(AssertionError, match="22007"):
        assert_write_fits_production_types("fixed_assets", {"depreciation_posted_through": "2026-04"})
    with pytest.raises(AssertionError, match="PGRST204"):
        assert_write_fits_production_types("fixed_assets", {"no_such_column": 1})
    # and it passes what Postgres accepts
    assert_write_fits_production_types(
        "fixed_assets", {"depreciation_posted_through": "2026-04-30",
                         "accumulated_depreciation_paise": 1000,
                         "wdv_rate_percent": 18.10, "is_disposed": False})
