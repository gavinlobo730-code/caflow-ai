"""What the firm-level payroll screens ask for — and what they may not ask for.

WHAT WAS WRONG

    Both firm-level payroll screens loaded EVERY PAYSLIP OF EVERY RUN the firm
    had ever produced, on mount.

    /payroll issued one `GET /runs/{id}/slips` per run, concurrently, for a tab
    that is not even the default — and every one of its five figures per run is
    an AGGREGATE: how many slips, the gross, the TDS, how many carried PF, how
    many carried ESI. Five numbers, fetched as N rows.

    /payroll/reports put every run's UUID into one PostgREST `in.()` and pulled
    the lot. Its five tabs then each looked at a slice: one run, one month, one
    employee's financial year. Not one of them wanted the firm's whole history.

    CLAUDE.md states the rule: "No report may fetch rows proportional to
    transaction volume. What crosses the wire must be proportional to the size
    of the ANSWER." A hundred employees over three years is 3,600 payslips —
    each carrying gross, net, every statutory deduction and the employer split
    — to render a table of a dozen rows.

WHAT THIS MODULE DOES

    `run_summaries` returns the aggregate, one row per RUN. Proportional to the
    number of months, which is what the table shows.

    `slips_for` returns payslips, and REFUSES a request that names no run, no
    month and no employee. That refusal is the fix, not a guard on it: an
    endpoint that will hand over the whole table is one a future screen will
    ask, and the two screens above are what that looks like.

WHY THE PF AND ESI COUNTS ARE READ AND NOT DERIVED

    They count slips that actually CARRIED the contribution, never a re-derived
    ceiling test. `/payroll` learnt this the hard way: an `esi_applicable` test
    of `gross <= 2100000` for the month drops a member ESI Rule 50 keeps in
    past the ceiling until the contribution period ends — so the screen read
    "no ESI-applicable employees" for people the firm had deducted from. The
    slip is the record of what was deducted; a rule re-applied afterwards is a
    second opinion about a past month.

EVERY READ HERE IS PAGED, AND A LIST OF RUNS IS SENT IN PIECES (POST-A-535)

    The runs of a year, the runs of every year and the payslips of those runs
    were each read in one request. The database answers at most a thousand rows
    to one request and says nothing about the rest, so past that the year-end
    report added up part of the year and the list of years lost its oldest
    ones, with no word on the screen: a hundred clients reach a thousand runs
    in under a year, and a hundred employees reach a thousand payslips in ten
    months. And the run ids went into ONE `in.()` filter, which is part of the
    address: a few hundred ids is a request the gateway refuses before the
    database sees it. Each read goes through `core.db_paging` now (`fetch_all`
    for the runs, `fetch_all_in` for the payslips of a list of runs), so every
    projection names `id`, which is what the pager walks on.

    THE SUMS ARE ADDED UP IN THE DATABASE (POST-A-536, migration 779). The two
    functions `payroll_run_summaries` and `payroll_year_end_totals` return the
    sums as one JSON document each, so what crosses the wire is the size of the
    ANSWER and not of the payroll. The route still narrows the runs to the
    caller's clients first and hands the database the run ids it may answer for.
    THE PYTHON PATH BELOW IS KEPT, not replaced: mock mode and local dev have no
    such function, and a database that has not applied 779 yet (or answers it
    wrongly) must still answer, so a missing or failing function is reported
    (`capture_soft_failure`) and the same figures are added up here from the
    paged payslips. `tests/test_779_the_payroll_reports_add_up_in_the_database_pg.py`
    runs the same payslips through both and compares them.
"""
from __future__ import annotations

import re
from typing import Callable, Optional
from core.db_paging import fetch_all, fetch_all_in, fetch_document
from core.db_provider import privileged_for
from core.observability import capture_soft_failure

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

_RUN_SUM_KEYS = ("gross_paise", "net_paise", "tds_paise", "pf_employee_paise", "pf_employer_paise",
                 "esi_employee_paise", "esi_employer_paise")
_EMPLOYEE_SUM_KEYS = ("gross_paise", "net_paise", "tds_paise", "pt_paise", "pf_employee_paise", "esi_employee_paise")


def _from_the_database(db, label: str, firm_id: str, call: Callable) -> Optional[list]:
    """The database function's answer, or None when there is none to ask (mock mode, a database without migration 779) or it failed.

    `call` takes the privileged client and returns the `.rpc(...)` builder, so the function's NAME is a literal at its call site (the
    schema checks read `.rpc("name", ...)` literals and a name passed through a variable is one nothing checks).

    None is never an empty answer: the caller then adds the figures up itself from the paged payslips, so a missing function costs
    speed and never a figure. A failure is reported, not swallowed."""
    client = privileged_for(db)
    if not callable(getattr(client, "rpc", None)):
        return None
    try:
        return fetch_document(lambda: call(client), label=f"payroll_report.{label}", expect=list)
    except Exception as exc:                                  # noqa: BLE001 — reported below, and the Python path answers
        capture_soft_failure(exc, operation=f"payroll_report.{label}", firm_id=firm_id)
        return None


