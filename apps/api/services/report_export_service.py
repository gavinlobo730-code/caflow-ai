"""Fetch a live report, and hand back it as a PDF or a spreadsheet (accounting-16).

THE ONE RULE: THE EXPORT CALLS THE REPORT THE SCREEN CALLS. Each fetcher below
is a single call to the function the screen's own endpoint is a thin wrapper
over — `ReportingService.ledger` / `.trial_balance` / `.cash_flow_statement`
(built per request by `routers.accounting._reporting_service`, so the caller's
client scope is the screen's), `customer_statement_service.ar_aging` and
`vendor_statement_service.ap_aging`. There is no second query and no second
computation, so the document cannot come out different from what the CA is
looking at, and a figure fixed in the report is fixed in the export with no
second edit. `tests/test_report_exports_are_the_screens_reports.py` pins it by
making each fetcher's source name the screen's function and nothing that reads
the ledger directly.

NO REPORT FETCHES ROWS PROPORTIONAL TO TRANSACTION VOLUME (CLAUDE.md,
"Reporting performance") — with the one honest exception a ledger always is:
its ANSWER is a row per line. It is read the way the screen reads it, through
the paged SQL function whose running balance is computed over the account's
whole history and only then sliced, one thousand lines at a time, and it is
BOUNDED: past `MAX_LEDGER_LINES_PDF` a PDF is refused in words and the CA is
told to narrow the period, because a three-thousand-page PDF that times out is
not a deliverable. The spreadsheet takes a higher ceiling for the same reason
a spreadsheet exists. Trial balance, cash flow and the two ageing reports are
already answers of their own size and are read once.

WHICH REPORT OFFERS WHICH FORMAT is `REPORTS`, and a format a report does not
offer is REFUSED rather than quietly produced: the trial balance has a
browser-made spreadsheet already (`exportXLSX` on the Reports tab) and a second
server-made one beside it would be two sheets of one report to keep in step.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from domain.reporting import export_builders as B
from domain.reporting.export_document import ExportRefused, ReportDocument
from services.report_pdf_service import build_report_pdf
from services.report_xlsx_service import XLSX_MEDIA_TYPE, build_report_xlsx, filename_for

_logger = logging.getLogger("caflow.report_exports")

PDF = "pdf"
XLSX = "xlsx"
PDF_MEDIA_TYPE = "application/pdf"

#: Lines the paged ledger is read in. PostgREST caps a TABLE response at about
#: 1,000 rows and `account_ledger_page` returns one jsonb document, so the cap
#: does not bite — but one page is one Singapore-to-Mumbai round trip and a
#: bounded page keeps one response small.
LEDGER_PAGE = 1000

#: Past this a PDF is refused, and so is a sheet at its own, higher ceiling.
#: MEASURED, not guessed: ReportLab lays a ledger out at about 1.2 ms a line when
#: a quarter of the narrations wrap and 2.8 ms when all of them do (pure-Python
#: string widths, no C accelerator), so 6,000 lines is 7 to 17 seconds on a
#: development machine against a worker that is killed at 120 — and 6,000 covers
#: the largest control account measured in production (Trade Receivables, 5,659
#: lines for one client). A spreadsheet writes about ten thousand lines a second.
MAX_LEDGER_LINES_PDF = 6_000
MAX_LEDGER_LINES_XLSX = 50_000

#: A report's open documents are one row each in the ageing PDF. Its rows are
#: short single-line strings (the cheap case above), so the ceiling is higher.
MAX_AGEING_DOCUMENTS_PDF = 10_000

#: report id -> the formats it is offered in.
REPORTS: dict[str, tuple[str, ...]] = {
    B.LEDGER: (PDF, XLSX),
    B.TRIAL_BALANCE: (PDF,),
    B.CASH_FLOW: (PDF, XLSX),
    B.AR_AGEING: (PDF,),
    B.AP_AGEING: (PDF,),
}


@dataclass(frozen=True)
class ExportedFile:
    content: bytes
    filename: str
    media_type: str


def _refuse_unknown(report: str, fmt: str) -> None:
    if report not in REPORTS:
        raise ExportRefused(f"There is no export called {report!r}.")
    if fmt not in REPORTS[report]:
        offered = " or ".join(REPORTS[report])
        raise ExportRefused(
            f"The {report} report is offered as {offered} only. "
            + ("Its spreadsheet is the XLSX button on the Reports tab, which is "
               "built from this same report." if (report == B.TRIAL_BALANCE and fmt == XLSX)
               else ""))


# ── The fetchers: one call to the screen's own report each ────────────────────

def fetch_ledger(svc, firm_id: str, client_id: str, account_id: str,
                 start: Optional[str], end: Optional[str], *, ceiling: int) -> dict:
    """Every line of one account's window, read through the paged function.

    The first page carries the whole window's opening balance, closing balance
    and totals (the function computes them over the window, not the page), so
    the pages after it only add lines — and `ledger_document` refuses a result
    whose lines do not add up to those totals, which is what turns a short read
    into a refusal instead of a wrong ledger.
    """
    first = svc.ledger(firm_id, client_id, account_id, start, end,
                       limit=LEDGER_PAGE, offset=0)
    lines = list(first.get("lines") or [])
    total = first.get("total_lines")
    if total is not None:
        total = int(total)
        if total > ceiling:
            raise _too_many_lines(total, ceiling)
        while len(lines) < total:
            page = svc.ledger(firm_id, client_id, account_id, start, end,
                              limit=LEDGER_PAGE, offset=len(lines))
            got = page.get("lines") or []
            if not got:
                break                       # short read: the builder refuses it
            lines.extend(got)
    elif len(lines) > ceiling:
        # The builder fallback (no database) returns the whole window and no
        # `total_lines`; the ceiling still applies.
        raise _too_many_lines(len(lines), ceiling)
    if not first.get("account_name"):
        raise ExportRefused("That account is not in this client's chart of accounts.")
    return {**first, "lines": lines}


def _too_many_lines(n: int, ceiling: int) -> ExportRefused:
    return ExportRefused(
        f"This ledger has {n:,} lines in the period, and an export is limited to "
        f"{ceiling:,}. Choose a shorter period and export it in parts.")


def _document(report: str, fmt: str, *, svc, db, firm_id: str, client_id: str,
              p: dict) -> ReportDocument:
    basis = p.get("basis") or "accrual"
    if report == B.LEDGER:
        if not p.get("account_id"):
            raise ExportRefused("A ledger export needs an account.")
        ceiling = MAX_LEDGER_LINES_XLSX if fmt == XLSX else MAX_LEDGER_LINES_PDF
        led = fetch_ledger(svc, firm_id, client_id, p["account_id"],
                           p.get("start_date"), p.get("end_date"), ceiling=ceiling)
        return B.ledger_document(led)
    if report == B.TRIAL_BALANCE:
        tb = svc.trial_balance(firm_id, client_id, p.get("as_of_date"),
                               basis=basis, start_date=p.get("start_date"))
        return B.trial_balance_document(tb, basis=basis)
    if report == B.CASH_FLOW:
        cf = svc.cash_flow_statement(firm_id, client_id, p.get("start_date"),
                                     p.get("end_date"), basis=basis)
        return B.cash_flow_document(cf, basis=basis)
    if report == B.AR_AGEING:
        from services.customer_statement_service import customer_statement_service
        data = customer_statement_service.ar_aging(db, firm_id, client_id, p.get("as_of"))
        _bound_ageing(data.get("invoices"))
        return B.ageing_document(data, payable=False)
    from services.vendor_statement_service import vendor_statement_service
    data = vendor_statement_service.ap_aging(db, firm_id, client_id, p.get("as_of"))
    _bound_ageing(data.get("bills"))
    return B.ageing_document(data, payable=True)


def _bound_ageing(documents) -> None:
    n = len(documents or [])
    if n > MAX_AGEING_DOCUMENTS_PDF:
        raise ExportRefused(
            f"There are {n:,} open documents, and an ageing PDF is limited to "
            f"{MAX_AGEING_DOCUMENTS_PDF:,}. The ageing screen lists them all and "
            "can be exported from there.")


# ── The letterhead's two rows ─────────────────────────────────────────────────

def load_firm(db, firm_id: str) -> dict:
    """The practice that is preparing the document.

    BOTH gstin columns are named in the projection, written out at the call
    site: `domain/firm/identity.gstin_of` falls back from `gstin` to
    `gst_number`, and a read that names one makes that fallback a silent no-op
    (`tests/test_the_firms_own_gstin_has_one_column.py` holds every `firms`
    projection to it). Firm-scoped by construction — the id IS the caller's.
    """
    rows = (db.table("firms").select("id, name, gstin, gst_number")
            .eq("id", firm_id).limit(1).execute().data) or []
    return rows[0] if rows else {}


def load_holder(db, firm_id: str, client_id: str) -> dict:
    from services.statement_pdf_service import load_account_holder
    try:
        return load_account_holder(db, firm_id, client_id)
    except ValueError as e:
        # The client row is the document's subject; without it there is no
        # letterhead to print, and a guess would put somebody else's name on it.
        raise ExportRefused(str(e))


# ── The door ──────────────────────────────────────────────────────────────────

def export_report(report: str, fmt: str, *, svc, db, firm_id: str, client_id: str,
                  params: Optional[dict] = None,
                  generated_on: Optional[str] = None) -> ExportedFile:
    """The report as a file, or an `ExportRefused` saying why not."""
    _refuse_unknown(report, fmt)
    doc = _document(report, fmt, svc=svc, db=db, firm_id=firm_id,
                    client_id=client_id, p=params or {})
    holder = load_holder(db, firm_id, client_id)
    firm = load_firm(db, firm_id)
    if fmt == XLSX:
        content = build_report_xlsx(doc, holder=holder, firm=firm, generated_on=generated_on)
        media = XLSX_MEDIA_TYPE
    else:
        content = build_report_pdf(doc, holder=holder, firm=firm, generated_on=generated_on)
        media = PDF_MEDIA_TYPE
    return ExportedFile(content=content, filename=filename_for(doc.file_stem, fmt),
                        media_type=media)
