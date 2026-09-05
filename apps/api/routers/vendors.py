"""Vendor master — CRUD with GSTIN validation.
Client-scoped: every vendor belongs to a CA client.
CGST Act Section 25: Registration of person. GSTIN format: 2-digit state + PAN (10) + entity + Z + check.
IT Act Section 194C/194I/194J: TDS applicable vendors tracked here.
"""
import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from domain.gst.gstin import problem_with as gstin_problem
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ValidationError
from models.common import api_response
from models.parties import VendorIn, VendorUpdateIn
from core.authz import assert_client_access, can_access_client
from core.permissions import rbac
from services import party_erasure
from services.audit_service import log_event
from services.timeline_service import timeline_service


def _current_fy_long() -> str:
    """Return full financial year string like '2025-26'. Indian FY: April 1 – March 31."""
    now = datetime.now(timezone.utc)
    start = now.year if now.month >= 4 else now.year - 1
    return f"{start}-{str(start + 1)[2:]}"

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.vendors")

router = APIRouter(prefix="/api/vendors", tags=["vendors"])


# ── Client-assignment scope (M2) ──────────────────────────────────────────────
# Mirrors customers.py's identical fix exactly — this file is a structural copy
# of it (VendorIn.client_id is required, same as CustomerIn's). create_vendor
# and bulk_create_vendors already checked the client on the way in (task #231);
# every other endpoint checked only the firm, including a write that can post a
# real opening-balance GL journal, a soft delete, and a PERMANENT delete that
# CASCADEs across bills and payments.
#
# vendor_statement and ap_aging take client_id directly and are guarded the
# same way as the query-param endpoints — vendor_statement_service._vendor
# already ties vendor_id to client_id server-side (both must match the same
# row), so the client check on client_id is sufficient without a second
# vendor-level check here.

def _assert_vendor_scope(current_user: dict, vendor: Optional[dict],
                         vendor_id: str) -> dict:
    """404 if missing/wrong firm, then 404 if outside assignment — the SAME
    detail either way. can_access_client (boolean), not assert_client_access,
    so this raises the router's own f"Vendor {id} not found" for both branches
    instead of assert_client_access's generic "Not found" — two different
    messages behind one status code would still be an oracle."""
    firm_id = current_user.get("firm_id")
    not_found = HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")
    if not vendor or vendor.get("firm_id") != firm_id:
        raise not_found
    if not can_access_client(current_user, vendor.get("client_id")):
        raise not_found
    return vendor


def _load_vendor_or_404(current_user: dict, vendor_id: str) -> dict:
    """Resolve one vendor, firm- and client-scoped, from mock or live store.
    Always selects the WHOLE row (never a narrowed column list) — several call
    sites here originally selected only opening_balance_paise, and a guard
    reading client_id off a row that never fetched it would silently pass (a
    missing client reads as "firm-level" and is allowed)."""
    if _USE_MOCK:
        vendor = next((v for v in MOCK_VENDORS if v["id"] == vendor_id), None)
    else:
        from core.supabase_client import get_supabase
        resp = (get_supabase().table("vendors").select("*")
                .eq("id", vendor_id).eq("firm_id", current_user.get("firm_id"))
                .limit(1).execute())
        vendor = resp.data[0] if resp.data else None
    return _assert_vendor_scope(current_user, vendor, vendor_id)

# ---------------------------------------------------------------------------
# Mock store
# ---------------------------------------------------------------------------
MOCK_VENDORS: list[dict] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm(v: Optional[str]) -> str:
    """Normalise an identifier for comparison (trim + upper). GSTIN/PAN are
    canonically uppercase, so case never distinguishes two real records."""
    return (v or "").strip().upper()


def _match_existing_vendor(candidates: list[dict], gstin: str, pan: str) -> Optional[dict]:
    """Master-data duplicate detection — mirrors customers.py's _match_existing
    exactly (same CGST Act §25 / IT Act §139A rationale), applied to vendors.
    Before this, vendors had ZERO duplicate protection at any layer (no app
    check, no DB unique constraint) — the only "duplicate" handling was a
    per-row insert-error classifier that could never fire, since nothing ever
    raises the unique-violation it was watching for. A retried/re-uploaded
    vendor CSV silently created full duplicate vendor rows, exactly like the
    purchase-bills bulk-import bug this mirrors the fix for.

    Match priority: GSTIN first (uniquely identifies a registration), then
    PAN (identifies the entity, used only when no GSTIN). Only ACTIVE vendors
    block creation — a previously deactivated namesake must never prevent
    re-creating the vendor."""
    if gstin:
        for c in candidates:
            if c.get("is_active", True) and _norm(c.get("gstin")) == gstin:
                return c
        return None
    if pan:
        for c in candidates:
            if c.get("is_active", True) and _norm(c.get("pan")) == pan:
                return c
    return None