def run_totals_from_slips(run_ids: list[str], rows: list[dict]) -> dict[str, dict]:
    """The five figures per run, added up from the payslip rows (the Python path, and the other half of the parity test)."""
    out: dict[str, dict] = {
        rid: {"run_id": rid, "slip_count": 0, "gross_paise": 0, "net_paise": 0,
              "tds_paise": 0, "pf_count": 0, "esi_count": 0,
              "pf_employee_paise": 0, "pf_employer_paise": 0,
              "esi_employee_paise": 0, "esi_employer_paise": 0}
        for rid in run_ids
    }
    for r in rows:
        b = out.get(str(r.get("run_id")))
        if b is None:
            continue
        b["slip_count"] += 1
        for key in _RUN_SUM_KEYS:
            b[key] += int(r.get(key) or 0)
        # What the slip CARRIED, never a re-derived ceiling test — see the module docstring for the member this got wrong.
        if int(r.get("pf_employee_paise") or 0) > 0:
            b["pf_count"] += 1
        if (int(r.get("esi_employee_paise") or 0) > 0
                or int(r.get("esi_employer_paise") or 0) > 0):
            b["esi_count"] += 1
    return out


def run_totals_from_answer(run_ids: list[str], answer: list[dict]) -> dict[str, dict]:
    """The same figures, from the database function's document."""
    out = run_totals_from_slips(run_ids, [])
    for r in answer:
        b = out.get(str(r.get("run_id")))
        if b is None:
            continue
        b["slip_count"] = int(r.get("slip_count") or 0)
        for key in (*_RUN_SUM_KEYS, "pf_count", "esi_count"):
            b[key] = int(r.get(key) or 0)
    return out


def employee_totals_from_slips(rows: list[dict]) -> list[dict]:
    """One row per employee from the payslip rows, ordered by name (the Python path, and the other half of the parity test)."""
    out: dict[str, dict] = {}
    for r in rows:
        key = str(r.get("employee_id"))
        b = out.setdefault(key, {
            "employee_id": key,
            "employee": r.get("payroll_employees") or None,
            "months": 0, "gross_paise": 0, "net_paise": 0, "tds_paise": 0,
            "pt_paise": 0, "pf_employee_paise": 0, "esi_employee_paise": 0,
        })
        b["months"] += 1
        for k in _EMPLOYEE_SUM_KEYS:
            b[k] += int(r.get(k) or 0)
    return _by_name(out.values())


def employee_totals_from_answer(answer: list[dict]) -> list[dict]:
    """The same rows, from the database function's document."""
    out = []
    for r in answer:
        out.append({
            "employee_id": str(r.get("employee_id")),
            "employee": ({k: r.get(k) for k in ("name", "pan", "designation", "department")} if r.get("has_employee") else None),
            "months": int(r.get("months") or 0),
            **{k: int(r.get(k) or 0) for k in _EMPLOYEE_SUM_KEYS},
        })
    return _by_name(out)


def _by_name(rows) -> list[dict]:
    return sorted(rows, key=lambda b: ((b["employee"] or {}).get("name") or "").lower())


def fy_of_month(month: str) -> Optional[str]:
    """'2026-04' -> '2026-27'; '2027-01' -> '2026-27'.

    DERIVED, because payroll_runs has no financial_year column — it carries
    `month` and nothing else about the year, and assuming otherwise is what
    tests/test_backend_columns_exist_pg.py caught in the first draft of this
    module. The Indian FY runs 1 April to 31 March, so January to March belong
    to the year that STARTED the previous April: a run for March 2027 is FY
    2026-27, and reading the first four characters would file it under 2027-28
    — a year with no payroll in it.
    """
    if not month or not _MONTH_RE.fullmatch(str(month)):
        return None
    year, mon = int(month[:4]), int(month[5:7])
    start = year if mon >= 4 else year - 1
    return f"{start}-{str((start + 1) % 100).zfill(2)}"


def months_of_fy(financial_year: str) -> list[str]:
    """The twelve 'YYYY-MM' months of a financial year, April first."""
    try:
        start = int(str(financial_year).split("-")[0])
    except (ValueError, IndexError, AttributeError) as unreadable:
        # A financial year that cannot be read gives a report with no months: said, so an empty report is not mistaken for a quiet year (POST-A-505).
        capture_soft_failure(unreadable, operation="payroll_report.months_of_fy_unreadable", financial_year=str(financial_year)[:20])
        return []
    return ([f"{start}-{m:02d}" for m in range(4, 13)]
            + [f"{start + 1}-{m:02d}" for m in range(1, 4)])

#: Every column the aggregate needs. Read as a literal so
#: tests/test_backend_columns_exist_pg.py can check each one against the real
#: schema — a joined or computed select list is invisible to it.
_SUMMARY_COLUMNS = ("run_id, gross_paise, net_paise, tds_paise, "
                    "pf_employee_paise, pf_employer_paise, "
                    "esi_employee_paise, esi_employer_paise")


