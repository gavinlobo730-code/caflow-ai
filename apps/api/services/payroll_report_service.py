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
"""
from __future__ import annotations

import re
from typing import Optional

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


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
    except (ValueError, IndexError, AttributeError):
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
    rows = (db.table("payroll_slips")
            .select("run_id, gross_paise, net_paise, tds_paise, "
                    "pf_employee_paise, pf_employer_paise, "
                    "esi_employee_paise, esi_employer_paise")
            .in_("run_id", run_ids).execute().data) or []

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
        for key in ("gross_paise", "net_paise", "tds_paise",
                    "pf_employee_paise", "pf_employer_paise",
                    "esi_employee_paise", "esi_employer_paise"):
            b[key] += int(r.get(key) or 0)
        # What the slip CARRIED, never a re-derived ceiling test — see the
        # module docstring for the member this got wrong.
        if int(r.get("pf_employee_paise") or 0) > 0:
            b["pf_count"] += 1
        if (int(r.get("esi_employee_paise") or 0) > 0
                or int(r.get("esi_employer_paise") or 0) > 0):
            b["esi_count"] += 1
    return out


def employee_year_totals(db, firm_id: str, financial_year: str,
                        client_id: Optional[str] = None) -> list[dict]:
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
    runs = (db.table("payroll_runs")
            .select("id, client_id, month")
            .eq("firm_id", firm_id).in_("month", months))
    if client_id:
        runs = runs.eq("client_id", client_id)
    run_rows = runs.execute().data or []
    if not run_rows:
        return []

    rows = (db.table("payroll_slips")
            .select("employee_id, gross_paise, net_paise, tds_paise, pt_paise, "
                    "pf_employee_paise, esi_employee_paise, "
                    "payroll_employees(name, pan, designation, department)")
            .in_("run_id", [str(r["id"]) for r in run_rows]).execute().data) or []

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
        for k in ("gross_paise", "net_paise", "tds_paise", "pt_paise",
                  "pf_employee_paise", "esi_employee_paise"):
            b[k] += int(r.get(k) or 0)
    return sorted(out.values(),
                  key=lambda b: ((b["employee"] or {}).get("name") or "").lower())


def financial_years(db, firm_id: str) -> list[str]:
    """Which years this firm has payroll for, newest first.

    Read off the RUNS, which are one per client-month, rather than off the
    payslips — the year picker used to derive its options from every payslip
    the firm had ever produced.
    """
    rows = (db.table("payroll_runs").select("month")
            .eq("firm_id", firm_id).execute().data) or []
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
