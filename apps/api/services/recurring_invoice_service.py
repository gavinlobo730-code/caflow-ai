"""
Recurring Invoices (Phase 4.3) — schedule-driven generation of DRAFT sales
invoices from per-customer templates.

Locked product decisions (do not revisit):
  1. Generation creates DRAFT invoices ONLY. Never auto-issue, auto-post a
     journal, create accounting entries, or auto-email. Flow:
     Template -> Draft Invoice -> CA reviews -> Issue -> Journal -> Statement ->
     Reminder -> Receipt.
  6. No invoice is ever emailed automatically. Customer communication happens
     after CA review via the existing manual send flow.

This service owns NO GST / journal / ledger / statement / reminder logic. It
calls the EXISTING invoice engine (routers.sales_invoices.create_invoice) so a
generated invoice is byte-for-byte an ordinary draft (GST, numbering, FY-lock
all reused). It is kept separate from billing_service (the practice's own fee
billing); the two only share cadence-style helper code.

Mock-mode (no SUPABASE_URL) mirrors the convention in billing_service /
sales_invoices: in-memory stores, and create_invoice writes to
MOCK_SALES_INVOICES. All functions accept an injectable `db` for DB-mode tests.
"""
import os
import uuid
import logging
from calendar import monthrange
from datetime import date, datetime, timezone, timedelta
from typing import Optional

from fastapi import HTTPException

from models.invoices import SalesInvoiceIn, InvoiceLineIn
from services.numbering import draft_placeholder_invoice_no

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.recurring")

DEFAULT_CREDIT_DAYS = 30          # firm default when customer.credit_days is absent (Decision 4)
MAX_CATCHUP_PER_RUN = 120         # safety bound on back-dated catch-up per template per run
# GSTR-1 classification vocabularies. Kept identical to migration 270's CHECK
# constraints, which are identical to migration 268's on client_sales_invoices.
# Validated HERE, at save time, rather than left to the database: a template
# holding a value an invoice cannot would fail inside generate_for_occurrence —
# an unattended 06:00 IST job, which is the worst place to discover it.
_SUPPLY_TYPES = ("taxable", "zero_rated", "nil_rated", "exempt", "non_gst")
_INVOICE_TYPES = ("Regular", "SEZ_with_payment", "SEZ_without_payment", "Deemed_export")

_FREQUENCIES = ("weekly", "monthly", "quarterly", "half_yearly", "yearly")
_MONTHS = {"monthly": 1, "quarterly": 3, "half_yearly": 6, "yearly": 12}

# Mock stores (mock mode only).
MOCK_RECURRING_TEMPLATES: list[dict] = []
MOCK_RECURRING_RUNS: list[dict] = []


def _db():
    from core.supabase_client import get_supabase
    return get_supabase()


