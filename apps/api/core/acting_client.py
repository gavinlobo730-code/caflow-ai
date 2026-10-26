"""The privileged client, with every statement it makes labelled with the person the request acts for (POST-A-339, migration 547).

WHY IT EXISTS
    The row-level edit log is written by triggers that record a write only when someone is signed in. A write the API makes with its
    PRIVILEGED client has no `auth.uid()`, so before this the payroll, bank and document tables' triggers recorded nothing for it:
    production holds 492 bank-line creates and 789 updates written by the trigger in 120 days against 58 written by the application.
    Migration 547 lets the one reader both audit triggers ask (`carried_audit_actor()`) take the person from a request header, and
    only on a request that runs as `service_role`. This module is the sender: `ActingClient` wraps the privileged client so that each
    statement it builds carries `x-acting-auth-user: <the auth id the authentication dependency verified for this request>`.

WHAT IT DOES AND DOES NOT DO
    * The label is the person of THIS request (`core.request_actor`, which the authentication dependency fills in after it has verified
      the token; the token is not decoded a second time). A job has no request and no person, so no label is sent and nothing is
      carried, which is what a job's audit has always been.
    * It labels a statement; it adds no filter and removes none. The privileged client carries no row security, and what the signed-in
      role's policies used to narrow (the firm, the client assignment, the role tier) is the route's to assert before the query.
    * It touches only what the builder offers: `table`/`from_`, `rpc`, and the five verbs. Anything else (`storage`, `auth`) is the
      wrapped client's own, unchanged.
    * It cannot make a statement more privileged than the client it wraps, and a signed-in session can neither send this header
      successfully nor become `service_role` to make it count (the database believes it only on a service-role request).

THE TWO NAMES THAT HAVE TO AGREE
    `ACTING_HEADER` is the lower-case header name migration 547's reader looks for in `request.headers`, and
    `tests/test_the_acting_client_labels_what_the_server_writes_for_a_person.py` reads the migration and pins them together.
"""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Optional

#: The request header migration 547's `carried_audit_actor()` reads. PostgREST lower-cases header names in `request.headers`.
ACTING_HEADER = "x-acting-auth-user"

_VERBS = ("select", "insert", "upsert", "update", "delete")


def _label(builder: Any, who: str) -> Any:
    """Put the label on a request builder, if it has headers to put it on (a test double may not). Every later method of the builder
    (`eq`, `order`, `single`, `maybe_single`, ...) returns the same builder or one made from its headers, so the label stays."""
    headers = getattr(builder, "headers", None)
    if isinstance(headers, MutableMapping):         # a double whose headers are not a mapping simply does not send the label
        headers[ACTING_HEADER] = who
    return builder


class _ActingTable:
    """What `client.table(name)` returns: the five verbs build the real request, then label it."""

    __slots__ = ("_inner", "_who")

    def __init__(self, inner: Any, who: str) -> None:
        self._inner = inner
        self._who = who

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if name in _VERBS and callable(attr):
            def verb(*args: Any, **kwargs: Any) -> Any:
                return _label(attr(*args, **kwargs), self._who)
            return verb
        return attr


class ActingClient:
    """The privileged client, labelling each statement with the person the request acts for."""

    __slots__ = ("_client", "_who")

    def __init__(self, client: Any, auth_user_id: str) -> None:
        self._client = client
        self._who = auth_user_id

    def table(self, name: str) -> Any:
        return _ActingTable(self._client.table(name), self._who)

    def from_(self, name: str) -> Any:
        return _ActingTable(self._client.from_(name), self._who)

    def rpc(self, fn: str, params: Optional[dict] = None, *args: Any, **kwargs: Any) -> Any:
        return _label(self._client.rpc(fn, params, *args, **kwargs), self._who)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def acting_as_request_person(client: Any) -> Any:
    """`client`, wrapped to label its statements with the person of the request in flight; `client` itself where there is none (a job)."""
    from core.request_actor import current_auth_user_id
    who = current_auth_user_id()
    return ActingClient(client, who) if who else client
