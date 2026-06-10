import os
from typing import Optional
from repositories.base import BaseRepository

_USE_MOCK = not os.environ.get("SUPABASE_URL")

if _USE_MOCK:
    from mock_data import MOCK_TIME_ENTRIES


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class TimeTrackingAnalyticsRepository(BaseRepository[dict]):

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
        if _USE_MOCK:
            entries = [e for e in MOCK_TIME_ENTRIES if e.get("firm_id") == firm_id and e.get("ended_at")]
            entries = [e for e in entries if e.get("started_at", "")[:10] >= date_from and e.get("started_at", "")[:10] <= date_to]
        else:
            query = (
                _get_db().table("time_entries")
                .select("user_id, duration_minutes, is_billable")
                .eq("firm_id", firm_id)
                .gte("started_at", f"{date_from}T00:00:00Z")
                .lte("started_at", f"{date_to}T23:59:59Z")
                .not_("ended_at", "is", None)
            )
            result = query.execute()
            entries = result.data or []

        by_user: dict[str, dict] = {}
        for entry in entries:
            user_id = entry.get("user_id")
            if not user_id:
                continue

            duration = entry.get("duration_minutes", 0)
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
        if _USE_MOCK:
            entries = [e for e in MOCK_TIME_ENTRIES if e.get("firm_id") == firm_id and e.get("ended_at")]
            entries = [e for e in entries if e.get("started_at", "")[:10] >= date_from and e.get("started_at", "")[:10] <= date_to]
        else:
            query = (
                _get_db().table("time_entries")
                .select("client_id, duration_minutes, is_billable")
                .eq("firm_id", firm_id)
                .gte("started_at", f"{date_from}T00:00:00Z")
                .lte("started_at", f"{date_to}T23:59:59Z")
                .not_("ended_at", "is", None)
            )
            result = query.execute()
            entries = result.data or []

        by_client: dict[str, dict] = {}
        for entry in entries:
            client_id = entry.get("client_id")
            if not client_id:
                continue

            duration = entry.get("duration_minutes", 0)
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
        if _USE_MOCK:
            entries = [e for e in MOCK_TIME_ENTRIES if e.get("firm_id") == firm_id and e.get("ended_at")]
            entries = [e for e in entries if e.get("started_at", "")[:10] >= date_from and e.get("started_at", "")[:10] <= date_to]
        else:
            query = (
                _get_db().table("time_entries")
                .select("duration_minutes, is_billable")
                .eq("firm_id", firm_id)
                .gte("started_at", f"{date_from}T00:00:00Z")
                .lte("started_at", f"{date_to}T23:59:59Z")
                .not_("ended_at", "is", None)
            )
            result = query.execute()
            entries = result.data or []

        total_minutes = 0
        billable_minutes = 0

        for entry in entries:
            duration = entry.get("duration_minutes", 0)
            is_billable = entry.get("is_billable", False)

            total_minutes += duration
            if is_billable:
                billable_minutes += duration

        return {
            "total_minutes": total_minutes,
            "billable_minutes": billable_minutes,
        }

    def get_effort_by_engagement(
        self,
        firm_id: str,
        date_from: str,
        date_to: str,
    ) -> dict[str, dict]:
        """
        Get effort metrics aggregated by engagement for a given period.

        Args:
            firm_id: The firm ID to filter by
            date_from: ISO date string (YYYY-MM-DD)
            date_to: ISO date string (YYYY-MM-DD)

        Returns:
            dict with engagement_id as key and {billable_minutes, total_minutes, avg_hourly_rate_paise} as value
        """
        if _USE_MOCK:
            entries = [e for e in MOCK_TIME_ENTRIES if e.get("firm_id") == firm_id and e.get("ended_at")]
            entries = [e for e in entries if e.get("started_at", "")[:10] >= date_from and e.get("started_at", "")[:10] <= date_to]
        else:
            query = (
                _get_db().table("time_entries")
                .select("engagement_id, duration_minutes, is_billable, hourly_rate_paise")
                .eq("firm_id", firm_id)
                .gte("started_at", f"{date_from}T00:00:00Z")
                .lte("started_at", f"{date_to}T23:59:59Z")
                .not_("ended_at", "is", None)
            )
            result = query.execute()
            entries = result.data or []

        by_engagement: dict[str, dict] = {}
        for entry in entries:
            engagement_id = entry.get("engagement_id")
            if not engagement_id:
                continue

            duration = entry.get("duration_minutes", 0)
            is_billable = entry.get("is_billable", False)
            hourly_rate_paise = entry.get("hourly_rate_paise", 0)

            if engagement_id not in by_engagement:
                by_engagement[engagement_id] = {
                    "billable_minutes": 0,
                    "total_minutes": 0,
                    "hourly_rates": [],  # Track all rates for averaging
                }

            by_engagement[engagement_id]["total_minutes"] += duration
            if is_billable:
                by_engagement[engagement_id]["billable_minutes"] += duration
            if hourly_rate_paise > 0:
                by_engagement[engagement_id]["hourly_rates"].append(hourly_rate_paise)

        # Convert hourly_rates list to average and remove the list
        for engagement_id in by_engagement:
            rates = by_engagement[engagement_id].pop("hourly_rates")
            avg_rate = sum(rates) // len(rates) if rates else 0
            by_engagement[engagement_id]["avg_hourly_rate_paise"] = avg_rate

        return by_engagement

    def get_cost_by_client(
        self,
        firm_id: str,
        date_from: str,
        date_to: str,
    ) -> dict[str, int]:
        """
        Get total cost (duration_minutes * hourly_rate_paise / 60) grouped by client_id.
        All arithmetic in paise (integer).

        Args:
            firm_id: The firm ID to filter by
            date_from: ISO date string (YYYY-MM-DD)
            date_to: ISO date string (YYYY-MM-DD)

        Returns:
            dict with client_id as key and total_cost_paise as value
        """
        if _USE_MOCK:
            entries = [e for e in MOCK_TIME_ENTRIES if e.get("firm_id") == firm_id and e.get("ended_at")]
            entries = [e for e in entries if e.get("started_at", "")[:10] >= date_from and e.get("started_at", "")[:10] <= date_to]
        else:
            query = (
                _get_db().table("time_entries")
                .select("client_id, duration_minutes, hourly_rate_paise")
                .eq("firm_id", firm_id)
                .gte("started_at", f"{date_from}T00:00:00Z")
                .lte("started_at", f"{date_to}T23:59:59Z")
                .not_("ended_at", "is", None)
            )
            result = query.execute()
            entries = result.data or []

        cost_by_client: dict[str, int] = {}
        for entry in entries:
            client_id = entry.get("client_id")
            if not client_id:
                continue

            duration_minutes = entry.get("duration_minutes", 0)
            hourly_rate_paise = entry.get("hourly_rate_paise", 0)

            # Cost = (duration_minutes / 60) * hourly_rate_paise (integer arithmetic)
            cost_paise = (duration_minutes * hourly_rate_paise) // 60

            if client_id not in cost_by_client:
                cost_by_client[client_id] = 0

            cost_by_client[client_id] += cost_paise

        return cost_by_client

    def get_cost_by_engagement(
        self,
        firm_id: str,
        date_from: str,
        date_to: str,
    ) -> dict[str, int]:
        """
        Get total cost (duration_minutes * hourly_rate_paise / 60) grouped by engagement_id.
        All arithmetic in paise (integer).

        Args:
            firm_id: The firm ID to filter by
            date_from: ISO date string (YYYY-MM-DD)
            date_to: ISO date string (YYYY-MM-DD)

        Returns:
            dict with engagement_id as key and total_cost_paise as value
        """
        if _USE_MOCK:
            entries = [e for e in MOCK_TIME_ENTRIES if e.get("firm_id") == firm_id and e.get("ended_at")]
            entries = [e for e in entries if e.get("started_at", "")[:10] >= date_from and e.get("started_at", "")[:10] <= date_to]
        else:
            query = (
                _get_db().table("time_entries")
                .select("engagement_id, duration_minutes, hourly_rate_paise")
                .eq("firm_id", firm_id)
                .gte("started_at", f"{date_from}T00:00:00Z")
                .lte("started_at", f"{date_to}T23:59:59Z")
                .not_("ended_at", "is", None)
            )
            result = query.execute()
            entries = result.data or []

        cost_by_engagement: dict[str, int] = {}
        for entry in entries:
            engagement_id = entry.get("engagement_id")
            if not engagement_id:
                continue

            duration_minutes = entry.get("duration_minutes", 0)
            hourly_rate_paise = entry.get("hourly_rate_paise", 0)

            # Cost = (duration_minutes / 60) * hourly_rate_paise (integer arithmetic)
            cost_paise = (duration_minutes * hourly_rate_paise) // 60

            if engagement_id not in cost_by_engagement:
                cost_by_engagement[engagement_id] = 0

            cost_by_engagement[engagement_id] += cost_paise

        return cost_by_engagement

    def get_metrics_by_team_member(
        self,
        firm_id: str,
        date_from: str,
        date_to: str,
    ) -> dict[str, dict]:
        """
        Get profitability metrics by team member including effort and utilisation.
        Returns: {user_id: {effort_minutes, cost_paise, revenue_paise, profit_paise, profit_margin_pct, utilisation_pct}}
        """
        if _USE_MOCK:
            entries = [e for e in MOCK_TIME_ENTRIES if e.get("firm_id") == firm_id and e.get("ended_at")]
            entries = [e for e in entries if e.get("started_at", "")[:10] >= date_from and e.get("started_at", "")[:10] <= date_to]
        else:
            query = (
                _get_db().table("time_entries")
                .select("user_id, duration_minutes, hourly_rate_paise, is_billable")
                .eq("firm_id", firm_id)
                .gte("started_at", f"{date_from}T00:00:00Z")
                .lte("started_at", f"{date_to}T23:59:59Z")
                .not_("ended_at", "is", None)
            )
            result = query.execute()
            entries = result.data or []

        metrics_by_user: dict[str, dict] = {}
        for entry in entries:
            user_id = entry.get("user_id")
            if not user_id:
                continue

            if user_id not in metrics_by_user:
                metrics_by_user[user_id] = {
                    "effort_minutes": 0,
                    "billable_minutes": 0,
                    "cost_paise": 0,
                }

            duration_minutes = entry.get("duration_minutes", 0)
            hourly_rate_paise = entry.get("hourly_rate_paise", 0)
            is_billable = entry.get("is_billable", False)

            cost_paise = (duration_minutes * hourly_rate_paise) // 60

            metrics_by_user[user_id]["effort_minutes"] += duration_minutes
            metrics_by_user[user_id]["cost_paise"] += cost_paise

            if is_billable:
                metrics_by_user[user_id]["billable_minutes"] += duration_minutes

        return metrics_by_user


time_tracking_analytics_repo = TimeTrackingAnalyticsRepository()
