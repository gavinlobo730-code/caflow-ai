"""Fetches what `domain/onboarding/first_run` needs to say which of a new firm's
first four steps are done (market_and_trust-16). It decides nothing.

SERVICE ROLE, WITH THE FIRM FILTER ON EVERY QUERY. `users` shows a caller only their
own row under their own JWT, so the one question the card asks of it — "is there a
second person in this firm" — cannot be answered as the caller. The service role
bypasses RLS, so the `.eq("firm_id", …)` on each read is the isolation, and a test
seeds a second firm's rows to prove it.

ONE ROW EACH, NOT A COUNT AND NOT A LIST. Every step is a question of "is there at
least one", and the earliest qualifying row's `created_at` is also the answer to
"when". So each read is `ORDER BY created_at LIMIT 1` — what crosses the wire is
proportional to the four answers, never to a firm's invoices. The exception is `users`,
where the second ACTIVE person is wanted and a deactivated one must not count, so up
to fifty rows are read and filtered here: a practice's team is small, and the read is
still bounded.

A READ THAT FAILS IS NOT A STEP THAT IS NOT DONE. Each fact is read on its own and a
failure becomes `Fact(None)` with a warning in the log, so one broken table cannot
blank the rest of the card or turn into a confident "you have not done this".
"""
from __future__ import annotations

import logging
import os
from typing import Callable, Optional

from domain.onboarding import first_run as rule
from core import db_provider

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_log = logging.getLogger("caflow.onboarding")

# A team is a handful of people; this bounds the read, it is not a limit on the firm.
_USER_READ_LIMIT = 50


_db = db_provider.service_db


def _client_fact(db, firm_id: str) -> rule.Fact:
    # Guardrail G2: the firm's own practice record is not a client the firm onboarded.
    rows = (db.table("clients").select("id, created_at")
            .eq("firm_id", firm_id).eq("is_internal", False).is_("deleted_at", None)
            .order("created_at").limit(1).execute().data) or []
    return rule.Fact(True, rows[0].get("created_at")) if rows else rule.Fact(False)


def _invoice_fact(db, firm_id: str) -> rule.Fact:
    # ISSUED, and raised HERE: a draft is not yet an invoice, and an opening-balance
    # document is the old system's invoice carried over (migration 391's is_opening),
    # which the CA did not raise. `is_opening` is named in the projection and
    # filtered in the QUERY, because with LIMIT 1 a carried-over row sorting first
    # would otherwise hide every real invoice behind it.
    rows = (db.table("client_sales_invoices").select("id, created_at, status, is_opening")
            .eq("firm_id", firm_id).eq("is_opening", False).neq("status", "draft")
            .is_("deleted_at", None).order("created_at").limit(1).execute().data) or []
    return rule.Fact(True, rows[0].get("created_at")) if rows else rule.Fact(False)


def _statement_fact(db, firm_id: str) -> rule.Fact:
    rows = (db.table("bank_statements").select("id, created_at")
            .eq("firm_id", firm_id).order("created_at").limit(1).execute().data) or []
    return rule.Fact(True, rows[0].get("created_at")) if rows else rule.Fact(False)


def _colleague_fact(db, firm_id: str) -> rule.Fact:
    # An invite is a `users` row (status 'invited') from the moment it is sent, so
    # "invited or joined" is "a second row that has not been deactivated".
    rows = (db.table("users").select("id, created_at, is_active")
            .eq("firm_id", firm_id).is_("deleted_at", None)
            .order("created_at").limit(_USER_READ_LIMIT).execute().data) or []
    active = [r for r in rows if r.get("is_active") is not False]
    if len(active) >= 2:
        return rule.Fact(True, active[1].get("created_at"))
    return rule.Fact(False)


def _firm_created_at(db, firm_id: str) -> Optional[str]:
    rows = (db.table("firms").select("id, created_at")
            .eq("id", firm_id).limit(1).execute().data) or []
    return rows[0].get("created_at") if rows else None


def _read(name: str, fn: Callable[[], rule.Fact]) -> rule.Fact:
    try:
        return fn()
    except Exception:  # noqa: BLE001 - one failed read must not blank the others
        _log.warning("caflow.onboarding: could not read %s for the first-run card", name, exc_info=True)
        return rule.Fact(None)


def first_run(firm_id: str) -> dict:
    """The first-run checklist for one firm, as `domain/onboarding/first_run.build`."""
    if _USE_MOCK:
        # No database to ask: every step is unreadable, which hides the card rather
        # than showing a firm four steps it may already have done.
        return rule.build({}, firm_created_at=None)
    db = _db()
    facts = {
        "first_client": _read("clients", lambda: _client_fact(db, firm_id)),
        "first_invoice": _read("invoices", lambda: _invoice_fact(db, firm_id)),
        "first_statement": _read("bank statements", lambda: _statement_fact(db, firm_id)),
        "invite_colleague": _read("team", lambda: _colleague_fact(db, firm_id)),
    }
    created_at: Optional[str] = None
    try:
        created_at = _firm_created_at(db, firm_id)
    except Exception:  # noqa: BLE001 - the time to first value is a nicety
        _log.warning("caflow.onboarding: could not read the firm's created_at", exc_info=True)
    return rule.build(facts, firm_created_at=created_at)
