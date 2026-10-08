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

THE PIN (POST-A-004, migration 480)
    The PIN is NOT in `firms` any more. It was plaintext in `firms.lock_pin`, which every member of the firm
    can read over PostgREST, and the comparison was `!=` with no limit on guesses. It is now a salted PBKDF2
    hash (`domain/firm/lock_pin`) in `public.firm_lock_pins`, a table `authenticated` holds no privilege on,
    reached only here and only through the service-role client. `firms.lock_pin` is kept (a DROP moves both
    sides of the production-fixture comparison) but is always NULL, and a CHECK keeps it so.

    A PIN that is checked is also COUNTED, before it is compared: a PIN is a few characters and the only
    thing standing between a signed-in Partner session and a practice-wide unlock. Every attempt that
    reaches the comparison spends one place in two windows (per person, tighter; per firm), a refusal is a
    429 with `Retry-After` EVEN FOR THE RIGHT PIN, and a wrong PIN leaves an audit row that names the year
    and the direction and never the PIN. Counting only the misses would have needed a peek the limiter does
    not have and would let a flood of parallel guesses all pass the check before the first miss was
    recorded. The cost is that a Partner closing more than five years inside a quarter of an hour is asked
    to wait, which is the rarer thing. The windows live in this process, like every limiter here: right
    for the one worker the API runs as, N times looser for N, and forgotten on a restart.
"""
import logging
from datetime import datetime, timezone
from math import ceil
from typing import Optional

from fastapi import HTTPException

from core.observability import capture_soft_failure
from core.rate_window import SlidingWindowLimiter
from domain.firm import lock_pin
from services.audit_service import log_event

_logger = logging.getLogger("caflow.year_lock")

# The table is named as a literal at each of its three call sites, deliberately: a table reached through a name
# is a chain tests/test_every_query_on_a_firm_table_carries_its_firm_scope.py cannot read, and its budget of
# such chains is exact.

#: How many times one person, and one firm, may put a PIN to the comparison in a window. Chosen so a Partner
#: who fumbles a PIN twice and then closes a year is never refused, and a guess at a four-character PIN is
#: slowed to a few hundred a day for a signed-in Partner session (and by a restart, not at all: see above).
ACTOR_ATTEMPTS = 5
FIRM_ATTEMPTS = 10
ATTEMPT_WINDOW_S = 15 * 60

_actor_attempts = SlidingWindowLimiter(ACTOR_ATTEMPTS, ATTEMPT_WINDOW_S)
_firm_attempts = SlidingWindowLimiter(FIRM_ATTEMPTS, ATTEMPT_WINDOW_S)


def reset_pin_attempts() -> None:
    """Forget every counted attempt. For a test, so one test's misses do not refuse the next."""
    _actor_attempts.reset()
    _firm_attempts.reset()


def _spend_pin_attempt(firm_id: str, actor_id: Optional[str]) -> None:
    """Count one attempt at the PIN, or refuse with a 429 that says how long to wait.

    The person's window is asked first: a Partner who has used theirs is refused without touching the
    firm's, so one person cannot spend the firm's whole allowance on their own.
    """
    wait: Optional[int] = None
    if actor_id:
        wait = _actor_attempts.hit_or_wait(f"{firm_id}:{actor_id}")
    if wait is None:
        wait = _firm_attempts.hit_or_wait(firm_id)
    if wait is None:
        return
    minutes = max(1, ceil(wait / 60))
    _logger.warning("year-lock PIN attempts refused for firm %s: %s s until a place opens", firm_id, wait)
    raise HTTPException(
        status_code=429,
        detail=(f"Too many attempts at the lock PIN. Please wait {minutes} minute"
                f"{'s' if minutes != 1 else ''} and try again. Nothing was changed."),
        headers={"Retry-After": str(wait)},
    )


def _stored_pin_hash(db, firm_id: str) -> Optional[str]:
    """The firm's stored PIN hash, or None when no PIN has been set."""
    resp = (db.table("firm_lock_pins").select("pin_hash")
            .eq("firm_id", firm_id).limit(1).execute())
    rows = resp.data or []
    if not rows:
        return None
    return rows[0].get("pin_hash") or ""


