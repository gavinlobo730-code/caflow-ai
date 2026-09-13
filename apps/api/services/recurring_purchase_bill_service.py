"""
Recurring purchase bills (PUR-26) — schedule-driven generation of DRAFT
supplier bills from per-vendor templates.

THE AP TWIN OF `recurring_invoice_service`, and deliberately its shape: a
template, its lines, and a runs ledger keyed (template, occurrence) that is
both the history a screen shows and the record that makes generation
idempotent. Three recurring features now — sales invoices (migration 107),
journals (377) and this (379) — with one set of habits and ONE cadence engine,
`domain/recurrence`, which is imported rather than copied for the reason
CLAUDE.md gives: two cadence engines drifting means one feature generates in a
month the other skips.

LOCKED, and the same rule the other two carry: generation creates DRAFTS ONLY.
A purchase bill becomes an accounting event when a CA RECEIVES it — that is
what posts Dr Expense / Dr GST Input / Cr Trade Payables, withholds the TDS and
claims the credit. Nothing here receives, posts, or pays.

WHY THIS MATTERS MORE ON THE PURCHASE SIDE THAN THE SALES SIDE. Rent (s.194I),
a consultant's retainer (s.194J) and a monthly maintenance contract (s.194C)
are the bills TDS attaches to, and most of the s.194 series charges on the
YEAR'S AGGREGATE — so a month nobody entered does not merely lose an expense,
it changes what the NEXT bill should withhold, and with it the Rule 30(2)
deposit and the quarterly statement.

THE ONE FIELD THIS CANNOT INVENT is `bill_no`, the VENDOR'S own document
number. A landlord's invoice number is a fact about the landlord's books, and
it is half the key GSTR-2B matching uses (`domain/gst/itc_matching`), so a
generated draft leaves it NULL for the CA to fill in when the bill arrives.
`our_reference` — the firm's own tracking number — IS ours to choose and is
stamped.

Mock-mode (no SUPABASE_URL) mirrors the convention in recurring_invoice_service:
in-memory stores, and the bill engine writes to MOCK_PURCHASE_BILLS. All
functions accept an injectable `db` for DB-mode tests.
"""
import os
import uuid
import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import HTTPException

from core.observability import capture_soft_failure
from domain import recurrence as _rec
from models.invoices import PurchaseBillIn, PurchaseBillLineIn

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.recurring_purchase")

MAX_CATCHUP_PER_RUN = _rec.MAX_CATCHUP_PER_RUN
_FREQUENCIES = _rec.FREQUENCIES

#: One date parser, in domain/recurrence, for the same reason the cadence is.
_d = _rec.to_date

# Imported, not re-implemented — see the module docstring.
from domain.recurrence import next_occurrence                       # noqa: E402

# Mock stores (mock mode only).
MOCK_RECURRING_BILL_TEMPLATES: list[dict] = []
MOCK_RECURRING_BILL_RUNS: list[dict] = []


def _db():
    from core.supabase_client import get_supabase
    return get_supabase()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def draft_our_reference() -> str:
    """The firm's OWN reference for a bill nobody has typed yet.

    Unlike a sales invoice number this is not a statutory series — CGST Rule
    46(b) governs the number the SUPPLIER puts on the document, which here is
    `bill_no` and belongs to the vendor. `our_reference` is internal tracking,
    so an obviously-generated value costs nothing and makes an unreviewed draft
    findable. Deliberately not a running sequence: a draft that is never
    received would leave a permanent gap in one, and a gap in a series is a
    scrutiny query the background job must not create on the CA's behalf (the
    same reasoning as `numbering.draft_placeholder_invoice_no`).
    """
    return f"RECUR-{uuid.uuid4().hex[:10].upper()}"


# ── Template CRUD ────────────────────────────────────────────────────────────

def _validate(data: dict) -> None:
    if data.get("frequency") not in _FREQUENCIES:
        raise HTTPException(status_code=422, detail=f"frequency must be one of {_FREQUENCIES}")
    if not data.get("lines"):
        raise HTTPException(status_code=422, detail="A template needs at least one line item.")
    if data.get("end_date") and data.get("start_date") and _d(data["end_date"]) < _d(data["start_date"]):
        raise HTTPException(status_code=422, detail="end_date cannot be before start_date.")
    # A template holding a line the bill engine would REFUSE fails inside an
    # unattended 06:00 IST job, with no CA present to see it. PurchaseBillLineIn
    # has required a catalogue item since migration 206, so refuse here instead
    # — the same argument recurring_invoice_service makes for its GSTR-1
    # classification.
    for ln in data.get("lines") or []:
        if not (ln.get("service_catalogue_id") or "").strip():
            raise HTTPException(
                status_code=422,
                detail="Product/Service is required on every line item — a bill "
                       "the engine would refuse cannot be generated unattended.")