class PayrollReportRefused(Exception):
    """A refusal the caller reads, not a 500."""


def run_summaries(db, firm_id: str, run_ids: list[str]) -> dict[str, dict]:
    """run_id -> the five figures the statutory table shows.

    One query for every run asked about, and the rows it reads carry eight
    columns rather than the whole slip. The screen this replaced made one
    request PER RUN and got every column of every payslip in each.
    """
    if not run_ids:
        return {}
    answer = _from_the_database(
        db, "payroll_run_summaries", firm_id, lambda c: c.rpc("payroll_run_summaries", {"p_firm": firm_id, "p_run_ids": run_ids}))
    if answer is not None:
        return run_totals_from_answer(run_ids, answer)
    rows = fetch_all_in(
        lambda: (privileged_for(db).table("payroll_slips")
                 .select("id, run_id, gross_paise, net_paise, tds_paise, "
                         "pf_employee_paise, pf_employer_paise, "
                         "esi_employee_paise, esi_employer_paise")),
        "run_id", run_ids, label="payroll_report.run_summaries")
    return run_totals_from_slips(run_ids, rows)


def employee_year_totals(db, firm_id: str, financial_year: str,
                        client_id: Optional[str] = None, *,
                        narrow: Callable[[list[dict]], list[dict]]) -> list[dict]:
    """One row per EMPLOYEE for a financial year — the year-end summary.

    This one has to be an aggregate rather than a narrowed slip read, and the
    distinction is worth stating because the other four tabs are the opposite
    case. A run's payslips, a month's payslips, one employee's twelve months —
    each is a row set the same size as the table it renders, so fetching the
    rows IS fetching the answer. A firm's whole financial year is not: a
    hundred employees over twelve months is 1,200 payslips to render a hundred
    rows, and that is proportional to payroll VOLUME, which CLAUDE.md's
    reporting rule forbids.
    """
    months = months_of_fy(financial_year)
    if not months:
        return []
    def _runs():
        q = (privileged_for(db).table("payroll_runs")
             .select("id, client_id, month")
             .eq("firm_id", firm_id).in_("month", months))
        return q.eq("client_id", client_id) if client_id else q
    # `narrow` is REQUIRED and has no default: the read above is the privileged client's, so it holds every client's
    # runs, and the caller (the route, which knows who is asking) says which of them may be answered for. Each run
    # carries its `client_id`, which is what the narrowing reads.
    run_rows = narrow(fetch_all(_runs, label="payroll_report.year_runs", strict=True))
    if not run_rows:
        return []

    run_ids = [str(r["id"]) for r in run_rows]
    answer = _from_the_database(
        db, "payroll_year_end_totals", firm_id, lambda c: c.rpc("payroll_year_end_totals", {"p_firm": firm_id, "p_run_ids": run_ids}))
    if answer is not None:
        return employee_totals_from_answer(answer)
    rows = fetch_all_in(
        lambda: (privileged_for(db).table("payroll_slips")
                 .select("id, employee_id, gross_paise, net_paise, tds_paise, pt_paise, "
                         "pf_employee_paise, esi_employee_paise, "
                         "payroll_employees(name, pan, designation, department)")),
        "run_id", run_ids, label="payroll_report.year_slips")
    return employee_totals_from_slips(rows)


def financial_years(db, firm_id: str, *, narrow: Callable[[list[dict]], list[dict]]) -> list[str]:
    """Which years this firm has payroll for, newest first.

    Read off the RUNS, which are one per client-month, rather than off the
    payslips — the year picker used to derive its options from every payslip
    the firm had ever produced.
    """
    rows = narrow(fetch_all(
        lambda: privileged_for(db).table("payroll_runs").select("id, month, client_id").eq("firm_id", firm_id),
        label="payroll_report.years_on_file", strict=True))
    years = {fy for fy in (fy_of_month(str(r.get("month") or "")) for r in rows) if fy}
    return sorted(years, reverse=True)


def assert_narrowed(run_id: Optional[str], month: Optional[str],
                    employee_id: Optional[str]) -> None:
    """A payslip read must name what it is about.

    THE REFUSAL IS THE FIX. Every screen that wanted payslips wanted a slice —
    one run, one month, one employee's year — and both of them asked for the
    firm's entire history because nothing stopped them. An endpoint that will
    hand over the whole table is one the next screen will ask.
    """
    if not (run_id or month or employee_id):
        raise PayrollReportRefused(
            "Name a run, a month or an employee. Payslips are not read for a "
            "whole firm at once: every screen that shows them shows one run, "
            "one month or one employee's year, and fetching the rest is work "
            "nobody sees.")
    if month and not _MONTH_RE.fullmatch(month):
        raise PayrollReportRefused("month must be YYYY-MM, like 2026-04.")
