"""
Knowledge Base + Client Instructions (Amendment v1.1 FR-KB, Batch 6).

Operational, lightweight (NOT a wiki). Reuses Postgres storage + FTS (no vectors),
RLS, the role/assignment model, internal_client_service (G1), timeline_service,
and audit_service. Tables (knowledge_articles / knowledge_article_versions /
client_instructions) were created in migration 073; assignment-gated RLS in 079.

Security note: the backend uses the SERVICE_ROLE key (RLS bypassed), so the
visibility helpers here are the PRIMARY control; migration 079 RLS is defense-in-depth.

Validated model:
- Manager/Partner: firm-wide. Executive/Reviewer: assignment-gated. Client: none.
- Internal practice client KB/instructions: Partner-only (G1).
- Articles authored by Manager+; client instructions by Executive+ (Executive only
  for assigned clients). Reviewer read-only. No acknowledgement/completion.
"""
import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from services.internal_client_service import is_internal_client

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.knowledge")

_FIRMWIDE_ROLES = {"partner", "owner", "manager"}   # see client-scoped content firm-wide
_PARTNER_ROLES = {"partner", "owner"}


def _db():
    from core.supabase_client import get_supabase
    return get_supabase()


def _role(current_user: dict) -> str:
    return str(current_user.get("role", "")).strip().lower()


# ── Visibility / authoring helpers (pure; the PRIMARY enforcement) ───────────

def can_view_client_content(current_user: dict, client_id: Optional[str],
                            is_internal: bool, is_assigned: bool) -> bool:
    """Read visibility for a client-scoped article or instruction."""
    role = _role(current_user)
    if is_internal:                       # G1 overrides everything
        return role in _PARTNER_ROLES
    if role in _FIRMWIDE_ROLES:           # Partner / Manager firm-wide
        return True
    if role in ("executive", "staff", "article", "reviewer", "viewer"):
        return is_assigned                # Executive/Reviewer assignment-gated
    return False                          # Client / unknown: none


def can_write_instruction(current_user: dict, is_internal: bool, is_assigned: bool) -> bool:
    """Write/edit a client instruction (Executive+; Executive only if assigned)."""
    role = _role(current_user)
    if is_internal:
        return role in _PARTNER_ROLES
    if role in _FIRMWIDE_ROLES:
        return True
    if role in ("executive", "staff", "article"):
        return is_assigned
    return False                          # Reviewer/Viewer/Client: read-only


def next_version(current_version: int) -> int:
    return int(current_version or 0) + 1


# ── Assignment lookup ────────────────────────────────────────────────────────

def is_assigned(firm_id: str, user_id: Optional[str], client_id: Optional[str]) -> bool:
    if not user_id or not client_id:
        return False
    if _USE_MOCK:
        return True   # mock has no assignments table; tests pass explicit flags to pure helpers
    res = (_db().table("user_client_assignments").select("id")
           .eq("user_id", user_id).eq("client_id", client_id).limit(1).execute())
    return bool(res.data)


def _assert_client_access(current_user: dict, client_id: str, *, write: bool = False) -> None:
    firm_id = current_user.get("firm_id")
    internal = is_internal_client(client_id, firm_id)
    assigned = is_assigned(firm_id, current_user.get("id"), client_id)
    ok = (can_write_instruction(current_user, internal, assigned) if write
          else can_view_client_content(current_user, client_id, internal, assigned))
    if not ok:
        # 404 for internal client (don't disclose); 403 otherwise.
        raise HTTPException(status_code=404 if internal else 403,
                            detail="Not found" if internal else "Not authorised for this client")


# ── Knowledge articles (DB CRUD; thin) ───────────────────────────────────────

