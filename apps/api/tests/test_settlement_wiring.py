"""
The leaver's settlement, wired: recorded, withheld on, posted, and reaching
Form 16.

WHAT THIS FILE IS ABOUT

Before migration 302 the settlement computed correctly and NOTHING CONSUMED IT
— no ledger entry, no withholding, no §17(1) for the year. The 1 September
walk-through called that the largest remaining gap in the module. These tests
pin each end of the wire.
"""
from datetime import date

import pytest

import routers.payroll as pr
from domain.payroll import settlement as S, gratuity as G, leave_encashment as L
from domain.payroll.annexure2 import build_annexure_ii
from services.phase2_journal_service import Phase2JournalService

CLIENT = "11111111-1111-1111-1111-111111111111"
EMPLOYEE = "22222222-2222-2222-2222-222222222222"
USER = {"id": "u1", "firm_id": "f1", "auth_user_id": "a1", "role": "Partner"}


# ── The tax head each component belongs on ───────────────────────────────────

def _settlement():
    g = G.compute(basic_plus_da_paise=50_000 * 100,
                  joining=date(2015, 4, 1), leaving=date(2025, 9, 30),
                  amount_actually_paid_paise=5_00_000 * 100)
    l = L.compute(amount_received_paise=1_50_000 * 100,
                  average_monthly_salary_paise=50_000 * 100,
                  completed_years_of_service=10, leave_days_encashed=60,
                  on_retirement=True)
    return S.build(salary_to_last_day_paise=50_000 * 100, gratuity=g, leave=l)


def test_leave_encashment_is_17_1_because_the_statute_says_so():
    """§17(1)(va) expressly makes "any payment received by an employee in
    respect of any period of leave not availed of by him" SALARY. That settles
    it rather than practice settling it."""
    c = next(c for c in _settlement().components if c.label == "Leave encashment")
    assert c.tax_head == S.HEAD_17_1
    assert c.exempt_section == "10(10AA)"


def test_gratuity_is_17_3_as_a_termination_payment():
    c = next(c for c in _settlement().components if c.label == "Gratuity")
    assert c.tax_head == S.HEAD_17_3
    assert c.exempt_section == "10(10)"


def test_the_heads_and_exemptions_reconcile_to_the_taxable_total():
    """Whatever the presentation, income chargeable must come out the same."""
    s = _settlement()
    by_head = s.gross_by_head(S.HEAD_17_1) + s.gross_by_head(S.HEAD_17_3)
    assert by_head == s.gross_paise
    assert by_head - s.exempt_paise == s.taxable_paise
    assert sum(s.exempt_by_section().values()) == s.exempt_paise


def test_the_exemption_breakup_names_its_clauses():
    """The annexure's §10 line wants a breakup by section, not one number."""
    assert set(_settlement().exempt_by_section()) == {"10(10)", "10(10AA)"}


# ── The ledger ───────────────────────────────────────────────────────────────

def _lines(**over):
    st = {"gross_paise": 7_00_000_00, "tds_paise": 50_000_00,
          "loan_recovery_paise": 20_000_00, "cost_reductions_paise": 50_000_00,
          "net_paid_paise": 5_80_000_00, "employee_name": "A Nair"}
    st.update(over)
    ids = {"salary_exp": "exp", "net": "net", "tds": "tds", "loans": "loans"}
    return Phase2JournalService._build_settlement_lines(ids, st)


def test_the_settlement_journal_balances():
    lines = _lines()
    assert sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines)


def test_a_recovery_reduces_the_cost_but_a_loan_gets_its_own_credit():
    """Notice pay recovered reduces what the departure cost the employer. A LOAN
    recovery is different: the employee owed the money, so collecting it
    extinguishes a receivable rather than reducing a cost."""
    lines = _lines()
    debit = next(l for l in lines if l["debit_paise"])
    assert debit["debit_paise"] == 7_00_000_00 - 50_000_00     # less the recovery
    loan = next(l for l in lines if l["account_id"] == "loans")
    assert loan["credit_paise"] == 20_000_00


def test_an_unbalanced_settlement_raises_rather_than_posting():
    """The debit is the employer's cost and the credits are where it went. If
    they disagree a component was mis-composed — defining one from the other
    would post a balanced-but-wrong entry, which is how the payroll accrual's
    own bug stayed hidden."""
    with pytest.raises(ValueError, match="does not balance"):
        _lines(net_paid_paise=1_00_000_00)


