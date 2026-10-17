"""A payslip's year-to-date counts the runs that paid somebody, and the run the document is for (POST-A-238).

THE DEFECT
    `payslip_pdf_service.load_ytd` selected the financial year's runs with no status filter, so the staff download counted
    an earlier month that was still a DRAFT or in REVIEW. A draft run has deducted nothing (PAY-04), so that month's tax and
    contributions went into a year-to-date figure that has to agree with Form 16. The same slip also read differently on
    the two downloads, because the employee's own sign-in sees only the runs released to them (migrations 323 and 485):
    staff counted every run, the employee counted the released ones.

WHAT IS HELD
    * only `finalized` and `paid` runs count, whichever month they are in;
    * the run the document itself is for counts even while it is a draft, because a watermarked draft payslip is a preview
      of its own month and would otherwise print a year-to-date that leaves that month out;
    * the single-slip download and the whole-run pack both name their own run;
    * the figure agrees between a staff reader (all runs visible) and an employee reader (released runs only).
"""
from __future__ import annotations

import pytest

from services import payslip_pdf_service as payslips
from tests.test_a_draft_payslip_says_so import EMPLOYEE, EMPLOYER, SLIP

FIRM, CLIENT, EMP = "firm-1", "client-1", "emp-1"

RUNS = [
    {"id": "r-apr", "month": "2026-04", "status": "paid"},
    {"id": "r-may", "month": "2026-05", "status": "finalized"},
    {"id": "r-jun", "month": "2026-06", "status": "review"},     # an earlier month still unreleased
    {"id": "r-jul", "month": "2026-07", "status": "draft"},      # the month the document is for
]
SLIPS = [
    {"run_id": "r-apr", "employee_id": EMP, "gross_paise": 100, "net_paise": 80, "tds_paise": 10},
    {"run_id": "r-may", "employee_id": EMP, "gross_paise": 100, "net_paise": 80, "tds_paise": 10},
    {"run_id": "r-jun", "employee_id": EMP, "gross_paise": 100, "net_paise": 80, "tds_paise": 10},
    {"run_id": "r-jul", "employee_id": EMP, "gross_paise": 100, "net_paise": 80, "tds_paise": 10},
]


class _Q:
    """Just the builder `load_ytd` uses, over in-memory rows. `visible` is what the reader's row security lets through."""

    def __init__(self, rows):
        self._rows, self._filters = rows, []

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._filters.append(lambda r: r.get(col) == val)
        return self

    def in_(self, col, vals):
        vals = set(vals)
        self._filters.append(lambda r: r.get(col) in vals)
        return self

    def execute(self):
        class _R:
            pass

        out = _R()
        out.data = [r for r in self._rows if all(f(r) for f in self._filters)]
        return out


class _Db:
    def __init__(self, visible_runs):
        self.runs = [dict(r, firm_id=FIRM, client_id=CLIENT) for r in visible_runs]
        visible = {r["id"] for r in self.runs}
        self.slips = [dict(s) for s in SLIPS if s["run_id"] in visible]

    def table(self, name):
        return _Q(self.runs if name == "payroll_runs" else self.slips)


def _ytd(monkeypatch, visible_runs, month="2026-07", include=()):
    import core.supabase_client as supabase_client

    monkeypatch.setattr(supabase_client, "get_supabase", lambda: _Db(visible_runs))
    return payslips.load_ytd(FIRM, CLIENT, month, [EMP], include_run_ids=include).get(EMP)


def test_an_unreleased_earlier_month_is_not_counted(monkeypatch):
    got = _ytd(monkeypatch, RUNS, month="2026-06")
    assert got["months"] == 2 and got["tds_paise"] == 20, "April (paid) and May (finalized) only; June is in review"


def test_a_draft_run_the_document_is_not_for_is_not_counted(monkeypatch):
    got = _ytd(monkeypatch, RUNS, month="2026-07")
    assert got["months"] == 2, "June (review) and July (draft) have deducted nothing"


