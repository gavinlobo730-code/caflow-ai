"""A payroll run is released once and paid once, whatever arrives at the same moment (POST-A-239).

THE DEFECT
    `finalize_run` read the run, refused `finalized` and `paid`, posted the accrual journal, wrote the loans down and only
    then wrote `status = finalized` with no condition on the status. `disburse_run` was the same shape: read, check, post
    the disbursement journal, write `paid`. A second request that arrives before the first finishes holds the same stale
    `draft` / `finalized` in its hands. For the release the accrual journal is deduped (dated the month's last day, keyed
    on PAY-{month}), but the loan write-down is a read-modify-write on each balance and ran twice. For the payment the
    journal is deduped on its entry date, so two requests with different payment dates both posted and the bank was
    credited twice.

WHAT IS HELD
    * the release is claimed by ONE conditional UPDATE before the loans are touched, and a request that does not change a
      row answers 409 and writes nothing;
    * the payment is claimed before anything is posted, by setting a lease column (migration 504) on a finalized run
      nobody holds; the request that does not get the claim answers 409 and posts nothing;
    * a claim is released when the posting fails, and lapses by itself after fifteen minutes;
    * a run reversed while its payment was being posted is not marked paid, and the entry just posted is reversed.

HOW A RACE IS DRIVEN HERE
    The in-memory database runs one statement at a time, so a race is staged at the point where it matters: a hook on the
    journal call runs the OTHER request (or the other writer) in the middle of this one, which is exactly where two real
    requests interleave.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import routers.payroll as payroll_mod
from models.payroll import PayrollDisburseIn
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-ONCE"
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
    bank_coa = d.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": "CLI", "account_name": "HDFC Bank",
                                            "is_active": True})
    d.seed("bank_accounts", {"id": "BANK-1", "firm_id": FIRM, "client_id": "CLI", "bank_name": "HDFC",
                             "coa_account_id": bank_coa["id"], "is_active": True})
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


def _with_a_loan_recovery(db, run_id: str, owed: int = 200_000, recovering: int = 50_000) -> dict:
    """The run's slip recovers `recovering` paise of an employee's loan, which owes `owed`."""
    for slip in db.rows("payroll_slips"):
        if slip.get("run_id") == run_id:
            slip["loan_recovery_paise"] = recovering
    return db.seed("payroll_loans", {"id": "L-1", "firm_id": FIRM, "client_id": "CLI", "employee_id": "e-1",
                                     "principal_paise": owed, "outstanding_paise": owed, "closed_on": None})


def _loan(db) -> dict:
    return next(r for r in db.rows("payroll_loans") if r["id"] == "L-1")


def _row(db, run_id: str) -> dict:
    return next(r for r in db.rows("payroll_runs") if r["id"] == run_id)


def _disbursement_entries(db) -> list[dict]:
    return [e for e in db.rows("journal_entries") if str(e.get("reference_no", "")).startswith("PAY-DISB-")]


def _pay(db, run_id: str, on: str = "2026-07-01"):
    return payroll_mod.disburse_run(run_id, PayrollDisburseIn(bank_account_id="BANK-1", payment_date=on), CALLER)


# ── the release ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_release_writes_the_loan_down_once_and_a_second_release_is_refused(db):
    run_id = _run(db)
    _with_a_loan_recovery(db, run_id)

    out = payroll_mod.finalize_run(run_id, CALLER)

    assert out["data"]["status"] == "finalized"
    assert _loan(db)["outstanding_paise"] == 150_000
    with pytest.raises(HTTPException) as refused:
        payroll_mod.finalize_run(run_id, CALLER)
    assert refused.value.status_code == 409
    assert _loan(db)["outstanding_paise"] == 150_000, "the refused request must not touch the balance"


def test_a_request_that_loses_the_race_to_release_the_run_writes_nothing(db, monkeypatch):
    """Both requests read `draft`. The other one releases the run while this one is posting the (deduped) journal, so
    this one's claim changes no row: it answers 409, leaves the loan alone and logs no transition of its own."""
    run_id = _run(db)
    _with_a_loan_recovery(db, run_id)

    from services.phase2_journal_service import Phase2JournalService
    real = Phase2JournalService.journal_for_payroll

    def post_then_lose_the_race(self, run, firm_id, client_id):
        journal_id = real(self, run, firm_id, client_id)
        _row(db, run_id).update({"status": "finalized", "journal_entry_id": journal_id})      # the other request
        return journal_id

    monkeypatch.setattr(Phase2JournalService, "journal_for_payroll", post_then_lose_the_race)

    with pytest.raises(HTTPException) as refused:
        payroll_mod.finalize_run(run_id, CALLER)

    assert refused.value.status_code == 409
    assert _loan(db)["outstanding_paise"] == 200_000, "only the request that released the run writes the loan down"
    assert [t for t in db.rows("payroll_run_transitions") if t["run_id"] == run_id] == []


