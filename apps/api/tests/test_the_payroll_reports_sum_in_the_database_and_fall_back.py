"""POST-A-536: the year-end payroll report and the table of runs ask the database for the sums, and fall back to adding them up.

WHAT THESE TESTS HOLD (the database half is `test_779_the_payroll_reports_add_up_in_the_database_pg.py`)
    * With a database function to ask (`rpc`), the answer is the function's and NO payslip is read: what crosses the wire is the size of
      the answer. The route's narrowing still happens first, and only the narrowed run ids are handed to the database.
    * Without one (mock mode, a database that has not applied migration 779), or when it fails or answers something that is not a
      document, the same figures are added up from the paged payslips, and a failure is REPORTED, never swallowed.
    * The database's document and the Python path give the same figures for the same payslips, here on a fixed set.
"""
from __future__ import annotations

import pytest

from services import payroll_report_service as prs

FIRM = "11111111-1111-1111-1111-111111111111"
RUNS = [{"id": "r1", "firm_id": FIRM, "client_id": "c1", "month": "2026-04"}, {"id": "r2", "firm_id": FIRM, "client_id": "c2", "month": "2026-05"},
        {"id": "r3", "firm_id": FIRM, "client_id": "c1", "month": "2026-06"}]
SLIPS = [
    {"id": "s1", "run_id": "r1", "employee_id": "e1", "gross_paise": 5000000, "net_paise": 4500000, "tds_paise": 100000, "pt_paise": 20000,
     "pf_employee_paise": 180000, "pf_employer_paise": 180000, "esi_employee_paise": 0, "esi_employer_paise": 0,
     "payroll_employees": {"name": "Asha", "pan": "ABCDE1234F", "designation": "Clerk", "department": "Ops"}},
    {"id": "s2", "run_id": "r2", "employee_id": "e1", "gross_paise": 5000000, "net_paise": 4400000, "tds_paise": 120000, "pt_paise": 20000,
     "pf_employee_paise": 180000, "pf_employer_paise": 180000, "esi_employee_paise": 0, "esi_employer_paise": 0,
     "payroll_employees": {"name": "Asha", "pan": "ABCDE1234F", "designation": "Clerk", "department": "Ops"}},
    {"id": "s3", "run_id": "r2", "employee_id": "e2", "gross_paise": 1800000, "net_paise": 1700000, "tds_paise": 0, "pt_paise": 0,
     "pf_employee_paise": 0, "pf_employer_paise": 0, "esi_employee_paise": 13500, "esi_employer_paise": 58500,
     "payroll_employees": {"name": "bala", "pan": None, "designation": None, "department": None}},
    {"id": "s4", "run_id": "r3", "employee_id": "e3", "gross_paise": 100, "net_paise": 100, "tds_paise": 0, "pt_paise": 0,
     "pf_employee_paise": 0, "pf_employer_paise": 0, "esi_employee_paise": 0, "esi_employer_paise": 0,
     "payroll_employees": None},
]


class _Result:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, db, table, rows):
        self.db, self.table, self.rows = db, table, list(rows)

    def select(self, *_a): return self
    def eq(self, k, v): self.rows = [r for r in self.rows if str(r.get(k)) == str(v)]; return self

    def in_(self, k, v):
        wanted = {str(x) for x in v}
        self.rows = [r for r in self.rows if str(r.get(k)) in wanted]
        return self

    def order(self, *_a, **_k): return self
    def limit(self, *_a): return self
    def range(self, a, b): self.rows = self.rows[a:b + 1]; return self
    def gt(self, k, v): self.rows = [r for r in self.rows if str(r.get(k)) > str(v)]; return self

    def execute(self):
        self.db.table_reads.append(self.table)
        return _Result(self.rows)


class _Rpc:
    def __init__(self, db, name, params): self.db, self.name, self.params = db, name, params
    def execute(self):
        self.db.rpc_calls.append((self.name, self.params))
        if self.db.rpc_error:
            raise self.db.rpc_error
        return _Result(self.db.rpc_data)


class _DB:
    def __init__(self, *, rpc=None, rpc_data=None, rpc_error=None):
        self.table_reads: list[str] = []
        self.rpc_calls: list[tuple] = []
        self.rpc_data, self.rpc_error = rpc_data, rpc_error
        if rpc:
            self.rpc = lambda name, params: _Rpc(self, name, params)

    def table(self, name):
        rows = {"payroll_runs": RUNS, "payroll_slips": SLIPS}.get(name, [])
        return _Q(self, name, rows)


def _answer_for_runs(run_ids):
    return [{"run_id": rid, **{k: sum(int(s.get(k) or 0) for s in SLIPS if s["run_id"] == rid) for k in prs._RUN_SUM_KEYS},
             "slip_count": sum(1 for s in SLIPS if s["run_id"] == rid),
             "pf_count": sum(1 for s in SLIPS if s["run_id"] == rid and int(s["pf_employee_paise"]) > 0),
             "esi_count": sum(1 for s in SLIPS if s["run_id"] == rid and (int(s["esi_employee_paise"]) > 0 or int(s["esi_employer_paise"]) > 0))}
            for rid in run_ids if any(s["run_id"] == rid for s in SLIPS)]


@pytest.fixture(autouse=True)
def _the_privileged_client_is_the_one_given(monkeypatch):
    monkeypatch.setattr(prs, "privileged_for", lambda db: db)


