"""
Explicit "opening balance as of" date — the fix for opening stock being
silently dated to whenever the CSV import happened to run (created_at/
"today") instead of a deliberately chosen date, matching QuickBooks Online /
Zoho Books convention and the platform's own opening_balance_service.py
pattern for AR/AP/bank opening balances. See routers/service_catalogue.py's
_default_opening_balance_date / _resolve_opening_balance_date.
"""
from datetime import date

from fastapi import HTTPException

import routers.service_catalogue as sc
from routers.service_catalogue import (
    _default_opening_balance_date,
    _fy_start_or_april_default,
    _has_seedable_opening_balance,
    _resolve_opening_balance_date,
)
from tests.e2e_harness import FakeDB

FIRM = "firm-obd-1"
CLIENT = "client-obd-1"


# ── _fy_start_or_april_default / _default_opening_balance_date ─────────────

def test_default_uses_client_fy_start_when_set():
    db = FakeDB()
    db.seed("clients", {"id": CLIENT, "financial_year_start": "2025-04-01"})
    assert _default_opening_balance_date(db, CLIENT) == "2025-04-01"


def test_default_falls_back_to_april_1_when_client_fy_start_unset():
    db = FakeDB()
    db.seed("clients", {"id": CLIENT, "financial_year_start": None})
    result = _default_opening_balance_date(db, CLIENT)
    assert result.endswith("-04-01")


def test_default_falls_back_to_april_1_when_client_not_found():
    db = FakeDB()
    result = _default_opening_balance_date(db, "no-such-client")
    assert result.endswith("-04-01")


def test_april_1_fallback_uses_ist_today_not_bare_utc(monkeypatch):
    """A confirmed IST-boundary bug: the fallback must use core.ist_clock's
    single source of truth for "today", not a bare datetime.now(utc) — else
    it silently disagrees with the CA's actual calendar day for the ~5.5
    hours/day IST has already crossed into a new day but UTC hasn't."""
    monkeypatch.setattr(sc, "ist_today", lambda: date(2026, 3, 15))
    assert _fy_start_or_april_default(None) == "2025-04-01"

    monkeypatch.setattr(sc, "ist_today", lambda: date(2026, 4, 1))
    assert _fy_start_or_april_default(None) == "2026-04-01"

    monkeypatch.setattr(sc, "ist_today", lambda: date(2026, 1, 1))
    assert _fy_start_or_april_default(None) == "2025-04-01"


def test_fy_start_or_april_default_prefers_given_value():
    assert _fy_start_or_april_default("2024-04-01") == "2024-04-01"


# ── _has_seedable_opening_balance ───────────────────────────────────────────

def test_has_seedable_opening_balance_matches_seed_opening_balance_gate():
    # Mirrors domain/inventory_service.py's seed_opening_balance: both
    # present AND quantity > 0 — cost may legitimately be 0 (free stock).
    assert _has_seedable_opening_balance(10, 5000) is True
    assert _has_seedable_opening_balance(10, 0) is True
    assert _has_seedable_opening_balance(0, 5000) is False   # zero qty never seeds
    assert _has_seedable_opening_balance(None, 5000) is False
    assert _has_seedable_opening_balance(10, None) is False
    assert _has_seedable_opening_balance(None, None) is False
    assert _has_seedable_opening_balance(-1, 5000) is False


# ── _resolve_opening_balance_date ────────────────────────────────────────────

