"""PAY-23 — the statutory bonus register for a whole accounting year.

`domain/payroll/bonus.py` has implemented the Payment of Bonus Act 1965 since
the payroll module was built and its ONLY caller was a leaver's settlement. So
a client's continuing employees — all of them, most years — were never computed
for, while §10 makes the minimum payable "whether or not the employer has any
allocable surplus", §19 makes it due within eight months of the year's close
and §28 makes non-payment an offence.

What these tests hold:

  1. §19's date is DERIVED from the year's own close, not stated.
  2. Every employee appears, including the ones the Act does not reach, each
     with its own reason — a register that drops them cannot be checked.
  3. The three refusals: the rate is the employer's, §12's minimum wage is a
     human step, and an unrecorded working-day count is neither nil nor thirty.
  4. §9's grounds are the Act's five and nothing else.
  5. The service reads §2(21) salary, RELEASED runs and days ACTUALLY worked —
     and each of those is a different column from the obvious wrong one.
"""
import uuid
from decimal import Decimal

import pytest

from domain.payroll import bonus as bonus_domain
from domain.payroll import bonus_register as br
from services import bonus_register_service as svc


FIRM = "firm-1"
CLIENT = "client-1"
YEAR = "2025-26"


def _emp(eid, name, salary_paise, months=12, days=280, **over):
    return {"employee_id": eid, "name": name,
            "monthly_salary_paise": salary_paise,
            "months_worked": months, "working_days": days, **over}


# ── 1. §19 ──────────────────────────────────────────────────────────────────

def test_the_due_date_is_eight_months_from_the_years_close():
    # 31 March 2026 plus eight months is 30 November 2026.
    assert br.due_date("2025-26") == "2026-11-30"
    assert br.due_date("2026-27") == "2027-11-30"


def test_the_due_date_is_derived_rather_than_stated():
    # Two consecutive years must differ by a year, which a literal could not
    # do wrongly but a hardcoded month/day pair would hide.
    import inspect
    src = inspect.getsource(br.due_date)
    assert "11, 30" not in src and '"11-30"' not in src, (
        "the date is derived from the year's own close, so a client whose "
        "accounting year is not the financial year gets their own date")


def test_the_proviso_is_named_rather_than_assumed():
    reg = br.build(accounting_year=YEAR, employees=[])
    assert any("two years" in n for n in reg.notes), (
        "§19's proviso allows an extension on application — the date shown is "
        "the unextended one and says so")


# ── 2. every employee appears ───────────────────────────────────────────────

def test_an_employee_above_the_2_13_ceiling_appears_with_its_reason():
    reg = br.build(accounting_year=YEAR,
                   employees=[_emp("e1", "Bala", 25_000_00)])
    line = reg.employees[0]
    assert line.eligible is False
    assert line.payable_paise == 0
    assert any("§2(13)" in r for r in line.reasons)
    assert reg.excluded_count == 1 and reg.eligible_count == 0


def test_an_employee_short_of_thirty_working_days_appears_with_its_reason():
    reg = br.build(accounting_year=YEAR,
                   employees=[_emp("e1", "Asha", 15_000_00, months=1, days=12)])
    line = reg.employees[0]
    assert line.eligible is False
    assert any("§8" in r for r in line.reasons)


def test_the_totals_count_only_the_eligible():
    reg = br.build(accounting_year=YEAR, employees=[
        _emp("e1", "Asha", 15_000_00),
        _emp("e2", "Bala", 25_000_00),          # above the ceiling
    ])
    assert reg.eligible_count == 1 and reg.excluded_count == 1
    assert reg.total_payable_paise == reg.employees[0].payable_paise


def test_the_12_ceiling_caps_the_base_at_7000_and_not_the_salary():
    # ₹15,000 a month for twelve months, computed on ₹7,000: 84,000 x 8.33%.
    reg = br.build(accounting_year=YEAR,
                   employees=[_emp("e1", "Asha", 15_000_00)])
    line = reg.employees[0]
    assert line.calculation_base_monthly_paise == 7_000_00
    assert line.payable_paise == 6_997_20


