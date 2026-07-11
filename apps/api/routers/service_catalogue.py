"""Product & Service master — billing presets for goods AND services (Batch 6;
broadened from services-only in the HSN/SAC architecture redesign).

A client's repeatable products/services (name + default HSN/SAC, GST rate,
unit price) so the invoice editor can drop a fully pre-priced line in one
pick. Historically NOT an inventory master (no stock, valuation, quantity,
SKU, barcode or warehouse — only billing defaults); migration 188
deliberately supersedes that for kind='good' rows, which now also carry
real stock quantity and moving-average cost (domain/inventory_service.py).
kind='service' rows are unaffected — those columns stay NULL/0 for them.

CLIENT-owned (migration 182): "Client B must never inherit Client A's
products." Every row belongs to exactly one client; RLS (can_access_client)
enforces this in addition to the app-level firm_id checks below. A preset is
a snapshot SOURCE: picking one copies its values onto the invoice line
(invoice lines store their own free-text HSN/rate/amount, no FK here), so
editing/archiving a preset never changes a past invoice. The stored
rate/price are pre-fill hints (CGST Rule 46(g)) — never used in tax/journal math.

`hsn_sac`, when set, must be a code already in the FIRM's own
`firm_hsn_library` (Decision C: HSN/SAC is selected only from the firm's
library, never authored ad hoc here) — the library itself stays firm-wide,
shared across all of the firm's clients, even though the Product/Service
referencing a code is client-owned. Enforced by `_hsn_in_library` below, an
application-layer check rather than a DB foreign key, so retiring a library
code can never break an existing product/service row.
"""
import os
import re
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ValidationError as PydanticValidationError
from models.common import api_response
from models.service_catalogue import ServiceCatalogueIn, ServiceCatalogueUpdateIn
from core.permissions import rbac

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.service_catalogue")

router = APIRouter(prefix="/api/service-catalogue", tags=["service_catalogue"])

# Mock store (used when SUPABASE_URL is not configured), mirrors customers.py.
MOCK_SERVICES: list[dict] = []

_SAFE_Q = re.compile(r"[^A-Za-z0-9 ]+")


def _hsn_in_library(firm_id: str, hsn_code: str) -> bool:
    """True if `hsn_code` is an ACTIVE row in this firm's own HSN/SAC
    library. A blank hsn_code is always allowed (HSN/SAC stays optional)."""
    if not hsn_code:
        return True
    if _USE_MOCK:
        from routers.firm_hsn_library import MOCK_LIBRARY
        return any(
            r for r in MOCK_LIBRARY
            if r.get("firm_id") == firm_id and r.get("hsn_code") == hsn_code
            and r.get("is_active", True)
        )
    from core.supabase_client import get_supabase
    db = get_supabase()
    rows = (
        db.table("firm_hsn_library").select("id")
        .eq("firm_id", firm_id).eq("hsn_code", hsn_code).eq("is_active", True)
        .execute().data or []
    )
    return bool(rows)


def _norm_name(v: Optional[str]) -> str:
    """Case/space-insensitive key for duplicate detection."""
    return re.sub(r"\s+", " ", (v or "").strip()).lower()


def _rank_services(term: str, rows: list[dict]) -> list[dict]:
    """Relevance-rank presets for a search term (pure, unit-testable).

      0 exact name         1 name prefix        2 name substring
      3 SAC/HSN prefix      4 description / notes / hsn substring
      5 no textual match (kept; the DB filter already narrowed)

    Ties preserve the input order, which the caller pre-sorts recency-then-
    frequency — so within a relevance tier the most recent/most used wins,
    giving "recent" and "frequently used" for free.
    """
    t = _norm_name(term)

    def rank(idx_row):
        i, r = idx_row
        name = _norm_name(r.get("name"))
        desc = _norm_name(r.get("description"))
        notes = _norm_name(r.get("notes"))
        hsn = (r.get("hsn_sac") or "").lower()
        if name == t:
            bucket = 0
        elif t and name.startswith(t):
            bucket = 1
        elif t and t in name:
            bucket = 2
        elif t and hsn.startswith(t):
            bucket = 3
        elif t and (t in desc or t in notes or t in hsn):
            bucket = 4
        else:
            bucket = 5
        return (bucket, i)

    return [r for _, r in sorted(enumerate(rows), key=rank)]