def test_resolve_uses_explicit_date_when_given(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(sc.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    date_, err = _resolve_opening_balance_date(db, FIRM, CLIENT, "2026-01-15")
    assert date_ == "2026-01-15"
    assert err is None


def test_resolve_falls_back_to_default_when_not_given(monkeypatch):
    db = FakeDB()
    db.seed("clients", {"id": CLIENT, "financial_year_start": "2025-04-01"})
    monkeypatch.setattr(sc.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    date_, err = _resolve_opening_balance_date(db, FIRM, CLIENT, None)
    assert date_ == "2025-04-01"
    assert err is None


def test_resolve_uses_precomputed_default_date_without_a_db_lookup(monkeypatch):
    """Bulk import batches the FY-start lookup itself (one .in_() query for
    every distinct client) and hands the result in via `default_date` —
    _resolve_opening_balance_date must not fall back to its own per-client
    DB query when one is supplied."""
    db = FakeDB()

    def _boom(*a, **k):
        raise AssertionError("must not query clients when default_date is supplied")

    monkeypatch.setattr(db, "table", _boom)
    monkeypatch.setattr(sc.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    date_, err = _resolve_opening_balance_date(db, FIRM, CLIENT, None, default_date="2025-07-01")
    assert date_ == "2025-07-01"
    assert err is None


def test_resolve_rejects_malformed_date_without_ever_calling_locked_fy_check(monkeypatch):
    db = FakeDB()
    calls = []
    monkeypatch.setattr(
        sc.period_validation_service, "validate_posting_date",
        lambda *a, **k: calls.append(a),
    )
    date_, err = _resolve_opening_balance_date(db, FIRM, CLIENT, "15-01-2026")
    assert date_ is None
    assert "Invalid opening balance date" in err
    assert calls == []  # never even reached the locked-FY check


def test_resolve_returns_none_and_message_when_date_is_in_a_locked_fy(monkeypatch):
    db = FakeDB()

    def _blocked(firm_id, date_str):
        raise HTTPException(status_code=422, detail="Cannot post to a locked financial year")

    monkeypatch.setattr(sc.period_validation_service, "validate_posting_date", _blocked)
    date_, err = _resolve_opening_balance_date(db, FIRM, CLIENT, "2024-04-01")
    assert date_ is None
    assert "locked financial year" in err


def test_resolve_never_raises_on_an_unexpected_validation_error(monkeypatch):
    """Defense in depth: _resolve_opening_balance_date's contract is "never
    raises" — even an exception type neither caller anticipated (not just
    HTTPException) must come back as (None, message), never propagate."""
    db = FakeDB()

    def _explodes(firm_id, date_str):
        raise RuntimeError("RPC transport died")

    monkeypatch.setattr(sc.period_validation_service, "validate_posting_date", _explodes)
    date_, err = _resolve_opening_balance_date(db, FIRM, CLIENT, "2025-06-01")
    assert date_ is None
    assert err  # some human-readable message, not a raised exception


def test_resolve_reuses_locked_fy_cache_across_calls(monkeypatch):
    """Bulk import threads one locked_fy_cache dict through every row's
    resolution — the same FY must only hit the (mocked/expensive)
    validate_posting_date RPC once, mirroring the pattern already
    established for sales_invoices.py/purchase_bills.py."""
    db = FakeDB()
    calls = []
    monkeypatch.setattr(
        sc.period_validation_service, "validate_posting_date",
        lambda firm_id, date_str: calls.append(date_str),
    )
    cache: dict = {}
    d1, e1 = _resolve_opening_balance_date(db, FIRM, CLIENT, "2025-06-01", locked_fy_cache=cache)
    d2, e2 = _resolve_opening_balance_date(db, FIRM, CLIENT, "2025-09-15", locked_fy_cache=cache)
    assert (d1, e1) == ("2025-06-01", None)
    assert (d2, e2) == ("2025-09-15", None)
    assert len(calls) == 1  # both dates fall in FY 2025-26 — checked once


# ── seed_opening_balances_batch: explicit-date-vs-legacy-fallback contract ──

def test_batch_row_with_explicit_none_date_skips_seeding_not_falls_back():
    from domain.inventory_service import seed_opening_balances_batch

    db = FakeDB()
    item_id = "item-locked-1"
    db.seed("service_catalogue", {"id": item_id, "firm_id": FIRM, "client_id": CLIENT,
                                    "name": "Widget", "kind": "good"})
    rows = [{
        "id": item_id, "client_id": CLIENT, "kind": "good", "name": "Widget",
        "opening_qty_units": "10", "opening_cost_paise": 10_000_00,
        # Present but None: the router already tried to resolve a date and
        # it fell in a locked FY — must skip, not silently fall back to
        # created_at/today.
        "opening_balance_date": None,
        "created_at": "2026-07-11T00:00:00Z",
    }]

    seed_opening_balances_batch(db, firm_id=FIRM, created_by="user-1", rows=rows)

    assert db.rows("inventory_stock_ledger") == []


def test_batch_row_with_explicit_date_uses_it_not_created_at():
    from domain.inventory_service import seed_opening_balances_batch

    db = FakeDB()
    item_id = "item-dated-1"
    db.seed("service_catalogue", {"id": item_id, "firm_id": FIRM, "client_id": CLIENT,
                                    "name": "Widget", "kind": "good"})
    rows = [{
        "id": item_id, "client_id": CLIENT, "kind": "good", "name": "Widget",
        "opening_qty_units": "10", "opening_cost_paise": 10_000_00,
        "opening_balance_date": "2025-04-01",
        "created_at": "2026-07-11T00:00:00Z",  # deliberately different — must NOT be used
    }]

    seed_opening_balances_batch(db, firm_id=FIRM, created_by="user-1", rows=rows)

    ledger = db.rows("inventory_stock_ledger")
    assert len(ledger) == 1
    assert ledger[0]["movement_date"] == "2025-04-01"
