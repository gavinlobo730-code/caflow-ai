"""
Portal Data Surfaces (Phase 4.5.2) — read-only, client-safe views of the
FIRM ↔ CLIENT relationship for the customer portal.

Locked scope: expose ONLY what the client owes/receives from the firm, never the
client's own accounting ledger. The fee relationship lives in the firm's INTERNAL
client books, where the portal client is a customer (G3 link
`client_firm_customer_links`). Compliance status keys on the portal client_id
directly. Every surface is projected to client-safe fields; internal fields
(journal ids, assignees, fees, notes, risk, escalation) are never returned.

Reuses (no reinvention): collections_service (aging/outstanding),
customer_statement_service + statement_pdf_service (4.1), invoice_pdf_service,
collections invoice_deliveries reminders (4.2), compliance_record_service (4.4).
"""
import os
import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import HTTPException

from services import collections_service
from core.ist_clock import ist_today
from core.db_paging import fetch_all

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.portal_data")

# Invoice statuses considered "open" (an outstanding balance the client owes the firm).
_OPEN = ("issued", "partially_paid")


def _db():
    if _USE_MOCK:
        return None
    from core.supabase_client import get_supabase
    return get_supabase()


def current_fy_range(today: Optional[date] = None) -> tuple[str, str]:
    """Indian FY (Apr 1 – Mar 31) containing `today`. Default statement window."""
    today = today or ist_today()
    start_year = today.year if today.month >= 4 else today.year - 1
    return f"{start_year}-04-01", f"{start_year + 1}-03-31"


# ── Pure, client-safe projections ────────────────────────────────────────────

def safe_invoice(inv: dict, today: Optional[date] = None) -> dict:
    """Client-safe invoice view + derived outstanding/overdue. Drops journal id,
    source, internal customer/client linkage, created_by, etc."""
    m = collections_service.assess_invoice(inv, today)
    return {
        "id": inv.get("id"),
        "invoice_no": inv.get("invoice_no"),
        "invoice_date": inv.get("invoice_date"),
        "due_date": inv.get("due_date"),
        "total_paise": int(inv.get("total_paise", 0) or 0),
        "paid_paise": int(inv.get("paid_paise", 0) or 0),
        "outstanding_paise": m["outstanding_paise"],
        "status": inv.get("status"),
        "is_overdue": m["is_overdue"],
        "days_overdue": m["days_overdue"],
    }


def safe_reminder(delivery: dict, invoice_no: Optional[str]) -> dict:
    """Client-safe reminder record. Drops sent_by_*, provider ids, raw error text."""
    return {
        "invoice_no": invoice_no,
        "status": delivery.get("status"),
        "sent_at": delivery.get("sent_at"),
        "created_at": delivery.get("created_at"),
    }


def safe_compliance(rec: dict) -> dict:
    """Client-safe compliance status. Drops notes, assignees (preparer/reviewer/
    approver/assigned_to), priority, risk_score, escalation, engagement_id."""
    return {
        "compliance_type": rec.get("compliance_type"),
        "obligation_type": rec.get("obligation_type"),
        "period_label": rec.get("period_label"),
        "period_start": rec.get("period_start"),
        "period_end": rec.get("period_end"),
        "due_date": rec.get("due_date"),
        "status": rec.get("status"),
        "filed_date": rec.get("filed_date"),
        "acknowledgement_no": rec.get("acknowledgement_no"),
    }


# ── Fee-relationship scope (G3): portal client → internal customer ───────────

def resolve_fee_scope(firm_id: str, client_id: str, db) -> Optional[dict]:
    """The firm's internal client + the customer that represents this portal client
    (where the firm's fee invoices to the client live). None when no link exists yet."""
    if db is None:
        return None
    from services.internal_client_service import get_internal_client_id
    internal_client_id = get_internal_client_id(firm_id)
    if not internal_client_id:
        return None
    rows = (db.table("client_firm_customer_links").select("internal_customer_id")
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data or [])
    if not rows:
        return None
    return {"internal_client_id": internal_client_id, "internal_customer_id": rows[0]["internal_customer_id"]}


# ── Surfaces ─────────────────────────────────────────────────────────────────

def list_invoices(firm_id: str, client_id: str, db=None, today: Optional[date] = None) -> list[dict]:
    db = db if db is not None else _db()
    scope = resolve_fee_scope(firm_id, client_id, db)
    if not scope:
        return []
    rows = (db.table("client_sales_invoices")
            .select("id,invoice_no,invoice_date,due_date,total_paise,paid_paise,status")
            .eq("firm_id", firm_id).eq("client_id", scope["internal_client_id"])
            .eq("customer_id", scope["internal_customer_id"]).is_("deleted_at", "null")
            .order("invoice_date", desc=True).execute().data or [])
    return [safe_invoice(r, today) for r in rows]