def test_a_minimum_wage_above_7000_raises_the_base():
    # §12 is "₹7,000 OR the minimum wage, WHICHEVER IS HIGHER" — reading it as
    # a flat ₹7,000 underpays by a third in a state whose wage is ₹11,000.
    reg = br.build(accounting_year=YEAR,
                   employees=[_emp("e1", "Asha", 15_000_00)],
                   minimum_wage_monthly_paise=11_000_00)
    assert reg.employees[0].calculation_base_monthly_paise == 11_000_00
    assert reg.employees[0].payable_paise > 6_997_20


def test_the_base_never_exceeds_the_salary_actually_drawn():
    reg = br.build(accounting_year=YEAR,
                   employees=[_emp("e1", "Asha", 9_000_00)],
                   minimum_wage_monthly_paise=11_000_00)
    assert reg.employees[0].calculation_base_monthly_paise == 9_000_00


# ── 3. the three refusals ───────────────────────────────────────────────────

def test_no_declared_rate_means_the_10_MINIMUM_and_says_it_is_not_a_placeholder():
    reg = br.build(accounting_year=YEAR, employees=[])
    assert reg.rate_bps == bonus_domain.MINIMUM_RATE_BPS
    assert reg.rate_is_the_statutory_minimum is True
    note = " ".join(reg.notes)
    assert "whether or not there is a surplus" in note


def test_a_declared_rate_is_not_flagged_as_the_minimum():
    reg = br.build(accounting_year=YEAR, employees=[], rate_bps=1500)
    assert reg.rate_is_the_statutory_minimum is False
    assert not any("8.33% applies" in n for n in reg.notes)


def test_no_minimum_wage_is_a_GAP_naming_the_direction_of_the_error():
    reg = br.build(accounting_year=YEAR,
                   employees=[_emp("e1", "Asha", 15_000_00)])
    gap = " ".join(reg.gaps)
    assert "§12" in gap and "too low" in gap


def test_one_minimum_wage_for_a_whole_client_is_a_STATED_simplification():
    reg = br.build(accounting_year=YEAR, employees=[],
                   minimum_wage_monthly_paise=11_000_00)
    assert any("SCHEDULED EMPLOYMENT" in n for n in reg.notes)


def test_an_unrecorded_working_day_count_is_neither_nil_nor_thirty():
    # Nil would disqualify every employee at a client who runs payroll without
    # attendance — hiding a debt §28 makes an offence to miss. Thirty would
    # assert a fact nobody holds. The figure is shown and the employee NAMED.
    reg = br.build(accounting_year=YEAR,
                   employees=[_emp("e1", "Asha", 15_000_00, days=None)])
    line = reg.employees[0]
    assert line.working_days is None
    assert line.eligible is True
    assert line.payable_paise > 0
    assert any("attendance" in g for g in line.gaps)
    assert any("Asha" in g for g in reg.gaps)


def test_the_gap_travels_with_the_LINE_not_only_the_summary():
    # A summary-only gap is invisible on the row a CA is reading.
    reg = br.build(accounting_year=YEAR, employees=[
        _emp("e1", "Asha", 15_000_00, days=None),
        _emp("e2", "Chitra", 15_000_00, days=280),
    ])
    assert reg.employees[0].gaps and not [
        g for g in reg.employees[1].gaps if "attendance" in g]


def test_nothing_is_posted_and_the_register_says_so():
    reg = br.build(accounting_year=YEAR, employees=[])
    assert any("Nothing is posted" in n for n in reg.notes)


def test_form_C_and_form_D_are_named_rather_than_produced():
    reg = br.build(accounting_year=YEAR, employees=[])
    note = " ".join(reg.notes)
    assert "Form C" in note and "Form D" in note


# ── 4. §9 ───────────────────────────────────────────────────────────────────

