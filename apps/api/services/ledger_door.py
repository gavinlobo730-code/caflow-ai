"""The one place the two database functions that write the ledger are called from (POST-A-317).

`post_journal_atomic` (the posting kernel) and `settle_receipt_atomic` (a plain rupee customer receipt) are the database's ledger
writers. Today every signed-in user can execute both over PostgREST with their own token, and the only thing that stands between a
member who holds ONE posting permission and any balanced entry for a client they reach, with any `source_type`, `status`,
`created_by` or `posted_by`, is a union of role pairs in the function's wrapper (migration 533). The API calls them through THIS
module instead: the privileged client, after the route's own checks (the role pair the route asked through `rbac()` and the caller's
access to the client, which every route that posts proves before it posts; see
`tests/test_a_route_that_asserts_the_client_it_was_given_acts_only_on_a_row_of_that_client.py` and the posting-route map of
24-10-2026), so the database function becomes the second lock and not the only one. Migration 546 is the change that then takes the
signed-in role's EXECUTE away; it is not built yet, and this module is shipped first because the API running against a revoked
grant fails soft and wrong.

THIS NEEDS MIGRATION 545 ON THE DATABASE IT TALKS TO. The wrappers of 545 read the carried person and remove the reserved
`audit_actor` key before the unguarded body, which builds its column list from the entry's keys; against a database without 545 every
posting from a request with a verified person would fail. The order of the rollout is 545, this change, then 546.

WHAT THE PRIVILEGED CALL KEEPS. The two wrappers still ask the closure (`period_closure_reason`: the firm's locked year and the
client's finalised year-end), the reversal's ownership and the receipt-and-journal agreement for every caller, the service role
included. What they do not ask of the service role is the caller's firm, client reach and role pair, because there is no caller. From
this deploy until 546 the database therefore no longer asks, of an API posting, that the client in the payload belongs to the firm in
the payload (`assert_caller_acts_for` asked it of the signed-in caller); this module asks that the payload names the firm and client
the route proved, and the route's own checks are the lock. Migration 546 is to ask the database the same of a privileged caller.

WHO POSTED. The audit triggers (migrations 111, 336 and 266) record a write only when `auth.uid()` is set, which the privileged
client never has, so the person travels in the payload instead: `audit_actor`, the auth id of the person this request is, as
`core.auth.get_current_user` verified it and recorded it (`core/request_actor.py`; the token is not decoded a second time). It is a
label and not a credential: migration 545 checks the person is a member of the entry's own firm before it believes it, and removes
the key before the unguarded body. The key is the DOOR'S: a value a caller put in the entry is removed and only the verified person is
put back, so a payload can never name its own actor. A job has no request and sends none; it is audited as the person in `created_by`
where there is one, and as nobody otherwise, which is what it always was. A manual run of the daily batch happens inside the request
of the person who pressed it, and is audited as that person. Most of the `journal_for_*` helpers that post a document's entry pass no
`created_by` at all, which is why the actor cannot ride on it.

A POSTING NAMES ITS FIRM AND ITS CLIENT. This refuses an empty one before the privileged client is used at all: `can_access_client`
answers True for no client (a firm-level resource has none to check), which is the one value a scope check must not be handed here.

Where there is no database configured (mock mode, local development, the in-memory test doubles) the client the caller already
holds is returned and the payload is left exactly as it was: it IS the double.
"""
from __future__ import annotations

import os

from core import db_provider

#: the payload each function reads the posting person from, and where the reserved key goes
_ENTRY_KEY = {"post_journal_atomic": "p_entry", "settle_receipt_atomic": "p_journal_entry"}
AUDIT_ACTOR_KEY = "audit_actor"


def door_words() -> str:
    """Who calls the two ledger functions in THIS process, in one word, for `/health`: `server` when a database is configured and the
    privileged client does the calling, `caller` when there is none (mock mode, local development) and the client the caller already
    holds is the double. A fact about the process's configuration that touches no network, so the route stays cheap; it is how a
    deployment is shown to be running this door before migration 546 takes the signed-in grant away, when no posting has happened
    for the audit log to show it."""
    return "server" if os.environ.get("SUPABASE_URL") else "caller"


def ledger_client(db, *, firm_id: str, client_id: str):
    """The client the ledger RPCs are called with: the privileged one where there is a database, else `db`."""
    if not firm_id or not client_id:
        raise ValueError("A posting names its firm and its client: refusing to call the ledger without both.")
    return db_provider.service_db_or_none() or db


def ledger_rpc(db, fn: str, params: dict, *, firm_id: str, client_id: str):
    """`<client>.rpc(fn, params)` for one of the two ledger functions, on the privileged client, carrying the posting person.

    Returns the request builder, so the caller keeps its own `.execute()` and its own handling of what comes back."""
    if fn not in _ENTRY_KEY:
        raise ValueError(f"{fn} is not a ledger function: refusing to call it through the ledger door.")
    client = ledger_client(db, firm_id=firm_id, client_id=client_id)
    entry = params.get(_ENTRY_KEY[fn]) or {}
    if str(entry.get("firm_id") or "") != str(firm_id) or str(entry.get("client_id") or "") != str(client_id):
        # The firm and client a caller names are the scope its route proved; the payload is what is posted. They must be one scope.
        raise ValueError("The ledger door was told one firm and client and the payload names another: refusing to post.")
    if db_provider.service_db_or_none() is not None:
        from core.request_actor import current_auth_user_id
        key = _ENTRY_KEY[fn]
        carried = {k: v for k, v in params[key].items() if k != AUDIT_ACTOR_KEY}     # the key is the door's: never one a caller wrote
        if current_auth_user_id():
            carried[AUDIT_ACTOR_KEY] = current_auth_user_id()
        params = {**params, key: carried}
    # The two names are spelt out, not passed on as a variable: the scanners that police who calls the ledger-writing functions
    # (tests/test_the_hero_figures_are_counted_facts.py, tests/test_backend_tables_exist_pg.py) read literals.
    if fn == "post_journal_atomic":
        return client.rpc("post_journal_atomic", params)
    return client.rpc("settle_receipt_atomic", params)
