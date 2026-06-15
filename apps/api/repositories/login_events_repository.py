"""M6 — login_events storage (mock + Supabase)."""
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_MOCK_EVENTS: list[dict] = []


def _db():
    from core.supabase_client import get_service_supabase
    return get_service_supabase()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LoginEventsRepository:
    def record(self, firm_id: Optional[str], user_id: Optional[str], email: Optional[str],
               event: str, ip: Optional[str] = None, user_agent: Optional[str] = None) -> dict:
        row = {"firm_id": firm_id, "user_id": user_id, "email": email,
               "event": event, "ip": ip, "user_agent": user_agent}
        if _USE_MOCK:
            row = {"id": f"le-{uuid.uuid4().hex[:8]}", "created_at": _now(), **row}
            _MOCK_EVENTS.append(row)
            return row
        try:
            res = _db().table("login_events").insert({**row, "created_at": _now()}).execute()
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
