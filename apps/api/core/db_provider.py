"""The one place a module asks for its database client (engineering-30).

WHAT THIS REPLACES
    Roughly a hundred modules each defined a private function whose whole body was
    `from core.supabase_client import get_supabase; return get_supabase()` — spelled `_db` in
    47 of them, `_get_db` in 36, `_supabase` in 11 and a handful of other names — in five slightly
    different shapes: request-scoped or privileged, with or without a "no database configured
    means None" branch, and four routers that answer 503 instead. A change to how a client is
    obtained (the per-user-JWT cutover, USE_USER_JWT, is the one that happened) was a change to a
    hundred places, and a hundred places is how a hundred and first appears with the wrong one.

    There are now six functions, each named for what it answers, and every module that used to
    carry its own shim binds the name it always had (`_db = db_provider.request_db`) so the tests
    that patch `module._db` are unchanged. `tests/test_one_door_to_the_database_client.py` fails a
    new private accessor, by SHAPE and not by name, so a `_client()` written next year is caught
    the same as a `_db()`.

WHICH ONE
    request_db()          the REQUEST-SCOPED client: with USE_USER_JWT on and a caller token it is a
                          per-user client and RLS applies (core.supabase_client.get_supabase).
                          Right for a read or write done on a caller's behalf.
    service_db()          the PRIVILEGED client, which bypasses RLS whatever USE_USER_JWT says
                          (get_service_supabase). Right where the caller is already authorised by
                          rbac() and a client-scope check, and for jobs, auth and audit writes.
                          The two are not interchangeable: a request-scoped client downgraded to
                          `authenticated` lacks the write grant some privileged paths need
                          (routers/payroll's `_db` says so), and a privileged one where RLS was
                          wanted is a quiet widening of access.
    request_db_or_none()  / service_db_or_none()
                          the same, or None where SUPABASE_URL is unset: mock mode and local
                          development, where a route answers from an in-memory fixture.
    service_db_or_503(detail)
                          the privileged client, or an HTTP 503 carrying `detail` where there is no
                          database. For a route that has no in-memory answer to give (the cheque
                          register, price lists, interest, the credit-ledger opening): saying so is
                          better than a 500 from `None.table(...)`.
    privileged_for(db)    the client a query on a PAYROLL, BANK or DOCUMENT table is made with
                          (POST-A-339): the privileged one wherever a database is configured, and the
                          client the caller handed in only where none is (mock mode, and the tests'
                          doubles, which answer from Python), labelled with the person of the request in
                          flight so the audit triggers still record who made the write
                          (core/acting_client.py, migration 547). A service that takes a `db` parameter
                          from a route cannot know which client it was given; this is how it states,
                          at the query, which one it wants, and
                          `tests/test_a_payroll_bank_or_document_table_is_queried_with_the_privileged_client.py`
                          reads that statement off the source. The caller's firm and client are the
                          caller's to assert BEFORE the query, because the privileged client carries
                          no row security: that is the price of taking the signed-in role's grant on
                          these tables away.

THE LOOKUP IS AT CALL TIME, ON PURPOSE
    Each function imports `core.supabase_client` when it is CALLED, not when this module loads.
    That is what the shims it replaces did, and the suite depends on it: tests patch
    `core.supabase_client.get_supabase` and expect the next call to see the patch, and a module-level
    `from core.supabase_client import get_supabase` here would have bound the real one for good.
"""
from __future__ import annotations

import os


def _configured() -> bool:
    return bool(os.environ.get("SUPABASE_URL"))


def request_db():
    from core.supabase_client import get_supabase
    return get_supabase()


def service_db():
    from core.supabase_client import get_service_supabase
    return get_service_supabase()


def request_db_or_none():
    return request_db() if _configured() else None


def service_db_or_none():
    return service_db() if _configured() else None


def service_db_or_503(detail: str):
    if not _configured():
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail=detail)
    return service_db()


def privileged_for(db):
    client = service_db_or_none()
    if client is None:
        return db
    from core.acting_client import acting_as_request_person
    return acting_as_request_person(client)
