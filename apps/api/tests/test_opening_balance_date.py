"""
Explicit "opening balance as of" date — the fix for opening stock being
silently dated to whenever the CSV import happened to run (created_at/
"today") instead of a deliberately chosen date, matching QuickBooks Online /
Zoho Books convention and the platform's own opening_balance_service.py
pattern for AR/AP/bank opening balances. See routers/service_catalogue.py's
_default_opening_balance_date / _resolve_opening_balance_date.
"""
from fastapi import HTTPException
import pytest

import routers.service_catalogue as sc
from routers.service_catalogue import (
    _default_opening_balance_date,
    _resolve_opening_balance_date,
)
from tests.e2e_harness import FakeDB

FIRM = "firm-obd-1"
CLIENT = "client-obd-1"


# ── _default_opening_balance_date ────────────────────────────────────────────

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


# ── _resolve_opening_balance_date ────────────────────────────────────────────

def test_resolve_uses_explicit_date_when_given(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(sc.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    assert _resolve_opening_balance_date(db, FIRM, CLIENT, "2026-01-15") == "2026-01-15"


def test_resolve_falls_back_to_default_when_not_given(monkeypatch):
    db = FakeDB()
    db.seed("clients", {"id": CLIENT, "financial_year_start": "2025-04-01"})
    monkeypatch.setattr(sc.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    assert _resolve_opening_balance_date(db, FIRM, CLIENT, None) == "2025-04-01"


def test_resolve_returns_none_when_date_is_in_a_locked_fy(monkeypatch):
    db = FakeDB()

    def _blocked(firm_id, date_str):
        raise HTTPException(status_code=422, detail="Cannot post to a locked financial year")

    monkeypatch.setattr(sc.period_validation_service, "validate_posting_date", _blocked)
    assert _resolve_opening_balance_date(db, FIRM, CLIENT, "2024-04-01") is None


# ── seed_opening_balances_batch: explicit-date-vs-legacy-fallback contract ──

def test_batch_row_with_explicit_none_date_skips_seeding_not_falls_back():
    from decimal import Decimal
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
