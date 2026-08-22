"""Customer master — CRUD with GSTIN validation.
Client-scoped: every customer belongs to a CA client.
CGST Act Section 25: Registration of person. GSTIN format: 2-digit state + PAN (10) + entity + Z + check.
"""
import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ValidationError as PydanticValidationError
from models.common import api_response
from models.parties import CustomerIn, CustomerUpdateIn
from core.authz import assert_client_access, can_access_client
from core.permissions import rbac
from core.exceptions import NotFoundError
from services.audit_service import log_event
from services.timeline_service import timeline_service


def _current_fy_long() -> str:
    """Return full financial year string like '2025-26'. Indian FY: April 1 – March 31."""
    now = datetime.now(timezone.utc)
    start = now.year if now.month >= 4 else now.year - 1
    return f"{start}-{str(start + 1)[2:]}"

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.customers")

router = APIRouter(prefix="/api/customers", tags=["customers"])


# ── Client-assignment scope (M2) ──────────────────────────────────────────────
# create_customer and bulk_create_customers already checked the client on the
# way IN (task #231). Every OTHER endpoint here — including reads, a WRITE that
# can trigger a real opening-balance journal post, a soft delete and a
# PERMANENT delete — checked only the firm. `customers.client_id` is required
# by CustomerIn, so it is never absent on a real row.
#
# Two shapes, matching every prior phase:
#   * query-param endpoints (list/outstanding-summary/ar-aging) get
#     assert_client_access BEFORE the `try` — several handlers in this file end
#     in a bare `except Exception:` with no `except HTTPException: raise`
#     ahead of it, so a guard placed inside would have its 404 caught and
#     turned into a 200. Placed uniformly for every query-param guard, even
#     the two that already have the re-raise, so the router does not depend on
#     everyone remembering which handlers have it.
#   * row-addressed endpoints resolve the row through _load_customer_or_404,
#     which always selects the WHOLE row rather than a narrowed column list —
#     several call sites here originally selected only `opening_balance_paise`,
#     and a guard reading `client_id` off a row that never fetched it would
#     silently pass (a missing client reads as "firm-level" and is allowed).

def _assert_customer_scope(current_user: dict, customer: Optional[dict],
                           customer_id: str) -> dict:
    """404 if missing/wrong firm, then 404 if outside assignment — the SAME
    detail either way, so the response body can never become an oracle for
    which ids are real. `can_access_client` (boolean), not
    `assert_client_access`, precisely so this can raise the router's own
    f"Customer {id} not found" instead of assert_client_access's generic
    "Not found" — two different messages behind one status code would still
    tell a caller which case they hit.
    """
    firm_id = current_user.get("firm_id")
    not_found = HTTPException(status_code=404,
                              detail=f"Customer {customer_id} not found")
    if not customer or customer.get("firm_id") != firm_id:
        raise not_found
    if not can_access_client(current_user, customer.get("client_id")):
        raise not_found
    return customer


def _load_customer_or_404(current_user: dict, customer_id: str) -> dict:
    """Resolve one customer, firm- and client-scoped, from mock or live store.

    The mock branches this replaces did not all firm-scope consistently either
    (get_customer/update_customer/get_customer_dependencies/delete_customer
    filtered by id alone) — centralizing the lookup fixes that as the same
    change, not a separate one, since it is the identical "addressed by id,
    nothing checked who it belongs to" pattern.
    """
    if _USE_MOCK:
        customer = next((c for c in MOCK_CUSTOMERS if c["id"] == customer_id), None)
    else:
        from core.supabase_client import get_supabase
        resp = (get_supabase().table("customers").select("*")
                .eq("id", customer_id).eq("firm_id", current_user.get("firm_id"))
                .limit(1).execute())
        customer = resp.data[0] if resp.data else None
    return _assert_customer_scope(current_user, customer, customer_id)

# ---------------------------------------------------------------------------
# Mock store (used when SUPABASE_URL is not configured)
# ---------------------------------------------------------------------------
MOCK_CUSTOMERS: list[dict] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_next_seq_mock() -> int:
    return len(MOCK_CUSTOMERS) + 1