def _line_rows(lines: list[dict]) -> list[dict]:
    rows = []
    for i, ln in enumerate(lines):
        rows.append({
            "description": ln.get("description", ""),
            "hsn_sac": ln.get("hsn_sac"),
            "unit": ln.get("unit"),
            "quantity": float(ln.get("quantity", 1) or 1),
            "rate_paise": int(ln.get("rate_paise", 0) or 0),
            # The template stores basis points and the bill engine takes a
            # percentage — one conversion, here, so a rate cannot be 18 bps in
            # one place and 18% in another.
            "gst_rate_bps": int(round(float(ln.get("gst_rate_percent", 18) or 0) * 100))
            if "gst_rate_percent" in ln else int(ln.get("gst_rate_bps", 1800) or 0),
            "is_service": bool(ln.get("is_service", False)),
            # CGST s.17(5) — CA-set, never inferred (migration 240). Carried on
            # the template because it is a property of what is being bought,
            # not of the month.
            "itc_eligible": bool(ln.get("itc_eligible", True)),
            "blocked_credit_reason": ln.get("blocked_credit_reason"),
            "tds_applicable": bool(ln.get("tds_applicable", False)),
            "expense_account_id": ln.get("expense_account_id"),
            "service_catalogue_id": ln.get("service_catalogue_id"),
            "sort_order": int(ln.get("sort_order", i)),
        })
    return rows


def create_template(firm_id: str, data: dict, created_by: Optional[str], db=None) -> dict:
    _validate(data)
    start = _d(data["start_date"]).isoformat()
    payload = {
        "firm_id": firm_id,
        "client_id": data["client_id"],
        "vendor_id": data["vendor_id"],
        "title": data["title"],
        "description": data.get("description"),
        "frequency": data["frequency"],
        "start_date": start,
        "end_date": _d(data["end_date"]).isoformat() if data.get("end_date") else None,
        "next_run_date": start,                      # first run = first occurrence
        "notes": data.get("notes"),
        "is_inter_state": bool(data.get("is_inter_state", False)),
        "is_reverse_charge": bool(data.get("is_reverse_charge", False)),
        "status": "active",
        "created_by": created_by,
    }
    lines = _line_rows(data["lines"])
    if _USE_MOCK:
        payload["id"] = str(uuid.uuid4())
        payload["created_at"] = _now_iso()
        payload["lines"] = lines
        MOCK_RECURRING_BILL_TEMPLATES.append(payload)
        return dict(payload)
    db = db or _db()
    row = db.table("recurring_purchase_bill_templates").insert(payload).execute().data[0]
    for ln in lines:
        ln["template_id"] = row["id"]
    if lines:
        db.table("recurring_purchase_bill_template_lines").insert(lines).execute()
    row["lines"] = lines
    return row