# Tables that hold a vendor's accounting history — mirrors customers.py's
# _DEPENDENCY_TABLES exactly (same CGST Act §35/36 / IT Act §44AA rationale).
# purchase_bills/purchase_payments are FK ON DELETE CASCADE to vendors; a raw
# hard-delete would silently wipe them. debit_notes/purchase_credit_notes
# carry a vendor_id column with NO enforced FK (added later, never backfilled
# with one) — a hard-delete would leave those rows pointing at a vendor that
# no longer exists instead of cascading, which is worse than data loss, so
# they must be guarded here at the application layer regardless.
# (label, table, date column) — mirrors customers.py. The DATE is what lets the
# refusal name a statute AND the day the duty lapses instead of only "records
# exist"; each table names its own column because they differ, and reading the
# wrong one silently anchors retention to the wrong year.
_VENDOR_DEPENDENCY_TABLES: list[tuple[str, str, str | None]] = [
    ("bills", "purchase_bills", "bill_date"),
    ("payments", "purchase_payments", "payment_date"),
    ("debit_notes", "debit_notes", "debit_note_date"),
    ("credit_notes", "purchase_credit_notes", "credit_note_date"),
]
# Tables with a deleted_at (soft-delete) column — a deleted row is no longer
# a live accounting record and must not block a vendor's permanent delete.
_SOFT_DELETE_VENDOR_DEPENDENCY_TABLES = {"purchase_bills", "debit_notes", "purchase_credit_notes"}


def _vendor_dependencies(db, vendor_id: str, opening_balance_paise: int) -> dict:
    """Count the accounting records linked to a vendor, and find the newest.

    Mirrors customers.py's _customer_dependencies exactly. Returns
    {counts, total, has_any, latest_record_date} — the last being the newest
    DATED record, which is what lets the refusal name the day the statutory duty
    lapses. None means the only blocker carries no accounting date."""
    counts: dict[str, int] = {}
    latest: str | None = None
    for label, table, date_col in _VENDOR_DEPENDENCY_TABLES:
        try:
            columns = "id" if date_col is None else f"id, {date_col}"
            q = db.table(table).select(columns).eq("vendor_id", vendor_id)
            if table in _SOFT_DELETE_VENDOR_DEPENDENCY_TABLES:
                q = q.is_("deleted_at", None)
            resp = q.execute()
            rows = resp.data or []
            counts[label] = len(rows)
            if date_col:
                for row in rows:
                    value = row.get(date_col)
                    # ISO dates compare correctly as text; anything unparseable
                    # is skipped rather than guessed.
                    if isinstance(value, str) and len(value) >= 10:
                        if latest is None or value[:10] > latest:
                            latest = value[:10]
        except Exception as e:  # a missing/locked table must never mask a dependency
            _logger.warning("dependency count failed for %s: %s", table, e)
            counts[label] = 0
    counts["opening_balance"] = 1 if (opening_balance_paise or 0) != 0 else 0
    total = sum(counts.values())
    # latest_record_date is the newest DATED accounting record. None means the
    # only blocker is an opening balance, which carries no statutory clock.
    return {"counts": counts, "total": total, "has_any": total > 0,
            "latest_record_date": latest}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/")
