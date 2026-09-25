"""Derive and store one client-year's aggregates (migration 417, D30).

WHERE THIS RUNS AND WHY THAT MAKES IT LEGAL

    CLAUDE.md: "No report may fetch rows proportional to transaction volume."
    This is not a report. It is a step of the 06:00 IST sweep, which already
    pays a per-client read twice over (`audit_and_heal_firm`,
    `run_reconciliation_for_firm`), and it exists precisely so the REPORT —
    `GET /api/analytics/benchmark` — reads a few dozen stored rows instead of
    every client's ledger.

    Every row-set read here goes through `core.db_paging.fetch_all`, the one
    pager, for the same reason every other one does: PostgREST caps a response
    at ~1000 rows and says nothing, so a truncated read is indistinguishable
    from a complete one and every figure computed from it is confidently wrong.

WHICH YEARS

    The current financial year and the one before it, and no more. A year's
    books keep moving until the return is filed and the audit is done, so the
    preceding year has to be re-derived; a year before that is settled, and
    re-deriving eight years for fifty clients every night is 400 per-client
    reads for figures that will not have changed. `YEARS_SWEPT` is the number
    and a test pins it, so widening it is a decision rather than a drift.

WHAT IT REFUSES

    A figure whose source answered nothing is written as NULL and NAMED in
    `gaps` — never 0. Migration 417's own comment has the argument: in a
    DISTRIBUTION a nil that means "not derived" moves every median it is
    counted in, and makes the client it belongs to read as the firm's best
    performer on a ratio nobody computed for them.

    ⚠️ AND "NOTHING" IS NOT THE SAME AS "NIL" ON EITHER SIDE OF THAT. A client
    with GSTR-3B returns on file that declare no output tax has an output tax
    of 0, which is a real answer and belongs in the distribution. A client with
    no returns at all has None. The two are told apart on whether any SOURCE
    ROW was found, never on whether the total came to zero.
"""
from __future__ import annotations

import logging
from typing import Optional

from core.db_paging import fetch_all
from core.ist_clock import fy_bounds, ist_fy_label
from domain.practice import client_metrics as rule
from domain.payroll.department_cost import EMPLOYER_COST_FIELDS

logger = logging.getLogger("caflow.client_metrics")

#: This year and the one before it. See the module docstring.
YEARS_SWEPT = 2

#: PAY-04: a draft run has paid nobody, so it is not a cost and its people are
#: not employees who were paid. Imported rather than respelled — the two
#: answer the same question and a private copy is how a fifth status silently
#: joins one and not the other.
from domain.payroll.run_status import PAYROLL_RELEASED  # noqa: E402


def preceding_fy(fy: str) -> str:
    """'2025-26' from '2026-27'. Derived, never a table."""
    start = int(fy[:4]) - 1
    return f"{start}-{str(start + 1)[-2:]}"


def years_to_sweep(today=None) -> list[str]:
    current = ist_fy_label(today)
    out = [current]
    for _ in range(YEARS_SWEPT - 1):
        out.append(preceding_fy(out[-1]))
    return out


def _periods_in(fy: str) -> list[str]:
    """The twelve MMYYYY keys of a financial year, April first.

    `.in_` over the named months and never a range: `period` is TEXT, so
    `'042025' > '032026'` and a gte/lte would drop the first nine months of
    every year and keep three belonging to the next — the trap GST-10 records.
    """
    start = int(fy[:4])
    return (
        [f"{m:02d}{start}" for m in range(4, 13)]
        + [f"{m:02d}{start + 1}" for m in range(1, 4)]
    )


class _Collector:
    """One client-year's figures, with a gap for every one left unanswered."""

    def __init__(self) -> None:
        self.figures: dict[str, Optional[int]] = {f: None for f in rule.FIGURES}
        self.gaps: list[rule.MetricGap] = []

    def answer(self, figure: str, value: int) -> None:
        self.figures[figure] = int(value)

    def cannot(self, figure: str, why: str) -> None:
        self.figures[figure] = None
        self.gaps.append(rule.MetricGap(figure=figure, why=why))

    def cannot_all(self, figures, why: str) -> None:
        for f in figures:
            self.cannot(f, why)


