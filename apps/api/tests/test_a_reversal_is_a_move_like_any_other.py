"""
Reversing a payroll run: on the transition log, on an Indian date, and on a
screen.

WHAT WAS WRONG

1. THE ONE MOVE THAT UNDOES A RELEASE WAS THE ONE MISSING FROM THE LOG.
   Migration 328 added payroll_run_transitions so a release is defensible in
   writing, and _log_transition is called on every status move — draft to
   review, review to finalized, finalized to paid. Not on the reversal. So the
   log said a run was finalised on the 3rd and paid on the 5th, and nothing at
   all about the reversal on the 6th that took both back. A month later the
   run reads as a draft that was never released, and the entry a reviewer would
   most want to find is the one that was never written.

2. TWO POSTING DATES CAME OFF THE UTC CLOCK.
   `str(datetime.now(timezone.utc).date())` for the disbursement's default
   payment date and for the reversal date. Between midnight and 05:30 IST the
   UTC date is still YESTERDAY, so a payment or reversal made at 2am IST posts
   a day early — and on 1 April that is a different FINANCIAL YEAR, validated
   against a year a CA may have just locked. The accrual was fixed for exactly
   this; these two were left.

   This is not CLAUDE.md's "report times in IST" presentation rule. A posting
   date is a business fact: the day the money moved, in the country the money
   moved in.

3. THE REVERSAL EXISTED ONLY ON THE SERVER.
   POST /runs/{id}/reverse has been complete since the payroll module was
   built and NOTHING in the frontend called it. Every refusal ending "Reverse
   the run first" — attendance, one-time earnings — pointed at something a CA
   had no way to do.

NEGATIVE CONTROLS
    Drop the _log_transition call from reverse_run and
    test_a_reversal_reaches_the_transition_log fails.
    Put datetime.now(timezone.utc).date() back and
    test_a_reversal_posts_on_the_indian_business_day fails.
"""
from __future__ import annotations

from datetime import date

import pytest

import routers.payroll as payroll_mod
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-REV"
PARTNER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "a-1",
           "email": "ca@f.test", "role": "Partner"}


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [payroll_mod])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": "CLI", "firm_id": FIRM,
                       "financial_year_start": "2026-04-01"})
    d.seed("payroll_runs", {
        "id": "RUN-1", "firm_id": FIRM, "client_id": "CLI", "month": "2026-08",
        "status": "paid", "headcount": 2,
        "total_gross_paise": 10_000_000, "total_net_paise": 9_000_000,
        "journal_entry_id": "JE-ACCRUAL",
        "disbursement_journal_entry_id": "JE-DISBURSE",
        "finalized_at": "2026-09-03T00:00:00Z", "paid_at": "2026-09-05T00:00:00Z",
    })
    return d


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch):
    """The journal reversal and the FY lock are not what these tests are about;
    both have their own suites. Stubbed so a missing chart of accounts in the
    double does not stand in for the assertion."""
    reversed_entries: list = []
    from services.phase2_journal_service import phase2_journal_service
    from services.period_validation_service import period_validation_service
    monkeypatch.setattr(phase2_journal_service, "reverse_entry",
                        lambda *a, **k: reversed_entries.append((a, k)))
    monkeypatch.setattr(period_validation_service, "validate_posting_date",
                        lambda *a, **k: None)
    monkeypatch.setattr(payroll_mod.timeline_service, "log", lambda *a, **k: None)
    yield reversed_entries


# ─── 1. the transition log ──────────────────────────────────────────────────

def test_a_reversal_reaches_the_transition_log(db):
    """Migration 328's log is the record of what was released and why. A
    reversal that never reaches it leaves the release standing in the log
    forever."""
    payroll_mod.reverse_run("RUN-1", PARTNER)
    rows = [t for t in db.rows("payroll_run_transitions") if t["run_id"] == "RUN-1"]
    assert len(rows) == 1, "the reversal must be logged like every other move"
    assert rows[0]["to_status"] == "review"