def list_vendors(
    client_id: str = Query(..., description="CA client ID — required"),
    include_inactive: bool = Query(False),
    current_user: dict = Depends(rbac("client", "read")),
):
    """List vendors for a client."""
    assert_client_access(current_user, client_id)
    try:
        if _USE_MOCK:
            firm_id = current_user.get("firm_id")
            result = [v for v in MOCK_VENDORS if v["client_id"] == client_id and v.get("firm_id") == firm_id]
            if not include_inactive:
                result = [v for v in result if v.get("is_active", True)]
            return api_response(True, result)

        from core.supabase_client import get_supabase
        db = get_supabase()
        # Tenant isolation: service-role bypasses RLS — firm_id is the only guard
        # against a cross-tenant read via a guessed client_id (H15). The mock path
        # above already firm-scopes; the DB path must match it.
        q = (db.table("vendors").select("*")
             .eq("firm_id", current_user.get("firm_id")).eq("client_id", client_id))
        if not include_inactive:
            q = q.eq("is_active", True)
        resp = q.execute()
        return api_response(True, resp.data or [])
    except Exception as e:
        _logger.error("list_vendors: %s", e)
        return api_response(False, None, "Unable to complete vendor operation. Please try again.")


@router.post("/")
def create_vendor(
    vendor_in: VendorIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    """Create a vendor. IT Act §194C/194I/194J: TDS section tracked per vendor."""
    try:
        # task #231 audit finding: same client_id ownership gap as
        # create_customer — a vendor stamped with the caller's own firm_id
        # could still point at another firm's client_id, corrupting that
        # firm's vendor list and (via opening-balance sync) leaking its real
        # opening balances into a journal the caller's firm can post.
        assert_client_access(current_user, vendor_in.client_id)
        payload = vendor_in.model_dump()
        payload["firm_id"] = current_user.get("firm_id")
        payload["is_active"] = True
        payload["created_at"] = datetime.now(timezone.utc).isoformat()

        gstin = _norm(payload.get("gstin"))
        # Shape AND check digit (CGST Act s.25) — see routers/customers.py for
        # why the shape alone is not enough. On the purchase side a wrong vendor
        # GSTIN means the bill will never match anything in GSTR-2B, and the
        # client's own input tax credit is what is at risk.
        _gstin_problem = gstin_problem(gstin)
        if _gstin_problem:
            raise HTTPException(status_code=422, detail=_gstin_problem)
        pan = _norm(payload.get("pan"))
        client_id = payload.get("client_id")
        firm_id = payload["firm_id"]

        if _USE_MOCK:
            if gstin or pan:
                candidates = [v for v in MOCK_VENDORS if v.get("client_id") == client_id and v.get("firm_id") == firm_id]
                existing = _match_existing_vendor(candidates, gstin, pan)
                if existing:
                    return api_response(True, {**existing, "duplicate": True})
            payload["id"] = str(uuid.uuid4())
            MOCK_VENDORS.append(payload)
            return api_response(True, payload)

        from core.supabase_client import get_supabase
        db = get_supabase()

        # ── Duplicate guard (master-data integrity) — mirrors create_customer.
        # Never silently create a second vendor matching an existing active one
        # by GSTIN or PAN for the same client; re-importing/resubmitting must
        # not create duplicates. ──────────────────────────────────────────────
        if gstin or pan:
            existing_resp = (
                db.table("vendors").select("*")
                .eq("client_id", client_id).eq("firm_id", firm_id).eq("is_active", True)
                .execute()
            )
            existing = _match_existing_vendor(existing_resp.data or [], gstin, pan)
            if existing:
                return api_response(True, {**existing, "duplicate": True})

        resp = db.table("vendors").insert(payload).execute()
        if not resp.data:
            _logger.error("create_vendor: Supabase insert returned no data. payload=%s", payload)
            raise HTTPException(
                status_code=500,
                detail="Vendor could not be saved to the database. Please try again.",
            )
        vendor = resp.data[0]
        vendor_id = vendor.get("id", "")

        # Auto-sync opening balances to the GL — no manual "post" step. Only when an
        # opening balance was entered. Idempotent regenerate; roll back on failure.
        if int(payload.get("opening_balance_paise") or 0) != 0:
            try:
                from services.opening_balance_service import post_opening_balances, AP
                # created_by FKs to public.users.id (internal), not the Supabase auth id.
                post_opening_balances(payload["firm_id"], payload.get("client_id"),
                                      created_by=current_user.get("id"), scope=frozenset({AP}))
            except Exception as sync_err:
                _logger.error("create_vendor opening-balance sync failed; rolling back: %s", sync_err)
                try:
                    db.table("vendors").delete().eq("id", vendor_id).eq("firm_id", payload["firm_id"]).execute()
                except Exception:
                    pass
                return api_response(False, None, "Unable to save vendor. Please try again.")

        log_event(
            payload["firm_id"], "vendor", vendor_id,
            "create", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data=vendor,
        )
        timeline_service.log_timeline_event(
            client_id=payload.get("client_id", ""),
            firm_id=payload.get("firm_id", ""),
            financial_year=_current_fy_long(),
            category="accounting",
            event_type="vendor_created",
            title=f"Vendor {payload.get('name', '')} added",
            description="New vendor added to the system.",
            severity="info",
            entity_type="vendor",
            entity_id=vendor_id,
            actor_id=current_user.get("auth_user_id"),
            actor_name=current_user.get("email"),
        )
        return api_response(True, vendor)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("create_vendor: %s", e, exc_info=True)
        # Surface a meaningful error — never expose raw DB internals to the client
        # Classify into a user-safe message; never echo raw DB internals (M11).
        msg = str(e).lower()
        if "duplicate" in msg or "unique" in msg:
            return api_response(False, None, "A vendor with this GSTIN or PAN already exists for this client.")
        if "foreign key" in msg or "violates" in msg:
            return api_response(False, None, "Vendor creation failed due to a data constraint.")
        if "not-null" in msg or "null value" in msg:
            return api_response(False, None, "Vendor creation failed — a required field is missing.")
        return api_response(False, None, "Unable to complete vendor operation. Please try again.")


class VendorBulkIn(BaseModel):
    """Loose body for POST /bulk — a plain dict per item (not VendorIn) so one
    malformed row fails validation individually instead of 422-ing the whole
    CSV-import batch."""
    vendors: list[dict]


def _bulk_item_error_message(e: ValidationError) -> str:
    """Turn a VendorIn ValidationError into one human-readable line."""
    parts = []
    for err in e.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()))
        msg = err.get("msg", "Invalid value")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts) or "Invalid vendor data."


