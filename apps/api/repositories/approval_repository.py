"""
Module 9.0 / M4 — approval_requests storage (mock + Supabase).
"""
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional
from core import db_provider

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_MOCK_REQUESTS: list[dict] = []
# The mock store's stand-in for the single UPDATE ... WHERE status = 'pending' the real table makes atomic.
_MOCK_CLAIM_LOCK = threading.Lock()


_db = db_provider.service_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApprovalRepository:
    def create(self, data: dict) -> dict:
        if _USE_MOCK:
            row = {
                "id": f"apr-{uuid.uuid4().hex[:8]}",
                "status": "pending",
                "created_at": _now(),
                "updated_at": _now(),
                "result": None, "decided_by": None, "decided_by_email": None,
                "decided_at": None, "reason": None,
                **data,
            }
            _MOCK_REQUESTS.append(row)
            return row
        payload = {**data, "created_at": _now(), "updated_at": _now()}
        res = _db().table("approval_requests").insert(payload).execute()
        return res.data[0] if res.data else payload

    def get(self, firm_id: str, request_id: str) -> Optional[dict]:
        if _USE_MOCK:
            return next((r for r in _MOCK_REQUESTS
                         if r["id"] == request_id and r["firm_id"] == firm_id), None)
        res = (_db().table("approval_requests").select("*")
               .eq("id", request_id).eq("firm_id", firm_id).limit(1).execute())
        return res.data[0] if res.data else None

    def list(self, firm_id: str, status: Optional[str] = None, limit: int = 100) -> list[dict]:
        if _USE_MOCK:
            rows = [r for r in _MOCK_REQUESTS if r["firm_id"] == firm_id
                    and (status is None or r["status"] == status)]
            return sorted(rows, key=lambda r: r["created_at"], reverse=True)[:limit]
        q = _db().table("approval_requests").select("*").eq("firm_id", firm_id)
        if status:
            q = q.eq("status", status)
        res = q.order("created_at", desc=True).limit(limit).execute()
        return res.data or []

    def update(self, firm_id: str, request_id: str, data: dict) -> Optional[dict]:
        if _USE_MOCK:
            row = self.get(firm_id, request_id)
            if row:
                row.update(data, updated_at=_now())
            return row
        payload = {**data, "updated_at": _now()}
        res = (_db().table("approval_requests").update(payload)
               .eq("id", request_id).eq("firm_id", firm_id).execute())
        return res.data[0] if res.data else None

    def decide_if_pending(self, firm_id: str, request_id: str, data: dict) -> Optional[dict]:
        """Give a request that is STILL pending its decision, once: one UPDATE ... WHERE status = 'pending'.

        Returns the updated row, or None when the request was no longer pending (somebody decided it first, or
        it does not exist). This is the claim: of two simultaneous decisions exactly one gets a row back.
        """
        if _USE_MOCK:
            with _MOCK_CLAIM_LOCK:
                row = self.get(firm_id, request_id)
                if not row or row.get("status") != "pending":
                    return None
                row.update(data, updated_at=_now())
                return row
        payload = {**data, "updated_at": _now()}
        res = (_db().table("approval_requests").update(payload)
               .eq("id", request_id).eq("firm_id", firm_id).eq("status", "pending").execute())
        return res.data[0] if res.data else None


approval_repo = ApprovalRepository()
