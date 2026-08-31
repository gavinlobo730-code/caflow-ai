"""
Task #229 — payroll critical/high gap fixes.

Covers the 4 categories named in the task: duplicate-run race (finding #1),
PF base excluding DA (finding #2), missing/weak validation on the payroll
Pydantic models (findings #5-8), and the frontend silent-write-failure sweep
(finding #4 — frontend-only, verified manually + via tsc, not unit-tested
here since this suite is backend-only).
"""
import math

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import routers.payroll as pr
from models.payroll import EmployeeIn, EmployeeUpdateIn, SalaryStructureIn, PayrollRunIn


# ── Finding #2: PF base = Basic + DA (EPF Act §6), not Basic alone ────────────

def test_compute_pf_uses_basic_plus_da_not_basic_alone():
    # basic 20,000, da 10% -> da 2,000 -> PF wages 22,000, capped at 15,000
    # -> 12% of 15,000 = 1,800 (the statutory max either way here, so use an
    # uncapped example below to actually distinguish the two bases).
    emp = {"basic_paise": 1000000, "da_percent": 20.0, "hra_percent": 0.0,
           "pf_applicable": True, "esi_applicable": False, "pt_applicable": False}
    # basic=10,000 da=2,000 -> PF wages 12,000 (below the 15,000 ceiling), so
    # the old basic-only bug (PF on 10,000) and the fix (PF on 12,000) differ.
    slip = pr._compute_slip(emp)
    assert slip["basic_paise"] == 1000000
    assert slip["da_paise"] == 200000
    pf_wages = slip["basic_paise"] + slip["da_paise"]
    assert pf_wages == 1200000
    expected_pf = math.floor(pf_wages * 12 / 100)
    assert expected_pf == 144000
    assert slip["pf_employee_paise"] == expected_pf
    assert slip["pf_employer_paise"] == expected_pf
    # the old (buggy) basic-only computation would have given 120000 — assert
    # the fix does NOT match that wrong value.
    old_buggy_pf = math.floor(1000000 * 12 / 100)
    assert slip["pf_employee_paise"] != old_buggy_pf


def test_compute_pf_ceiling_still_applies_to_basic_plus_da():
    # basic 20,000 + da 20% (4,000) = pf wages 24,000 -> still capped at the
    # statutory 15,000 ceiling -> 12% of 15,000 = 1,800, not 12% of 24,000.
    emp = {"basic_paise": 2000000, "da_percent": 20.0, "hra_percent": 0.0,
           "pf_applicable": True, "esi_applicable": False, "pt_applicable": False}
    slip = pr._compute_slip(emp)
    assert slip["pf_employee_paise"] == 180000
    assert slip["pf_employer_paise"] == 180000


def test_compute_pf_zero_da_matches_basic_only_pf():
    # da_percent=0 -> PF wages == basic exactly; sanity check the fix doesn't
    # change behaviour for the (still very common) zero-DA case.
    emp = {"basic_paise": 1000000, "da_percent": 0.0, "hra_percent": 0.0,
           "pf_applicable": True, "esi_applicable": False, "pt_applicable": False}
    slip = pr._compute_slip(emp)
    assert slip["pf_employee_paise"] == math.floor(1000000 * 12 / 100)


def test_compute_pf_helper_accepts_wages_directly():
    # Asserts the two figures this test is about, rather than the whole dict.
    # _compute_pf also returns the EPS/EPF split of the employer's share plus
    # EDLI and admin — see tests/test_pf_eps_split.py. Both values below are
    # unchanged by that work; only the dict grew.
    at_12k = pr._compute_pf(1200000)
    assert at_12k["employee"] == 144000
    assert at_12k["employer"] == 144000
    at_ceiling = pr._compute_pf(2400000)
    assert at_ceiling["employee"] == 180000
    assert at_ceiling["employer"] == 180000


# ── Finding #1: create_run duplicate-run race (check-then-act, no DB constraint
#    until migration 237) — the fix catches the concurrent-insert unique
#    violation and turns it into the same friendly 409 the app-level check gives.

class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, store, table, control):
        self.s, self.t = store, table
        self.control = control
        self.op = "select"
        self.payload = None
        self.f = []

    def insert(self, p):
        self.op, self.payload = "insert", p
        return self

    def update(self, p):
        self.op, self.payload = "update", p
        return self

    def select(self, *a, **k):
        self.op = "select"
        return self

    def eq(self, k, v):
        self.f.append((k, v))
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def _match(self):
        rows = self.s.setdefault(self.t, [])
        return [r for r in rows if all(r.get(k) == v for k, v in self.f)]

    def execute(self):
        rows = self.s.setdefault(self.t, [])
        if self.op == "insert":
            if self.t == "payroll_runs" and self.control.get("fail_next_run_insert"):
                self.control["fail_next_run_insert"] = False
                raise Exception(
                    'duplicate key value violates unique constraint '
                    '"uq_payroll_runs_firm_client_month"'
                )
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            ins = []
            for p in items:
                rec = dict(p)
                rec.setdefault("id", f"{self.t}-{len(rows) + 1}")
                rows.append(rec)
                ins.append(rec)
            return _Resp(ins)
        m = self._match()
        if self.op == "update":
            for r in m:
                r.update(self.payload)
            return _Resp(m)
        return _Resp(m)


class FakeDB:
    def __init__(self):
        self.store = {}
        self.control = {"fail_next_run_insert": False}

    def table(self, name):
        return _Q(self.store, name, self.control)


