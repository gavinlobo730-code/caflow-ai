"""
Module 9.0 / M3 — user↔client assignment storage.

Thin CRUD over public.user_client_assignments (created in migration 022). This is
the data the M2 authorization engine (core.authz) reads to scope non-Partner
access. Dual-path: in-memory in mock/dev, Supabase in production.
"""
import os
import uuid
from typing import Optional

_USE_MOCK = not os.environ.get("SUPABASE_URL")

# In-memory store for mock/dev/tests — list of {id, firm_id, user_id, client_id}.
_MOCK_ASSIGNMENTS: list[dict] = []


def _db():
    from core.supabase_client import get_supabase
    return get_supabase()


class AssignmentRepository:
    def create(self, firm_id: str, user_id: str, client_id: str) -> dict:
        """Idempotent: returns the existing row if (user, client) already linked."""
        if _USE_MOCK:
            for a in _MOCK_ASSIGNMENTS:
                if a["user_id"] == user_id and a["client_id"] == client_id:
                    return a
            row = {"id": f"asg-{uuid.uuid4().hex[:8]}", "firm_id": firm_id,
                   "user_id": user_id, "client_id": client_id}
            _MOCK_ASSIGNMENTS.append(row)
            return row

        existing = (_db().table("user_client_assignments").select("*")
                    .eq("user_id", user_id).eq("client_id", client_id).limit(1).execute())
        if existing.data:
            return existing.data[0]
        res = (_db().table("user_client_assignments")
               .insert({"firm_id": firm_id, "user_id": user_id, "client_id": client_id})
               .execute())
        return res.data[0] if res.data else {"firm_id": firm_id, "user_id": user_id, "client_id": client_id}

    def remove(self, firm_id: str, user_id: str, client_id: str) -> bool:
        """Returns True if a row was removed."""
        if _USE_MOCK:
            before = len(_MOCK_ASSIGNMENTS)
            _MOCK_ASSIGNMENTS[:] = [
                a for a in _MOCK_ASSIGNMENTS
                if not (a["firm_id"] == firm_id and a["user_id"] == user_id and a["client_id"] == client_id)
            ]
            return len(_MOCK_ASSIGNMENTS) < before

        res = (_db().table("user_client_assignments").delete()
               .eq("firm_id", firm_id).eq("user_id", user_id).eq("client_id", client_id).execute())
        return bool(res.data)

    def list_for_user(self, firm_id: str, user_id: str) -> list[str]:
        """Client ids assigned to a user."""
        if _USE_MOCK:
            return [a["client_id"] for a in _MOCK_ASSIGNMENTS
                    if a["firm_id"] == firm_id and a["user_id"] == user_id]
        res = (_db().table("user_client_assignments").select("client_id")
               .eq("firm_id", firm_id).eq("user_id", user_id).execute())
        return [r["client_id"] for r in (res.data or [])]

    def list_for_client(self, firm_id: str, client_id: str) -> list[str]:
        """User ids assigned to a client."""
        if _USE_MOCK:
            return [a["user_id"] for a in _MOCK_ASSIGNMENTS
                    if a["firm_id"] == firm_id and a["client_id"] == client_id]
        res = (_db().table("user_client_assignments").select("user_id")
               .eq("firm_id", firm_id).eq("client_id", client_id).execute())
        return [r["user_id"] for r in (res.data or [])]

    def exists(self, firm_id: str, user_id: str, client_id: str) -> bool:
        return client_id in self.list_for_user(firm_id, user_id)


assignment_repo = AssignmentRepository()
