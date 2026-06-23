import os
from typing import Optional
from datetime import datetime, timezone
from repositories.base import BaseRepository
from core.exceptions import NotFoundError

_USE_MOCK = not os.environ.get("SUPABASE_URL")

if _USE_MOCK:
    from mock_data import MOCK_INVOICES, INVOICE_INDEX


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class InvoiceRepository(BaseRepository[dict]):

    def find_by_id(self, id: str) -> Optional[dict]:
        if _USE_MOCK:
            inv = INVOICE_INDEX.get(id)
            return inv if inv and not inv.get("is_deleted") else None
        result = _get_db().table("fee_invoices").select("*").eq("id", id).eq("is_deleted", False).maybe_single().execute()
        return result.data

    def find_all(
        self,
        firm_id: Optional[str] = None,
        client_id: Optional[str] = None,
        engagement_id: Optional[str] = None,
        status: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        **filters,
    ) -> list[dict]:
        if _USE_MOCK:
            invoices = list(MOCK_INVOICES)
            invoices = [i for i in invoices if not i.get("is_deleted")]
            if firm_id:
                invoices = [i for i in invoices if i.get("firm_id") == firm_id]
            if client_id:
                invoices = [i for i in invoices if i.get("client_id") == client_id]
            if engagement_id:
                invoices = [i for i in invoices if i.get("engagement_id") == engagement_id]
            if status:
                invoices = [i for i in invoices if i.get("status") == status]
            if date_from:
                invoices = [i for i in invoices if i.get("invoice_date", "") >= date_from]
            if date_to:
                invoices = [i for i in invoices if i.get("invoice_date", "") <= date_to]
            return invoices

        query = _get_db().table("fee_invoices").select("*").eq("is_deleted", False)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        if client_id:
            query = query.eq("client_id", client_id)
        if engagement_id:
            query = query.eq("engagement_id", engagement_id)
        if status:
            query = query.eq("status", status)
        if date_from:
            query = query.gte("invoice_date", date_from)
        if date_to:
            query = query.lte("invoice_date", date_to)
        result = query.order("invoice_date", desc=True).execute()
        return result.data or []

    def list_for_engagement(self, engagement_id: str) -> list[dict]:
        return self.find_all(engagement_id=engagement_id)

    def find_by_id_or_raise(self, id: str) -> dict:
        invoice = self.find_by_id(id)
        if not invoice:
            raise NotFoundError("Invoice", id)
        return invoice

    def create(self, data: dict) -> dict:
        if _USE_MOCK:
            import uuid
            record = {
                "id": str(uuid.uuid4()),
                **data,
                "created_at": self.now_iso(),
                "updated_at": self.now_iso(),
            }
            MOCK_INVOICES.append(record)
            INVOICE_INDEX[record["id"]] = record
            return record
        result = _get_db().table("fee_invoices").insert({
            **data,
            "created_at": self.now_iso(),
            "updated_at": self.now_iso(),
        }).execute()
        return result.data[0]

    def update(self, id: str, data: dict) -> Optional[dict]:
        if _USE_MOCK:
            invoice = INVOICE_INDEX.get(id)
            if not invoice:
                return None
            invoice.update({**data, "updated_at": self.now_iso()})
            return invoice
        result = _get_db().table("fee_invoices").update({
            **data,
            "updated_at": self.now_iso(),
        }).eq("id", id).execute()
        return result.data[0] if result.data else None

    def change_status(self, id: str, new_status: str) -> Optional[dict]:
        """Transition invoice to new status (Draft -> Issued -> Paid)"""
        return self.update(id, {"status": new_status})

    def delete(self, id: str) -> bool:
        if _USE_MOCK:
            invoice = INVOICE_INDEX.get(id)
            if not invoice:
                return False
            invoice["is_deleted"] = True
            invoice["deleted_at"] = self.now_iso()
            return True
        _get_db().table("fee_invoices").update({
            "is_deleted": True,
            "deleted_at": self.now_iso(),
        }).eq("id", id).execute()
        return True

    def generate_next_invoice_number(self, firm_id: str, current_date: Optional[str] = None) -> str:
        """
        Generate next invoice number: CF-{fiscal_year}-{sequential}
        Example: CF-2025-001

        Fiscal year in India runs April 1 to March 31.
        Uses atomic DB sequence (next_invoice_number function) in production
        to prevent duplicate invoice numbers under concurrent requests.
        """
        if current_date is None:
            current_date = datetime.now(timezone.utc).isoformat()

        date_obj = datetime.fromisoformat(current_date.replace('Z', '+00:00'))
        fiscal_year = date_obj.year - 1 if date_obj.month < 4 else date_obj.year

        if _USE_MOCK:
            invoices = self.find_all(firm_id=firm_id)
            max_seq = 0
            for inv in invoices:
                inv_no = inv.get("invoice_no", "")
                if inv_no:
                    parts = inv_no.split("-")
                    if len(parts) == 3:
                        try:
                            max_seq = max(max_seq, int(parts[2]))
                        except ValueError:
                            pass
            return f"CF-{fiscal_year}-{max_seq + 1:03d}"

        # Atomic DB sequence — prevents race conditions under concurrent invoice generation
        result = _get_db().rpc("next_invoice_number", {"p_firm_id": firm_id}).execute()
        next_seq = result.data if isinstance(result.data, int) else 1
        return f"CF-{fiscal_year}-{next_seq:03d}"

    def soft_delete(self, id: str) -> bool:
        if _USE_MOCK:
            invoice = INVOICE_INDEX.get(id)
            if not invoice:
                return False
            invoice["is_deleted"] = True
            invoice["deleted_at"] = self.now_iso()
            return True
        result = _get_db().table("fee_invoices").update({
            "is_deleted": True,
            "deleted_at": self.now_iso(),
        }).eq("id", id).execute()
        return bool(result.data)

    def get_revenue_by_period(
        self,
        firm_id: str,
        date_from: str,
        date_to: str,
        statuses: list[str] = None,
    ) -> dict[str, dict]:
        """
        Get revenue aggregated by engagement for a given period.

        Args:
            firm_id: The firm ID to filter by
            date_from: ISO date string (YYYY-MM-DD)
            date_to: ISO date string (YYYY-MM-DD)
            statuses: List of invoice statuses to include (default: ['Issued', 'Paid'])

        Returns:
            dict with engagement_id as key and {revenue_paise, invoice_count} as value
        """
        if statuses is None:
            statuses = ['Issued', 'Paid']

        invoices = self.find_all(
            firm_id=firm_id,
            date_from=date_from,
            date_to=date_to,
        )

        by_engagement: dict[str, dict] = {}
        for invoice in invoices:
            if invoice.get("status") not in statuses:
                continue

            engagement_id = invoice.get("engagement_id")
            if not engagement_id:
                continue

            revenue_paise = invoice.get("total_paise", 0)

            if engagement_id not in by_engagement:
                by_engagement[engagement_id] = {
                    "revenue_paise": 0,
                    "invoice_count": 0,
                }

            by_engagement[engagement_id]["revenue_paise"] += revenue_paise
            by_engagement[engagement_id]["invoice_count"] += 1

        return by_engagement

    def get_revenue_by_client(self, firm_id: str, date_from: str, date_to: str) -> dict[str, int]:
        """
        Get total revenue (amount_paise) grouped by client_id.
        Returns: {client_id: total_amount_paise}
        All values in paise (integer arithmetic).
        """
        invoices = self.find_all(firm_id=firm_id, date_from=date_from, date_to=date_to)
        revenue_by_client: dict[str, int] = {}
        for inv in invoices:
            client_id = inv.get("client_id")
            if client_id:
                amount_paise = inv.get("amount_paise", 0)
                revenue_by_client[client_id] = revenue_by_client.get(client_id, 0) + amount_paise
        return revenue_by_client

    def get_revenue_by_engagement(self, firm_id: str, date_from: str, date_to: str) -> dict[str, dict]:
        """
        Get revenue grouped by engagement_id with engagement and client details.
        Returns: {engagement_id: {engagement_id, client_id, client_name, service_type, revenue_paise}}
        All values in paise (integer arithmetic).
        """
        invoices = self.find_all(firm_id=firm_id, date_from=date_from, date_to=date_to)
        revenue_by_engagement: dict[str, dict] = {}
        for inv in invoices:
            eng_id = inv.get("engagement_id")
            if eng_id:
                if eng_id not in revenue_by_engagement:
                    revenue_by_engagement[eng_id] = {
                        "engagement_id": eng_id,
                        "client_id": inv.get("client_id"),
                        "client_name": None,
                        "service_type": None,
                        "revenue_paise": 0,
                    }
                revenue_by_engagement[eng_id]["revenue_paise"] += inv.get("amount_paise", 0)
        return revenue_by_engagement


invoice_repo = InvoiceRepository()
