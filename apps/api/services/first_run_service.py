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
from core.db_provider import privileged_for

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


def _invoice_fact(db, firm_id: str, practice: Optional[str] = None) -> rule.Fact:
    # ISSUED, and raised HERE: a draft is not yet an invoice, and an opening-balance
    # document is the old system's invoice carried over (migration 391's is_opening),
    # which the CA did not raise. `is_opening` is named in the projection and
    # filtered in the QUERY, because with LIMIT 1 a carried-over row sorting first
    # would otherwise hide every real invoice behind it.
    #
    # NOT THE FIRM'S OWN FEE BILL (POST-A-533). The step is "an invoice for a client", and since fees are billed from My
    # practice on this same table (POST-B-193) a fee bill would tick it for a firm that has raised nothing for any client.
    # The practice's own record is left out here, in the query, and its fee bill is the practice list's own step.
    q = (db.table("client_sales_invoices").select("id, created_at, status, is_opening, client_id")
         .eq("firm_id", firm_id).eq("is_opening", False).neq("status", "draft")
         .is_("deleted_at", None))
    if practice:
        q = q.neq("client_id", practice)
    rows = q.order("created_at").limit(1).execute().data or []
    return rule.Fact(True, rows[0].get("created_at")) if rows else rule.Fact(False)


def _statement_fact(db, firm_id: str, practice: Optional[str] = None) -> rule.Fact:
    # A client's statement: the firm's own is the practice list's step (see `_invoice_fact`).
    q = (privileged_for(db).table("bank_statements").select("id, created_at, client_id")
         .eq("firm_id", firm_id))
    if practice:
        q = q.neq("client_id", practice)
    rows = q.order("created_at").limit(1).execute().data or []
    return rule.Fact(True, rows[0].get("created_at")) if rows else rule.Fact(False)


# ── the firm's own practice (POST-A-533) ──────────────────────────────────────────────────────────────────────────────
# Every read names the firm AND the practice's own record. A firm whose practice is not set up has done none of the
# three steps that need its books, and that is a FACT (False), not an unknown: nothing can exist for a record that does not.

def _practice_identity_fact(db, firm_id: str, practice: Optional[str]) -> rule.Fact:
    if not practice:
        return rule.Fact(False)
    rows = (db.table("clients").select("id, created_at, pan")
            .eq("firm_id", firm_id).eq("id", practice).eq("is_internal", True)
            .limit(1).execute().data) or []
    # Set up, with the PAN its books were made from. A record with no PAN is not one whose details can be checked.
    if rows and rows[0].get("pan"):
        return rule.Fact(True, rows[0].get("created_at"))
    return rule.Fact(False)


def _practice_books_fact(db, firm_id: str, practice: Optional[str]) -> rule.Fact:
    if not practice:
        return rule.Fact(False)
    # The first entry of any kind: opening balances, an imported trial balance, a journal, or the posting of a first bill.
    rows = (db.table("journal_entries").select("id, created_at")
            .eq("firm_id", firm_id).eq("client_id", practice).is_("deleted_at", None)
            .order("created_at").limit(1).execute().data) or []
    return rule.Fact(True, rows[0].get("created_at")) if rows else rule.Fact(False)


def _practice_statement_fact(db, firm_id: str, practice: Optional[str]) -> rule.Fact:
    if not practice:
        return rule.Fact(False)
    rows = (privileged_for(db).table("bank_statements").select("id, created_at")
            .eq("firm_id", firm_id).eq("client_id", practice)
            .order("created_at").limit(1).execute().data) or []
    return rule.Fact(True, rows[0].get("created_at")) if rows else rule.Fact(False)


def _practice_fee_bill_fact(db, firm_id: str, practice: Optional[str]) -> rule.Fact:
    if not practice:
        return rule.Fact(False)
    # Issued, and raised here: the same rule as a client's first invoice, on the practice's own record.
    rows = (db.table("client_sales_invoices").select("id, created_at, status, is_opening")
            .eq("firm_id", firm_id).eq("client_id", practice).eq("is_opening", False).neq("status", "draft")
            .is_("deleted_at", None).order("created_at").limit(1).execute().data) or []
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


def _dismissed(db, firm_id: str, user_id: Optional[str]) -> Optional[bool]:
    """Whether THIS person dismissed the card for good: True / False, or None when it could not be read (which is not a dismissal)."""
    if not user_id:
        return None
    rows = (db.table("users").select("first_run_dismissed_at")
            .eq("id", user_id).eq("firm_id", firm_id).limit(1).execute().data) or []
    if not rows:
        return None
    return rows[0].get("first_run_dismissed_at") is not None


def first_run(firm_id: str, user_id: Optional[str] = None, *, for_partner: bool = False) -> dict:
    """The first-run checklist for one firm as `user_id` sees it, as `domain/onboarding/first_run.build`.

    `for_partner` is the CALLER's to say (the route knows the role): the firm's own practice is the Partner's alone, so
    its steps are read and sent for a Partner and for nobody else."""
    if _USE_MOCK:
        # No database to ask: every step is unreadable, which hides the card rather
        # than showing a firm four steps it may already have done.
        return rule.build({}, firm_created_at=None, practice_facts={} if for_partner else None)
    db = _db()
    # Which record is the practice's own. A read that fails leaves the practice list unreadable and, for the two client
    # steps that must leave the practice out, unreadable too: counting the firm's own fee bill as a client's invoice
    # would be a tick nobody earned.
    practice: Optional[str] = None
    practice_known = True
    try:
        from services.internal_client_service import get_internal_client_id
        practice = get_internal_client_id(firm_id)
    except Exception:  # noqa: BLE001 - reported as unreadable steps, never as a guess
        practice_known = False
        _log.warning("caflow.onboarding: could not read which record is the practice's own", exc_info=True)
    unknown = rule.Fact(None)
    facts = {
        "first_client": _read("clients", lambda: _client_fact(db, firm_id)),
        "first_invoice": _read("invoices", lambda: _invoice_fact(db, firm_id, practice)) if practice_known else unknown,
        "first_statement": _read("bank statements", lambda: _statement_fact(db, firm_id, practice)) if practice_known else unknown,
        "invite_colleague": _read("team", lambda: _colleague_fact(db, firm_id)),
    }
    practice_facts = None
    if for_partner:
        practice_facts = {} if not practice_known else {
            "practice_identity": _read("the practice's record", lambda: _practice_identity_fact(db, firm_id, practice)),
            "practice_books": _read("the practice's books", lambda: _practice_books_fact(db, firm_id, practice)),
            "practice_statement": _read("the practice's bank statements", lambda: _practice_statement_fact(db, firm_id, practice)),
            "practice_fee_bill": _read("the practice's fee bills", lambda: _practice_fee_bill_fact(db, firm_id, practice)),
        }
    created_at: Optional[str] = None
    try:
        created_at = _firm_created_at(db, firm_id)
    except Exception:  # noqa: BLE001 - the time to first value is a nicety
        _log.warning("caflow.onboarding: could not read the firm's created_at", exc_info=True)
    dismissed: Optional[bool] = None
    try:
        dismissed = _dismissed(db, firm_id, user_id)
    except Exception:  # noqa: BLE001 - an unread dismissal leaves the card to its steps, and says so
        _log.warning("caflow.onboarding: could not read whether the caller dismissed the first-run card", exc_info=True)
    return rule.build(facts, firm_created_at=created_at, dismissed=dismissed,
                      practice_facts=practice_facts, practice_client_id=practice if for_partner else None)