def test_a_run_nobody_has_released_is_claimed_and_the_lease_left_in_a_draft_is_erased(db):
    """A draft run is writable from a signed-in session, so a lease value put there while it was a draft must not
    survive the release and block the payment."""
    run_id = _run(db)
    _row(db, run_id)["disbursement_claimed_at"] = "2099-01-01T00:00:00+00:00"

    payroll_mod.finalize_run(run_id, CALLER)

    assert _row(db, run_id)["status"] == "finalized"
    assert _row(db, run_id)["disbursement_claimed_at"] is None
    assert _pay(db, run_id)["data"]["status"] == "paid"


# ── the payment ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _a_finalized_run(db) -> str:
    run_id = _run(db)
    payroll_mod.finalize_run(run_id, CALLER)
    return run_id


def test_a_payment_marks_the_run_paid_posts_one_entry_and_clears_the_claim(db):
    run_id = _a_finalized_run(db)

    out = _pay(db, run_id)

    assert out["data"]["status"] == "paid"
    assert len(_disbursement_entries(db)) == 1
    row = _row(db, run_id)
    assert row["status"] == "paid" and row["disbursement_claimed_at"] is None
    assert row["disbursement_journal_entry_id"] == out["data"]["disbursement_journal_entry_id"]


def test_a_second_payment_with_another_date_is_refused_while_the_first_is_posting(db, monkeypatch):
    """The defect: the journal's duplicate check includes the entry date, so a second request dated a day later was not
    a duplicate of the first and the bank was credited twice. The second request now meets the first one's claim."""
    run_id = _a_finalized_run(db)
    from services.phase2_journal_service import Phase2JournalService
    real = Phase2JournalService.journal_for_payroll_disbursement
    second: dict = {}

    def post_while_the_other_request_arrives(self, run, bank_account, firm_id, client_id, payment_date):
        try:
            _pay(db, run_id, on="2026-07-02")
        except HTTPException as refused:
            second["status"] = refused.status_code
        return real(self, run, bank_account, firm_id, client_id, payment_date)

    monkeypatch.setattr(Phase2JournalService, "journal_for_payroll_disbursement", post_while_the_other_request_arrives)

    first = _pay(db, run_id, on="2026-07-01")

    assert second == {"status": 409}
    assert first["data"]["status"] == "paid"
    assert len(_disbursement_entries(db)) == 1, "one payroll is one credit to the bank"
    assert _disbursement_entries(db)[0]["entry_date"] == "2026-07-01"


def test_a_payment_that_fails_to_post_gives_the_run_back(db, monkeypatch):
    run_id = _a_finalized_run(db)
    from services.phase2_journal_service import Phase2JournalService

    def fails(self, *a, **k):
        raise RuntimeError("the ledger is unreachable")

    real = Phase2JournalService.journal_for_payroll_disbursement
    monkeypatch.setattr(Phase2JournalService, "journal_for_payroll_disbursement", fails)
    with pytest.raises(RuntimeError):
        _pay(db, run_id)
    assert _row(db, run_id)["disbursement_claimed_at"] is None, "a failed posting must not lock the run for fifteen minutes"
    assert _row(db, run_id)["status"] == "finalized"

    # The ledger is back; the Partner presses Pay again. Only the failing method is put back: `monkeypatch.undo()` would
    # also undo the database wiring, switch the router into its no-database branch and make this assertion vacuous.
    monkeypatch.setattr(Phase2JournalService, "journal_for_payroll_disbursement", real)
    assert _pay(db, run_id)["data"]["status"] == "paid"
    assert _row(db, run_id)["status"] == "paid" and len(_disbursement_entries(db)) == 1