def test_run_summaries_are_the_databases_and_read_no_payslip():
    db = _DB(rpc=True, rpc_data=_answer_for_runs(["r1", "r2"]))
    got = prs.run_summaries(db, FIRM, ["r1", "r2", "r9"])
    assert db.rpc_calls == [("payroll_run_summaries", {"p_firm": FIRM, "p_run_ids": ["r1", "r2", "r9"]})]
    assert "payroll_slips" not in db.table_reads
    assert got["r2"]["slip_count"] == 2 and got["r2"]["esi_count"] == 1 and got["r1"]["pf_count"] == 1
    assert got["r9"] == prs.run_totals_from_slips(["r9"], [])["r9"], "a run with no payslips is zeros, as the Python path says"


def test_the_python_path_and_the_databases_document_give_the_same_run_figures():
    ids = ["r1", "r2", "r3", "r9"]
    via_db = prs.run_summaries(_DB(rpc=True, rpc_data=_answer_for_runs(ids)), FIRM, ids)
    via_python = prs.run_summaries(_DB(), FIRM, ids)
    assert via_db == via_python


def test_year_end_is_the_databases_and_reads_only_the_runs():
    answer = [{"employee_id": "e1", "has_employee": True, "name": "Asha", "pan": "ABCDE1234F", "designation": "Clerk", "department": "Ops",
               "months": 2, "gross_paise": 10000000, "net_paise": 8900000, "tds_paise": 220000, "pt_paise": 40000,
               "pf_employee_paise": 360000, "esi_employee_paise": 0}]
    db = _DB(rpc=True, rpc_data=answer)
    got = prs.employee_year_totals(db, FIRM, "2026-27", narrow=lambda rows: rows)
    assert db.table_reads and set(db.table_reads) == {"payroll_runs"}, "the runs are read to narrow them; no payslip is"
    assert db.rpc_calls[0][0] == "payroll_year_end_totals" and db.rpc_calls[0][1]["p_run_ids"] == ["r1", "r2", "r3"]
    assert got[0]["employee"] == {"name": "Asha", "pan": "ABCDE1234F", "designation": "Clerk", "department": "Ops"}


def test_only_the_runs_the_caller_may_be_answered_for_go_to_the_database():
    db = _DB(rpc=True, rpc_data=[])
    prs.employee_year_totals(db, FIRM, "2026-27", narrow=lambda rows: [r for r in rows if r["client_id"] == "c1"])
    assert db.rpc_calls[0][1]["p_run_ids"] == ["r1", "r3"]


def test_the_python_path_and_the_databases_document_give_the_same_year_end_rows():
    via_python = prs.employee_year_totals(_DB(), FIRM, "2026-27", narrow=lambda rows: rows)
    by_emp = {}
    for s in SLIPS:
        b = by_emp.setdefault(s["employee_id"], {"employee_id": s["employee_id"], "has_employee": bool(s["payroll_employees"]),
                                                 **(s["payroll_employees"] or {"name": None, "pan": None, "designation": None, "department": None}),
                                                 "months": 0, **{k: 0 for k in prs._EMPLOYEE_SUM_KEYS}})
        b["months"] += 1
        for k in prs._EMPLOYEE_SUM_KEYS:
            b[k] += int(s[k])
    via_db = prs.employee_year_totals(_DB(rpc=True, rpc_data=list(by_emp.values())), FIRM, "2026-27", narrow=lambda rows: rows)
    assert via_db == via_python
    assert [r["employee_id"] for r in via_python] == ["e3", "e1", "e2"], "ordered by name, case-folded; an employee with no name first"


@pytest.mark.parametrize("db_kwargs", [
    dict(rpc=True, rpc_error=RuntimeError("function public.payroll_run_summaries does not exist")),
    dict(rpc=True, rpc_data=None),
    dict(rpc=True, rpc_data={"error": "nope"}),
])
def test_a_missing_failing_or_wrong_answer_falls_back_and_is_reported(monkeypatch, db_kwargs):
    reported = []
    monkeypatch.setattr(prs, "capture_soft_failure", lambda exc, **k: reported.append((str(exc), k)))
    db = _DB(**db_kwargs)
    got = prs.run_summaries(db, FIRM, ["r1", "r2"])
    assert got == prs.run_summaries(_DB(), FIRM, ["r1", "r2"]), "the figures are the same, added up from the payslips"
    assert "payroll_slips" in db.table_reads, "the payslips were read instead"
    assert len(reported) == 1 and reported[0][1]["operation"] == "payroll_report.payroll_run_summaries"


def test_no_database_function_to_ask_is_not_a_failure_to_report(monkeypatch):
    reported = []
    monkeypatch.setattr(prs, "capture_soft_failure", lambda exc, **k: reported.append(exc))
    assert prs.run_summaries(_DB(), FIRM, ["r1"])["r1"]["slip_count"] == 1
    assert reported == []


def test_the_service_still_sends_no_request_of_its_own():
    """The database function is asked through `core.db_paging.fetch_document`, so the service itself holds no `.execute()`."""
    import ast
    import pathlib
    src = (pathlib.Path(prs.__file__)).read_text(encoding="utf8")
    calls = [n.lineno for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "execute"]
    assert calls == []