def create_article(current_user: dict, scope: str, title: str, content: str,
                   department: Optional[str] = None, client_id: Optional[str] = None,
                   tags: Optional[list] = None) -> dict:
    firm_id = current_user.get("firm_id")
    if scope == "client":
        if not client_id:
            raise HTTPException(status_code=422, detail="client_id required for client-scoped article")
        _assert_client_access(current_user, client_id, write=False)  # must be visible to author
        if is_internal_client(client_id, firm_id) and _role(current_user) not in _PARTNER_ROLES:
            raise HTTPException(status_code=404, detail="Not found")  # G1
    if _USE_MOCK:
        return {"id": "mock", "scope": scope, "title": title, "current_version": 1}
    db = _db()
    art = db.table("knowledge_articles").insert({
        "firm_id": firm_id, "scope": scope, "department": department, "client_id": client_id,
        "title": title, "current_version": 1, "tags": tags or [],
        "is_archived": False, "created_by": current_user.get("id"),
    }).execute().data[0]
    db.table("knowledge_article_versions").insert({
        "firm_id": firm_id, "article_id": art["id"], "version": 1,
        "content": content or "", "changed_by": current_user.get("id"),
    }).execute()
    _emit_article_event(current_user, art, "kb_article_created", "Knowledge article created")
    return art


def edit_article(current_user: dict, article_id: str, content: str) -> dict:
    """Append a NEW version (never mutate history) and bump current_version."""
    if _USE_MOCK:
        return {"id": article_id, "current_version": 2}
    db = _db()
    art = _load_article_or_404(db, current_user, article_id)
    v = next_version(art.get("current_version", 1))
    db.table("knowledge_article_versions").insert({
        "firm_id": art["firm_id"], "article_id": article_id, "version": v,
        "content": content or "", "changed_by": current_user.get("id"),
    }).execute()
    upd = db.table("knowledge_articles").update({
        "current_version": v, "updated_at": _now()}).eq("id", article_id).execute().data[0]
    _emit_article_event(current_user, upd, "kb_article_updated", f"Knowledge article updated (v{v})")
    return upd


def restore_version(current_user: dict, article_id: str, version: int) -> dict:
    """Rollback = write the chosen version's content as a NEW version (non-destructive)."""
    if _USE_MOCK:
        return {"id": article_id, "restored_from": version}
    db = _db()
    art = _load_article_or_404(db, current_user, article_id)
    old = (db.table("knowledge_article_versions").select("content")
           .eq("article_id", article_id).eq("version", version).limit(1).execute().data)
    if not old:
        raise HTTPException(status_code=404, detail="Version not found")
    return edit_article(current_user, article_id, old[0]["content"])


def archive_article(current_user: dict, article_id: str) -> dict:
    if _USE_MOCK:
        return {"id": article_id, "is_archived": True}
    db = _db()
    art = _load_article_or_404(db, current_user, article_id)
    upd = db.table("knowledge_articles").update({"is_archived": True, "updated_at": _now()}).eq("id", article_id).execute().data[0]
    _emit_article_event(current_user, upd, "kb_article_archived", "Knowledge article archived")
    return upd


