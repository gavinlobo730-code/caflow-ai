import os
from typing import Optional
from repositories.base import BaseRepository

_USE_MOCK = not os.environ.get("SUPABASE_URL")

MOCK_TDS_RETURNS: list[dict] = []
MOCK_TDS_DEDUCTIONS: list[dict] = []


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class TDSRepository(BaseRepository[dict]):

    def get_returns(
        self,
        client_id: str,
        firm_id: str,
    ) -> list[dict]:
        """Fetch all TDS returns for a client. IT Act Section 192/194."""
        if _USE_MOCK:
            return [
                r for r in MOCK_TDS_RETURNS
                if r["client_id"] == client_id and r["firm_id"] == firm_id
            ]
        result = (
            _get_db()
            .table("tds_returns")
            .select("*")
            .eq("firm_id", firm_id)
            .eq("client_id", client_id)
            .order("financial_year", desc=True)
            .execute()
        )
        return result.data or []

    def get_deductions(
        self,
        client_id: str,
        firm_id: str,
        financial_year: Optional[str] = None,
        quarter: Optional[str] = None,
    ) -> list[dict]:
        """Fetch TDS deductions for a client, optionally filtered by FY/quarter."""
        if _USE_MOCK:
            rows = [
                r for r in MOCK_TDS_DEDUCTIONS
                if r["client_id"] == client_id and r["firm_id"] == firm_id
            ]
            if financial_year:
                rows = [r for r in rows if r.get("financial_year") == financial_year]
            if quarter:
                rows = [r for r in rows if r.get("quarter") == quarter]
            return rows
        db = _get_db()
        q = (
            db.table("tds_deductions")
            .select("*")
            .eq("firm_id", firm_id)
            .eq("client_id", client_id)
        )
        if financial_year:
            q = q.eq("financial_year", financial_year)
        if quarter:
            q = q.eq("quarter", quarter)
        result = q.order("transaction_date", desc=True).execute()
        return result.data or []


tds_repo = TDSRepository()