def _classify_db_error(msg_lower: str) -> str:
    """Same user-safe classification create_vendor uses (M11: never echo raw
    DB internals to the client)."""
    if "duplicate" in msg_lower or "unique" in msg_lower:
        return "A vendor with this GSTIN or PAN already exists for this client."
    if "foreign key" in msg_lower or "violates" in msg_lower:
        return "Vendor creation failed due to a data constraint."
    if "not-null" in msg_lower or "null value" in msg_lower:
        return "Vendor creation failed — a required field is missing."
    return "Unable to complete vendor operation. Please try again."


def _finish_vendor_creation(db, vendor: dict, payload: dict, current_user: dict) -> Optional[str]:
    """Post-insert side effects for ONE newly-created vendor row — same
    opening-balance GL sync (rollback-on-failure) and audit/timeline logging
    create_vendor runs for a single create. Returns a user-safe error message
    on failure, or None on success.
    """
    vendor_id = vendor.get("id", "")
    firm_id = payload["firm_id"]

    if int(payload.get("opening_balance_paise") or 0) != 0:
        try:
            from services.opening_balance_service import post_opening_balances, AP
            post_opening_balances(firm_id, payload.get("client_id"),
                                  created_by=current_user.get("id"), scope=frozenset({AP}))
        except Exception as sync_err:
            _logger.error("create_vendors_bulk opening-balance sync failed; rolling back vendor %s: %s",
                          vendor_id, sync_err)
            try:
                db.table("vendors").delete().eq("id", vendor_id).eq("firm_id", firm_id).execute()
            except Exception:
                pass
            return "Unable to save vendor. Please try again."

    log_event(
        firm_id, "vendor", vendor_id,
        "create", actor_id=current_user.get("auth_user_id"),
        actor_email=current_user.get("email"), new_data=vendor,
    )
    timeline_service.log_timeline_event(
        client_id=payload.get("client_id", ""),
        firm_id=firm_id,
        financial_year=_current_fy_long(),
        category="accounting",
        event_type="vendor_created",
        title=f"Vendor {payload.get('name', '')} added",
        description="New vendor added to the system.",
        severity="info",
        entity_type="vendor",
        entity_id=vendor_id,
        actor_id=current_user.get("auth_user_id"),
        actor_name=current_user.get("email"),
    )
    return None