def get_state(db, firm_id: str) -> dict:
    """Return {locked_financial_years, pin_set}. Never returns the PIN, or anything made from it."""
    resp = (db.table("firms").select("locked_financial_years")
            .eq("id", firm_id).limit(1).execute())
    if not resp.data:
        raise HTTPException(status_code=404, detail="Firm not found")
    row = resp.data[0]
    return {
        "locked_financial_years": row.get("locked_financial_years") or [],
        "pin_set": _stored_pin_hash(db, firm_id) is not None,
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
    when no PIN is set yet, a supplied PIN is stored (as a hash) as the firm's lock PIN.

    `actor_id` is the Supabase AUTH id: it names the person in the audit trail and keys their attempt
    window (the audit-actor rule, tests/test_the_audit_log_names_one_kind_of_actor.py).

    Idempotent: locking an already-locked year (or unlocking an open one) is a no-op
    on the array. Every change is audited. Returns the new lock state.
    """
    if not financial_year:
        raise HTTPException(status_code=422, detail="financial_year is required")

    resp = (db.table("firms").select("locked_financial_years")
            .eq("id", firm_id).limit(1).execute())
    if not resp.data:
        raise HTTPException(status_code=404, detail="Firm not found")
    current: list[str] = list(resp.data[0].get("locked_financial_years") or [])
    stored_hash = _stored_pin_hash(db, firm_id)
    pin_set = stored_hash is not None
    adopted_now = False

    if not bypass_pin:
        if pin_set:
            if not pin:
                # Nothing was put to the comparison, so nothing is counted.
                raise HTTPException(status_code=403, detail="Incorrect lock PIN.")
            _spend_pin_attempt(firm_id, actor_id)
            verdict = lock_pin.verify(pin, stored_hash)
            if not verdict.ok:
                log_event(
                    firm_id, "firm", firm_id, "year_lock_pin_refused",
                    actor_id=actor_id, actor_email=actor_email,
                    new_data={"financial_year": financial_year, "lock": lock},
                )
                raise HTTPException(status_code=403, detail="Incorrect lock PIN.")
            if verdict.needs_rehash:
                _upgrade_stored_hash(db, firm_id, stored_hash, pin)
        elif pin:
            # First lock: adopt the supplied PIN for future lock/unlock actions.
            problem = lock_pin.problem_with(pin)
            if problem:
                raise HTTPException(status_code=422, detail=problem)
            _adopt_pin(db, firm_id, pin)
            pin_set = True
            adopted_now = True

    if lock:
        if financial_year not in current:
            current.append(financial_year)
    else:
        current = [fy for fy in current if fy != financial_year]

    upd = (db.table("firms").update({"locked_financial_years": current})
           .eq("id", firm_id).execute())
    if not upd.data:
        raise HTTPException(status_code=404, detail="Firm not found")

    new_data: dict = {"financial_year": financial_year, "locked_financial_years": current}
    if adopted_now:
        # That a PIN was set by this request is worth the trail; the PIN itself, or anything made from it, is not.
        new_data["pin_set"] = True
    log_event(
        firm_id, "firm", firm_id,
        "year_lock" if lock else "year_unlock",
        actor_id=actor_id, actor_email=actor_email,
        new_data=new_data,
    )
    _logger.info("FY %s %s for firm %s", financial_year, "locked" if lock else "unlocked", firm_id)
    return {"locked_financial_years": current, "pin_set": pin_set}


def _adopt_pin(db, firm_id: str, pin: str) -> None:
    """Store the first PIN a firm sets. Two requests racing to set one: the loser is told, not overwritten."""
    try:
        db.table("firm_lock_pins").insert({
            "firm_id": firm_id,
            "pin_hash": lock_pin.hash_pin(pin),
        }).execute()
    except Exception as exc:  # noqa: BLE001 - PostgREST raises its own APIError; the code is what matters
        text = f"{getattr(exc, 'code', '')} {exc}".lower()
        if "23505" in text or "duplicate key" in text:
            raise HTTPException(
                status_code=409,
                detail="A lock PIN was set a moment ago. Enter that PIN and try again.",
            ) from exc
        raise


def _upgrade_stored_hash(db, firm_id: str, old_hash: str, pin: str) -> None:
    """Rewrite a hash made by an older scheme from the PIN just verified. Fail soft: the PIN still works."""
    try:
        (db.table("firm_lock_pins")
         .update({"pin_hash": lock_pin.hash_pin(pin),
                  "updated_at": datetime.now(timezone.utc).isoformat()})
         .eq("firm_id", firm_id).eq("pin_hash", old_hash).execute())
    except Exception as exc:  # noqa: BLE001 - never fail a lock over the upgrade of how its PIN is stored
        capture_soft_failure(exc, operation="year_lock.pin_rehash", firm_id=firm_id)


# ── Client-scoped locks (migration 289) ──────────────────────────────────────
#
# A firm lock (above) is a deliberate practice-wide decision behind the lock
# PIN. A CLIENT lock closes one accounting entity's year, which is what
# finalising that client's year-end engagement actually means. Finalising used
# to write a FIRM lock, so one client's year-end stopped posting for every
# other client in the practice.
#
# Both are enforced: a posting is refused if either applies.

def is_client_year_locked(db, firm_id: str, client_id: str,
                          financial_year: str) -> bool:
    """True when this client's financial year is closed."""
    if not (firm_id and client_id and financial_year):
        return False
    resp = (db.table("client_year_locks").select("id")
            .eq("firm_id", firm_id)
            .eq("client_id", client_id)
            .eq("financial_year", financial_year)
            .limit(1).execute())
    return bool(resp.data)


def set_client_lock(db, firm_id: str, client_id: str, financial_year: str,
                    lock: bool, actor_id: Optional[str] = None,
                    actor_email: Optional[str] = None,
                    reason: Optional[str] = None,
                    actor_auth_id: Optional[str] = None) -> dict:
    """Lock or unlock ONE client's financial year. Idempotent and audited.

    No PIN: the firm PIN guards practice-wide locks, and this closes a single
    entity's year on the authority of the Partner-gated workflow that calls it.

    TWO ACTOR IDS, BECAUSE THEY GO TO DIFFERENT PLACES.
        `actor_id` is the INTERNAL public.users.id and is the only one that may
        reach `locked_by`, which references users(id) (migration 289 above).
        `actor_auth_id` is the Supabase auth id and is used only for audit_log
        attribution, exactly as journal_posting_service.post_draft splits them.

        Both callers passed current_user["auth_user_id"] for `actor_id`, and
        production holds no user whose users.id equals their auth id — so the
        INSERT violated the FK, the exception propagated out of
        lock_year_if_completing, and the status row had ALREADY been written.
        The engagement went to "locked" (terminal, and until now unreopenable)
        while the client's year stayed open. Latent only because production has
        no year-end engagements yet; the identical bug was found and fixed once
        already in banking.py's column-mapping save.
    """
    already = is_client_year_locked(db, firm_id, client_id, financial_year)
    if lock and not already:
        db.table("client_year_locks").insert({
            "firm_id": firm_id,
            "client_id": client_id,
            "financial_year": financial_year,
            "locked_by": actor_id,
            "reason": reason,
        }).execute()
    elif not lock and already:
        (db.table("client_year_locks").delete()
         .eq("firm_id", firm_id)
         .eq("client_id", client_id)
         .eq("financial_year", financial_year).execute())

    if lock != already:
        log_event(
            firm_id, "client_year_lock", client_id,
            "lock" if lock else "unlock",
            actor_id=actor_auth_id or actor_id, actor_email=actor_email,
            new_data={"financial_year": financial_year, "reason": reason},
        )
    return {"financial_year": financial_year, "locked": lock}
