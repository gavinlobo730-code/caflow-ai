"""A released payroll run records the loan write-down it still owes, and a reversal, a delete and a recompute each act on
the run once and only while it is in the state they saw (POST-A-253, POST-A-254, migration 508).

THE DEFECTS
    * `finalize_run` claims the run as `finalized` and then writes the loans down. A process that dies between the two,
      or a write-down that fails part-way, left a released run with no record that the write-down was owed. A later
      reversal found no recovery rows and took the slip-based fallback, which adds `min(slip amount, principal -
      outstanding)` back onto a loan the run never reduced: an instalment nobody took.
    * `delete_run` and `recompute_run` read the status once and wrote without a condition on it, so a release that landed
      in between lost its slips (recompute) or the whole finalized run and its journal's evidence (delete).
    * two overlapping `reverse_run` requests both got past `reverse_entry`, which hands the second the first's entry, and
      both put the loans back.

HOW A RACE IS DRIVEN HERE
    The in-memory database runs one statement at a time, so a race is staged at the point where it matters, by a hook on
    the call that sits between the read and the write.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import routers.payroll as payroll_mod
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-OWED"
CALLER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "auth-1",
          "email": "ca@f.test", "role": "Partner"}


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [payroll_mod])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    monkeypatch.setattr(payroll_mod, "income_tax_rate_gap", lambda fy: None)
    d.seed("clients", {"id": "CLI", "firm_id": FIRM, "financial_year_start": "2026-04-01"})
    d.seed("client_payroll_settings", {"id": "cps-1", "firm_id": FIRM, "client_id": "CLI", "payroll_enabled": True})
    for name in ("Salaries Expense", "Net Salary Payable", "PF Payable", "ESI Payable", "PT Payable",
                 "TDS Payable - Salary"):
        d.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": "CLI", "account_name": name, "is_active": True})
    d.seed("payroll_employees", {
        "id": "e-1", "firm_id": FIRM, "client_id": "CLI", "name": "Asha", "basic_paise": 5_000_000,
        "hra_percent": 0.0, "da_percent": 0.0, "other_allowances_paise": 0, "lta_paise": 0, "medical_paise": 0,
        "special_allowance_paise": 0, "pf_applicable": False, "esi_applicable": False, "pt_applicable": False,
        "is_active": True, "status": "active"})
    d.seed("attendance", {"firm_id": FIRM, "employee_id": "e-1", "month": 6, "year": 2026, "working_days": 26,
                          "days_present": 26, "casual_leaves": 0, "sick_leaves": 0, "earned_leaves": 0,
                          "lop_days": 0})
    return d


def _run(db) -> str:
    out = payroll_mod.create_run(payroll_mod.PayrollRunIn(client_id="CLI", month="2026-06"), CALLER)
    assert out["success"] is True
    return out["data"]["id"]


def _row(db, run_id: str) -> dict:
    return next(r for r in db.rows("payroll_runs") if r["id"] == run_id)


def _loan(db, loan_id: str = "L-1") -> dict:
    return next(r for r in db.rows("payroll_loans") if r["id"] == loan_id)


def _recovering(db, run_id: str, amount: int = 50_000) -> None:
    for slip in db.rows("payroll_slips"):
        if slip.get("run_id") == run_id:
            slip["loan_recovery_paise"] = amount


def _a_loan(db, loan_id="L-1", principal=200_000, outstanding=200_000) -> dict:
    return db.seed("payroll_loans", {"id": loan_id, "firm_id": FIRM, "client_id": "CLI", "employee_id": "e-1",
                                     "principal_paise": principal, "outstanding_paise": outstanding,
                                     "closed_on": None})


def _recovery_rows(db, run_id: str) -> list[dict]:
    return [r for r in db.rows("payroll_loan_recoveries") if r.get("run_id") == run_id]


def _break_the_balance_write(monkeypatch, db):
    """Make the first write to a loan balance raise, as a dropped connection would."""
    real = FakeDB.table

    def table(self, name):
        q = real(self, name)
        if name == "payroll_loans":
            original = q.update

            def update(payload, **k):
                if "outstanding_paise" in payload:
                    raise ConnectionError("the database went away")
                return original(payload, **k)
            q.update = update
        return q

    monkeypatch.setattr(FakeDB, "table", table)
    return lambda: monkeypatch.setattr(FakeDB, "table", real)


# ── the release records what it still owes ───────────────────────────────────────────────────────────────────────────

def test_a_release_that_wrote_its_loans_down_owes_nothing(db):
    run_id = _run(db)
    _a_loan(db)
    _recovering(db, run_id)

    out = payroll_mod.finalize_run(run_id, CALLER)

    assert out["data"]["loan_writedown_owed"] is False
    assert _loan(db)["outstanding_paise"] == 150_000
    assert _row(db, run_id).get("loan_writedown_owed_at") is None
    assert len(_recovery_rows(db, run_id)) == 1


def test_a_release_with_no_loans_to_write_down_owes_nothing(db):
    run_id = _run(db)
    out = payroll_mod.finalize_run(run_id, CALLER)
    assert out["data"]["loan_writedown_owed"] is False
    assert _row(db, run_id).get("loan_writedown_owed_at") is None


def test_a_write_down_that_fails_leaves_the_debt_on_the_run_and_says_so(db, monkeypatch):
    run_id = _run(db)
    _a_loan(db)
    _recovering(db, run_id)
    restore = _break_the_balance_write(monkeypatch, db)

    out = payroll_mod.finalize_run(run_id, CALLER)

    restore()
    assert out["data"]["status"] == "finalized", "the release itself stands: its journal is posted"
    assert out["data"]["loan_writedown_owed"] is True
    assert _row(db, run_id)["loan_writedown_owed_at"] is not None
    assert _loan(db)["outstanding_paise"] == 200_000
    assert _recovery_rows(db, run_id) == []


def test_a_write_down_whose_history_row_cannot_be_written_puts_the_balance_back(db, monkeypatch):
    """A balance moved with no row behind it is the state neither a reversal nor a rerun can see, so it is not left."""
    run_id = _run(db)
    _a_loan(db)
    _recovering(db, run_id)
    monkeypatch.setattr(payroll_mod, "_record_loan_movement", lambda *a, **k: False)

    out = payroll_mod.finalize_run(run_id, CALLER)

    assert out["data"]["loan_writedown_owed"] is True
    assert _loan(db)["outstanding_paise"] == 200_000, "the balance must be put back when its history row failed"
    assert _row(db, run_id)["loan_writedown_owed_at"] is not None


# ── the owed write-down ──────────────────────────────────────────────────────────────────────────────────────────────

def _released_with_the_debt(db, monkeypatch) -> str:
    run_id = _run(db)
    _a_loan(db)
    _recovering(db, run_id)
    restore = _break_the_balance_write(monkeypatch, db)
    payroll_mod.finalize_run(run_id, CALLER)
    restore()
    assert _row(db, run_id)["loan_writedown_owed_at"] is not None
    return run_id


def test_the_owed_write_down_finishes_the_job_and_clears_the_debt(db, monkeypatch):
    run_id = _released_with_the_debt(db, monkeypatch)

    out = payroll_mod.write_down_owed_loans(run_id, CALLER)

    assert out["success"] is True and out["data"]["written_down"] == 1
    assert _loan(db)["outstanding_paise"] == 150_000
    assert _row(db, run_id)["loan_writedown_owed_at"] is None
    assert len(_recovery_rows(db, run_id)) == 1


def test_pressing_it_twice_writes_the_loans_down_once(db, monkeypatch):
    run_id = _released_with_the_debt(db, monkeypatch)
    payroll_mod.write_down_owed_loans(run_id, CALLER)

    with pytest.raises(HTTPException) as second:
        payroll_mod.write_down_owed_loans(run_id, CALLER)

    assert second.value.status_code == 409
    assert _loan(db)["outstanding_paise"] == 150_000
    assert len(_recovery_rows(db, run_id)) == 1


def test_a_run_that_owes_nothing_is_refused(db):
    run_id = _run(db)
    payroll_mod.finalize_run(run_id, CALLER)
    with pytest.raises(HTTPException) as refused:
        payroll_mod.write_down_owed_loans(run_id, CALLER)
    assert refused.value.status_code == 409


def test_a_loan_the_interrupted_attempt_already_wrote_down_is_not_written_down_again(db, monkeypatch):
    """Two loans for one employee. The first attempt reached the first loan (its balance and its history row) and died
    before the second. The rerun finishes the second and leaves the first alone."""
    run_id = _run(db)
    _a_loan(db, "L-1", principal=30_000, outstanding=30_000)
    _a_loan(db, "L-2", principal=200_000, outstanding=200_000)
    _recovering(db, run_id, amount=50_000)
    # what the interrupted attempt left behind: L-1 taken to 0 (30,000) with its row, L-2 untouched
    _loan(db, "L-1").update({"outstanding_paise": 0, "closed_on": "2026-07-01"})
    db.seed("payroll_loan_recoveries", {"firm_id": FIRM, "client_id": "CLI", "loan_id": "L-1", "run_id": run_id,
                                        "employee_id": "e-1", "amount_paise": 30_000, "kind": "recovered"})
    payroll_mod.finalize_run(run_id, CALLER)      # the claim; its own write-down finds L-1 on record
    _row(db, run_id)["loan_writedown_owed_at"] = datetime.now(timezone.utc).isoformat()   # the debt a crash would leave
    before = len(_recovery_rows(db, run_id))

    payroll_mod.write_down_owed_loans(run_id, CALLER)

    assert _loan(db, "L-1")["outstanding_paise"] == 0, "the loan on record is not touched again"
    assert len([r for r in _recovery_rows(db, run_id) if r["loan_id"] == "L-1"]) == 1
    assert _loan(db, "L-2")["outstanding_paise"] == 200_000 - 20_000, "the remainder of the slip amount lands on L-2"
    assert len(_recovery_rows(db, run_id)) >= before


def test_an_owed_write_down_that_fails_again_keeps_the_debt(db, monkeypatch):
    run_id = _released_with_the_debt(db, monkeypatch)
    restore = _break_the_balance_write(monkeypatch, db)

    out = payroll_mod.write_down_owed_loans(run_id, CALLER)

    restore()
    assert out["success"] is False
    assert _row(db, run_id)["loan_writedown_owed_at"] is not None, "the screen must keep offering it"
    assert _loan(db)["outstanding_paise"] == 200_000


# ── a reversal does not guess at what was never taken ────────────────────────────────────────────────────────────────

def test_reversing_a_run_whose_write_down_never_happened_restores_nothing(db, monkeypatch):
    """The borrower has repaid 100,000 already (principal 200,000, outstanding 100,000), the run's slip recovers 50,000
    and the write-down never happened. The old fallback added min(50,000, 100,000) = 50,000 back: an instalment that was
    never taken."""
    run_id = _run(db)
    _a_loan(db, principal=200_000, outstanding=100_000)
    _recovering(db, run_id, amount=50_000)
    restore = _break_the_balance_write(monkeypatch, db)
    payroll_mod.finalize_run(run_id, CALLER)
    restore()

    out = payroll_mod.reverse_run(run_id, CALLER)

    assert _loan(db)["outstanding_paise"] == 100_000, "nothing was taken, so nothing may be put back"
    assert any("never written down" in note for note in out["data"]["loan_notes"])
    assert _row(db, run_id)["status"] == "review"
    assert _row(db, run_id)["loan_writedown_owed_at"] is None, "a reopened run owes nothing"


def test_reversing_a_run_that_wrote_some_loans_down_puts_back_exactly_those(db, monkeypatch):
    run_id = _run(db)
    _a_loan(db, "L-1", principal=30_000, outstanding=0)
    _a_loan(db, "L-2", principal=200_000, outstanding=200_000)
    _recovering(db, run_id, amount=50_000)
    payroll_mod.finalize_run(run_id, CALLER)
    # make it look like the second loan was never reached
    _loan(db, "L-2").update({"outstanding_paise": 200_000})
    db.rows("payroll_loan_recoveries")[:] = [r for r in db.rows("payroll_loan_recoveries") if r["loan_id"] == "L-1"] or \
        [{"firm_id": FIRM, "client_id": "CLI", "loan_id": "L-1", "run_id": run_id, "employee_id": "e-1",
          "amount_paise": 30_000, "kind": "recovered"}]
    _row(db, run_id)["loan_writedown_owed_at"] = datetime.now(timezone.utc).isoformat()

    payroll_mod.reverse_run(run_id, CALLER)

    assert _loan(db, "L-1")["outstanding_paise"] == 30_000, "what the run took from L-1 goes back"
    assert _loan(db, "L-2")["outstanding_paise"] == 200_000, "L-2 was never reduced, so it is not raised"


# ── a reversal is claimed ────────────────────────────────────────────────────────────────────────────────────────────

def _a_released_run(db) -> str:
    run_id = _run(db)
    _a_loan(db)
    _recovering(db, run_id)
    payroll_mod.finalize_run(run_id, CALLER)
    return run_id


def test_a_reversal_reopens_the_run_and_leaves_no_claim(db):
    run_id = _a_released_run(db)

    out = payroll_mod.reverse_run(run_id, CALLER)

    assert out["data"]["status"] == "review"
    assert _row(db, run_id)["reversal_claimed_at"] is None
    assert _loan(db)["outstanding_paise"] == 200_000, "the instalment goes back once"


def test_a_second_reversal_that_arrives_while_the_first_is_running_is_refused(db, monkeypatch):
    run_id = _a_released_run(db)
    from services.phase2_journal_service import phase2_journal_service
    real = phase2_journal_service.reverse_entry
    second: dict = {}

    def reverse_while_the_other_request_arrives(*a, **k):
        try:
            payroll_mod.reverse_run(run_id, CALLER)
        except HTTPException as refused:
            second["status"] = refused.status_code
        return real(*a, **k)

    monkeypatch.setattr(phase2_journal_service, "reverse_entry", reverse_while_the_other_request_arrives)

    out = payroll_mod.reverse_run(run_id, CALLER)

    assert second == {"status": 409}
    assert out["data"]["status"] == "review"
    assert _loan(db)["outstanding_paise"] == 200_000, "one reversal puts one instalment back, not two"
    assert len([r for r in _recovery_rows(db, run_id) if r.get("kind") == "reversed"]) == 1


def test_a_reversal_that_fails_gives_the_run_back(db, monkeypatch):
    run_id = _a_released_run(db)
    from services.phase2_journal_service import phase2_journal_service

    def fails(*a, **k):
        raise RuntimeError("the ledger is unreachable")

    real = phase2_journal_service.reverse_entry
    monkeypatch.setattr(phase2_journal_service, "reverse_entry", fails)
    with pytest.raises(RuntimeError):
        payroll_mod.reverse_run(run_id, CALLER)
    assert _row(db, run_id)["reversal_claimed_at"] is None, "a failed reversal must not lock the run for fifteen minutes"
    assert _row(db, run_id)["status"] == "finalized"

    monkeypatch.setattr(phase2_journal_service, "reverse_entry", real)
    assert payroll_mod.reverse_run(run_id, CALLER)["data"]["status"] == "review"


def test_a_claim_held_by_another_request_refuses_a_reversal_and_a_lapsed_one_does_not(db):
    run_id = _a_released_run(db)
    now = datetime.now(timezone.utc)

    for minutes in (1, 10, 14):
        _row(db, run_id)["reversal_claimed_at"] = (now - timedelta(minutes=minutes)).isoformat()
        with pytest.raises(HTTPException) as held:
            payroll_mod.reverse_run(run_id, CALLER)
        assert held.value.status_code == 409, minutes
        assert _row(db, run_id)["status"] == "finalized"
        assert _loan(db)["outstanding_paise"] == 150_000, "a refused reversal changes nothing"

    _row(db, run_id)["reversal_claimed_at"] = (now - timedelta(minutes=16)).isoformat()
    assert payroll_mod.reverse_run(run_id, CALLER)["data"]["status"] == "review"


def test_a_reversal_whose_claim_was_taken_over_stops_without_logging_a_reopen(db, monkeypatch):
    run_id = _a_released_run(db)
    from services.phase2_journal_service import phase2_journal_service
    real = phase2_journal_service.reverse_entry

    def taken_over(*a, **k):
        _row(db, run_id)["reversal_claimed_at"] = "2099-01-01T00:00:00+00:00"       # another request's lease
        return real(*a, **k)

    monkeypatch.setattr(phase2_journal_service, "reverse_entry", taken_over)

    with pytest.raises(HTTPException) as stopped:
        payroll_mod.reverse_run(run_id, CALLER)

    assert stopped.value.status_code == 409
    assert _row(db, run_id)["status"] == "finalized"
    assert [t for t in db.rows("payroll_run_transitions") if t["run_id"] == run_id and t.get("to_status") == "review"] == []


# ── delete and recompute act only on a run that is still unreleased ──────────────────────────────────────────────────

def _release_lands_after_the_check(monkeypatch, db, run_id):
    """The status check passes, then the other request releases the run."""
    real = payroll_mod._assert_run_is_unreleased

    def check_then_get_released(db_, rid, firm_id, verb):
        found = real(db_, rid, firm_id, verb)
        _row(db, run_id).update({"status": "finalized", "journal_entry_id": "J-1"})
        return found

    monkeypatch.setattr(payroll_mod, "_assert_run_is_unreleased", check_then_get_released)


def test_a_run_released_after_the_check_is_not_deleted(db, monkeypatch):
    run_id = _run(db)
    _release_lands_after_the_check(monkeypatch, db, run_id)

    with pytest.raises(HTTPException) as refused:
        payroll_mod.delete_run(run_id, CALLER)

    assert refused.value.status_code == 409
    assert _row(db, run_id)["status"] == "finalized", "a released run and its journal are not removed"
    assert [s for s in db.rows("payroll_slips") if s["run_id"] == run_id], "its slips stay"
    assert [a for a in db.rows("audit_log") if a.get("entity_id") == run_id and a.get("action") == "delete"] == [], \
        "the edit log must not say a run was deleted when it was not"


def test_a_draft_run_is_still_deleted_and_logged(db):
    run_id = _run(db)
    out = payroll_mod.delete_run(run_id, CALLER)
    assert out["data"]["deleted"] is True
    assert [r for r in db.rows("payroll_runs") if r["id"] == run_id] == []


def test_a_run_released_after_the_check_keeps_its_slips_when_a_recompute_is_attempted(db, monkeypatch):
    run_id = _run(db)
    slips_before = [s["id"] for s in db.rows("payroll_slips") if s["run_id"] == run_id]
    assert slips_before
    _release_lands_after_the_check(monkeypatch, db, run_id)

    with pytest.raises(HTTPException) as refused:
        payroll_mod.recompute_run(run_id, CALLER)

    assert refused.value.status_code == 409
    assert [s["id"] for s in db.rows("payroll_slips") if s["run_id"] == run_id] == slips_before, \
        "a released run's slips are not deleted and rebuilt"


def test_the_totals_of_a_run_released_while_its_slips_were_rebuilt_are_not_overwritten(db):
    run_id = _run(db)
    before = _row(db, run_id)["total_gross_paise"]
    _row(db, run_id).update({"status": "finalized", "journal_entry_id": "J-1", "total_gross_paise": before})

    with pytest.raises(HTTPException) as refused:
        payroll_mod._compute_and_store_slips(db, FIRM, "CLI", "2026-06", run_id)

    assert refused.value.status_code == 409
    assert "reverse the run" in refused.value.detail
    assert _row(db, run_id)["total_gross_paise"] == before


def test_a_draft_run_is_still_recomputed(db):
    run_id = _run(db)
    out = payroll_mod.recompute_run(run_id, CALLER)
    assert out["success"] is True and out["data"]["headcount"] == 1
