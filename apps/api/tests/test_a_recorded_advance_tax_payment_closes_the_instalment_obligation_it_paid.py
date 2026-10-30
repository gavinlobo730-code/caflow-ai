"""Advance tax saved in the income-tax register closes the instalment obligation it paid (POST-A-267, the advance-tax half).

WHAT WAS WRONG
    A client with an Advance Tax engagement carries four ADVANCE_TAX obligations on the compliance calendar and the register
    (`advance_tax_payments`, `POST /api/income-tax/advance-tax`) is where the payments are recorded. Recording one never
    touched the calendar, so four instalments paid and recorded read Overdue on Deadlines, the Compliance tab and the dashboard.
    It is the split the GST and ITR workspaces, the TDS statements and challans and the MCA filings had.

WHAT IS HELD
    * an instalment is paid when the cumulative tax paid ON OR BEFORE its due date reaches the cumulative percentage of the
      estimate that it requires, the measure the section 234C engine uses; the obligation is closed with the day the
      requirement was first reached and the challan number of the payment made that day;
    * a payment after the due date, one with no date, one in the future, a short one and an estimate of nothing close nothing;
      a short instalment whose date has passed and something was paid says by how much, and one that the whole sum would have
      covered had it been on time says that instead;
    * an instalment that is not due yet and short, and one that nothing was paid against, are not answered;
    * the obligation moves through `mark_filed`, only the instalment's own obligation moves (not another year's, another type's,
      or another client's), and one already Filed keeps its own date;
    * a presumptive assessee's lone 15 March instalment closes the 15 March obligation and the answer names the three earlier
      obligations as not required and left as they are;
    * no compliance access, a failure reading the calendar and a client with no advance-tax obligation never fail the saving;
    * `save_advance_tax` answers `{installments, compliance_obligations}` and the answer is the closer's.
"""
from __future__ import annotations

from datetime import date

import pytest

import routers.income_tax as it
from mock_data import MOCK_COMPLIANCE_RECORDS
from repositories.compliance_records_repository import compliance_records_repo
from services import advance_tax_closes_obligation as closes
from services.advance_tax_closes_obligation import Decision, Payment, decide_instalment

FIRM, CLIENT = "firm-1", "client-1"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}
FY = "2025-26"
LAKH = 1_00_000_00
DUE = {1: date(2025, 6, 15), 2: date(2025, 9, 15), 3: date(2025, 12, 15), 4: date(2026, 3, 15)}
PERCENT = {1: 15, 2: 45, 3: 75, 4: 100}
AFTER_THE_YEAR = date(2026, 4, 1)