def _norm(v: Optional[str]) -> str:
    """Normalise an identifier for comparison (trim + upper). GSTIN/PAN are
    canonically uppercase, so case never distinguishes two real records."""
    return (v or "").strip().upper()


def _match_existing(candidates: list[dict], gstin: str, pan: str) -> Optional[dict]:
    """Master-data duplicate detection.

    Match priority (CAFLOW customer-module spec):
      1) GSTIN — CGST Act §25: a GSTIN uniquely identifies a registration.
      2) PAN   — IT Act §139A: identifies the entity, used only when no GSTIN.
    Only ACTIVE customers block creation: a previously deactivated namesake must
    never prevent re-creating the customer. Returns the matched row or None.
    """
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


# Tables that hold a customer's accounting history. EVERY FK that references
# customers is ON DELETE CASCADE, so a raw hard-delete would silently wipe these
# rows. CGST Act §35/36 (and IT Act §44AA) require books & records to be
# preserved, so we BLOCK a permanent delete at the application layer whenever any
# of these exist and steer the user to deactivation instead.
_DEPENDENCY_TABLES: list[tuple[str, str]] = [
    ("invoices", "client_sales_invoices"),
    ("receipts", "receipts"),
    ("credit_notes", "credit_notes"),
    ("recurring_templates", "recurring_invoice_templates"),
]
# Tables with a deleted_at (soft-delete) column — a deleted row is no longer
# a live accounting record and must not block a customer's permanent delete.
_SOFT_DELETE_DEPENDENCY_TABLES = {"client_sales_invoices", "credit_notes"}


def _customer_dependencies(db, customer_id: str, opening_balance_paise: int) -> dict:
    """Count the accounting records linked to a customer.

    A non-zero opening balance is itself an accounting dependency. Returns
    {counts: {...}, total: int, has_any: bool}. customer_id is a globally unique
    UUID, so filtering dependents by customer_id alone is sufficient and correct.
    """
    counts: dict[str, int] = {}
    for label, table in _DEPENDENCY_TABLES:
        try:
            q = db.table(table).select("id").eq("customer_id", customer_id)
            if table in _SOFT_DELETE_DEPENDENCY_TABLES:
                q = q.is_("deleted_at", None)
            resp = q.execute()
            counts[label] = len(resp.data or [])
        except Exception as e:  # a missing/locked table must never mask a dependency
            _logger.warning("dependency count failed for %s: %s", table, e)
            counts[label] = 0
    counts["opening_balance"] = 1 if (opening_balance_paise or 0) != 0 else 0
    total = sum(counts.values())
    return {"counts": counts, "total": total, "has_any": total > 0}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/")
def list_customers(
    client_id: str = Query(..., description="CA client ID — required"),
    include_inactive: bool = Query(False),
    current_user: dict = Depends(rbac("client", "read")),
):
    assert_client_access(current_user, client_id)
    try:
        if _USE_MOCK:
            firm_id = current_user.get("firm_id")
            result = [c for c in MOCK_CUSTOMERS if c["client_id"] == client_id and c.get("firm_id") == firm_id]
            if not include_inactive:
                result = [c for c in result if c.get("is_active", True)]
            return api_response(True, result)

        from core.supabase_client import get_supabase
        db = get_supabase()
        # Tenant isolation: service-role bypasses RLS — firm_id is the only guard
        # against a cross-tenant read via a guessed client_id (H15). The mock path
        # above already firm-scopes; the DB path must match it.
        q = (db.table("customers").select("*")
             .eq("firm_id", current_user.get("firm_id")).eq("client_id", client_id))
        if not include_inactive:
            q = q.eq("is_active", True)
        resp = q.execute()
        return api_response(True, resp.data or [])
    except Exception as e:
        _logger.error("list_customers: %s", e)
        return api_response(False, None, "Unable to complete customer operation. Please try again.")


