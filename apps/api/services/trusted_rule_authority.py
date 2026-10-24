"""A trusted rule posts only while the person who trusted it could still let it (ledger POST-A-339).

WHY THIS EXISTS
    A trusted bank rule passes entries without a click, and what it posts is credited to the person who trusted it:
    `journal_entries.created_by` is `rule.trusted_by` and the line is stamped with the rule (`bank_entry_service.pass_ready`). The
    design's whole ground for acting unprompted is that a NAMED PERSON ANSWERS for it. Promoting needed `banking:approve` and a
    Manager's seat, and was asked once, at the moment the rule was trusted. Nothing asked it again when the sweep ran, so a member
    who was un-assigned from the client, suspended, demoted to an Executive or had Banking blocked on the Team screen after
    trusting a rule left a rule that kept posting under their name, daily, from the scheduler running as the server.

WHAT IT ASKS, EVERY TIME THE RULES ARE READ
    Whether the firm is still there (a suspended or soft-deleted firm blocks every one of its members at sign-in, so no member of it
    can post, and a rule credited to one of them must not either); whether the person is still a member of the firm and not suspended; still holds `banking:approve` (what let them trust a rule)
    and `banking:write` (what posting is) under the per-person grid, which is the rule `rbac()` applies to a request; and still
    reaches the client (a Partner reaches every client of the firm, anyone else needs an assignment). `core.permissions.
    resolve_permission` and `core.authz.is_client_assigned` are the same functions a request is judged by, so a person is not
    answerable under one rule and refused under another.

    BOTH PAIRS, and not only `banking:write` as the ledger line first said: a Manager demoted to an Executive still holds
    `banking:write` (an Executive writes banking), so write alone would have let a demoted person's rule keep posting. `approve` is
    the one that went with the seat.

WHAT HAPPENS TO A RULE THAT FAILS
    It is left out of the set of trusted rules, which is what `counts()` (the screen's "trusted pending") and `pass_ready` (the
    sweep and the screen's progress bar) both read, so the lines it drafted stay READY in the review queue for a person to pass,
    the screen's number and the sweep agree, and the run's result NAMES the rule and the reason. The rule row itself is not
    changed: a Partner re-trusting it, or the person getting their access back, is what puts it back. An answer that cannot be
    established (the read failed) is a refusal too, never a pass.

WHO IS TOLD WHY
    The reason a rule is waiting names a colleague's suspension or removal, which the Team screen shows only to those who hold
    `team:read`. The run's summary (read by a Partner) and the log carry the specific code and sentence; every screen and every
    HTTP answer that any banking user can read carries `WAITING_SENTENCE` and nothing about the person.

THE READS ARE THE SERVER'S
    The privileged client where there is one: a request's own client reads another member's `user_permissions` under row security,
    which would show a signed-in Manager an empty grid for the person who trusted the rule and so fall back to the role, which is
    to say fail open.
"""
from __future__ import annotations

import logging
from typing import NamedTuple, Optional

from core import authz, db_provider
from core.observability import capture_soft_failure
from core.permissions import canonical_role, resolve_permission

_logger = logging.getLogger("caflow.bank.trusted_rule_authority")

#: What the person must still hold. `approve` is what let them trust a rule (the role template says a Manager or above); `write` is
#: what a posting is.
REQUIRED = (("banking", "approve"), ("banking", "write"))


class Gap(NamedTuple):
    """Why a trusted rule may not post this time: a code a program can group by and a sentence a person can read."""
    code: str
    sentence: str


#: What a screen or an HTTP answer says of a rule that is waiting, whatever the reason: it names no person and no status.
WAITING_SENTENCE = ("Waiting: the person who trusted this rule can no longer let rules pass by themselves. "
                    "A Manager or Partner can trust it again.")

FIRM_UNAVAILABLE = Gap("firm_unavailable", "The firm is suspended or no longer available, so none of its members can post.")
NO_ONE = Gap("no_one_answers",
             "No person is recorded as having trusted this rule, so nobody answers for what it would post.")
