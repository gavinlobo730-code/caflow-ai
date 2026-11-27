from typing import Optional
from datetime import date
from repositories.base import BaseRepository
from core import db_provider
from core.db_paging import fetch_all
from core.ist_clock import ist_day_window
from core.list_window import probe, split
from domain.time_summary import summarise


_get_db = db_provider.request_db


def _writer():
    """The client that CREATES, CHANGES and REMOVES a time entry: the server's own, carrying the person it acts for (POST-A-546).

    An entry's two rate columns price the hour and `billed_invoice_id` says which invoice bills it. Those are the server's to
    write (the rate is resolved when the work is recorded, the mark is set by a claim that takes only entries still unbilled),
    and the database is about to refuse them from a signed-in session, so that a hand-made request cannot price or mark an
    entry. An insert carries the rate and an update may, and removing an entry an invoice bills would leave the invoice billing
    time that is not there, so all three go through here, ahead of that migration (the house order: the server's writers move
    in a change that ships first). Reads stay the caller's. Every statement names the firm, because row security does not run
    for this client."""
    return db_provider.privileged_for(_get_db())


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
        if not data.get("firm_id"):
            raise ValueError("a time entry is created for a firm: the server's own client is not narrowed by row security")
        result = _writer().table("time_entries").insert({
            **data,
            "created_at": self.now_iso(),
            "updated_at": self.now_iso(),
        }).execute()
        return result.data[0]

    def update(self, id: str, data: dict, firm_id: str) -> Optional[dict]:
        """Change one entry OF THE FIRM. `firm_id` is required, never defaulted: this statement runs as the server's own client."""
        if not firm_id:
            raise ValueError("a time entry is changed inside a firm: the server's own client is not narrowed by row security")
        result = (_writer().table("time_entries").update({
            **data,
            "updated_at": self.now_iso(),
        }).eq("id", id).eq("firm_id", firm_id).execute())
        return result.data[0] if result.data else None

    def delete(self, id: str, firm_id: str) -> bool:
        """Remove one entry OF THE FIRM. `firm_id` is required, never defaulted: this statement runs as the server's own client."""
        if not firm_id:
            raise ValueError("a time entry is removed inside a firm: the server's own client is not narrowed by row security")
        result = _writer().table("time_entries").delete().eq("id", id).eq("firm_id", firm_id).execute()
        return len(result.data) > 0

    def get_summary(self, firm_id: str, user_id: str, date_from: date, date_to: date) -> dict:
        """One member's FINISHED time over a range of Indian days, both counted (POST-A-156).

        Summed by the database (`public.time_entry_summary`, migration 586) on the privileged client, because the answer is a few
        numbers and every entry the member ever made is not (CLAUDE.md's reporting rule). It used to fetch every entry and add them
        up here. With no service database configured the twin `domain.time_summary.summarise` runs over the same window's rows; in
        practice that is the in-memory test doubles, because `find_all` itself needs a database. `tests/test_time_entry_summary_parity_pg.py`
        holds the two identical. The sum is the member's own time on every client, including one they are no longer assigned to:
        it is their time, and the entry list on the same screen is a different question (what the caller may see). A failed call is raised, never
        answered from the twin: two answers to one question, one of them silent, is how the figures drift."""
        db = db_provider.service_db_or_none()
        if db is not None:
            start, end = ist_day_window(date_from, date_to)
            res = db.rpc("time_entry_summary", {"p_firm": firm_id, "p_user": user_id, "p_from": start, "p_to": end}).execute()
            out = getattr(res, "data", None)
            if not isinstance(out, dict) or "total_minutes" not in out:
                raise ValueError(f"time_entry_summary returned {type(out).__name__}, not a summary")
            return out
        rows = self.find_all(firm_id=firm_id, user_id=user_id, date_from=date_from.isoformat(), date_to=date_to.isoformat())
        return summarise(rows, date_from, date_to)


time_tracking_repo = TimeTrackingRepository()
