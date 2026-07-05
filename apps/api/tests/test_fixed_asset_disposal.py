"""
Fixed Asset disposal — atomicity tests (C1).

dispose_asset() previously called `data.get("notes", ...)` on a Pydantic v2
model (no `.get()` method) AFTER the disposal journal had already posted,
crashing on every real invocation and leaving an orphaned journal; because
`is_disposed` was never set, every retry posted another orphaned journal.

The fix claims the disposal atomically (a conditional update guarded on
`is_disposed = false`) BEFORE any journal is posted, and rolls the claim back
if the journal fails to post (`journal_for_asset_disposal` returns None on
failure — it never raises, by an existing, unrelated contract shared by every
journal_for_* method in Phase2JournalService).
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
    """journal_for_asset_disposal returning None (its real failure contract)
    must roll the claim back — the asset must NOT end up disposed."""
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
