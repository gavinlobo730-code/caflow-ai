"""
Bank reconciliation statement PDF (Banking B.4 / Tier 2.6).

The CSV export has always existed, but a reconciliation is the thing a CA signs
off and hands to a client or an auditor, and a spreadsheet is not that document.
This renders the same report the screen and the CSV show — one source
(bank_reconciliation_service.report), three presentations.

Reuses the invoice PDF stack (reportlab, _load_firm, _paise_to_rupee_str), same
as statement_pdf_service. Every amount arrives as integer paise and is formatted
for display only — no arithmetic happens here.

NOT a statutory document: it evidences that a bank account's posted ledger
agrees with its statement for a period. It carries no accounting entries.
"""
from __future__ import annotations

import io
import logging

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from services.invoice_pdf_service import _load_firm, _paise_to_rupee_str

logger = logging.getLogger("caflow.services")


def _amount(paise) -> str:
    value = int(paise or 0)
    return _paise_to_rupee_str(value) if value else ""


def build_reconciliation_pdf(report: dict, firm: dict) -> bytes:
    session = report["reconciliation"]
    summary = report["summary"]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm,
        leftMargin=16 * mm, rightMargin=16 * mm, title="Bank Reconciliation Statement")
    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Title"], fontSize=16, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=9,
                         textColor=colors.HexColor("#64748B"))
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9)
    elems = []

    elems.append(Paragraph(firm.get("name") or "Chartered Accountant", h))
    elems.append(Paragraph("Bank Reconciliation Statement", sub))
    elems.append(Spacer(1, 8))

    status = str(session.get("status") or "").replace("_", " ").title()
    meta = [
        [Paragraph(f"<b>Bank account:</b> {session.get('account_no') or '—'}", small),
         Paragraph(f"<b>Period:</b> {session.get('statement_start_date')} to "
                   f"{session.get('statement_end_date')}", small)],
        [Paragraph(f"<b>Status:</b> {status}", small),
         Paragraph(f"<b>Completed:</b> {str(session.get('completed_at') or '—')[:10]}", small)],
    ]
    mt = Table(meta, colWidths=[89 * mm, 89 * mm])
    mt.setStyle(TableStyle([("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                            ("TOPPADDING", (0, 0), (-1, -1), 1)]))
    elems.append(mt)

    # A reopened period must say so on the face of the document — otherwise the
    # PDF looks identical to one that was certified once and never touched.
    if int(session.get("reopen_count") or 0) > 0:
        elems.append(Spacer(1, 4))
        elems.append(Paragraph(
            f"<b>Reopened {session['reopen_count']} time(s).</b> Last reopened "
            f"{str(session.get('reopened_at') or '')[:10]}"
            + (f" — {session.get('reopen_reason')}" if session.get("reopen_reason") else ""),
            sub))
    elems.append(Spacer(1, 10))

    # ── Tie-out ─────────────────────────────────────────────────────────────
    elems.append(Paragraph("Balance tie-out", ParagraphStyle(
        "sec", parent=styles["Heading3"], fontSize=10, spaceAfter=4)))
    tie_rows = [
        ["Opening balance", _paise_to_rupee_str(summary["opening_balance_paise"])],
        ["Add: Deposits reconciled", _paise_to_rupee_str(summary["deposits_paise"])],
        ["Less: Withdrawals reconciled", _paise_to_rupee_str(summary["withdrawals_paise"])],
        # WHAT the adjustment is, on the same line as the figure (BANK-05).
        # This document is what a CA hands to a client or an auditor, and an
        # "Adjustments ₹47,300.00" on it that explains nothing is the defect.
        # A reason is mandatory for any non-zero figure (migration 355), so the
        # bare label only ever appears beside a zero.
        [("Adjustments" if not summary["adjustments_paise"]
          else f"Adjustments — {session.get('adjustments_reason') or 'reason not recorded'}"),
         _paise_to_rupee_str(summary["adjustments_paise"])],
        ["Reconciled book balance", _paise_to_rupee_str(summary["reconciled_book_balance_paise"])],
        ["Statement closing balance", _paise_to_rupee_str(summary["statement_closing_balance_paise"])],
        ["Difference", _paise_to_rupee_str(summary["difference_paise"])],
    ]
    tie = Table(tie_rows, colWidths=[120 * mm, 58 * mm])
    tie.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, 4), (-1, 4), "Helvetica-Bold"),
        ("FONTNAME", (0, 5), (-1, 5), "Helvetica-Bold"),
        ("FONTNAME", (0, 6), (-1, 6), "Helvetica-Bold"),
        ("LINEABOVE", (0, 4), (-1, 4), 0.5, colors.HexColor("#94A3B8")),
        ("LINEABOVE", (0, 6), (-1, 6), 0.5, colors.HexColor("#94A3B8")),
        ("BACKGROUND", (0, 6), (-1, 6),
         colors.HexColor("#DCFCE7") if summary["reconciles"] else colors.HexColor("#FEE2E2")),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elems.append(tie)
    elems.append(Spacer(1, 6))
    elems.append(Paragraph(
        "The statement ties out to the reconciled book balance."
        if summary["reconciles"] else
        "<b>This statement does not tie out.</b>", small))
    elems.append(Spacer(1, 12))

    # ── The Bank Reconciliation Statement itself (BANK-04) ──────────────────
    # Until this existed, everything above was the whole document: the tie-out
    # and three buckets of STATEMENT lines, under a title that promises the
    # accountant's two-sided statement. A cheque issued and entered in the books
    # but not yet presented at the bank had no row anywhere in it, and neither
    # did a deposit banked but not yet credited — which are the two items a BRS
    # is FOR. The tie-out stays above as the internal check; this is the working
    # paper.
    brs = report.get("brs")
    if brs:
        elems.append(Paragraph("Bank Reconciliation Statement", ParagraphStyle(
            "sec", parent=styles["Heading3"], fontSize=10, spaceAfter=4)))
        brs_rows = [["Balance as per Cash Book (books)",
                     _paise_to_rupee_str(brs["book_balance_paise"])]]

        def _bucket_rows(key: str, label: str, sign: str) -> None:
            b = brs.get(key) or {}
            if not b.get("count"):
                return
            brs_rows.append([f"{sign} {label} ({b['count']})",
                             _paise_to_rupee_str(b["total_paise"])])
            for it in (b.get("items") or []):
                ref = f" [{it['reference_no']}]" if it.get("reference_no") else ""
                brs_rows.append([
                    f"      {it['date']}  {(it.get('particulars') or '')[:58]}{ref}",
                    _paise_to_rupee_str(it["amount_paise"])])
            if b["listed"] < b["count"]:
                # Never a silent cap. A truncated list that read as complete
                # would be worse than a long one.
                brs_rows.append([f"      … and {b['count'] - b['listed']} more, "
                                 f"included in the total above", ""])

        _bucket_rows("unpresented_cheques", "Cheques issued but not yet presented", "Add:")
        _bucket_rows("deposits_in_transit", "Deposits banked but not yet credited", "Less:")
        _bucket_rows("bank_credits_not_in_books", "Credited by the bank, not in the books", "Add:")
        _bucket_rows("bank_debits_not_in_books", "Debited by the bank, not in the books", "Less:")
        brs_rows.append(["Balance as per Pass Book (bank)",
                         _paise_to_rupee_str(brs["computed_bank_balance_paise"])])
        if brs.get("statement_balance_paise") is not None:
            brs_rows.append(["Balance per the statement",
                             _paise_to_rupee_str(brs["statement_balance_paise"])])
            brs_rows.append(["Difference", _paise_to_rupee_str(brs["difference_paise"])])
        brs_table = Table(brs_rows, colWidths=[130 * mm, 48 * mm], repeatRows=1)
        brs_style = [
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("LINEABOVE", (0, len(brs_rows) - (3 if brs.get("statement_balance_paise") is not None else 1)),
             (-1, len(brs_rows) - (3 if brs.get("statement_balance_paise") is not None else 1)),
             0.5, colors.HexColor("#94A3B8")),
            ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        if brs.get("statement_balance_paise") is not None:
            brs_style.append(("FONTNAME", (0, len(brs_rows) - 3), (-1, len(brs_rows) - 1),
                              "Helvetica-Bold"))
            brs_style.append((
                "BACKGROUND", (0, len(brs_rows) - 1), (-1, len(brs_rows) - 1),
                colors.HexColor("#DCFCE7") if brs.get("agrees") else colors.HexColor("#FEE2E2")))
        else:
            brs_style.append(("FONTNAME", (0, len(brs_rows) - 1), (-1, len(brs_rows) - 1),
                              "Helvetica-Bold"))
        brs_table.setStyle(TableStyle(brs_style))
        elems.append(brs_table)
        if brs.get("gap"):
            elems.append(Spacer(1, 4))
            elems.append(Paragraph(f"<b>{brs['gap']}</b>", sub))
        elems.append(Spacer(1, 12))

    # ── Line sections ───────────────────────────────────────────────────────
    def section(title: str, lines: list[dict]) -> None:
        elems.append(Paragraph(f"{title} ({len(lines)})", ParagraphStyle(
            "sec", parent=styles["Heading3"], fontSize=10, spaceAfter=4)))
        if not lines:
            elems.append(Paragraph("None.", sub))
            elems.append(Spacer(1, 8))
            return
        rows = [["Date", "Description", "Reference", "Debit", "Credit"]]
        for t in lines:
            rows.append([
                t.get("transaction_date", ""), (t.get("description") or "")[:60],
                t.get("reference_no") or "",
                _amount(t.get("debit_paise")), _amount(t.get("credit_paise")),
            ])
        table = Table(rows, colWidths=[22 * mm, 82 * mm, 30 * mm, 22 * mm, 22 * mm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        elems.append(table)
        elems.append(Spacer(1, 10))

    section("Reconciled", report.get("reconciled") or [])
    section("Unreconciled", report.get("unreconciled") or [])
    if report.get("exceptions"):
        section("Exceptions", report["exceptions"])

    elems.append(Paragraph(
        "Prepared from posted accounting records. This statement evidences agreement "
        "between the bank account's ledger and its statement for the period; it is not "
        "a tax document and carries no accounting entries. Amounts in INR.", sub))

    doc.build(elems)
    return buf.getvalue()


def get_reconciliation_pdf(db, firm_id: str, recon_id: str) -> tuple[bytes, str]:
    """Render the reconciliation report as a PDF. For a COMPLETED session this
    serves the FROZEN snapshot — the same figures the CA certified — because
    bank_reconciliation_service.report returns the snapshot for completed
    sessions. A PDF that recomputed live would be a different document from the
    one that was signed off."""
    from services.bank_reconciliation_service import bank_reconciliation_service
    report = bank_reconciliation_service.report(db, firm_id, recon_id)
    if not report.get("brs"):
        # A completed session frozen before migration 356 has no statement in its
        # snapshot, and a mutable one never does. Computing it here keeps the
        # document whole; failing to compute it must not withhold the PDF, which
        # is the same document it has always been plus a section.
        try:
            report = {**report,
                      "brs": bank_reconciliation_service.brs(db, firm_id, recon_id)}
        except Exception as e:                                    # noqa: BLE001
            from core.observability import capture_soft_failure
            capture_soft_failure(e, operation="bank_reconciliation_pdf_brs",
                                 reconciliation_id=recon_id, firm_id=firm_id)
    firm = _load_firm(firm_id)
    session = report["reconciliation"]
    account = (session.get("account_no") or "account").replace(" ", "-")
    filename = (f"bank-reconciliation-{account}-"
                f"{session.get('statement_start_date')}-to-"
                f"{session.get('statement_end_date')}.pdf")
    return build_reconciliation_pdf(report, firm), filename
