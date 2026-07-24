"""
Task #232 — fixed-asset depreciation-engine gaps.

High: WDV depreciation was recomputed at EVERY monthly posting from
accumulated_depreciation_paise as it stood THAT month — already reduced by
every earlier month's charge in the same year — instead of a fixed annual
figure computed once from the year's OPENING WDV. This systematically
under-depreciated (each month's charge used a smaller and smaller base).
_annual_depreciation_for_period fixes this by caching the opening-of-FY
accumulated depreciation (fixed_assets.depreciation_fy /
depreciation_fy_start_accum_paise, migration 239) and reusing it for every
month within the same financial year, resetting only when a new FY starts.

High: fixed_assets.py never called period_validation_service at all —
create/depreciate/dispose could all post inside a locked financial year.

Medium: no pro-rata depreciation for the asset's purchase month (Schedule II
Note 3 / IT Act §32), and no validation that a depreciation period isn't
before the asset's purchase date.

Low: depreciation math now uses Decimal instead of binary float
(CLAUDE.md: integer paise arithmetic) — verified not to have changed any of
test_depreciation_engine.py's existing expected values.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import HTTPException

import routers.fixed_assets as fa_router
from routers.fixed_assets import (
    _annual_depreciation_for_period,
    _prorate_purchase_month,
    _period_end_date,
)
from models.accounting import DepreciationIn, FixedAssetIn, DisposalIn

FIRM, CLIENT = "firm-1", "client-1"


# ── Fake Supabase (same shape/semantics as test_fixed_asset_disposal.py's) ──

class _Resp:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _Q:
    def __init__(self, store, table):
        self.s, self.t = store, table
        self.op = "select"
        self.payload = None
        self.f = []
        self.single_ = False
        self._count_mode = None

    def insert(self, p):
        self.op, self.payload = "insert", p
        return self

    def update(self, p):
        self.op, self.payload = "update", p
        return self

    def select(self, *a, count=None, **k):
        self.op = "select"
        self._count_mode = count
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
        rows = self.s.setdefault(self.t, [])
        return [r for r in rows if all(r.get(k) == v for k, v in self.f)]

    def execute(self):
        if self.op == "insert":
            rows = self.s.setdefault(self.t, [])
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            out = []
            for p in items:
                rec = dict(p)
                rec.setdefault("id", f"{self.t}-{len(rows) + 1}")
                rows.append(rec)
                out.append(rec)
            return _Resp(out)
        m = self._match()
        if self.op == "update":
            for r in m:
                r.update(self.payload)
            return _Resp(m)
        if self._count_mode:
            return _Resp(m, count=len(m))
        if self.single_:
            return _Resp(m[0] if m else None)
        return _Resp(m)


class FakeDB:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return _Q(self.store, name)


def _seed_asset(db, **overrides):
    asset = {
        "id": "asset-1", "firm_id": FIRM, "client_id": CLIENT,
        "asset_name": "Test Machine", "asset_code": "FA-001",
        "asset_category": "Plant & Machinery", "is_disposed": False,
        "purchase_date": "2026-04-10",
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
def _patch_side_effects(monkeypatch):
    monkeypatch.setattr(fa_router.timeline_service, "log", lambda *a, **k: None)
    yield


def _dep(**overrides):
    return DepreciationIn(**overrides)


# ── _annual_depreciation_for_period (pure logic) ─────────────────────────────

def test_wdv_reuses_fy_start_base_within_the_same_financial_year():
    """Same FY, base already cached — must NOT recompute from live accum."""
    asset = {
        "purchase_cost_paise": 100_000_00, "salvage_value_paise": 0,
        "depreciation_method": "WDV", "wdv_rate_percent": 24.0,
        "asset_category": "Other",
        "accumulated_depreciation_paise": 6_000_00,  # already reduced this FY
        "depreciation_fy": "2026-27", "depreciation_fy_start_accum_paise": 0,
    }
    annual, fy, fy_start = _annual_depreciation_for_period(asset, "2026-07")
    assert fy == "2026-27"
    assert fy_start == 0  # reused the CACHED opening balance, not live accum
    assert annual == 24_000_00  # 24% of the FY-opening WDV (100,000), not of (100,000-6,000)


def test_wdv_recomputes_fresh_base_on_first_posting_of_a_new_fy():
    asset = {
        "purchase_cost_paise": 100_000_00, "salvage_value_paise": 0,
        "depreciation_method": "WDV", "wdv_rate_percent": 24.0,
        "asset_category": "Other",
        "accumulated_depreciation_paise": 24_000_00,  # all of FY1 posted
        "depreciation_fy": "2026-27", "depreciation_fy_start_accum_paise": 0,
    }
    # Posting April of the NEXT FY — must snapshot the live (post-FY1) accum.
    annual, fy, fy_start = _annual_depreciation_for_period(asset, "2027-04")
    assert fy == "2027-28"
    assert fy_start == 24_000_00
    assert annual == 18_240_00  # 24% of WDV (100,000-24,000=76,000)


def test_sl_method_unaffected_by_fy_caching():
    asset = {
        "purchase_cost_paise": 100_000_00, "salvage_value_paise": 0,
        "depreciation_method": "SL", "useful_life_years": 5,
        "accumulated_depreciation_paise": 30_000_00,
        "depreciation_fy": None, "depreciation_fy_start_accum_paise": None,
    }
    annual, fy, _ = _annual_depreciation_for_period(asset, "2026-07")
    assert annual == 20_000_00  # (100,000-0)/5, independent of FY caching
    assert fy == "2026-27"


# ── post_depreciation: the under-depreciation regression itself ────────────

def test_wdv_monthly_charge_stays_fixed_across_months_in_the_same_fy():
    """The core task #232 bug: month 2's charge must equal month 1's — both
    computed from the SAME fixed FY-opening base — not a smaller figure
    recomputed from month 1's already-reduced accumulated_depreciation_paise."""
    db = FakeDB()
    _seed_asset(db, purchase_date="2026-04-01", wdv_rate_percent=24.0)
    fa_router._db = lambda: db
    fa_router._journal_svc.journal_for_depreciation = lambda *a, **k: "je-1"

    r1 = fa_router.post_depreciation("asset-1", _dep(period="2026-05"), {"firm_id": FIRM, "id": "u1"})
    r2 = fa_router.post_depreciation("asset-1", _dep(period="2026-06"), {"firm_id": FIRM, "id": "u1"})

    m1 = r1["data"]["depreciation_paise"]
    m2 = r2["data"]["depreciation_paise"]
    assert m1 == m2, f"month 2 ({m2}) should equal month 1 ({m1}) within the same FY"

    # The OLD (buggy) behaviour would have recomputed annual from the
    # ALREADY-REDUCED accum after month 1 — strictly less than the fixed
    # figure. Prove the fix produces the LARGER, correct amount.
    accum_after_m1 = 100_000_00 - m1
    buggy_annual = accum_after_m1 * 24 // 100
    buggy_monthly = buggy_annual // 12
    assert m2 > buggy_monthly