def _sort_recent_first(rows: list[dict]) -> list[dict]:
    """Recency-then-frequency ordering (mirrors the DB rank index)."""
    return sorted(
        rows,
        key=lambda r: (r.get("last_used_at") or "", r.get("use_count") or 0),
        reverse=True,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/")
def list_services(
    client_id: str = Query(..., description="CA client ID — required, Products & Services are client-owned"),
    q: str = Query("", description="Search by name, description or SAC/HSN"),
    include_archived: bool = Query(False),
    limit: int = Query(20, ge=1, le=500),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """List/search one client's presets. Active-only by default; ranked by
    relevance then recency/frequency. Empty query returns the recent/frequent
    presets (the picker's before-you-type list)."""
    try:
        term = _SAFE_Q.sub(" ", (q or "").strip()).strip()
        firm_id = current_user.get("firm_id")

        if _USE_MOCK:
            rows = [s for s in MOCK_SERVICES if s.get("firm_id") == firm_id and s.get("client_id") == client_id]
            if not include_archived:
                rows = [s for s in rows if s.get("is_active", True)]
            rows = _sort_recent_first(rows)
            if term:
                rows = [r for r in _rank_services(term, rows) if _matches(term, r)]
            return api_response(True, rows[:limit])

        from core.supabase_client import get_supabase
        db = get_supabase()
        query = db.table("service_catalogue").select("*").eq("firm_id", firm_id).eq("client_id", client_id)
        if not include_archived:
            query = query.eq("is_active", True)
        if term:
            query = query.or_(
                f"name.ilike.*{term}*,description.ilike.*{term}*,hsn_sac.ilike.{term}*"
            )
        rows = (
            query.order("last_used_at", desc=True)
            .order("use_count", desc=True)
            .order("name")
            .limit(limit * 2)
            .execute()
            .data
            or []
        )
        rows = _rank_services(term, rows) if term else rows
        return api_response(True, rows[:limit])
    except Exception as e:
        _logger.error("list_services: %s", e)
        return api_response(False, None, "Unable to load the service catalogue. Please try again.")


def _matches(term: str, row: dict) -> bool:
    """Mock-mode text filter mirroring the DB or() clause."""
    t = _norm_name(term)
    return (
        t in _norm_name(row.get("name"))
        or t in _norm_name(row.get("description"))
        or (row.get("hsn_sac") or "").lower().startswith(t)
    )


@router.post("/")
def create_service(
    data: ServiceCatalogueIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Create a preset. A second ACTIVE preset with the same name (case/space-
    insensitive) is rejected as a duplicate: the existing row is returned with
    duplicate=True and nothing is inserted."""
    try:
        firm_id = current_user.get("firm_id")
        payload = data.model_dump()
        client_id = payload["client_id"]
        if payload.get("hsn_sac") and not _hsn_in_library(firm_id, payload["hsn_sac"]):
            return api_response(
                False, None,
                "That HSN/SAC code is not in your firm's library. Add it there first.",
            )
        payload["firm_id"] = firm_id
        payload["is_active"] = True
        now = datetime.now(timezone.utc).isoformat()
        payload["created_at"] = now
        payload["updated_at"] = now
        key = _norm_name(payload["name"])

        if _USE_MOCK:
            existing = next(
                (s for s in MOCK_SERVICES
                 if s.get("firm_id") == firm_id and s.get("client_id") == client_id
                 and s.get("is_active", True) and _norm_name(s.get("name")) == key),
                None,
            )
            if existing:
                return api_response(True, {**existing, "duplicate": True})
            payload["id"] = str(uuid.uuid4())
            payload["use_count"] = 0
            payload["last_used_at"] = None
            MOCK_SERVICES.append(payload)
            return api_response(True, payload)

        from core.supabase_client import get_supabase
        db = get_supabase()
        existing_rows = (
            db.table("service_catalogue").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id).eq("is_active", True)
            .execute().data or []
        )
        existing = next((s for s in existing_rows if _norm_name(s.get("name")) == key), None)
        if existing:
            return api_response(True, {**existing, "duplicate": True})
        resp = db.table("service_catalogue").insert(payload).execute()
        created = resp.data[0] if resp.data else payload

        # Seed the moving-average costing ledger from the opening balance, if
        # one was given (goods only — meaningless for services, and
        # seed_opening_balance itself no-ops if either field is missing).
        # Never blocks creation: a failure here is logged, not raised.
        if payload.get("kind") == "good" and (payload.get("opening_qty_units") or payload.get("opening_cost_paise")):
            try:
                from domain.inventory_service import seed_opening_balance
                seed_opening_balance(
                    db, firm_id=firm_id, client_id=client_id, service_catalogue_id=created["id"],
                    movement_date=now[:10], opening_qty=payload.get("opening_qty_units"),
                    opening_cost_paise=payload.get("opening_cost_paise"),
                    # journal_entries.created_by FK references users(id), not auth_user_id.
                    created_by=current_user.get("id"),
                )
            except Exception as e:
                _logger.error("create_service: opening balance seeding failed for %s: %s", created.get("id"), e, exc_info=True)

        return api_response(True, created)
    except Exception as e:
        _logger.error("create_service: %s", e)
        return api_response(False, None, "Unable to create the service. Please try again.")


class ServiceBulkIn(BaseModel):
    """Loose body — items are validated individually inside the handler (via
    ServiceCatalogueIn(**item)) so one malformed CSV row cannot 422 the whole
    batch."""
    services: list[dict]


@router.post("/bulk")
def bulk_create_services(
    data: ServiceBulkIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Bulk product/service import (CSV upload).

    Mirrors bulk_create_customers: instead of the frontend firing one
    POST /api/service-catalogue/ per row, this does ONE HSN/SAC-library
    snapshot (per firm, not per row), ONE duplicate-name snapshot (per
    distinct client_id in the batch, not per row) and ONE batch insert.

    Duplicate matching mirrors create_service's own rule exactly: a second
    ACTIVE preset with the same case/space-insensitive name is a duplicate,
    checked against both the pre-fetched existing rows AND rows already
    accepted earlier in this same batch.
    """
    try:
        firm_id = current_user.get("firm_id")
        items = data.services or []

        created: list[dict] = []
        duplicates: list[dict] = []
        errors: list[dict] = []

        # ── Step 1: per-item validation ──────────────────────────────────────
        validated: list[tuple[int, dict]] = []
        for idx, item in enumerate(items):
            item = item if isinstance(item, dict) else {}
            try:
                parsed = ServiceCatalogueIn(**item)
            except PydanticValidationError as e:
                msgs = "; ".join(err.get("msg", str(err)) for err in e.errors())
                errors.append({"index": idx, "name": item.get("name"), "error": msgs})
                continue
            except Exception as e:
                errors.append({"index": idx, "name": item.get("name"), "error": str(e)})
                continue
            payload = parsed.model_dump()
            payload["firm_id"] = firm_id
            payload["is_active"] = True
            now = datetime.now(timezone.utc).isoformat()
            payload["created_at"] = now
            payload["updated_at"] = now
            payload["id"] = str(uuid.uuid4())
            validated.append((idx, payload))

        if not validated:
            return api_response(True, {"created": created, "duplicates": duplicates, "errors": errors})

        # ── Step 2: HSN/SAC library check — ONE snapshot for this firm instead
        # of one query per row (_hsn_in_library, hoisted). ──────────────────────
        db = None
        active_hsn_codes: set = set()
        if _USE_MOCK:
            from routers.firm_hsn_library import MOCK_LIBRARY
            active_hsn_codes = {
                r.get("hsn_code") for r in MOCK_LIBRARY
                if r.get("firm_id") == firm_id and r.get("is_active", True)
            }
        else:
            from core.supabase_client import get_supabase
            db = get_supabase()
            hsn_rows = (
                db.table("firm_hsn_library").select("hsn_code")
                .eq("firm_id", firm_id).eq("is_active", True).execute().data or []
            )
            active_hsn_codes = {r.get("hsn_code") for r in hsn_rows}

        checked: list[tuple[int, dict]] = []
        for idx, payload in validated:
            hsn = payload.get("hsn_sac")
            if hsn and hsn not in active_hsn_codes:
                errors.append({
                    "index": idx, "name": payload.get("name"),
                    "error": "That HSN/SAC code is not in your firm's library. Add it there first.",
                })
                continue
            checked.append((idx, payload))

        if not checked:
            return api_response(True, {"created": created, "duplicates": duplicates, "errors": errors})

        # ── Step 3: duplicate-name snapshot — ONE query per distinct client_id
        # in the batch (this importer is always scoped to a single client_id
        # per CSV upload in practice, so this is a single query in the common
        # case). ─────────────────────────────────────────────────────────────
        client_ids = sorted({p.get("client_id") for _, p in checked})
        existing_by_client: dict[str, list[dict]] = {}
        if _USE_MOCK:
            for cid in client_ids:
                existing_by_client[cid] = [
                    s for s in MOCK_SERVICES
                    if s.get("client_id") == cid and s.get("firm_id") == firm_id and s.get("is_active", True)
                ]
        else:
            for cid in client_ids:
                resp = (
                    db.table("service_catalogue").select("*")
                    .eq("client_id", cid).eq("firm_id", firm_id).eq("is_active", True)
                    .execute()
                )
                existing_by_client[cid] = resp.data or []

        # ── Step 4: duplicate guard — against the DB snapshot AND rows already
        # accepted earlier in this batch. ────────────────────────────────────
        accepted_in_batch: dict[str, list[dict]] = {cid: [] for cid in client_ids}
        to_insert: list[tuple[int, dict]] = []
        for idx, payload in checked:
            cid = payload.get("client_id")
            key = _norm_name(payload.get("name"))
            candidates = existing_by_client.get(cid, []) + accepted_in_batch.get(cid, [])
            match = next((s for s in candidates if _norm_name(s.get("name")) == key), None)
            if match:
                duplicates.append({"index": idx, "name": payload.get("name"), "existing_id": match.get("id")})
                continue
            accepted_in_batch.setdefault(cid, []).append(payload)
            to_insert.append((idx, payload))

        if not to_insert:
            return api_response(True, {"created": created, "duplicates": duplicates, "errors": errors})

        # ── Step 5: ONE batch insert for every new row. ─────────────────────────
        if _USE_MOCK:
            for idx, payload in to_insert:
                payload["use_count"] = 0
                payload["last_used_at"] = None
                MOCK_SERVICES.append(payload)
                created.append(payload)
        else:
            resp = db.table("service_catalogue").insert([p for _, p in to_insert]).execute()
            rows = resp.data or [p for _, p in to_insert]
            created.extend(rows)

            # Seed the moving-average costing ledger for every imported goods
            # row that came with an opening balance — batched (one ledger
            # insert + one cache upsert for the WHOLE batch), not per row.
            # Every row here just got a brand-new id above, so there is no
            # existing ledger entry to guard against (unlike the single-create
            # path's seed_opening_balance, which stays per-row/idempotent for
            # PATCH-time opening-balance additions to an already-live item).
            # Never blocks the import: seeding failures are logged, not raised.
            from domain.inventory_service import seed_opening_balances_batch
            seed_opening_balances_batch(
                # journal_entries.created_by FK references users(id), not auth_user_id.
                db, firm_id=firm_id, created_by=current_user.get("id"), rows=rows,
            )

        return api_response(True, {"created": created, "duplicates": duplicates, "errors": errors})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("bulk_create_services: %s", e)
        return api_response(False, None, "Unable to complete product/service import. Please try again.")


@router.patch("/{service_id}")
def update_service(
    service_id: str,
    data: ServiceCatalogueUpdateIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Edit a preset, or archive/restore it via is_active. Renaming to an
    existing active name is rejected as a duplicate."""
    try:
        firm_id = current_user.get("firm_id")
        patch = {k: v for k, v in data.model_dump().items() if v is not None}
        if not patch:
            raise HTTPException(status_code=422, detail="No fields to update.")
        if "hsn_sac" in patch and not _hsn_in_library(firm_id, patch["hsn_sac"]):
            return api_response(
                False, None,
                "That HSN/SAC code is not in your firm's library. Add it there first.",
            )
        patch["updated_at"] = datetime.now(timezone.utc).isoformat()

        if _USE_MOCK:
            row = next((s for s in MOCK_SERVICES
                        if s.get("id") == service_id and s.get("firm_id") == firm_id), None)
            if not row:
                raise HTTPException(status_code=404, detail="Service not found.")
            if "name" in patch:
                key = _norm_name(patch["name"])
                clash = any(
                    s for s in MOCK_SERVICES
                    if s.get("id") != service_id and s.get("firm_id") == firm_id
                    and s.get("client_id") == row.get("client_id")
                    and s.get("is_active", True) and _norm_name(s.get("name")) == key
                )
                if clash:
                    return api_response(False, None, "Another active service already uses that name.")
            row.update(patch)
            return api_response(True, row)

        from core.supabase_client import get_supabase
        db = get_supabase()
        owned = (db.table("service_catalogue").select("*")
                 .eq("id", service_id).eq("firm_id", firm_id).execute().data or [])
        if not owned:
            raise HTTPException(status_code=404, detail="Service not found.")
        if "name" in patch:
            key = _norm_name(patch["name"])
            others = (db.table("service_catalogue").select("id,name,is_active")
                      .eq("firm_id", firm_id).eq("client_id", owned[0]["client_id"]).eq("is_active", True)
                      .execute().data or [])
            if any(o for o in others if o["id"] != service_id and _norm_name(o.get("name")) == key):
                return api_response(False, None, "Another active service already uses that name.")
        resp = (db.table("service_catalogue").update(patch)
                .eq("id", service_id).eq("firm_id", firm_id).execute())
        updated = resp.data[0] if resp.data else {**owned[0], **patch}

        if owned[0].get("kind") == "good" and "opening_qty_units" in patch and "opening_cost_paise" in patch:
            try:
                from domain.inventory_service import seed_opening_balance
                seed_opening_balance(
                    db, firm_id=firm_id, client_id=owned[0]["client_id"], service_catalogue_id=service_id,
                    movement_date=datetime.now(timezone.utc).date().isoformat(),
                    opening_qty=patch.get("opening_qty_units"), opening_cost_paise=patch.get("opening_cost_paise"),
                    # journal_entries.created_by FK references users(id), not auth_user_id.
                    created_by=current_user.get("id"),
                )
            except Exception as e:
                _logger.error("update_service: opening balance seeding failed for %s: %s", service_id, e, exc_info=True)

        return api_response(True, updated)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("update_service: %s", e)
        return api_response(False, None, "Unable to update the service. Please try again.")



# ── Permanent delete ─────────────────────────────────────────────────────────
# service_catalogue_id (migration 184, extended to Purchase Bill/Credit Note/
# Debit Note lines by 189) is a REAL link, set the moment a preset is picked
# via ServiceCataloguePicker and copied through create/update alike — so this
# checks actual usage, not a proxy, the same way customer deletion checks real
# linked records (routers/customers.py's _customer_dependencies). A draft or
# cancelled document was never a final financial record, so it doesn't count
# — mirrors CGST Act §34: once a document is actually issued, correcting it
# means a Credit/Debit Note, not silently editing what it referenced. Archive
# (is_active=false via PATCH) remains the only removal path once a preset has
# genuinely been used.

_SERVICE_USAGE_CHECKS = [
    ("a sales invoice", "client_sales_invoice_lines", "sales_invoice_id", "client_sales_invoices"),
    ("a purchase bill", "purchase_bill_lines", "bill_id", "purchase_bills"),
    ("a credit note", "credit_note_lines", "credit_note_id", "credit_notes"),
    ("a debit note", "debit_note_lines", "debit_note_id", "debit_notes"),
]


def _find_service_usage(db, service_id: str) -> list[str]:
    """Two-step per document type (fetch linked lines, then their parents'
    status) rather than a single embedded-join query — PostgREST supports
    `parent!inner(status)` embedding, but keeping this to plain eq/in_ filters
    means it also runs correctly against the FakeDB test harness, which has
    no join support at all."""
    found: list[str] = []
    for label, line_table, fk_col, parent_table in _SERVICE_USAGE_CHECKS:
        lines = (
            db.table(line_table).select(f"id, {fk_col}")
            .eq("service_catalogue_id", service_id).execute().data or []
        )
        parent_ids = list({ln[fk_col] for ln in lines if ln.get(fk_col)})
        if not parent_ids:
            continue
        parents = (
            db.table(parent_table).select("id, status")
            .in_("id", parent_ids).execute().data or []
        )
        if any(p.get("status") not in ("draft", "cancelled") for p in parents):
            found.append(label)
    # inventory_stock_ledger.service_catalogue_id cascades on delete (migration
    # 188) — silently wiping real stock movement history otherwise.
    if (db.table("inventory_stock_ledger").select("id")
            .eq("service_catalogue_id", service_id).limit(1).execute().data or []):
        found.append("your inventory stock ledger (it has recorded stock movements)")
    return found


def _find_service_usage_mock(service_id: str) -> list[str]:
    """Mock-mode equivalent — deferred imports of each router's in-memory
    store to avoid a circular import (mirrors firm_hsn_library.py's
    _find_hsn_usage_mock)."""
    found: list[str] = []

    from routers.sales_invoices import MOCK_SALES_INVOICE_LINES, MOCK_SALES_INVOICES
    invoices_by_id = {i.get("id"): i for i in MOCK_SALES_INVOICES}
    if any(
        (invoices_by_id.get(ln.get("sales_invoice_id")) or {}).get("status") not in ("draft", "cancelled")
        for ln in MOCK_SALES_INVOICE_LINES if ln.get("service_catalogue_id") == service_id
    ):
        found.append("a sales invoice")

    from routers.purchase_bills import MOCK_PURCHASE_BILL_LINES, MOCK_PURCHASE_BILLS
    bills_by_id = {b.get("id"): b for b in MOCK_PURCHASE_BILLS}
    if any(
        (bills_by_id.get(ln.get("bill_id")) or {}).get("status") not in ("draft", "cancelled")
        for ln in MOCK_PURCHASE_BILL_LINES if ln.get("service_catalogue_id") == service_id
    ):
        found.append("a purchase bill")

    from routers.credit_notes import MOCK_CREDIT_NOTE_LINES, MOCK_CREDIT_NOTES
    cn_by_id = {c.get("id"): c for c in MOCK_CREDIT_NOTES}
    if any(
        (cn_by_id.get(ln.get("credit_note_id")) or {}).get("status") not in ("draft", "cancelled")
        for ln in MOCK_CREDIT_NOTE_LINES if ln.get("service_catalogue_id") == service_id
    ):
        found.append("a credit note")

    from routers.debit_notes import MOCK_DEBIT_NOTE_LINES, MOCK_DEBIT_NOTES
    dn_by_id = {d.get("id"): d for d in MOCK_DEBIT_NOTES}
    if any(
        (dn_by_id.get(ln.get("debit_note_id")) or {}).get("status") not in ("draft", "cancelled")
        for ln in MOCK_DEBIT_NOTE_LINES if ln.get("service_catalogue_id") == service_id
    ):
        found.append("a debit note")

    return found


def _service_blocked_message(used_in: list[str]) -> str:
    return f"This product/service is used on {', '.join(used_in)} and can't be permanently deleted. Archive it instead."


@router.delete("/{service_id}")
def delete_service(
    service_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Permanently delete a preset — only when it is not linked to any real,
    non-draft/cancelled document, or to any inventory stock movement. See the
    module note above for what counts as "used" and why."""
    try:
        firm_id = current_user.get("firm_id")

        if _USE_MOCK:
            row = next((s for s in MOCK_SERVICES
                        if s.get("id") == service_id and s.get("firm_id") == firm_id), None)
            if not row:
                raise HTTPException(status_code=404, detail="Service not found.")
            used_in = _find_service_usage_mock(service_id)
            if used_in:
                return api_response(False, None, _service_blocked_message(used_in))
            MOCK_SERVICES.remove(row)
            return api_response(True, {"id": service_id})

        from core.supabase_client import get_supabase
        db = get_supabase()
        owned = (db.table("service_catalogue").select("id")
                 .eq("id", service_id).eq("firm_id", firm_id).execute().data or [])
        if not owned:
            raise HTTPException(status_code=404, detail="Service not found.")
        used_in = _find_service_usage(db, service_id)
        if used_in:
            return api_response(False, None, _service_blocked_message(used_in))
        db.table("service_catalogue").delete().eq("id", service_id).eq("firm_id", firm_id).execute()
        return api_response(True, {"id": service_id})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("delete_service: %s", e)
        return api_response(False, None, "Unable to delete the service. Please try again.")


@router.post("/{service_id}/used")
def record_service_used(
    service_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Fire-and-forget usage bump (use_count += 1, last_used_at = now) so the
    picker can rank recent/frequent presets. Decoupled from invoice posting: the
    editor calls this when a preset is picked; it touches no accounting state."""
    try:
        firm_id = current_user.get("firm_id")
        now = datetime.now(timezone.utc).isoformat()

        if _USE_MOCK:
            row = next((s for s in MOCK_SERVICES
                        if s.get("id") == service_id and s.get("firm_id") == firm_id), None)
            if not row:
                raise HTTPException(status_code=404, detail="Service not found.")
            row["use_count"] = (row.get("use_count") or 0) + 1
            row["last_used_at"] = now
            return api_response(True, {"id": service_id, "use_count": row["use_count"]})

        from core.supabase_client import get_supabase
        db = get_supabase()
        owned = (db.table("service_catalogue").select("use_count")
                 .eq("id", service_id).eq("firm_id", firm_id).execute().data or [])
        if not owned:
            raise HTTPException(status_code=404, detail="Service not found.")
        next_count = (owned[0].get("use_count") or 0) + 1
        db.table("service_catalogue").update(
            {"use_count": next_count, "last_used_at": now}
        ).eq("id", service_id).eq("firm_id", firm_id).execute()
        return api_response(True, {"id": service_id, "use_count": next_count})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("record_service_used: %s", e)
        return api_response(False, None, "Unable to record service usage. Please try again.")
