"""A salary challan that names its wage month closes that month's salary TDS deposit obligation when the month's salary challans paid on
time what payroll deducted (POST-A-267, the salary half; migration 695).

WHAT WAS WRONG
    A client with a payroll engagement carries a `TDS_SALARY_DEPOSIT` obligation for every month on the compliance calendar, due by
    Rule 30(2)'s date. The salary tax is deposited on a challan recorded in the TDS register under section 192, and a challan carries a
    quarter and no month, so recording one never touched the calendar and a month paid on time read Overdue.

WHAT IS HELD
    * the door: a wage month only on a salary challan, only inside the challan's own quarter of its own year, and only as a month;
    * the rule: closed when payroll has a finalised run with tax for the month and the salary challans naming the month that were paid
      on or before the due date (30 April for March) carry at least that tax; the last punctual payment's date and serial are what
      the obligation records; a late challan counts for nothing; each way of failing leaves it open with its own sentence;
    * the closer over the fake database: only the named month's salary obligation moves, the challans that closed it are kept on it,
      another client's challan is not counted, a draft run closes nothing, a caller without compliance or payroll access is told;
    * the route: a salary challan recorded with a month closes it and says so; one recorded with no month says how to state one;
    * a retraction of a salary challan reopens the month it closed, and a non-salary challan's retraction leaves it alone.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from core.auth import get_current_user
from mock_data import MOCK_COMPLIANCE_RECORDS
from repositories.compliance_records_repository import compliance_records_repo
from services import tds_salary_deposit_closes_obligation as salary
from services.tds_salary_deposit_closes_obligation import Decision, decide, month_problem
from tests.e2e_harness import FakeDB

FIRM = "11111111-1111-4111-8111-111111111111"
CLIENT = "22222222-2222-4222-8222-222222222222"
OTHER_CLIENT = "33333333-3333-4333-8333-333333333333"
FY = "2025-26"
MANAGER = {"id": "u1", "firm_id": FIRM, "role": "Manager", "email": "manager@f1.test", "auth_user_id": "auth-manager"}
MONTH = "2025-07"
DUE = date(2025, 8, 7)
MONTH_START = date(2025, 7, 1)
AFTER = date(2025, 9, 1)
WHAT = "TDS deposit (salary) July 2025 obligation"
DEDUCTED = 25_000_00


# ── the door ────────────────────────────────────────────────────────────────

def test_a_month_inside_the_quarter_on_a_salary_challan_is_taken_and_blank_is_none():
    assert month_problem(deduction_month="2025-07", section="192", financial_year=FY, quarter="Q2") is None
    assert month_problem(deduction_month="2025-09", section="192", financial_year=FY, quarter="Q2") is None
    assert month_problem(deduction_month=None, section="194C", financial_year=FY, quarter="Q2") is None
    assert month_problem(deduction_month="  ", section="194C", financial_year=FY, quarter="Q2") is None


def test_a_month_on_a_non_salary_challan_is_refused_in_words():
    got = month_problem(deduction_month="2025-07", section="194C", financial_year=FY, quarter="Q2")
    assert got and "only on a salary challan" in got


@pytest.mark.parametrize("month", ["2025-06", "2025-10", "2026-07"])
def test_a_month_outside_the_challans_quarter_is_refused_naming_the_month(month):
    got = month_problem(deduction_month=month, section="192", financial_year=FY, quarter="Q2")
    assert got and "is not in Q2 of FY 2025-26" in got


def test_march_belongs_to_the_fourth_quarter_of_the_year_that_ends_in_it():
    assert month_problem(deduction_month="2026-03", section="192", financial_year=FY, quarter="Q4") is None


@pytest.mark.parametrize("month", ["2025-7", "2025-13", "July", "2025/07", "2025-07-01"])
def test_text_that_is_not_a_month_is_refused(month):
    got = month_problem(deduction_month=month, section="192", financial_year=FY, quarter="Q2")
    assert got and "YYYY-MM" in got


def test_the_request_model_refuses_a_month_on_another_section_and_keeps_one_on_a_salary_challan():
    from routers.tds_workspace import CreateChallanRequest
    base = dict(client_id=CLIENT, bsr_code="0510001", challan_date="2025-08-05", amount_paise=100, challan_no="1",
                financial_year=FY, quarter="Q2")
    with pytest.raises(PydanticValidationError):
        CreateChallanRequest(**base, section="194J", deduction_month="2025-07")
    assert CreateChallanRequest(**base, section="192", deduction_month=" 2025-07 ").deduction_month == "2025-07"
    assert CreateChallanRequest(**base, section="194J", deduction_month="").deduction_month is None


# ── the rule ────────────────────────────────────────────────────────────────

def _c(cid, tax, on, *, no=None, head="200", surcharge=0):
    return {"id": cid, "section": "192", "payment_date": on, "challan_no": no or cid, "tds_paise": tax, "surcharge_paise": surcharge,
            "minor_head": head, "deduction_month": MONTH}


def _decide(challans, **kw):
    base = dict(today=AFTER, due=DUE, month_start=MONTH_START, what=WHAT, deducted_paise=DEDUCTED, challans=challans)
    base.update(kw)
    return decide(**base)


def test_paid_in_full_on_time_closes_with_the_date_and_serial_and_the_challans_that_covered_it():
    got = _decide([_c("a", DEDUCTED, "2025-08-05", no="00042")])
    assert got == Decision(filed_on=date(2025, 8, 5), reference="00042", covering_ids=frozenset({"a"}))


def test_two_punctual_challans_that_together_pay_it_close_on_the_later_one():
    got = _decide([_c("a", 10_000_00, "2025-08-01"), _c("b", 15_000_00, "2025-08-06", no="00077")])
    assert got.filed_on == date(2025, 8, 6) and got.reference == "00077" and got.covering_ids == {"a", "b"}


def test_the_surcharge_on_the_challan_is_tax_and_counts():
    assert _decide([_c("a", DEDUCTED - 100, "2025-08-05", surcharge=100)]).filed_on == date(2025, 8, 5)


def test_the_due_date_itself_is_on_time_and_the_day_after_counts_for_nothing():
    assert _decide([_c("a", DEDUCTED, DUE.isoformat())]).filed_on == DUE
    late = _decide([_c("a", DEDUCTED, "2025-08-08")])
    assert late.filed_on is None
    assert "after the due date 2025-08-07 is not counted" in late.sentence and "Mark it filed from Compliance" in late.sentence


def test_march_tax_is_due_on_30_april_through_the_compliance_engine():
    from services import compliance_engine as ce
    assert ce.tds_deposit_due_date(2026, 3) == date(2026, 4, 30)


def test_one_paisa_short_closes_nothing_and_the_sentence_names_the_figures():
    got = _decide([_c("a", DEDUCTED - 1, "2025-08-05")])
    assert got.filed_on is None and "₹24,999.99" in got.sentence and "₹0.01" in got.sentence and "₹25,000" in got.sentence
    assert "Record the challan that paid the rest" in got.sentence


def test_a_late_challan_does_not_make_up_a_punctual_shortfall():
    got = _decide([_c("a", 20_000_00, "2025-08-05"), _c("b", 5_000_00, "2025-08-20")])
    assert got.filed_on is None and "₹5,000.00 less" in got.sentence


def test_each_other_way_of_failing_leaves_it_open_with_its_own_sentence():
    assert "no finalised run" in _decide([_c("a", DEDUCTED, "2025-08-05")], deducted_paise=None).sentence
    assert "deducted no tax" in _decide([_c("a", DEDUCTED, "2025-08-05")], deducted_paise=0).sentence
    assert "minor head 400" in _decide([_c("a", DEDUCTED, "2025-08-05", head="400")]).sentence
    assert "no payment date" in _decide([_c("a", DEDUCTED, None)]).sentence
    assert "has not happened yet" in _decide([_c("a", DEDUCTED, "2025-09-02")]).sentence
    assert "before the wage month began" in _decide([_c("a", DEDUCTED, "2025-06-30")]).sentence
    assert "come to ₹0" in _decide([]).sentence


def test_a_month_a_person_reopened_is_not_closed_again_on_the_same_challans_but_is_on_a_different_one():
    held = _decide([_c("a", DEDUCTED, "2025-08-05")], closed_on_before=frozenset({"a"}))
    assert held.filed_on is None and "a person reopened it" in held.sentence
    again = _decide([_c("a", DEDUCTED, "2025-08-05"), _c("b", 1_00, "2025-08-06")], closed_on_before=frozenset({"a"}))
    assert again.filed_on == date(2025, 8, 6)


# ── the closer over the fake database ───────────────────────────────────────

@pytest.fixture
def world(monkeypatch):
    import routers.tds_workspace as tw
    import core.supabase_client as sc
    import services.timeline_service as ts
    import services.audit_service as au
    MOCK_COMPLIANCE_RECORDS.clear()
    db = FakeDB()
    monkeypatch.setattr(tw, "_USE_MOCK", False)
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    monkeypatch.setattr(sc, "get_service_supabase", lambda: db)
    monkeypatch.setattr(tw.timeline_service, "log_timeline_event", lambda *a, **k: None)
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(au, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(tw.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    monkeypatch.setattr(salary, "ist_today", lambda: AFTER)
    # The route's own date check reads today in India; the challan dates below are in 2025, so they are in the past either way.
    state = {"user": dict(MANAGER)}
    app = FastAPI()
    app.include_router(tw.router)
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    yield TestClient(app, raise_server_exceptions=False), db, state
    MOCK_COMPLIANCE_RECORDS.clear()


def _run(db, *, status="finalized", tax=DEDUCTED, month=MONTH, client=CLIENT, slips=2):
    run = db.seed("payroll_runs", {"firm_id": FIRM, "client_id": client, "month": month, "status": status})
    for _ in range(slips):
        db.seed("payroll_slips", {"run_id": run["id"], "tds_paise": tax // slips})
    return run


def _obligation(month=MONTH, *, otype="TDS_SALARY_DEPOSIT", status="Not Started", client=CLIENT):
    y, m = int(month[:4]), int(month[5:7])
    return compliance_records_repo.create({
        "firm_id": FIRM, "client_id": client, "compliance_type": "Payroll", "obligation_type": otype,
        "period_label": f"TDS on salary {month}", "period_start": f"{month}-01", "period_end": f"{month}-28",
        "due_date": date(y + (m == 12), m % 12 + 1, 7).isoformat(), "status": status})


def _seed_challan(db, tax=DEDUCTED, *, on="2025-08-05", month=MONTH, client=CLIENT, section="192", no="00042"):
    return db.seed("tds_challans", {"firm_id": FIRM, "client_id": client, "section": section, "challan_no": no, "bsr_code": "0510001",
                                    "financial_year": FY, "quarter": "Q2", "tds_paise": tax, "surcharge_paise": 0, "interest_paise": 0,
                                    "penalty_paise": 0, "total_paise": tax, "payment_date": on, "minor_head": "200",
                                    "status": "deposited", "deduction_month": month})


def _close(db, challan, *, may_write=True, may_read=True):
    return salary.close_for_recorded_challan(db=db, firm_id=FIRM, client_id=CLIENT, challan=challan, actor=MANAGER,
                                             may_write_compliance=may_write, may_read_payroll=may_read)


def _now(rec):
    return compliance_records_repo.find_by_id(rec["id"])


def test_a_punctual_salary_challan_closes_only_its_months_salary_obligation_and_keeps_what_closed_it(world):
    _client, db, _s = world
    _run(db)
    july = _obligation()
    august = _obligation("2025-08")
    esi = _obligation(otype="ESI_DEPOSIT")
    c = _seed_challan(db)
    out = _close(db, c)
    assert out[0]["closed"] is True and out[0]["filed_on"] == "2025-08-05" and out[0]["reference"] == "00042"
    assert out[0]["needs_action"] is False and "TDS deposit (salary) July 2025" in out[0]["message"]
    assert _now(july)["status"] == "Filed" and _now(july)["closing_tds_challan_ids"] == [c["id"]]
    assert _now(august)["status"] == "Not Started" and _now(esi)["status"] == "Not Started"


def test_another_clients_challan_naming_the_month_is_not_counted(world):
    _client, db, _s = world
    _run(db)
    july = _obligation()
    _seed_challan(db, DEDUCTED, client=OTHER_CLIENT, no="THEIRS")
    mine = _seed_challan(db, 1_00, no="MINE")
    out = _close(db, mine)
    assert out[0]["state"] == "not_closed" and _now(july)["status"] == "Not Started"


def test_a_draft_run_closes_nothing(world):
    _client, db, _s = world
    _run(db, status="draft")
    july = _obligation()
    out = _close(db, _seed_challan(db))
    assert "no finalised run" in out[0]["message"] and _now(july)["status"] == "Not Started"


def test_a_salary_challan_with_no_month_says_how_to_state_one_and_a_non_salary_one_is_not_answered(world):
    _client, db, _s = world
    _run(db)
    july = _obligation()
    out = _close(db, _seed_challan(db, month=None))
    assert out[0]["needs_action"] is True and "names no wage month" in out[0]["message"] and "retract" in out[0]["message"]
    assert _close(db, _seed_challan(db, section="194C", month=None)) == []
    assert _now(july)["status"] == "Not Started"


def test_without_compliance_or_payroll_access_nothing_moves_and_no_payroll_figure_is_named(world):
    _client, db, _s = world
    _run(db)
    july = _obligation()
    c = _seed_challan(db, 1_00)
    assert "does not include Compliance" in _close(db, c, may_write=False)[0]["message"]
    no_payroll = _close(db, c, may_read=False)[0]["message"]
    assert "does not include payroll" in no_payroll and "₹" not in no_payroll
    assert _now(july)["status"] == "Not Started"


def test_a_month_with_no_obligation_is_told_so_without_being_asked_to_act_and_a_filed_one_is_not_answered(world):
    _client, db, _s = world
    _run(db)
    out = _close(db, _seed_challan(db))
    assert out[0]["state"] == "not_on_the_calendar" and out[0]["needs_action"] is False
    filed = _obligation(status="Filed")
    assert _close(db, _seed_challan(db, no="2")) == [] and _now(filed)["status"] == "Filed"


# ── the route and the retraction ────────────────────────────────────────────

def _body(**kw):
    base = dict(client_id=CLIENT, bsr_code="0510001", challan_date="2025-08-05", amount_paise=DEDUCTED, challan_no="00042",
                section="192", financial_year=FY, quarter="Q2", deduction_month=MONTH)
    base.update(kw)
    return base


def test_the_route_records_the_month_and_answers_what_became_of_the_obligation(world):
    client, db, _s = world
    _run(db)
    july = _obligation()
    res = client.post("/api/tds-workspace/challans", json=_body())
    data = res.json()["data"]
    assert res.status_code == 200 and data["deduction_month"] == MONTH
    assert data["compliance_obligations"][0]["closed"] is True and _now(july)["status"] == "Filed"


def test_the_route_refuses_a_month_outside_the_quarter_and_stores_nothing(world):
    client, db, _s = world
    res = client.post("/api/tds-workspace/challans", json=_body(deduction_month="2025-10"))
    assert res.status_code == 422
    assert db.rows("tds_challans") == []


def test_a_challan_recorded_without_a_month_is_written_without_the_column(world):
    """So the route keeps working in the minutes the API is live before migration 695 is."""
    client, db, _s = world
    res = client.post("/api/tds-workspace/challans", json=_body(section="194C", deduction_month=None))
    assert res.status_code == 200 and "deduction_month" not in res.json()["data"]


def test_retracting_the_salary_challan_reopens_the_month_it_closed_and_says_salary(world):
    client, db, _s = world
    _run(db)
    july = _obligation()
    non_salary = compliance_records_repo.create({
        "firm_id": FIRM, "client_id": CLIENT, "compliance_type": "TDS", "obligation_type": "TDS_NON_SALARY_DEPOSIT",
        "period_label": "TDS deposit 2025-07", "period_start": "2025-07-01", "period_end": "2025-07-31", "due_date": "2025-08-07",
        "status": "Filed"})
    recorded = client.post("/api/tds-workspace/challans", json=_body()).json()["data"]
    assert _now(july)["status"] == "Filed"
    out = client.post(f"/api/tds-workspace/challans/{recorded['id']}/retract", json={"reason": "Keyed under the wrong month"})
    data = out.json()["data"]
    assert data["reopened_obligation_ids"] == [july["id"]] and _now(july)["status"] != "Filed"
    assert "monthly TDS deposit (salary)" in data["calendar_note"] and "non-salary" not in data["calendar_note"]
    assert _now(non_salary)["status"] == "Filed"


def test_the_served_challan_sections_say_which_is_a_salary_deposit():
    """The screens offer the wage-month box from this flag and know no section themselves."""
    from domain.tds.section_labels import challan_sections
    for fy in ("2025-26", "2026-27"):
        flagged = {c["section"]: c["salary"] for c in challan_sections(fy)}
        assert flagged["192"] is True
        assert [s for s, salary in flagged.items() if salary] == ["192"]
