"""The firm's year-lock PIN: how it is stored, and how it is checked (POST-A-004, migration 480).

WHAT WAS WRONG
    `firms.lock_pin` held the PIN as typed. `public.firms` is readable by every member of the firm
    over PostgREST (migration 033 grants SELECT, UPDATE to `authenticated`, and the role-by-table
    matrix shows a Manager, an Executive and a Reviewer all read the row), so any of them could run
    `select lock_pin from firms` from a browser console, and a Partner's own session could set the
    column to NULL and switch the PIN off. The check itself was `pin != stored_pin`: not constant
    time, and with no limit on how many guesses a four-character PIN would take.

WHAT THIS MODULE IS
    The rule for the stored form and the comparison, and nothing else: no database, no clock, no
    request. `services/year_lock_service` fetches and writes, and it keeps the stored form in
    `public.firm_lock_pins`, a table `authenticated` holds no privilege on at all. The access is the
    fix; the hash is what is left on disk if someone with a backup reads it.

    A salted hash of a four-character PIN is brute-forced in seconds by anyone who can read it, so
    hashing alone would have fixed almost nothing while the column stayed browser-readable. That is
    why the column is emptied and the hash lives where no signed-in session can reach.

TWO SCHEMES, AND WHY THERE ARE TWO
    `pbkdf2_sha256$<iterations>$<salt>$<hash>` is what this module writes: PBKDF2-HMAC-SHA256 from
    the standard library (OWASP's figure for it is 600,000 iterations, about 0.4 s here, and the
    count is part of the stored string so it can be raised later and an old row upgraded on its next
    successful use).

    `sha256$<salt>$<hash>` is what migration 480 writes for a PIN that already existed. SQL in the
    migration has `sha256()` and `gen_random_uuid()` in core Postgres and no PBKDF2 (pgcrypto is an
    extension that lives in a different schema on Supabase and is not assumed), so a PIN that existed
    when the migration ran is stored with one round of SHA-256 over `salt || pin` and is REWRITTEN
    as PBKDF2 the first time it verifies. Until then it is exactly as strong as the plaintext was,
    behind a wall the plaintext was not.

    Anything else (an unknown scheme, a malformed string, an absurd iteration count) verifies as
    False. A check that cannot understand what it was given fails closed.

WHAT IT DOES NOT DO
    It does not decide who may try, how often, or what happens on a miss: that is the service and the
    limiter. It does not normalise the PIN (no trimming, no case folding, no Unicode normalisation):
    the PIN is compared as typed, which is what the plaintext comparison did and what the SQL
    backfill hashed.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import NamedTuple, Optional

PBKDF2_SCHEME = "pbkdf2_sha256"
#: Written by migration 480 for a PIN that existed before it; understood here and upgraded on use.
LEGACY_SCHEME = "sha256"

#: OWASP's current figure for PBKDF2-HMAC-SHA256. Part of the stored string, so raising it later does
#: not strand a row: `verify` reports `needs_rehash` for any row below this count.
ITERATIONS = 600_000
#: A stored count above this is not something this module wrote; refusing it stops a row from naming an
#: iteration count that would hold a worker for minutes.
MAX_ACCEPTED_ITERATIONS = 10_000_000

SALT_BYTES = 16

#: What a PIN may be when it is SET. The verify path applies neither bound, so a PIN set before this
#: rule existed still opens the year it locked.
MIN_LENGTH = 4
MAX_LENGTH = 128


class Verdict(NamedTuple):
    ok: bool
    #: True when the stored form is understood and correct but is not the one this module would write
    #: now, so the caller should rewrite it from the PIN it was just given.
    needs_rehash: bool


_REJECTED = Verdict(False, False)


def problem_with(pin: object) -> Optional[str]:
    """What is wrong with a PIN someone is SETTING, in a sentence; None when it is acceptable.

    Applied only when a PIN is chosen. It is deliberately not applied when one is checked.
    """
    if not isinstance(pin, str):
        return "The lock PIN must be text."
    if len(pin) < MIN_LENGTH:
        return f"The lock PIN must be at least {MIN_LENGTH} characters."
    if len(pin) > MAX_LENGTH:
        return f"The lock PIN can be at most {MAX_LENGTH} characters."
    if _pin_bytes(pin) is None:
        return "The lock PIN contains a character that cannot be stored."
    return None


def hash_pin(pin: str, *, iterations: Optional[int] = None, salt: Optional[str] = None) -> str:
    """The stored form of a PIN: `pbkdf2_sha256$<iterations>$<salt>$<hex digest>`.

    `iterations` is read at call time, so a test that wants a cheap hash says so and a caller that says
    nothing gets the module's figure."""
    raw = _pin_bytes(pin)
    if raw is None:
        raise ValueError("a PIN that cannot be encoded cannot be stored")
    iterations = ITERATIONS if iterations is None else iterations
    salt = salt or secrets.token_hex(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", raw, salt.encode("ascii"), iterations).hex()
    return f"{PBKDF2_SCHEME}${iterations}${salt}${digest}"


def verify(pin: object, stored: object) -> Verdict:
    """Is `pin` the one `stored` was made from? Never raises; every doubt is a no."""
    if not isinstance(pin, str) or not isinstance(stored, str):
        return _REJECTED
    raw = _pin_bytes(pin)
    if raw is None:
        return _REJECTED
    parts = stored.split("$")
    scheme = parts[0]
    try:
        if scheme == PBKDF2_SCHEME and len(parts) == 4:
            iterations = int(parts[1])
            if not 1 <= iterations <= MAX_ACCEPTED_ITERATIONS:
                return _REJECTED
            salt, expected = parts[2], parts[3]
            computed = hashlib.pbkdf2_hmac("sha256", raw, salt.encode("ascii"), iterations).hex()
            return Verdict(_same(computed, expected), iterations < ITERATIONS)
        if scheme == LEGACY_SCHEME and len(parts) == 3:
            salt, expected = parts[1], parts[2]
            computed = hashlib.sha256(salt.encode("utf-8") + raw).hexdigest()
            return Verdict(_same(computed, expected), True)
    except (ValueError, UnicodeError):
        return _REJECTED
    return _REJECTED


def _same(computed: str, expected: str) -> bool:
    """The one comparison of a digest in this module, and it is constant time."""
    return hmac.compare_digest(computed.encode("utf-8"), expected.encode("utf-8", "replace"))


def _pin_bytes(pin: str) -> Optional[bytes]:
    """The PIN as UTF-8, or None for text that has no UTF-8 form (a lone surrogate)."""
    try:
        return pin.encode("utf-8")
    except UnicodeError:
        return None
