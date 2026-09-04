"""
A payroll release is defensible, or a Partner signs for it in writing.

WHAT WAS WRONG
    POST /api/payroll/runs returns two lists of things the run could NOT
    establish:

        statutory_gaps    a state levies professional tax or a labour welfare
                          fund this run did not compute. Article 276 makes the
                          employer liable to deduct and deposit, so the zero is
                          a shortfall with interest, not an absence of liability.
        attendance_gaps   nobody entered attendance, so the run paid a full
                          month on the 26-day default (migrations 324, 326).

    Both were shown on the draft and enforced NOWHERE. Finalising posts a real,
    immutable general-ledger journal and is the point after which the figures
    cannot be changed — so the warnings stopped being advice at exactly the
    moment nothing was enforcing them.

WHAT IT DOES NOW
    finalize refuses a run with any gap outstanding, NAMING them, unless a
    Partner records why. The reason goes on payroll_run_transitions
    (migration 328) beside the gaps that stood, and that table is append-only:
    a log somebody can edit is a claim, not a record.

    The gaps are RECOMPUTED at the release, never read from the draft. A CA who
    records the missing state slabs (327) or enters the missing attendance (326)
    in between has genuinely closed the gap, and a stored list would still be
    refusing — which is how a block teaches people that it is noise.

    draft <-> review is logged but NOT blocked: it posts no journal and pays
    nobody, and requiring a reason there would only teach people to type "n/a"
    before the moment it matters.

NEGATIVE CONTROL
    Delete the _reason_for_releasing_with call from finalize_run and the four
    blocking tests fail — the run finalises with an unresolved gap and posts
    its journal. Drop the length floor and
    test_a_reason_of_substance_is_required passes "ok" through.
"""
from __future__ import annotations

import pytest

import routers.payroll as payroll_mod
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-REL"
CALLER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "auth-1",
          "email": "ca@f.test", "role": "Partner"}
GOOD_REASON = "Client confirmed by email on the 3rd that nobody was on leave."


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [payroll_mod])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": "CLI", "firm_id": FIRM,
                       "financial_year_start": "2026-04-01"})
    # Payroll is switched ON for this client (migration 332). A firm that
    # runs payroll for a client has said so; without the row every write
    # below is refused, which is the gate working rather than a fixture
    # detail — see assert_payroll_enabled.
    d.seed("client_payroll_settings", {"id": "cps-1", "firm_id": FIRM, "client_id": "CLI",
                                        "payroll_enabled": True})
    # journal_for_payroll resolves these by NAME and refuses without them, so a
    # clean finalise needs them present — otherwise every "it went through"
    # assertion below would be measuring a missing chart of accounts instead of
    # the release rule.
    for name in ("Salaries Expense", "Net Salary Payable", "PF Payable",
                 "ESI Payable", "PT Payable", "TDS Payable - Salary"):
        d.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": "CLI",
                                     "account_name": name, "is_active": True})
    return d


def _employee(db, name="Asha", emp_id="e-1", **kw):
    row = {"id": emp_id, "firm_id": FIRM, "client_id": "CLI", "name": name,
           "basic_paise": 5_000_000, "hra_percent": 0.0, "da_percent": 0.0,
           "other_allowances_paise": 0, "lta_paise": 0, "medical_paise": 0,
           "special_allowance_paise": 0, "pf_applicable": False,
           "esi_applicable": False, "pt_applicable": False,
           "is_active": True, "status": "active"}
    row.update(kw)
    return db.seed("payroll_employees", row)


def _attendance(db, emp_id="e-1", month=6, year=2026):
    db.seed("attendance", {"firm_id": FIRM, "employee_id": emp_id,
                           "month": month, "year": year,
                           "working_days": 26, "days_present": 26,
                           "casual_leaves": 0, "sick_leaves": 0,
                           "earned_leaves": 0, "lop_days": 0})


def _run(db, month="2026-06"):
    out = payroll_mod.create_run(
        payroll_mod.PayrollRunIn(client_id="CLI", month=month), CALLER)
    assert out["success"] is True
    return out["data"]["id"]


# ── the block ────────────────────────────────────────────────────────────────

def test_a_clean_run_finalises_with_no_reason(db):
    """The other half of any block. One that also stops the people entitled to
    the action is one that gets reverted the same week."""
    _employee(db)
    _attendance(db)
    out = payroll_mod.finalize_run(_run(db), CALLER)
    assert out["success"] is True
    assert out["data"]["status"] == "finalized"
    assert out["data"]["overridden_gaps"] == []


def test_a_run_with_an_unentered_attendance_is_blocked(db):
    """THE HEADLINE. This run pays a full month on the 26-day default and
    nobody said it should."""
    _employee(db)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        payroll_mod.finalize_run(_run(db), CALLER)
    assert e.value.status_code == 409


def test_the_refusal_names_the_gaps_rather_than_counting_them(db):
    """A count would send the CA back to the draft screen to work out which.
    The sentences are the whole point of having collected them."""
    _employee(db, name="Asha")
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        payroll_mod.finalize_run(_run(db), CALLER)
    gaps = e.value.detail["gaps"]
    assert any("Asha" in g and "no attendance entered" in g for g in gaps)


def test_a_blocked_run_posts_no_journal_and_stays_draft(db):
    """The check runs BEFORE the journal, so a refusal cannot leave a run that
    is not finalised carrying an entry that says it is."""
    _employee(db)
    run_id = _run(db)
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        payroll_mod.finalize_run(run_id, CALLER)
    run = next(r for r in db.rows("payroll_runs") if r["id"] == run_id)
    assert run["status"] == "draft"
    assert not run.get("journal_entry_id")


