"""Customer master — CRUD with GSTIN validation.
Client-scoped: every customer belongs to a CA client.
CGST Act Section 25: Registration of person. GSTIN format: 2-digit state + PAN (10) + entity + Z + check.
"""
import os
import re
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError as PydanticValidationError
from models.common import api_response
from models.parties import CustomerIn, CustomerUpdateIn
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

# CGST Act §25: GSTIN format — 2-digit state code + 10-char PAN + entity digit + Z + check digit
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")

router = APIRouter(prefix="/api/customers", tags=["customers"])

# ---------------------------------------------------------------------------
# Mock store (used when SUPABASE_URL is not configured)
# ---------------------------------------------------------------------------
MOCK_CUSTOMERS: list[dict] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_gstin(gstin: str, state_code: Optional[str] = None) -> None:
    """Raise 422 if GSTIN is syntactically invalid or state code mismatch."""
    if not GSTIN_RE.match(gstin):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid GSTIN format: '{gstin}'. Expected: 2-digit state + PAN(10) + entity + Z + check.",
        )
    if state_code and gstin[:2] != state_code:
        raise HTTPException(
            status_code=422,
            detail=f"GSTIN state code '{gstin[:2]}' does not match provided state_code '{state_code}'.",
        )


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


def _customer_dependencies(db, customer_id: str, opening_balance_paise: int) -> dict:
    """Count the accounting records linked to a customer.

    A non-zero opening balance is itself an accounting dependency. Returns
    {counts: {...}, total: int, has_any: bool}. customer_id is a globally unique
    UUID, so filtering dependents by customer_id alone is sufficient and correct.
    """
    counts: dict[str, int] = {}
    for label, table in _DEPENDENCY_TABLES:
        try:
            resp = db.table(table).select("id").eq("customer_id", customer_id).execute()
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
    try:
        if _USE_MOCK:
            firm_id = current_user.get("firm_id")
            result = [c for c in MOCK_CUSTOMERS if c["client_id"] == client_id and c.get("firm_id") == firm_id]
            if not include_inactive:
                result = [c for c in result if c.get("is_active", True)]
            return api_response(True, result)

        from core.supabase_client import get_supabase
        db = get_supabase()
        q = db.table("customers").select("*").eq("client_id", client_id)
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
                from services.opening_balance_service import post_opening_balances
                # journal_entries.created_by FKs to public.users.id (the INTERNAL id),
                # NOT the Supabase auth id. current_user carries both — use "id".
                post_opening_balances(firm_id, client_id, created_by=current_user.get("id"))
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


@router.get("/outstanding")
def get_outstanding_summary(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("client", "read")),
):
    """Aggregate outstanding balances across all customers for a client."""
    try:
        if _USE_MOCK:
            return api_response(True, {"client_id": client_id, "total_outstanding_paise": 0, "customers": []})

        from core.supabase_client import get_supabase
        db = get_supabase()
        customers = db.table("customers").select("id,name,opening_balance_paise").eq("client_id", client_id).eq("is_active", True).execute()

        result = []
        for cust in (customers.data or []):
            inv_resp = (
                db.table("sales_invoices")
                .select("id,total_paise,paid_paise,status")
                .eq("customer_id", cust["id"])
                .not_.in_("status", ["paid", "cancelled"])
                .execute()
            )
            inv_outstanding = sum(
                (i.get("total_paise", 0) - i.get("paid_paise", 0))
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


@router.get("/{customer_id}")
def get_customer(
    customer_id: str,
    current_user: dict = Depends(rbac("client", "read")),
):
    try:
        if _USE_MOCK:
            cust = next((c for c in MOCK_CUSTOMERS if c["id"] == customer_id), None)
            if not cust:
                raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
            return api_response(True, cust)

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("customers").select("*").eq("id", customer_id).eq("firm_id", current_user.get("firm_id")).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
        return api_response(True, resp.data[0])
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

        if _USE_MOCK:
            for i, c in enumerate(MOCK_CUSTOMERS):
                if c["id"] == customer_id:
                    MOCK_CUSTOMERS[i] = {**c, **data}
                    return api_response(True, MOCK_CUSTOMERS[i])
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        firm_id = current_user.get("firm_id")
        # Snapshot the prior row for opening-balance change detection + rollback.
        prior_resp = db.table("customers").select("*").eq("id", customer_id).eq("firm_id", firm_id).limit(1).execute()
        if not prior_resp.data:
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
        prior = prior_resp.data[0]

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
                from services.opening_balance_service import post_opening_balances
                post_opening_balances(firm_id, updated.get("client_id") or prior.get("client_id"),
                                      created_by=current_user.get("id"))
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
        firm_id = current_user.get("firm_id")
        if _USE_MOCK:
            cust = next((c for c in MOCK_CUSTOMERS if c["id"] == customer_id), None)
            if not cust:
                raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
            opening = cust.get("opening_balance_paise") or 0
            deps = {"counts": {"invoices": 0, "receipts": 0, "credit_notes": 0,
                               "recurring_templates": 0,
                               "opening_balance": 1 if opening else 0},
                    "total": 1 if opening else 0, "has_any": bool(opening)}
        else:
            from core.supabase_client import get_supabase
            db = get_supabase()
            cust_resp = (
                db.table("customers").select("opening_balance_paise")
                .eq("id", customer_id).eq("firm_id", firm_id).limit(1).execute()
            )
            if not cust_resp.data:
                raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
            opening = cust_resp.data[0].get("opening_balance_paise") or 0
            deps = _customer_dependencies(db, customer_id, opening)
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
            # Verify the customer exists in this firm and gather its opening balance.
            cust_resp = (
                db.table("customers").select("opening_balance_paise")
                .eq("id", customer_id).eq("firm_id", firm_id).limit(1).execute()
            )
            if not cust_resp.data:
                raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
            opening = cust_resp.data[0].get("opening_balance_paise") or 0
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

        # Fetch customer for opening balance
        cust_resp = db.table("customers").select("opening_balance_paise").eq("id", customer_id).limit(1).execute()
        if not cust_resp.data:
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
        opening_balance = cust_resp.data[0].get("opening_balance_paise") or 0

        inv_resp = (
            db.table("sales_invoices")
            .select("id,invoice_no,invoice_date,total_paise,paid_paise,status")
            .eq("customer_id", customer_id)
            .not_.in_("status", ["paid", "cancelled"])
            .execute()
        )
        invoices = inv_resp.data or []
        inv_outstanding = sum(
            (i.get("total_paise", 0) - i.get("paid_paise", 0))
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
