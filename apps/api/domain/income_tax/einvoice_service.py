"""
E-Invoice Integration Layer — Provider abstraction for IRP (Invoice Registration Portal).
CGST Act Section 31B — E-Invoice mandate for eligible taxpayers.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to IRP/government portal
All IRN generation and cancellation requires explicit CA action.
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from uuid import uuid4
from core import db_provider

_logger = logging.getLogger("caflow.einvoice")
_USE_MOCK = not os.environ.get("SUPABASE_URL")

_MOCK_RECORDS: dict[str, dict] = {}


# ── Provider Abstraction ──────────────────────────────────────────────────────

class EInvoiceProvider(ABC):
    """Abstract interface for e-invoice integration providers."""

    @abstractmethod
    def generate_irn(self, invoice_data: dict) -> dict:
        """Generate Invoice Reference Number. Returns {irn, ack_number, ack_date, qr_data}."""
        ...

    @abstractmethod
    def cancel_irn(self, irn: str, reason_code: int, reason: str) -> dict:
        """Cancel an existing IRN. Returns {status, cancelled_at}."""
        ...

    @abstractmethod
    def get_invoice_status(self, irn: str) -> dict:
        """Get current status of an IRN. Returns {status, details}."""
        ...


class ManualProvider(EInvoiceProvider):
    """Manual provider — CA generates IRN on government portal and records here."""

    def generate_irn(self, invoice_data: dict) -> dict:
        return {"irn": None, "ack_number": None, "ack_date": None, "qr_data": None}

    def cancel_irn(self, irn: str, reason_code: int, reason: str) -> dict:
        return {"status": "cancelled", "cancelled_at": datetime.now(timezone.utc).isoformat()}

    def get_invoice_status(self, irn: str) -> dict:
        return {"status": "unknown", "details": {}}


def get_provider(provider_name: str = "manual") -> EInvoiceProvider:
    if provider_name == "manual":
        return ManualProvider()
    # Future: ClearTax, Tally, e-Invoice6 etc.
    _logger.warning("Unknown e-invoice provider '%s', falling back to manual", provider_name)
    return ManualProvider()


# ── Service Functions ─────────────────────────────────────────────────────────

_supabase = db_provider.request_db


def create_einvoice_record(
    firm_id: str,
    client_id: str,
    invoice_number: str,
    invoice_date: str,
    created_by: str,
    sales_invoice_id: str | None = None,
    provider: str = "manual",
    gst_treatment: str | None = None,
    lut_number: str | None = None,
) -> dict:
    """Create e-invoice record in draft state.

    gst_treatment / lut_number capture the supply's compliance treatment
    (Export / SEZ / Deemed export, with/without payment; LUT/Bond reference).
    They are metadata on this record only — never fed into tax/journal math.
    """
    if _USE_MOCK:
        row = {
            "id": str(uuid4()),
            "firm_id": firm_id,
            "client_id": client_id,
            "sales_invoice_id": sales_invoice_id,
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "irn": None,
            "ack_number": None,
            "ack_date": None,
            "qr_data": None,
            "status": "draft",
            "provider": provider,
            "provider_response": {},
            "gst_treatment": gst_treatment,
            "lut_number": lut_number,
            "ca_review_required": True,
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _MOCK_RECORDS[row["id"]] = row
        return row

    sb = _supabase()
    row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "sales_invoice_id": sales_invoice_id,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "status": "draft",
        "provider": provider,
        "gst_treatment": gst_treatment,
        "lut_number": lut_number,
        "ca_review_required": True,
        "created_by": created_by,
    }
    res = sb.table("einvoice_records").insert(row).execute()
    return res.data[0] if res.data else row


def get_einvoice_record(firm_id: str, record_id: str) -> dict | None:
    """Read a single record by id, scoped to the firm.

    Module 9.0: the two row-addressed IRN routes mutate by record_id and
    previously scoped on firm_id alone, so the router had no way to learn a
    record's client_id *before* writing to it. This read is what lets the
    router enforce client-assignment scope ahead of the mutation.
    """
    if _USE_MOCK:
        row = _MOCK_RECORDS.get(record_id)
        return row if row and row.get("firm_id") == firm_id else None

    sb = _supabase()
    res = sb.table("einvoice_records").select("*").eq("id", record_id).eq(
        "firm_id", firm_id
    ).execute()
    return (res.data or [None])[0]


def record_irn_generated(
    firm_id: str,
    record_id: str,
    irn: str,
    ack_number: str,
    ack_date: str,
    qr_data: str | None = None,
    provider_response: dict | None = None,
) -> dict:
    """
    Record that CA has generated IRN on the government portal.
    # CA REVIEW REQUIRED — IRN must be generated by CA on IRP portal, not auto-submitted
    """
    update = {
        "irn": irn,
        "ack_number": ack_number,
        "ack_date": ack_date,
        "qr_data": qr_data,
        "status": "generated",
        "provider_response": provider_response or {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if _USE_MOCK:
        if record_id in _MOCK_RECORDS:
            _MOCK_RECORDS[record_id].update(update)
        return _MOCK_RECORDS.get(record_id, {})

    sb = _supabase()
    res = sb.table("einvoice_records").update(update).eq("id", record_id).eq(
        "firm_id", firm_id
    ).execute()
    return res.data[0] if res.data else {}


def record_irn_cancelled(
    firm_id: str,
    record_id: str,
    cancellation_reason: str,
) -> dict:
    """
    Record IRN cancellation.
    # CA REVIEW REQUIRED — Cancellation must be done by CA on IRP portal
    """
    update = {
        "status": "cancelled",
        "cancellation_reason": cancellation_reason,
        "cancelled_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if _USE_MOCK:
        if record_id in _MOCK_RECORDS:
            _MOCK_RECORDS[record_id].update(update)
        return _MOCK_RECORDS.get(record_id, {})

    sb = _supabase()
    res = sb.table("einvoice_records").update(update).eq("id", record_id).eq(
        "firm_id", firm_id
    ).execute()
    return res.data[0] if res.data else {}


def list_einvoices(
    firm_id: str,
    client_id: str,
    status: str | None = None,
    sales_invoice_id: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """The client's e-invoice records, newest first. `sales_invoice_id` asks for one invoice's own (POST-A-263): the
    invoice drawer used to read every record the client had ever had and look for its invoice among them, which grows
    with the client's history and was cut silently at the database's row cap. `limit` is the number of rows to READ, so
    a caller that reports a window passes `core.list_window.probe(window)` and splits the answer with `split`."""
    if _USE_MOCK:
        records = [r for r in _MOCK_RECORDS.values()
                   if r["firm_id"] == firm_id and r["client_id"] == client_id]
        if status:
            records = [r for r in records if r["status"] == status]
        if sales_invoice_id:
            records = [r for r in records if r.get("sales_invoice_id") == sales_invoice_id]
        records.sort(key=lambda r: (str(r.get("created_at") or ""), str(r.get("id"))), reverse=True)
        return records[:limit] if limit else records

    sb = _supabase()
    q = sb.table("einvoice_records").select("*").eq("firm_id", firm_id).eq("client_id", client_id)
    if status:
        q = q.eq("status", status)
    if sales_invoice_id:
        q = q.eq("sales_invoice_id", sales_invoice_id)
    # `id` breaks a tie between two records made in the same instant, so the same rows come back in the same order.
    q = q.order("created_at", desc=True).order("id", desc=True)
    if limit:
        q = q.limit(limit)
    return q.execute().data or []


def live_einvoice_for_invoice(firm_id: str, sales_invoice_id: str) -> dict | None:
    """The e-invoice record for this invoice that is not cancelled, or None (POST-A-263).

    An invoice has one IRN. A record prepared for it is live until it is cancelled, and a second live one is a draft
    that is never recorded or cancelled: `uq_einvoice_records_one_live_per_invoice` (migration 518) is the database's
    half of this question and the create route asks it first so the refusal can name the record that is there."""
    if _USE_MOCK:
        live = [r for r in _MOCK_RECORDS.values()
                if r["firm_id"] == firm_id and r.get("sales_invoice_id") == sales_invoice_id
                and r["status"] != "cancelled"]
        live.sort(key=lambda r: (str(r.get("created_at") or ""), str(r.get("id"))), reverse=True)
        return live[0] if live else None

    sb = _supabase()
    res = (sb.table("einvoice_records").select("*").eq("firm_id", firm_id)
           .eq("sales_invoice_id", sales_invoice_id).neq("status", "cancelled")
           .order("created_at", desc=True).order("id", desc=True).limit(1).execute())
    return (res.data or [None])[0]
