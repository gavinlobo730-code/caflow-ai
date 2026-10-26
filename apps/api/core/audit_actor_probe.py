"""Whether the hosted API passes the acting header through to the database, said by the deployment itself (POST-A-339, migration 547).

WHY IT EXISTS
    Everything that keeps the row-level edit log whole after the payroll, bank and document tables lose the signed-in role's grants rests on
    one fact Python cannot prove from here: that a header the API puts on a request reaches the database as
    `current_setting('request.headers')` through the hosted PostgREST. Migration 547's `audit_actor_probe()` returns what the database
    saw of the request that called it. This module asks it once, at boot, with a label of its own, and `/health` carries the answer, so
    the claim is something a deployment SAYS and a person reads with `curl .../health`, in the way `ledger_door` and `ai` are.

THE WORDS (one of)
    carried    the database saw the label on a request that ran as service_role: the header is forwarded and the audit triggers can
               name the person.
    not_seen   the database answered but saw no label (a proxy dropped it, or the migration is not the one this code expects).
    wrong_role the database saw the label but the request did not run as service_role, so it would not be believed.
    failed     the question could not be asked or its answer could not be read (the function is missing, the database is unreachable).
    unchecked  nothing asked yet, or there is no database (mock mode, local development).

A fact about this process held in memory: `words()` touches no network, so `/health` stays cheap and cannot turn into a 503 because
the probe was slow. The probe itself runs on the boot thread with the rest of the slow half of startup.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from core.acting_client import ActingClient

_logger = logging.getLogger("caflow.audit_actor_probe")

#: What the probe sends as the header. Not a person: the probe function only echoes what it saw.
PROBE_LABEL = "audit-actor-probe"

_state: dict[str, str] = {"words": "unchecked"}


def words() -> str:
    return _state["words"]


def judge(answer: Any) -> str:
    """The word for what `audit_actor_probe()` returned."""
    if not isinstance(answer, dict):
        return "failed"
    if answer.get("header") != PROBE_LABEL:
        return "not_seen"
    if answer.get("role") != "service_role":
        return "wrong_role"
    return "carried"


def run(client: Optional[Any] = None) -> str:
    """Ask the database once and remember the word. Never raises: a failed question is the word `failed`, not a failed boot."""
    if client is None:
        if not os.environ.get("SUPABASE_URL"):
            _state["words"] = "unchecked"
            return "unchecked"
        from core.db_provider import service_db
        client = service_db()
    try:
        data = ActingClient(client, PROBE_LABEL).rpc("audit_actor_probe", {}).execute().data
        _state["words"] = judge(data)
    except Exception:  # noqa: BLE001 - a probe that cannot be answered is reported, and boot goes on
        _logger.exception("the audit actor probe could not be answered")
        _state["words"] = "failed"
    if _state["words"] != "carried":
        _logger.error("audit actor probe says %s: writes the API makes with its privileged client will NOT name the person in the "
                      "edit log until the header reaches the database", _state["words"])
    return _state["words"]
