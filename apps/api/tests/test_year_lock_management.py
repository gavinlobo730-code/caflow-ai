"""
Secure year-lock management (multi-year hardening #3).

Verifies the backend year-lock service (the sole sanctioned writer of
firms.locked_financial_years) and its year-end integration:
  * lock / unlock toggles the firm's locked-year array (idempotent)
  * the firm lock PIN is verified server-side; first lock adopts a supplied PIN
  * a wrong PIN is rejected (403); trusted system callers may bypass the PIN
  * get_state never leaks the PIN
  * completing a year-end engagement (→ locked) locks that financial year

WHERE THE PIN LIVES (POST-A-004, migration 480): not in `firms`. It is a salted hash in `firm_lock_pins`,
which no signed-in session can read, and `firms.lock_pin` stays NULL. The tests below seed and read the
table the code actually uses; tests/test_the_year_lock_pin_is_hashed_limited_and_unreadable.py is the
fuller statement of the storage, the limiter and the audit trail.
"""
import pytest
from fastapi import HTTPException

from domain.firm import lock_pin
from services import year_lock_service as yls
import routers.year_end as ye
from routers.year_end import EngagementStatusIn
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-A"
PARTNER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "p@firma.test", "role": "Partner"}


def _setup(monkeypatch, pin=None, mods=None):
    """A firm; with `pin`, one that has already set it, as migration 480 and the service store it."""
    # A cheap hash: these tests are about who is let through, not about how slow the KDF is (the real figure
    # is pinned in the PIN test module, which does not patch it).
    monkeypatch.setattr(lock_pin, "ITERATIONS", 1_000)
    db = FakeDB()
    wire_e2e(monkeypatch, db, mods or [yls])
    db.seed("firms", {"id": FIRM, "locked_financial_years": [], "lock_pin": None})
    if pin is not None:
        db.seed("firm_lock_pins", {"firm_id": FIRM, "pin_hash": lock_pin.hash_pin(pin)})
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
    # The PIN is adopted — as a hash, in the table no signed-in session can read, never in `firms`.
    row = next(r for r in db.rows("firms") if r["id"] == FIRM)
    assert row["lock_pin"] is None
    stored = [r for r in db.rows("firm_lock_pins") if r["firm_id"] == FIRM]
    assert len(stored) == 1 and "1234" not in stored[0]["pin_hash"]
    assert lock_pin.verify("1234", stored[0]["pin_hash"]).ok


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

def test_year_end_completion_locks_that_client_only(monkeypatch):
    """Finalising an engagement closes ONE client's year.

    It used to write a FIRM-level lock (firms.locked_financial_years), so a
    Partner finalising one client's FY 2024-25 stopped posting in that year for
    every other client in the practice, and clearing it needed the firm lock
    PIN. In March or September that is a practice-wide outage produced by a
    routine click. An engagement belongs to one accounting entity, so the lock
    it writes belongs to one entity (migration 289)."""
    db = _setup(monkeypatch, mods=[ye, yls])
    db.seed("year_end_engagements", {"id": "ENG", "firm_id": FIRM,
                                     "client_id": "CLIENT-A",
                                     "financial_year": "2024-25", "status": "approved"})
    res = ye.update_engagement_status("ENG", EngagementStatusIn(status="locked"), PARTNER)
    assert res["success"] is True

    locks = [r for r in db.rows("client_year_locks")
             if r["firm_id"] == FIRM and r["financial_year"] == "2024-25"]
    assert len(locks) == 1, "the client's year was not closed"
    assert locks[0]["client_id"] == "CLIENT-A"

    firm = next(r for r in db.rows("firms") if r["id"] == FIRM)
    assert "2024-25" not in (firm.get("locked_financial_years") or []), (
        "one client's year-end locked the whole firm's financial year — the "
        "practice-wide outage this change exists to remove"
    )


def test_a_year_end_without_a_client_locks_nothing(monkeypatch):
    """There is no correct firm-wide fallback: locking the practice because a
    client id is missing is the exact bug being removed, so it refuses."""
    db = _setup(monkeypatch, mods=[ye, yls])
    db.seed("year_end_engagements", {"id": "ENG2", "firm_id": FIRM,
                                     "financial_year": "2024-25", "status": "approved"})
    ye.update_engagement_status("ENG2", EngagementStatusIn(status="locked"), PARTNER)

    firm = next(r for r in db.rows("firms") if r["id"] == FIRM)
    assert "2024-25" not in (firm.get("locked_financial_years") or [])
    assert not [r for r in db.rows("client_year_locks")
                if r["financial_year"] == "2024-25"]