# ── The books ────────────────────────────────────────────────────────────────

def _from_the_books(reporting, firm_id: str, client_id: str, fy: str,
                    into: _Collector) -> None:
    """Turnover, profit before tax, tax expense and purchases.

    Off `ReportingService.profit_loss`, which reads `account_period_balances` —
    twelve pre-aggregated buckets per account — rather than the lines. The same
    engine the P&L screen renders, so a benchmark and a statement cannot
    disagree about one client's turnover.
    """
    start, end = fy_bounds(fy)
    try:
        pl = reporting.profit_loss(firm_id, client_id, start, end)
    except Exception as e:                       # pragma: no cover - defensive
        logger.warning("client_metrics: P&L failed for %s %s: %s", client_id, fy, e)
        into.cannot_all(
            ("turnover_paise", "profit_before_tax_paise",
             "tax_expense_paise", "purchases_paise"),
            "the profit and loss account could not be built for this year",
        )
        return

    revenue = pl.get("revenue") or {}
    cos = pl.get("cost_of_sales") or {}
    opex = pl.get("operating_expenses") or {}
    rows = list(revenue.get("lines") or []) + list(cos.get("lines") or []) \
        + list(opex.get("lines") or [])

    if not rows:
        # Nothing posted in the year. NOT nil: a client whose books this
        # product does not keep has no turnover figure, and a zero would put
        # them at the bottom of every distribution as though they had traded
        # and earned nothing.
        into.cannot_all(
            ("turnover_paise", "profit_before_tax_paise",
             "tax_expense_paise", "purchases_paise"),
            "no journal entries in this financial year",
        )
        return

    into.answer("turnover_paise", int(revenue.get("total_paise") or 0))

    # Tax expense is the Schedule III caption, resolved by the one classifier
    # (`domain/reporting/schedule_iii`) that the P&L rows already carry. Not a
    # name match on "tax": a client's chart holds GST Input, TDS Receivable and
    # Professional Tax Payable, none of which is tax EXPENSE.
    tax = sum(
        int(r.get("amount_paise") or 0)
        for r in opex.get("lines") or []
        if (r.get("schedule_iii_caption") or "") == "Tax Expense"
    )
    into.answer("tax_expense_paise", tax)

    # PROFIT BEFORE TAX, so `net_profit_paise` — which is struck after every
    # expense — has the tax added back. The P&L builder has no below-the-line
    # section (see CLAUDE.md on why `Tax Expense` is absent from PL_EXP_ORDER),
    # so tax sits among the operating expenses and this is where it comes out.
    into.answer("profit_before_tax_paise", int(pl.get("net_profit_paise") or 0) + tax)

    into.answer("purchases_paise", int(cos.get("total_paise") or 0))


# ── GST, as filed ────────────────────────────────────────────────────────────

def _from_the_returns(db, client_id: str, fy: str, into: _Collector) -> None:
    """Output tax, ITC availed and cash paid, off the year's GSTR-3B headers.

    THE RETURN, NOT THE LEDGER, and that is a decision. Output tax could be
    read off the GST Output account and ITC off the purchase register, and the
    two would disagree the moment a return was revised or a bank-line credit
    was declared. A benchmark of TAX POSITIONS compares what was filed.

    Twelve header rows per client-year — proportional to the answer.
    """
    periods = _periods_in(fy)
    rows = fetch_all(
        lambda: db.table("gstr3b_returns")
        .select("id, period, tax_liability_paise, itc_claimed_paise, cash_payable_paise")
        .eq("client_id", client_id).in_("period", periods),
        label="client_metrics.gstr3b",
    )
    if not rows:
        into.cannot_all(
            ("output_tax_paise", "itc_availed_paise", "gst_cash_paid_paise"),
            "no GSTR-3B is on file for any month of this year",
        )
        return
    into.answer("output_tax_paise", sum(int(r.get("tax_liability_paise") or 0) for r in rows))
    into.answer("itc_availed_paise", sum(int(r.get("itc_claimed_paise") or 0) for r in rows))
    into.answer("gst_cash_paid_paise", sum(int(r.get("cash_payable_paise") or 0) for r in rows))


