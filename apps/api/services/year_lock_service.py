"""
Secure financial-year lock management (multi-year hardening #3).

Year locks live in firms.locked_financial_years (text[]). Previously the frontend
wrote that array directly via the client (RLS allowed any authenticated firm user),
and the lock PIN was even read down to the browser — so the "Partner-only" control
was bypassable and the PIN exposed.

This service is the SINGLE backend writer of year locks:
  * runs under the service-role connection (a DB trigger now blocks every other
    session from changing locked_financial_years — see migration 136),
  * is reached only through a Partner-gated, audited endpoint,
  * verifies the firm lock PIN server-side (the PIN never leaves the server),
  * and is reused by the year-end workflow to auto-lock an approved year.

Indian FY strings look like "2025-26". All actions are audited via log_event.
"""
import logging
from typing import Optional

from fastapi import HTTPException

from services.audit_service import log_event

_logger = logging.getLogger("caflow.year_lock")


def get_state(db, firm_id: str) -> dict:
    """Return {locked_financial_years, pin_set}. Never returns the PIN itself."""
    resp = (db.table("firms").select("locked_financial_years, lock_pin")
            .eq("id", firm_id).limit(1).execute())
    if not resp.data:
        raise HTTPException(status_code=404, detail="Firm not found")
    row = resp.data[0]
    return {
        "locked_financial_years": row.get("locked_financial_years") or [],
        "pin_set": bool(row.get("lock_pin")),
    }


def set_lock(
    db,
    firm_id: str,
    financial_year: str,
    lock: bool,
    pin: Optional[str] = None,
    actor_id: Optional[str] = None,
    actor_email: Optional[str] = None,
    bypass_pin: bool = False,
) -> dict:
    """Lock or unlock a financial year for a firm (the only sanctioned writer).

    PIN: when a firm lock PIN is set it must be supplied and match (unless
    bypass_pin — used by trusted internal callers such as the year-end workflow);
    when no PIN is set yet, a supplied PIN is stored as the firm's lock PIN.

    Idempotent: locking an already-locked year (or unlocking an open one) is a no-op
    on the array. Every change is audited. Returns the new lock state.
    """
    if not financial_year:
        raise HTTPException(status_code=422, detail="financial_year is required")

    resp = (db.table("firms").select("locked_financial_years, lock_pin")
            .eq("id", firm_id).limit(1).execute())
    if not resp.data:
        raise HTTPException(status_code=404, detail="Firm not found")
    row = resp.data[0]
    current: list[str] = list(row.get("locked_financial_years") or [])
    stored_pin: Optional[str] = row.get("lock_pin")

    update: dict = {}
    if not bypass_pin:
        if stored_pin:
            if not pin or pin != stored_pin:
                raise HTTPException(status_code=403, detail="Incorrect lock PIN.")
        elif pin:
            # First lock: adopt the supplied PIN for future lock/unlock actions.
            update["lock_pin"] = pin
            stored_pin = pin

    if lock:
        if financial_year not in current:
            current.append(financial_year)
    else:
        current = [fy for fy in current if fy != financial_year]

    update["locked_financial_years"] = current
    upd = db.table("firms").update(update).eq("id", firm_id).execute()
    if not upd.data:
        raise HTTPException(status_code=404, detail="Firm not found")

    log_event(
        firm_id, "firm", firm_id,
        "year_lock" if lock else "year_unlock",
        actor_id=actor_id, actor_email=actor_email,
        new_data={"financial_year": financial_year, "locked_financial_years": current},
    )
    _logger.info("FY %s %s for firm %s", financial_year, "locked" if lock else "unlocked", firm_id)
    return {"locked_financial_years": current, "pin_set": bool(stored_pin)}
