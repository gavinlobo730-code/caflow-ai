"""POST-A-486 — the sessions a login is signed in on (mock + Supabase). Migration 765.

One row per (person, sign-in service session id). `register` creates it and says whether it did, which is how a second device is
noticed exactly once even when two requests announce the same new session at the same moment (a unique key decides, not a read
followed by a write). `touch` says the session is still in use; `end` and `end_others` close rows. A row is never deleted here:
which devices a login used, and when, is the record the Team screen reads. The privileged client is the only writer (the signed-in
database roles hold nothing on the table).
"""
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from core import db_provider

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_MOCK_ROWS: list[dict] = []

_db = db_provider.service_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LoginSessionsRepository:
    def register(self, firm_id: str, user_id: str, session_id: str, ip: Optional[str], user_agent: Optional[str],
                 now: Optional[str] = None) -> bool:
        """Open the session if this is the first anyone has heard of it. True when it was created now, False when it was already
        known (its sighting is then refreshed). Raises if the write fails: the caller decides whether that blocks anything."""
        stamp = now or _now()
        if _USE_MOCK:
            for row in _MOCK_ROWS:
                if row["user_id"] == user_id and row["session_id"] == session_id:
                    self._refresh(row, stamp)
                    return False
            _MOCK_ROWS.append({
                "id": f"ls-{uuid.uuid4().hex[:8]}", "firm_id": firm_id, "user_id": user_id, "session_id": session_id,
                "ip": ip, "user_agent": user_agent, "started_at": stamp, "last_seen_at": stamp, "ended_at": None,
            })
            return True
        res = (_db().table("login_sessions")
               .upsert({"firm_id": firm_id, "user_id": user_id, "session_id": session_id, "ip": ip, "user_agent": user_agent,
                        "started_at": stamp, "last_seen_at": stamp},
                       on_conflict="user_id,session_id", ignore_duplicates=True)
               .execute())
        # With ignore-duplicates the answer holds the rows that were INSERTED, and none for a session already known.
        if res.data:
            return True
        self.touch(firm_id, user_id, session_id, stamp)
        return False

    @staticmethod
    def _refresh(row: dict, stamp: str) -> None:
        if row.get("ended_at"):
            return                      # an ended session stays ended: a late request from it does not bring it back
        row["last_seen_at"] = stamp

    def touch(self, firm_id: str, user_id: str, session_id: str, now: Optional[str] = None) -> None:
        """Say the session is still in use. A session that was ended is not reopened. The address and browser are the ones the session
        was FIRST seen with: a report only moves the time."""
        stamp = now or _now()
        if _USE_MOCK:
            for row in _MOCK_ROWS:
                if row["firm_id"] == firm_id and row["user_id"] == user_id and row["session_id"] == session_id:
                    self._refresh(row, stamp)
            return
        (_db().table("login_sessions").update({"last_seen_at": stamp})
         .eq("firm_id", firm_id).eq("user_id", user_id).eq("session_id", session_id).is_("ended_at", "null").execute())

    def end(self, firm_id: str, user_id: str, session_id: str, how: str, now: Optional[str] = None) -> None:
        stamp = now or _now()
        if _USE_MOCK:
            for row in _MOCK_ROWS:
                if (row["firm_id"] == firm_id and row["user_id"] == user_id and row["session_id"] == session_id
                        and not row.get("ended_at")):
                    row["ended_at"], row["ended_how"] = stamp, how
            return
        (_db().table("login_sessions").update({"ended_at": stamp, "ended_how": how})
         .eq("firm_id", firm_id).eq("user_id", user_id).eq("session_id", session_id).is_("ended_at", "null").execute())

    def end_others(self, firm_id: str, user_id: str, keep_session_id: str, how: str, now: Optional[str] = None) -> None:
        """End every open session of the person except `keep_session_id`."""
        stamp = now or _now()
        if _USE_MOCK:
            for row in _MOCK_ROWS:
                if (row["firm_id"] == firm_id and row["user_id"] == user_id and row["session_id"] != keep_session_id
                        and not row.get("ended_at")):
                    row["ended_at"], row["ended_how"] = stamp, how
            return
        (_db().table("login_sessions").update({"ended_at": stamp, "ended_how": how})
         .eq("firm_id", firm_id).eq("user_id", user_id).neq("session_id", keep_session_id).is_("ended_at", "null").execute())

    def end_all(self, firm_id: str, user_id: str, how: str, now: Optional[str] = None) -> None:
        """End every open session of the person (a suspension, a forced sign-out)."""
        stamp = now or _now()
        if _USE_MOCK:
            for row in _MOCK_ROWS:
                if row["firm_id"] == firm_id and row["user_id"] == user_id and not row.get("ended_at"):
                    row["ended_at"], row["ended_how"] = stamp, how
            return
        (_db().table("login_sessions").update({"ended_at": stamp, "ended_how": how})
         .eq("firm_id", firm_id).eq("user_id", user_id).is_("ended_at", "null").execute())

    def open_for_user(self, firm_id: str, user_id: str, seen_since: str) -> list[dict]:
        """Sessions of one person not ended and heard from since `seen_since` (an ISO instant): the candidates for "live"."""
        if _USE_MOCK:
            return [dict(r) for r in _MOCK_ROWS
                    if r["firm_id"] == firm_id and r["user_id"] == user_id and not r.get("ended_at")
                    and r["last_seen_at"] >= seen_since]
        res = (_db().table("login_sessions").select("*").eq("firm_id", firm_id).eq("user_id", user_id)
               .is_("ended_at", "null").gte("last_seen_at", seen_since).order("last_seen_at", desc=True).limit(50).execute())
        return res.data or []

    def open_for_firm(self, firm_id: str, seen_since: str, limit: int = 500) -> list[dict]:
        """Every open, recently heard-from session in the firm, for the Partners' list of who is signed in where."""
        if _USE_MOCK:
            rows = [dict(r) for r in _MOCK_ROWS
                    if r["firm_id"] == firm_id and not r.get("ended_at") and r["last_seen_at"] >= seen_since]
            return sorted(rows, key=lambda r: r["last_seen_at"], reverse=True)[:limit]
        res = (_db().table("login_sessions").select("*").eq("firm_id", firm_id)
               .is_("ended_at", "null").gte("last_seen_at", seen_since)
               .order("last_seen_at", desc=True).order("id").limit(limit).execute())
        return res.data or []


login_sessions_repo = LoginSessionsRepository()