def _d(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Pure cadence engine (deterministic, month-end clamped) ───────────────────

def _add_months_clamped(d: date, months: int) -> date:
    """Add `months` to d, clamping the day to the last valid day of the target
    month (e.g. Jan-31 + 1 month -> Feb-28/29). Anchored to the original day."""
    m = d.month - 1 + months
    y = d.year + m // 12
    month = m % 12 + 1
    last = monthrange(y, month)[1]
    return date(y, month, min(d.day, last))


def occurrence(frequency: str, start_date, n: int) -> date:
    """The n-th occurrence (n=0 is start_date). Strictly increasing in n."""
    start = _d(start_date)
    if frequency == "weekly":
        return start + timedelta(days=7 * n)
    if frequency not in _MONTHS:
        raise ValueError(f"Unsupported frequency: {frequency}")
    return _add_months_clamped(start, _MONTHS[frequency] * n)


def _index_floor(frequency: str, start: date, ref: date) -> int:
    """A lower-bound estimate of the occurrence index at/just before `ref`."""
    if frequency == "weekly":
        return max(0, (ref - start).days // 7)
    return max(0, ((ref.year - start.year) * 12 + (ref.month - start.month)) // _MONTHS[frequency])


def occurrence_on_or_after(frequency: str, start_date, ref) -> date:
    """Smallest occurrence date >= ref (the first occurrence is start_date)."""
    start, ref = _d(start_date), _d(ref)
    if ref <= start:
        return start
    n = _index_floor(frequency, start, ref)
    while n > 0 and occurrence(frequency, start, n - 1) >= ref:
        n -= 1
    while occurrence(frequency, start, n) < ref:
        n += 1
    return occurrence(frequency, start, n)


def next_occurrence(frequency: str, start_date, after=None) -> date:
    """Smallest occurrence strictly AFTER `after` (or the first occurrence =
    start_date when `after` is None or precedes start_date). Pure + deterministic."""
    start = _d(start_date)
    if after is None:
        return start
    after = _d(after)
    if after < start:
        return start
    n = _index_floor(frequency, start, after)
    while n > 0 and occurrence(frequency, start, n - 1) > after:
        n -= 1
    while occurrence(frequency, start, n) <= after:
        n += 1
    return occurrence(frequency, start, n)


def preview_occurrences(template: dict, count: int = 5, from_date=None) -> list[str]:
    """The next `count` occurrence dates from the template's next_run_date,
    stopping at end_date. Read-only preview (no writes)."""
    freq = template["frequency"]
    start = template["start_date"]
    end = _d(template["end_date"]) if template.get("end_date") else None
    cur = _d(template.get("next_run_date") or start)
    if from_date:
        cur = occurrence_on_or_after(freq, start, max(_d(from_date), _d(start)))
    out: list[str] = []
    n = 0
    while len(out) < max(count, 0) and n < MAX_CATCHUP_PER_RUN:
        if end and cur > end:
            break
        out.append(cur.isoformat())
        nxt = next_occurrence(freq, start, cur)
        if nxt is None or nxt <= cur:
            break
        cur = nxt
        n += 1
    return out


# ── Due date (Decision 4) ────────────────────────────────────────────────────

def due_date_for(occurrence_date, customer: dict) -> str:
    """invoice_date == occurrence_date; due_date = occurrence + customer.credit_days,
    falling back to the firm default when credit_days is missing."""
    days = customer.get("credit_days") if customer else None
    days = int(days) if days is not None else DEFAULT_CREDIT_DAYS
    return (_d(occurrence_date) + timedelta(days=days)).isoformat()


# ── Template CRUD ────────────────────────────────────────────────────────────

def _validate(data: dict) -> None:
    if data.get("frequency") not in _FREQUENCIES:
        raise HTTPException(status_code=422, detail=f"frequency must be one of {_FREQUENCIES}")
    if not data.get("lines"):
        raise HTTPException(status_code=422, detail="A template needs at least one line item.")
    if data.get("end_date") and data.get("start_date") and _d(data["end_date"]) < _d(data["start_date"]):
        raise HTTPException(status_code=422, detail="end_date cannot be before start_date.")
    _validate_classification(data)


def _validate_classification(data: dict) -> None:
    """Reject a classification the invoice table would refuse.

    Only checks keys that are PRESENT, so it serves both create (where the
    Pydantic defaults always supply them) and a partial update (where absent
    means "leave alone").
    """
    if data.get("supply_type") is not None and data["supply_type"] not in _SUPPLY_TYPES:
        raise HTTPException(status_code=422, detail=f"supply_type must be one of {_SUPPLY_TYPES}")
    if data.get("invoice_type") is not None and data["invoice_type"] not in _INVOICE_TYPES:
        raise HTTPException(status_code=422, detail=f"invoice_type must be one of {_INVOICE_TYPES}")


def _line_rows(lines: list[dict]) -> list[dict]:
    rows = []
    for i, ln in enumerate(lines):
        rows.append({
            "service_catalogue_id": ln["service_catalogue_id"],
            "description": ln.get("description", ""),
            "hsn_sac": ln.get("hsn_sac"),
            "quantity": float(ln.get("quantity", 1) or 1),
            "rate_paise": int(ln.get("rate_paise", 0) or 0),
            "gst_rate_bps": int(round(float(ln.get("gst_rate_percent", 18) or 0) * 100))
            if "gst_rate_percent" in ln else int(ln.get("gst_rate_bps", 1800) or 0),
            "is_service": bool(ln.get("is_service", False)),
            "sort_order": int(ln.get("sort_order", i)),
        })
    return rows


def create_template(firm_id: str, data: dict, created_by: Optional[str], db=None) -> dict:
    _validate(data)
    start = _d(data["start_date"]).isoformat()
    payload = {
        "firm_id": firm_id,
        "client_id": data["client_id"],
        "customer_id": data["customer_id"],
        "title": data["title"],
        "description": data.get("description"),
        "frequency": data["frequency"],
        "start_date": start,
        "end_date": _d(data["end_date"]).isoformat() if data.get("end_date") else None,
        "next_run_date": start,                      # first run = first occurrence
        "notes": data.get("notes"),
        "is_inter_state": bool(data.get("is_inter_state", False)),
        # GSTR-1 classification (task #160, migration 270). Stamped on every
        # invoice this template generates — see generate_for_occurrence.
        "supply_type": data.get("supply_type") or "taxable",
        "invoice_type": data.get("invoice_type") or "Regular",
        "is_reverse_charge": bool(data.get("is_reverse_charge") or False),
        "status": "active",
        "created_by": created_by,
    }
    lines = _line_rows(data["lines"])
    if _USE_MOCK:
        payload["id"] = str(uuid.uuid4())
        payload["created_at"] = _now_iso()
        payload["lines"] = lines
        MOCK_RECURRING_TEMPLATES.append(payload)
        return dict(payload)
    db = db or _db()
    row = db.table("recurring_invoice_templates").insert(payload).execute().data[0]
    for ln in lines:
        ln["template_id"] = row["id"]
    if lines:
        db.table("recurring_invoice_template_lines").insert(lines).execute()
    row["lines"] = lines
    return row


def update_template(firm_id: str, template_id: str, data: dict, db=None) -> dict:
    _validate_classification(data)
    existing = get_template(firm_id, template_id, db=db)
    if not existing:
        raise HTTPException(status_code=404, detail="Recurring template not found.")
    fields: dict = {}
    for k in ("title", "description", "frequency", "notes", "is_inter_state",
              "supply_type", "invoice_type", "is_reverse_charge"):
        if data.get(k) is not None:
            fields[k] = data[k]
    if fields.get("frequency") and fields["frequency"] not in _FREQUENCIES:
        raise HTTPException(status_code=422, detail=f"frequency must be one of {_FREQUENCIES}")
    if data.get("start_date") is not None:
        fields["start_date"] = _d(data["start_date"]).isoformat()
    if "end_date" in data:
        fields["end_date"] = _d(data["end_date"]).isoformat() if data.get("end_date") else None
    # Re-base the next run when the schedule's shape changes (idempotency still
    # prevents duplicate invoices for occurrence dates already generated).
    if "start_date" in fields or "frequency" in fields:
        new_start = fields.get("start_date", existing["start_date"])
        fields["next_run_date"] = _d(new_start).isoformat()
    fields["updated_at"] = _now_iso()

    new_lines = _line_rows(data["lines"]) if data.get("lines") is not None else None

    if _USE_MOCK:
        existing.update(fields)
        if new_lines is not None:
            existing["lines"] = new_lines
        for t in MOCK_RECURRING_TEMPLATES:
            if t["id"] == template_id:
                t.update(fields)
                if new_lines is not None:
                    t["lines"] = new_lines
        return dict(existing)
    db = db or _db()
    db.table("recurring_invoice_templates").update(fields).eq("id", template_id).eq("firm_id", firm_id).execute()
    if new_lines is not None:
        db.table("recurring_invoice_template_lines").delete().eq("template_id", template_id).execute()
        for ln in new_lines:
            ln["template_id"] = template_id
        if new_lines:
            db.table("recurring_invoice_template_lines").insert(new_lines).execute()
    return get_template(firm_id, template_id, db=db)


def set_status(firm_id: str, template_id: str, status: str, db=None) -> dict:
    if status not in ("active", "paused", "archived"):
        raise HTTPException(status_code=422, detail="status must be active | paused | archived")
    existing = get_template(firm_id, template_id, db=db)
    if not existing:
        raise HTTPException(status_code=404, detail="Recurring template not found.")
    fields = {"status": status, "updated_at": _now_iso()}
    if _USE_MOCK:
        for t in MOCK_RECURRING_TEMPLATES:
            if t["id"] == template_id:
                t.update(fields)
        existing.update(fields)
        return dict(existing)
    db = db or _db()
    db.table("recurring_invoice_templates").update(fields).eq("id", template_id).eq("firm_id", firm_id).execute()
    return get_template(firm_id, template_id, db=db)


def get_template(firm_id: str, template_id: str, db=None) -> Optional[dict]:
    if _USE_MOCK:
        t = next((x for x in MOCK_RECURRING_TEMPLATES
                  if x["id"] == template_id and x["firm_id"] == firm_id), None)
        return dict(t) if t else None
    db = db or _db()
    rows = (db.table("recurring_invoice_templates").select("*")
            .eq("id", template_id).eq("firm_id", firm_id).limit(1).execute().data or [])
    if not rows:
        return None
    t = rows[0]
    t["lines"] = (db.table("recurring_invoice_template_lines").select("*")
                  .eq("template_id", template_id).order("sort_order").execute().data or [])
    return t


def list_templates(firm_id: str, client_id: Optional[str] = None,
                   status: Optional[str] = None, include_archived: bool = True, db=None) -> list[dict]:
    if _USE_MOCK:
        out = [dict(t) for t in MOCK_RECURRING_TEMPLATES if t["firm_id"] == firm_id]
        if client_id:
            out = [t for t in out if t.get("client_id") == client_id]
        if status:
            out = [t for t in out if t.get("status") == status]
        elif not include_archived:
            out = [t for t in out if t.get("status") != "archived"]
        return out
    db = db or _db()
    q = db.table("recurring_invoice_templates").select("*").eq("firm_id", firm_id)
    if client_id:
        q = q.eq("client_id", client_id)
    if status:
        q = q.eq("status", status)
    rows = q.order("next_run_date").execute().data or []
    if status is None and not include_archived:
        rows = [r for r in rows if r.get("status") != "archived"]
    # attach lines in one grouped query
    ids = [r["id"] for r in rows]
    lines_by_t: dict = {}
    if ids:
        all_lines = (db.table("recurring_invoice_template_lines").select("*")
                     .in_("template_id", ids).order("sort_order").execute().data or [])
        for ln in all_lines:
            lines_by_t.setdefault(ln["template_id"], []).append(ln)
    for r in rows:
        r["lines"] = lines_by_t.get(r["id"], [])
    return rows


def _template_lines(template: dict, db=None) -> list[dict]:
    if template.get("lines") is not None:
        return template["lines"]
    if _USE_MOCK:
        return []
    db = db or _db()
    return (db.table("recurring_invoice_template_lines").select("*")
            .eq("template_id", template["id"]).order("sort_order").execute().data or [])


# ── Generation (DRAFT only) ──────────────────────────────────────────────────

def _system_actor(firm_id: str) -> dict:
    """Non-interactive actor for scheduler-driven generation."""
    return {"firm_id": firm_id, "auth_user_id": None, "email": "scheduler@recurring", "role": "Partner"}


def _customer(db, firm_id: str, customer_id: str) -> dict:
    if _USE_MOCK or not customer_id:
        return {}
    try:
        rows = (db.table("customers").select("id,name,email,credit_days,state_code")
                .eq("id", customer_id).eq("firm_id", firm_id).limit(1).execute().data or [])
        return rows[0] if rows else {}
    except Exception:  # pragma: no cover
        return {}


def _find_generated(firm_id: str, template_id: str, occurrence_iso: str, db=None) -> Optional[dict]:
    """The invoice already generated for this (template, occurrence), if any —
    the authoritative idempotency check (one occurrence -> one invoice)."""
    if _USE_MOCK:
        from routers.sales_invoices import MOCK_SALES_INVOICES
        for inv in MOCK_SALES_INVOICES:
            if inv.get("recurring_template_id") == template_id and inv.get("recurring_occurrence") == occurrence_iso:
                return inv
        return None
    db = db or _db()
    res = (db.table("client_sales_invoices").select("*")
           .eq("firm_id", firm_id).eq("recurring_template_id", template_id)
           .eq("recurring_occurrence", occurrence_iso).limit(1).execute().data or [])
    return res[0] if res else None


def _stamp_recurring(firm_id: str, invoice: dict, template_id: str, occurrence_iso: str, db=None) -> dict:
    fields = {"recurring_template_id": template_id, "recurring_occurrence": occurrence_iso, "source": "recurring"}
    if _USE_MOCK:
        invoice.update(fields)
        return invoice
    db = db or _db()
    try:
        upd = (db.table("client_sales_invoices").update(fields)
               .eq("id", invoice["id"]).eq("firm_id", firm_id).execute())
        return upd.data[0] if upd.data else {**invoice, **fields}
    except Exception as e:  # unique(recurring_template_id, recurring_occurrence) race
        _logger.warning("duplicate recurring run for template %s occ %s: %s", template_id, occurrence_iso, e)
        db.table("client_sales_invoice_lines").delete().eq("sales_invoice_id", invoice["id"]).execute()
        db.table("client_sales_invoices").delete().eq("id", invoice["id"]).execute()
        winner = _find_generated(firm_id, template_id, occurrence_iso, db)
        if winner:
            return winner
        raise


def _record_run(firm_id: str, template_id: str, occurrence_iso: str, invoice_id: Optional[str],
                status: str, detail: Optional[dict], db=None) -> None:
    rec = {"firm_id": firm_id, "template_id": template_id, "occurrence_date": occurrence_iso,
           "invoice_id": invoice_id, "status": status, "detail": detail}
    if _USE_MOCK:
        rec["id"] = str(uuid.uuid4())
        rec["created_at"] = _now_iso()
        MOCK_RECURRING_RUNS.append(rec)
        return
    db = db or _db()
    try:
        db.table("recurring_invoice_runs").upsert(rec, on_conflict="template_id,occurrence_date").execute()
    except Exception as e:  # pragma: no cover - history is best-effort
        _logger.warning("recurring run-log failed (%s/%s): %s", template_id, occurrence_iso, e)


def _set_next_run(firm_id: str, template_id: str, next_run_iso: Optional[str], db=None) -> None:
    if _USE_MOCK:
        for t in MOCK_RECURRING_TEMPLATES:
            if t["id"] == template_id:
                t["next_run_date"] = next_run_iso
        return
    db = db or _db()
    db.table("recurring_invoice_templates").update(
        {"next_run_date": next_run_iso, "updated_at": _now_iso()}
    ).eq("id", template_id).eq("firm_id", firm_id).execute()


def _generate_one(firm_id: str, template: dict, actor: dict, occurrence_iso: str, db=None) -> dict:
    """Idempotently create ONE draft invoice for (template, occurrence). Reuses
    the existing invoice engine — no GST/journal/posting here. Never issues, never
    emails (Decisions 1 & 6)."""
    existing = _find_generated(firm_id, template["id"], occurrence_iso, db)
    if existing:
        return {"invoice": existing, "occurrence": occurrence_iso, "created": False, "idempotent": True}

    customer = _customer(db or (None if _USE_MOCK else _db()), firm_id, template.get("customer_id"))
    lines = [
        InvoiceLineIn(
            service_catalogue_id=ln["service_catalogue_id"],
            description=ln.get("description", ""),
            hsn_sac=ln.get("hsn_sac"),
            quantity=float(ln.get("quantity", 1) or 1),
            rate_paise=int(ln.get("rate_paise", 0) or 0),
            gst_rate_percent=float(ln.get("gst_rate_bps", 1800) or 0) / 100.0,
            is_service=bool(ln.get("is_service", False)),
        )
        for ln in _template_lines(template, db)
    ]
    if not lines:
        raise HTTPException(status_code=422, detail="Template has no line items to invoice.")

    inv_in = SalesInvoiceIn(
        client_id=template["client_id"],
        customer_id=template["customer_id"],
        # Sales invoice numbering is fully manual (no CA present in an
        # unattended recurring run) — a placeholder the CA must replace with
        # the real invoice number before Issue. See draft_placeholder_invoice_no.
        invoice_no=draft_placeholder_invoice_no(),
        invoice_date=occurrence_iso,                     # Decision 4: invoice_date == occurrence
        due_date=due_date_for(occurrence_iso, customer),  # Decision 4: + credit_days (firm default fallback)
        lines=lines,
        is_inter_state=bool(template.get("is_inter_state", False)),
        # GSTR-1 classification (task #160). Without this the generated invoice
        # fell to migration 268's column defaults and every occurrence of an SEZ
        # or exempt engagement went out as a plain domestic taxable sale — in an
        # UNATTENDED job, so with no CA present to notice the mis-declaration.
        supply_type=template.get("supply_type") or "taxable",
        invoice_type=template.get("invoice_type") or "Regular",
        is_reverse_charge=bool(template.get("is_reverse_charge") or False),
        notes=template.get("notes")
        or f"Auto-generated draft from recurring template '{template.get('title', '')}' for {occurrence_iso}",
    )

    # REUSE the existing invoice engine — identical to a manually created invoice
    # (GST, FY-lock). It creates the invoice as a DRAFT; we never issue.
    from routers.sales_invoices import create_invoice
    resp = create_invoice(inv_in, actor)
    if not resp.get("success"):
        _record_run(firm_id, template["id"], occurrence_iso, None, "failed", {"error": resp.get("error")}, db)
        raise HTTPException(status_code=500, detail=resp.get("error") or "Recurring invoice generation failed.")

    invoice = _stamp_recurring(firm_id, resp["data"], template["id"], occurrence_iso, db)
    _record_run(firm_id, template["id"], occurrence_iso, invoice.get("id"), "generated", None, db)

    # Audit + timeline (best-effort; never an accounting event).
    try:
        from services.audit_service import log_event
        log_event(firm_id, "sales_invoice", invoice.get("id"), "recurring_generated",
                  actor_id=actor.get("auth_user_id"),
                  new_data={"template_id": template["id"], "occurrence": occurrence_iso, "status": "draft"},
                  metadata={"source": "recurring"})
    except Exception:  # pragma: no cover
        pass
    try:
        from services.timeline_service import timeline_service
        timeline_service.log(template.get("client_id", ""), "ai", "Recurring Draft Invoice Created",
                             f"Draft {invoice.get('invoice_no', '')} generated from template "
                             f"'{template.get('title', '')}' for {occurrence_iso} (awaiting CA review)", "info",
                             firm_id=firm_id, entity_type="sales_invoice", entity_id=invoice.get("id"),
                             amount_paise=int(invoice.get("total_paise", 0) or 0))
    except Exception:  # pragma: no cover
        pass
    return {"invoice": invoice, "occurrence": occurrence_iso, "created": True, "idempotent": False}


def generate_due_recurring_invoices(firm_id: str, client_id: Optional[str] = None,
                                    as_of=None, actor: Optional[dict] = None, db=None) -> dict:
    """Generate DRAFT invoices for every active template whose occurrences are due
    on/before `as_of`. Idempotent and safe to run repeatedly (manually or via the
    scheduler). Catches up missed occurrences (bounded). Never issues/posts/emails."""
    as_of = _d(as_of) if as_of else date.today()
    db = db or (None if _USE_MOCK else _db())
    actor = actor or _system_actor(firm_id)
    generated, skipped, failed = [], [], []

    for t in list_templates(firm_id, client_id=client_id, status="active", db=db):
        end = _d(t["end_date"]) if t.get("end_date") else None
        nrd = _d(t["next_run_date"]) if t.get("next_run_date") else None
        steps = 0
        while nrd and nrd <= as_of and (end is None or nrd <= end) and steps < MAX_CATCHUP_PER_RUN:
            occ = nrd.isoformat()
            try:
                res = _generate_one(firm_id, t, actor, occ, db)
                (generated if res["created"] else skipped).append(
                    {"template_id": t["id"], "occurrence": occ, "invoice_id": res["invoice"].get("id")})
            except Exception as e:
                _logger.error("recurring generation failed (%s/%s): %s", t["id"], occ, e)
                failed.append({"template_id": t["id"], "occurrence": occ, "error": str(e)})
                break  # stop this template; other templates still run
            nxt = next_occurrence(t["frequency"], t["start_date"], nrd)
            _set_next_run(firm_id, t["id"], nxt.isoformat() if nxt else None, db)
            nrd = nxt
            steps += 1

    return {"generated": generated, "skipped": skipped, "failed": failed,
            "generated_count": len(generated), "skipped_count": len(skipped), "failed_count": len(failed)}


def run_for_template(firm_id: str, template_id: str, as_of=None, actor: Optional[dict] = None, db=None) -> dict:
    """Manual single-template generation (CA-initiated 'Generate now')."""
    t = get_template(firm_id, template_id, db=db)
    if not t:
        raise HTTPException(status_code=404, detail="Recurring template not found.")
    if t.get("status") != "active":
        raise HTTPException(status_code=422, detail="Only active templates can be run.")
    # Reuse the batch engine scoped to this one template via its client + a filter.
    as_of = _d(as_of) if as_of else date.today()
    db = db or (None if _USE_MOCK else _db())
    actor = actor or _system_actor(firm_id)
    end = _d(t["end_date"]) if t.get("end_date") else None
    nrd = _d(t["next_run_date"]) if t.get("next_run_date") else None
    generated, skipped, failed = [], [], []
    steps = 0
    while nrd and nrd <= as_of and (end is None or nrd <= end) and steps < MAX_CATCHUP_PER_RUN:
        occ = nrd.isoformat()
        try:
            res = _generate_one(firm_id, t, actor, occ, db)
            (generated if res["created"] else skipped).append(
                {"template_id": t["id"], "occurrence": occ, "invoice_id": res["invoice"].get("id")})
        except Exception as e:
            failed.append({"template_id": t["id"], "occurrence": occ, "error": str(e)})
            break
        nxt = next_occurrence(t["frequency"], t["start_date"], nrd)
        _set_next_run(firm_id, t["id"], nxt.isoformat() if nxt else None, db)
        nrd = nxt
        steps += 1
    return {"generated": generated, "skipped": skipped, "failed": failed,
            "generated_count": len(generated), "skipped_count": len(skipped), "failed_count": len(failed)}


# ── History ──────────────────────────────────────────────────────────────────

def template_history(firm_id: str, template_id: str, db=None) -> list[dict]:
    """Generation history for a template (newest first), each row enriched with
    the generated invoice's number / status / total for the History UI."""
    if _USE_MOCK:
        from routers.sales_invoices import MOCK_SALES_INVOICES
        runs = sorted([dict(r) for r in MOCK_RECURRING_RUNS
                       if r["firm_id"] == firm_id and r["template_id"] == template_id],
                      key=lambda r: r.get("created_at") or "", reverse=True)
        inv_by_id = {i["id"]: i for i in MOCK_SALES_INVOICES}
        for r in runs:
            inv = inv_by_id.get(r.get("invoice_id")) or {}
            r["invoice"] = {"id": inv.get("id"), "invoice_no": inv.get("invoice_no"),
                            "status": inv.get("status"), "total_paise": inv.get("total_paise")}
        return runs
    db = db or _db()
    runs = (db.table("recurring_invoice_runs").select("*")
            .eq("firm_id", firm_id).eq("template_id", template_id)
            .order("created_at", desc=True).execute().data or [])
    inv_ids = [r["invoice_id"] for r in runs if r.get("invoice_id")]
    inv_by_id: dict = {}
    if inv_ids:
        invs = (db.table("client_sales_invoices")
                .select("id,invoice_no,status,total_paise").in_("id", inv_ids).execute().data or [])
        inv_by_id = {i["id"]: i for i in invs}
    for r in runs:
        r["invoice"] = inv_by_id.get(r.get("invoice_id"))
    return runs
