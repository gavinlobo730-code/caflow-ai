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


def _in_scope(eff, client_id) -> bool:
    """Assignment-scope gate. eff is None ⇒ firm-wide (no extra filter).
    Entities without a client association (client_id falsy) are always included
    for firm staff — they are firm-level resources, not client-scoped."""
    if eff is None:
        return True
    if not client_id:
        return True
    return str(client_id) in eff


@router.get("")
def global_search(
    q: str = Query("", description="Search query (min 2 chars)"),
    current_user: dict = Depends(rbac("client", "read")),
):
    """Authorization-scoped search across clients, accounts, journals, leads,
    engagements, tasks, documents and DSC records."""
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

    # ── Leads (pipeline) — firm-scoped; assignment-scoped via converted client ──
    try:
        leads: list[dict] = []
        if _USE_MOCK or not firm_id:
            from routers.lifecycle import _MOCK_LEADS
            leads = [l for l in _MOCK_LEADS if l.get("firm_id") == firm_id]
        else:
            like = f"%{query}%"
            lr = (_db().table("leads")
                  .select("id, company_name, contact_name, email, phone, stage, converted_client_id")
                  .eq("firm_id", firm_id)
                  .or_(f"company_name.ilike.{like},contact_name.ilike.{like},"
                       f"email.ilike.{like},phone.ilike.{like}")
                  .limit(8).execute())
            leads = lr.data or []
        count = 0
        for l in leads:
            if not _in_scope(eff, l.get("converted_client_id")):
                continue
            hay = " ".join(str(l.get(k, "")) for k in
                           ("company_name", "contact_name", "email", "phone")).lower()
            if ql in hay:
                results.append({
                    "id": l.get("id"),
                    "category": "leads",
                    "title": l.get("company_name") or l.get("contact_name") or "—",
                    "subtitle": l.get("stage") or l.get("email") or "",
                    "href": "/pipeline",
                })
                count += 1
            if count >= 8:
                break
    except Exception:
        pass

    # ── Engagement letters — firm-scoped (no per-client assignment column) ──────
    try:
        engagements: list[dict] = []
        if _USE_MOCK or not firm_id:
            from routers.engagement_letters import _MOCK_ENGAGEMENTS
            engagements = [e for e in _MOCK_ENGAGEMENTS if e.get("firm_id") == firm_id]
        else:
            like = f"%{query}%"
            er = (_db().table("engagements")
                  .select("id, title, engagement_number, recipient_name, status, client_id")
                  .eq("firm_id", firm_id)
                  .or_(f"title.ilike.{like},engagement_number.ilike.{like},"
                       f"recipient_name.ilike.{like}")
                  .limit(8).execute())
            engagements = er.data or []
        count = 0
        for e in engagements:
            if not _in_scope(eff, e.get("client_id")):
                continue
            hay = " ".join(str(e.get(k, "")) for k in
                           ("title", "engagement_number", "recipient_name")).lower()
            if ql in hay:
                num = e.get("engagement_number") or ""
                status = e.get("status") or ""
                subtitle = f"{status} · {num}".strip(" ·") if (status or num) else ""
                results.append({
                    "id": e.get("id"),
                    "category": "engagements",
                    "title": e.get("title") or num or "—",
                    "subtitle": subtitle,
                    "href": "/engagements",
                })
                count += 1
            if count >= 8:
                break
    except Exception:
        pass

    # ── Tasks — firm-scoped via repo; assignment-scoped on client_id ───────────
    try:
        from repositories.task_repository import task_repo
        count = 0
        for t in task_repo.find_all(firm_id=firm_id):
            if not _in_scope(eff, t.get("client_id")):
                continue
            hay = " ".join(str(t.get(k, "")) for k in ("title", "description")).lower()
            if ql in hay:
                results.append({
                    "id": t.get("id"),
                    "category": "tasks",
                    "title": t.get("title") or "—",
                    "subtitle": t.get("status") or "",
                    "href": "/work",
                })
                count += 1
            if count >= 8:
                break
    except Exception:
        pass

    # ── Documents — firm-scoped via repo; assignment-scoped on client_id ───────
    try:
        from repositories.document_repository import document_repo
        count = 0
        for d in document_repo.find_all(firm_id=firm_id):
            if not _in_scope(eff, d.get("client_id")):
                continue
            hay = " ".join(str(d.get(k, "")) for k in ("file_name", "document_type")).lower()
            if ql in hay:
                results.append({
                    "id": d.get("id"),
                    "category": "documents",
                    "title": d.get("file_name") or "—",
                    "subtitle": d.get("document_type") or "",
                    "href": "/documents",
                })
                count += 1
            if count >= 8:
                break
    except Exception:
        pass

    # ── DSC records — firm-level (no client association) ────────────────────────
    # Lazily imported & try/excepted so search still works if the repo is absent.
    try:
        from repositories.dsc_repository import dsc_repo
        count = 0
        for s in dsc_repo.find_all(firm_id=firm_id):
            hay = " ".join(str(s.get(k, "")) for k in ("holder_name", "pan")).lower()
            if ql in hay:
                expiry = s.get("expiry_date") or ""
                results.append({
                    "id": s.get("id"),
                    "category": "dsc",
                    "title": s.get("holder_name") or "—",
                    "subtitle": f"DSC · expires {expiry}".rstrip(" ") if expiry else "DSC",
                    "href": "/settings/dsc-tracker",
                })
                count += 1
            if count >= 8:
                break
    except Exception:
        pass

    return api_response(True, {"results": results})
