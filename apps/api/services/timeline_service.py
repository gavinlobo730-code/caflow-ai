"""
Timeline service — writes structured events to client_timeline_events.
Non-fatal: failures are logged as warnings and never propagate to callers.

Table: client_timeline_events (migration 045)
Columns: id, client_id, firm_id, financial_year, period, category, event_type,
         severity, title, description, action_label, action_url, entity_type,
         entity_id, actor_type, actor_id, actor_name, amount_paise,
         is_pinned, visibility, created_at, deleted_at, deleted_by
"""
import os
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.timeline_service")


class TimelineService:
    """Writes structured events to the client_timeline_events table."""

    def log_timeline_event(
        self,
        client_id: str,
        firm_id: str,
        financial_year: str,
        category: str,
        event_type: str,
        title: str,
        description: Optional[str] = None,
        severity: str = "info",
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        amount_paise: Optional[int] = None,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
        actor_type: str = "user",
        action_label: Optional[str] = None,
        action_url: Optional[str] = None,
        visibility: str = "all",
    ) -> None:
        """
        Insert a structured event into client_timeline_events.

        Non-fatal: never raises; logs warnings on any failure.
        In mock mode: logs at INFO level only, no DB call.

        Args:
            client_id:       CA client UUID.
            firm_id:         CA firm UUID.
            financial_year:  Indian FY string, e.g. "2025-26".
            category:        One of: accounting|compliance|payroll|tax|document|work|ai|portal|team
            event_type:      Granular type, e.g. "invoice_posted".
            title:           Short human-readable title.
            description:     Optional longer description.
            severity:        info|success|warning|critical (default: info).
            entity_type:     Optional entity class, e.g. "sales_invoice".
            entity_id:       Optional entity UUID.
            amount_paise:    Optional monetary value in integer paise (BIGINT).
            actor_id:        Optional actor UUID (user/system).
            actor_name:      Optional actor display name or email.
            actor_type:      user|system|ai|client (default: user).
            action_label:    Optional CTA label, e.g. "View Invoice".
            action_url:      Optional CTA URL path.
            visibility:      all|internal|partner_only (default: all).
        """
        # Derive the YYYY-MM period string from today
        now = datetime.now(timezone.utc)
        period = now.strftime("%Y-%m")

        if _USE_MOCK:
            _logger.info(
                "[MOCK] timeline_event firm=%s client=%s fy=%s category=%s type=%s title=%r",
                firm_id, client_id, financial_year, category, event_type, title,
            )
            return

        try:
            # Lazy import to avoid circular dependency at module load time
            from core.supabase_client import get_supabase
            db = get_supabase()

            payload: dict = {
                "id":             str(uuid.uuid4()),
                "client_id":      client_id,
                "firm_id":        firm_id,
                "financial_year": financial_year,
                "period":         period,
                "category":       category,
                "event_type":     event_type,
                "title":          title,
                "severity":       severity,
                "actor_type":     actor_type,
                "visibility":     visibility,
                "is_pinned":      False,
                "created_at":     now.isoformat(),
            }

            if description is not None:
                payload["description"] = description
            if entity_type is not None:
                payload["entity_type"] = entity_type
            if entity_id is not None:
                payload["entity_id"] = entity_id
            if amount_paise is not None:
                # All money in integer paise (BIGINT) — never float
                payload["amount_paise"] = int(amount_paise)
            if actor_id is not None:
                payload["actor_id"] = actor_id
            if actor_name is not None:
                payload["actor_name"] = actor_name
            if action_label is not None:
                payload["action_label"] = action_label
            if action_url is not None:
                payload["action_url"] = action_url

            db.table("client_timeline_events").insert(payload).execute()

            _logger.debug(
                "timeline_event inserted: firm=%s client=%s type=%s",
                firm_id, client_id, event_type,
            )
        except Exception as exc:  # Non-fatal: log and swallow
            _logger.warning(
                "timeline_service.log_timeline_event failed (non-fatal): %s", exc
            )


    def log(
        self,
        client_id: str,
        category: str,
        title: str,
        description: Optional[str] = None,
        severity: str = "info",
        firm_id: str = "",
        financial_year: str = "",
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        amount_paise: Optional[int] = None,
        actor_id: Optional[str] = None,
    ) -> None:
        """Convenience shorthand for log_timeline_event with minimal required args."""
        if not financial_year:
            from datetime import date
            today = date.today()
            fy_start = today.year if today.month >= 4 else today.year - 1
            financial_year = f"{fy_start}-{str(fy_start + 1)[-2:]}"
        self.log_timeline_event(
            client_id=client_id,
            firm_id=firm_id,
            financial_year=financial_year,
            category=category,
            event_type=title.lower().replace(" ", "_"),
            title=title,
            description=description,
            severity=severity,
            entity_type=entity_type,
            entity_id=entity_id,
            amount_paise=amount_paise,
            actor_id=actor_id,
        )


# Module-level singleton
timeline_service = TimelineService()
