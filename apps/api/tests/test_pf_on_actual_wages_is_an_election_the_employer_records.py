"""PF on ACTUAL wages above the ceiling is an election the employer records (payroll-22).

WHAT WAS WRONG
    `_compute_pf` capped the employee's 12% and the employer's 12% at the Rs 15,000
    ceiling for every employee, and `domain/payroll/ecr.py` capped the EPF wage on
    the ECR the same way. Many employers contribute on the whole wage — EPF Scheme
    1952 para 26(6) lets an employee and the employer jointly do so — and nothing
    on the employee master could say it. Their payroll under-deducted, their
    ledger under-accrued, and their return declared the wrong EPF wage.

[S] — THE LAW IS SECONDARY-SOURCED
    Egress is refused in this environment. Para 26(6), the EPS and EDLI ceilings
    and the base of the administrative charge are written from knowledge and
    pinned here so a later change is deliberate. `domain/payroll/
    pf_wage_election.VERIFIED` is False and the screen says so. Nothing is filed.

THE VERIFY LINE
    Basic Rs 40,000 with the election on: the employee share is Rs 4,800, the EPS
    contribution stays Rs 1,250, EDLI wages stay at Rs 15,000, and the ECR shows
    EPF wages of 40,000 and EPS wages of 15,000.

WHAT THIS PROVES, AND THE NEGATIVE CONTROLS (each mutant was run and these fail)
    * the verify line, end to end through the real run, the real ECR builder and
      the real journal builder                          — drop `on_actual_wages`
      from `_pf_for_slip`'s call and the verify-line tests fail
    * EPS and EDLI never follow the election           — make `_compute_pf`'s
      `eps_wages` or `edli` read `capped` and the ceiling-for-everyone tests and
      both properties fail
    * an employee with NO election computes EXACTLY what they computed before,
      across a matrix and as a property            — make NULL read as elected
      (`applies` returning True for `None`) and the matrix and the no-election
      property fail
    * the ECR's EPS and EDLI columns stay at the ceiling — uncap `eps_wages` in
      `build_ecr` and the ECR column tests fail
    * a member with no election produces a byte-identical ECR line — flag every
      slip and the byte-identity test fails
    * the election is read at compute time from the row, never cached on a run
"""
from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest
from fastapi import HTTPException
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

import routers.payroll as pr
from domain.payroll import ecr as ecr_domain
from domain.payroll import handoff as handoff_domain
from domain.payroll import pf_wage_election as election
from domain.payroll.statutory import rates_for
from models.payroll import EmployeeIn, EmployeeUpdateIn
from services import payslip_pdf_service
from services.phase2_journal_service import Phase2JournalService
from tests._property import kernel
from tests.e2e_harness import FakeDB, wire_e2e

API = Path(__file__).resolve().parents[1]
WEB = API.parent / "web"

# ── an oracle for what the product computed BEFORE this change ───────────────
#
# Written out longhand with literals rather than read from `statutory.py`, so a
# test of "nothing moved" cannot be passed by moving both sides, and the
# registry's own figures are pinned beside it below.
CEILING = 15_000_00


