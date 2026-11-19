"""M6 — login_events storage (mock + Supabase)."""
import os
import uuid
from datetime import datetime, timezone
from typing import Optional
from core import db_provider

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_MOCK_EVENTS: list[dict] = []


_db = db_provider.service_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_missing_column(exc: Exception) -> bool:
    """PostgreSQL's undefined_column (42703), or PostgREST's own "column not in the schema cache" (PGRST204)."""
    return getattr(exc, "code", None) in ("42703", "PGRST204")


class LoginEventsRepository:
    def record(self, firm_id: Optional[str], user_id: Optional[str], email: Optional[str],
               event: str, ip: Optional[str] = None, user_agent: Optional[str] = None,
               session_id: Optional[str] = None) -> dict:
        row = {"firm_id": firm_id, "user_id": user_id, "email": email,
               "event": event, "ip": ip, "user_agent": user_agent}
        if _USE_MOCK:
            row = {"id": f"le-{uuid.uuid4().hex[:8]}", "created_at": _now(), **row, "session_id": session_id}
            _MOCK_EVENTS.append(row)
            return row
        # `session_id` is migration 765's column (POST-A-486). The API can be live a few minutes before the migration job has run, and an
        # insert naming a column that is not there fails the whole row: so it is tried again without that column, once, rather than
        # losing the sign-in record for those minutes. ONLY for that one answer (an undefined column): any other failure, a timeout most
        # of all, may have committed the row, and a second insert would write it twice. Everything else is the old behaviour: the record
        # is lost and the sign-in goes on (a sign-in record never blocks the sign-in). Both payloads are written out whole so the column
        # check can read them.
        try:
            res = _db().table("login_events").insert({
                "firm_id": firm_id, "user_id": user_id, "email": email, "event": event, "ip": ip, "user_agent": user_agent,
                "session_id": session_id, "created_at": _now()}).execute()
            return res.data[0] if res.data else {**row, "session_id": session_id}
        except Exception as exc:
            if not _is_missing_column(exc):
                return row
        try:
            res = _db().table("login_events").insert({
                "firm_id": firm_id, "user_id": user_id, "email": email, "event": event, "ip": ip, "user_agent": user_agent,
                "created_at": _now()}).execute()
            return res.data[0] if res.data else row
        except Exception:
            return row  # never block auth flows on audit write

    def list_for_firm(self, firm_id: str, limit: int = 100) -> list[dict]:
        if _USE_MOCK:
            return sorted([e for e in _MOCK_EVENTS if e["firm_id"] == firm_id],
                          key=lambda e: e["created_at"], reverse=True)[:limit]
        res = (_db().table("login_events").select("*").eq("firm_id", firm_id)
               .order("created_at", desc=True).limit(limit).execute())
        return res.data or []

    def list_for_user(self, firm_id: str, user_id: str, limit: int = 50) -> list[dict]:
        if _USE_MOCK:
            return sorted([e for e in _MOCK_EVENTS if e["firm_id"] == firm_id and e["user_id"] == user_id],
                          key=lambda e: e["created_at"], reverse=True)[:limit]
        res = (_db().table("login_events").select("*").eq("firm_id", firm_id).eq("user_id", user_id)
               .order("created_at", desc=True).limit(limit).execute())
        return res.data or []


login_events_repo = LoginEventsRepository()