@pytest.fixture
def world(monkeypatch):
    import services.audit_service as au
    import services.timeline_service as ts
    MOCK_COMPLIANCE_RECORDS.clear()
    monkeypatch.setattr(au, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(closes, "ist_today", lambda: AFTER_THE_YEAR)
    yield
    MOCK_COMPLIANCE_RECORDS.clear()


def _obligation(number, *, client=CLIENT, otype="ADVANCE_TAX", status="Not Started", due=None):
    due = (due or DUE[number]).isoformat()
    return compliance_records_repo.create({
        "firm_id": FIRM, "client_id": client, "compliance_type": "Income Tax", "obligation_type": otype,
        "period_label": f"Advance Tax {PERCENT[number]}% (FY {FY})", "period_start": due, "period_end": due, "due_date": due,
        "status": status})


def _all_four(**kw):
    return {n: _obligation(n, **kw) for n in (1, 2, 3, 4)}


def _now(rec):
    return compliance_records_repo.find_by_id(rec["id"])


def _row(number, paid=0, on=None, challan=None, *, estimate=LAKH):
    return {"installment_number": number, "due_date": DUE[number].isoformat(), "required_percent": PERCENT[number],
            "estimated_tax_paise": estimate, "paid_amount_paise": paid,
            "paid_date": on.isoformat() if on else None, "challan_number": challan}


def _close(rows, *, may_write=True, client=CLIENT):
    return closes.close_for_saved_register(
        firm_id=FIRM, client_id=client, financial_year=FY, rows=rows, actor=USER, may_write_compliance=may_write)


def _by_number(answers):
    return {a["instalment"]: a for a in answers if "instalment" in a}


# ── the rule ────────────────────────────────────────────────────────────────

def _decide(required, payments, *, due=DUE[1], today=AFTER_THE_YEAR, touched=True):
    return decide_instalment(label="The 15% instalment", due=due, required_paise=required, payments=payments, today=today,
                             touched=touched)


def test_the_requirement_met_on_the_due_date_closes_with_that_date_and_the_challan():
    got = _decide(15_000_00, [Payment(15_000_00, DUE[1], "CH-1")])
    assert got == Decision(filed_on=DUE[1], reference="CH-1")


def test_one_paisa_short_closes_nothing_and_the_exact_requirement_closes():
    """The boundary: the requirement is met when it is reached, not when it is nearly reached."""
    assert _decide(15_000_00, [Payment(15_000_00 - 1, DUE[1], "CH-1")]).filed_on is None
    assert _decide(15_000_00, [Payment(15_000_00, DUE[1], "CH-1")]).filed_on == DUE[1]


def test_two_payments_close_with_the_day_the_second_one_reached_the_requirement():
    got = _decide(15_000_00, [Payment(10_000_00, date(2025, 6, 2), "CH-1"), Payment(5_000_00, date(2025, 6, 9), "CH-2"),
                              Payment(9_000_00, date(2025, 6, 12), "CH-3")])
    assert got.filed_on == date(2025, 6, 9) and got.reference == "CH-2"


def test_the_last_challan_paid_that_day_is_the_reference():
    got = _decide(15_000_00, [Payment(10_000_00, date(2025, 6, 9), "CH-1"), Payment(5_000_00, date(2025, 6, 9), "CH-7")])
    assert got.reference == "CH-7"


def test_a_payment_after_the_due_date_meets_nothing_and_the_answer_says_the_total_would_have_covered_it():
    got = _decide(15_000_00, [Payment(15_000_00, date(2025, 6, 20), "CH-1")])
    assert got.filed_on is None
    assert "enough" in got.sentence and "₹15,000" in got.sentence and "only ₹0.00 was paid on or before" in got.sentence


def test_a_short_instalment_says_by_how_much():
    got = _decide(15_000_00, [Payment(9_000_00, date(2025, 6, 10), "CH-1")])
    assert got.filed_on is None
    assert "₹9,000" in got.sentence and "₹15,000" in got.sentence and "₹6,000" in got.sentence and "short" in got.sentence


def test_a_short_instalment_nothing_was_recorded_against_is_not_explained():
    """The cumulative total is the same on every later date, so a sentence about each would say one thing three times."""
    assert _decide(15_000_00, [Payment(9_000_00, date(2025, 6, 10), "CH-1")], touched=False) == Decision()
    assert _decide(15_000_00, [Payment(15_000_00, date(2025, 6, 20), "CH-1")], touched=False) == Decision()


def test_a_payment_with_no_date_counts_toward_nothing():
    got = _decide(15_000_00, [Payment(15_000_00, None, "CH-1")])
    assert got == Decision()


def test_a_payment_in_the_future_is_not_a_fact_yet_and_is_said():
    got = _decide(15_000_00, [Payment(15_000_00, date(2026, 6, 10), "CH-1")], due=date(2026, 6, 15), today=date(2026, 5, 1))
    assert got.filed_on is None and "has not come yet" in got.sentence


def test_a_short_instalment_that_is_not_due_yet_is_not_answered():
    assert _decide(15_000_00, [Payment(5_000_00, date(2025, 6, 1), None)], today=date(2025, 6, 10)) == Decision()


def test_an_instalment_due_today_is_not_yet_a_shortfall():
    assert _decide(15_000_00, [], today=DUE[1]) == Decision()


def test_nothing_recorded_after_the_due_date_is_not_answered_the_screens_already_say_overdue():
    assert _decide(15_000_00, []) == Decision()


def test_a_requirement_of_nothing_closes_nothing():
    assert _decide(0, [Payment(5_000_00, DUE[1], "CH-1")]) == Decision()


# ── the register ────────────────────────────────────────────────────────────

def test_paid_instalments_close_their_own_obligations_with_the_date_and_challan(world):
    ob = _all_four()
    rows = [_row(1, 15_000_00, date(2025, 6, 10), "CH-1"), _row(2, 30_000_00, date(2025, 9, 15), "CH-2"),
            _row(3, 30_000_00, date(2025, 12, 14), "CH-3"), _row(4, 25_000_00, date(2026, 3, 15), "CH-4")]
    answers = _by_number(_close(rows))
    assert all(answers[n]["closed"] for n in (1, 2, 3, 4)), answers
    assert answers[2]["filed_on"] == "2025-09-15" and answers[2]["reference"] == "CH-2"
    assert "check it against the challan" in answers[1]["message"]
    for n, rec in ob.items():
        now = _now(rec)
        assert now["status"] == "Filed", (n, now)
    assert _now(ob[1])["filed_date"] == "2025-06-10" and _now(ob[1])["acknowledgement_no"] == "CH-1"


def test_a_short_instalment_stays_open_and_a_later_payment_does_not_close_an_earlier_one(world):
    ob = _all_four()
    rows = [_row(1, 15_000_00, date(2025, 6, 10), "CH-1"), _row(2, 30_000_00, date(2025, 9, 15), "CH-2"),
            _row(3, 20_000_00, date(2025, 12, 20), "CH-3")]
    rows.append(_row(4))
    answers = _by_number(_close(rows))
    assert answers[1]["closed"] and answers[2]["closed"]
    assert not answers[3]["closed"] and answers[3]["needs_action"] and "short" in answers[3]["message"]
    assert "₹30,000" in answers[3]["message"] and "short" in answers[3]["message"]
    assert 4 not in answers            # nothing was recorded against the fourth: the screens already call it overdue
    assert _now(ob[3])["status"] == "Not Started" and _now(ob[4])["status"] == "Not Started"


def test_an_instalment_the_register_never_paid_anything_toward_is_not_answered(world):
    _all_four()
    answers = _close([_row(1), _row(2), _row(3), _row(4)])
    assert answers == []


def test_an_obligation_already_filed_keeps_its_own_date_and_is_not_answered(world):
    ob = _all_four()
    first = _now(ob[1])
    compliance_records_repo.update(first["id"], {"status": "Filed", "filed_date": "2025-06-12", "acknowledgement_no": "MINE"})
    answers = _by_number(_close([_row(1, 15_000_00, date(2025, 6, 10), "CH-1"), _row(2), _row(3), _row(4)]))
    assert 1 not in answers
    assert _now(ob[1])["filed_date"] == "2025-06-12" and _now(ob[1])["acknowledgement_no"] == "MINE"


def test_only_this_clients_this_years_advance_tax_obligations_move(world):
    mine = _all_four()
    other_client = _all_four(client="client-2")
    other_type = _obligation(1, otype="TDS_NON_SALARY_DEPOSIT")
    other_year = _obligation(1, due=date(2024, 6, 15))
    _close([_row(1, 15_000_00, date(2025, 6, 10), "CH-1"), _row(2), _row(3), _row(4)])
    assert _now(mine[1])["status"] == "Filed"
    assert all(_now(r)["status"] == "Not Started" for r in other_client.values())
    assert _now(other_type)["status"] == "Not Started" and _now(other_year)["status"] == "Not Started"


def test_without_compliance_access_nothing_closes_and_the_answer_says_so(world):
    ob = _all_four()
    answers = _close([_row(1, 15_000_00, date(2025, 6, 10), "CH-1"), _row(2), _row(3), _row(4)], may_write=False)
    assert [a["state"] for a in answers] == ["not_allowed"] and answers[0]["needs_action"]
    assert _now(ob[1])["status"] == "Not Started"


def test_without_compliance_access_and_nothing_to_close_nothing_is_said(world):
    _all_four()
    assert _close([_row(1), _row(2), _row(3), _row(4)], may_write=False) == []


def test_a_client_with_no_advance_tax_obligation_is_answered_nothing(world):
    assert _close([_row(1, 15_000_00, date(2025, 6, 10), "CH-1"), _row(2), _row(3), _row(4)]) == []


def test_an_estimate_of_nothing_closes_nothing(world):
    ob = _all_four()
    assert _close([_row(n, 5_000_00, DUE[n], "X", estimate=0) for n in (1, 2, 3, 4)]) == []
    assert all(_now(r)["status"] == "Not Started" for r in ob.values())


def test_a_presumptive_assessee_closes_the_15_march_obligation_and_is_told_about_the_earlier_three(world):
    ob = _all_four()
    answers = _close([_row(4, LAKH, date(2026, 3, 10), "CH-9")])
    assert _now(ob[4])["status"] == "Filed" and _now(ob[4])["filed_date"] == "2026-03-10"
    note = [a for a in answers if "instalment" not in a]
    assert len(note) == 1 and note[0]["needs_action"] and "§211(1) proviso" in note[0]["message"]
    assert "3 earlier" in note[0]["message"]
    assert all(_now(ob[n])["status"] == "Not Started" for n in (1, 2, 3))


def test_a_presumptive_assessee_is_not_told_about_earlier_obligations_already_filed(world):
    ob = _all_four(status="Filed")
    assert _close([_row(4, LAKH, date(2026, 3, 10), "CH-9")]) == []
    assert _now(ob[4])["status"] == "Filed"


def test_a_client_that_is_named_by_nobody_is_not_matched():
    out = closes.close_for_saved_register(firm_id="", client_id="", financial_year=FY, rows=[_row(1)], actor=USER,
                                          may_write_compliance=True)
    assert len(out) == 1 and out[0]["needs_action"] and "names no client" in out[0]["message"]


def test_an_empty_register_answers_nothing(world):
    assert _close([]) == []


# ── the door ────────────────────────────────────────────────────────────────

def _request(installments=(), estimate=LAKH, **kw):
    return it.SaveAdvanceTaxRequest(client_id=CLIENT, fy=FY, estimated_tax_paise=estimate,
                                    installments=list(installments), **kw)


def _inst(n, paid, on, challan):
    return it.AdvanceTaxInstallmentInput(installment_number=n, paid_amount_paise=paid, paid_date=on, challan_number=challan)


@pytest.fixture
def door(world, monkeypatch):
    monkeypatch.setattr(it, "assert_client_access", lambda user, client_id: None)
    monkeypatch.setattr(it, "_db", lambda: None)
    monkeypatch.setattr(it, "can_user", lambda user, resource, action: True)


def test_saving_the_register_answers_the_installments_and_what_became_of_the_obligations(door):
    ob = _all_four()
    out = it.save_advance_tax(_request([_inst(1, 15_000_00, date(2025, 6, 10), "CH-1")]), current_user=USER)
    assert out["success"] is True
    assert [r["installment_number"] for r in out["data"]["installments"]] == [1, 2, 3, 4]
    answers = out["data"]["compliance_obligations"]
    assert [a["instalment"] for a in answers] == [1] and answers[0]["closed"] is True
    assert _now(ob[1])["status"] == "Filed"


def test_a_failure_reading_the_calendar_never_fails_the_saving(door, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("calendar down")
    monkeypatch.setattr(closes.compliance_records_repo, "find_all", boom)
    out = it.save_advance_tax(_request([_inst(1, 15_000_00, date(2025, 6, 10), "CH-1")]), current_user=USER)
    assert out["success"] is True and len(out["data"]["installments"]) == 4
    only = out["data"]["compliance_obligations"]
    assert len(only) == 1 and only[0]["needs_action"] and "could not be updated" in only[0]["message"]


def test_saving_again_does_not_close_twice_or_change_the_filed_date(door):
    ob = _all_four()
    body = _request([_inst(1, 15_000_00, date(2025, 6, 10), "CH-1")])
    it.save_advance_tax(body, current_user=USER)
    again = it.save_advance_tax(body, current_user=USER)
    assert again["data"]["compliance_obligations"] == []
    assert _now(ob[1])["filed_date"] == "2025-06-10"
