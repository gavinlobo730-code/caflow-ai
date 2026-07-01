"""
Currency master reader (G1) — the currencies table is the single source of truth.

No currency list is hardcoded in application code; every consumer reads the master
through these helpers (which take an injected DB handle so they are testable).
"""
from __future__ import annotations

BASE_CURRENCY = "INR"

_COLUMNS = "code, symbol, display_name, minor_unit, is_active"


def list_currencies(db, active_only: bool = True) -> list[dict]:
    q = db.table("currencies").select(_COLUMNS)
    if active_only:
        q = q.eq("is_active", True)
    res = q.order("code").execute()
    return list(getattr(res, "data", None) or [])


def get_currency(db, code: str) -> dict | None:
    res = (
        db.table("currencies")
        .select(_COLUMNS)
        .eq("code", code.upper())
        .limit(1)
        .execute()
    )
    rows = getattr(res, "data", None) or []
    return rows[0] if rows else None


def minor_unit(db, code: str, default: int = 2) -> int:
    """ISO 4217 minor-unit exponent for `code` (JPY→0, INR→2, KWD→3). Falls back to
    `default` only when the code is absent — real codes always come from the master."""
    row = get_currency(db, code)
    if row and row.get("minor_unit") is not None:
        return int(row["minor_unit"])
    return default