def test_section_9_forfeits_the_WHOLE_bonus():
    reg = br.build(accounting_year=YEAR, employees=[
        _emp("e1", "Asha", 15_000_00, disqualified_ground="fraud")])
    line = reg.employees[0]
    assert line.eligible is False and line.payable_paise == 0
    assert any("§9" in r for r in line.reasons)


def test_the_grounds_are_the_ACTS_five_and_nothing_else():
    assert set(br.SECTION_9_GROUNDS) == {
        "fraud",
        "riotous_or_violent_behaviour_on_the_premises",
        "theft_of_establishment_property",
        "misappropriation_of_establishment_property",
        "sabotage_of_establishment_property",
    }, ("a free-text reason would let 'poor performance' forfeit a statutory "
        "debt, which §9 does not reach")


def test_the_grounds_match_the_column_the_database_CHECKs():
    from pathlib import Path
    sql = Path(__file__).resolve().parents[1] / "migrations" / \
        "395_the_employers_own_bonus_determination.sql"
    body = sql.read_text(encoding="utf-8")
    for ground in br.SECTION_9_GROUNDS:
        assert f"'{ground}'" in body, (
            f"{ground} is offered by the domain module and would be REJECTED "
            f"by the CHECK — the two lists must be one")


def test_a_ground_the_act_does_not_name_is_refused_at_the_door():
    from routers.payroll import BonusDisqualificationIn
    with pytest.raises(Exception) as e:
        BonusDisqualificationIn(client_id=CLIENT, employee_id="e1",
                                accounting_year=YEAR, ground="poor_performance",
                                dismissed_on="2025-06-01")
    assert "§9" in str(e.value)


# ── 5. what the service reads ───────────────────────────────────────────────

class _Res:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, store, table):
        self.store, self.t = store, table
        self.f = []
        self._limit = None
        self._insert = None
        self._update = None

    def select(self, *a, **k):
        return self

    def eq(self, k, v):
        self.f.append(("eq", k, v)); return self

    def gte(self, k, v):
        self.f.append(("gte", k, v)); return self

    def lte(self, k, v):
        self.f.append(("lte", k, v)); return self

    def in_(self, k, vals):
        self.f.append(("in", k, set(str(x) for x in vals))); return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        self._limit = n; return self

    def insert(self, rows):
        self._insert = rows if isinstance(rows, list) else [rows]; return self

    def update(self, patch):
        self._update = patch; return self

    def _match(self, r):
        for op, k, v in self.f:
            if op == "eq" and str(r.get(k)) != str(v):
                return False
            if op == "gte" and str(r.get(k)) < str(v):
                return False
            if op == "lte" and str(r.get(k)) > str(v):
                return False
            if op == "in" and str(r.get(k)) not in v:
                return False
        return True

    def execute(self):
        rows_table = self.store.setdefault(self.t, [])
        if self._insert is not None:
            out = []
            for r in self._insert:
                row = {"id": str(uuid.uuid4()), **r}
                rows_table.append(row); out.append(row)
            return _Res(out)
        if self._update is not None:
            updated = []
            for r in rows_table:
                if self._match(r):
                    r.update(self._update); updated.append(r)
            return _Res(updated)
        rows = [dict(r) for r in rows_table if self._match(r)]
        rows.sort(key=lambda r: str(r.get("id")))
        if self._limit is not None:
            rows = rows[: self._limit]
        return _Res(rows)


class _DB:
    def __init__(self, **tables):
        self.store = dict(tables)

    def table(self, name):
        return _Q(self.store, name)


def _service_db(**over):
    store = {
        "payroll_employees": [
            {"id": "e1", "firm_id": FIRM, "client_id": CLIENT, "name": "Asha",
             "basic_paise": 10_000_00, "da_percent": 50, "is_active": True},
        ],
        "payroll_runs": [
            {"id": "r1", "firm_id": FIRM, "client_id": CLIENT,
             "month": "2025-06", "status": "finalized"},
            {"id": "r2", "firm_id": FIRM, "client_id": CLIENT,
             "month": "2025-07", "status": "draft"},
        ],
        "payroll_slips": [
            {"id": "s1", "run_id": "r1", "employee_id": "e1"},
            {"id": "s2", "run_id": "r2", "employee_id": "e1"},
        ],
        "attendance": [
            {"id": "a1", "firm_id": FIRM, "employee_id": "e1",
             "year": 2025, "month": 6, "working_days": 26, "days_present": 24},
        ],
        "bonus_declarations": [],
        "bonus_disqualifications": [],
    }
    store.update(over)
    return _DB(**store)