def _reversals(db, client_id: str, fy: str, into: _Collector) -> None:
    """Credit reversed in the year, from the register that records the GROUND.

    Keyed on `period`, the register's own MMYYYY of the return the reversal was
    declared in — GST-10's reasoning: there is no reversal DATE column, and
    §44 with Rule 80(1) consolidates the returns FURNISHED for the year, so the
    period is the right key as well as the only one.
    """
    periods = _periods_in(fy)
    rows = fetch_all(
        lambda: db.table("itc_reversal_register")
        .select("id, igst_paise, cgst_paise, sgst_paise, cess_paise")
        .eq("client_id", client_id).in_("period", periods),
        label="client_metrics.itc_reversals",
    )
    if not rows:
        # A client with returns on file and no reversals reversed nothing, and
        # that IS nil — unlike the block above, where an absent return means
        # nobody declared anything either way. The two are told apart on
        # whether the RETURNS were found, which is why this reads the same
        # figure the caller already established.
        if into.figures.get("itc_availed_paise") is None:
            into.cannot("itc_reversed_paise",
                        "no GSTR-3B is on file, so there is no return for a "
                        "reversal to have been declared in")
        else:
            into.answer("itc_reversed_paise", 0)
        return
    into.answer("itc_reversed_paise", sum(
        int(r.get("igst_paise") or 0) + int(r.get("cgst_paise") or 0)
        + int(r.get("sgst_paise") or 0) + int(r.get("cess_paise") or 0)
        for r in rows
    ))


# ── TDS ──────────────────────────────────────────────────────────────────────

def _tds(db, client_id: str, fy: str, into: _Collector) -> None:
    """Withheld during the year, and deposited during the year.

    TWO DIFFERENT POPULATIONS ON PURPOSE. Deducted is dated by the transaction;
    deposited is dated by the challan's own payment date, and Rule 30(2) puts
    March's deposit in April — so the two do not tie for any real client, and
    the gap between them is what a benchmark is for. Netting them into one
    "TDS" figure would hide exactly that.
    """
    start, end = fy_bounds(fy)
    deducted = fetch_all(
        lambda: db.table("tds_deductions").select("id, tds_paise")
        .eq("client_id", client_id)
        .gte("transaction_date", start).lte("transaction_date", end),
        label="client_metrics.tds_deductions",
    )
    if deducted:
        into.answer("tds_deducted_paise", sum(int(r.get("tds_paise") or 0) for r in deducted))
    else:
        into.cannot("tds_deducted_paise",
                    "no TDS deduction is recorded for this client in this year")

    challans = fetch_all(
        lambda: db.table("tds_challans").select("id, tds_paise")
        .eq("client_id", client_id)
        .gte("payment_date", start).lte("payment_date", end),
        label="client_metrics.tds_challans",
    )
    if challans:
        # The TAX figure, not `total_paise`: a challan's total carries
        # surcharge, interest and penalty, and interest on a late deposit is
        # not tax deposited. TDS-27's split.
        into.answer("tds_deposited_paise", sum(int(r.get("tds_paise") or 0) for r in challans))
    else:
        into.cannot("tds_deposited_paise",
                    "no TDS challan is recorded for this client in this year")


# ── Payroll ──────────────────────────────────────────────────────────────────