def dues(firm_id: str, client_id: str, db=None, today: Optional[date] = None) -> dict:
    """Canonical AR (replaces the legacy `transactions` source): outstanding fee
    invoices the client owes the firm, in integer paise."""
    invoices = list_invoices(firm_id, client_id, db=db, today=today)
    open_invs = [i for i in invoices if i["status"] in _OPEN and i["outstanding_paise"] > 0]
    overdue = [i for i in open_invs if i["is_overdue"]]
    return {
        "dues": open_invs,
        "total_outstanding_paise": sum(i["outstanding_paise"] for i in open_invs),
        "overdue_paise": sum(i["outstanding_paise"] for i in overdue),
        "overdue_count": len(overdue),
    }


def invoice_in_scope(firm_id: str, client_id: str, invoice_id: str, db=None) -> bool:
    """Ownership check for PDF access — the invoice must be a fee invoice issued to
    THIS portal client (internal client + linked customer)."""
    db = db if db is not None else _db()
    scope = resolve_fee_scope(firm_id, client_id, db)
    if not scope:
        return False
    rows = (db.table("client_sales_invoices").select("id")
            .eq("id", invoice_id).eq("firm_id", firm_id)
            .eq("client_id", scope["internal_client_id"]).eq("customer_id", scope["internal_customer_id"])
            .is_("deleted_at", "null").limit(1).execute().data or [])
    return bool(rows)


def reminder_history(firm_id: str, client_id: str, db=None, today: Optional[date] = None) -> list[dict]:
    db = db if db is not None else _db()
    invoices = list_invoices(firm_id, client_id, db=db, today=today)
    by_id = {i["id"]: i for i in invoices}
    if not by_id:
        return []
    rows = (db.table("invoice_deliveries").select("invoice_id,status,sent_at,created_at,kind")
            .eq("firm_id", firm_id).eq("kind", "reminder").in_("invoice_id", list(by_id))
            .order("created_at", desc=True).execute().data or [])
    return [safe_reminder(r, (by_id.get(r.get("invoice_id")) or {}).get("invoice_no")) for r in rows]


def statement(firm_id: str, client_id: str, start: str, end: str, db=None) -> dict:
    db = db if db is not None else _db()
    scope = resolve_fee_scope(firm_id, client_id, db)
    if not scope:
        return {"customer": None, "transactions": [], "opening_balance_paise": 0,
                "closing_balance_paise": 0, "available": False}
    from services.customer_statement_service import customer_statement_service
    return customer_statement_service.generate(
        db, firm_id, scope["internal_client_id"], scope["internal_customer_id"], start, end)


def statement_pdf(firm_id: str, client_id: str, start: str, end: str, db=None) -> tuple[bytes, str]:
    db = db if db is not None else _db()
    scope = resolve_fee_scope(firm_id, client_id, db)
    if not scope:
        raise HTTPException(status_code=404, detail="No statement available for this client.")
    from services.statement_pdf_service import get_customer_statement_pdf
    return get_customer_statement_pdf(
        db, firm_id, scope["internal_client_id"], scope["internal_customer_id"], start, end)


def compliance(firm_id: str, client_id: str, db=None) -> list[dict]:
    """Compliance status for the portal client (their own filings), client-safe."""
    from domain.compliance_record_service import compliance_record_service
    recs = compliance_record_service.list_records(firm_id=firm_id, client_id=client_id)
    return [safe_compliance(r) for r in recs]


# ── Documents, requests and messages — the three sections the shell advertised
#    and nothing served (2.4) ──────────────────────────────────────────────────
#
# `portal_self._DASHBOARD_SECTIONS` has listed documents, requests and messages
# with `available: True` since it was written, and its comment calls them
# "RLS-direct surfaces" — meaning the client reads them straight over PostgREST
# with their own JWT, which migration 109's policies do allow. But no portal
# page ever did, so the API told a client three sections existed and the
# dashboard silently filtered all three out of its own tab row. The
# `capital_wip` shape on the one surface the outside world sees.
#
# THEY ARE SERVED HERE RATHER THAN READ FROM THE BROWSER, and the reason is
# specific: the DOWNLOAD cannot work over PostgREST. Migration 005's storage
# policies gate the `Documents` bucket on `get_my_firm_id()`, which reads the
# STAFF `users` table — a portal contact has no row there, so the function
# answers NULL and every `createSignedUrl` is refused. A browser-side documents
# list would render rows and then fail every download.
#
# The alternative was a storage policy mirroring migration 109's table ones.
# Rejected: it keys authorisation on the OBJECT PATH (`firm/client/uuid-name`),
# so the grant is only as narrow as that convention stays, and a future
# uploader writing a different shape widens it silently. The ownership gate
# here is the same one `/invoices/{id}/pdf` already uses for this principal,
# in Python, where the client context is resolved rather than parsed.