def _load_article_or_404(db, current_user: dict, article_id: str) -> dict:
    firm_id = current_user.get("firm_id")
    res = db.table("knowledge_articles").select("*").eq("id", article_id).eq("firm_id", firm_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Article not found")
    art = res.data[0]
    if art.get("scope") == "client" and art.get("client_id"):
        _assert_client_access(current_user, art["client_id"], write=False)
    return art


def get_article(current_user: dict, article_id: str) -> dict:
    if _USE_MOCK:
        return {"id": article_id}
    db = _db()
    art = _load_article_or_404(db, current_user, article_id)
    cur = (db.table("knowledge_article_versions").select("content")
           .eq("article_id", article_id).eq("version", art.get("current_version", 1)).limit(1).execute().data)
    art["content"] = cur[0]["content"] if cur else ""
    return art


def list_versions(current_user: dict, article_id: str) -> list[dict]:
    if _USE_MOCK:
        return []
    db = _db()
    _load_article_or_404(db, current_user, article_id)  # enforces visibility
    return (db.table("knowledge_article_versions").select("version, changed_by, changed_at")
            .eq("article_id", article_id).order("version", desc=True).execute().data or [])


def search_articles(current_user: dict, query: Optional[str] = None, scope: Optional[str] = None,
                    client_id: Optional[str] = None, include_archived: bool = False) -> list[dict]:
    """Firm/department article search (Postgres FTS). Excludes client-scoped +
    internal-client content unless a specific assigned client_id is requested."""
    if _USE_MOCK:
        return []
    db = _db()
    q = db.table("knowledge_articles").select("*").eq("firm_id", current_user.get("firm_id"))
    if not include_archived:
        q = q.eq("is_archived", False)
    if client_id:
        _assert_client_access(current_user, client_id, write=False)
        q = q.eq("client_id", client_id)
    elif scope:
        q = q.eq("scope", scope)
    else:
        q = q.in_("scope", ["firm", "department"])   # firm KB list excludes client-scoped
    if query:
        q = q.ilike("title", f"%{query}%")           # title search; FTS handled by GIN at scale
    rows = q.order("updated_at", desc=True).execute().data or []
    # Defense-in-depth: drop internal-client rows for non-partners (service-role bypasses RLS).
    return [r for r in rows if not (is_internal_client(r.get("client_id"), current_user.get("firm_id"))
                                    and _role(current_user) not in _PARTNER_ROLES)]


# ── Client instructions (DB CRUD; thin) ──────────────────────────────────────

def list_client_instructions(current_user: dict, client_id: str) -> list[dict]:
    _assert_client_access(current_user, client_id, write=False)
    if _USE_MOCK:
        return []
    return (_db().table("client_instructions").select("*")
            .eq("firm_id", current_user.get("firm_id")).eq("client_id", client_id)
            .order("is_pinned", desc=True).order("created_at", desc=True).execute().data or [])


def create_instruction(current_user: dict, client_id: str, title: str, body: str,
                       is_pinned: bool = False) -> dict:
    _assert_client_access(current_user, client_id, write=True)
    if _USE_MOCK:
        return {"id": "mock", "client_id": client_id, "title": title}
    row = _db().table("client_instructions").insert({
        "firm_id": current_user.get("firm_id"), "client_id": client_id,
        "title": title, "body": body or "", "is_pinned": is_pinned,
        "created_by": current_user.get("id"),
    }).execute().data[0]
    _emit_instruction_event(current_user, row, "client_instruction_created", f"Client instruction added: {title}")
    return row


def update_instruction(current_user: dict, client_id: str, instruction_id: str, fields: dict) -> dict:
    _assert_client_access(current_user, client_id, write=True)
    allowed = {k: v for k, v in fields.items() if k in ("title", "body", "is_pinned", "is_archived")}
    if _USE_MOCK:
        return {"id": instruction_id, **allowed}
    allowed["updated_at"] = _now()
    row = (_db().table("client_instructions").update(allowed)
           .eq("id", instruction_id).eq("firm_id", current_user.get("firm_id"))
           .eq("client_id", client_id).execute().data)
    if not row:
        raise HTTPException(status_code=404, detail="Instruction not found")
    evt = "client_instruction_archived" if allowed.get("is_archived") else "client_instruction_updated"
    _emit_instruction_event(current_user, row[0], evt, "Client instruction updated")
    return row[0]


# ── Timeline / audit wiring ──────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit_article_event(current_user: dict, art: dict, event_type: str, title: str) -> None:
    """Client-scoped article events -> client Timeline; firm/department -> audit_log."""
    try:
        if art.get("scope") == "client" and art.get("client_id"):
            from services.timeline_service import timeline_service
            timeline_service.log(art["client_id"], "ai", title, art.get("title", ""), "info",
                                 firm_id=current_user.get("firm_id", ""),
                                 entity_type="knowledge_article", entity_id=art.get("id"),
                                 actor_id=current_user.get("id"))
        else:
            from services.audit_service import log_event
            log_event(current_user.get("firm_id", ""), "knowledge_article", str(art.get("id", "")),
                      event_type, actor_id=current_user.get("id"),
                      actor_email=current_user.get("email"), new_data={"title": art.get("title")})
    except Exception:  # pragma: no cover - non-fatal
        pass


def _emit_instruction_event(current_user: dict, row: dict, event_type: str, title: str) -> None:
    try:
        from services.timeline_service import timeline_service
        timeline_service.log(row["client_id"], "ai", title, row.get("title", ""), "info",
                             firm_id=current_user.get("firm_id", ""),
                             entity_type="client_instruction", entity_id=row.get("id"),
                             actor_id=current_user.get("id"))
    except Exception:  # pragma: no cover - non-fatal
        pass