def test_the_service_reads_2_21_salary_and_not_the_slips_gross():
    # basic 10,000 + DA at 50% = 15,000. The slip's gross carries HRA and
    # every other allowance, which §2(21) excludes.
    out = svc.read_register(_service_db(), firm_id=FIRM, client_id=CLIENT,
                            accounting_year=YEAR)
    assert out["employees"][0]["monthly_salary_paise"] == 15_000_00


def test_a_DRAFT_run_is_not_a_month_worked():
    out = svc.read_register(_service_db(), firm_id=FIRM, client_id=CLIENT,
                            accounting_year=YEAR)
    assert out["employees"][0]["months_worked"] == 1, (
        "a draft run has paid nobody — PAY-04's reasoning, and here it would "
        "put a month of salary into a statutory debt on an unapproved run")


def test_two_slips_in_one_month_are_still_one_month():
    db = _service_db()
    db.store["payroll_runs"].append(
        {"id": "r3", "firm_id": FIRM, "client_id": CLIENT,
         "month": "2025-06", "status": "finalized"})
    db.store["payroll_slips"].append(
        {"id": "s3", "run_id": "r3", "employee_id": "e1"})
    out = svc.read_register(db, firm_id=FIRM, client_id=CLIENT,
                            accounting_year=YEAR)
    assert out["employees"][0]["months_worked"] == 1, (
        "a re-run or a correction is not a second month of service")


def test_the_service_counts_days_PRESENT_and_not_the_establishments_days():
    out = svc.read_register(_service_db(), firm_id=FIRM, client_id=CLIENT,
                            accounting_year=YEAR)
    assert out["employees"][0]["working_days"] == 24, (
        "§8 counts days ACTUALLY worked, so `days_present` is the column and "
        "`working_days` — the establishment's days in the month — is not")


def test_attendance_outside_the_accounting_year_is_not_counted():
    db = _service_db()
    db.store["attendance"].append(
        {"id": "a2", "firm_id": FIRM, "employee_id": "e1",
         "year": 2025, "month": 3, "working_days": 26, "days_present": 25})
    out = svc.read_register(db, firm_id=FIRM, client_id=CLIENT,
                            accounting_year=YEAR)
    assert out["employees"][0]["working_days"] == 24, (
        "March 2025 is FY 2024-25 — a financial year runs April to March")


def test_no_attendance_at_all_reads_as_UNKNOWN_and_not_as_zero():
    db = _service_db(attendance=[])
    out = svc.read_register(db, firm_id=FIRM, client_id=CLIENT,
                            accounting_year=YEAR)
    assert out["employees"][0]["working_days"] is None


def test_an_attendance_row_saying_ZERO_is_a_different_fact_from_none_at_all():
    db = _service_db()
    db.store["attendance"][0]["days_present"] = 0
    out = svc.read_register(db, firm_id=FIRM, client_id=CLIENT,
                            accounting_year=YEAR)
    assert out["employees"][0]["working_days"] == 0, (
        "zero recorded and nothing recorded are different facts and the "
        "register must not collapse them")


def test_another_firms_employee_is_not_on_this_register():
    db = _service_db()
    db.store["payroll_employees"].append(
        {"id": "e9", "firm_id": "firm-2", "client_id": CLIENT, "name": "Other",
         "basic_paise": 10_000_00, "da_percent": 0, "is_active": True})
    out = svc.read_register(db, firm_id=FIRM, client_id=CLIENT,
                            accounting_year=YEAR)
    assert {e["employee_id"] for e in out["employees"]} == {"e1"}