def test_the_log_records_what_was_actually_reversed(db):
    """from_status is the status BEFORE the update — 'paid' — not the 'review'
    it has just become. Reading the pre-update row is what makes the log say
    which release was undone rather than merely that something was."""
    payroll_mod.reverse_run("RUN-1", PARTNER)
    row = next(t for t in db.rows("payroll_run_transitions") if t["run_id"] == "RUN-1")
    assert row["from_status"] == "paid"
    assert row["actor_id"] == "u-1"


def test_reversing_a_finalized_run_records_finalized(db):
    for r in db.rows("payroll_runs"):
        r["status"] = "finalized"
        r["disbursement_journal_entry_id"] = None
    payroll_mod.reverse_run("RUN-1", PARTNER)
    row = next(t for t in db.rows("payroll_run_transitions") if t["run_id"] == "RUN-1")
    assert row["from_status"] == "finalized"


def test_a_reversal_needs_no_override_reason(db):
    """Migration 328's CHECK requires a reason only for a move INTO finalized
    or paid. Reversing moves out of them, so it carries none — and the CHECK
    would refuse the row if the code sent one it did not need."""
    payroll_mod.reverse_run("RUN-1", PARTNER)
    row = next(t for t in db.rows("payroll_run_transitions") if t["run_id"] == "RUN-1")
    assert row["override_reason"] is None
    assert row["gaps"] == []


# ─── 2. the date the reversal posts on ──────────────────────────────────────

def test_a_reversal_posts_on_the_indian_business_day(db, monkeypatch, _no_side_effects):
    """2am IST on 1 April is still 31 MARCH in UTC — the previous financial
    year, which a CA may have just locked. The reversal must post on the Indian
    business day."""
    import core.ist_clock as clock
    monkeypatch.setattr(payroll_mod, "ist_today", lambda: date(2027, 4, 1))
    payroll_mod.reverse_run("RUN-1", PARTNER)
    # reverse_entry(db, firm_id, entry_id, reversal_date, ...) — positional.
    dates = {call[0][3] for call in _no_side_effects}
    assert dates == {"2027-04-01"}, f"posted on {dates}"
    assert clock  # the module is the authority; imported to say so


def test_both_journals_are_reversed_disbursement_first(db, _no_side_effects):
    """The disbursement depends on the accrual having been posted, so it is
    undone first. Reversing the accrual out from under a live disbursement
    would leave the payable credited by nothing."""
    payroll_mod.reverse_run("RUN-1", PARTNER)
    order = [call[0][2] for call in _no_side_effects]
    assert order == ["JE-DISBURSE", "JE-ACCRUAL"]


def test_the_run_reopens_at_review_not_draft(db):
    """'review' rather than 'draft': the month's work was done and checked, and
    what a correction needs is the last step back, not all of them."""
    payroll_mod.reverse_run("RUN-1", PARTNER)
    run = next(r for r in db.rows("payroll_runs") if r["id"] == "RUN-1")
    assert run["status"] == "review"
    assert run["journal_entry_id"] is None
    assert run["disbursement_journal_entry_id"] is None
    assert run["paid_at"] is None and run["finalized_at"] is None


def test_a_draft_run_cannot_be_reversed(db):
    """There is nothing posted to reverse. Refused rather than made a no-op, so
    a CA who pressed it on the wrong row is told."""
    from fastapi import HTTPException
    for r in db.rows("payroll_runs"):
        r["status"] = "draft"
    with pytest.raises(HTTPException) as e:
        payroll_mod.reverse_run("RUN-1", PARTNER)
    assert e.value.status_code == 400


def test_reversing_makes_the_month_editable_again(db):
    """The whole point of the refusals that say "Reverse the run first":
    attendance and one-time earnings are locked while a run is released, and
    reversing is what unlocks them."""
    assert payroll_mod._attendance_is_locked(db, FIRM, "CLI", "2026-08") == "paid"
    payroll_mod.reverse_run("RUN-1", PARTNER)
    assert payroll_mod._attendance_is_locked(db, FIRM, "CLI", "2026-08") is None