def test_an_unregistered_pt_state_blocks_the_release_too(db):
    """Not only attendance. Professional tax being deducted in a state with no
    registration certificate is a liability the employer cannot settle."""
    _employee(db, pt_applicable=True, pt_state="MH")
    _attendance(db)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        payroll_mod.finalize_run(_run(db), CALLER)
    assert any("PTRC" in g for g in e.value.detail["gaps"])


# ── the override ─────────────────────────────────────────────────────────────

def test_a_partner_may_release_with_a_written_reason(db):
    _employee(db)
    out = payroll_mod.finalize_run(
        _run(db), CALLER, payroll_mod.ReleaseIn(override_reason=GOOD_REASON))
    assert out["success"] is True
    assert out["data"]["status"] == "finalized"
    assert len(out["data"]["overridden_gaps"]) == 1


def test_a_reason_of_substance_is_required(db):
    """Twenty characters is not a quality bar. It is a floor under "ok", "-"
    and ".", which is what a required free-text field collects when nothing
    asks for more."""
    _employee(db)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        payroll_mod.finalize_run(
            _run(db), CALLER, payroll_mod.ReleaseIn(override_reason="ok"))
    assert e.value.status_code == 422
    assert "at least 20 characters" in e.value.detail


def test_whitespace_is_not_a_reason(db):
    _employee(db)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        payroll_mod.finalize_run(
            _run(db), CALLER, payroll_mod.ReleaseIn(override_reason="   " * 20))
    assert e.value.status_code == 409, "a blank reason is no reason at all"


def test_a_reason_on_a_clean_run_is_harmless(db):
    """Nothing to override, so nothing is refused and nothing is logged as an
    override. A CA who types one anyway has not broken anything."""
    _employee(db)
    _attendance(db)
    out = payroll_mod.finalize_run(
        _run(db), CALLER, payroll_mod.ReleaseIn(override_reason=GOOD_REASON))
    assert out["success"] is True and out["data"]["overridden_gaps"] == []


# ── the gaps are recomputed, not remembered ──────────────────────────────────

def test_entering_the_attendance_after_drafting_unblocks_the_release(db):
    """The reason the gaps are recomputed. A CA who has closed the gap has
    closed it, and a stored list would still be refusing — which is how a block
    teaches people that it is noise."""
    _employee(db)
    run_id = _run(db)
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        payroll_mod.finalize_run(run_id, CALLER)

    # The slip still says nobody entered it, so the gap must survive an
    # attendance row added AFTER the figures were computed — it did not go into
    # them. Regenerating is what closes it.
    _attendance(db)
    with pytest.raises(HTTPException):
        payroll_mod.finalize_run(run_id, CALLER)

    db.rows("payroll_runs")[:] = [r for r in db.rows("payroll_runs") if r["id"] != run_id]
    db.rows("payroll_slips")[:] = [s for s in db.rows("payroll_slips") if s["run_id"] != run_id]
    assert payroll_mod.finalize_run(_run(db), CALLER)["success"] is True


# ── the log ──────────────────────────────────────────────────────────────────

def test_a_release_writes_a_transition_row(db):
    _employee(db)
    _attendance(db)
    run_id = _run(db)
    payroll_mod.finalize_run(run_id, CALLER)
    [row] = [t for t in db.rows("payroll_run_transitions") if t["run_id"] == run_id]
    assert row["to_status"] == "finalized"
    assert row["from_status"] == "draft"
    assert row["gaps"] == []
    assert row["actor_id"] == "u-1"


def test_an_overridden_release_records_the_gaps_and_the_reason(db):
    """Beside each other, because either alone is unreadable months later."""
    _employee(db)
    run_id = _run(db)
    payroll_mod.finalize_run(run_id, CALLER,
                             payroll_mod.ReleaseIn(override_reason=GOOD_REASON))
    [row] = [t for t in db.rows("payroll_run_transitions") if t["run_id"] == run_id]
    assert row["override_reason"] == GOOD_REASON
    assert len(row["gaps"]) == 1 and "no attendance entered" in row["gaps"][0]


def test_moving_a_run_to_review_is_logged_but_not_blocked(db):
    """It posts no journal and pays nobody. Requiring a reason here would only
    teach people to type "n/a" before the moment it matters."""
    _employee(db)
    run_id = _run(db)
    out = payroll_mod.update_run_status(
        run_id, payroll_mod.RunStatusIn(status="review"), CALLER)
    assert out["success"] is True
    [row] = [t for t in db.rows("payroll_run_transitions") if t["run_id"] == run_id]
    assert row["to_status"] == "review" and row["override_reason"] is None


def test_a_blocked_release_writes_no_transition(db):
    """It did not happen. A log of attempts is a different table."""
    _employee(db)
    run_id = _run(db)
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        payroll_mod.finalize_run(run_id, CALLER)
    assert [t for t in db.rows("payroll_run_transitions") if t["run_id"] == run_id] == []


def test_the_log_is_written_after_the_transition_it_records():
    """So a logging failure cannot roll back a posted journal, and it is
    swallowed: a run that finalised HAS finalised, and a 500 at that point
    invites the re-finalisation the immutability guards exist to prevent."""
    import inspect
    src = inspect.getsource(payroll_mod._log_transition)
    assert "except Exception:" in src
    assert "_logger.exception" in src
    fin = inspect.getsource(payroll_mod.finalize_run)
    assert fin.index('"status":          "finalized"') < fin.index("_log_transition(")
