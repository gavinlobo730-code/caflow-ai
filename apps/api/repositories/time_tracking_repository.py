from typing import Optional
from datetime import datetime, timezone
from repositories.base import BaseRepository
from core import db_provider
from core.db_paging import fetch_all
from core.ist_clock import ist_day_window
from core.list_window import probe, split


_get_db = db_provider.request_db


class TimeTrackingRepository(BaseRepository[dict]):

    @staticmethod
    def _filtered(
        firm_id: str,
        user_id: Optional[str],
        client_id: Optional[str],
        task_id: Optional[str],
        date_from: Optional[str],
        date_to: Optional[str],
    ):
        query = _get_db().table("time_entries").select("*").eq("firm_id", firm_id)
        if user_id:
            query = query.eq("user_id", user_id)
        if client_id:
            query = query.eq("client_id", client_id)
        if task_id:
            query = query.eq("task_id", task_id)
        # A range of days is a range of INDIAN days (POST-A-251): midnight IST to midnight IST, the end exclusive.
        start, end = ist_day_window(date_from, date_to)
        if start:
            query = query.gte("started_at", start)
        if end:
            query = query.lt("started_at", end)
        return query

    def find_all(
        self,
        firm_id: str,
        user_id: Optional[str] = None,
        client_id: Optional[str] = None,
        task_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> list[dict]:
        """EVERY matching entry, newest first. For a reader that builds a figure
        or a file from them (the export); a screen that lists them asks
        `find_page`. A single read here was cut at PostgREST's ~1000 rows
        without a word, so an export of a busy firm's year was a short file."""
        rows = fetch_all(
            lambda: self._filtered(firm_id, user_id, client_id, task_id, date_from, date_to),
            "id",
            label="time_entries",
        )
        # fetch_all imposes its own ORDER BY id, so the newest-first order is
        # applied to the rows it handed back, never inside the paged query.
        rows.sort(key=lambda r: r.get("started_at") or "", reverse=True)
        return rows

    def find_page(
        self,
        firm_id: str,
        limit: int,
        user_id: Optional[str] = None,
        client_id: Optional[str] = None,
        task_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> tuple[list[dict], bool]:
        """The latest `limit` entries and whether older ones exist (core/list_window)."""
        result = (
            self._filtered(firm_id, user_id, client_id, task_id, date_from, date_to)
            .order("started_at", desc=True)
            .order("id", desc=True)
            .limit(probe(limit))
            .execute()
        )
        return split(result.data or [], limit)

    def find_running(self, firm_id: str, user_id: str) -> Optional[dict]:
        result = (
            _get_db().table("time_entries")
            .select("*")
            .eq("firm_id", firm_id)
            .eq("user_id", user_id)
            .is_("ended_at", None)
            .maybe_single()
            .execute()
        )
        return result.data

    def find_by_id(self, id: str, firm_id: Optional[str] = None) -> Optional[dict]:
        query = _get_db().table("time_entries").select("*").eq("id", id)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        result = query.maybe_single().execute()
        return result.data

    def create(self, data: dict) -> dict:
        result = _get_db().table("time_entries").insert({
            **data,
            "created_at": self.now_iso(),
            "updated_at": self.now_iso(),
        }).execute()
        return result.data[0]

    def update(self, id: str, data: dict, firm_id: Optional[str] = None) -> Optional[dict]:
        query = _get_db().table("time_entries").update({
            **data,
            "updated_at": self.now_iso(),
        }).eq("id", id)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        result = query.execute()
        return result.data[0] if result.data else None

    def delete(self, id: str, firm_id: Optional[str] = None) -> bool:
        query = _get_db().table("time_entries").delete().eq("id", id)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        result = query.execute()
        return len(result.data) > 0

    def get_summary(self, firm_id: str, user_id: Optional[str] = None, client_id: Optional[str] = None) -> dict:
        entries = self.find_all(firm_id=firm_id, user_id=user_id, client_id=client_id)
        completed = [e for e in entries if e.get("ended_at") and e.get("duration_minutes")]
        total_minutes = sum(e["duration_minutes"] for e in completed)
        billable_minutes = sum(e["duration_minutes"] for e in completed if e.get("is_billable"))

        by_client: dict[str, dict] = {}
        by_user: dict[str, dict] = {}
        for e in completed:
            cid = e.get("client_id") or "unknown"
            uid = e.get("user_id") or "unknown"
            if cid not in by_client:
                by_client[cid] = {"client_id": cid, "client_name": None, "minutes": 0}
            by_client[cid]["minutes"] += e["duration_minutes"]
            if uid not in by_user:
                by_user[uid] = {"user_id": uid, "user_name": None, "minutes": 0}
            by_user[uid]["minutes"] += e["duration_minutes"]

        return {
            "total_minutes": total_minutes,
            "billable_minutes": billable_minutes,
            "entries_count": len(completed),
            "by_client": list(by_client.values()),
            "by_user": list(by_user.values()),
        }


time_tracking_repo = TimeTrackingRepository()