def test_wdv_resets_base_when_crossing_into_a_new_financial_year():
    db = FakeDB()
    _seed_asset(db, purchase_date="2026-04-01", wdv_rate_percent=25.0)
    fa_router._db = lambda: db
    fa_router._journal_svc.journal_for_depreciation = lambda *a, **k: "je-1"

    # Post every month of FY 2026-27 (Apr..Mar).
    months = [f"2026-{m:02d}" for m in range(4, 13)] + [f"2027-{m:02d}" for m in (1, 2, 3)]
    total_fy1 = 0
    for period in months:
        r = fa_router.post_depreciation("asset-1", _dep(period=period), {"firm_id": FIRM, "id": "u1"})
        total_fy1 += r["data"]["depreciation_paise"]

    asset = db.store["fixed_assets"][0]
    assert asset["depreciation_fy"] == "2026-27"
    fy1_wdv = 100_000_00 - total_fy1

    # First posting of FY 2027-28 must recompute from the FY1-end WDV.
    r_new_fy = fa_router.post_depreciation("asset-1", _dep(period="2027-04"), {"firm_id": FIRM, "id": "u1"})
    asset = db.store["fixed_assets"][0]
    assert asset["depreciation_fy"] == "2027-28"
    assert asset["depreciation_fy_start_accum_paise"] == total_fy1
    expected_annual_fy2 = fy1_wdv * 25 // 100
    assert r_new_fy["data"]["depreciation_paise"] == expected_annual_fy2 // 12


# ── Pro-rata for the purchase month ─────────────────────────────────────────

def test_prorate_purchase_month_pure_function():
    # April has 30 days; purchased on the 10th -> held 21 of 30 days.
    assert _prorate_purchase_month(3000, "2026-04-10") == 3000 * 21 // 30


