import os
from typing import Optional
from repositories.base import BaseRepository
from core.exceptions import NotFoundError
from core import db_provider

_USE_MOCK = not os.environ.get("SUPABASE_URL")

if _USE_MOCK:
    from mock_data import MOCK_ENGAGEMENTS, ENGAGEMENT_INDEX


_get_db = db_provider.request_db

#: What an engagement SAYS about the work, with none of what it charges. A caller that only needs to know which
#: services a client is engaged for, and whether the engagement is live, reads these and nothing else: the fee, the
#: billing cycle and the notes are the practice's economics, which core/permissions reserves to a Partner.
SCOPE_COLUMNS = ("id", "firm_id", "client_id", "service_type", "status")


class EngagementRepository(BaseRepository[dict]):

    def find_by_id(self, id: str) -> Optional[dict]:
        if _USE_MOCK:
            e = ENGAGEMENT_INDEX.get(id)
            return e if e else None
        result = _get_db().table("fee_engagements").select("*").eq("id", id).maybe_single().execute()
        return result.data

    def find_all(
        self,
        firm_id: Optional[str] = None,
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        **filters,
    ) -> list[dict]:
        if _USE_MOCK:
            engagements = list(MOCK_ENGAGEMENTS)
            if firm_id:
                engagements = [e for e in engagements if e.get("firm_id") == firm_id]
            if client_id:
                engagements = [e for e in engagements if e.get("client_id") == client_id]
            if status:
                engagements = [e for e in engagements if e.get("status") == status]
            return engagements

        query = _get_db().table("fee_engagements").select("*")
        if firm_id:
            query = query.eq("firm_id", firm_id)
        if client_id:
            query = query.eq("client_id", client_id)
        if status:
            query = query.eq("status", status)
        result = query.order("created_at", desc=True).execute()
        return result.data or []

    def find_scope(self, firm_id: str, client_id: Optional[str] = None) -> list[dict]:
        """The engagements' SCOPE (client, service, status), read WITHOUT their fees and without the caller's row security.

        WHY A SEPARATE READ. `find_all` runs as the caller, so what comes back is what the caller's row security lets
        them see, and the fee economics of an engagement are a Partner's. The obligation generator, the ITR due-date
        question and the Compliance tab ask something else: which services does this client buy, and is the engagement
        live. Asking that through `find_all` meant a rule on who reads FEES silently changed which obligations a
        calendar got, with the response still looking like success. This read is the privileged client with the
        firm's own scope, and the four columns above; the CALLER IS AUTHORISED BY THE ROUTE (rbac and
        assert_client_access, or an `allowed_client_ids` filter) before it gets here, which is the contract of
        `db_provider.service_db`.
        """
        if _USE_MOCK:
            rows = self.find_all(firm_id=firm_id, client_id=client_id)
            return [{k: e.get(k) for k in SCOPE_COLUMNS} for e in rows]
        query = (db_provider.service_db().table("fee_engagements")
                 .select(", ".join(SCOPE_COLUMNS)).eq("firm_id", firm_id))
        if client_id:
            query = query.eq("client_id", client_id)
        return query.order("created_at", desc=True).execute().data or []

    def count_active_for_client(self, firm_id: str, client_id: str) -> int:
        """How many ACTIVE fee engagements this client has: a COUNT, read with the privileged client.

        The client-delete check asks whether live fees would be orphaned. Read as the caller, a rule that keeps the fee
        tables from everyone below `billing:read` would answer zero for a person the Partner granted `client:delete`
        and not billing, and the blocker would silently never fire. No row and no figure leaves this method, only a
        number; the CALLER IS AUTHORISED BY THE ROUTE (`rbac("client", "delete")` and the client scope) before it is
        called, which is the contract of `db_provider.service_db`. A failed read RAISES: the caller turns that into a
        refusal, because a count that could not be taken is not a zero.
        """
        if _USE_MOCK:
            return len(self.find_all(firm_id=firm_id, client_id=client_id, status="Active"))
        res = (db_provider.service_db().table("fee_engagements").select("id", count="exact")
               .eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "Active").execute())
        return res.count if res.count is not None else len(res.data or [])

    def find_scope_by_id(self, id: str, firm_id: str) -> Optional[dict]:
        """One engagement's scope (see `find_scope`), or None when it is not this firm's."""
        if _USE_MOCK:
            e = ENGAGEMENT_INDEX.get(id)
            return {k: e.get(k) for k in SCOPE_COLUMNS} if e and e.get("firm_id") == firm_id else None
        rows = (db_provider.service_db().table("fee_engagements").select(", ".join(SCOPE_COLUMNS))
                .eq("id", id).eq("firm_id", firm_id).limit(1).execute().data or [])
        return rows[0] if rows else None

    def list_by_status(self, firm_id: str, status: str) -> list[dict]:
        return self.find_all(firm_id=firm_id, status=status)

    def get_or_raise(self, id: str) -> dict:
        engagement = self.find_by_id(id)
        if not engagement:
            raise NotFoundError("Engagement", id)
        return engagement

    def create(self, data: dict) -> dict:
        if _USE_MOCK:
            import uuid
            record = {
                "id": str(uuid.uuid4()),
                **data,
                "created_at": self.now_iso(),
                "updated_at": self.now_iso(),
            }
            MOCK_ENGAGEMENTS.append(record)
            ENGAGEMENT_INDEX[record["id"]] = record
            return record
        result = _get_db().table("fee_engagements").insert({**data, "created_at": self.now_iso(), "updated_at": self.now_iso()}).execute()
        return result.data[0]

    def update(self, id: str, data: dict) -> Optional[dict]:
        if _USE_MOCK:
            engagement = ENGAGEMENT_INDEX.get(id)
            if not engagement:
                return None
            engagement.update({**data, "updated_at": self.now_iso()})
            return engagement
        result = _get_db().table("fee_engagements").update({**data, "updated_at": self.now_iso()}).eq("id", id).execute()
        return result.data[0] if result.data else None

    def soft_delete(self, id: str) -> bool:
        if _USE_MOCK:
            engagement = ENGAGEMENT_INDEX.get(id)
            if not engagement:
                return False
            engagement["updated_at"] = self.now_iso()
            return True
        result = _get_db().table("fee_engagements").update({"updated_at": self.now_iso()}).eq("id", id).execute()
        return bool(result.data)


engagement_repo = EngagementRepository()
