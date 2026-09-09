"""
Fixed Asset disposal — atomicity tests (C1).

dispose_asset() previously called `data.get("notes", ...)` on a Pydantic v2
model (no `.get()` method) AFTER the disposal journal had already posted,
crashing on every real invocation and leaving an orphaned journal; because
`is_disposed` was never set, every retry posted another orphaned journal.

The fix claims the disposal atomically (a conditional update guarded on
`is_disposed = false`) BEFORE any journal is posted, and rolls the claim back
if the journal fails to post. The router guards against BOTH a None
journal_id and a raised exception (as of task #103, journal_for_asset_disposal
re-raises unexpected posting failures instead of swallowing them into a None
return — a real None is now only possible in _USE_MOCK mode). The tests below
monkeypatch journal_for_asset_disposal directly to simulate each failure mode
independently of which real code path produces it.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import HTTPException

import routers.fixed_assets as fa_router
from models.accounting import DisposalIn

FIRM, CLIENT = "firm-1", "client-1"


# ── Fake Supabase (same shape/semantics as test_bank_posting.py's FakeDB) ────

class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, store, table):
        self.s, self.t = store, table
        self.op = "select"
        self.payload = None
        self.f = []
        self.single_ = False

    def update(self, p):
        self.op, self.payload = "update", p
        return self

    def select(self, *a, **k):
        self.op = "select"
        return self

    def eq(self, k, v):
        self.f.append((k, v))
        return self

    # migration 351 gave fixed_assets a deleted_at, so every read now excludes a
    # soft-deleted asset. Modelled faithfully rather than as a no-op: a fake
    # that ignored the filter would pass while a deleted asset still counted in
    # the register.
    def is_(self, col, _null="null"):
        self.f.append((col, None))
        return self

    def limit(self, _n):
        return self

    def single(self):
        self.single_ = True
        return self

    def _match(self):
        rows = self.s.setdefault(self.t, [])
        out = []
        for r in rows:
            if all(r.get(k) == v for k, v in self.f):
                out.append(r)
        return out

    def execute(self):
        m = self._match()
        if self.op == "update":
            for r in m:
                r.update(self.payload)
            return _Resp(m)
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
        "asset_name": "Test Laptop", "asset_code": "FA-001",
        "asset_category": "Computer", "is_disposed": False,
        "purchase_cost_paise": 100_000_00, "accumulated_depreciation_paise": 40_000_00,
        "disposal_date": None, "disposal_value_paise": None, "notes": "original note",
    }
    asset.update(overrides)
    db.store.setdefault("fixed_assets", []).append(asset)
    return asset


@pytest.fixture(autouse=True)
def _patch_timeline(monkeypatch):
    monkeypatch.setattr(fa_router.timeline_service, "log", lambda *a, **k: None)
    yield


def _disposal(**overrides):
    payload = {"disposal_type": "Sale", "sale_proceeds_paise": 50_000_00, "notes": "disposed"}
    payload.update(overrides)
    return DisposalIn(**payload)


def test_successful_disposal_posts_journal_and_marks_disposed():
    db = FakeDB()
    _seed_asset(db)
    fa_router._db = lambda: db
    fa_router._journal_svc.journal_for_asset_disposal = lambda *a, **k: "je-1"

    result = fa_router.dispose_asset("asset-1", _disposal(), {"firm_id": FIRM, "id": "u1"})

    assert result["data"]["journal_entry_id"] == "je-1"
    asset = db.store["fixed_assets"][0]
    assert asset["is_disposed"] is True
    assert asset["notes"] == "disposed"


def test_failed_disposal_rolls_back_and_never_orphans_a_journal():
    """A None journal_id (simulated here directly; in the real service this
    now only occurs in _USE_MOCK mode — see module docstring) must roll the
    claim back — the asset must NOT end up disposed."""
    db = FakeDB()
    _seed_asset(db)
    fa_router._db = lambda: db
    fa_router._journal_svc.journal_for_asset_disposal = lambda *a, **k: None

    with pytest.raises(HTTPException) as exc:
        fa_router.dispose_asset("asset-1", _disposal(), {"firm_id": FIRM, "id": "u1"})
    assert exc.value.status_code == 502

    asset = db.store["fixed_assets"][0]
    assert asset["is_disposed"] is False
    assert asset["disposal_date"] is None
    assert asset["disposal_value_paise"] is None
    assert asset["notes"] == "original note"  # rolled back, not the attempted "disposed"


def test_retry_after_failure_succeeds_cleanly_with_exactly_one_journal():
    db = FakeDB()
    _seed_asset(db)
    fa_router._db = lambda: db

    calls = []
    def flaky_journal(*a, **k):
        calls.append(1)
        return None if len(calls) == 1 else f"je-{len(calls)}"
    fa_router._journal_svc.journal_for_asset_disposal = flaky_journal

    with pytest.raises(HTTPException):
        fa_router.dispose_asset("asset-1", _disposal(), {"firm_id": FIRM, "id": "u1"})
    assert db.store["fixed_assets"][0]["is_disposed"] is False

    result = fa_router.dispose_asset("asset-1", _disposal(), {"firm_id": FIRM, "id": "u1"})
    assert result["data"]["journal_entry_id"] == "je-2"
    assert len(calls) == 2  # exactly one failed attempt + one successful attempt — no duplicate posting
    assert db.store["fixed_assets"][0]["is_disposed"] is True


def test_already_disposed_asset_is_rejected_before_any_journal_call():
    db = FakeDB()
    _seed_asset(db, is_disposed=True)
    fa_router._db = lambda: db
    called = []
    fa_router._journal_svc.journal_for_asset_disposal = lambda *a, **k: called.append(1) or "je-x"

    with pytest.raises(HTTPException) as exc:
        fa_router.dispose_asset("asset-1", _disposal(), {"firm_id": FIRM, "id": "u1"})
    assert exc.value.status_code == 409
    assert called == []  # the ledger must never be touched for an already-disposed asset


def test_repeated_disposal_attempts_never_create_more_than_one_journal():
    """Simulates two back-to-back requests for the same asset (e.g. a
    double-click or a client retry) — only the first may succeed."""
    db = FakeDB()
    _seed_asset(db)
    fa_router._db = lambda: db
    posted = []
    def journal(*a, **k):
        posted.append(1)
        return f"je-{len(posted)}"
    fa_router._journal_svc.journal_for_asset_disposal = journal

    first = fa_router.dispose_asset("asset-1", _disposal(), {"firm_id": FIRM, "id": "u1"})
    assert first["data"]["journal_entry_id"] == "je-1"

    with pytest.raises(HTTPException) as exc:
        fa_router.dispose_asset("asset-1", _disposal(), {"firm_id": FIRM, "id": "u1"})
    assert exc.value.status_code == 409
    assert len(posted) == 1  # the second attempt never reached the journal service


def test_asset_not_found_raises_404():
    db = FakeDB()
    fa_router._db = lambda: db
    with pytest.raises(HTTPException) as exc:
        fa_router.dispose_asset("missing-asset", _disposal(), {"firm_id": FIRM, "id": "u1"})
    assert exc.value.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# FA-08 — the gain or loss is computed from what has been POSTED
# ─────────────────────────────────────────────────────────────────────────────
#
# dispose_asset computes `wdv = purchase_cost_paise - accumulated_depreciation_
# paise`, and accumulated depreciation is whatever the CA has actually posted.
# An asset bought in April, depreciated to June and sold in November therefore
# books a WDV four months too high, a gain four months too small (or a loss too
# large), and the year's depreciation expense short by the same amount — with
# nothing on the screen saying so.
#
# FA-01 made this look MORE trustworthy while leaving it wrong: accumulated
# depreciation used to be frozen at 0 for every asset, so the stale figure is
# now a real number.
#
# It REFUSES rather than posting the gap, because post_depreciation already
# refuses a skipped month for a reason that applies here word for word: "each
# month is its own journal needing its own CA review ... quietly posting three
# entries behind one click is exactly the unprompted acting this codebase does
# not do." Four such journals inside a transaction the CA thinks is about a sale
# would be worse, not better.

def _held_asset(db, **overrides):
    """Bought 10 April 2026, depreciated through 30 June 2026."""
    fields = {"purchase_date": "2026-04-10",
              "depreciation_posted_through": "2026-06-30"}
    fields.update(overrides)
    return _seed_asset(db, **fields)


def test_disposing_with_months_unposted_is_refused_and_names_them():
    db = FakeDB()
    _held_asset(db)
    fa_router._db = lambda: db
    called = []
    fa_router._journal_svc.journal_for_asset_disposal = lambda *a, **k: called.append(1) or "je-x"

    with pytest.raises(HTTPException) as exc:
        fa_router.dispose_asset("asset-1", _disposal(disposal_date="2026-11-20"),
                                {"firm_id": FIRM, "id": "u1"})

    assert exc.value.status_code == 422
    for month in ("2026-07", "2026-08", "2026-09", "2026-10"):
        assert month in exc.value.detail, f"{month} must be named"
    assert "4 months too high" in exc.value.detail
    assert "Post 2026-07 first" in exc.value.detail, "in order, one click each"
    assert not called, "nothing may reach the ledger on the way to the refusal"
    assert db.store["fixed_assets"][0]["is_disposed"] is False


def test_the_disposal_month_itself_is_not_required():
    """Depreciation to a disposal DATE is a part month, and the engine posts
    whole months only. Requiring the disposal month would make every mid-month
    sale unpostable."""
    db = FakeDB()
    _held_asset(db, depreciation_posted_through="2026-10-31")
    fa_router._db = lambda: db
    fa_router._journal_svc.journal_for_asset_disposal = lambda *a, **k: "je-2"

    result = fa_router.dispose_asset("asset-1", _disposal(disposal_date="2026-11-20"),
                                     {"firm_id": FIRM, "id": "u1"})

    assert result["success"] is True
    assert result["data"]["part_month_depreciation_not_charged"] is True, (
        "1-20 November is not charged and the CA has to be told")


def test_a_disposal_on_a_charged_month_end_leaves_nothing_uncharged():
    db = FakeDB()
    _held_asset(db, depreciation_posted_through="2026-11-30")
    fa_router._db = lambda: db
    fa_router._journal_svc.journal_for_asset_disposal = lambda *a, **k: "je-3"

    result = fa_router.dispose_asset("asset-1", _disposal(disposal_date="2026-11-30"),
                                     {"firm_id": FIRM, "id": "u1"})

    assert result["success"] is True
    assert result["data"]["part_month_depreciation_not_charged"] is False


def test_an_asset_never_depreciated_at_all_is_refused_from_its_purchase_month():
    """The commonest shape of the defect, and the one FA-01 changed the look of:
    accumulated depreciation of 0 used to be every asset's state."""
    db = FakeDB()
    _seed_asset(db, purchase_date="2026-04-10",
                accumulated_depreciation_paise=0)
    fa_router._db = lambda: db
    fa_router._journal_svc.journal_for_asset_disposal = lambda *a, **k: "je-4"

    with pytest.raises(HTTPException) as exc:
        fa_router.dispose_asset("asset-1", _disposal(disposal_date="2026-07-05"),
                                {"firm_id": FIRM, "id": "u1"})

    assert "2026-04" in exc.value.detail, "the pro-rated purchase month counts too"
    assert "2026-06" in exc.value.detail
    assert "2026-07" not in exc.value.detail, "the disposal month is a part month"


