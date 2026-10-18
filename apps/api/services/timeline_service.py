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
from core import db_provider
from core.ist_clock import ist_now, ist_today

_USE_MOCK = not os.environ.get("SUPABASE_URL")
# Events are written with the privileged client and by nobody signed in (POST-A-228, migration 515): under the production
# default (USE_USER_JWT) `get_supabase()` is the CALLER's own session, so this table's INSERT grant to `authenticated` was
# what let a browser name any actor it liked. The firm is always named by the caller of this service, never read from a row.
_write_db = db_provider.service_db
_logger = logging.getLogger("caflow.timeline_service")

# In-memory store for mock mode — enables GET /api/timeline in dev
MOCK_TIMELINE_EVENTS: list[dict] = []


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
        # The YYYY-MM period is the INDIAN month: on the 1st between 00:00 and 05:30 IST the UTC clock still reads the
        # month before. `now` stays the UTC instant, which is what `created_at` stores.
        row = self._row(
            client_id=client_id, firm_id=firm_id, financial_year=financial_year, category=category,
            event_type=event_type, title=title, description=description, severity=severity,
            entity_type=entity_type, entity_id=entity_id, amount_paise=amount_paise, actor_id=actor_id,
            actor_name=actor_name, actor_type=actor_type, action_label=action_label, action_url=action_url,
            visibility=visibility,
        )

        if _USE_MOCK:
            _logger.info(
                "[MOCK] timeline_event firm=%s client=%s fy=%s category=%s type=%s title=%r",
                firm_id, client_id, financial_year, category, event_type, title,
            )
            MOCK_TIMELINE_EVENTS.append(row)
            return

        try:
            self._insert(row)

            _logger.debug(
                "timeline_event inserted: firm=%s client=%s type=%s",
                firm_id, client_id, event_type,
            )
        except Exception as exc:  # Non-fatal: log and swallow
            _logger.warning(
                "timeline_service.log_timeline_event failed (non-fatal): %s", exc
            )

    def record_event(self, **fields) -> dict:
        """Write one event and SAY WHETHER IT WAS WRITTEN: the door the browser's own events come through.

        `log_timeline_event` is for the server's own bookkeeping and swallows a failure on purpose (a failed log must
        never look like a failed posting). A person who asked for an event to be recorded is owed the truth, so this
        raises, and the route answers 503 with a sentence. Same row, same insert; only the swallowing differs.
        Takes the same keywords as `log_timeline_event` and returns the stored row.
        """
        row = self._row(**fields)
        if _USE_MOCK:
            MOCK_TIMELINE_EVENTS.append(row)
            return row
        return self._insert(row)

    def _insert(self, row: dict) -> dict:
        """The ONE insert into the feed, so the server's own log and a requested record write it the same way.

        The firm is named last, on purpose: nothing in `row` can override it. Returns the stored row (or `row` when the
        database answers nothing back). Raises on failure; `log_timeline_event` is what swallows it."""
        payload = {**self._stored(row), "firm_id": row["firm_id"]}
        saved = _write_db().table("client_timeline_events").insert(payload).execute().data or []
        return saved[0] if saved else row

    @staticmethod
    def _row(
        *, client_id, firm_id, financial_year, category, event_type, title, description=None, severity="info",
        entity_type=None, entity_id=None, amount_paise=None, actor_id=None, actor_name=None, actor_type="user",
        action_label=None, action_url=None, visibility="all",
    ) -> dict:
        """The event as it is held: every key present, an unset optional one None."""
        return {
            "id":             str(uuid.uuid4()),
            "client_id":      client_id,
            "firm_id":        firm_id,
            "financial_year": financial_year,
            "period":         ist_now().strftime("%Y-%m"),
            "category":       category,
            "event_type":     event_type,
            "title":          title,
            "description":    description,
            "severity":       severity,
            "entity_type":    entity_type,
            "entity_id":      entity_id,
            # All money in integer paise (BIGINT) — never float
            "amount_paise":   int(amount_paise) if amount_paise is not None else None,
            "actor_id":       actor_id,
            "actor_name":     actor_name,
            "actor_type":     actor_type,
            "action_label":   action_label,
            "action_url":     action_url,
            "visibility":     visibility,
            "is_pinned":      False,
            "created_at":     datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _stored(row: dict) -> dict:
        """The row as the table receives it: an optional column left unset is OMITTED, not sent as NULL."""
        required = ("id", "client_id", "firm_id", "financial_year", "period", "category", "event_type", "title",
                    "severity", "actor_type", "visibility", "is_pinned", "created_at")
        return {k: v for k, v in row.items() if k in required or v is not None}

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
            today = ist_today()
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