@router.post("/bulk")
def create_vendors_bulk(
    body: VendorBulkIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    """Bulk-create vendors in ONE request — replaces the CSV-import UI's
    N-sequential-POST loop (a 100-row import was 100 round-trips, multiplied
    across every firm importing concurrently). Each item is validated
    individually so one bad row doesn't fail the whole batch.

    Insert strategy: try ONE batch insert first — the common, all-valid case,
    a single round-trip to Postgres. A multi-row INSERT is all-or-nothing, so
    a unique-constraint hit on any row fails the WHOLE batch and Postgres
    doesn't tell us which row(s) caused it. In that case we fall back to
    inserting the remaining items ONE AT A TIME, server-side (still just 1 HTTP
    round-trip from the client), so duplicates can be isolated and reported
    while the rest of the batch still succeeds.
    """
    created: list[dict] = []
    duplicates: list[dict] = []
    errors: list[dict] = []

    # ── Per-item validation (VendorIn, not the loose FastAPI body model) ────
    valid_items: list[tuple[int, dict]] = []  # (original index, payload)
    for i, item in enumerate(body.vendors):
        name = item.get("name") if isinstance(item, dict) else None
        try:
            vendor_in = VendorIn(**item)
        except ValidationError as e:
            errors.append({"index": i, "name": name, "error": _bulk_item_error_message(e)})
            continue
        except Exception:
            errors.append({"index": i, "name": name, "error": "Invalid vendor data."})
            continue

        # task #231 audit finding: same client_id ownership gap as create_vendor
        # — checked per-item so one bad row is rejected without failing the batch.
        if not can_access_client(current_user, vendor_in.client_id):
            errors.append({"index": i, "name": name, "error": "Client not found for this firm."})
            continue

        payload = vendor_in.model_dump()
        payload["firm_id"] = current_user.get("firm_id")
        payload["is_active"] = True
        payload["created_at"] = datetime.now(timezone.utc).isoformat()
        valid_items.append((i, payload))

    if not valid_items:
        return api_response(True, {"created": created, "duplicates": duplicates, "errors": errors})

    try:
        if _USE_MOCK:
            for i, payload in valid_items:
                payload["id"] = str(uuid.uuid4())
                MOCK_VENDORS.append(payload)
                created.append(payload)
            return api_response(True, {"created": created, "duplicates": duplicates, "errors": errors})

        from core.supabase_client import get_supabase
        db = get_supabase()

        # ── Duplicate guard — same rationale as create_vendor / customers.py's
        # bulk_create_customers: ONE dedup-snapshot fetch per distinct client_id
        # in the batch, checked against BOTH the pre-fetched existing rows AND
        # rows already accepted earlier in this same batch, so two duplicate
        # CSV rows never both get inserted. Without this, retrying/re-uploading
        # the same vendor CSV silently created full duplicate vendor rows —
        # there was no protection at any layer (no DB unique constraint either)
        # before this fix. ────────────────────────────────────────────────────
        firm_id = current_user.get("firm_id")
        client_ids = sorted({p.get("client_id") for _, p in valid_items})
        existing_by_client: dict[str, list[dict]] = {}
        for cid in client_ids:
            resp = (
                db.table("vendors").select("*")
                .eq("client_id", cid).eq("firm_id", firm_id).eq("is_active", True)
                .execute()
            )
            existing_by_client[cid] = resp.data or []

        accepted_in_batch: dict[str, list[dict]] = {cid: [] for cid in client_ids}
        deduped_items: list[tuple[int, dict]] = []
        for idx, payload in valid_items:
            cid = payload.get("client_id")
            gstin = _norm(payload.get("gstin"))
            pan = _norm(payload.get("pan"))
            candidates = existing_by_client.get(cid, []) + accepted_in_batch.get(cid, [])
            match = _match_existing_vendor(candidates, gstin, pan) if (gstin or pan) else None
            if match:
                duplicates.append({"index": idx, "name": payload.get("name"), "existing_id": match.get("id")})
                continue
            accepted_in_batch.setdefault(cid, []).append(payload)
            deduped_items.append((idx, payload))
        valid_items = deduped_items

        if not valid_items:
            return api_response(True, {"created": created, "duplicates": duplicates, "errors": errors})

        # ── Attempt 1: single batch insert (the fast path) ──────────────────
        batch_rows = None
        try:
            resp = db.table("vendors").insert([p for _, p in valid_items]).execute()
            if resp.data and len(resp.data) == len(valid_items):
                batch_rows = resp.data
        except Exception as batch_err:
            _logger.info(
                "create_vendors_bulk: batch insert failed (%s); falling back to per-row inserts.",
                batch_err,
            )
            batch_rows = None

        if batch_rows is not None:
            for (i, payload), vendor in zip(valid_items, batch_rows):
                err = _finish_vendor_creation(db, vendor, payload, current_user)
                if err:
                    errors.append({"index": i, "name": payload.get("name"), "error": err})
                else:
                    created.append(vendor)
            return api_response(True, {"created": created, "duplicates": duplicates, "errors": errors})

        # ── Attempt 2: per-row fallback — isolates exactly which row(s) hit
        #    the constraint, while everything else still succeeds. ───────────
        for i, payload in valid_items:
            try:
                resp = db.table("vendors").insert(payload).execute()
                if not resp.data:
                    errors.append({
                        "index": i, "name": payload.get("name"),
                        "error": "Vendor could not be saved to the database. Please try again.",
                    })
                    continue
                vendor = resp.data[0]
            except Exception as row_err:
                msg = _classify_db_error(str(row_err).lower())
                entry = {"index": i, "name": payload.get("name"), "error": msg}
                if "already exists" in msg:
                    duplicates.append(entry)
                else:
                    errors.append(entry)
                continue

            err = _finish_vendor_creation(db, vendor, payload, current_user)
            if err:
                errors.append({"index": i, "name": payload.get("name"), "error": err})
            else:
                created.append(vendor)

        return api_response(True, {"created": created, "duplicates": duplicates, "errors": errors})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("create_vendors_bulk: %s", e, exc_info=True)
        return api_response(False, None, "Unable to complete vendor operation. Please try again.")


@router.get("/{vendor_id}")
def get_vendor(
    vendor_id: str,
    current_user: dict = Depends(rbac("client", "read")),
):
    """Get a single vendor by ID."""
    try:
        vendor = _load_vendor_or_404(current_user, vendor_id)
        return api_response(True, vendor)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_vendor: %s", e)
        return api_response(False, None, "Unable to complete vendor operation. Please try again.")


@router.patch("/{vendor_id}")
def update_vendor(
    vendor_id: str,
    data: VendorUpdateIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    """Partial update of vendor."""
    try:
        payload = data.model_dump(exclude_none=True)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        data = payload

        # The prior-row fetch doubles as the M2 guard: WRITING opening_balance_paise
        # can post a real GL journal, so the refusal must land before that fetch
        # even decides whether anything changed, let alone before the update.
        prior = _load_vendor_or_404(current_user, vendor_id)

        if _USE_MOCK:
            for i, v in enumerate(MOCK_VENDORS):
                if v["id"] == vendor_id:
                    MOCK_VENDORS[i] = {**v, **data}
                    return api_response(True, MOCK_VENDORS[i])
            raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        firm_id = current_user.get("firm_id")

        # Tenant isolation (OOS-5): scope the write by firm_id. Under service-role
        # (RLS bypassed) an unscoped by-id update could mutate another firm's row.
        resp = db.table("vendors").update(data).eq("id", vendor_id).eq("firm_id", firm_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")
        updated = resp.data[0]

        # Auto-sync opening balances only when the opening balance actually changed.
        if int(updated.get("opening_balance_paise") or 0) != int(prior.get("opening_balance_paise") or 0):
            try:
                from services.opening_balance_service import post_opening_balances, AP
                post_opening_balances(firm_id, updated.get("client_id") or prior.get("client_id"),
                                      created_by=current_user.get("id"), scope=frozenset({AP}))
            except Exception as sync_err:
                _logger.error("update_vendor opening-balance sync failed; rolling back: %s", sync_err)
                try:
                    db.table("vendors").update({k: prior.get(k) for k in data.keys()}).eq("id", vendor_id).eq("firm_id", firm_id).execute()
                except Exception:
                    pass
                return api_response(False, None, "Unable to save vendor. Please try again.")

        log_event(
            current_user.get("firm_id", ""), "vendor", vendor_id,
            "update", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data=updated,
        )
        return api_response(True, updated)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("update_vendor: %s", e)
        return api_response(False, None, "Unable to complete vendor operation. Please try again.")


@router.get("/{vendor_id}/dependencies")
def get_vendor_dependencies(
    vendor_id: str,
    current_user: dict = Depends(rbac("client", "read")),
):
    """Report the accounting records linked to a vendor so the UI can decide
    whether a permanent delete is safe (it is only when there are none).
    Mirrors customers.py's get_customer_dependencies exactly."""
    try:
        vend = _load_vendor_or_404(current_user, vendor_id)
        opening = vend.get("opening_balance_paise") or 0
        if _USE_MOCK:
            deps = {"counts": {"bills": 0, "payments": 0, "debit_notes": 0, "credit_notes": 0,
                               "opening_balance": 1 if opening else 0},
                    "total": 1 if opening else 0, "has_any": bool(opening)}
        else:
            from core.supabase_client import get_supabase
            deps = _vendor_dependencies(get_supabase(), vendor_id, opening)
        return api_response(True, {
            "can_delete": not deps["has_any"],
            "dependencies": deps["counts"],
            "total": deps["total"],
        })
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_vendor_dependencies: %s", e)
        return api_response(False, None, "Unable to complete vendor operation. Please try again.")


@router.delete("/{vendor_id}")
def delete_vendor(
    vendor_id: str,
    current_user: dict = Depends(rbac("client", "delete")),
    # Plain default (not Query(...)) so direct callers get a real bool, not a
    # truthy FieldInfo. FastAPI still exposes it as the ?permanent= query param.
    permanent: bool = False,
):
    """Vendor lifecycle removal — Partner only (client.delete RBAC). Mirrors
    customers.py's delete_customer exactly.

    Default (permanent=False): soft delete = deactivate (is_active=False). The
    vendor leaves new-bill pickers but all history stays intact and it can be
    reactivated.

    permanent=True: hard delete. Allowed ONLY when the vendor has no linked
    accounting records (bills, payments, debit notes, credit notes, opening
    balance) — see _vendor_dependencies.
    """
    try:
        firm_id = current_user.get("firm_id")
        # Both branches below act on a real, named client's books — one
        # deactivates a vendor, the other permanently destroys its row. The
        # refusal has to land before either, so resolve-and-check happens once,
        # up front, for mock and live alike.
        vend = _load_vendor_or_404(current_user, vendor_id)

        if _USE_MOCK:
            for i, v in enumerate(MOCK_VENDORS):
                if v["id"] == vendor_id:
                    if permanent:
                        if (v.get("opening_balance_paise") or 0) != 0:
                            # Same sentence as the live path: a mock-only message is a
                            # second wording of one refusal, and they drift.
                            raise HTTPException(
                                status_code=409,
                                detail=party_erasure.refusal(
                                    party_erasure.VENDOR, latest_record_date=None),
                            )
                        MOCK_VENDORS.pop(i)
                        return api_response(True, {"id": vendor_id, "deleted": True})
                    MOCK_VENDORS[i]["is_active"] = False
                    return api_response(True, {"id": vendor_id, "is_active": False})
            raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()

        if permanent:
            opening = vend.get("opening_balance_paise") or 0
            deps = _vendor_dependencies(db, vendor_id, opening)
            if deps["has_any"]:
                # The refusal names the statute and the date it lapses, not just
                # that records exist — see services/party_erasure.py.
                raise HTTPException(
                    status_code=409,
                    detail=party_erasure.refusal(
                        party_erasure.VENDOR,
                        latest_record_date=deps.get("latest_record_date"),
                    ),
                )
            del_resp = db.table("vendors").delete().eq("id", vendor_id).eq("firm_id", firm_id).execute()
            if not del_resp.data:
                raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")
            log_event(
                firm_id or "", "vendor", vendor_id,
                "delete_permanent", actor_id=current_user.get("auth_user_id"),
                actor_email=current_user.get("email"),
            )
            return api_response(True, {"id": vendor_id, "deleted": True})

        # Soft delete (deactivate). Tenant isolation (OOS-5): firm-scope the write.
        resp = db.table("vendors").update({"is_active": False}).eq("id", vendor_id).eq("firm_id", firm_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")
        log_event(
            firm_id or "", "vendor", vendor_id,
            "delete", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
        )
        return api_response(True, {"id": vendor_id, "is_active": False})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("delete_vendor: %s", e)
        return api_response(False, None, "Unable to complete vendor operation. Please try again.")


@router.get("/{vendor_id}/outstanding")
def get_vendor_outstanding(
    vendor_id: str,
    current_user: dict = Depends(rbac("client", "read")),
):
    """
    Outstanding payable = sum of net_payable_paise on unpaid purchase bills
    MINUS total purchase_payments made against this vendor.
    All arithmetic in integer paise.
    """
    try:
        if _USE_MOCK:
            return api_response(True, {
                "vendor_id": vendor_id,
                "outstanding_paise": 0,
            })

        from core.supabase_client import get_supabase
        db = get_supabase()
        firm_id = current_user.get("firm_id")

        # _load_vendor_or_404 fetches the whole row rather than just "id" — the
        # M2 guard's own input, client_id, must never depend on which columns a
        # caller's SELECT happened to need.
        _load_vendor_or_404(current_user, vendor_id)

        # M5: outstanding = Σ (net_payable − paid) over live bills, excluding drafts
        # (never received — no payable exists yet) and cancelled bills, matching
        # vendor_statement_service.py's _DEAD_BILL exclusion set. Computing per-bill
        # from the bill's own paid_paise avoids the double-subtraction the old code
        # hit (a fully-paid bill was excluded from the sum yet its payment was still
        # subtracted). Payments now reconcile to the bill sub-ledger (H11).
        bills_resp = (
            db.table("purchase_bills")
            .select("id,net_payable_paise,paid_paise,debited_paise,credit_note_paise,status")
            .eq("firm_id", firm_id)
            .eq("vendor_id", vendor_id)
            .not_.in_("status", ["cancelled", "draft"])
            .execute()
        )
        # Net payable per bill = (net_payable + credit notes) − paid − debited
        # (CGST Act §34: debit notes relieve it, credit notes add to it).
        outstanding_paise = sum(
            int(b.get("net_payable_paise", 0) or 0) + int(b.get("credit_note_paise", 0) or 0)
            - int(b.get("paid_paise", 0) or 0) - int(b.get("debited_paise", 0) or 0)
            for b in (bills_resp.data or [])
        )

        return api_response(True, {
            "vendor_id": vendor_id,
            "outstanding_paise": outstanding_paise,
        })
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_vendor_outstanding: %s", e)
        return api_response(False, None, "Unable to complete vendor operation. Please try again.")


@router.get("/ap-aging")
def ap_aging(
    client_id: str = Query(..., description="CA client ID — required"),
    as_of: Optional[str] = Query(None, description="Aging as-of date (YYYY-MM-DD)"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Accounts-payable aging for a client — per-bill outstanding bucketed by age.
    Derived entirely from posted bills, payments and debit notes (firm-scoped)."""
    assert_client_access(current_user, client_id)
    try:
        if _USE_MOCK:
            # The AR mirror has always had this branch and this one had not, so
            # with no database the payables ageing returned a generic failure
            # while the receivables ageing returned an empty schedule. Two
            # endpoints that are each other's mirror answering differently is
            # how a screen ends up showing an error beside a working panel.
            return api_response(True, {"as_of": as_of, "buckets": {},
                                       "total_outstanding_paise": 0, "bills": []})
        from core.supabase_client import get_supabase
        from services.vendor_statement_service import vendor_statement_service
        db = get_supabase()
        data = vendor_statement_service.ap_aging(db, current_user.get("firm_id"), client_id, as_of)
        return api_response(True, data)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("ap_aging: %s", e)
        return api_response(False, None, "Unable to complete vendor operation. Please try again.")


@router.get("/{vendor_id}/statement")
def vendor_statement(
    vendor_id: str,
    client_id: str = Query(..., description="CA client ID — required"),
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: str = Query(..., description="YYYY-MM-DD"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Vendor account statement: opening payable, period bills/payments/debit notes
    with a running balance, and closing payable. Derived from posted data only."""
    # vendor_statement_service._vendor ties vendor_id to client_id server-side
    # (both must match one row), so checking client_id is sufficient — no
    # separate vendor-level check is needed here.
    assert_client_access(current_user, client_id)
    try:
        from core.supabase_client import get_supabase
        from services.vendor_statement_service import vendor_statement_service
        db = get_supabase()
        data = vendor_statement_service.generate(
            db, current_user.get("firm_id"), client_id, vendor_id, start_date, end_date)
        return api_response(True, data)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("vendor_statement: %s", e)
        return api_response(False, None, "Unable to complete vendor operation. Please try again.")