def test_a_disposal_in_the_purchase_month_needs_nothing_posted():
    """Bought and sold inside one month: there is no WHOLE month to charge, so
    refusing would make the sale unpostable for no gain."""
    db = FakeDB()
    _seed_asset(db, purchase_date="2026-04-10", accumulated_depreciation_paise=0)
    fa_router._db = lambda: db
    fa_router._journal_svc.journal_for_asset_disposal = lambda *a, **k: "je-5"

    result = fa_router.dispose_asset("asset-1", _disposal(disposal_date="2026-04-25"),
                                     {"firm_id": FIRM, "id": "u1"})

    assert result["success"] is True


def test_the_months_outstanding_helper_on_its_own():
    """The arithmetic, without the router around it."""
    f = fa_router._depreciation_months_outstanding
    asset = {"purchase_date": "2026-04-10", "depreciation_posted_through": "2026-06-30"}
    assert f(asset, "2026-11-20") == ["2026-07", "2026-08", "2026-09", "2026-10"]
    assert f(asset, "2026-07-01") == []
    assert f(asset, "2026-06-30") == []
    # Across a year boundary.
    assert f({"purchase_date": "2025-11-01", "depreciation_posted_through": "2025-12-31"},
             "2026-03-15") == ["2026-01", "2026-02"]
    # Never depreciated: the purchase month is outstanding too.
    assert f({"purchase_date": "2026-04-10"}, "2026-07-05") == ["2026-04", "2026-05", "2026-06"]
    # An asset with no purchase date recorded cannot be reasoned about, and a
    # refusal on no evidence would block every legacy row.
    assert f({}, "2026-07-05") == []