def _payroll(db, client_id: str, fy: str, into: _Collector) -> None:
    """Cost, and how many people it was paid to.

    RELEASED RUNS ONLY (PAY-04): a draft has paid nobody, so counting one puts
    a month of salary into a benchmark of what employing people cost.

    COST IS PAY-25's TWO DEBITS, summed — gross pay under §17(1) plus the
    employer's own PF, EDLI, administrative charge and ESI, the fields
    `domain/payroll/department_cost.EMPLOYER_COST_FIELDS` names. Net pay is not
    cost; the employee's own deductions are the employer's money too, paid to
    somebody else.
    """
    start, end = fy_bounds(fy)
    runs = fetch_all(
        lambda: db.table("payroll_runs").select("id, status, month")
        .eq("client_id", client_id)
        .gte("month", start[:7]).lte("month", end[:7]),
        label="client_metrics.payroll_runs",
    )
    released = [r["id"] for r in runs if (r.get("status") or "") in PAYROLL_RELEASED]
    if not released:
        why = ("no payroll run for this year has been released"
               if runs else "no payroll run exists for this client in this year")
        into.cannot("payroll_cost_paise", why)
        into.cannot("employee_count", why)
        return

    cols = "id, run_id, employee_id, gross_paise, " + ", ".join(EMPLOYER_COST_FIELDS)
    slips = fetch_all(
        lambda: db.table("payroll_slips").select(cols).in_("run_id", released),
        label="client_metrics.payroll_slips",
    )
    cost = 0
    people: set[str] = set()
    for s in slips:
        cost += int(s.get("gross_paise") or 0)
        cost += sum(int(s.get(f) or 0) for f in EMPLOYER_COST_FIELDS)
        if s.get("employee_id"):
            people.add(str(s["employee_id"]))
    into.answer("payroll_cost_paise", cost)
    into.answer("employee_count", len(people))


# ── The step the sweep calls ─────────────────────────────────────────────────

def compute_for_client(db, reporting, firm_id: str, client_id: str, fy: str) -> dict:
    """One client, one year. Returns the row to store."""
    into = _Collector()
    _from_the_books(reporting, firm_id, client_id, fy, into)
    _from_the_returns(db, client_id, fy, into)
    _reversals(db, client_id, fy, into)
    _tds(db, client_id, fy, into)
    _payroll(db, client_id, fy, into)
    row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "financial_year": fy,
        "gaps": [g.as_dict() for g in into.gaps],
    }
    row.update(into.figures)
    return row


def store(db, row: dict) -> None:
    """Replace this client-year's row.

    UPSERT on the migration's own key, so a night that runs twice writes one
    row — and so a figure that MOVED is overwritten rather than added to. The
    sweep re-derives; it never accumulates.
    """
    db.table("client_period_metrics").upsert(
        {**row, "computed_at": "now()", "updated_at": "now()"},
        on_conflict="client_id,financial_year",
    ).execute()


def refresh_firm(db, firm_id: str, reporting=None, today=None) -> dict:
    """Every client of one firm, for the years this sweep covers.

    The unit the 06:00 IST scheduler job runs. Returns a compact summary for
    the run log, the shape `audit_and_heal_firm` and `run_reconciliation_for_firm`
    already return.
    """
    if reporting is None:
        from domain.reporting.service import ReportingService
        from domain.reporting.sources import SupabaseLedgerSource
        reporting = ReportingService(SupabaseLedgerSource(db, None))

    clients = fetch_all(
        lambda: db.table("clients").select("id").eq("firm_id", firm_id),
        label="client_metrics.clients",
    )
    years = years_to_sweep(today)
    written = 0
    failed: list[dict] = []
    for c in clients:
        for fy in years:
            try:
                store(db, compute_for_client(db, reporting, firm_id, str(c["id"]), fy))
                written += 1
            except Exception as e:
                # One client's bad year must not stop the firm's sweep — the
                # posture every other step here takes.
                logger.error("client_metrics: %s %s failed: %s", c.get("id"), fy, e,
                             exc_info=True)
                failed.append({"client_id": str(c.get("id")), "financial_year": fy,
                               "error": str(e)})
    return {"clients": len(clients), "years": years, "rows_written": written,
            "failed": failed}