def test_a_claim_held_by_another_request_refuses_a_payment_and_a_lapsed_one_does_not(db, monkeypatch):
    run_id = _a_finalized_run(db)
    now = datetime.now(timezone.utc)

    for minutes in (1, 10, 14):                              # a live claim, up to just inside the lease
        _row(db, run_id)["disbursement_claimed_at"] = (now - timedelta(minutes=minutes)).isoformat()
        with pytest.raises(HTTPException) as held:
            _pay(db, run_id)
        assert held.value.status_code == 409, minutes
        assert _disbursement_entries(db) == [], "a refused payment posts nothing"
        assert _row(db, run_id)["status"] == "finalized"

    _row(db, run_id)["disbursement_claimed_at"] = (now - timedelta(minutes=16)).isoformat()    # lapsed
    assert _pay(db, run_id)["data"]["status"] == "paid"


def test_a_run_reversed_while_its_payment_was_posting_is_not_marked_paid_and_the_entry_is_undone(db, monkeypatch):
    run_id = _a_finalized_run(db)
    from services.phase2_journal_service import Phase2JournalService, phase2_journal_service
    real = Phase2JournalService.journal_for_payroll_disbursement
    undone: list = []

    def post_then_get_reversed(self, run, bank_account, firm_id, client_id, payment_date):
        journal_id = real(self, run, bank_account, firm_id, client_id, payment_date)
        _row(db, run_id).update({"status": "review", "journal_entry_id": None})              # reverse_run, mid-flight
        return journal_id

    monkeypatch.setattr(Phase2JournalService, "journal_for_payroll_disbursement", post_then_get_reversed)
    # On the INSTANCE, not the class: other test modules patch the singleton's attribute by string path and monkeypatch
    # restores it as an instance attribute holding the old bound method, which would shadow a class-level patch here.
    monkeypatch.setattr(phase2_journal_service, "reverse_entry",
                        lambda db_, firm_id, journal_id, *a, **k: undone.append(journal_id) or "REV-1")

    with pytest.raises(HTTPException) as refused:
        _pay(db, run_id)

    assert refused.value.status_code == 409
    assert _row(db, run_id)["status"] == "review", "the run stays where the reversal put it"
    assert _row(db, run_id).get("disbursement_journal_entry_id") is None
    assert len(undone) == 1 and undone[0] == _disbursement_entries(db)[0]["id"], "the posted entry must be reversed"


def test_a_run_already_paid_is_still_refused_before_any_claim_is_made(db):
    run_id = _a_finalized_run(db)
    _pay(db, run_id)
    with pytest.raises(HTTPException) as refused:
        _pay(db, run_id)
    assert refused.value.status_code == 409
    assert len(_disbursement_entries(db)) == 1


def test_a_run_paid_by_another_request_before_this_one_claims_is_not_claimed_again(db, monkeypatch):
    """The claim's status filter. The run is `finalized` when this request reads it and `paid` by the time it claims: its
    lease is empty again after the payment, so only the status stops a second payment. The flip is staged where the
    router asks for today's date, which is after the read and before the claim."""
    run_id = _a_finalized_run(db)
    real_today = payroll_mod.ist_today

    def another_request_pays_first():
        _row(db, run_id).update({"status": "paid", "disbursement_claimed_at": None})
        return real_today()

    monkeypatch.setattr(payroll_mod, "ist_today", another_request_pays_first)
    with pytest.raises(HTTPException) as refused:
        payroll_mod.disburse_run(run_id, PayrollDisburseIn(bank_account_id="BANK-1"), CALLER)
    assert refused.value.status_code == 409
    assert _disbursement_entries(db) == []


def test_a_retry_after_a_posting_that_timed_out_with_another_date_is_not_a_second_payment(db, monkeypatch):
    """The entry committed and the response was lost, so the run is still `finalized` and its claim was released. A retry
    dated a day later is not a repeat to the journal kernel, which keys on the entry date: it must find the first entry
    itself and say where it is. The same date goes through and records the payment against the run."""
    run_id = _a_finalized_run(db)
    from services.phase2_journal_service import Phase2JournalService
    real = Phase2JournalService.journal_for_payroll_disbursement

    def commit_then_time_out(self, *a, **k):
        real(self, *a, **k)
        raise TimeoutError("the response never arrived")

    monkeypatch.setattr(Phase2JournalService, "journal_for_payroll_disbursement", commit_then_time_out)
    with pytest.raises(TimeoutError):
        _pay(db, run_id, on="2026-07-01")
    monkeypatch.setattr(Phase2JournalService, "journal_for_payroll_disbursement", real)
    assert len(_disbursement_entries(db)) == 1 and _row(db, run_id)["status"] == "finalized"

    with pytest.raises(HTTPException) as refused:
        _pay(db, run_id, on="2026-07-02")
    assert refused.value.status_code == 409 and "2026-07-01" in refused.value.detail
    assert len(_disbursement_entries(db)) == 1, "the retry must not post a second entry"
    assert _row(db, run_id)["disbursement_claimed_at"] is None, "a refused retry gives the run back"

    assert _pay(db, run_id, on="2026-07-01")["data"]["status"] == "paid"
    assert len(_disbursement_entries(db)) == 1


