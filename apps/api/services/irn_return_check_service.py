"""
The reads behind `domain/gst/irn_against_return` (POST-A-066): the period's GSTR-1 as the books build it, the period's live IRN
records, and the invoices those records are linked to.

THE RETURN IS THE BUILD ITSELF. The invoices "this return declares" are read off `gst_return_service.gstr1_from_books`'s own payload
(its B2B, export and B2CL tables), so the check reads the return the way the build makes it; it is built again for the check, so the
answer is about the books as they stand now (an invoice changed since the CA built the return is answered as it is now). It asks the
build without the ledger reconciliation and the Table 13 coverage, which are about other things and are the build's heaviest reads.

THE RECORDS ARE THE PERIOD'S. A live record belongs to the period by its own invoice date or by its linked invoice's, so both are
read: the records dated in the window, and the records linked to an invoice dated in it. The invoices a record is linked to that
fall outside the window are then read by id, so a record whose invoice moved to another period is reported as such. Every read
names the firm and the client and pages through `core.db_paging`.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Nothing here reaches the IRP or the portal.
"""
from __future__ import annotations

from typing import Optional

from core.db_paging import fetch_all, fetch_all_in
from domain.gst import irn_against_return as rule
from domain.gst import return_period
from services import gst_return_service

# Each read names its columns as a literal, so the column check (`tests/test_backend_columns_exist_pg.py`) can read every one of them.


def check(db, firm_id: str, client_id: str, period: str, gstin: str, frequency: Optional[str] = None) -> dict:
    """The period's live IRN records against the GSTR-1 the books build for it."""
    window = return_period.resolve(period, frequency)
    built = gst_return_service.gstr1_from_books(db, firm_id, client_id, window.key, gstin, frequency=frequency,
                                                reconcile_to_ledger=False, with_table_13_coverage=False)
    in_window = fetch_all(
        lambda: (db.table("client_sales_invoices").select("id, invoice_no, invoice_date, status, deleted_at, is_opening")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .gte("invoice_date", window.start).lte("invoice_date", window.end)),
        key="id", label="irn_return_check.invoices")
    invoices = {str(r["id"]): r for r in in_window}
    by_date = fetch_all(
        lambda: (db.table("einvoice_records").select("id, sales_invoice_id, invoice_number, invoice_date, status, irn")
                 .eq("firm_id", firm_id).eq("client_id", client_id).eq("status", rule.LIVE)
                 .gte("invoice_date", window.start).lte("invoice_date", window.end)),
        key="id", label="irn_return_check.records_by_date")
    by_invoice = fetch_all_in(
        lambda: (db.table("einvoice_records").select("id, sales_invoice_id, invoice_number, invoice_date, status, irn")
                 .eq("firm_id", firm_id).eq("client_id", client_id).eq("status", rule.LIVE)),
        "sales_invoice_id", list(invoices), label="irn_return_check.records_by_invoice")
    records = {str(r["id"]): r for r in [*by_date, *by_invoice]}
    elsewhere = {str(r["sales_invoice_id"]) for r in records.values()
                 if r.get("sales_invoice_id") and str(r["sales_invoice_id"]) not in invoices}
    for r in fetch_all_in(
            lambda: (db.table("client_sales_invoices").select("id, invoice_no, invoice_date, status, deleted_at, is_opening")
                     .eq("firm_id", firm_id).eq("client_id", client_id)),
            "id", elsewhere, label="irn_return_check.linked_invoices"):
        invoices[str(r["id"])] = r
    # An unlinked record names its invoice by number (invoice numbers are unique per client, migration 151), so the invoices carrying
    # those numbers are read wherever they are dated: an unlinked record whose invoice is cancelled or in another period says so.
    numbers = {str(r.get("invoice_number") or "").strip() for r in records.values() if not r.get("sales_invoice_id")}
    numbers.discard("")
    for r in fetch_all_in(
            lambda: (db.table("client_sales_invoices").select("id, invoice_no, invoice_date, status, deleted_at, is_opening")
                     .eq("firm_id", firm_id).eq("client_id", client_id)),
            "invoice_no", numbers, label="irn_return_check.invoices_by_number"):
        invoices[str(r["id"])] = r
    answer = rule.compare(built.get("payload") or {}, records.values(), invoices, window.start, window.end)
    return {"period": window.key, "from": window.start, "to": window.end, "gstin": gstin, **answer}