def test_purchase_month_depreciation_is_prorated_by_days_held():
    db = FakeDB()
    _seed_asset(db, purchase_date="2026-04-10", wdv_rate_percent=24.0)
    fa_router._db = lambda: db
    fa_router._journal_svc.journal_for_depreciation = lambda *a, **k: "je-1"

    result = fa_router.post_depreciation("asset-1", _dep(period="2026-04"), {"firm_id": FIRM, "id": "u1"})

    full_monthly = (100_000_00 * 24 // 100) // 12
    expected = full_monthly * 21 // 30  # 30-day April, held from the 10th (21 days)
    assert result["data"]["depreciation_paise"] == expected
    assert result["data"]["depreciation_paise"] < full_monthly


def test_month_after_purchase_month_gets_the_full_charge_not_prorated():
    db = FakeDB()
    _seed_asset(db, purchase_date="2026-04-10", wdv_rate_percent=24.0)
    fa_router._db = lambda: db
    fa_router._journal_svc.journal_for_depreciation = lambda *a, **k: "je-1"

    result = fa_router.post_depreciation("asset-1", _dep(period="2026-05"), {"firm_id": FIRM, "id": "u1"})

    full_monthly = (100_000_00 * 24 // 100) // 12
    assert result["data"]["depreciation_paise"] == full_monthly


# ── Purchase-date validation ─────────────────────────────────────────────────

def test_rejects_period_before_the_purchase_date():
    db = FakeDB()
    _seed_asset(db, purchase_date="2026-07-15")
    fa_router._db = lambda: db

    with pytest.raises(HTTPException) as exc:
        fa_router.post_depreciation("asset-1", _dep(period="2026-06"), {"firm_id": FIRM, "id": "u1"})
    assert exc.value.status_code == 422


def test_accepts_the_exact_purchase_month():
    db = FakeDB()
    _seed_asset(db, purchase_date="2026-07-15")
    fa_router._db = lambda: db
    fa_router._journal_svc.journal_for_depreciation = lambda *a, **k: "je-1"

    result = fa_router.post_depreciation("asset-1", _dep(period="2026-07"), {"firm_id": FIRM, "id": "u1"})
    assert result["success"] is True


def test_rejects_malformed_period_format():
    db = FakeDB()
    _seed_asset(db)
    fa_router._db = lambda: db
    with pytest.raises(HTTPException) as exc:
        fa_router.post_depreciation("asset-1", _dep(period="2026"), {"firm_id": FIRM, "id": "u1"})
    assert exc.value.status_code == 422


# ── Period-lock (FY lock) enforcement — all 3 write paths ───────────────────

def _raise_locked(firm_id, date_str):
    raise HTTPException(status_code=422, detail="Cannot post to a locked financial year")


def test_create_asset_blocked_in_locked_fy(monkeypatch):
    db = FakeDB()
    fa_router._db = lambda: db
    monkeypatch.setattr(fa_router.period_validation_service, "validate_posting_date", _raise_locked)

    body = FixedAssetIn(client_id=CLIENT, asset_name="Laptop", purchase_date="2026-04-01",
                        purchase_cost_paise=50_000_00)
    with pytest.raises(HTTPException) as exc:
        fa_router.create_asset(body, {"firm_id": FIRM, "id": "u1"})
    assert exc.value.status_code == 422
    assert db.store.get("fixed_assets", []) == []  # never inserted


def test_post_depreciation_blocked_in_locked_fy(monkeypatch):
    db = FakeDB()
    _seed_asset(db, purchase_date="2026-04-01")
    fa_router._db = lambda: db
    monkeypatch.setattr(fa_router.period_validation_service, "validate_posting_date", _raise_locked)

    with pytest.raises(HTTPException) as exc:
        fa_router.post_depreciation("asset-1", _dep(period="2026-07"), {"firm_id": FIRM, "id": "u1"})
    assert exc.value.status_code == 422
    assert db.store["fixed_assets"][0]["depreciation_posted_through"] is None  # unchanged


def test_dispose_asset_blocked_in_locked_fy(monkeypatch):
    db = FakeDB()
    _seed_asset(db, purchase_date="2026-04-01")
    fa_router._db = lambda: db
    monkeypatch.setattr(fa_router.period_validation_service, "validate_posting_date", _raise_locked)

    with pytest.raises(HTTPException) as exc:
        fa_router.dispose_asset("asset-1", DisposalIn(sale_proceeds_paise=10_000_00), {"firm_id": FIRM, "id": "u1"})
    assert exc.value.status_code == 422
    assert db.store["fixed_assets"][0]["is_disposed"] is False  # never claimed


# ── _period_end_date ──────────────────────────────────────────────────────────

def test_period_end_date_uses_the_last_calendar_day():
    assert _period_end_date("2026-02") == "2026-02-28"  # not a leap year
    assert _period_end_date("2028-02") == "2028-02-29"  # leap year
    assert _period_end_date("2026-04") == "2026-04-30"


# ── Depreciation journal is dated to the PERIOD, not "today" ────────────────

def test_depreciation_journal_dated_to_period_end_not_today(monkeypatch):
    import services.phase2_journal_service as pjs
    from services.phase2_journal_service import Phase2JournalService

    monkeypatch.setattr(pjs, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: FakeDB())
    svc = Phase2JournalService()
    accounts = {"%Depreciation Expense%": "acc-dep-exp", "%Accumulated Depreciation%": "acc-adep"}
    monkeypatch.setattr(svc, "_find_account",
                        lambda db, firm_id, client_id, pattern, system_key=None: accounts[pattern])
    captured = {}
    monkeypatch.setattr(svc, "_create_journal", lambda db, **k: captured.update(k) or "je-1")

    asset = {"id": "asset-1", "asset_code": "FA-001", "asset_name": "Widget",
              "depreciation_method": "WDV"}
    svc.journal_for_depreciation(asset, 1000_00, "2026-06", FIRM, CLIENT)

    assert captured["entry_date"] == "2026-06-30"  # last day of June, not today's date