def test_a_payment_whose_lease_was_taken_over_and_paid_by_another_request_is_not_undone(db, monkeypatch):
    """This request stalled past the lease; another took over, posted the same entry (the kernel hands both the same one
    on the same date) and marked the run paid. This request's paid-write then changes no row, and the entry is the OTHER
    request's payment, so it must not be reversed."""
    run_id = _a_finalized_run(db)
    from services.phase2_journal_service import Phase2JournalService
    real = Phase2JournalService.journal_for_payroll_disbursement

    def post_and_let_another_request_finish_first(self, run, bank_account, firm_id, client_id, payment_date):
        journal_id = real(self, run, bank_account, firm_id, client_id, payment_date)
        _row(db, run_id).update({"status": "paid", "disbursement_journal_entry_id": journal_id,
                                 "disbursement_claimed_at": None})
        return journal_id

    monkeypatch.setattr(Phase2JournalService, "journal_for_payroll_disbursement", post_and_let_another_request_finish_first)
    with pytest.raises(HTTPException) as refused:
        _pay(db, run_id)
    assert refused.value.status_code == 409 and "Another request" in refused.value.detail
    entry = _disbursement_entries(db)[0]
    assert not entry.get("is_reversed"), "the payment the other request recorded must stay in the books"
    assert _row(db, run_id)["status"] == "paid"


def test_a_payment_whose_lease_was_taken_over_while_the_other_request_is_still_posting_leaves_the_entry_in_place(db, monkeypatch):
    """The other request holds the lease and has not marked the run paid yet. The kernel may have handed it the entry this
    request posted, so this request must not reverse it; and this request's own write is refused because the lease is no
    longer its own, even though the run is still `finalized`."""
    run_id = _a_finalized_run(db)
    from services.phase2_journal_service import Phase2JournalService
    real = Phase2JournalService.journal_for_payroll_disbursement

    def post_and_lose_the_lease(self, run, bank_account, firm_id, client_id, payment_date):
        journal_id = real(self, run, bank_account, firm_id, client_id, payment_date)
        _row(db, run_id)["disbursement_claimed_at"] = datetime.now(timezone.utc).isoformat() + "-other"
        return journal_id

    monkeypatch.setattr(Phase2JournalService, "journal_for_payroll_disbursement", post_and_lose_the_lease)
    with pytest.raises(HTTPException) as refused:
        _pay(db, run_id)
    assert refused.value.status_code == 409
    assert not _disbursement_entries(db)[0].get("is_reversed")
    assert _row(db, run_id)["status"] == "finalized"
    assert _row(db, run_id)["disbursement_claimed_at"].endswith("-other"), "the new holder's claim must be left as it is"


def test_a_reopened_runs_posted_entry_is_really_reversed_by_the_undo(db, monkeypatch):
    """The earlier reversal test replaces `reverse_entry`; this one lets the real one run, so the date, the signature and
    the netting of the entry are exercised."""
    run_id = _a_finalized_run(db)
    from services.phase2_journal_service import Phase2JournalService
    real = Phase2JournalService.journal_for_payroll_disbursement

    def post_then_get_reversed(self, run, bank_account, firm_id, client_id, payment_date):
        journal_id = real(self, run, bank_account, firm_id, client_id, payment_date)
        _row(db, run_id).update({"status": "review", "journal_entry_id": None})
        return journal_id

    monkeypatch.setattr(Phase2JournalService, "journal_for_payroll_disbursement", post_then_get_reversed)
    with pytest.raises(HTTPException) as refused:
        _pay(db, run_id)
    assert refused.value.status_code == 409 and "was reversed" in refused.value.detail and "NOT" not in refused.value.detail
    assert _disbursement_entries(db)[0].get("is_reversed") is True
    assert _row(db, run_id).get("disbursement_claimed_at") is None, "a reopened run must not carry the lease"


