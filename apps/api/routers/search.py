"""
Module 9.0 / M2 — Server-side, authorization-scoped global search.

Replaces the previous client-side Supabase search (which was firm-scoped only and
disclosed any client's name/PAN/GSTIN to any staff member). Every result is
filtered through core.authz so a user can only discover entities for clients they
are authorized to access — an unassigned client never appears in results or
autocomplete.
"""
import os
from fastapi import APIRouter, Depends, Query

from models.common import api_response
from core.permissions import rbac
from core.authz import effective_client_ids
from repositories.client_repository import client_repo

router = APIRouter(prefix="/api/search", tags=["search"])

_USE_MOCK = not os.environ.get("SUPABASE_URL")


def _db():
    from core.supabase_client import get_supabase
    return get_supabase()


@router.get("")
def global_search(
    q: str = Query("", description="Search query (min 2 chars)"),
    current_user: dict = Depends(rbac("client", "read")),
):
    """Authorization-scoped search across clients, accounts and journals."""
    query = (q or "").strip()
    if len(query) < 2:
        return api_response(True, {"results": []})

    firm_id = current_user.get("firm_id")
    eff = effective_client_ids(current_user)  # None ⇒ firm-wide (Partner/Manager)
    ql = query.lower()
    results: list[dict] = []

    # ── Clients (internal practice client excluded via find_all default) ──────
    clients = client_repo.find_all(firm_id=firm_id)
    for c in clients:
        if eff is not None and str(c.get("id")) not in eff:
            continue
        hay = " ".join(str(c.get(k, "")) for k in ("client_name", "pan", "gstin")).lower()
        if ql in hay:
            results.append({
                "id": c.get("id"),
                "category": "clients",
                "title": c.get("client_name", "—"),
                "subtitle": c.get("gstin") or c.get("pan") or c.get("entity_type") or "",
                "href": f"/clients/{c.get('id')}/overview",
            })
        if len(results) >= 8:
            break

    # ── Accounts + journals (real DB only; scoped to authorized clients) ──────
    if not _USE_MOCK and firm_id:
        like = f"%{query}%"
        try:
            acc_q = (_db().table("chart_of_accounts")
                     .select("id, account_code, account_name, client_id")
                     .eq("firm_id", firm_id)
                     .or_(f"account_name.ilike.{like},account_code.ilike.{like}")
                     .limit(10).execute())
            for a in (acc_q.data or []):
                if eff is not None and a.get("client_id") and str(a["client_id"]) not in eff:
                    continue
                results.append({
                    "id": a.get("id"), "category": "accounts",
                    "title": a.get("account_name", "—"),
                    "subtitle": a.get("account_code", ""),
                    "href": "/accounting/chart-of-accounts",
                })
        except Exception:
            pass
        try:
            jr_q = (_db().table("journal_entries")
                    .select("id, narration, entry_date, client_id")
                    .eq("firm_id", firm_id)
                    .ilike("narration", like)
                    .order("entry_date", desc=True).limit(10).execute())
            for j in (jr_q.data or []):
                if eff is not None and j.get("client_id") and str(j["client_id"]) not in eff:
                    continue
                results.append({
                    "id": j.get("id"), "category": "journals",
                    "title": j.get("narration", "Journal entry"),
                    "subtitle": j.get("entry_date", ""),
                    "href": "/accounting/journal",
                })
        except Exception:
            pass

    return api_response(True, {"results": results})
