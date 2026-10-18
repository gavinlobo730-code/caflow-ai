import os
import uuid
from typing import Optional
from repositories.base import BaseRepository
from core import db_provider

_USE_MOCK = not os.environ.get("SUPABASE_URL")

if _USE_MOCK:
    from domain.ai_insight_service import MOCK_AI_INSIGHTS_V2, _insight_index


_get_db = db_provider.request_db


def _write_db():
    """The client every INSERT and UPDATE on `ai_insights` goes through: the privileged one (POST-A-257).

    A signed-in session holds no write privilege on this table (migration 507), so nothing here may write as the caller.
    Reads stay on `_get_db` (the caller's own session, so row security still narrows them). Writing privileged means row
    security is no longer the second lock on a write, so every write names its firm: a row is created with one and an
    update addresses a row by firm AND id."""
    return db_provider.service_db()


class AIInsightsRepository(BaseRepository[dict]):

    def find_all(
        self,
        firm_id: Optional[str] = None,
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
    ) -> list[dict]:
        if _USE_MOCK:
            items = list(MOCK_AI_INSIGHTS_V2)
            if client_id:
                items = [i for i in items if i.get("client_id") == client_id]
            if status:
                items = [i for i in items if i["status"] == status]
            if category:
                items = [i for i in items if i.get("category") == category]
            return sorted(items, key=lambda i: i["created_at"], reverse=True)

        query = _get_db().table("ai_insights").select("*, clients(client_name)").is_("deleted_at", None)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        if client_id:
            query = query.eq("client_id", client_id)
        if status:
            query = query.eq("status", status)
        if category:
            query = query.eq("category", category)
        result = query.order("created_at", desc=True).execute()
        return [_normalize(r) for r in (result.data or [])]

    def find_by_id(self, insight_id: str, firm_id: Optional[str] = None) -> Optional[dict]:
        if _USE_MOCK:
            return _insight_index.get(insight_id)

        query = _get_db().table("ai_insights").select("*, clients(client_name)").eq("id", insight_id).is_("deleted_at", None)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        result = query.maybe_single().execute()
        return _normalize(result.data) if result.data else None

    def create(self, data: dict) -> dict:
        if _USE_MOCK:
            iid = f"aiv2-gen-{str(uuid.uuid4())[:8]}"
            insight = {"id": iid, "created_at": self.now_iso(), **data}
            MOCK_AI_INSIGHTS_V2.append(insight)
            _insight_index[iid] = insight
            return insight

        payload = {k: v for k, v in data.items() if v is not None and k != "client_name"}
        # Map service fields to DB columns
        if "recommendation" in payload:
            payload["recommended_action"] = payload.pop("recommendation")
        if "insight_type" not in payload:
            payload["insight_type"] = "OTHER"
        payload["created_at"] = self.now_iso()
        payload["updated_at"] = self.now_iso()
        if not payload.get("firm_id"):
            # Written privileged, so a row with no firm would belong to nobody and be readable by nobody: refuse it here
            # rather than let the database's NOT NULL be the only thing that says so.
            raise ValueError("an insight is created for a firm: firm_id is required")
        result = _write_db().table("ai_insights").insert(payload).execute()
        return _normalize(result.data[0])

    def update_status(self, insight_id: str, status: str, firm_id: Optional[str]) -> Optional[dict]:
        """Change one insight's status. `firm_id` is REQUIRED: the write is made with the privileged client, and a row
        addressed by id alone could be any firm's (it was optional while row security was the second lock)."""
        if _USE_MOCK:
            insight = _insight_index.get(insight_id)
            if insight:
                insight["status"] = status
            return insight

        if not firm_id:
            raise ValueError("an insight's status is changed for a firm: firm_id is required")
        result = (
            _write_db()
            .table("ai_insights")
            .update({"status": status, "updated_at": self.now_iso()})
            .eq("id", insight_id)
            .eq("firm_id", firm_id)
            .execute()
        )
        return _normalize(result.data[0]) if result.data else None


def _normalize(row: dict) -> dict:
    """Map DB column names to service layer names."""
    if not row:
        return row
    # Flatten the clients join
    client_data = row.pop("clients", None)
    if client_data and "client_name" not in row:
        row["client_name"] = client_data.get("client_name", "Unknown")
    # Map recommended_action → recommendation
    if "recommended_action" in row and "recommendation" not in row:
        row["recommendation"] = row.pop("recommended_action")
    return row


ai_insights_repo = AIInsightsRepository()
