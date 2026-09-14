"""Fetches what `domain/gst/rcm_documents.py` decides with, numbers the
document, and writes it (PUR-19).

The split is this file's whole point: the domain module is pure and takes
facts, this one reads them. What it refuses to do is decide anything — whether
a document is due, what its particulars say and what could not be stated are
all the domain module's answers.

NUMBERING IS THE SALES SERIES' RULE, NOT A SECOND ONE.
`domain/gst/invoice_series.py` is CGST Rule 46(b) as code and Rule 52(b) is
worded identically, so both kinds go through it — the sixteen-character and
character-set REFUSALS, and the sequence-break WARNING. What differs is the
SERIES HEAD: each kind runs its own, because Rule 46(b) allows "one or multiple
series" and putting a self-invoice number into the outward sales sequence would
place a number in the GSTR-1 series that no outward supply carries.

BOTH DOCUMENTS ASK THE PERIOD LOCK, and that is not belt-and-braces. A
self-invoice is the document Rule 36(1)(b) makes the input credit rest on, so
issuing one dated inside a period whose GSTR-3B is filed changes what that
return should have said — the same reasoning the bill itself carries.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import HTTPException

from core.db_paging import fetch_all
from core.ist_clock import ist_fy_label, ist_today
from domain.gst import rcm_documents as rd
from domain.gst.invoice_series import (
    SeriesSettings,
    format_number,
    format_violation,
    next_sequence,
    split_number,
)

_logger = logging.getLogger("caflow.rcm_documents")

#: The columns a document read must carry. Named so a query can be checked
#: against them — a read that omits `particulars_json` hands the screen a
#: document with no particulars, which is not a document.
DOCUMENT_COLUMNS = (
    "id, firm_id, client_id, vendor_id, kind, purchase_bill_id, "
    "purchase_payment_id, document_no, document_date, particulars_json, "
    "taxable_paise, cgst_paise, sgst_paise, igst_paise, cess_paise, "
    "amount_paid_paise, notes, created_at, created_by, deleted_at"
)

#: What the vendor block and the s.31(3)(f) question both need.
VENDOR_COLUMNS = (
    "id, name, gstin, state_code, pan, address, city, state, pincode, "
    "gst_registration_status"
)

#: How many numbers to read back before taking the highest. The same figure and
#: the same reasoning as `sales_numbering_service._SEQUENCE_WINDOW`: one row
#: would do while every number is zero-padded to one width, and a window
#: survives the series picking up an unpadded number from an import.
_SEQUENCE_WINDOW = 50


def _series_settings(kind: str) -> SeriesSettings:
    """The series for one kind.

    NOT read from `invoice_settings`: that row is the firm's OUTWARD series and
    these two are different series by construction. Defaults in code, with the
    number editable at issue — which is the mode a practice runs anyway
    (Tally's "Automatic (Manual Override)"). Adding settings columns later is
    additive and nothing here has to move.
    """
    return SeriesSettings(
        prefix=rd.DEFAULT_PREFIX_FOR_KIND[kind].rstrip("/"),
        include_financial_year=True,
        sequence_length=3,
        starting_number=1,
        manual_override_allowed=True,
    )


def _numbers_in_series(db, firm_id: str, client_id: str, kind: str,
                       head: str) -> list[str]:
    """The window of numbers already used in this kind's series, highest first.

    Firm- AND client-scoped, because the uniqueness index is and because the
    service-role key bypasses RLS — the `.eq("firm_id", …)` is the primary
    isolation control, not a convenience.
    """
    if db is None or not head:
        return []
    try:
        resp = (db.table("rcm_documents").select("document_no")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("kind", kind)
                .is_("deleted_at", "null")
                .like("document_no", f"{head}%")
                .order("document_no", desc=True)
                .limit(_SEQUENCE_WINDOW).execute())
    except Exception:  # noqa: BLE001
        # A numbering read that fails must not stop a statutory document being
        # issued. The number stays editable, so the worst case is a suggestion
        # the CA overwrites.
        _logger.warning("rcm numbering: could not read the %s series", kind)
        return []
    return [r.get("document_no") or "" for r in (resp.data or [])]


def suggest_number(db, *, firm_id: str, client_id: str, kind: str,
                   document_date=None,
                   existing: Optional[list[str]] = None) -> str:
    """The next number in this kind's series, for the form to pre-fill.

    A SUGGESTION. What is written is whatever the request carries, refused only
    where Rule 46(b)/52(b) refuses it.
    """
    fy = ist_fy_label(document_date)
    settings = _series_settings(kind)
    head, _ = split_number(format_number(settings, fy, 1))
    used = (existing if existing is not None
            else _numbers_in_series(db, firm_id, client_id, kind, head))
    return format_number(settings, fy, next_sequence(used, settings, fy))


# ── The parties ──────────────────────────────────────────────────────────────

def _address_of(row: dict[str, Any]) -> str:
    """One address line from the parts a row carries.

    Deliberately not `invoice_pdf_service._address_lines`: that returns the
    lines a PDF paragraph wants and this is a domain value stored on the
    document. Same parts, one string, and the PDF re-wraps it.
    """
    parts = [row.get("address") or row.get("address_line1"),
             row.get("address_line2"), row.get("city"),
             row.get("state"), row.get("pincode")]
    return ", ".join(str(p).strip() for p in parts if p and str(p).strip())


def vendor_party(vendor: dict[str, Any], registration: str) -> rd.Party:
    """The supplier block.

    The GSTIN travels ONLY where the supplier is registered. On a self-invoice
    that is never — the document exists because they are not — and on a payment
    voucher Rule 52(a) asks for it "if registered", so an unregistered
    supplier's block correctly has none.
    """
    return rd.Party(
        name=(vendor.get("name") or "").strip(),
        address=_address_of(vendor),
        gstin=(((vendor.get("gstin") or "").strip() or None)
               if registration == rd.REGISTERED else None),
        state_code=((vendor.get("state_code") or "").strip() or None),
    )


def client_party(client: dict[str, Any]) -> rd.Party:
    """The recipient block — the client, who is the person issuing this.

    `legal_name` first, the same choice `invoice_pdf_service._client_party`
    makes for a supplier block: Rule 46 wants the name the GST registration is
    held in.
    """
    return rd.Party(
        name=(client.get("legal_name") or client.get("client_name")
              or client.get("name") or "").strip(),
        address=_address_of(client),
        gstin=((client.get("gstin") or "").strip() or None),
        state_code=((client.get("state_code") or "").strip() or None),
    )


# ── Reads ────────────────────────────────────────────────────────────────────

# EVERY TABLE AND EVERY COLUMN IS A LITERAL AT THE CALL SITE, deliberately.
# A `_one(db, table, columns, ...)` helper read better and was invisible to
# `tests/test_backend_columns_exist_pg.py`, which resolves neither a variable
# table name nor a module constant — and that guard is what caught the two
# columns this module had wrong (`purchase_bill_lines.bill_id` and
# `purchase_payment_allocations.allocated_paise`), both of which fail SILENTLY.
# A helper that hides the names from it buys tidiness with the one check that
# would notice.

def _first(rows) -> Optional[dict]:
    rows = rows or []
    return rows[0] if rows else None


def _bill_or_none(db, firm_id: str, bill_id: str) -> Optional[dict]:
    return _first(db.table("purchase_bills").select(
        "id, firm_id, client_id, vendor_id, bill_no, bill_date, "
        "is_reverse_charge, is_interstate, taxable_amount_paise, "
        "cgst_paise, sgst_paise, igst_paise, cess_paise, total_gst_paise, "
        "total_paise, deleted_at")
        .eq("id", bill_id).eq("firm_id", firm_id).limit(1).execute().data)


def _bill(db, firm_id: str, bill_id: str) -> dict:
    row = _bill_or_none(db, firm_id, bill_id)
    if not row or row.get("deleted_at"):
        raise HTTPException(status_code=404, detail="Purchase bill not found.")
    return row


def _bill_lines(db, firm_id: str, bill_id: str) -> list[dict]:
    """Paged: one row per line, and a bill with more lines than one page is a
    bill whose self-invoice would silently omit the rest."""
    return fetch_all(
        lambda: db.table("purchase_bill_lines").select(
            # `bill_id`, NOT `purchase_bill_id`: migration 050 created the FK
            # under the longer name and migration 051 RENAMED it to match what
            # the router was already inserting. The sibling allocation table
            # kept the long name, so the two spellings sit side by side in this
            # module and reading either one off the other is silent — PostgREST
            # answers a column that does not exist with an error the paged read
            # turns into an empty result, so the self-invoice would have shown
            # no lines at all.
            "id, bill_id, description, hsn_sac, quantity, "
            "taxable_amount_paise")
        .eq("bill_id", bill_id),
        key="id", label="purchase_bill_lines")
    # No `unit` column on this table, so Rule 46(h)'s unit of measure is absent
    # from a self-invoice built off a bill. Not invented: the UQC is a fact
    # about what was supplied and the bill does not record it.


def _vendor(db, firm_id: str, vendor_id: str) -> dict:
    row = _first(db.table("vendors").select(
        "id, name, gstin, state_code, pan, address, city, state, "
        "pincode, gst_registration_status")
        .eq("id", vendor_id).eq("firm_id", firm_id).limit(1).execute().data)
    if not row:
        raise HTTPException(status_code=404, detail="Vendor not found.")
    return row


def _client(db, firm_id: str, client_id: str) -> dict:
    row = _first(db.table("clients").select(
        "id, client_name, legal_name, gstin, pan, state_code, "
        "address_line1, address_line2, city, state, pincode")
        .eq("id", client_id).eq("firm_id", firm_id).limit(1).execute().data)
    if not row:
        raise HTTPException(status_code=404, detail="Client not found.")
    return row


def _payment(db, firm_id: str, payment_id: str) -> dict:
    row = _first(db.table("purchase_payments").select(
        "id, firm_id, client_id, vendor_id, purchase_bill_id, "
        "payment_no, payment_date, amount_paise, reference_no")
        .eq("id", payment_id).eq("firm_id", firm_id).limit(1).execute().data)
    if not row:
        raise HTTPException(status_code=404, detail="Payment not found.")
    return row


def settled_bills(db, firm_id: str, payment: dict) -> list[dict]:
    """What this payment settled, in BOTH shapes (PUR-22).

    `purchase_payments.purchase_bill_id` is the legacy single-bill FK, written
    with no allocation row; `purchase_payment_allocations` is the multi-bill
    shape, written with that column NULL. A reader that knows one shape is
    silently wrong about the other, and on a payment voucher being wrong means
    stating tax for a supply this payment did not pay for.
    """
    legacy_id = payment.get("purchase_bill_id")
    if legacy_id:
        bill = _bill_or_none(db, firm_id, legacy_id)
        if not bill or bill.get("deleted_at"):
            return []
        return [{"bill": bill, "settled_paise": int(payment.get("amount_paise") or 0)}]

    rows = fetch_all(
        lambda: db.table("purchase_payment_allocations").select(
            # `allocated_paise` is this table's own name for the figure
            # (migration 226). `amount_paise` is what `purchase_payments`
            # calls the payment's TOTAL, and reading the allocation under that
            # name settles every bill at zero — a payment voucher stating tax
            # on a supply nothing was paid for.
            "id, purchase_payment_id, purchase_bill_id, allocated_paise, "
            "is_voided")
        .eq("purchase_payment_id", payment.get("id")),
        key="id", label="purchase_payment_allocations")
    # Filtered in PYTHON so a row lacking the key reads as LIVE — the same rule
    # PUR-22 states for both not-undone tests.
    live = [r for r in rows if not r.get("is_voided")]

    out: list[dict] = []
    for a in live:
        bill = _bill_or_none(db, firm_id, a.get("purchase_bill_id"))
        if not bill or bill.get("deleted_at"):
            continue
        out.append({"bill": bill,
                    "settled_paise": int(a.get("allocated_paise") or 0)})
    return out


def existing_for(db, firm_id: str, *, bill_id: Optional[str] = None,
                 payment_id: Optional[str] = None) -> Optional[dict]:
    """The document already issued against this parent, or None.

    A second one is a duplicate of a statutory record, not a correction — the
    partial unique indexes say so in the database and this says so before the
    insert, so the CA gets a sentence rather than a constraint violation.
    """
    if not (bill_id or payment_id):
        return None
    # TWO literal `.eq`s rather than one computed column name. `.eq(column, …)`
    # reads better and is invisible to the column guard — the same reason the
    # reads above are spelled out.
    q = (db.table("rcm_documents").select(
             "id, firm_id, client_id, vendor_id, kind, purchase_bill_id, "
             "purchase_payment_id, document_no, document_date, "
             "particulars_json, taxable_paise, cgst_paise, sgst_paise, "
             "igst_paise, cess_paise, amount_paid_paise, notes, created_at, "
             "created_by, deleted_at")
         .eq("firm_id", firm_id))
    q = (q.eq("purchase_bill_id", bill_id) if bill_id
         else q.eq("purchase_payment_id", payment_id))
    return _first(q.is_("deleted_at", "null").limit(1).execute().data)


# ── The two previews ─────────────────────────────────────────────────────────

def preview_self_invoice(db, *, firm_id: str, bill_id: str,
                         document_no: Optional[str] = None,
                         document_date: Optional[str] = None) -> dict:
    """What a s.31(3)(f) self-invoice for this bill would say, or why none is due.

    Writes nothing. The same function `issue` builds from, so what the CA
    confirms is what gets stored.
    """
    bill = _bill(db, firm_id, bill_id)
    vendor = _vendor(db, firm_id, bill["vendor_id"])
    decision = rd.self_invoice_due(bill, vendor)
    registration, _why = rd.registration_of(vendor)

    out: dict[str, Any] = {
        "kind": rd.KIND_SELF_INVOICE,
        "section": rd.SECTION_FOR_KIND[rd.KIND_SELF_INVOICE],
        "rule": rd.RULE_FOR_KIND[rd.KIND_SELF_INVOICE],
        "due": decision.due,
        "reasons": decision.reasons,
        "gaps": decision.gaps,
        "vendor_registration": registration,
        "existing": existing_for(db, firm_id, bill_id=bill_id),
        "particulars": None,
    }
    if not decision.due:
        return out

    client = _client(db, firm_id, bill["client_id"])
    date = (document_date or str(bill.get("bill_date") or ist_today().isoformat()))[:10]
    number = document_no or suggest_number(
        db, firm_id=firm_id, client_id=bill["client_id"],
        kind=rd.KIND_SELF_INVOICE, document_date=date)
    particulars = rd.self_invoice_particulars(
        bill=bill, bill_lines=_bill_lines(db, firm_id, bill_id),
        supplier=vendor_party(vendor, registration), recipient=client_party(client),
        document_no=number, document_date=date)
    out["particulars"] = rd.as_dict(particulars)
    return out


def preview_payment_voucher(db, *, firm_id: str, payment_id: str,
                            document_no: Optional[str] = None,
                            document_date: Optional[str] = None) -> dict:
    """What a s.31(3)(g) payment voucher for this payment would say, or why none
    is due. Writes nothing."""
    payment = _payment(db, firm_id, payment_id)
    vendor = _vendor(db, firm_id, payment["vendor_id"])
    settled = settled_bills(db, firm_id, payment)
    decision = rd.payment_voucher_due(payment, settled)
    registration, _why = rd.registration_of(vendor)

    out: dict[str, Any] = {
        "kind": rd.KIND_PAYMENT_VOUCHER,
        "section": rd.SECTION_FOR_KIND[rd.KIND_PAYMENT_VOUCHER],
        "rule": rd.RULE_FOR_KIND[rd.KIND_PAYMENT_VOUCHER],
        "due": decision.due,
        "reasons": decision.reasons,
        "gaps": decision.gaps,
        "vendor_registration": registration,
        "existing": existing_for(db, firm_id, payment_id=payment_id),
        "particulars": None,
    }
    if not decision.due:
        return out

    client = _client(db, firm_id, payment["client_id"])
    date = (document_date
            or str(payment.get("payment_date") or ist_today().isoformat()))[:10]
    number = document_no or suggest_number(
        db, firm_id=firm_id, client_id=payment["client_id"],
        kind=rd.KIND_PAYMENT_VOUCHER, document_date=date)
    particulars = rd.payment_voucher_particulars(
        payment=payment, settled=settled,
        supplier=vendor_party(vendor, registration), recipient=client_party(client),
        document_no=number, document_date=date)
    out["particulars"] = rd.as_dict(particulars)
    return out


# ── The write ────────────────────────────────────────────────────────────────

def issue(db, *, firm_id: str, kind: str, bill_id: Optional[str] = None,
          payment_id: Optional[str] = None, document_no: Optional[str] = None,
          document_date: Optional[str] = None, notes: Optional[str] = None,
          actor_id: Optional[str] = None) -> dict:
    """Issue the document, once.

    # CA REVIEW REQUIRED — the CA confirms the particulars before this runs.
    """
    if kind not in rd.KINDS:
        raise HTTPException(status_code=422, detail=f"Unknown document kind {kind!r}.")

    preview = (preview_self_invoice(db, firm_id=firm_id, bill_id=bill_id,
                                    document_no=document_no,
                                    document_date=document_date)
               if kind == rd.KIND_SELF_INVOICE
               else preview_payment_voucher(db, firm_id=firm_id,
                                            payment_id=payment_id,
                                            document_no=document_no,
                                            document_date=document_date))

    if preview.get("existing"):
        raise HTTPException(
            status_code=409,
            detail=(f"{preview['existing'].get('document_no')} has already been "
                    f"issued against this document. A second one is a duplicate "
                    f"statutory record, not a correction."))
    if not preview["due"]:
        raise HTTPException(
            status_code=422,
            detail=" ".join(preview["reasons"] + preview["gaps"])
                   or "No document is due.")

    particulars = preview["particulars"] or {}
    number = (document_no or particulars.get("document_no") or "").strip()
    violation = format_violation(number)
    if violation:
        # Rule 46(b)/52(b) REFUSES — over sixteen characters, or a character the
        # rule does not permit. Not a warning: both the GSTR-1 schema and the
        # IRP reject such a number anyway.
        raise HTTPException(status_code=422, detail=violation)

    parent = _bill(db, firm_id, bill_id) if kind == rd.KIND_SELF_INVOICE \
        else _payment(db, firm_id, payment_id)
    client_id = parent["client_id"]
    date = particulars.get("document_date") or ist_today().isoformat()

    from services.period_validation_service import period_validation_service
    from services import period_lock_service
    # BOTH questions. The FY switch is the firm's own; `assert_open` is the
    # client's, and it applies because this document is what Rule 36(1)(b)
    # makes the input credit rest on — issuing one into a period whose GSTR-3B
    # is filed changes what that return should have said.
    period_validation_service.validate_posting_date(firm_id or "", date)
    period_lock_service.assert_open(db, firm_id, client_id, date)

    heads = {t["head"]: int(t["amount_paise"]) for t in particulars.get("taxes", [])}
    row = (db.table("rcm_documents").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "vendor_id": parent["vendor_id"],
        "kind": kind,
        "purchase_bill_id": bill_id if kind == rd.KIND_SELF_INVOICE else None,
        "purchase_payment_id": payment_id if kind == rd.KIND_PAYMENT_VOUCHER else None,
        "document_no": number,
        "document_date": date,
        "particulars_json": particulars,
        "taxable_paise": int(particulars.get("taxable_paise") or 0),
        "cgst_paise": heads.get("CGST", 0),
        "sgst_paise": heads.get("SGST", 0),
        "igst_paise": heads.get("IGST", 0),
        "cess_paise": heads.get("CESS", 0),
        "amount_paid_paise": int(particulars.get("amount_paid_paise") or 0),
        "notes": notes,
        "created_by": actor_id,
    }).execute().data or [{}])[0]
    if not row.get("id"):
        raise HTTPException(status_code=500, detail="Could not issue the document.")
    return row


def listing(db, *, firm_id: str, client_id: str,
            kind: Optional[str] = None) -> list[dict]:
    """Every document issued for this client, newest first.

    One row per reverse-charge bill or payment, so the answer is proportional
    to the documents rather than to the ledger — but paged all the same,
    because a year of monthly GTA bills across a busy client is a row set and
    PostgREST truncates one silently at a thousand.
    """
    def q():
        b = (db.table("rcm_documents").select(
                 "id, firm_id, client_id, vendor_id, kind, purchase_bill_id, "
                 "purchase_payment_id, document_no, document_date, "
                 "particulars_json, taxable_paise, cgst_paise, sgst_paise, "
                 "igst_paise, cess_paise, amount_paid_paise, notes, created_at, "
                 "created_by, deleted_at")
             .eq("firm_id", firm_id).eq("client_id", client_id)
             .is_("deleted_at", "null"))
        return b.eq("kind", kind) if kind else b

    rows = fetch_all(q, key="id", label="rcm_documents")
    # Ordered AFTER the paged read: `fetch_all` imposes its own ORDER BY id, so
    # an ordering asked for inside the query is applied per page and lost.
    return sorted(rows, key=lambda r: (str(r.get("document_date") or ""),
                                       str(r.get("created_at") or "")), reverse=True)
