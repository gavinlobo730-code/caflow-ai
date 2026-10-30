"""An ESI remittance recorded as paid closes the wage month's ESI deposit obligation when it was on time and covered what payroll computed (POST-A-267, the ESI half).

WHAT WAS WRONG
    A client with a payroll engagement carries an `ESI_DEPOSIT` obligation for every wage month on the compliance calendar, and the
    remittance register (`POST /api/payroll/clients/{id}/remittances`) is where a deposit is recorded. Recording one never touched
    the calendar, so a month's ESI paid and recorded read Overdue on Deadlines, the Compliance tab and the dashboard. It is the
    split the GST and ITR workspaces, the TDS statements and challans, the MCA filings and the advance-tax register had.

WHAT IS HELD
    * the obligation is closed when the remittance is PAID, payroll has a finalised run for the month whose ESI (the employees'
      share plus the employer's, from the slips) is above nil, the amount recorded is AT LEAST that sum (interest can be added at
      the portal), and the payment is dated, not in the future, not before the wage month and ON OR BEFORE the 15th of the next
      month; it carries the payment date and the challan number;
    * each way of failing leaves it open with its own sentence: only submitted, no finalised run, nil computed, amount not recorded
      (the field's default is not "paid nothing"), amount short (the sentence names the three figures), no date, a future date, a date
      before the month, a late payment;
    * only the wage month's own ESI obligation moves, not another month's, type's, client's or a draft run's;
    * an obligation already Filed keeps its own date and is not answered; a professional-tax or EPF record answers nothing; a client
      with no such obligation is told so without being asked to act; a caller without compliance access is told, and nothing moves;
    * a failure reading the calendar never fails the recording, and the route answers `compliance_obligations` beside the row.
"""
from __future__ import annotations

from datetime import date

import pytest

import routers.payroll as payroll
from mock_data import MOCK_COMPLIANCE_RECORDS
from repositories.compliance_records_repository import compliance_records_repo
from services import esi_deposit_closes_obligation as closes
from services.esi_deposit_closes_obligation import Decision, decide
from tests.e2e_harness import FakeDB

FIRM, CLIENT = "firm-1", "client-1"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}
MONTH = "2026-06"
DUE = date(2026, 7, 15)
MONTH_START = date(2026, 6, 1)
AFTER = date(2026, 8, 1)
WHAT = "ESI deposit obligation for June 2026"
EMPLOYEES, EMPLOYER = 1_500_00, 4_000_00
OWED = EMPLOYEES + EMPLOYER