def test_a_declaration_is_read_and_applied():
    db = _service_db(bonus_declarations=[{
        "id": "d1", "firm_id": FIRM, "client_id": CLIENT,
        "accounting_year": YEAR, "rate_bps": 1200,
        "allocable_surplus_paise": None,
        "minimum_wage_monthly_paise": 11_000_00,
        "scheduled_employment": "Shops and establishments", "notes": None}])
    out = svc.read_register(db, firm_id=FIRM, client_id=CLIENT,
                            accounting_year=YEAR)
    assert out["rate_bps"] == 1200
    assert out["minimum_wage_monthly_paise"] == 11_000_00
    assert out["declaration"]["id"] == "d1"


def test_another_years_declaration_is_not_applied():
    db = _service_db(bonus_declarations=[{
        "id": "d1", "firm_id": FIRM, "client_id": CLIENT,
        "accounting_year": "2024-25", "rate_bps": 1200,
        "allocable_surplus_paise": None, "minimum_wage_monthly_paise": None,
        "scheduled_employment": None, "notes": None}])
    out = svc.read_register(db, firm_id=FIRM, client_id=CLIENT,
                            accounting_year=YEAR)
    assert out["rate_bps"] == 833 and out["declaration"] is None


def test_a_disqualification_reaches_the_register():
    db = _service_db(bonus_disqualifications=[{
        "id": "x1", "firm_id": FIRM, "client_id": CLIENT, "employee_id": "e1",
        "accounting_year": YEAR, "ground": "theft_of_establishment_property",
        "dismissed_on": "2025-08-01"}])
    out = svc.read_register(db, firm_id=FIRM, client_id=CLIENT,
                            accounting_year=YEAR)
    line = out["employees"][0]
    assert line["eligible"] is False
    assert any("Theft" in r for r in line["reasons"])


def test_saving_a_declaration_twice_updates_rather_than_duplicates():
    db = _service_db()
    svc.save_declaration(db, firm_id=FIRM, client_id=CLIENT,
                         accounting_year=YEAR, rate_bps=1000,
                         allocable_surplus_paise=None,
                         minimum_wage_monthly_paise=None,
                         scheduled_employment=None, notes=None, actor_id=None)
    svc.save_declaration(db, firm_id=FIRM, client_id=CLIENT,
                         accounting_year=YEAR, rate_bps=1500,
                         allocable_surplus_paise=None,
                         minimum_wage_monthly_paise=None,
                         scheduled_employment=None, notes=None, actor_id=None)
    assert len(db.store["bonus_declarations"]) == 1
    assert db.store["bonus_declarations"][0]["rate_bps"] == 1500


def test_EVERY_read_and_write_in_the_service_carries_the_firm_filter():
    """The service-role key bypasses RLS, so the app-layer filter is the
    isolation control (CLAUDE.md). `payroll_slips` has no `firm_id` and is
    scoped through its run — which is why the run read must carry it."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(svc))
    SCOPED_THROUGH_A_PARENT = {"payroll_slips"}
    unscoped = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain = ast.unparse(node)
        if ".table(" not in chain or ".execute()" not in chain:
            continue
        table = None
        for n in ast.walk(node):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "table" and n.args
                    and isinstance(n.args[0], ast.Constant)):
                table = n.args[0].value
        if table in SCOPED_THROUGH_A_PARENT:
            continue
        if ".insert(" in chain:
            scoped = "'firm_id'" in chain or '"firm_id"' in chain
        else:
            scoped = "eq('firm_id'" in chain or 'eq("firm_id"' in chain
        if not scoped:
            unscoped.append(f"{table}: {chain[:110]}")
    assert not unscoped, (
        "these reads or writes omit the tenant filter:\n  " + "\n  ".join(unscoped))


def test_the_parent_read_carries_the_filter_the_child_cannot():
    import inspect
    src = inspect.getsource(svc._months_worked)
    assert 'table("payroll_runs")' in src and 'eq("firm_id"' in src, (
        "payroll_slips has no firm_id, so the run read is the only tenant "
        "check — the two guards must not both be satisfied by dropping it")
