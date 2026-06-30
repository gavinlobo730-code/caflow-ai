"""
Period validation service — prevents posting to locked financial years.

Uses the is_fy_locked(firm_id uuid, date date) Postgres function (migration 020).
Returns True if the given date falls in a locked FY for that firm.

Indian Financial Year: April 1 – March 31.
Locking is managed by Partners via the firm settings.
"""
import os
import logging
from datetime import date as date_type, datetime
from typing import Optional

from fastapi import HTTPException

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.period_validation")


def get_fy_for_date(date_str: str) -> str:
    """
    Return the Indian Financial Year string for the given ISO date.

    Indian FY runs April 1 – March 31.
    e.g. "2025-07-15" → "2025-26", "2026-01-10" → "2025-26", "2026-04-01" → "2026-27"

    Args:
        date_str: ISO date string "YYYY-MM-DD".

    Returns:
        FY string in format "YYYY-YY", e.g. "2025-26".
    """
    try:
        parsed = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Invalid date format '{date_str}': expected YYYY-MM-DD") from exc

    if parsed.month >= 4:
        # April–December: FY starts this calendar year
        start_year = parsed.year
    else:
        # January–March: FY started previous calendar year
        start_year = parsed.year - 1

    end_year_short = str(start_year + 1)[2:]  # last two digits
    return f"{start_year}-{end_year_short}"


class PeriodValidationService:
    """Validates that a transaction date falls in an open (unlocked) financial year."""

    def validate_posting_date(self, firm_id: str, date_str: str) -> None:
        """
        Raise HTTPException(422) if date_str falls in a locked FY for firm_id.

        Uses the is_fy_locked() Postgres RPC function (migration 020).
        In mock mode: always passes without any DB call.

        Fail-closed: if the lock status cannot be determined (RPC/DB error), the
        operation is BLOCKED rather than allowed through. Accounting integrity
        takes priority over availability — a posting must never slip into a
        possibly-locked year because a check failed silently.

        Args:
            firm_id:  Firm UUID string.
            date_str: ISO date string "YYYY-MM-DD".

        Raises:
            HTTPException(422): If the financial year containing date_str is locked.
            HTTPException(422): If the lock status could not be verified.
            ValueError:         If date_str is not a valid ISO date.
        """
        if _USE_MOCK:
            # In mock mode there is no DB — always allow posting
            return

        # Validate date format early and derive FY string for error messages
        fy_string = get_fy_for_date(date_str)

        try:
            # Lazy import to avoid circular dependency at module load time
            from core.supabase_client import get_supabase
            db = get_supabase()

            # Call the Postgres function defined in migration 020
            resp = db.rpc(
                "is_fy_locked",
                {"p_firm_id": firm_id, "p_date": date_str},
            ).execute()

            is_locked: Optional[bool] = None
            if resp.data is not None:
                # RPC returns a scalar; supabase-py wraps it in a list or returns directly
                if isinstance(resp.data, list) and len(resp.data) > 0:
                    is_locked = bool(resp.data[0])
                elif isinstance(resp.data, bool):
                    is_locked = resp.data

            if is_locked is True:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Cannot post to a locked financial year: {fy_string}. "
                        "Only Partners can unlock financial years."
                    ),
                )

            # Fail-closed: an indeterminate result must block, not pass.
            if is_locked is None:
                _logger.error(
                    "period_validation_service: is_fy_locked returned no value for "
                    "firm=%s date=%s — blocking (fail-closed).", firm_id, date_str,
                )
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Could not verify the financial-year lock status. "
                        "The posting was blocked to protect closed periods — please retry."
                    ),
                )

        except HTTPException:
            # Re-raise validation errors — do not swallow them
            raise
        except Exception as exc:
            # Fail-closed on DB/RPC errors: block rather than silently continue, so a
            # posting can never slip into a possibly-locked year because a check failed.
            _logger.error(
                "period_validation_service: is_fy_locked RPC failed for firm=%s date=%s — "
                "blocking (fail-closed). Error: %s",
                firm_id, date_str, exc,
            )
            raise HTTPException(
                status_code=422,
                detail=(
                    "Could not verify the financial-year lock status. "
                    "The posting was blocked to protect closed periods — please retry."
                ),
            )


# Module-level singleton
period_validation_service = PeriodValidationService()