@pytest.fixture
def world(monkeypatch):
    import services.audit_service as au
    import services.timeline_service as ts
    MOCK_COMPLIANCE_RECORDS.clear()
    monkeypatch.setattr(au, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(closes, "ist_today", lambda: AFTER)
    yield
    MOCK_COMPLIANCE_RECORDS.clear()


def _db(*, status="finalized", employees=EMPLOYEES, employer=EMPLOYER, month=MONTH, client=CLIENT, slips=2) -> FakeDB:
    db = FakeDB()
    db.seed("payroll_runs", {"id": "run-1", "firm_id": FIRM, "client_id": client, "month": month, "status": status})
    for i in range(slips):
        db.seed("payroll_slips", {"id": f"slip-{i}", "run_id": "run-1", "esi_employee_paise": employees // slips,
                                  "esi_employer_paise": employer // slips})
    return db


def _obligation(month="2026-06", *, client=CLIENT, otype="ESI_DEPOSIT", ctype="Payroll", status="Not Started"):
    y, m = int(month[:4]), int(month[5:7])
    nxt = date(y + (m == 12), m % 12 + 1, 15).isoformat()
    return compliance_records_repo.create({
        "firm_id": FIRM, "client_id": client, "compliance_type": ctype, "obligation_type": otype,
        "period_label": f"ESI contribution {month}", "period_start": f"{month}-01", "period_end": f"{month}-28",
        "due_date": nxt, "status": status})


def _now(rec):
    return compliance_records_repo.find_by_id(rec["id"])


def _remittance(*, amount=OWED, paid_on="2026-07-10", status="paid", challan="CH-77", month=MONTH, scheme="esic"):
    return {"id": "rem-1", "scheme": scheme, "wage_month": month, "status": status, "paid_on": paid_on, "amount_paise": amount,
            "challan_number": challan}


def _close(remittance, db=None, *, may_write=True, client=CLIENT):
    return closes.close_for_recorded_remittance(
        db=db if db is not None else _db(), firm_id=FIRM, client_id=client, remittance=remittance, actor=USER,
        may_write_compliance=may_write)


# ── the rule ────────────────────────────────────────────────────────────────

def _decide(**kw):
    base = dict(today=AFTER, due=DUE, month_start=MONTH_START, what=WHAT, owed_paise=OWED, employee_paise=EMPLOYEES,
                employer_paise=EMPLOYER, paid_paise=OWED, paid_on=date(2026, 7, 10), challan_number="CH-77")
    base.update(kw)
    return decide(**base)


def test_covered_and_on_time_closes_with_the_payment_date_and_the_challan():
    assert _decide() == Decision(filed_on=date(2026, 7, 10), reference="CH-77")


def test_the_due_date_itself_is_on_time_and_the_day_after_is_not():
    assert _decide(paid_on=DUE).filed_on == DUE
    late = _decide(paid_on=date(2026, 7, 16))
    assert late.filed_on is None and "after the due date 2026-07-15" in late.sentence and "Compliance" in late.sentence


def test_an_amount_above_what_payroll_computed_closes_because_interest_can_be_added_at_the_portal():
    assert _decide(paid_paise=OWED + 1_23_00).filed_on == date(2026, 7, 10)


def test_one_paisa_short_closes_nothing_and_the_sentence_names_the_three_figures():
    got = _decide(paid_paise=OWED - 1)
    assert got.filed_on is None
    assert "₹5,499.99" in got.sentence and "₹5,500" in got.sentence and "₹1,500" in got.sentence and "₹4,000" in got.sentence
    assert _decide(paid_paise=OWED).filed_on is not None


def test_an_amount_left_at_nil_is_not_recorded_rather_than_paid_nothing():
    got = _decide(paid_paise=0)
    assert got.filed_on is None and "not recorded" in got.sentence


def test_no_finalised_run_is_said():
    got = _decide(owed_paise=None)
    assert got.filed_on is None and "no finalised run" in got.sentence


def test_a_month_payroll_computed_no_esi_for_is_not_closed_here():
    got = _decide(owed_paise=0, employee_paise=0, employer_paise=0)
    assert got.filed_on is None and "computed no ESI" in got.sentence


def test_a_payment_with_no_date_a_future_date_and_a_date_before_the_month_each_close_nothing():
    assert "no payment date" in _decide(paid_on=None).sentence
    assert "has not happened yet" in _decide(paid_on=date(2026, 8, 5)).sentence
    before = _decide(paid_on=date(2026, 5, 31))
    assert before.filed_on is None and "before the wage month began" in before.sentence


def test_a_blank_challan_number_is_no_reference():
    assert _decide(challan_number="  ").reference is None
    assert _decide(challan_number=None).reference is None


# ── the register ────────────────────────────────────────────────────────────

def test_a_paid_remittance_closes_the_months_obligation_with_the_date_and_the_challan(world):
    rec = _obligation()
    answers = _close(_remittance())
    assert len(answers) == 1 and answers[0]["closed"] is True and answers[0]["needs_action"] is False
    assert answers[0]["filed_on"] == "2026-07-10" and answers[0]["reference"] == "CH-77" and answers[0]["month"] == MONTH
    assert "challan CH-77" in answers[0]["message"]
    now = _now(rec)
    assert now["status"] == "Filed" and now["filed_date"] == "2026-07-10" and now["acknowledgement_no"] == "CH-77"


def test_a_late_payment_leaves_the_obligation_open_and_asks_somebody_to_act(world):
    rec = _obligation()
    answers = _close(_remittance(paid_on="2026-07-20"))
    assert [a["state"] for a in answers] == ["not_closed"] and answers[0]["needs_action"] is True
    assert "after the due date" in answers[0]["message"]
    assert _now(rec)["status"] == "Not Started"


def test_a_short_payment_leaves_it_open(world):
    rec = _obligation()
    answers = _close(_remittance(amount=OWED - 100))
    assert answers[0]["state"] == "not_closed" and "less than" in answers[0]["message"]
    assert _now(rec)["status"] == "Not Started"


def test_a_remittance_only_submitted_answers_nothing_and_closes_nothing(world):
    rec = _obligation()
    assert _close(_remittance(status="submitted")) == []
    assert _now(rec)["status"] == "Not Started"


def test_professional_tax_answers_nothing(world):
    rec = _obligation()
    assert _close(_remittance(scheme="professional_tax")) == []
    assert _now(rec)["status"] == "Not Started"


def test_a_draft_run_does_not_count_as_payroll_having_computed_the_month(world):
    rec = _obligation()
    answers = _close(_remittance(), _db(status="draft"))
    assert answers[0]["state"] == "not_closed" and "no finalised run" in answers[0]["message"]
    assert _now(rec)["status"] == "Not Started"


def test_another_clients_finalised_run_is_not_this_clients(world):
    rec = _obligation()
    answers = _close(_remittance(), _db(client="client-2"))
    assert "no finalised run" in answers[0]["message"]
    assert _now(rec)["status"] == "Not Started"


def test_a_paid_run_counts_as_finalised(world):
    rec = _obligation()
    assert _close(_remittance(), _db(status="paid"))[0]["closed"] is True
    assert _now(rec)["status"] == "Filed"


def test_only_the_wage_months_own_esi_obligation_moves(world):
    mine = _obligation()
    other_month = _obligation("2026-05")
    other_type = _obligation(otype="EPF_DEPOSIT")
    other_client = _obligation(client="client-2")
    _close(_remittance())
    assert _now(mine)["status"] == "Filed"
    assert all(_now(r)["status"] == "Not Started" for r in (other_month, other_type, other_client))


def test_an_obligation_already_filed_keeps_its_own_date_and_is_not_answered(world):
    rec = _obligation()
    compliance_records_repo.update(rec["id"], {"status": "Filed", "filed_date": "2026-07-12", "acknowledgement_no": "MINE"})
    assert _close(_remittance()) == []
    assert _now(rec)["filed_date"] == "2026-07-12" and _now(rec)["acknowledgement_no"] == "MINE"


def test_a_client_with_no_esi_obligation_is_told_so_without_being_asked_to_act(world):
    answers = _close(_remittance())
    assert len(answers) == 1 and answers[0]["state"] == "not_on_the_calendar" and answers[0]["needs_action"] is False


def test_without_compliance_access_nothing_closes_and_the_answer_says_so(world):
    rec = _obligation()
    answers = _close(_remittance(), may_write=False)
    assert [a["state"] for a in answers] == ["not_allowed"] and answers[0]["needs_action"] is True
    assert _now(rec)["status"] == "Not Started"


def test_a_remittance_with_a_wage_month_that_is_not_one_answers_nothing(world):
    _obligation()
    assert _close(_remittance(month="June 2026")) == []


def test_the_amount_owed_is_summed_from_every_slip_of_the_months_run_and_only_that_run():
    db = FakeDB()
    db.seed("payroll_runs", {"id": "run-1", "firm_id": FIRM, "client_id": CLIENT, "month": MONTH, "status": "finalized"})
    db.seed("payroll_runs", {"id": "run-0", "firm_id": FIRM, "client_id": CLIENT, "month": "2026-05", "status": "finalized"})
    for rid, emp, empr in (("run-1", 100_00, 300_00), ("run-1", 250_00, 700_00), ("run-1", 0, 0), ("run-0", 999_00, 999_00)):
        db.seed("payroll_slips", {"run_id": rid, "esi_employee_paise": emp, "esi_employer_paise": empr})
    assert closes.esi_owed(db, FIRM, CLIENT, MONTH) == (350_00, 1000_00)
    assert closes.esi_owed(_db(status="draft"), FIRM, CLIENT, MONTH) is None
    assert closes.esi_owed(db, FIRM, CLIENT, "2026-04") is None


def test_a_client_that_is_named_by_nobody_is_not_matched():
    out = closes.close_for_recorded_remittance(db=_db(), firm_id="", client_id="", remittance=_remittance(), actor=USER,
                                               may_write_compliance=True)
    assert len(out) == 1 and out[0]["needs_action"] and "names no client" in out[0]["message"]


# ── the door ────────────────────────────────────────────────────────────────

@pytest.fixture
def door(world, monkeypatch):
    db = _db()
    monkeypatch.setattr(payroll, "_db", lambda: db)
    monkeypatch.setattr(payroll, "assert_client_access", lambda user, client_id: None)
    monkeypatch.setattr(payroll.remittances, "record", lambda db, **kw: _remittance(
        amount=kw["amount_paise"], paid_on=kw["paid_on"], status=kw["status"], challan=kw["challan_number"], month=kw["wage_month"]))
    monkeypatch.setattr("core.permissions.can_user", lambda user, resource, action: True)
    return db


def _body(**kw):
    base = dict(scheme="esic", wage_month=MONTH, status="paid", submitted_on="2026-07-09", paid_on="2026-07-10",
                challan_number="CH-77", amount_paise=OWED)
    base.update(kw)
    return payroll.RemittanceIn(**base)


def test_recording_the_remittance_answers_the_row_and_what_became_of_the_obligation(door):
    rec = _obligation()
    out = payroll.record_remittance(CLIENT, _body(), current_user=USER)
    assert out["success"] is True and out["data"]["remittance"]["challan_number"] == "CH-77"
    answers = out["data"]["compliance_obligations"]
    assert len(answers) == 1 and answers[0]["closed"] is True
    assert _now(rec)["status"] == "Filed"


def test_a_failure_reading_the_calendar_never_fails_the_recording(door, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("calendar down")
    monkeypatch.setattr(closes.compliance_records_repo, "find_all", boom)
    out = payroll.record_remittance(CLIENT, _body(), current_user=USER)
    assert out["success"] is True and out["data"]["remittance"]["amount_paise"] == OWED
    only = out["data"]["compliance_obligations"]
    assert len(only) == 1 and only[0]["needs_action"] and "could not be updated" in only[0]["message"]


def test_recording_again_does_not_close_twice_or_change_the_filed_date(door):
    rec = _obligation()
    payroll.record_remittance(CLIENT, _body(), current_user=USER)
    again = payroll.record_remittance(CLIENT, _body(paid_on="2026-07-12"), current_user=USER)
    assert again["data"]["compliance_obligations"] == []
    assert _now(rec)["filed_date"] == "2026-07-10"