def update_template(firm_id: str, template_id: str, data: dict, db=None) -> dict:
    existing = get_template(firm_id, template_id, db=db)
    if not existing:
        raise HTTPException(status_code=404, detail="Recurring bill template not found.")
    fields: dict = {}
    for k in ("title", "description", "frequency", "notes",
              "is_inter_state", "is_reverse_charge", "vendor_id"):
        if data.get(k) is not None:
            fields[k] = data[k]
    if fields.get("frequency") and fields["frequency"] not in _FREQUENCIES:
        raise HTTPException(status_code=422, detail=f"frequency must be one of {_FREQUENCIES}")
    if data.get("start_date") is not None:
        fields["start_date"] = _d(data["start_date"]).isoformat()
    if "end_date" in data:
        fields["end_date"] = _d(data["end_date"]).isoformat() if data.get("end_date") else None
    new_start = fields.get("start_date", existing["start_date"])
    new_end = fields["end_date"] if "end_date" in fields else existing.get("end_date")
    if new_end and _d(new_end) < _d(new_start):
        raise HTTPException(status_code=422, detail="end_date cannot be before start_date.")
    # Re-base the next run when the schedule's shape changes. Idempotency still
    # prevents a second bill for an occurrence already generated.
    if "start_date" in fields or "frequency" in fields:
        fields["next_run_date"] = _d(new_start).isoformat()
    fields["updated_at"] = _now_iso()

    new_lines = _line_rows(data["lines"]) if data.get("lines") is not None else None

    if _USE_MOCK:
        existing.update(fields)
        if new_lines is not None:
            existing["lines"] = new_lines
        for t in MOCK_RECURRING_BILL_TEMPLATES:
            if t["id"] == template_id:
                t.update(fields)
                if new_lines is not None:
                    t["lines"] = new_lines
        return dict(existing)
    db = db or _db()
    (db.table("recurring_purchase_bill_templates").update(fields)
       .eq("id", template_id).eq("firm_id", firm_id).execute())
    if new_lines is not None:
        (db.table("recurring_purchase_bill_template_lines").delete()
           .eq("template_id", template_id).execute())
        for ln in new_lines:
            ln["template_id"] = template_id
        if new_lines:
            db.table("recurring_purchase_bill_template_lines").insert(new_lines).execute()
    return get_template(firm_id, template_id, db=db)


def set_status(firm_id: str, template_id: str, status: str, db=None) -> dict:
    if status not in ("active", "paused", "archived"):
        raise HTTPException(status_code=422, detail="status must be active | paused | archived")
    existing = get_template(firm_id, template_id, db=db)
    if not existing:
        raise HTTPException(status_code=404, detail="Recurring bill template not found.")
    fields = {"status": status, "updated_at": _now_iso()}
    if _USE_MOCK:
        for t in MOCK_RECURRING_BILL_TEMPLATES:
            if t["id"] == template_id:
                t.update(fields)
        existing.update(fields)
        return dict(existing)
    db = db or _db()
    (db.table("recurring_purchase_bill_templates").update(fields)
       .eq("id", template_id).eq("firm_id", firm_id).execute())
    return get_template(firm_id, template_id, db=db)


def get_template(firm_id: str, template_id: str, db=None) -> Optional[dict]:
    if _USE_MOCK:
        t = next((x for x in MOCK_RECURRING_BILL_TEMPLATES
                  if x["id"] == template_id and x["firm_id"] == firm_id), None)
        return dict(t) if t else None
    db = db or _db()
    rows = (db.table("recurring_purchase_bill_templates").select("*")
            .eq("id", template_id).eq("firm_id", firm_id).limit(1).execute().data or [])
    if not rows:
        return None
    t = rows[0]
    t["lines"] = (db.table("recurring_purchase_bill_template_lines").select("*")
                  .eq("template_id", template_id).order("sort_order").execute().data or [])
    return t