def _rupee(paise: int) -> int:
    return ((paise + 50) // 100) * 100


def before(wages: int, eps_eligible: bool = True) -> dict:
    """`_compute_pf` as it stood before payroll-22: everything capped."""
    capped = min(wages, CEILING)
    employee = _rupee(capped * 1200 // 10000)
    employer = _rupee(capped * 1200 // 10000)
    eps = min(_rupee(min(wages, CEILING) * 833 // 10000), employer)
    if not eps_eligible:
        eps = 0
    return {"employee": employee, "employer": employer, "employer_eps": eps,
            "employer_epf": employer - eps,
            "edli": _rupee(min(wages, CEILING) * 50 // 10000),
            "admin": _rupee(capped * 50 // 10000)}


def elected(wages: int, eps_eligible: bool = True) -> dict:
    """The same arithmetic with ONLY the EPF base (and the admin charge that
    follows it) moved to the whole wage."""
    employee = _rupee(wages * 1200 // 10000)
    employer = _rupee(wages * 1200 // 10000)
    eps = min(_rupee(min(wages, CEILING) * 833 // 10000), employer)
    if not eps_eligible:
        eps = 0
    return {"employee": employee, "employer": employer, "employer_eps": eps,
            "employer_epf": employer - eps,
            "edli": _rupee(min(wages, CEILING) * 50 // 10000),
            "admin": _rupee(wages * 50 // 10000)}


def _emp(**over) -> dict:
    base = dict(id="e1", name="Asha Kumar", uan="100200300400",
                basic_paise=40_000_00, hra_percent=0, da_percent=0,
                lta_paise=0, medical_paise=0, special_allowance_paise=0,
                other_allowances_paise=0, pf_applicable=True, eps_eligible=True,
                esi_applicable=False, pt_applicable=False,
                joining_date="2018-04-01", gratuity_act_covered=True)
    base.update(over)
    return base


def _slip(emp: dict, fy: str = "2026-27", month: int = 12) -> dict:
    return pr._compute_slip(emp, fy=fy, pt_month=month)


PF_KEYS = ("pf_employee_paise", "pf_employer_paise", "pf_employer_eps_paise",
           "pf_employer_epf_paise", "edli_paise", "pf_admin_paise",
           "pf_wages_paise", "pf_wages_addback_paise", "pf_wages_rule_applied")


def test_the_oracle_is_the_registrys_own_figures():
    """The literals above are the registry's, so 'nothing moved' is asserted
    against numbers somebody can read, and a registry change fails here first."""
    r = rates_for("2026-27").pf
    assert (r.wage_ceiling_paise, r.eps_ceiling_paise, r.edli_ceiling_paise) == (
        CEILING, CEILING, CEILING)
    assert (r.employee_rate_bps, r.employer_rate_bps, r.eps_rate_bps,
            r.edli_rate_bps, r.admin_rate_bps) == (1200, 1200, 833, 50, 50)


# ═════════════════════════════════════════════════════════════════════════════
# THE VERIFY LINE
# ═════════════════════════════════════════════════════════════════════════════

def test_the_verify_line_on_a_payslip():
    """Basic Rs 40,000, election on: Rs 4,800 employee, EPS Rs 1,250, EDLI on
    Rs 15,000 (so Rs 75)."""
    slip = _slip(_emp(pf_on_actual_wages=True))
    assert slip["pf_employee_paise"] == 4_800_00
    assert slip["pf_employer_paise"] == 4_800_00
    assert slip["pf_employer_eps_paise"] == 1_250_00
    assert slip["pf_employer_epf_paise"] == 3_550_00
    assert slip["edli_paise"] == 75_00           # 0.5% of 15,000, not of 40,000
    assert slip["pf_admin_paise"] == 200_00      # 0.5% of the EPF wage [S]
    assert slip["pf_wages_paise"] == 40_000_00
    assert slip["pf_on_actual_wages"] is True


def test_the_same_employee_without_the_election_is_capped():
    slip = _slip(_emp())
    assert slip["pf_employee_paise"] == 1_800_00
    assert slip["pf_employer_eps_paise"] == 1_250_00
    assert slip["pf_employer_epf_paise"] == 550_00
    assert slip["edli_paise"] == 75_00
    assert slip["pf_admin_paise"] == 75_00
    assert slip["pf_on_actual_wages"] is False


def test_the_verify_line_on_the_ecr():
    """EPF wages 40,000, EPS wages 15,000, EDLI wages 15,000 — and the line is
    the file's own format."""
    emp = _emp(pf_on_actual_wages=True)
    slip = {**_slip(emp), "employee_id": "e1"}
    f = ecr_domain.build_ecr(
        slips=[slip], employees_by_id={"e1": emp}, days_in_month=31,
        wage_ceiling_paise=CEILING, employee_rate_bps=1200)
    assert f.problems == []
    m = f.members[0]
    assert (m.epf_wages, m.eps_wages, m.edli_wages) == (40_000, 15_000, 15_000)
    assert m.eps_contribution == 1_250
    assert m.on_actual_wages is True
    # The contribution columns follow the file's existing convention (employee
    # plus the employer's EPF half) — unchanged by the election.
    assert f.to_text() == ecr_domain.DELIMITER.join([
        "100200300400", "ASHA KUMAR", "40000", "40000", "15000", "15000",
        "8350", "1250", "7100", "0", "0"])


def test_eps_wages_and_edli_wages_stay_at_the_ceiling_for_every_wage():
    for wages in (14_999_00, 15_000_00, 15_000_01, 40_000_00, 5_00_000_00):
        emp = _emp(basic_paise=wages, pf_on_actual_wages=True)
        slip = {**_slip(emp), "employee_id": "e1"}
        f = ecr_domain.build_ecr(
            slips=[slip], employees_by_id={"e1": emp}, days_in_month=31,
            wage_ceiling_paise=CEILING, employee_rate_bps=1200)
        assert f.problems == [], wages
        m = f.members[0]
        assert m.eps_wages <= 15_000 and m.edli_wages <= 15_000, wages
        assert m.epf_wages == wages // 100, wages


# ═════════════════════════════════════════════════════════════════════════════
# NOTHING ELSE MOVES — a matrix and a property
# ═════════════════════════════════════════════════════════════════════════════

NO_ELECTION_STATES = [
    pytest.param({}, id="no keys at all (every row that exists today)"),
    pytest.param({"pf_on_actual_wages": None}, id="NULL"),
    pytest.param({"pf_on_actual_wages": False}, id="withdrawn"),
    pytest.param({"pf_on_actual_wages": "yes"}, id="a truthy string is not an election"),
    pytest.param({"pf_on_actual_wages": 1}, id="a 1 is not an election"),
    pytest.param({"pf_on_actual_wages": True, "pf_on_actual_wages_from": "2099-01-01"},
                 id="elected from a date after the month"),
    pytest.param({"pf_on_actual_wages": True, "pf_on_actual_wages_from": "not-a-date"},
                 id="elected from a date nobody can read"),
]
BASICS = [1_000_00, 14_999_00, 15_000_00, 15_000_01, 15_001_00, 40_000_00, 5_00_000_00]


@pytest.mark.parametrize("basic", BASICS)
@pytest.mark.parametrize("state", NO_ELECTION_STATES)
@pytest.mark.parametrize("eps_eligible", [True, False])
def test_an_employee_with_no_election_computes_exactly_what_they_did_before(
        basic, state, eps_eligible):
    """THE REGRESSION PIN. Every figure on the slip, not just PF — and against
    both the oracle of the old arithmetic and the slip of the same employee with
    the election keys absent altogether."""
    plain = _emp(basic_paise=basic, eps_eligible=eps_eligible)
    keyed = _emp(basic_paise=basic, eps_eligible=eps_eligible, **state)
    a, b = _slip(plain), _slip(keyed)
    assert a == {**b, "pf_on_actual_wages": False} == {**a, "pf_on_actual_wages": False}
    assert b["pf_on_actual_wages"] is False
    old = before(basic, eps_eligible)
    assert (b["pf_employee_paise"], b["pf_employer_paise"],
            b["pf_employer_eps_paise"], b["pf_employer_epf_paise"],
            b["edli_paise"], b["pf_admin_paise"]) == (
        old["employee"], old["employer"], old["employer_eps"],
        old["employer_epf"], old["edli"], old["admin"])


@pytest.mark.parametrize("basic", [1_000_00, 14_999_00, 15_000_00])
def test_at_or_below_the_ceiling_the_election_changes_nothing(basic):
    """Elected or not, a wage that does not reach the ceiling is the same
    contribution — min() of a smaller figure is that figure."""
    on = _slip(_emp(basic_paise=basic, pf_on_actual_wages=True))
    off = _slip(_emp(basic_paise=basic))
    assert {k: on[k] for k in PF_KEYS} == {k: off[k] for k in PF_KEYS}


@kernel()
@given(wages=st.integers(min_value=0, max_value=10 ** 10),
       eps_eligible=st.booleans())
def test_property_no_election_is_the_old_arithmetic_for_any_wage(wages, eps_eligible):
    got = pr._compute_pf(wages, "2026-27", eps_eligible=eps_eligible)
    assert got == before(wages, eps_eligible)
    assert got == pr._compute_pf(wages, "2026-27", eps_eligible=eps_eligible,
                                 on_actual_wages=False)


@kernel()
@given(wages=st.integers(min_value=0, max_value=10 ** 10),
       eps_eligible=st.booleans())
def test_property_the_election_moves_only_the_epf_base(wages, eps_eligible):
    """Employee, employer, the EPF half and the admin charge follow the whole
    wage; EPS and EDLI are the old figures at every wage. And the elected
    figure is never LESS than the capped one."""
    got = pr._compute_pf(wages, "2026-27", eps_eligible=eps_eligible,
                         on_actual_wages=True)
    assert got == elected(wages, eps_eligible)
    capped = before(wages, eps_eligible)
    assert got["employer_eps"] == capped["employer_eps"]
    assert got["edli"] == capped["edli"]
    assert got["employee"] >= capped["employee"]
    assert got["admin"] >= capped["admin"]
    assert got["employer_eps"] + got["employer_epf"] == got["employer"]
    assert got["employer_eps"] <= 1_250_00
    assert got["employer_epf"] >= 0


def test_an_employee_without_eps_puts_the_whole_employer_share_in_epf():
    """GSR 609(E): no pension membership, so the whole 12% goes to EPF — and
    with the election that is 12% of the whole wage."""
    slip = _slip(_emp(pf_on_actual_wages=True, eps_eligible=False))
    assert slip["pf_employer_eps_paise"] == 0
    assert slip["pf_employer_epf_paise"] == slip["pf_employer_paise"] == 4_800_00


def test_the_rule_itself_says_pf_off_beats_an_election():
    """Asked of `applies` directly, not only through the slip, whose own
    pf_applicable gate would otherwise hide a weakening of the rule."""
    emp = _emp(pf_applicable=False, pf_on_actual_wages=True)
    assert election.applies(emp, fy_label="2026-27", month=12) is False
    assert election.applies({**emp, "pf_applicable": True},
                            fy_label="2026-27", month=12) is True


def test_pf_not_applicable_beats_an_election_and_the_slip_does_not_claim_one():
    slip = _slip(_emp(pf_applicable=False, pf_on_actual_wages=True))
    assert slip["pf_employee_paise"] == 0 and slip["pf_admin_paise"] == 0
    assert slip["pf_on_actual_wages"] is False


# ═════════════════════════════════════════════════════════════════════════════
# BOTH PERIODS — the election rides the SAME wage base the capped path uses
# ═════════════════════════════════════════════════════════════════════════════

def test_before_the_codes_the_uncapped_base_is_basic_plus_da_only():
    """October 2025 is EPF Act s.6. 40,000 of basic with 20,000 of special
    allowance contributes on 40,000 — never on the 60,000 the later definition
    would reach. The pre-commencement branch keeps its own figure."""
    emp = _emp(special_allowance_paise=20_000_00, pf_on_actual_wages=True)
    slip = _slip(emp, fy="2025-26", month=10)
    assert slip["pf_wages_rule_applied"] is False
    assert slip["pf_wages_paise"] == 40_000_00
    assert slip["pf_employee_paise"] == 4_800_00


def test_after_commencement_it_is_the_section_2_88_aggregate():
    emp = _emp(special_allowance_paise=20_000_00, pf_on_actual_wages=True)
    slip = _slip(emp, fy="2025-26", month=12)
    assert slip["pf_wages_rule_applied"] is True
    assert slip["pf_wages_paise"] == 60_000_00
    assert slip["pf_employee_paise"] == 7_200_00


def test_the_election_and_the_ceiling_agree_with_the_capped_path_on_the_same_base():
    """Same employee, same month: the capped slip's wage base is the elected
    slip's wage base. Only the cap differs."""
    for fy, month in (("2025-26", 10), ("2025-26", 12), ("2026-27", 6)):
        base = _emp(special_allowance_paise=20_000_00, hra_percent=20)
        a = _slip(base, fy, month)
        b = _slip({**base, "pf_on_actual_wages": True}, fy, month)
        assert a["pf_wages_paise"] == b["pf_wages_paise"], (fy, month)
        assert a["pf_wages_addback_paise"] == b["pf_wages_addback_paise"]
        assert b["pf_employee_paise"] == _rupee(b["pf_wages_paise"] * 1200 // 10000)


# ═════════════════════════════════════════════════════════════════════════════
# THE DATE THE ELECTION TAKES EFFECT
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("from_date,fy,month,applies", [
    ("2026-10-15", "2026-27", 9, False),    # the month ends before the request
    ("2026-10-15", "2026-27", 10, True),    # a month is paid as ONE thing
    ("2026-10-31", "2026-27", 10, True),    # the last day of its own month
    ("2026-11-01", "2026-27", 10, False),   # the day after
    ("2026-10-15", "2026-27", 11, True),
    ("2026-10-15", "2026-27", 2, True),     # February belongs to the NEXT calendar year
    ("2027-03-01", "2026-27", 2, False),
    (None, "2026-27", 4, True),             # no date: every month
    ("", "2026-27", 4, True),
])
def test_a_month_ending_before_the_date_stays_capped(from_date, fy, month, applies):
    emp = _emp(pf_on_actual_wages=True, pf_on_actual_wages_from=from_date)
    assert election.applies(emp, fy_label=fy, month=month) is applies
    slip = _slip(emp, fy, month)
    assert slip["pf_on_actual_wages"] is applies
    assert slip["pf_employee_paise"] == (4_800_00 if applies else 1_800_00)


def test_a_month_that_cannot_be_placed_is_not_guessed_into_an_election():
    emp = _emp(pf_on_actual_wages=True, pf_on_actual_wages_from="2026-10-01")
    for fy, month in ((None, 12), ("2026-27", None), ("2026-27", 13), ("junk", 5)):
        assert election.applies(emp, fy_label=fy, month=month) is False


def test_the_election_is_read_off_the_row_every_time_and_cached_nowhere():
    """PAY-21: a draft recomputed after the election is recorded, dated or
    withdrawn picks up exactly what the row says now."""
    row = _emp()
    assert _slip(row)["pf_employee_paise"] == 1_800_00
    row["pf_on_actual_wages"] = True
    assert _slip(row)["pf_employee_paise"] == 4_800_00
    row["pf_on_actual_wages_from"] = "2027-01-01"
    assert _slip(row)["pf_employee_paise"] == 1_800_00
    row["pf_on_actual_wages_from"] = None
    row["pf_on_actual_wages"] = False
    assert _slip(row)["pf_employee_paise"] == 1_800_00
    params = set(inspect.signature(pr._compute_slip).parameters)
    assert not any("elect" in p or "actual" in p for p in params), (
        "_compute_slip must take the election from the employee row it is "
        "given, not from a parameter a caller could cache")


def test_the_run_header_carries_no_election():
    """A run is a month of slips, and the election is a fact about an employee.
    Nothing may be added to payroll_runs for it."""
    sql = (API / "migrations" /
           "477_pf_on_actual_wages_is_an_election_the_employer_records.sql").read_text()
    code = "\n".join(l for l in sql.splitlines() if not l.lstrip().startswith("--"))
    assert "payroll_runs" not in code


# ═════════════════════════════════════════════════════════════════════════════
# THE REAL RUN, THE REAL ECR, THE REAL JOURNAL
# ═════════════════════════════════════════════════════════════════════════════

FIRM = "FIRM-PF22"
CALLER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "auth-1",
          "email": "ca@f.test", "role": "Partner"}
ACCOUNTS = {"salary_exp": "A-EXP", "net": "A-NET", "pf": "A-PF", "esi": "A-ESI",
            "pt": "A-PT", "tds": "A-TDS", "loans": "A-LOAN",
            "employer_contribution": "A-CONTRIB"}


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [pr])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": "CLI", "firm_id": FIRM,
                       "financial_year_start": "2026-04-01"})
    d.seed("client_payroll_settings", {"id": "cps-1", "firm_id": FIRM,
                                       "client_id": "CLI", "payroll_enabled": True})
    return d


def _seed_employee(db, emp_id, name, basic, **kw):
    row = {"id": emp_id, "firm_id": FIRM, "client_id": "CLI", "name": name,
           "uan": "1002003004" + emp_id[-2:], "basic_paise": basic,
           "hra_percent": 0.0, "da_percent": 0.0, "other_allowances_paise": 0,
           "lta_paise": 0, "medical_paise": 0, "special_allowance_paise": 0,
           "pf_applicable": True, "eps_eligible": True, "esi_applicable": False,
           "pt_applicable": False, "is_active": True, "status": "active"}
    row.update(kw)
    return db.seed("payroll_employees", row)


def _run(db, month="2026-12"):
    out = pr.create_run(pr.PayrollRunIn(client_id="CLI", month=month), CALLER)
    assert out["success"] is True
    return out["data"]["id"]


def _slips(db, run_id):
    return {s["employee_id"]: s for s in db.rows("payroll_slips")
            if s["run_id"] == run_id}


def _roster(db):
    _seed_employee(db, "e-01", "Elected Ek", 40_000_00, pf_on_actual_wages=True)
    _seed_employee(db, "e-02", "Capped Do", 40_000_00)
    _seed_employee(db, "e-03", "Below Teen", 10_000_00, pf_on_actual_wages=True)
    _seed_employee(db, "e-04", "No Pension Char", 40_000_00,
                   pf_on_actual_wages=True, eps_eligible=False)


def test_a_real_run_stores_what_it_applied(db):
    _roster(db)
    slips = _slips(db, _run(db))
    assert slips["e-01"]["pf_employee_paise"] == 4_800_00
    assert slips["e-01"]["pf_on_actual_wages"] is True
    assert slips["e-02"]["pf_employee_paise"] == 1_800_00
    assert slips["e-02"]["pf_on_actual_wages"] is False
    assert slips["e-03"]["pf_employee_paise"] == 1_200_00        # below the ceiling
    assert slips["e-04"]["pf_employer_eps_paise"] == 0


def test_the_run_totals_carry_the_larger_contribution_and_the_admin_floor(db):
    _roster(db)
    run_id = _run(db)
    run = [r for r in db.rows("payroll_runs") if r["id"] == run_id][0]
    slips = _slips(db, run_id).values()
    assert run["total_pf_paise"] == sum(
        s["pf_employee_paise"] + s["pf_employer_paise"] for s in slips)
    assert run["total_edli_paise"] == sum(s["edli_paise"] for s in slips)
    assert run["total_pf_admin_paise"] == max(
        sum(s["pf_admin_paise"] for s in slips), 500_00)


def test_recomputing_a_draft_after_the_election_changed_reads_the_row_now(db):
    """PAY-21 through the real door. The election is withdrawn after the draft
    was made; the recompute is capped and the slip says so."""
    _roster(db)
    run_id = _run(db)
    assert _slips(db, run_id)["e-01"]["pf_employee_paise"] == 4_800_00
    for row in db.rows("payroll_employees"):
        if row["id"] == "e-01":
            row["pf_on_actual_wages"] = False
    pr.recompute_run(run_id, CALLER)
    again = _slips(db, run_id)["e-01"]
    assert again["pf_employee_paise"] == 1_800_00
    assert again["pf_on_actual_wages"] is False


def test_the_journal_foots_with_an_elected_employee_and_carries_the_employer_share(db):
    """PAY-25's identity — gross + contribution == the payable credits — holds
    when the employer share is larger, and the share is summed off the slips."""
    _roster(db)
    run_id = _run(db)
    run = [r for r in db.rows("payroll_runs") if r["id"] == run_id][0]
    contribution = Phase2JournalService._payroll_employer_contribution(db, run)
    slips = _slips(db, run_id).values()
    assert contribution == (sum(s["pf_employer_paise"] + s["esi_employer_paise"]
                                for s in slips)
                            + run["total_edli_paise"] + run["total_pf_admin_paise"])
    lines = Phase2JournalService._build_payroll_lines(ACCOUNTS, run, contribution)
    assert (sum(l["debit_paise"] for l in lines)
            == sum(l["credit_paise"] for l in lines))
    # 4,800 + 1,800 + 1,200 + 4,800 of employer PF, none of it capped for the
    # three elected members above the ceiling.
    assert sum(s["pf_employer_paise"] for s in slips) == 12_600_00
    pf_credit = sum(l["credit_paise"] for l in lines if l["account_id"] == "A-PF")
    assert pf_credit == (run["total_pf_paise"] + run["total_edli_paise"]
                         + run["total_pf_admin_paise"])


def _finalise_and_build(db, run_id):
    for row in db.rows("payroll_runs"):
        if row["id"] == run_id:
            row["status"] = "finalized"
    return pr._build_run_ecr(db, CALLER, run_id)


def test_the_ecr_of_a_real_run_declares_each_member_as_the_slip_says(db):
    _roster(db)
    run_id = _run(db)
    _run_row, _month, f = _finalise_and_build(db, run_id)
    assert f.problems == []
    by_name = {m.name: m for m in f.members}
    assert by_name["ELECTED EK"].epf_wages == 40_000
    assert by_name["ELECTED EK"].eps_wages == 15_000
    assert by_name["ELECTED EK"].edli_wages == 15_000
    assert by_name["CAPPED DO"].epf_wages == 15_000
    assert by_name["BELOW TEEN"].epf_wages == 10_000
    assert by_name["NO PENSION CHAR"].eps_wages == 0       # excluded from EPS
    assert by_name["NO PENSION CHAR"].epf_wages == 40_000
    t = f.totals()
    assert t["members_on_actual_wages"] == 3
    assert t["edli_wages"] == 15_000 + 15_000 + 10_000 + 15_000


def test_the_ecr_declares_what_the_slip_applied_not_what_the_row_says_today(db):
    """The row can change after a month is finalised. The return is of what was
    remitted."""
    _roster(db)
    run_id = _run(db)
    for row in db.rows("payroll_employees"):
        row["pf_on_actual_wages"] = False             # withdrawn since
    _r, _m, f = _finalise_and_build(db, run_id)
    assert f.problems == []
    assert {m.name: m.epf_wages for m in f.members}["ELECTED EK"] == 40_000

    # And the other way: elected since, but the month was computed capped.
    for row in db.rows("payroll_employees"):
        row["pf_on_actual_wages"] = True
    for slip in db.rows("payroll_slips"):
        slip["pf_on_actual_wages"] = False
    _r, _m, f = _finalise_and_build(db, run_id)
    # Capped slips carry capped contributions, so the capped line is consistent
    # and nothing is refused.
    assert {m.name: m.epf_wages for m in f.members}["CAPPED DO"] == 15_000


# ═════════════════════════════════════════════════════════════════════════════
# THE ECR: byte-identical without an election, refusals with one
# ═════════════════════════════════════════════════════════════════════════════

def _ecr(slips, emps, **kw):
    return ecr_domain.build_ecr(
        slips=slips, employees_by_id={e["id"]: e for e in emps},
        days_in_month=31, wage_ceiling_paise=CEILING, **kw)


@pytest.mark.parametrize("basic", BASICS)
def test_a_member_with_no_election_files_a_byte_identical_line(basic):
    emp = _emp(basic_paise=basic)
    slip = {**_slip(emp), "employee_id": "e1"}
    now = _ecr([slip], [emp], employee_rate_bps=1200)
    # The same slip with the flag key REMOVED, as every slip written before the
    # election existed is, and with no rate supplied, as every caller written
    # before it does.
    legacy = {k: v for k, v in slip.items() if k != "pf_on_actual_wages"}
    then = _ecr([legacy], [emp])
    assert now.problems == then.problems == []
    assert now.to_text() == then.to_text()
    m = now.members[0]
    assert m.epf_wages == min(basic // 100, 15_000)
    assert m.on_actual_wages is False


def test_an_election_beside_pf_off_is_refused_by_the_ecr_and_named():
    emp = _emp(pf_applicable=False, pf_on_actual_wages=True)
    slip = {**_slip(_emp()), "employee_id": "e1"}
    f = _ecr([slip], [emp], employee_rate_bps=1200)
    assert f.members == []
    assert any("PF does not apply" in p and "Asha Kumar" in p for p in f.problems)
    assert not f.is_filable


def test_that_refusal_is_asked_before_the_never_contributory_skip():
    """With PF off and nothing contributed a member is normally 'not a member'
    and skipped in silence. An election beside it must not be hidden by that."""
    emp = _emp(pf_applicable=False, pf_on_actual_wages=True)
    nil = {"employee_id": "e1", "pf_employee_paise": 0, "pf_employer_paise": 0}
    f = _ecr([nil], [emp], employee_rate_bps=1200)
    assert len(f.problems) == 1


def test_a_slip_that_says_actual_wages_but_holds_no_pf_wage_is_refused():
    emp = _emp(pf_on_actual_wages=True)
    slip = {**_slip(emp), "employee_id": "e1", "pf_wages_paise": None}
    f = _ecr([slip], [emp], employee_rate_bps=1200)
    assert f.members == []
    assert any("does not hold the PF wage" in p for p in f.problems)


def test_a_declared_wage_the_contribution_does_not_follow_is_refused():
    """A slip flagged elected whose contribution is the capped one: the file
    would declare 40,000 of EPF wages against 1,800 of contribution."""
    emp = _emp(pf_on_actual_wages=True)
    capped = _slip(_emp())
    slip = {**capped, "employee_id": "e1", "pf_on_actual_wages": True}
    f = _ecr([slip], [emp], employee_rate_bps=1200)
    assert f.members == []
    assert any("not 12% of that" in p for p in f.problems)


def test_the_tie_out_is_one_rupee_wide_because_the_file_is_whole_rupees():
    emp = _emp(pf_on_actual_wages=True)
    slip = {**_slip(emp), "employee_id": "e1",
            "pf_wages_paise": 40_000_99}               # paise the file cannot carry
    f = _ecr([slip], [emp], employee_rate_bps=1200)
    assert f.problems == []


def test_the_tie_out_is_skipped_where_no_rate_is_supplied():
    """Every caller written before payroll-22 passes none and behaves as before."""
    emp = _emp(pf_on_actual_wages=True)
    capped = _slip(_emp())
    slip = {**capped, "employee_id": "e1", "pf_on_actual_wages": True}
    assert _ecr([slip], [emp]).problems == []


def test_the_ecr_route_supplies_the_rate_from_the_registry():
    src = inspect.getsource(pr._build_run_ecr)
    assert "employee_rate_bps=pf_rates.employee_rate_bps" in src


def test_the_ecr_employee_select_names_the_election_column():
    src = inspect.getsource(pr._finalised_run_inputs)
    assert "pf_on_actual_wages" in src


# ═════════════════════════════════════════════════════════════════════════════
# THE HANDOFF
# ═════════════════════════════════════════════════════════════════════════════

def _epf(totals):
    return handoff_domain.epf_obligation(
        wage_month="2026-12", due_date="2027-01-15", establishment_code="X",
        identity_gaps=[], file_totals=totals, edli_paise=0, admin_paise=0,
        problems=[], filable=True, filename="x.txt", blocking_months=[],
        sequence_note=None, required_returns=["regular"],
        return_type_reason=None, interest_note=None)


BASE_TOTALS = {"members": 12, "gross_wages": 6_00_000, "epf_wages": 1_80_000,
               "eps_wages": 1_80_000, "epf_contribution": 30_000,
               "eps_contribution": 15_000}


def test_a_month_with_no_election_reads_exactly_as_it_did():
    plain = _epf(BASE_TOTALS)
    labels = [f.label for f in plain.confirm]
    assert "Total EDLI wages" not in labels
    epf = [f for f in plain.confirm if f.label == "Total EPF wages"][0]
    assert epf.note == "what the portal computes A/c 1 and A/c 21 from"
    assert not any("actual wages" in w for w in plain.warnings)
    # a zero count is the same as the key being absent
    zero = _epf({**BASE_TOTALS, "members_on_actual_wages": 0, "edli_wages": 0})
    assert [f.to_dict() for f in zero.confirm] == [f.to_dict() for f in plain.confirm]
    assert zero.warnings == plain.warnings


def test_a_month_with_an_election_says_how_many_and_what_stays_at_the_ceiling():
    ob = _epf({**BASE_TOTALS, "members_on_actual_wages": 2, "edli_wages": 90_000})
    labels = [f.label for f in ob.confirm]
    assert labels.index("Total EDLI wages") == labels.index("Total EPS wages") + 1
    edli = [f for f in ob.confirm if f.label == "Total EDLI wages"][0]
    assert edli.rupees == 90_000
    epf = [f for f in ob.confirm if f.label == "Total EPF wages"][0]
    assert "A/c 21" in epf.note and "stay at the ceiling" in epf.note
    warning = [w for w in ob.warnings if "actual wages" in w]
    assert len(warning) == 1
    assert "2 member(s)" in warning[0] and "unverified" in warning[0]


# ═════════════════════════════════════════════════════════════════════════════
# THE ROW AND ITS TWO DOORS
# ═════════════════════════════════════════════════════════════════════════════

def _create(**kw):
    return EmployeeIn(client_id="CLI", name="Asha", **kw)


def test_the_create_door_accepts_a_recorded_election():
    e = _create(pf_on_actual_wages=True, pf_on_actual_wages_from="2026-10-01",
                pf_on_actual_wages_reference="  Joint request dated   04-10-2026 ")
    assert e.pf_on_actual_wages is True
    assert e.pf_on_actual_wages_from == "2026-10-01"
    assert e.pf_on_actual_wages_reference == "Joint request dated 04-10-2026"


def test_the_create_door_defaults_to_nothing_recorded():
    e = _create()
    assert (e.pf_on_actual_wages, e.pf_on_actual_wages_from,
            e.pf_on_actual_wages_reference) == (None, None, None)


@pytest.mark.parametrize("model,kw", [
    (EmployeeIn, dict(client_id="CLI", name="A", pf_on_actual_wages=True,
                      pf_on_actual_wages_from="01/10/2026")),
    (EmployeeUpdateIn, dict(pf_on_actual_wages_from="01/10/2026")),
    (EmployeeIn, dict(client_id="CLI", name="A", pf_on_actual_wages=True,
                      pf_on_actual_wages_from="1926-10-01")),
    (EmployeeUpdateIn, dict(pf_on_actual_wages_from="1926-10-01")),
    (EmployeeIn, dict(client_id="CLI", name="A", pf_on_actual_wages=True,
                      pf_on_actual_wages_reference="x" * 201)),
    (EmployeeUpdateIn, dict(pf_on_actual_wages_reference="x" * 201)),
])
def test_both_doors_refuse_a_malformed_date_and_a_long_reference(model, kw):
    """A validator only at the create door is one PATCH from being none."""
    with pytest.raises(ValidationError):
        model(**kw)


def test_the_create_door_refuses_an_election_for_an_employee_without_pf():
    with pytest.raises(ValidationError) as e:
        _create(pf_applicable=False, pf_on_actual_wages=True)
    assert "PF is not applicable" in str(e.value)


@pytest.mark.parametrize("kw", [
    dict(pf_on_actual_wages_from="2026-10-01"),
    dict(pf_on_actual_wages_reference="a reference"),
    dict(pf_on_actual_wages=False, pf_on_actual_wages_from="2026-10-01"),
])
def test_the_create_door_refuses_a_date_or_reference_without_an_election(kw):
    with pytest.raises(ValidationError) as e:
        _create(**kw)
    assert "not recorded as made" in str(e.value)


def test_the_update_door_refuses_what_the_request_alone_contradicts():
    with pytest.raises(ValidationError):
        EmployeeUpdateIn(pf_applicable=False, pf_on_actual_wages=True)
    with pytest.raises(ValidationError):
        EmployeeUpdateIn(pf_on_actual_wages=False, pf_on_actual_wages_from="2026-10-01")


def test_a_blank_date_or_reference_on_update_means_clear_and_survives_exclude_none():
    """PATCH cannot send a null, so a blank is sent as "" and must not be
    dropped on the way — or the old date would stay in place."""
    sent = EmployeeUpdateIn(pf_on_actual_wages_from="",
                            pf_on_actual_wages_reference="  ").model_dump(exclude_none=True)
    assert sent == {"pf_on_actual_wages_from": "", "pf_on_actual_wages_reference": ""}


def test_every_create_field_of_the_election_is_on_the_update_model_too():
    for key in election.ALL_KEYS:
        assert key in EmployeeIn.model_fields
        assert key in EmployeeUpdateIn.model_fields


STORED = {"pf_applicable": True, "pf_on_actual_wages": None,
          "pf_on_actual_wages_from": None, "pf_on_actual_wages_reference": None}
STORED_ELECTED = {"pf_applicable": True, "pf_on_actual_wages": True,
                  "pf_on_actual_wages_from": "2026-10-01",
                  "pf_on_actual_wages_reference": "ref"}


@pytest.mark.parametrize("stored,patch,ok", [
    (STORED, {"name": "x"}, True),                                  # not touched at all
    (STORED, {"pf_on_actual_wages": True}, True),
    (STORED, {"pf_on_actual_wages": True, "pf_on_actual_wages_from": "2026-10-01"}, True),
    (STORED, {"pf_on_actual_wages_from": "2026-10-01"}, False),     # date, no election
    (STORED, {"pf_applicable": False}, True),
    ({**STORED, "pf_applicable": False}, {"pf_on_actual_wages": True}, False),
    (STORED_ELECTED, {"pf_applicable": False}, False),              # PF off beside election
    (STORED_ELECTED, {"pf_applicable": False, "pf_on_actual_wages": False}, True),
    (STORED_ELECTED, {"pf_on_actual_wages": False}, True),          # withdrawal
    (STORED_ELECTED, {"pf_on_actual_wages_from": ""}, True),        # clear the date
    (STORED_ELECTED, {"pf_on_actual_wages": False,
                      "pf_on_actual_wages_from": "2027-01-01"}, False),
    ({**STORED, "pf_on_actual_wages": False}, {"pf_on_actual_wages_reference": "r"}, False),
])
def test_a_patch_is_judged_against_the_row_it_lands_on(stored, patch, ok):
    plan = election.plan_update(stored, patch)
    assert (plan.problems == []) is ok, plan.problems


def test_withdrawing_an_election_clears_its_date_and_reference_with_it():
    plan = election.plan_update(STORED_ELECTED, {"pf_on_actual_wages": False})
    assert plan.changes == {"pf_on_actual_wages_from": None,
                            "pf_on_actual_wages_reference": None}


def test_a_patch_that_touches_nothing_of_the_election_never_reads_the_row():
    assert election.needs_stored_row({"name": "x", "pf_applicable": True}) is False
    assert election.needs_stored_row({"pf_applicable": False}) is True
    assert election.needs_stored_row({"pf_on_actual_wages_reference": "r"}) is True


# ── through the real routes ──────────────────────────────────────────────────

def test_create_without_an_election_never_names_the_election_columns(db):
    out = pr.create_employee(_create(), CALLER)
    assert out["success"] is True
    row = db.rows("payroll_employees")[0]
    assert not any(k in row for k in election.ALL_KEYS)


def test_create_with_an_election_writes_it_and_logs_who_recorded_it(db):
    out = pr.create_employee(
        _create(pf_on_actual_wages=True, pf_on_actual_wages_from="2026-10-01",
                pf_on_actual_wages_reference="ref-1"), CALLER)
    emp = out["data"]
    assert emp["pf_on_actual_wages"] is True
    log = [r for r in db.rows("audit_log")
           if (r.get("metadata") or {}).get("what") == "pf_on_actual_wages_election"]
    assert len(log) == 1
    assert log[0]["actor_id"] == "auth-1"             # the AUTH id, not users.id
    assert log[0]["new_data"]["pf_on_actual_wages_reference"] == "ref-1"
    assert log[0]["old_data"] is None


def test_patch_records_then_withdraws_and_the_log_keeps_the_old_values(db):
    _seed_employee(db, "e-01", "Asha", 40_000_00)
    pr.update_employee("e-01", EmployeeUpdateIn(
        pf_on_actual_wages=True, pf_on_actual_wages_from="2026-10-01",
        pf_on_actual_wages_reference="ref-1"), CALLER)
    row = db.rows("payroll_employees")[0]
    assert (row["pf_on_actual_wages"], row["pf_on_actual_wages_from"]) == (
        True, "2026-10-01")

    pr.update_employee("e-01", EmployeeUpdateIn(pf_on_actual_wages=False), CALLER)
    row = db.rows("payroll_employees")[0]
    assert row["pf_on_actual_wages"] is False
    assert row["pf_on_actual_wages_from"] is None
    assert row["pf_on_actual_wages_reference"] is None

    log = [r for r in db.rows("audit_log")
           if (r.get("metadata") or {}).get("what") == "pf_on_actual_wages_election"]
    assert len(log) == 2
    withdrawal = log[-1]
    assert withdrawal["old_data"]["pf_on_actual_wages_reference"] == "ref-1"
    assert withdrawal["new_data"]["pf_on_actual_wages"] is False


def test_patch_refuses_pf_off_beside_a_recorded_election_in_a_sentence(db):
    _seed_employee(db, "e-01", "Asha", 40_000_00, pf_on_actual_wages=True)
    with pytest.raises(HTTPException) as e:
        pr.update_employee("e-01", EmployeeUpdateIn(pf_applicable=False), CALLER)
    assert e.value.status_code == 422
    assert "PF is not applicable" in e.value.detail
    assert db.rows("payroll_employees")[0]["pf_applicable"] is True    # nothing written


def test_patch_allows_pf_off_together_with_the_withdrawal(db):
    _seed_employee(db, "e-01", "Asha", 40_000_00, pf_on_actual_wages=True)
    pr.update_employee("e-01", EmployeeUpdateIn(
        pf_applicable=False, pf_on_actual_wages=False), CALLER)
    row = db.rows("payroll_employees")[0]
    assert (row["pf_applicable"], row["pf_on_actual_wages"]) == (False, False)


def test_patch_refuses_a_date_on_an_election_that_is_not_made(db):
    _seed_employee(db, "e-01", "Asha", 40_000_00)
    with pytest.raises(HTTPException) as e:
        pr.update_employee("e-01", EmployeeUpdateIn(
            pf_on_actual_wages_from="2026-10-01"), CALLER)
    assert e.value.status_code == 422
    assert "not recorded as made" in e.value.detail


def test_an_ordinary_patch_never_reads_or_writes_the_election_and_logs_nothing(db):
    _seed_employee(db, "e-01", "Asha", 40_000_00)
    pr.update_employee("e-01", EmployeeUpdateIn(designation="Analyst"), CALLER)
    assert not [r for r in db.rows("audit_log")
                if (r.get("metadata") or {}).get("what") == "pf_on_actual_wages_election"]
    assert "pf_on_actual_wages" not in db.rows("payroll_employees")[0]


def test_the_import_refuses_a_row_that_switches_pf_off_for_an_elected_employee(db):
    _seed_employee(db, "e-01", "Asha", 40_000_00, employee_code="EMP001",
                   pf_on_actual_wages=True)
    out = pr._pf_election_conflicts_in_import(
        db, FIRM, [("e-01", {"pf_applicable": False}),
                   ("e-09", {"pf_applicable": True})])
    assert len(out) == 1 and "EMP001" in out[0] and "Withdraw the election" in out[0]
    assert pr._pf_election_conflicts_in_import(
        db, FIRM, [("e-01", {"pf_applicable": True})]) == []


# ═════════════════════════════════════════════════════════════════════════════
# THE PROJECTION AGREES WITH THE RUN
# ═════════════════════════════════════════════════════════════════════════════

def _position(db, month="2026-12"):
    resp = pr.statutory_position(client_id="CLI", month=month, current_user=CALLER)
    assert resp["success"] is True
    return {r["employee_id"]: r for r in resp["data"]["rows"]}


def test_the_projection_and_the_run_agree_for_an_elected_employee(db):
    _roster(db)
    projected = _position(db)
    run_id = _run(db)
    slips = _slips(db, run_id)
    for emp_id in ("e-01", "e-02", "e-03", "e-04"):
        for field in ("pf_employee_paise", "pf_employer_paise",
                      "pf_employer_eps_paise", "pf_employer_epf_paise",
                      "edli_paise", "pf_admin_paise"):
            assert projected[emp_id][field] == slips[emp_id][field], (emp_id, field)
    assert projected["e-01"]["pf_on_actual_wages"] is True
    assert projected["e-02"]["pf_on_actual_wages"] is False


def test_once_a_run_exists_the_screen_reads_the_flag_off_the_slip(db):
    _roster(db)
    run_id = _run(db)
    for row in db.rows("payroll_employees"):
        row["pf_on_actual_wages"] = False             # withdrawn since the run
    rows = _position(db)
    assert rows["e-01"]["pf_on_actual_wages"] is True
    assert rows["e-01"]["pf_employee_paise"] == _slips(db, run_id)["e-01"]["pf_employee_paise"]


def test_both_callers_go_through_the_one_helper():
    tree = ast.parse(inspect.getsource(pr))
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for caller in ("_compute_slip", "statutory_position"):
        called = {c.func.id for c in ast.walk(fns[caller])
                  if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        assert "_pf_for_slip" in called, caller
        assert "_compute_pf" not in called, (
            f"{caller} calls _compute_pf itself — two copies of 'does this "
            f"employee's election apply this month' drift")


# ═════════════════════════════════════════════════════════════════════════════
# WHAT AN EMPLOYEE AND A CA READ
# ═════════════════════════════════════════════════════════════════════════════

def test_the_payslip_says_so_on_the_same_row_and_only_for_an_elected_slip():
    plain = payslip_pdf_service.deduction_lines(_slip(_emp()))
    elected_rows = payslip_pdf_service.deduction_lines(
        _slip(_emp(pf_on_actual_wages=True)))
    assert len(plain[0]) == len(elected_rows[0])          # no extra row: no page break moves
    assert plain[0][1][0] == "Provident Fund (Employee)"
    assert "on actual wages" in elected_rows[0][1][0]
    assert "employer's election" in elected_rows[0][1][0]


def _tsx(rel: str) -> str:
    return (WEB / rel).read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.replace("&apos;", "'").split())


def test_the_screens_notice_is_the_servers_wording_character_for_character():
    """A guard written in apps/web would assert the form against a copy of
    itself. This pins it from the side that owns the sentence."""
    form = _flat(_tsx("components/payroll/AddEmployeeModal.tsx"))
    assert _flat(election.SCREEN_NOTICE) in form


def test_the_notice_says_the_three_things_the_employer_must_be_told():
    n = election.SCREEN_NOTICE
    assert "this product does not check that the request exists" in n.lower()
    assert "that is for the employer to establish" in n
    assert "unverified" in n
    assert "not modelled" in n
    assert "EPF Scheme 1952, para 26(6)" in n


def test_the_form_sends_the_election_the_way_the_server_reads_it():
    form = _tsx("components/payroll/AddEmployeeModal.tsx")
    for needle in ("pf_on_actual_wages: true", "pf_on_actual_wages: false",
                   "pf_on_actual_wages_from: form.pf_on_actual_wages_from",
                   "pf_on_actual_wages_reference: form.pf_on_actual_wages_reference.trim()"):
        assert needle in form, needle
    # shown only where PF applies, and never inferred from a wage
    assert "form.pf_applicable && (" in form
    assert not re.search(r"pf_on_actual_wages\s*[:=]\s*[^,;\n]*basic", form)


def test_the_payslip_and_the_statutory_screen_label_what_the_server_stored():
    page = _tsx("app/payroll/page.tsx")
    assert "slip.pf_on_actual_wages" in page
    assert "PF on actual wages (elected)" in page
    statutory = _tsx("app/payroll/statutory/page.tsx")
    assert "r.pf_on_actual_wages" in statutory


def test_the_not_modelled_list_names_the_higher_pension_option():
    text = " ".join(election.NOT_MODELLED)
    assert "higher-pension" in text and "para 11(3)" in text
    assert "all or nothing" in text
    assert election.VERIFIED is False


def test_every_statute_figure_here_is_graded_secondary_in_the_module():
    src = (API / "domain" / "payroll" / "pf_wage_election.py").read_text()
    assert "[S]" in src and "VERIFIED = False" in src
    assert "para 26(6)" in src


# ═════════════════════════════════════════════════════════════════════════════
# WHO MAY WRITE IT, AND WHERE — a rule over the tree, not a list of today's files
# ═════════════════════════════════════════════════════════════════════════════

def _py_files_mentioning(token: str) -> set[str]:
    out = set()
    for path in API.rglob("*.py"):
        rel = path.relative_to(API).as_posix()
        if rel.startswith(("tests/", ".venv", "venv/")) or "__pycache__" in rel:
            continue
        if token in path.read_text(encoding="utf-8", errors="ignore"):
            out.add(rel)
    return out


def test_the_set_of_backend_files_that_know_the_election_is_exactly_these():
    """The domain rule, its two doors' model, the payroll router (which writes
    it at create and PATCH, reads it at compute and for the ECR) and the ECR and
    payslip renderers that read what a slip stored (the handoff reads only the
    ECR's own totals). A new file mentioning the column is a new door and has to
    be added here on purpose."""
    assert _py_files_mentioning("pf_on_actual_wages") == {
        "domain/payroll/pf_wage_election.py",
        "domain/payroll/ecr.py",
        "models/payroll.py",
        "routers/payroll.py",
        "services/payslip_pdf_service.py",
    }


def test_only_the_two_employee_routes_write_the_election_and_both_need_payroll_write():
    """The control is reachable only with the permission the employee edit
    already needs: `rbac("payroll", "write")` on both doors, and no other route
    handler in the router mentions the election's keys at all."""
    source = (API / "routers" / "payroll.py").read_text()
    tree = ast.parse(source)
    handlers = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for name in ("create_employee", "update_employee"):
        defaults = [ast.unparse(d).replace("'", '"') for d in handlers[name].args.defaults]
        assert any('rbac("payroll", "write")' in d for d in defaults), name

    allowed = {"create_employee", "update_employee", "_log_pf_election_change",
               "_pf_election_conflicts_in_import", "_pf_for_slip", "_compute_pf",
               "_compute_slip", "statutory_position", "_finalised_run_inputs",
               "_build_run_ecr", "import_employees"}
    offenders = []
    for fn in handlers.values():
        body = ast.get_source_segment(source, fn) or ""
        if ("pf_on_actual_wages" in body or "pf_election." in body) and fn.name not in allowed:
            offenders.append(fn.name)
    assert offenders == [], offenders


def test_in_the_browser_only_the_employee_form_sends_the_election():
    """Every other screen reads what the server stored and labels it."""
    sends = re.compile(r"pf_on_actual_wages(_from|_reference)?\s*:\s*(true|false|form\.)")
    writers = set()
    for root in ("app", "components", "lib"):
        for path in (WEB / root).rglob("*.ts*"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if sends.search(text):
                writers.add(path.relative_to(WEB).as_posix())
    assert writers == {"components/payroll/AddEmployeeModal.tsx"}


def test_the_three_states_have_names_and_only_a_real_true_is_an_election():
    assert election.state_of(None) == "unrecorded"
    assert election.state_of(False) == "withdrawn"
    assert election.state_of(True) == "elected"
    assert election.state_of("true") == "unrecorded"      # not a boolean, not an election


def test_a_date_arrives_as_a_date_object_or_a_timestamp_as_readily_as_a_string():
    """PostgREST sends a string; a driver or a test double may send an object.
    All three mean the same day, and none is guessed at."""
    from datetime import date, datetime
    for from_ in ("2026-12-31", date(2026, 12, 31), datetime(2026, 12, 31, 18, 30)):
        emp = _emp(pf_on_actual_wages=True, pf_on_actual_wages_from=from_)
        assert election.applies(emp, fy_label="2026-27", month=12) is True
        assert election.applies(emp, fy_label="2026-27", month=11) is False
    assert election.applies(_emp(pf_on_actual_wages=True,
                                 pf_on_actual_wages_from=20261231),
                            fy_label="2026-27", month=12) is False   # an int is no date


def test_the_cleaners_take_blank_none_and_objects():
    from datetime import date, datetime
    assert election.clean_effective_from(None) is None
    assert election.clean_effective_from("   ") is None
    assert election.clean_effective_from(date(2026, 10, 1)) == "2026-10-01"
    assert election.clean_effective_from(datetime(2026, 10, 1, 9, 0)) == "2026-10-01"
    assert election.clean_reference(None) is None
    assert election.clean_reference(" \t\n ") is None
    assert election.clean_reference("a\x00b\n  c") == "a b c"        # controls become spaces
    assert election.clean_reference("x" * 200) == "x" * 200


def test_the_employee_importer_does_not_set_the_election():
    """It is an assertion somebody makes about one employee. The import takes no
    such column (and the browser's column list, which a parity test holds equal
    to this one, takes none either)."""
    from domain.payroll import employee_import
    names = {c for c, _ in employee_import.COLUMNS}
    assert not any("pf_on_actual" in n or "actual_wage" in n for n in names)
