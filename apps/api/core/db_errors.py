"""Reading what a failed database call says it was (ops-14, ops-21).

Two pieces of new machinery - the scheduler's claim store (jobs/claims.py) and the mail outbox
(services/email_outbox_service.py) - each need to tell ONE failure apart from every other: "this
database does not have the table or function yet". Code and migration deploy on separate tracks
(core/schema_guard.py's header is the history), so there is a window in which the API is live and
a migration is not, and for these two the right behaviour in that window is to carry on the way
the code did before the migration existed, loudly. Every OTHER failure (the database unreachable, a
timeout, a permission refusal) must not be mistaken for it, because treating those as "not there
yet" would turn a lock that cannot be checked into a lock that is open.

`core/exceptions._sqlstate` reads only a five-character SQLSTATE; PostgREST's own codes
(`PGRST202`, `PGRST205`) are longer, so it cannot be reused here.
"""
from __future__ import annotations

import logging
from typing import Optional

_logger = logging.getLogger("caflow.db_errors")

#: PostgREST: the function / the table is not in the schema cache. Postgres: undefined_function,
#: undefined_table.
_MISSING = frozenset({"PGRST202", "PGRST205", "42883", "42P01"})


def error_code(exc: BaseException) -> Optional[str]:
    """The provider's code for a failure - PostgREST's `PGRSTnnn` or a SQLSTATE - or None.

    supabase-py has put it in `.code` and in the first of `.args` (a dict) in different
    versions, so both are read. Never raises: this runs while reporting a failure."""
    try:
        code = getattr(exc, "code", None)
        if isinstance(code, str) and code.strip():
            return code.strip()
        first = (getattr(exc, "args", None) or [None])[0]
        if isinstance(first, dict):
            got = first.get("code")
            if isinstance(got, str) and got.strip():
                return got.strip()
    except Exception:                                           # noqa: BLE001
        # A getter that raises on an exception object built by code that was already failing. Saying so at
        # DEBUG keeps this from being a silent swallow (tests/test_soft_failure_visibility.py ratchets those).
        _logger.debug("could not read an error code off a %s", type(exc).__name__, exc_info=True)
    return None


def is_missing_store(exc: BaseException, *, name: Optional[str] = None) -> bool:
    """True for "the function or table is not in this database" and for nothing else.

    `name` additionally accepts a message that says it could not find that function, for a
    client that reports PostgREST's refusal without its code."""
    if error_code(exc) in _MISSING:
        return True
    if name:
        try:
            text = str(exc).lower()
        except Exception:                                       # noqa: BLE001
            return False
        return "could not find the function" in text and name.lower() in text
    return False