def list_templates(firm_id: str, client_id: Optional[str] = None,
                   status: Optional[str] = None, include_archived: bool = True,
                   db=None) -> list[dict]:
    if _USE_MOCK:
        out = [dict(t) for t in MOCK_RECURRING_BILL_TEMPLATES if t["firm_id"] == firm_id]
        if client_id:
            out = [t for t in out if t.get("client_id") == client_id]
        if status:
            out = [t for t in out if t.get("status") == status]
        elif not include_archived:
            out = [t for t in out if t.get("status") != "archived"]
        return out
    db = db or _db()
    q = db.table("recurring_purchase_bill_templates").select("*").eq("firm_id", firm_id)
    if client_id:
        q = q.eq("client_id", client_id)
    if status:
        q = q.eq("status", status)
    rows = q.order("next_run_date").execute().data or []
    if status is None and not include_archived:
        rows = [r for r in rows if r.get("status") != "archived"]
    ids = [r["id"] for r in rows]
    lines_by_t: dict = {}
    if ids:
        all_lines = (db.table("recurring_purchase_bill_template_lines").select("*")
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
    return (db.table("recurring_purchase_bill_template_lines").select("*")
            .eq("template_id", template["id"]).order("sort_order").execute().data or [])


# ── Generation (DRAFT only) ──────────────────────────────────────────────────

def _system_actor(firm_id: str) -> dict:
    """Non-interactive actor for scheduler-driven generation."""
    return {"firm_id": firm_id, "id": None, "auth_user_id": None,
            "email": "scheduler@recurring", "role": "Partner"}


def _find_generated(firm_id: str, template_id: str, occurrence_iso: str, db=None) -> Optional[dict]:
    """The bill already generated for this (template, occurrence), if any — the
    authoritative idempotency check (one occurrence -> one bill)."""
    if _USE_MOCK:
        from routers.purchase_bills import MOCK_PURCHASE_BILLS
        for b in MOCK_PURCHASE_BILLS:
            if (b.get("recurring_template_id") == template_id
                    and b.get("recurring_occurrence") == occurrence_iso):
                return b
        return None
    db = db or _db()
    res = (db.table("purchase_bills").select("*")
           .eq("firm_id", firm_id).eq("recurring_template_id", template_id)
           .eq("recurring_occurrence", occurrence_iso).limit(1).execute().data or [])
    return res[0] if res else None


def _stamp_recurring(firm_id: str, bill: dict, template_id: str,
                     occurrence_iso: str, db=None) -> dict:
    fields = {"recurring_template_id": template_id, "recurring_occurrence": occurrence_iso}
    if _USE_MOCK:
        bill.update(fields)
        return bill
    db = db or _db()
    try:
        upd = (db.table("purchase_bills").update(fields)
               .eq("id", bill["id"]).eq("firm_id", firm_id).execute())
        return upd.data[0] if upd.data else {**bill, **fields}
    except Exception as e:
        # uq_purchase_bills_recurring lost the race. Delete the loser rather
        # than leave a second draft for one month, and return the winner —
        # exactly what recurring_invoice_service does. Safe to delete: the bill
        # is a DRAFT, so no journal, no stock movement and no TDS register row
        # exists behind it (all three happen at RECEIVE).
        _logger.warning("duplicate recurring bill for template %s occ %s: %s",
                        template_id, occurrence_iso, e)
        db.table("purchase_bill_lines").delete().eq("bill_id", bill["id"]).execute()
        db.table("purchase_bills").delete().eq("id", bill["id"]).execute()
        winner = _find_generated(firm_id, template_id, occurrence_iso, db)
        if winner:
            return winner
        raise


def _record_run(firm_id: str, template_id: str, occurrence_iso: str,
                bill_id: Optional[str], status: str, detail: Optional[dict], db=None) -> None:
    rec = {"firm_id": firm_id, "template_id": template_id, "occurrence_date": occurrence_iso,
           "purchase_bill_id": bill_id, "status": status, "detail": detail}
    if _USE_MOCK:
        rec["id"] = str(uuid.uuid4())
        rec["created_at"] = _now_iso()
        MOCK_RECURRING_BILL_RUNS.append(rec)
        return
    db = db or _db()
    try:
        (db.table("recurring_purchase_bill_runs")
           .upsert(rec, on_conflict="template_id,occurrence_date").execute())
    except Exception as e:  # pragma: no cover - history is best-effort
        _logger.warning("recurring bill run-log failed (%s/%s): %s",
                        template_id, occurrence_iso, e)


def _set_next_run(firm_id: str, template_id: str, next_run_iso: Optional[str], db=None) -> None:
    if _USE_MOCK:
        for t in MOCK_RECURRING_BILL_TEMPLATES:
            if t["id"] == template_id:
                t["next_run_date"] = next_run_iso
        return
    db = db or _db()
    (db.table("recurring_purchase_bill_templates")
       .update({"next_run_date": next_run_iso, "updated_at": _now_iso()})
       .eq("id", template_id).eq("firm_id", firm_id).execute())


def _generate_one(firm_id: str, template: dict, actor: dict,
                  occurrence_iso: str, db=None) -> dict:
    """Idempotently create ONE draft purchase bill for (template, occurrence).

    Reuses the existing bill engine, so GST, the s.17(5) split, the vendor's
    TDS section and the FY lock are the ordinary ones. Never receives, never
    posts, never pays.
    """
    existing = _find_generated(firm_id, template["id"], occurrence_iso, db)
    if existing:
        return {"bill": existing, "occurrence": occurrence_iso,
                "created": False, "idempotent": True}

    lines = [
        PurchaseBillLineIn(
            description=ln.get("description", ""),
            hsn_sac=ln.get("hsn_sac"),
            unit=ln.get("unit"),
            quantity=float(ln.get("quantity", 1) or 1),
            rate_paise=int(ln.get("rate_paise", 0) or 0),
            gst_rate_percent=float(ln.get("gst_rate_bps", 1800) or 0) / 100.0,
            is_service=bool(ln.get("is_service", False)),
            tds_applicable=bool(ln.get("tds_applicable", False)),
            expense_account_id=ln.get("expense_account_id"),
            service_catalogue_id=ln.get("service_catalogue_id"),
            itc_eligible=bool(ln.get("itc_eligible", True)),
            blocked_credit_reason=ln.get("blocked_credit_reason"),
        )
        for ln in _template_lines(template, db)
    ]
    if not lines:
        raise HTTPException(status_code=422, detail="Template has no line items to bill.")

    bill_in = PurchaseBillIn(
        client_id=template["client_id"],
        vendor_id=template["vendor_id"],
        bill_date=occurrence_iso,
        # bill_no is the VENDOR'S number and is left unset — see the module
        # docstring. our_reference is the firm's own and is stamped.
        our_reference=draft_our_reference(),
        lines=lines,
        is_inter_state=bool(template.get("is_inter_state", False)),
        is_reverse_charge=bool(template.get("is_reverse_charge", False)),
        notes=template.get("notes")
        or (f"Auto-generated draft from recurring template "
            f"'{template.get('title', '')}' for {occurrence_iso}. "
            f"Enter the supplier's own bill number before receiving."),
    )

    from routers.purchase_bills import create_purchase_bill
    resp = create_purchase_bill(bill_in, actor)
    if not resp.get("success"):
        _record_run(firm_id, template["id"], occurrence_iso, None, "failed",
                    {"error": resp.get("error")}, db)
        raise HTTPException(status_code=500,
                            detail=resp.get("error") or "Recurring bill generation failed.")

    bill = _stamp_recurring(firm_id, resp["data"], template["id"], occurrence_iso, db)
    _record_run(firm_id, template["id"], occurrence_iso, bill.get("id"), "generated", None, db)

    # Audit + timeline. Best-effort — the DRAFT is the deliverable and a
    # failure to narrate it must not undo one — but REPORTED rather than
    # swallowed: a run that silently stops writing its own history is exactly
    # the state this feature's idempotency ledger exists to make visible.
    try:
        from services.audit_service import log_event
        log_event(firm_id, "purchase_bill", bill.get("id"), "recurring_generated",
                  actor_id=actor.get("auth_user_id"),
                  new_data={"template_id": template["id"], "occurrence": occurrence_iso,
                            "status": "draft"},
                  metadata={"source": "recurring"})
    except Exception as e:  # pragma: no cover
        capture_soft_failure(e, operation="recurring_bill.audit",
                             firm_id=firm_id, template_id=template["id"],
                             occurrence=occurrence_iso)
    try:
        from services.timeline_service import timeline_service
        timeline_service.log(
            template.get("client_id", ""), "ai", "Recurring Draft Bill Created",
            f"Draft bill {bill.get('our_reference', '')} generated from template "
            f"'{template.get('title', '')}' for {occurrence_iso} (awaiting CA review)",
            "info", firm_id=firm_id, entity_type="purchase_bill", entity_id=bill.get("id"),
            amount_paise=int(bill.get("total_paise", 0) or 0))
    except Exception as e:  # pragma: no cover
        capture_soft_failure(e, operation="recurring_bill.timeline",
                             firm_id=firm_id, template_id=template["id"],
                             occurrence=occurrence_iso)
    return {"bill": bill, "occurrence": occurrence_iso, "created": True, "idempotent": False}


def _run_template(firm_id: str, t: dict, actor: dict, as_of: date, db) -> dict:
    """Walk ONE template's due occurrences. Shared by the sweep and the manual
    single-template run, so the catch-up rule cannot differ between them."""
    end = _d(t["end_date"]) if t.get("end_date") else None
    nrd = _d(t["next_run_date"]) if t.get("next_run_date") else None
    generated, skipped, failed = [], [], []
    steps = 0
    while nrd and nrd <= as_of and (end is None or nrd <= end) and steps < MAX_CATCHUP_PER_RUN:
        occ = nrd.isoformat()
        try:
            res = _generate_one(firm_id, t, actor, occ, db)
            (generated if res["created"] else skipped).append(
                {"template_id": t["id"], "occurrence": occ, "bill_id": res["bill"].get("id")})
        except Exception as e:
            # RECORDED, and the template does NOT advance: a template that
            # cannot generate needs a CA, and advancing past a failure would
            # skip the month silently — the rule migration 377 states.
            _logger.error("recurring bill generation failed (%s/%s): %s", t["id"], occ, e)
            failed.append({"template_id": t["id"], "occurrence": occ, "error": str(e)})
            break
        nxt = next_occurrence(t["frequency"], t["start_date"], nrd)
        _set_next_run(firm_id, t["id"], nxt.isoformat() if nxt else None, db)
        nrd = nxt
        steps += 1
    return {"generated": generated, "skipped": skipped, "failed": failed}


def generate_due_recurring_bills(firm_id: str, client_id: Optional[str] = None,
                                 as_of=None, actor: Optional[dict] = None, db=None) -> dict:
    """Generate DRAFT bills for every active template due on/before `as_of`.

    Idempotent and safe to run repeatedly (manually or via the scheduler).
    Catches up missed occurrences, bounded by MAX_CATCHUP_PER_RUN. Never
    receives, posts or pays.
    """
    as_of = _d(as_of) if as_of else date.today()
    db = db or (None if _USE_MOCK else _db())
    actor = actor or _system_actor(firm_id)
    generated, skipped, failed = [], [], []
    for t in list_templates(firm_id, client_id=client_id, status="active", db=db):
        out = _run_template(firm_id, t, actor, as_of, db)
        generated += out["generated"]
        skipped += out["skipped"]
        failed += out["failed"]
    return {"generated": generated, "skipped": skipped, "failed": failed,
            "generated_count": len(generated), "skipped_count": len(skipped),
            "failed_count": len(failed)}


def run_for_template(firm_id: str, template_id: str, as_of=None,
                     actor: Optional[dict] = None, db=None) -> dict:
    """Manual single-template generation (CA-initiated 'Generate now')."""
    t = get_template(firm_id, template_id, db=db)
    if not t:
        raise HTTPException(status_code=404, detail="Recurring bill template not found.")
    if t.get("status") != "active":
        raise HTTPException(status_code=422, detail="Only active templates can be run.")
    as_of = _d(as_of) if as_of else date.today()
    db = db or (None if _USE_MOCK else _db())
    actor = actor or _system_actor(firm_id)
    out = _run_template(firm_id, t, actor, as_of, db)
    return {**out,
            "generated_count": len(out["generated"]),
            "skipped_count": len(out["skipped"]),
            "failed_count": len(out["failed"])}


# ── History ──────────────────────────────────────────────────────────────────

def template_history(firm_id: str, template_id: str, db=None) -> list[dict]:
    """Generation history for a template (newest first), each row enriched with
    the generated bill's reference / status / total for the History UI."""
    if _USE_MOCK:
        from routers.purchase_bills import MOCK_PURCHASE_BILLS
        runs = sorted([dict(r) for r in MOCK_RECURRING_BILL_RUNS
                       if r["firm_id"] == firm_id and r["template_id"] == template_id],
                      key=lambda r: r.get("created_at") or "", reverse=True)
        by_id = {b["id"]: b for b in MOCK_PURCHASE_BILLS}
        for r in runs:
            b = by_id.get(r.get("purchase_bill_id")) or {}
            r["bill"] = {"id": b.get("id"), "bill_no": b.get("bill_no"),
                         "our_reference": b.get("our_reference"),
                         "status": b.get("status"), "total_paise": b.get("total_paise")}
        return runs
    db = db or _db()
    runs = (db.table("recurring_purchase_bill_runs").select("*")
            .eq("firm_id", firm_id).eq("template_id", template_id)
            .order("created_at", desc=True).execute().data or [])
    ids = [r["purchase_bill_id"] for r in runs if r.get("purchase_bill_id")]
    by_id: dict = {}
    if ids:
        bills = (db.table("purchase_bills")
                 .select("id,bill_no,our_reference,status,total_paise")
                 .in_("id", ids).execute().data or [])
        by_id = {b["id"]: b for b in bills}
    for r in runs:
        r["bill"] = by_id.get(r.get("purchase_bill_id"))
    return runs
