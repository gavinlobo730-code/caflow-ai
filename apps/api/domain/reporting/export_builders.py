"""Turn the dict a report endpoint returns into a `ReportDocument` (accounting-16).

Every function here takes the SAME dict the screen's own endpoint serves —
`ReportingService.ledger`, `.trial_balance`, `.cash_flow_statement`,
`customer_statement_service.ar_aging` and `vendor_statement_service.ap_aging` —
and copies it across. That is the whole of the "the export and the screen
cannot disagree" argument: there is no second computation to disagree with.

WHAT IS CHECKED, AND WHAT IS ONLY SAID

    A LEDGER IS REFUSED if it does not foot. Its lines, opening balance and
    closing balance are three figures that must agree by construction (a
    running balance is the opening plus every line before it), so a mismatch
    means the page fetch was incomplete or the report is wrong — and a printed
    ledger that does not add up is the copy that goes to the bank.

    A TRIAL BALANCE AND A CASH FLOW STATEMENT ARE NOT REFUSED when they do not
    balance or reconcile. Both carry a verdict the screen shows (`is_balanced`,
    `reconciles`), and a CA opening one that is out wants the document in hand
    to chase the difference with. The verdict is printed as a note instead, in
    the same words the screen would use, never softened.

    AN AGEING IS REFUSED if its rows do not add to its own total, for the same
    reason a ledger is.

NOTHING IS COMPUTED. Where a sum is taken (a trial balance's opening and
period columns, which the report returns per row and never as a grand total) it
is a sum of the rows printed directly above it, so the document foots to
itself; no statutory figure is derived.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from domain.money_text import rupees_paise
from domain.reporting.export_document import (
    BALANCE, BODY, EMPHASIS, INT, MONEY, SECTION, TEXT,
    Column, ExportRefused, ReportDocument, Row, Table,
)

LEDGER = "ledger"
TRIAL_BALANCE = "trial-balance"
CASH_FLOW = "cash-flow"
AR_AGEING = "ar-ageing"
AP_AGEING = "ap-ageing"

#: A sheet's name may not carry these, nor exceed 31 characters.
_SHEET_BAD = re.compile(r"[\[\]:*?/\\]")


def slug(text: Optional[str], fallback: str = "report") -> str:
    """A filename-safe fragment. Lower-case, hyphen-separated, never empty."""
    out = re.sub(r"[^A-Za-z0-9]+", "-", str(text or "")).strip("-").lower()
    return out or fallback


def sheet_name(text: Optional[str], fallback: str = "Report") -> str:
    cleaned = _SHEET_BAD.sub(" ", str(text or "")).strip()
    return (cleaned or fallback)[:31]


def _nz(paise: Optional[int]) -> Optional[int]:
    """A zero debit or credit is an empty cell, not a printed 0.00."""
    value = int(paise or 0)
    return value if value else None


def _rs(paise: int) -> str:
    return f"Rs.{rupees_paise(paise)}"


def _basis_label(basis: Optional[str]) -> str:
    # Cash basis is management reporting only (IT Act s.145) and never feeds a
    # GST or ITR figure; the screen says so and so does the document.
    return ("Cash (management reporting only)" if (basis or "accrual") == "cash"
            else "Accrual")


# ── Ledger ────────────────────────────────────────────────────────────────────

def ledger_document(led: dict) -> ReportDocument:
    """One account's ledger for a window, opening to closing.

    `led` must carry EVERY line of the window — the caller pages the SQL
    function and merges — because the totals describe the whole window and a
    document of the first thousand lines under a full window's totals would
    simply not add up.
    """
    lines = list(led.get("lines") or [])
    opening = int(led.get("opening_balance_paise") or 0)
    closing = int(led.get("closing_balance_paise") or 0)
    total_dr = int(led.get("total_debit_paise") or 0)
    total_cr = int(led.get("total_credit_paise") or 0)

    sum_dr = sum(int(ln.get("debit_paise") or 0) for ln in lines)
    sum_cr = sum(int(ln.get("credit_paise") or 0) for ln in lines)
    if sum_dr != total_dr or sum_cr != total_cr:
        raise ExportRefused(
            "This ledger was not printed because its lines do not add up to its "
            f"totals (lines: {_rs(sum_dr)} debit / {_rs(sum_cr)} credit; report "
            f"totals: {_rs(total_dr)} / {_rs(total_cr)}). Some lines were not "
            "read; try again, and if it repeats the report itself needs a look.")
    if opening + total_dr - total_cr != closing:
        raise ExportRefused(
            "This ledger was not printed because its opening balance, its "
            "movement and its closing balance do not agree "
            f"({_rs(opening)} + {_rs(total_dr)} - {_rs(total_cr)} is not "
            f"{_rs(closing)}).")
    if lines and int(lines[-1].get("running_balance_paise") or 0) != closing:
        raise ExportRefused(
            "This ledger was not printed because its last running balance "
            "differs from its closing balance.")

    rows: list[Row] = [Row(("", "Opening balance", None, None, None, opening), EMPHASIS)]
    for ln in lines:
        rows.append(Row((
            str(ln.get("entry_date") or "")[:10],
            ln.get("narration") or "",
            ln.get("reference_no") or "",
            _nz(ln.get("debit_paise")),
            _nz(ln.get("credit_paise")),
            int(ln.get("running_balance_paise") or 0),
        )))
    rows.append(Row(("", "Total for the period", None, total_dr, total_cr, None), EMPHASIS))
    rows.append(Row(("", "Closing balance", None, None, None, closing), EMPHASIS))

    table = Table(
        columns=(
            Column("date", "Date", TEXT, 1.0),
            Column("particulars", "Particulars", TEXT, 2.8),
            # An invoice number is up to sixteen characters (CGST Rule 46(b)),
            # and a bank-posted entry's reference is longer still; this is wide
            # enough that an ordinary document number sits on one line.
            Column("ref", "Ref", TEXT, 1.7),
            Column("debit", "Debit", MONEY, 1.15),
            Column("credit", "Credit", MONEY, 1.15),
            Column("balance", "Balance", BALANCE, 1.35),
        ),
        rows=tuple(rows),
    )
    name = led.get("account_name") or ""
    code = led.get("account_code") or ""
    subject = f"{name} ({code})" if code and name else (name or code or "")
    start, end = led.get("start_date") or "", led.get("end_date") or ""
    notes = [
        "Balances are debit-positive; Dr and Cr mark the side of the running "
        "balance. The opening balance is the account's cumulative balance "
        "before the first day of the period.",
        "Lines are read from posted entries only.",
    ]
    if led.get("has_foreign_lines"):
        notes.append(
            "Some lines are in a foreign currency. Every amount here is the "
            "base-currency (INR) figure that drives the balance.")
    meta: list[tuple[str, str]] = []
    if led.get("account_type"):
        meta.append(("Account type", str(led["account_type"])))
    return ReportDocument(
        report_id=LEDGER, title="General Ledger", subject=subject,
        period=f"{start} to {end}" if start or end else "",
        tables=(table,), meta=tuple(meta), notes=tuple(notes),
        file_stem=f"ledger-{slug(name or code, 'account')}-{start}-{end}",
        sheet_name=sheet_name(name or "Ledger", "Ledger"),
    )


# ── Trial balance ─────────────────────────────────────────────────────────────

def trial_balance_document(tb: dict, *, basis: str = "accrual") -> ReportDocument:
    lines = list(tb.get("lines") or [])
    periodic = bool(tb.get("start_date"))
    as_of = tb.get("as_of_date") or ""
    grand_dr = int(tb.get("total_debit_paise") or 0)
    grand_cr = int(tb.get("total_credit_paise") or 0)

    if periodic:
        def col(key: str) -> int:
            return sum(int(ln.get(key) or 0) for ln in lines)
        rows = [Row((
            ln.get("account_code") or "", ln.get("account_name") or "",
            _nz(ln.get("opening_debit_paise")), _nz(ln.get("opening_credit_paise")),
            _nz(ln.get("period_debit_paise")), _nz(ln.get("period_credit_paise")),
            _nz(ln.get("total_debit_paise")), _nz(ln.get("total_credit_paise")),
        )) for ln in lines]
        rows.append(Row((
            "", "Total",
            _nz(col("opening_debit_paise")), _nz(col("opening_credit_paise")),
            _nz(col("period_debit_paise")), _nz(col("period_credit_paise")),
            grand_dr, grand_cr,
        ), EMPHASIS))
        columns = (
            Column("code", "Code", TEXT, 0.9),
            Column("account", "Account", TEXT, 3.2),
            Column("open_dr", "Opening Dr", MONEY, 1.3),
            Column("open_cr", "Opening Cr", MONEY, 1.3),
            Column("period_dr", "Period Dr", MONEY, 1.3),
            Column("period_cr", "Period Cr", MONEY, 1.3),
            Column("close_dr", "Closing Dr", MONEY, 1.3),
            Column("close_cr", "Closing Cr", MONEY, 1.3),
        )
        period = f"{tb.get('start_date')} to {as_of}"
    else:
        rows = [Row((
            ln.get("account_code") or "", ln.get("account_name") or "",
            ln.get("account_type") or "",
            _nz(ln.get("total_debit_paise")), _nz(ln.get("total_credit_paise")),
        )) for ln in lines]
        rows.append(Row(("", "Total", "", grand_dr, grand_cr), EMPHASIS))
        columns = (
            Column("code", "Code", TEXT, 0.9),
            Column("account", "Account", TEXT, 3.4),
            Column("type", "Type", TEXT, 1.3),
            Column("debit", "Debit", MONEY, 1.4),
            Column("credit", "Credit", MONEY, 1.4),
        )
        period = f"As at {as_of}"

    notes: list[str] = []
    if tb.get("is_balanced", grand_dr == grand_cr):
        notes.append("The trial balance balances: total debits equal total credits.")
    else:
        diff = int(tb.get("difference_paise") or (grand_dr - grand_cr))
        notes.append(
            f"THE TRIAL BALANCE DOES NOT BALANCE. Debits exceed credits by "
            f"{_rs(diff)}." if diff > 0 else
            f"THE TRIAL BALANCE DOES NOT BALANCE. Credits exceed debits by "
            f"{_rs(-diff)}.")
    if periodic:
        notes.append(
            "Profit and Loss accounts show the period's movement alone; the "
            "result of earlier years is carried in 'Surplus brought forward' "
            "where there is one.")
    if tb.get("period_gap"):
        notes.append(str(tb["period_gap"]))
    return ReportDocument(
        report_id=TRIAL_BALANCE, title="Trial Balance", subject="",
        period=period, tables=(Table(columns, tuple(rows)),),
        meta=(("Basis", _basis_label(basis)),), notes=tuple(notes),
        landscape=periodic,
        file_stem=f"trial-balance-{(tb.get('start_date') + '-to-') if periodic else ''}{as_of}",
        sheet_name="Trial Balance",
    )


# ── Cash flow ─────────────────────────────────────────────────────────────────

def _flow_label(line: dict) -> str:
    code, name = line.get("account_code") or "", line.get("account_name") or ""
    return f"{code}  {name}".strip() if code else name


def cash_flow_document(cf: dict, *, basis: str = "accrual") -> ReportDocument:
    rows: list[Row] = []
    for key in ("operating", "investing", "financing"):
        sec = cf.get(key) or {}
        label = sec.get("label") or key.title()
        rows.append(Row((label, None), SECTION))
        for line in sec.get("lines") or []:
            rows.append(Row((_flow_label(line), int(line.get("amount_paise") or 0))))
        rows.append(Row((f"Net {label[0].lower()}{label[1:]}",
                         int(sec.get("total_paise") or 0)), EMPHASIS))
    net = int(cf.get("net_change_paise") or 0)
    opening = int(cf.get("opening_cash_paise") or 0)
    closing = int(cf.get("closing_cash_paise") or 0)
    rows.append(Row(("Net increase / (decrease) in cash and bank", net), EMPHASIS))
    rows.append(Row(("Cash and bank at the start of the period", opening)))
    rows.append(Row(("Cash and bank at the end of the period", closing), EMPHASIS))

    notes = [
        "Prepared under AS-3 (indirect method) as presented in Schedule III to "
        "the Companies Act 2013. Investing and financing follow the actual cash "
        "legs of posted entries; operating cash is presented as the indirect "
        "reconciliation. Non-cash entries are left out of every section.",
    ]
    if cf.get("reconciles"):
        notes.append(
            "The statement reconciles: operating, investing and financing cash "
            "add to the net change, which equals closing less opening cash.")
    else:
        ties = (cf.get("operating_reconciliation") or {}).get("ties_out", True)
        why = ("" if ties else
               " The indirect operating reconciliation does not tie to the "
               "operating cash.")
        notes.append(
            "THE STATEMENT DOES NOT RECONCILE: operating, investing and "
            "financing cash do not agree with the change in cash and bank "
            f"balances.{why}")
    excluded = int(cf.get("non_cash_excluded_count") or 0)
    if excluded:
        notes.append(f"{excluded} non-cash entr{'y' if excluded == 1 else 'ies'} "
                     "left out of the statement.")
    start, end = cf.get("start_date") or "", cf.get("end_date") or ""
    return ReportDocument(
        report_id=CASH_FLOW, title="Cash Flow Statement", subject="",
        period=f"{start} to {end}",
        tables=(Table(columns=(Column("particulars", "Particulars", TEXT, 4.2),
                               Column("amount", "Amount", MONEY, 1.4)),
                      rows=tuple(rows)),),
        meta=(("Basis", _basis_label(basis)),), notes=tuple(notes),
        file_stem=f"cash-flow-{start}-to-{end}", sheet_name="Cash Flow",
    )


# ── Ageing (receivables and payables) ─────────────────────────────────────────

_BUCKETS = (("not_due", "Not due"), ("0-30", "0-30 days"), ("31-60", "31-60 days"),
            ("61-90", "61-90 days"), ("90+", "Over 90 days"))


def _sorted_by_age(docs: Iterable[dict], number_key: str) -> list[dict]:
    # The screen's default: longest-open first. Ties broken by document number
    # so the same data renders the same way on every read.
    return sorted(docs, key=lambda d: (-int(d.get("days_overdue") or 0),
                                       str(d.get(number_key) or "")))


def ageing_document(ageing: dict, *, payable: bool) -> ReportDocument:
    """Open invoices (or bills) by age, with the advances kept apart.

    The buckets are the OPERATIONAL ones a collections or payments run is worked
    from, not the Schedule III statutory columns; the note says so because the
    two are different questions and are not to be reconciled to one another.
    """
    docs_key, party_key, num_key, date_key = (
        ("bills", "vendor_name", "bill_no", "bill_date") if payable
        else ("invoices", "customer_name", "invoice_no", "invoice_date"))
    party_label = "Vendor" if payable else "Customer"
    doc_label = "Bill" if payable else "Invoice"
    docs = _sorted_by_age(ageing.get(docs_key) or [], num_key)
    total = int(ageing.get("total_outstanding_paise") or 0)
    buckets = ageing.get("buckets") or {}

    row_sum = sum(int(d.get("outstanding_paise") or 0) for d in docs)
    bucket_sum = sum(int(buckets.get(k) or 0) for k, _ in _BUCKETS)
    if row_sum != total or bucket_sum != total:
        raise ExportRefused(
            f"This ageing was not printed because its documents ({_rs(row_sum)}) "
            f"and its age buckets ({_rs(bucket_sum)}) do not add to its total "
            f"({_rs(total)}).")

    summary = Table(
        heading="Summary by age",
        columns=tuple(Column(k, label, MONEY, 1.0) for k, label in _BUCKETS)
        + (Column("total", "Total", MONEY, 1.1),),
        rows=(Row(tuple(int(buckets.get(k) or 0) for k, _ in _BUCKETS) + (total,),
                  EMPHASIS),),
    )
    detail_rows = [Row((
        d.get(party_key) or "", d.get(num_key) or "",
        str(d.get(date_key) or "")[:10], int(d.get("days_overdue") or 0),
        dict(_BUCKETS).get(d.get("aging_bucket"), str(d.get("aging_bucket") or "")),
        int(d.get("outstanding_paise") or 0),
    )) for d in docs]
    detail_rows.append(Row(("Total outstanding", "", "", None, "", total), EMPHASIS))
    detail = Table(
        heading=f"Open {doc_label.lower()}s",
        columns=(
            Column("party", party_label, TEXT, 2.6),
            Column("document", doc_label, TEXT, 1.5),
            Column("date", "Date", TEXT, 1.1),
            Column("days", "Days", INT, 0.7),
            Column("bucket", "Age", TEXT, 1.2),
            Column("outstanding", "Outstanding", MONEY, 1.4),
        ),
        rows=tuple(detail_rows),
    )
    tables = [summary, detail]

    adv = list(ageing.get("advances") or [])
    notes = [
        "Buckets are the operational ones, aged from the due date (the "
        f"{doc_label.lower()} date where there is none) — not the Schedule III "
        "statutory columns. Use the ageing schedule for the note to the "
        "balance sheet.",
    ]
    if adv:
        adv_total = int(ageing.get("total_advances_paise") or 0)
        # The report states the net itself (what ties to the control account);
        # `total - adv_total` is only the fallback for a payload that predates
        # the field, and is the same subtraction the report makes.
        stated = ageing.get("net_payable_paise" if payable else "net_receivable_paise")
        net = int(stated) if stated is not None else total - adv_total
        adv_rows = [Row((
            a.get("party_name") or "", a.get("document_no") or "",
            str(a.get("document_date") or "")[:10], int(a.get("days_old") or 0),
            dict(_BUCKETS).get(a.get("aging_bucket"), str(a.get("aging_bucket") or "")),
            int(a.get("unapplied_paise") or 0),
        )) for a in adv]
        adv_rows.append(Row(("Less advances on account", "", "", None, "", adv_total), EMPHASIS))
        adv_rows.append(Row((("Net payable" if payable else "Net receivable"),
                             "", "", None, "", net), EMPHASIS))
        tables.append(Table(
            heading=("Unapplied payments to vendors" if payable
                     else "Unapplied receipts from customers"),
            columns=(
                Column("party", party_label, TEXT, 2.6),
                Column("document", "Payment" if payable else "Receipt", TEXT, 1.5),
                Column("date", "Date", TEXT, 1.1),
                Column("days", "Days", INT, 0.7),
                Column("bucket", "Age", TEXT, 1.2),
                Column("amount", "Unapplied", MONEY, 1.4),
            ),
            rows=tuple(adv_rows),
        ))
        notes.append(
            "Advances are money that no document has absorbed. They are shown "
            "apart and never enter the buckets, because an advance is not an "
            "open document and adding it would misstate the note.")
    for gap in ageing.get("advance_gaps") or []:
        notes.append(str(gap))
    if ageing.get("by_currency"):
        notes.append(
            "Foreign-currency documents are included at their base-currency "
            "(INR) outstanding, which is the figure that ties to the ledger.")
    as_of = ageing.get("as_of") or ""
    kind = "payables" if payable else "receivables"
    return ReportDocument(
        report_id=AP_AGEING if payable else AR_AGEING,
        title=("Accounts Payable Ageing" if payable else "Accounts Receivable Ageing"),
        subject="", period=f"As at {as_of}", tables=tuple(tables),
        notes=tuple(notes), landscape=False,
        file_stem=f"ageing-{kind}-{as_of}",
        sheet_name=("AP Ageing" if payable else "AR Ageing"),
    )
