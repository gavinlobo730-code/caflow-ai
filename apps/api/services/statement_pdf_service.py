"""
Statement of account PDF — customer OR vendor, one builder.

The vendor half was added on 25-09: `GET /api/vendors/{id}/statement` had
been built, tested and reachable by NOBODY, while the customer twin had a
whole Statements tab with a PDF and an email. The AP mirror of a live AR
feature, which is a shape this repository has found before.

PARAMETERISED RATHER THAN COPIED. The two statements differ in exactly four
places — whose account it is, what the party is called, which totals are
printed, and WHICH SIGN MEANS WHAT — so a second builder would be one
formatting change away from two documents that look like two products.
`StatementKind` holds those four and nothing else.

Reuses the invoice PDF stack (reportlab, _load_firm, _paise_to_rupee_str). This
is NOT a tax document and carries NO accounting entries — it renders the opening
balance, the period's invoices/receipts/credit notes with a running balance, and
the closing outstanding. All amounts arrive as integer paise (display only).
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from services import pdf_style

from services.invoice_pdf_service import _load_firm, _paise_to_rupee_str
from services.customer_statement_service import customer_statement_service
from services.pdf_page_furniture import numbered

logger = logging.getLogger("caflow.services")


def _bal(paise: int, positive_side: str = "Dr") -> str:
    """Signed balance as 'x,xxx.xx Dr|Cr'.

    ⚠️ THE SENSE IS NOT THE SAME ON BOTH STATEMENTS AND IT IS NOT COSMETIC. On a
    CUSTOMER statement the running balance is debit-positive: a positive figure
    is money the customer owes, so it prints Dr. On a VENDOR statement
    `vendor_statement_service.build_statement` runs it CREDIT-positive (a bill
    increases it), so the same positive figure is money the CLIENT owes, and
    printing Dr there would state the debt against the wrong party on a
    document somebody reconciles from.
    """
    side = positive_side if paise >= 0 else ("Cr" if positive_side == "Dr" else "Dr")
    return f"{_paise_to_rupee_str(abs(paise))} {side}"


@dataclass(frozen=True)
class StatementKind:
    """The four things that differ between a customer and a vendor statement."""

    #: The key the statement dict files the counterparty under.
    party_key: str
    #: What the counterparty is called, on the subtitle and the meta row.
    party_label: str
    #: Which side a POSITIVE running balance is. See `_bal`.
    positive_side: str
    #: The three totals printed under the table, as (label, key) pairs. Their
    #: keys differ because the two services name them for their own direction.
    totals: tuple[tuple[str, str], ...]
    #: The closing row's label — what is OWED, and by whom, in one word.
    closing_label: str


CUSTOMER = StatementKind(
    party_key="customer",
    party_label="Customer",
    positive_side="Dr",
    totals=(("Invoiced", "invoiced_paise"), ("Received", "received_paise"),
            ("Credits", "credited_paise")),
    closing_label="Closing Outstanding",
)

VENDOR = StatementKind(
    party_key="vendor",
    party_label="Vendor",
    # Credit-positive: a bill increases what the client owes.
    positive_side="Cr",
    totals=(("Billed", "billed_paise"), ("Paid", "paid_paise"),
            ("Debit notes", "debited_paise")),
    closing_label="Closing Payable",
)


def build_statement_pdf(statement: dict, account_holder: dict, party: dict,
                        kind: StatementKind = CUSTOMER) -> bytes:
    """A statement of account, headed by WHOSE ACCOUNT IT IS.

    The second argument used to be the CA FIRM, and the letterhead read the
    practice's name. It is the wrong party: the customer owes money to the
    CLIENT, the practice is not to it, and a statement demanding payment under
    a chartered accountant's name misstates who is owed. Same confusion the
    sales-invoice PDF carried until 2026-09-08, and the same fix — the party is
    passed in rather than assumed, and the caller loads the `clients` row.

    Lower stakes than the invoice, and worth saying why: this is not a Rule 46
    document, it carries no GSTIN and claims no credit. What it does carry is a
    demand for money, and the name on that has to be the name of the creditor.

    On the CLIENT-PORTAL path the same lookup correctly names the practice: the
    firm's own fee invoices live under its internal practice client (migration
    074), which is a `clients` row carrying the firm's name.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            title=f"{kind.party_label} Statement")
    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Title"], fontSize=16, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=9, textColor=pdf_style.C_HINT)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9)
    elems = []

    # The client's own registered name, in the order the ledger prefers it.
    holder_name = (account_holder.get("legal_name")
                   or account_holder.get("trade_name")
                   or account_holder.get("client_name")
                   # `name` is the shape the firm row uses; kept so a caller
                   # that still passes one renders rather than showing a blank
                   # letterhead, which is the one outcome worse than a wrong
                   # name.
                   or account_holder.get("name")
                   or "Statement of Account")
    period = statement["period"]
    elems.append(Paragraph(holder_name, h))
    elems.append(Paragraph(f"{kind.party_label} Statement of Account", sub))
    elems.append(Spacer(1, 8))

    cust = statement[kind.party_key]
    meta = [
        [Paragraph(f"<b>{kind.party_label}:</b> {cust.get('name') or ''}", small),
         Paragraph(f"<b>Period:</b> {period['start_date']} to {period['end_date']}", small)],
        [Paragraph(f"<b>GSTIN:</b> {cust.get('gstin') or '—'}", small),
         Paragraph(f"<b>Email:</b> {cust.get('email') or '—'}", small)],
    ]
    mt = Table(meta, colWidths=[95 * mm, 83 * mm])
    mt.setStyle(TableStyle([("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 1)]))
    elems.append(mt)
    elems.append(Spacer(1, 10))

    rows = [["Date", "Particulars", "Ref", "Debit", "Credit", "Balance"]]
    rows.append(["", "Opening Balance", "", "", "", _bal(statement["opening_balance_paise"], kind.positive_side)])
    for t in statement["transactions"]:
        rows.append([
            t["date"], t["particulars"], t.get("reference") or "",
            _paise_to_rupee_str(t["debit_paise"]) if t["debit_paise"] else "",
            _paise_to_rupee_str(t["credit_paise"]) if t["credit_paise"] else "",
            _bal(t["running_balance_paise"], kind.positive_side),
        ])
    rows.append(["", kind.closing_label, "", "", "", _bal(statement["closing_balance_paise"], kind.positive_side)])

    table = Table(rows, colWidths=[20 * mm, 70 * mm, 24 * mm, 22 * mm, 22 * mm, 20 * mm], repeatRows=1)
    # The opening-balance row sits directly under the header and the closing
    # balance at the foot, so the zebra runs between them rather than over
    # them — which is why `data_table_style` takes both bounds.
    table.setStyle(TableStyle(
        pdf_style.data_table_style(
            font_size=8, padding=3, right_align_from=3,
            first_body_row=2, last_body_row=-2)
        + pdf_style.emphasis_row(1)
        + pdf_style.emphasis_row(-1)
        + [("LINEBELOW", (0, 0), (-1, 0), 0.5, pdf_style.C_INK)]
    ))
    elems.append(table)
    elems.append(Spacer(1, 8))

    tot = statement["totals"]
    elems.append(Paragraph(" &nbsp;|&nbsp; ".join(
        f"{label}: Rs.{_paise_to_rupee_str(tot.get(key) or 0)}"
        for label, key in kind.totals), sub))
    elems.append(Spacer(1, 6))
    elems.append(Paragraph("This is a statement of account, not a tax invoice. Amounts in INR.", sub))

    numbered(doc, elems)
    return buf.getvalue()


def load_account_holder(db, firm_id: str, client_id: str) -> dict:
    """The `clients` row the statement is issued BY — firm-scoped, and refused
    rather than defaulted.

    Falling back to the firm is what produced the defect: a statement of
    account headed with the CA practice's name, sent to the client's customer,
    demanding money the practice is not owed. A missing client row is a
    question, not a letterhead.
    """
    row = (db.table("clients")
           .select("id,client_name,legal_name,trade_name,gstin,pan")
           .eq("id", client_id).eq("firm_id", firm_id)
           .maybe_single().execute())
    holder = getattr(row, "data", None) or {}
    if not holder:
        raise ValueError(
            f"Client {client_id} not found for firm {firm_id} — a statement of "
            "account cannot be issued without knowing whose account it is."
        )
    return holder


def get_customer_statement_pdf(db, firm_id, client_id, customer_id, start, end) -> tuple[bytes, str]:
    statement = customer_statement_service.generate(db, firm_id, client_id, customer_id, start, end)
    pdf = build_statement_pdf(statement, load_account_holder(db, firm_id, client_id),
                              statement["customer"])
    name = (statement["customer"].get("name") or "customer").replace(" ", "-").lower()
    filename = f"statement-{name}-{start}-{end}.pdf"
    return pdf, filename


def get_vendor_statement_pdf(db, firm_id, client_id, vendor_id, start, end) -> tuple[bytes, str]:
    """The supplier's account, as the CLIENT's books have it.

    `load_account_holder` is the same call and for the same reason: the account
    holder is the CLIENT, not the practice. A vendor statement is a
    RECONCILIATION document rather than a demand — the supplier sends theirs,
    the CA compares — so nothing here chases anybody, and there is deliberately
    no email path: `customer_statement_service` carries `record_delivery`
    because that side pursues money, and adding a delivery log for this one
    would be a table and a migration rather than the unwiring this fixes.
    """
    from services.vendor_statement_service import vendor_statement_service
    statement = vendor_statement_service.generate(db, firm_id, client_id, vendor_id, start, end)
    pdf = build_statement_pdf(statement, load_account_holder(db, firm_id, client_id),
                              statement["vendor"], VENDOR)
    name = (statement["vendor"].get("name") or "vendor").replace(" ", "-").lower()
    filename = f"vendor-statement-{name}-{start}-{end}.pdf"
    return pdf, filename