def test_no_loan_account_is_needed_when_nothing_was_recovered():
    """A firm whose chart predates migration 301 must still be able to settle a
    leaver who owes nothing."""
    lines = _lines(loan_recovery_paise=0, net_paid_paise=6_00_000_00)
    assert not [l for l in lines if l["account_id"] == "loans"]
    assert sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines)


# ── Form 16: the far end of the wire ─────────────────────────────────────────

def _slip(**over):
    base = dict(employee_id="e1", basic_paise=50_000_00, hra_paise=20_000_00,
                da_paise=0, lta_paise=0, medical_paise=0,
                special_allowance_paise=0, other_allowances_paise=0,
                pt_paise=200_00, tds_paise=5_000_00)
    base.update(over)
    return base


def test_a_settlement_reaches_the_annexure_that_becomes_form_16():
    """THE point of this work. Before it, a settlement was computed, shown, and
    never reached anyone's Form 16 — a CA re-keyed the taxable part by hand."""
    settled = {"gross_17_1_paise": 2_00_000_00, "gross_17_3_paise": 5_00_000_00,
               "exempt_paise": 3_88_461_53, "tds_paise": 40_000_00}
    a = build_annexure_ii(
        slips=[_slip()] * 6,
        employees_by_id={"e1": {"id": "e1", "name": "Asha Kumar",
                                "pan": "ABCDE1234F"}},
        standard_deduction_paise=75_000_00,
        months_expected=6,
        settlements_by_employee={"e1": settled})
    r = a.rows[0]

    # Six months of payslips plus the settlement's §17(1) half.
    assert r.salary_17_1_paise == 6 * 70_000_00 + 2_00_000_00
    # Gratuity on its own line.
    assert r.profits_in_lieu_17_3_paise == 5_00_000_00
    # The §10 exemptions come off, and the TDS is added to the year's.
    assert r.exempt_under_10_paise == 3_88_461_53
    assert r.tds_deducted_paise == 6 * 5_000_00 + 40_000_00

    assert r.gross_salary_paise == r.salary_17_1_paise + 5_00_000_00
    assert r.net_salary_paise == r.gross_salary_paise - 3_88_461_53


def test_an_employee_with_no_settlement_is_unchanged():
    plain = build_annexure_ii(
        slips=[_slip()] * 12,
        employees_by_id={"e1": {"id": "e1", "name": "Asha Kumar",
                                "pan": "ABCDE1234F"}},
        standard_deduction_paise=75_000_00)
    r = plain.rows[0]
    assert r.profits_in_lieu_17_3_paise == 0
    assert r.salary_17_1_paise == 12 * 70_000_00
    assert r.tds_deducted_paise == 12 * 5_000_00


# ── The endpoint ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    monkeypatch.setattr(pr, "_db", lambda: None)
    monkeypatch.setattr(pr, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(pr, "assert_not_internal_for_payroll", lambda *a, **k: None)


def test_record_settlement_is_callable():
    body = pr.SettlementRecordIn(client_id=CLIENT, leaving_date="2026-09-30")
    assert pr.record_settlement(EMPLOYEE, body, USER)["success"]


def test_record_settlement_refuses_a_status_that_is_not_a_departure():
    from fastapi import HTTPException
    body = pr.SettlementRecordIn(client_id=CLIENT, leaving_date="2026-09-30",
                                 new_status="on holiday")
    with pytest.raises(HTTPException) as e:
        pr.record_settlement(EMPLOYEE, body, USER)
    assert e.value.status_code == 422


def test_record_settlement_refuses_a_malformed_leaving_date():
    from fastapi import HTTPException
    body = pr.SettlementRecordIn(client_id=CLIENT, leaving_date="last Tuesday")
    with pytest.raises(HTTPException) as e:
        pr.record_settlement(EMPLOYEE, body, USER)
    assert e.value.status_code == 422


def test_preview_and_record_compose_through_the_same_path():
    """Two computations would drift, and the drift would be invisible: a CA
    would approve one set of figures on screen and a different set would reach
    the ledger."""
    import inspect
    for fn in (pr.preview_settlement, pr.record_settlement):
        assert "_compose_settlement" in inspect.getsource(fn)