@router.post("/")
def create_customer(
    data: CustomerIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    try:
        # task #231 audit finding: client_id was never checked against the
        # caller's firm — a customer could be created stamped with the
        # caller's OWN firm_id but pointing at ANOTHER firm's client_id,
        # corrupting that firm's customer list and, if opening_balance_paise
        # was set, leaking that firm's real opening balances into a journal
        # the caller's own firm can post (see opening_balance_service's
        # _fetch_masters, now also firm-scoped as defense-in-depth).
        assert_client_access(current_user, data.client_id)
        payload = data.model_dump()
        payload["firm_id"] = current_user.get("firm_id")
        payload["is_active"] = True
        payload["created_at"] = datetime.now(timezone.utc).isoformat()
        data = payload

        # ── Duplicate guard (master-data integrity) ─────────────────────────
        # Never silently create a second customer that matches an existing active
        # one by GSTIN (preferred) or PAN for the same client. Re-importing the
        # same file must NOT create duplicates. When a match is found we return
        # the EXISTING record flagged duplicate=True (no insert), so the caller
        # can report it as "already exists / skipped".
        gstin = _norm(data.get("gstin"))
        pan = _norm(data.get("pan"))
        client_id = data.get("client_id")
        firm_id = data.get("firm_id")

        if _USE_MOCK:
            candidates = [
                c for c in MOCK_CUSTOMERS
                if c.get("client_id") == client_id and c.get("firm_id") == firm_id
            ]
            existing = _match_existing(candidates, gstin, pan)
            if existing:
                return api_response(True, {**existing, "duplicate": True})
            data["id"] = str(uuid.uuid4())
            MOCK_CUSTOMERS.append(data)
            return api_response(True, data)

        from core.supabase_client import get_supabase
        db = get_supabase()
        if gstin or pan:
            existing_resp = (
                db.table("customers")
                .select("*")
                .eq("client_id", client_id)
                .eq("firm_id", firm_id)
                .eq("is_active", True)
                .execute()
            )
            existing = _match_existing(existing_resp.data or [], gstin, pan)
            if existing:
                return api_response(True, {**existing, "duplicate": True})

        resp = db.table("customers").insert(data).execute()
        customer = resp.data[0] if resp.data else data
        customer_id = customer.get("id", "")

        # Auto-sync opening balances to the GL — no manual "post" step. Only when an
        # opening balance was actually entered. Idempotent regenerate; if it fails we
        # roll back the just-created customer so the books never go partial.
        if int(data.get("opening_balance_paise") or 0) != 0:
            try:
                from services.opening_balance_service import post_opening_balances, AR
                # journal_entries.created_by FKs to public.users.id (the INTERNAL id),
                # NOT the Supabase auth id. current_user carries both — use "id".
                post_opening_balances(firm_id, client_id, created_by=current_user.get("id"),
                                      scope=frozenset({AR}))
            except Exception as sync_err:
                _logger.error("create_customer opening-balance sync failed; rolling back: %s", sync_err)
                try:
                    db.table("customers").delete().eq("id", customer_id).eq("firm_id", firm_id).execute()
                except Exception:
                    pass
                return api_response(False, None, "Unable to save customer. Please try again.")

        log_event(
            data["firm_id"], "customer", customer_id,
            "create", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data=customer,
        )
        timeline_service.log_timeline_event(
            client_id=data.get("client_id", ""),
            firm_id=data.get("firm_id", ""),
            financial_year=_current_fy_long(),
            category="accounting",
            event_type="customer_created",
            title=f"Customer {data.get('name', '')} added",
            description="New customer added to the system.",
            severity="info",
            entity_type="customer",
            entity_id=customer_id,
            actor_id=current_user.get("auth_user_id"),
            actor_name=current_user.get("email"),
        )
        return api_response(True, customer)
    except HTTPException:
        raise
    except PydanticValidationError as e:
        # Surface specific field-level validation errors to the caller
        msgs = "; ".join(
            err.get("msg", str(err)) for err in e.errors()
        )
        _logger.warning("create_customer validation: %s", msgs)
        return api_response(False, None, msgs)
    except Exception as e:
        err_str = str(e)
        _logger.error("create_customer: %s", err_str)
        # Surface DB constraint violations (duplicate GSTIN, missing FK, etc.)
        if "duplicate" in err_str.lower() or "unique" in err_str.lower():
            return api_response(False, None, "A customer with this GSTIN already exists.")
        if "foreign key" in err_str.lower() or "violates" in err_str.lower():
            return api_response(False, None, "Invalid client reference. Please refresh and try again.")
        return api_response(False, None, "Unable to complete customer operation. Please try again.")


class CustomerBulkIn(BaseModel):
    """Loose body — items are validated individually inside the handler (via
    CustomerIn(**item)) so one malformed CSV row cannot 422 the whole batch."""
    customers: list[dict]


@router.post("/bulk")
def bulk_create_customers(
    data: CustomerBulkIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    """Bulk customer import (CSV upload).

    Replaces the frontend's `for (const c of records) POST /api/customers/` loop
    — which re-ran create_customer's whole active-customer dedup SELECT on every
    single row — with ONE dedup-snapshot fetch (per distinct client_id in the
    batch, not per item) and ONE batch insert.

    Duplicate matching mirrors _match_existing exactly (GSTIN first, then PAN —
    CGST Act §25 / IT Act §139A, see _match_existing docstring), checked against
    both the pre-fetched existing rows AND rows already accepted earlier in this
    same batch, so two duplicate CSV rows never both get inserted.
    """
    try:
        firm_id = current_user.get("firm_id")
        items = data.customers or []

        created: list[dict] = []
        duplicates: list[dict] = []
        errors: list[dict] = []

        # ── Step 1: per-item validation ──────────────────────────────────────
        validated: list[tuple[int, dict]] = []
        for idx, item in enumerate(items):
            item = item if isinstance(item, dict) else {}
            try:
                parsed = CustomerIn(**item)
            except PydanticValidationError as e:
                msgs = "; ".join(err.get("msg", str(err)) for err in e.errors())
                errors.append({"index": idx, "name": item.get("name"), "error": msgs})
                continue
            except Exception as e:
                errors.append({"index": idx, "name": item.get("name"), "error": str(e)})
                continue
            # task #231 audit finding: same client_id ownership gap as the
            # single-create endpoint — checked per-item so one bad row is
            # rejected without 404ing the whole batch (mirrors the existing
            # per-item error-collection design here).
            if not can_access_client(current_user, parsed.client_id):
                errors.append({"index": idx, "name": item.get("name"), "error": "Client not found for this firm."})
                continue
            payload = parsed.model_dump()
            payload["firm_id"] = firm_id
            payload["is_active"] = True
            payload["created_at"] = datetime.now(timezone.utc).isoformat()
            # Client-generated id: lets within-batch duplicate detection (Step 3)
            # and the post-insert opening-balance/audit loop (Step 5) address a
            # row deterministically without depending on insert-response ordering.
            payload["id"] = str(uuid.uuid4())
            validated.append((idx, payload))

        if not validated:
            return api_response(True, {"created": created, "duplicates": duplicates, "errors": errors})

        # ── Step 2: dedup snapshot — ONE query per distinct client_id in the
        # batch (this importer is always scoped to a single client_id per CSV
        # upload in practice, so this is a single query in the common case; a
        # batch that happens to span multiple client_ids still gets correct,
        # per-client dedup instead of one query per item). ─────────────────────
        client_ids = sorted({p.get("client_id") for _, p in validated})
        existing_by_client: dict[str, list[dict]] = {}
        db = None
        if _USE_MOCK:
            for cid in client_ids:
                existing_by_client[cid] = [
                    c for c in MOCK_CUSTOMERS
                    if c.get("client_id") == cid and c.get("firm_id") == firm_id
                ]
        else:
            from core.supabase_client import get_supabase
            db = get_supabase()
            for cid in client_ids:
                resp = (
                    db.table("customers")
                    .select("*")
                    .eq("client_id", cid)
                    .eq("firm_id", firm_id)
                    .eq("is_active", True)
                    .execute()
                )
                existing_by_client[cid] = resp.data or []

        # ── Step 3: duplicate guard — GSTIN-then-PAN (_match_existing), against
        # the DB snapshot AND rows already accepted earlier in this batch. ──────
        accepted_in_batch: dict[str, list[dict]] = {cid: [] for cid in client_ids}
        to_insert: list[tuple[int, dict]] = []
        for idx, payload in validated:
            cid = payload.get("client_id")
            gstin = _norm(payload.get("gstin"))
            pan = _norm(payload.get("pan"))
            candidates = existing_by_client.get(cid, []) + accepted_in_batch.get(cid, [])
            match = _match_existing(candidates, gstin, pan)
            if match:
                duplicates.append({"index": idx, "name": payload.get("name"), "existing_id": match.get("id")})
                continue
            accepted_in_batch.setdefault(cid, []).append(payload)
            to_insert.append((idx, payload))

        if not to_insert:
            return api_response(True, {"created": created, "duplicates": duplicates, "errors": errors})

        # ── Step 4: ONE batch insert for every new row. ─────────────────────────
        if _USE_MOCK:
            inserted_rows: list[tuple[int, dict]] = []
            for idx, payload in to_insert:
                row = dict(payload)
                MOCK_CUSTOMERS.append(row)
                inserted_rows.append((idx, row))
        else:
            resp = db.table("customers").insert([p for _, p in to_insert]).execute()
            data_rows = resp.data or [p for _, p in to_insert]
            inserted_rows = list(zip((idx for idx, _ in to_insert), data_rows))

        # ── Step 5: opening-balance GL sync per newly-created row — same
        # rollback-on-failure isolation as the single endpoint (post_opening_
        # balances + delete-on-failure), but scoped to ONLY the failing row so
        # one bad row's GL-posting failure can't sink the rest of the batch. ────
        for idx, row in inserted_rows:
            customer_id = row.get("id", "")
            cid = row.get("client_id")
            if int(row.get("opening_balance_paise") or 0) != 0:
                try:
                    from services.opening_balance_service import post_opening_balances, AR
                    # journal_entries.created_by FKs to public.users.id (INTERNAL id).
                    post_opening_balances(firm_id, cid, created_by=current_user.get("id"),
                                          scope=frozenset({AR}))
                except Exception as sync_err:
                    _logger.error(
                        "bulk_create_customers opening-balance sync failed for index %s; rolling back: %s",
                        idx, sync_err,
                    )
                    try:
                        if _USE_MOCK:
                            MOCK_CUSTOMERS[:] = [c for c in MOCK_CUSTOMERS if c.get("id") != customer_id]
                        else:
                            db.table("customers").delete().eq("id", customer_id).eq("firm_id", firm_id).execute()
                    except Exception:
                        pass
                    errors.append({"index": idx, "name": row.get("name"), "error": "Unable to save customer. Please try again."})
                    continue

            created.append(row)
            log_event(
                firm_id, "customer", customer_id,
                "create", actor_id=current_user.get("auth_user_id"),
                actor_email=current_user.get("email"), new_data=row,
            )
            timeline_service.log_timeline_event(
                client_id=row.get("client_id", ""),
                firm_id=firm_id,
                financial_year=_current_fy_long(),
                category="accounting",
                event_type="customer_created",
                title=f"Customer {row.get('name', '')} added",
                description="New customer added to the system.",
                severity="info",
                entity_type="customer",
                entity_id=customer_id,
                actor_id=current_user.get("auth_user_id"),
                actor_name=current_user.get("email"),
            )

        return api_response(True, {"created": created, "duplicates": duplicates, "errors": errors})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("bulk_create_customers: %s", e)
        return api_response(False, None, "Unable to complete customer operation. Please try again.")


@router.get("/outstanding")
def get_outstanding_summary(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("client", "read")),
):
    """Aggregate outstanding balances across all customers for a client."""
    assert_client_access(current_user, client_id)
    try:
        if _USE_MOCK:
            return api_response(True, {"client_id": client_id, "total_outstanding_paise": 0, "customers": []})

        from core.supabase_client import get_supabase
        db = get_supabase()
        firm_id = current_user.get("firm_id")
        customers = db.table("customers").select("id,name,opening_balance_paise").eq("client_id", client_id).eq("firm_id", firm_id).eq("is_active", True).execute()

        result = []
        for cust in (customers.data or []):
            inv_resp = (
                db.table("client_sales_invoices")
                .select("id,total_paise,paid_paise,credited_paise,debit_note_paise,status")
                .eq("customer_id", cust["id"])
                .eq("firm_id", firm_id)
                .not_.in_("status", ["paid", "cancelled", "draft"])
                .execute()
            )
            # Net receivable = (total + debit notes) − cash paid − credit notes
            # applied (CGST Act §34, integer paise). A draft invoice was never issued
            # (no journal posted) so it isn't a receivable yet — excluded here to match
            # customer_statement_service.py's _DEAD_INVOICE set.
            inv_outstanding = sum(
                (i.get("total_paise", 0) + (i.get("debit_note_paise", 0) or 0)
                 - i.get("paid_paise", 0) - (i.get("credited_paise", 0) or 0))
                for i in (inv_resp.data or [])
            )
            # Integer arithmetic only; opening balance always >= 0
            opening = cust.get("opening_balance_paise") or 0
            result.append({
                "customer_id": cust["id"],
                "customer_name": cust["name"],
                "outstanding_paise": inv_outstanding + opening,
            })

        total = sum(r["outstanding_paise"] for r in result)
        return api_response(True, {"client_id": client_id, "total_outstanding_paise": total, "customers": result})
    except Exception as e:
        _logger.error("get_outstanding_summary: %s", e)
        return api_response(False, None, "Unable to complete customer operation. Please try again.")


@router.get("/ar-aging")
def ar_aging(
    client_id: str = Query(..., description="CA client ID — required"),
    as_of: Optional[str] = Query(None, description="Aging as-of date (YYYY-MM-DD)"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Accounts-receivable aging for a client — per-invoice outstanding bucketed by
    age (the AR mirror of /vendors/ap-aging). Derived entirely from posted invoices,
    receipts and credit notes (firm-scoped); foreign invoices carry dual-currency
    detail, INR-only clients see the base aging unchanged."""
    assert_client_access(current_user, client_id)
    try:
        if _USE_MOCK:
            return api_response(True, {"as_of": None, "buckets": {}, "total_outstanding_paise": 0, "invoices": []})
        from core.supabase_client import get_supabase
        from services.customer_statement_service import customer_statement_service
        db = get_supabase()
        data = customer_statement_service.ar_aging(db, current_user.get("firm_id"), client_id, as_of)
        return api_response(True, data)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("ar_aging: %s", e)
        return api_response(False, None, "Unable to complete customer operation. Please try again.")


@router.get("/{customer_id}")
def get_customer(
    customer_id: str,
    current_user: dict = Depends(rbac("client", "read")),
):
    try:
        cust = _load_customer_or_404(current_user, customer_id)
        return api_response(True, cust)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_customer: %s", e)
        return api_response(False, None, "Unable to complete customer operation. Please try again.")


@router.patch("/{customer_id}")
def update_customer(
    customer_id: str,
    data: CustomerUpdateIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    try:
        payload = data.model_dump(exclude_none=True)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        data = payload

        # The prior-row fetch doubles as the M2 guard: WRITING opening_balance_paise
        # can post a real GL journal, so the refusal must land before that fetch even
        # decides whether anything changed, let alone before the update itself.
        prior = _load_customer_or_404(current_user, customer_id)

        if _USE_MOCK:
            for i, c in enumerate(MOCK_CUSTOMERS):
                if c["id"] == customer_id:
                    MOCK_CUSTOMERS[i] = {**c, **data}
                    return api_response(True, MOCK_CUSTOMERS[i])
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        firm_id = current_user.get("firm_id")

        # Tenant isolation (OOS-5): scope the write by firm_id. Under service-role
        # (RLS bypassed) an unscoped by-id update could mutate another firm's row.
        resp = db.table("customers").update(data).eq("id", customer_id).eq("firm_id", firm_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
        updated = resp.data[0]

        # Auto-sync opening balances to the GL ONLY when the opening balance actually
        # changed (not on name/email/phone/credit-days/GSTIN edits). Idempotent
        # regenerate; on failure restore the prior values so no partial save lands.
        if int(updated.get("opening_balance_paise") or 0) != int(prior.get("opening_balance_paise") or 0):
            try:
                from services.opening_balance_service import post_opening_balances, AR
                post_opening_balances(firm_id, updated.get("client_id") or prior.get("client_id"),
                                      created_by=current_user.get("id"), scope=frozenset({AR}))
            except Exception as sync_err:
                _logger.error("update_customer opening-balance sync failed; rolling back: %s", sync_err)
                try:
                    db.table("customers").update({k: prior.get(k) for k in data.keys()}).eq("id", customer_id).eq("firm_id", firm_id).execute()
                except Exception:
                    pass
                return api_response(False, None, "Unable to save customer. Please try again.")

        log_event(
            current_user.get("firm_id", ""), "customer", customer_id,
            "update", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data=updated,
        )
        return api_response(True, updated)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("update_customer: %s", e)
        return api_response(False, None, "Unable to complete customer operation. Please try again.")


@router.get("/{customer_id}/dependencies")
def get_customer_dependencies(
    customer_id: str,
    current_user: dict = Depends(rbac("client", "read")),
):
    """Report the accounting records linked to a customer so the UI can decide
    whether a permanent delete is safe (it is only when there are none)."""
    try:
        cust = _load_customer_or_404(current_user, customer_id)
        opening = cust.get("opening_balance_paise") or 0
        if _USE_MOCK:
            deps = {"counts": {"invoices": 0, "receipts": 0, "credit_notes": 0,
                               "recurring_templates": 0,
                               "opening_balance": 1 if opening else 0},
                    "total": 1 if opening else 0, "has_any": bool(opening)}
        else:
            from core.supabase_client import get_supabase
            deps = _customer_dependencies(get_supabase(), customer_id, opening)
        return api_response(True, {
            "can_delete": not deps["has_any"],
            "dependencies": deps["counts"],
            "total": deps["total"],
        })
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_customer_dependencies: %s", e)
        return api_response(False, None, "Unable to complete customer operation. Please try again.")


@router.delete("/{customer_id}")
def delete_customer(
    customer_id: str,
    current_user: dict = Depends(rbac("client", "delete")),
    # Plain default (not Query(...)) so direct callers get a real bool, not a
    # truthy FieldInfo. FastAPI still exposes it as the ?permanent= query param.
    permanent: bool = False,
):
    """Customer lifecycle removal — Partner only (via client.delete RBAC).

    Default (permanent=False): soft delete = deactivate (is_active=False). The
    customer leaves new-invoice pickers but all history stays intact and it can
    be reactivated.

    permanent=True: hard delete. Allowed ONLY when the customer has no linked
    accounting records (invoices, receipts, credit notes, recurring templates,
    opening balance). Every FK is ON DELETE CASCADE, so this guard — not the
    database — is what protects the books; we refuse with 409 when records exist.
    """
    try:
        firm_id = current_user.get("firm_id")
        # Both branches below act on a real, named client's books — one
        # deactivates a customer, the other permanently destroys its row (and,
        # via CASCADE, everything the has_any check doesn't catch). The refusal
        # has to land before either, so resolve-and-check happens once, up front,
        # for mock and live alike — the mock loop below no longer needs its own
        # not-found raise, but the DB branch's opening-balance figure now comes
        # from this same fetch instead of a second query.
        cust = _load_customer_or_404(current_user, customer_id)

        if _USE_MOCK:
            for i, c in enumerate(MOCK_CUSTOMERS):
                if c["id"] == customer_id:
                    if permanent:
                        if (c.get("opening_balance_paise") or 0) != 0:
                            raise HTTPException(status_code=409, detail="Customer has accounting records and cannot be deleted. Deactivate instead.")
                        MOCK_CUSTOMERS.pop(i)
                        return api_response(True, {"id": customer_id, "deleted": True})
                    MOCK_CUSTOMERS[i]["is_active"] = False
                    return api_response(True, {"id": customer_id, "is_active": False})
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()

        if permanent:
            opening = cust.get("opening_balance_paise") or 0
            deps = _customer_dependencies(db, customer_id, opening)
            if deps["has_any"]:
                # CASCADE FKs would otherwise destroy these records silently.
                raise HTTPException(
                    status_code=409,
                    detail="This customer has linked accounting records and cannot be permanently deleted. Deactivate the customer instead to preserve history.",
                )
            del_resp = db.table("customers").delete().eq("id", customer_id).eq("firm_id", firm_id).execute()
            if not del_resp.data:
                raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
            log_event(
                firm_id or "", "customer", customer_id,
                "delete_permanent", actor_id=current_user.get("auth_user_id"),
                actor_email=current_user.get("email"),
            )
            return api_response(True, {"id": customer_id, "deleted": True})

        # Soft delete (deactivate). Tenant isolation (OOS-5): firm-scope the write.
        resp = db.table("customers").update({"is_active": False}).eq("id", customer_id).eq("firm_id", firm_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
        log_event(
            firm_id or "", "customer", customer_id,
            "delete", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
        )
        return api_response(True, {"id": customer_id, "is_active": False})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("delete_customer: %s", e)
        return api_response(False, None, "Unable to complete customer operation. Please try again.")


@router.get("/{customer_id}/outstanding")
def get_customer_outstanding(
    customer_id: str,
    current_user: dict = Depends(rbac("client", "read")),
):
    """
    Outstanding balance = sum of (total_paise - paid_paise) on open invoices
    PLUS opening_balance_paise.
    All arithmetic in integer paise.
    """
    try:
        if _USE_MOCK:
            return api_response(True, {
                "customer_id": customer_id,
                "outstanding_paise": 0,
                "invoices": [],
            })

        from core.supabase_client import get_supabase
        db = get_supabase()

        # _load_customer_or_404 fetches the whole row (not just
        # opening_balance_paise, the field this endpoint actually wants) —
        # the M2 guard's own input, client_id, must never depend on which
        # columns a caller's SELECT happened to need.
        firm_id = current_user.get("firm_id")
        cust = _load_customer_or_404(current_user, customer_id)
        opening_balance = cust.get("opening_balance_paise") or 0

        inv_resp = (
            db.table("client_sales_invoices")
            .select("id,invoice_no,invoice_date,total_paise,paid_paise,credited_paise,debit_note_paise,status")
            .eq("customer_id", customer_id)
            .eq("firm_id", firm_id)
            .not_.in_("status", ["paid", "cancelled", "draft"])
            .execute()
        )
        invoices = inv_resp.data or []
        # Net receivable = (total + debit notes) − cash paid − credit notes
        # applied (CGST Act §34, integer paise). A draft invoice was never issued
        # (no journal posted) so it isn't a receivable yet — excluded here to match
        # customer_statement_service.py's _DEAD_INVOICE set.
        inv_outstanding = sum(
            (i.get("total_paise", 0) + (i.get("debit_note_paise", 0) or 0)
             - i.get("paid_paise", 0) - (i.get("credited_paise", 0) or 0))
            for i in invoices
        )
        total_outstanding = inv_outstanding + opening_balance  # integer paise

        return api_response(True, {
            "customer_id": customer_id,
            "outstanding_paise": total_outstanding,
            "invoices": invoices,
        })
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_customer_outstanding: %s", e)
        return api_response(False, None, "Unable to complete customer operation. Please try again.")
