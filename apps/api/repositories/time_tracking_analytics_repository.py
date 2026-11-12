import os
from typing import Optional
from repositories.base import BaseRepository
from core import db_provider
from core.db_paging import fetch_all
from core.ist_clock import in_ist_window, ist_day_window

_USE_MOCK = not os.environ.get("SUPABASE_URL")

if _USE_MOCK:
    from mock_data import MOCK_TIME_ENTRIES


_get_db = db_provider.request_db


def _starts(date_from: str) -> str:
    """Midnight IST at the start of `date_from`: a report range is a range of INDIAN days (POST-A-251), so an entry started
    at 01:40 IST on 1 April, which is stored as 31 March 20:10 UTC, is April's."""
    return ist_day_window(date_from, None)[0]


def _ends(date_to: str) -> str:
    """Midnight IST at the END of `date_to`, to be used as an EXCLUSIVE bound (`.lt`)."""
    return ist_day_window(None, date_to)[1]


class TimeTrackingAnalyticsRepository(BaseRepository[dict]):

    def _ended_entries(self, firm_id: str, date_from: str, date_to: str, columns: str) -> list[dict]:
        """Every ENDED time entry of the firm that started in the window, `columns` of each, read in keyset pages.

        ONE READ FOR EVERY TIME ANALYTIC (POST-B-321). Each method below used to carry its own copy of this query with one
        unpaged `.execute()`, so past PostgREST's cap (about a thousand rows) every hours, cost and effort figure was
        silently short of the entries it left out, with no error. `columns` must include `id`, the paging key.
        """
        if _USE_MOCK:
            entries = [e for e in MOCK_TIME_ENTRIES if e.get("firm_id") == firm_id and e.get("ended_at")]
            return [e for e in entries if in_ist_window(e.get("started_at"), date_from, date_to)]
        return fetch_all(
            lambda: (
                _get_db().table("time_entries")
                .select(columns)
                .eq("firm_id", firm_id)
                .gte("started_at", _starts(date_from))
                .lt("started_at", _ends(date_to))
                .not_.is_("ended_at", "null")
            ),
            key="id", label="time entries for analytics",
        )

    def get_hours_by_employee(
        self,
        firm_id: str,
        date_from: str,
        date_to: str,
    ) -> dict[str, dict]:
        """
        Get total and billable minutes by employee for a given period.

        Args:
            firm_id: The firm ID to filter by
            date_from: ISO date string (YYYY-MM-DD)
            date_to: ISO date string (YYYY-MM-DD)

        Returns:
            dict with user_id as key and {total_minutes, billable_minutes} as value
        """
        entries = self._ended_entries(firm_id, date_from, date_to, "id, user_id, duration_minutes, is_billable")

        by_user: dict[str, dict] = {}
        for entry in entries:
            user_id = entry.get("user_id")
            if not user_id:
                continue

            # entry.get(key, 0) only substitutes the default when the KEY IS
            # ABSENT, not when its stored VALUE IS NULL -- and duration_minutes
            # can be NULL (an entry PATCHed with only ended_at, not started_at,
            # never recomputes it). `or 0` coalesces the None too.
            duration = entry.get("duration_minutes") or 0
            is_billable = entry.get("is_billable", False)

            if user_id not in by_user:
                by_user[user_id] = {"total_minutes": 0, "billable_minutes": 0}

            by_user[user_id]["total_minutes"] += duration
            if is_billable:
                by_user[user_id]["billable_minutes"] += duration

        return by_user

    def get_hours_by_client(
        self,
        firm_id: str,
        date_from: str,
        date_to: str,
    ) -> dict[str, dict]:
        """
        Get total and billable minutes by client for a given period.

        Args:
            firm_id: The firm ID to filter by
            date_from: ISO date string (YYYY-MM-DD)
            date_to: ISO date string (YYYY-MM-DD)

        Returns:
            dict with client_id as key and {total_minutes, billable_minutes} as value
        """
        entries = self._ended_entries(firm_id, date_from, date_to, "id, client_id, duration_minutes, is_billable")

        by_client: dict[str, dict] = {}
        for entry in entries:
            client_id = entry.get("client_id")
            if not client_id:
                continue

            duration = entry.get("duration_minutes") or 0
            is_billable = entry.get("is_billable", False)

            if client_id not in by_client:
                by_client[client_id] = {"total_minutes": 0, "billable_minutes": 0}

            by_client[client_id]["total_minutes"] += duration
            if is_billable:
                by_client[client_id]["billable_minutes"] += duration

        return by_client

    def get_firm_hours(
        self,
        firm_id: str,
        date_from: str,
        date_to: str,
    ) -> dict:
        """
        Get total and billable minutes for the entire firm for a given period.

        Args:
            firm_id: The firm ID to filter by
            date_from: ISO date string (YYYY-MM-DD)
            date_to: ISO date string (YYYY-MM-DD)

        Returns:
            dict with {total_minutes, billable_minutes}
        """
        entries = self._ended_entries(firm_id, date_from, date_to, "id, duration_minutes, is_billable")

        total_minutes = 0
        billable_minutes = 0

        for entry in entries:
            duration = entry.get("duration_minutes") or 0
            is_billable = entry.get("is_billable", False)

            total_minutes += duration
            if is_billable:
                billable_minutes += duration

        return {
            "total_minutes": total_minutes,
            "billable_minutes": billable_minutes,
        }

    #: What the worth of billable time needs of an entry, and no more: the two rates an hour can have been priced with.
    WORTH_COLUMNS = "id, client_id, engagement_id, duration_minutes, is_billable, billable_rate_paise, hourly_rate_paise"

    def get_worth_entries(self, firm_id: str, date_from: str, date_to: str) -> list[dict]:
        """The ended time entries of the window with the two rates each was recorded with, for the realization report.

        THE WORTH IS NOT COMPUTED HERE (POST-A-426). It used to be: this read averaged the legacy `hourly_rate_paise` of
        the entries that carried one and the report multiplied that average by ALL the engagement's billable minutes, so
        an hour priced with the stored `billable_rate_paise` (every timer entry and every entry priced from an engagement
        or a person since migration 451) was worth nothing and the screen drew a dash. The rows are returned whole and
        `domain/practice/realization` prices each from its own rate (`time_rate.entry_rate`), the one reading the
        unbilled-work total uses. Read in keyset pages like every time read here (`_ended_entries`)."""
        return self._ended_entries(firm_id, date_from, date_to, self.WORTH_COLUMNS)

    #: What the cost of a client's, an engagement's or a member's time needs of an entry, and no more.
    COST_COLUMNS = "id, user_id, client_id, engagement_id, duration_minutes, is_billable"

    def get_cost_entries(self, firm_id: str, date_from: str, date_to: str) -> list[dict]:
        """The ended time entries of the window, who recorded each, for which client and engagement and for how long.

        THE COST IS NOT COMPUTED HERE (POST-B-321). It used to be, as `minutes x time_entries.hourly_rate_paise`: the rate
        the hour BILLS at, which is NULL on every entry the timer started, so those hours cost nothing. What an hour costs
        the practice is the member's `users.cost_rate_paise`, an unset one is unknown and not zero, and
        `domain/practice/profitability` decides all of that; this returns the rows it folds.
        """
        return self._ended_entries(firm_id, date_from, date_to, self.COST_COLUMNS)

time_tracking_analytics_repo = TimeTrackingAnalyticsRepository()