NOT_A_MEMBER = Gap("not_a_member", "The person who trusted this rule is no longer a member of the firm.")
SUSPENDED = Gap("suspended", "The person who trusted this rule is suspended.")
NO_ROLE = Gap("no_role", "The person who trusted this rule no longer has a role in the firm.")
CANNOT_TRUST = Gap("cannot_trust",
                   "The person who trusted this rule no longer holds the Banking approval that lets a rule post by itself.")
CANNOT_POST = Gap("cannot_post", "The person who trusted this rule no longer holds the Banking access that posting needs.")
NOT_ASSIGNED = Gap("not_assigned", "The person who trusted this rule is no longer assigned to this client.")
UNREADABLE = Gap("unreadable",
                 "Whether the person who trusted this rule may still post could not be checked just now, so the rule waits.")

CODES = (NO_ONE.code, FIRM_UNAVAILABLE.code, NOT_A_MEMBER.code, SUSPENDED.code, NO_ROLE.code, CANNOT_TRUST.code, CANNOT_POST.code,
         NOT_ASSIGNED.code, UNREADABLE.code)


class Verdict(NamedTuple):
    """The answer for one person: why a rule they trusted may not post (None when it may), and, once the person is found, their
    AUTH id, which is what the audit log names an actor by (`audit_log.actor_id` is the auth id, `journal_entries.created_by` the
    internal one)."""
    gap: Optional[Gap]
    auth_user_id: Optional[str] = None


def verdict(db, firm_id: str, client_id: str, trusted_by: Optional[str]) -> Verdict:
    """Whether the person who trusted a rule still answers for it, and who they are to the audit log."""
    if not trusted_by:
        return Verdict(NO_ONE)
    try:
        # obtaining the privileged client is part of the check: a client that cannot be built is a check that cannot be made
        reader = db_provider.service_db_or_none() or db
        return _verdict(reader, str(firm_id), str(client_id), str(trusted_by))
    except Exception as exc:       # a check that cannot be made is a refusal, and it is reported, not swallowed
        _logger.exception("trusted-rule authority could not be read for firm %s client %s", firm_id, client_id)
        capture_soft_failure(exc, operation="trusted_rule_authority")
        return Verdict(UNREADABLE)


def authority_gap(db, firm_id: str, client_id: str, trusted_by: Optional[str]) -> Optional[Gap]:
    """None when the person who trusted a rule still answers for it; otherwise why not."""
    return verdict(db, firm_id, client_id, trusted_by).gap


def _firm_gap(reader, firm_id: str) -> Optional[Gap]:
    """What `core.auth.get_current_user` asks of the firm before it lets any member in: not soft-deleted, not suspended."""
    rows = (reader.table("firms").select("id, is_active, deleted_at").eq("id", firm_id).limit(1).execute().data) or []
    firm = rows[0] if rows else None
    if firm and (firm.get("deleted_at") or firm.get("is_active") is False):     # a row that says so, exactly as the sign-in reads it
        return FIRM_UNAVAILABLE
    return None


def _verdict(reader, firm_id: str, client_id: str, user_id: str) -> Verdict:
    from services.user_permission_service import overrides_for
    firm_gap = _firm_gap(reader, firm_id)
    if firm_gap:
        return Verdict(firm_gap)
    rows = (reader.table("users").select("id, role, is_active, auth_user_id")
            .eq("firm_id", firm_id).eq("id", user_id).limit(1).execute().data) or []
    if not rows:
        return Verdict(NOT_A_MEMBER)
    member = rows[0]
    auth_id = member.get("auth_user_id")
    if member.get("is_active") is False:
        return Verdict(SUSPENDED, auth_id)
    role = canonical_role(member.get("role"))
    if not role:
        return Verdict(NO_ROLE, auth_id)
    overrides = overrides_for(reader, firm_id, user_id)
    for resource, action in REQUIRED:
        if not resolve_permission(role, overrides, resource, action):
            return Verdict(CANNOT_TRUST if action == "approve" else CANNOT_POST, auth_id)
    if authz.is_firmwide({"role": role}):
        return Verdict(None, auth_id)
    return Verdict(None if authz.is_client_assigned(user_id, client_id, firm_id) else NOT_ASSIGNED, auth_id)