def test_when_the_undo_cannot_reverse_the_entry_the_screen_says_it_is_still_in_the_books(db, monkeypatch):
    run_id = _a_finalized_run(db)
    from services.phase2_journal_service import Phase2JournalService, phase2_journal_service
    real = Phase2JournalService.journal_for_payroll_disbursement

    def post_then_get_reversed(self, run, bank_account, firm_id, client_id, payment_date):
        journal_id = real(self, run, bank_account, firm_id, client_id, payment_date)
        _row(db, run_id).update({"status": "review", "journal_entry_id": None})
        return journal_id

    def cannot_reverse(db_, firm_id, journal_id, *a, **k):
        raise ValueError("the period is closed")

    monkeypatch.setattr(Phase2JournalService, "journal_for_payroll_disbursement", post_then_get_reversed)
    monkeypatch.setattr(phase2_journal_service, "reverse_entry", cannot_reverse)
    with pytest.raises(HTTPException) as refused:
        _pay(db, run_id)
    entry = _disbursement_entries(db)[0]
    assert refused.value.status_code == 409
    assert "could NOT be reversed" in refused.value.detail and entry["id"] in refused.value.detail
    assert "was reversed" in refused.value.detail and "the entry that had just been posted was reversed" not in refused.value.detail


def test_a_reversal_that_lands_between_the_release_claim_and_the_loan_write_down_leaves_the_loans_alone(db, monkeypatch):
    """The claim makes the run `finalized` BEFORE the loans are written down, so a reversal can land in between: it finds
    no recovery rows to put back, reopens the run, and the write-down would then apply to a run in review. The release
    reads the run again afterwards and, finding it reopened, puts the write-down back and answers 409."""
    run_id = _run(db)
    _with_a_loan_recovery(db, run_id)
    monkeypatch.setattr("services.period_validation_service.period_validation_service.validate_posting_date",
                        lambda *a, **k: None)
    from services.phase2_journal_service import phase2_journal_service
    monkeypatch.setattr(phase2_journal_service, "reverse_entry", lambda db_, firm_id, journal_id, *a, **k: "REV")
    real = payroll_mod._apply_loan_recoveries

    def reverse_first_then_write_down(db_, firm_id, client_id, rid, created_by=None):
        payroll_mod.reverse_run(run_id, CALLER)
        return real(db_, firm_id, client_id, rid, created_by)

    monkeypatch.setattr(payroll_mod, "_apply_loan_recoveries", reverse_first_then_write_down)
    with pytest.raises(HTTPException) as refused:
        payroll_mod.finalize_run(run_id, CALLER)

    assert refused.value.status_code == 409 and "reversed while it was being released" in refused.value.detail
    assert _row(db, run_id)["status"] == "review"
    assert _loan(db)["outstanding_paise"] == 200_000, "the write-down applied to a reopened run must be put back"
    finalised = [t for t in db.rows("payroll_run_transitions") if t["run_id"] == run_id and t["to_status"] == "finalized"]
    assert finalised == [], "a release that was undone before it finished must not be logged as one"


def test_reversing_a_run_clears_a_payment_lease_left_on_it(db, monkeypatch):
    run_id = _a_finalized_run(db)
    _row(db, run_id)["disbursement_claimed_at"] = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr("services.period_validation_service.period_validation_service.validate_posting_date",
                        lambda *a, **k: None)
    from services.phase2_journal_service import phase2_journal_service
    monkeypatch.setattr(phase2_journal_service, "reverse_entry", lambda db_, firm_id, journal_id, *a, **k: "REV")
    payroll_mod.reverse_run(run_id, CALLER)
    assert _row(db, run_id)["status"] == "review" and _row(db, run_id)["disbursement_claimed_at"] is None


# ── mutation controls: the tests above must fail without the claim ───────────────────────────────────────────────────

def test_the_finalise_claim_is_a_conditional_update_and_runs_before_the_write_down():
    import inspect
    src = inspect.getsource(payroll_mod.finalize_run)
    assert '.not_.in_("status", ["finalized", "paid"])' in src
    assert src.index("claimed = ") < src.index("_apply_loan_recoveries(")
    assert "if not claimed.data" in src


def test_the_disbursement_claim_comes_before_the_journal_and_the_paid_write_is_conditional():
    import inspect
    src = inspect.getsource(payroll_mod.disburse_run)
    assert src.index("_claim_the_run_for_disbursement(") < src.index("journal_for_payroll_disbursement(")
    assert '.eq("status", "finalized")' in src[src.index("paid = "):]
    assert "_release_disbursement_claim" in src