FIRM, CLIENT = "firm-1", "client-1"
USER = {"firm_id": FIRM, "auth_user_id": "u1"}


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch):
    monkeypatch.setattr(pr.timeline_service, "log", lambda *a, **k: None)
    yield


def test_create_run_concurrent_insert_collision_returns_friendly_409():
    db = FakeDB()
    monkeypatch_db = db
    # No existing row — the app-level duplicate SELECT genuinely finds
    # nothing (this is exactly the race: another request's insert lands
    # between this SELECT and this request's own INSERT).
    db.control["fail_next_run_insert"] = True
    import routers.payroll as pr_mod
    orig_db = pr_mod._db
    pr_mod._db = lambda: monkeypatch_db
    try:
        with pytest.raises(HTTPException) as exc_info:
            pr_mod.create_run(PayrollRunIn(client_id=CLIENT, month="2026-06"), USER)
        assert exc_info.value.status_code == 409
        assert "already exists" in exc_info.value.detail
    finally:
        pr_mod._db = orig_db
    # No orphan run row left behind by the failed insert.
    assert db.store.get("payroll_runs", []) == []


def test_create_run_happy_path_still_works_with_the_new_try_except():
    db = FakeDB()
    import routers.payroll as pr_mod
    orig_db = pr_mod._db
    pr_mod._db = lambda: db
    try:
        result = pr_mod.create_run(PayrollRunIn(client_id=CLIENT, month="2026-07"), USER)
    finally:
        pr_mod._db = orig_db
    assert result["success"] is True
    assert result["data"]["month"] == "2026-07"
    assert result["data"]["status"] == "draft"
    assert len(db.store["payroll_runs"]) == 1


def test_create_run_other_db_errors_still_propagate_unmasked():
    """A non-unique-violation insert failure must NOT be swallowed into the
    friendly 409 — only a genuine constraint collision should be reinterpreted."""
    db = FakeDB()

    class _BoomQ(_Q):
        def execute(self):
            if self.op == "insert" and self.t == "payroll_runs":
                raise Exception("connection reset by peer")
            return super().execute()

    class _BoomDB(FakeDB):
        def table(self, name):
            return _BoomQ(self.store, name, self.control)

    boom_db = _BoomDB()
    import routers.payroll as pr_mod
    orig_db = pr_mod._db
    pr_mod._db = lambda: boom_db
    try:
        with pytest.raises(Exception) as exc_info:
            pr_mod.create_run(PayrollRunIn(client_id=CLIENT, month="2026-08"), USER)
        assert not isinstance(exc_info.value, HTTPException)
        assert "connection reset" in str(exc_info.value)
    finally:
        pr_mod._db = orig_db


# ── Findings #5-7: EmployeeIn / EmployeeUpdateIn validation gaps ──────────────

def _valid_employee_kwargs(**overrides):
    kw = dict(client_id=CLIENT, name="Priya Rao", basic_paise=5000000)
    kw.update(overrides)
    return kw


def test_employee_in_rejects_negative_hra_percent():
    with pytest.raises(ValidationError):
        EmployeeIn(**_valid_employee_kwargs(hra_percent=-10.0))


def test_employee_in_rejects_negative_da_percent():
    with pytest.raises(ValidationError):
        EmployeeIn(**_valid_employee_kwargs(da_percent=-5.0))


def test_employee_in_rejects_da_percent_over_100():
    with pytest.raises(ValidationError):
        EmployeeIn(**_valid_employee_kwargs(da_percent=500.0))


def test_employee_in_accepts_valid_percents():
    e = EmployeeIn(**_valid_employee_kwargs(hra_percent=40.0, da_percent=10.0))
    assert e.hra_percent == 40.0 and e.da_percent == 10.0


def test_employee_in_rejects_malformed_pan():
    with pytest.raises(ValidationError):
        EmployeeIn(**_valid_employee_kwargs(pan="NOTAPAN"))


def test_employee_in_accepts_and_normalizes_valid_pan():
    e = EmployeeIn(**_valid_employee_kwargs(pan="abcde1234f"))
    assert e.pan == "ABCDE1234F"


def test_employee_update_in_rejects_negative_basic_paise():
    # task #229: EmployeeUpdateIn had NO numeric validation at all before this fix.
    with pytest.raises(ValidationError):
        EmployeeUpdateIn(basic_paise=-100)


def test_employee_update_in_rejects_negative_hra_percent():
    with pytest.raises(ValidationError):
        EmployeeUpdateIn(hra_percent=-1.0)


def test_employee_update_in_rejects_blank_name():
    with pytest.raises(ValidationError):
        EmployeeUpdateIn(name="   ")


def test_employee_update_in_accepts_omitted_fields():
    # Optional fields must still be omittable (PATCH semantics) — validators
    # must not reject None.
    u = EmployeeUpdateIn(designation="Manager")
    assert u.basic_paise is None and u.hra_percent is None and u.name is None


def test_employee_update_in_rejects_malformed_pan():
    with pytest.raises(ValidationError):
        EmployeeUpdateIn(pan="12345ABCDE")


# ── Finding #8: SalaryStructureIn numeric validation ──────────────────────────

def test_salary_structure_in_rejects_negative_percent():
    with pytest.raises(ValidationError):
        SalaryStructureIn(client_id=CLIENT, name="Grade A", hra_percent=-5.0)


def test_salary_structure_in_rejects_negative_medical_paise():
    with pytest.raises(ValidationError):
        SalaryStructureIn(client_id=CLIENT, name="Grade A", medical_paise=-100)


def test_salary_structure_in_accepts_valid_defaults():
    s = SalaryStructureIn(client_id=CLIENT, name="Grade A")
    assert s.basic_percent == 40.0