# ── EVERY PROJECTION BELOW IS SPELLED OUT AT ITS CALL SITE ────────────────────
#
# These three began as `_DOCUMENT_COLUMNS` / `_REQUEST_COLUMNS` /
# `_MESSAGE_COLUMNS`, which reads better and is invisible to
# `tests/test_backend_columns_exist_pg.py`: that guard checks every `.select()`
# in apps/api against the real schema AS A STRING, so a projection reached
# through a NAME is not checked at all — it is counted against a budget of
# blind spots instead. Three constants and one `.insert(row)` took that count
# three over, which is how this was found. `domain/firm/identity` records the
# same decision for the same reason. Each is used exactly once, so there is
# nothing to share and the only thing a name bought was the loss of the check.
#
# Client-safe, all three: a portal contact sees what a document IS, never who
# uploaded it (`uploaded_by` is a staff user) nor where it sits in storage.


def list_documents(firm_id: str, client_id: str, db=None) -> list[dict]:
    """Documents the firm has filed against this client."""
    db = db if db is not None else _db()
    rows = fetch_all(
        lambda: db.table("client_documents")
        .select("id, file_name, description, file_size, mime_type, created_at")
        .eq("firm_id", firm_id).eq("client_id", client_id),
        label="portal_data_service.documents")
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows


def document_in_scope(firm_id: str, client_id: str, document_id: str, db=None) -> Optional[dict]:
    """The row, with its storage path, IF it belongs to this portal client.

    Returns None rather than raising so the caller answers 404 — never reveal
    that a document exists under another client, which is the same posture
    `invoice_in_scope` takes."""
    db = db if db is not None else _db()
    rows = (db.table("client_documents").select("id, file_name, file_path, mime_type")
            .eq("id", document_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .limit(1).execute().data) or []
    return rows[0] if rows else None


def list_document_requests(firm_id: str, client_id: str, db=None) -> list[dict]:
    """What the firm has asked this client for, open ones first.

    Sorted open-then-fulfilled rather than by date alone: the whole point of
    the panel for the client is what they still owe their accountant, and a
    month of fulfilled requests above it buries that."""
    db = db if db is not None else _db()
    rows = fetch_all(
        lambda: db.table("document_requests")
        .select("id, title, description, is_urgent, status, fulfilled_at, created_at")
        .eq("firm_id", firm_id).eq("client_id", client_id),
        label="portal_data_service.document_requests")
    rows.sort(key=lambda r: (
        (r.get("status") or "") == "fulfilled",
        # Urgent first WITHIN the open ones — `is_urgent` is the CA saying this
        # is what is holding the work up.
        not bool(r.get("is_urgent")),
        # Oldest first: the request that has been waiting longest is the one to
        # answer, which is the reverse of every other list in this product.
        str(r.get("created_at") or ""),
    ))
    return rows


def list_messages(firm_id: str, client_id: str, db=None) -> list[dict]:
    """The thread between the firm and this client, oldest first — a
    conversation reads downwards."""
    db = db if db is not None else _db()
    rows = fetch_all(
        lambda: db.table("portal_messages")
        .select("id, sender_type, sender_name, body, created_at")
        .eq("firm_id", firm_id).eq("client_id", client_id),
        label="portal_data_service.messages")
    rows.sort(key=lambda r: str(r.get("created_at") or ""))
    return rows


def post_message(firm_id: str, client_id: str, body: str, sender_name: Optional[str],
                 db=None) -> dict:
    """A message FROM the client. `sender_type` is stamped 'client' here and is
    never taken from the request — migration 048 CHECKs it to ('ca', 'client'),
    and a caller-supplied value would let a client post as their accountant."""
    db = db if db is not None else _db()
    # Spelled out in the call rather than built into a `row` variable, for the
    # reason the projection note above gives: a payload bound to a name is
    # unreadable to the column guard. The echo below repeats the five keys
    # rather than sharing them, which is the same price `domain/tally/
    # party_identifiers` pays and for the same reason — a name here buys
    # tidiness and loses the check on the write that matters.
    out = db.table("portal_messages").insert({
        "firm_id": firm_id, "client_id": client_id,
        "sender_type": "client", "sender_name": sender_name,
        "body": body,
    }).execute().data or []
    return out[0] if out else {
        "firm_id": firm_id, "client_id": client_id,
        "sender_type": "client", "sender_name": sender_name, "body": body,
    }