def test_the_run_the_document_is_for_counts_even_as_a_draft(monkeypatch):
    got = _ytd(monkeypatch, RUNS, month="2026-07", include=["r-jul"])
    assert got["months"] == 3 and got["gross_paise"] == 300
    assert got["tds_paise"] == 30, "April, May and the July draft being previewed; June (review) still left out"


def test_staff_and_the_employee_read_the_same_year_to_date(monkeypatch):
    staff = _ytd(monkeypatch, RUNS, month="2026-06")
    employee = _ytd(monkeypatch, [r for r in RUNS if r["status"] in ("finalized", "paid")], month="2026-06")
    assert staff == employee


def test_the_filter_is_the_one_released_statuses_constant(monkeypatch):
    from domain.payroll.run_status import PAYROLL_RELEASED

    assert set(PAYROLL_RELEASED) == {"finalized", "paid"}
    only_drafts = [dict(r, status="draft") for r in RUNS]
    assert _ytd(monkeypatch, only_drafts, month="2026-07") is None, "nothing released: no year-to-date block at all"


def _capture_load_ytd(monkeypatch):
    seen: dict = {}

    def _stub(firm_id, client_id, month, employee_ids, include_run_ids=()):
        seen.update(month=month, employee_ids=list(employee_ids), include_run_ids=list(include_run_ids))
        return {}

    monkeypatch.setattr(payslips, "load_ytd", _stub)
    monkeypatch.setattr(payslips, "load_employer", lambda firm_id, client_id, db=None: dict(EMPLOYER))
    return seen


def test_the_single_slip_download_names_its_own_run(monkeypatch):
    """Run end to end: a draft payslip previews its own month, so the run the slip belongs to is handed to load_ytd."""
    class _Res:
        data = {**{k: v for k, v in SLIP.items() if k != "id"}, "id": "S1", "run_id": "R-DRAFT",
                "payroll_employees": dict(EMPLOYEE),
                "payroll_runs": {"month": "2026-09", "firm_id": "F1", "client_id": "C1", "status": "draft"}}

    class _Table:
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def maybe_single(self): return self
        def execute(self): return _Res()

    class _Db:
        def table(self, name): return _Table()

    import core.supabase_client as supabase_client

    monkeypatch.setattr(supabase_client, "get_supabase", lambda: _Db())
    seen = _capture_load_ytd(monkeypatch)

    payslips.get_payslip_pdf("S1", "F1")

    assert seen["include_run_ids"] == ["R-DRAFT"]
    assert seen["month"] == "2026-09"


def test_the_whole_run_pack_names_its_own_run(monkeypatch):
    run = {"id": "R-PACK", "firm_id": "F1", "client_id": "C1", "month": "2026-09", "status": "draft"}
    slips = [{**{k: v for k, v in SLIP.items() if k != "id"}, "id": "S1", "employee_id": "emp-1",
              "payroll_employees": dict(EMPLOYEE)}]

    class _Table:
        def __init__(self, name): self.name = name
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def maybe_single(self): return self

        def execute(self):
            class _R:
                pass

            r = _R()
            r.data = run if self.name == "payroll_runs" else slips
            return r

    class _Db:
        def table(self, name): return _Table(name)

    import core.supabase_client as supabase_client

    monkeypatch.setattr(supabase_client, "get_supabase", lambda: _Db())
    seen = _capture_load_ytd(monkeypatch)

    _zip, filename, problems = payslips.build_run_payslip_zip("R-PACK", "F1")

    assert problems == [] and filename == "payslips-2026-09.zip"
    assert seen["include_run_ids"] == ["R-PACK"]


@pytest.mark.parametrize("status", ["draft", "review"])
def test_a_month_that_is_only_a_draft_or_in_review_gives_no_year_to_date(monkeypatch, status):
    runs = [{"id": "r-apr", "month": "2026-04", "status": status}]
    got = _ytd(monkeypatch, runs, month="2026-04")
    assert got is None, f"a {status} run must not produce a year-to-date"
