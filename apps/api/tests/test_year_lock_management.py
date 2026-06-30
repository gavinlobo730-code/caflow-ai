"""
Secure year-lock management (multi-year hardening #3).

Verifies the backend year-lock service (the sole sanctioned writer of
firms.locked_financial_years) and its year-end integration:
  * lock / unlock toggles the firm's locked-year array (idempotent)
  * the firm lock PIN is verified server-side; first lock adopts a supplied PIN
  * a wrong PIN is rejected (403); trusted system callers may bypass the PIN
  * get_state never leaks the PIN
  * completing a year-end engagement (→ locked) locks that financial year
"""
import pytest
from fastapi import HTTPException

from services import year_lock_service as yls
import routers.year_end as ye
from routers.year_end import EngagementStatusIn
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-A"
PARTNER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "p@firma.test", "role": "Partner"}


def _setup(monkeypatch, pin=None, mods=None):
    db = FakeDB()
    wire_e2e(monkeypatch, db, mods or [yls])
    db.seed("firms", {"id": FIRM, "locked_financial_years": [], "lock_pin": pin})
    return db


# ── service: lock / unlock ───────────────────────────────────────────────────

def test_lock_then_unlock(monkeypatch):
    db = _setup(monkeypatch)
    s = yls.set_lock(db, FIRM, "2024-25", lock=True)
    assert "2024-25" in s["locked_financial_years"]
    s = yls.set_lock(db, FIRM, "2024-25", lock=False)
    assert "2024-25" not in s["locked_financial_years"]


def test_lock_is_idempotent(monkeypatch):
    db = _setup(monkeypatch)
    yls.set_lock(db, FIRM, "2024-25", lock=True)
    yls.set_lock(db, FIRM, "2024-25", lock=True)
    row = next(r for r in db.rows("firms") if r["id"] == FIRM)
    assert row["locked_financial_years"].count("2024-25") == 1


# ── service: PIN handling ────────────────────────────────────────────────────

def test_first_lock_sets_pin(monkeypatch):
    db = _setup(monkeypatch, pin=None)
    s = yls.set_lock(db, FIRM, "2024-25", lock=True, pin="1234")
    assert s["pin_set"] is True
    row = next(r for r in db.rows("firms") if r["id"] == FIRM)
    assert row["lock_pin"] == "1234"


def test_wrong_pin_blocked(monkeypatch):
    db = _setup(monkeypatch, pin="1234")
    with pytest.raises(HTTPException) as e:
        yls.set_lock(db, FIRM, "2024-25", lock=True, pin="9999")
    assert e.value.status_code == 403
    row = next(r for r in db.rows("firms") if r["id"] == FIRM)
    assert "2024-25" not in row["locked_financial_years"]   # unchanged


def test_correct_pin_allows(monkeypatch):
    db = _setup(monkeypatch, pin="1234")
    s = yls.set_lock(db, FIRM, "2024-25", lock=True, pin="1234")
    assert "2024-25" in s["locked_financial_years"]


def test_system_caller_bypasses_pin(monkeypatch):
    db = _setup(monkeypatch, pin="1234")
    s = yls.set_lock(db, FIRM, "2024-25", lock=True, bypass_pin=True)
    assert "2024-25" in s["locked_financial_years"]


def test_get_state_never_leaks_pin(monkeypatch):
    db = _setup(monkeypatch, pin="1234")
    s = yls.get_state(db, FIRM)
    assert s["pin_set"] is True
    assert "lock_pin" not in s and "pin" not in s


# ── year-end integration ─────────────────────────────────────────────────────

def test_year_end_completion_locks_the_year(monkeypatch):
    db = _setup(monkeypatch, mods=[ye, yls])
    db.seed("year_end_engagements", {"id": "ENG", "firm_id": FIRM,
                                     "financial_year": "2024-25", "status": "approved"})
    res = ye.update_engagement_status("ENG", EngagementStatusIn(status="locked"), PARTNER)
    assert res["success"] is True
    row = next(r for r in db.rows("firms") if r["id"] == FIRM)
    assert "2024-25" in row["locked_financial_years"]
