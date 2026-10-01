"""The practice's own mail — who gets it, whether they want it, and the record
that it went (practice_management-02 and -03).

`domain/practice_notices.py` decides the rule (the vocabulary, the defaults, the
dedupe key, the overdue cadence). `services/email_service.py` holds the wording
and the transport. This module is the glue between them and the database, and it
decides nothing statutory.

THE ONE DOOR IS `deliver`, AND IT NEVER RAISES. Every mail in this module goes
through it, so the four guarantees are stated once:

  1. a recipient with no usable address, or who has switched the event off, or
     who is no longer active, is skipped — and a skip is NOT recorded, because
     the log is the record of SENDS and "we did not send" is the absence of a row;
  2. a SWEEP mail is deduplicated against what was already SENT for the same
     (event, address, thing, tier, day), so a sweep run twice sends once — the
     two doors that bypass the scheduler's once-a-day flag included;
  3. a failed attempt is recorded (status `failed`, no dedupe key) and does not
     block a retry;
  4. nothing in here may stop the work that triggered it: assigning a task, or a
     client posting a message, must succeed whether or not the mail does.

WHO A MAIL IS FROM IS DECIDED BY WHO THE SENDER IS (practice_management-04).
A notice to STAFF goes from the product's own sender exactly as it always has —
`test_internal_notifications_are_unchanged` pins that. A notice to a client's
PORTAL CONTACT about the practice's own work (a document request, a message
from the accountant) is the practice writing to its own client, so it carries
the practice's name and a Reply-To that reaches it. Nothing here ever mails a
client's CUSTOMER: an invoice-type mail names the client and has its own path.

STORES. Mock mode (no SUPABASE_URL) keeps the preferences and the log in
process, the way `portal_access_service` keeps its contacts, so the whole flow
runs in the mock suite. Against a database the service role is used and EVERY
query carries `.eq("firm_id", …)`: this module runs from the daily sweep, where
there is no caller's JWT, and from a portal CLIENT's request, whose JWT could
not read `users`, `clients` or the assignment table at all.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable, Optional

from core.ist_clock import ist_today
from core.urls import frontend_base, portal_login_url
from domain import practice_notices as rules
from services import email_service

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.practice_mail")

# Mock stores (mock/dev mode only).
MOCK_PREFERENCES: dict[tuple[str, str], dict] = {}
MOCK_LOG: list[dict] = []

_IN_CHUNK = 150
_DONE_TASK_STATUSES = frozenset({"completed", "cancelled"})

#: The values that switch the practice's own mail ON. Anything else, including
#: the variable being absent, an empty string, "false" and a typo, is OFF.
_SWITCH_ON = frozenset({"1", "true", "yes", "on"})


def mail_enabled() -> bool:
    """Whether this deployment sends the practice's own mail at all.

    `PRACTICE_MAIL_ENABLED` is OFF unless it is explicitly one of 1, true, yes
    or on (case and surrounding spaces ignored). It is read at CALL time, so
    changing it needs no code and a test can flip it. It is the one firm-wide
    switch over everything this module and `portal_notice_service` send: a
    notice to staff about a task or a deadline, an escalation, and a mail to a
    client's portal contact about a document request or a message. Off is what
    the product did before that mail existed (an assignment made an in-app
    notification and nothing more), so switching it off removes a behaviour and
    does not break one.

    It does NOT touch the in-app notifications, which are always created, nor
    the sign-in, invite and engagement mail, which are other things.
    """
    return os.environ.get("PRACTICE_MAIL_ENABLED", "").strip().lower() in _SWITCH_ON


def reset_mock_stores() -> None:  # test helper
    MOCK_PREFERENCES.clear()
    MOCK_LOG.clear()


def _db():
    from core.supabase_client import get_service_supabase
    return get_service_supabase()


# ── preferences ──────────────────────────────────────────────────────────────

def chosen_preferences(firm_id: str, user_id: str) -> dict[str, bool]:
    """The person's EXPLICIT rows only: `{event_type: email_enabled}`."""
    if not user_id:
        return {}
    if _USE_MOCK:
        return {e: bool(r["email_enabled"]) for (u, e), r in MOCK_PREFERENCES.items()
                if u == str(user_id) and r.get("firm_id") == firm_id}
    rows = (_db().table("user_notification_preferences")
            .select("event_type, email_enabled")
            .eq("firm_id", firm_id).eq("user_id", user_id).execute().data) or []
    return {r["event_type"]: bool(r["email_enabled"]) for r in rows
            if isinstance(r.get("event_type"), str)}


def effective_preferences(firm_id: str, user_id: str) -> list[dict]:
    return rules.effective_preferences(chosen_preferences(firm_id, user_id))


def set_preference(firm_id: str, user_id: str, event_type: str, email_enabled: bool) -> dict:
    """Record one person's choice. An event outside the vocabulary is REFUSED
    (ValueError) rather than stored inert: the screen is served the vocabulary,
    so a request naming another one is a bug, not a preference."""
    if not rules.is_known_event(event_type):
        raise ValueError(
            f"{event_type!r} is not an event you can set a mail preference for "
            f"(one of: {', '.join(rules.EVENT_TYPES)}).")
    if not isinstance(email_enabled, bool):
        raise ValueError("email_enabled must be true or false.")
    now = datetime.now(timezone.utc).isoformat()
    row = {"firm_id": firm_id, "user_id": str(user_id), "event_type": event_type,
           "email_enabled": email_enabled, "updated_at": now}
    if _USE_MOCK:
        MOCK_PREFERENCES[(str(user_id), event_type)] = row
        return dict(row)
    # The payload is written out at the call so `tests/_backend_query_parser` can
    # read its keys against the real schema; passing `row` by name would make this
    # write invisible to that check (its unreadable budget is exact).
    _db().table("user_notification_preferences").upsert(
        {"firm_id": firm_id, "user_id": str(user_id), "event_type": event_type,
         "email_enabled": email_enabled, "updated_at": now},
        on_conflict="user_id,event_type").execute()
    return row


# ── the record of sends ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class Ref:
    """What a mail was ABOUT. `tier` tells two mails about one thing apart —
    a deadline's 7-day and 3-day notices are different mails."""
    ref_type: str
    ref_id: str
    tier: Optional[str] = None


def _sent_keys(firm_id: str, keys: list[str]) -> set[str]:
    """Which of these dedupe keys already have a SENT row."""
    if not keys:
        return set()
    if _USE_MOCK:
        wanted = set(keys)
        return {r["dedupe_key"] for r in MOCK_LOG
                if r.get("firm_id") == firm_id and r.get("status") == "sent"
                and r.get("dedupe_key") in wanted}
    found: set[str] = set()
    for i in range(0, len(keys), _IN_CHUNK):
        rows = (_db().table("practice_email_log").select("dedupe_key")
                .eq("firm_id", firm_id).eq("status", "sent")
                .in_("dedupe_key", keys[i:i + _IN_CHUNK]).execute().data) or []
        found |= {r["dedupe_key"] for r in rows if r.get("dedupe_key")}
    return found


def _record(firm_id: str, event_type: str, recipient: dict, email: str, kind: str,
            refs: list[Ref], day: date, status: str, keys: dict[Ref, str],
            detail: Optional[str] = None) -> None:
    if not refs:
        return
    # ONE comprehension with the row written out in it, and the insert below takes
    # that comprehension rather than a name: `tests/_backend_query_parser` reads the
    # keys of a dict literal inside an insert's comprehension against the real
    # schema and cannot read a payload held in a variable.
    def rows():
        return [{
            "firm_id": firm_id,
            "event_type": event_type,
            "recipient_kind": kind,
            "recipient_user_id": recipient.get("id") if kind == "staff" else None,
            "recipient_email": email,
            "ref_type": ref.ref_type,
            "ref_id": ref.ref_id,
            "tier": ref.tier,
            "sent_for_date": day.isoformat(),
            # Only a SENT row carries the key: a failed attempt must never block
            # the retry the unique index would otherwise forbid.
            "dedupe_key": keys.get(ref) if status == "sent" else None,
            "status": status,
            "detail": detail,
        } for ref in refs]

    if _USE_MOCK:
        MOCK_LOG.extend({**r, "created_at": datetime.now(timezone.utc).isoformat()}
                        for r in rows())
        return
    try:
        _db().table("practice_email_log").insert([{
            "firm_id": firm_id,
            "event_type": event_type,
            "recipient_kind": kind,
            "recipient_user_id": recipient.get("id") if kind == "staff" else None,
            "recipient_email": email,
            "ref_type": ref.ref_type,
            "ref_id": ref.ref_id,
            "tier": ref.tier,
            "sent_for_date": day.isoformat(),
            "dedupe_key": keys.get(ref) if status == "sent" else None,
            "status": status,
            "detail": detail,
        } for ref in refs]).execute()
    except Exception:                                           # noqa: BLE001
        # The mail has ALREADY gone. A unique-key collision here means another
        # run recorded the same send first, which is the dedupe doing its job;
        # any other failure is a record that was not kept, not a mail that was
        # not sent, and the work that triggered it must not fail over it.
        _logger.warning("caflow.practice_mail: could not record %d %s send(s) "
                        "for firm %s", len(refs), event_type, firm_id, exc_info=True)


def deliver(firm_id: str, event_type: str, recipient: dict, refs: list[Ref],
            send: Callable[[list[Ref]], bool], *, day: Optional[date] = None,
            kind: str = "staff", dedupe: bool = True) -> str:
    """Send ONE mail to ONE recipient about `refs`, honouring the rules above.

    `send` receives the refs that are still to be said — after deduplication —
    and returns whether the provider accepted the mail. Returns one of
    `sent`, `failed`, `duplicate`, `skipped_no_address`, `skipped_inactive`,
    `skipped_preference` or `skipped_switched_off`. NEVER RAISES.

    THE FIRM-WIDE SWITCH IS ASKED FIRST, before an address, a preference or the
    log: with it off nothing is sent, nothing is recorded (the log is the record
    of SENDS) and `send` is never called. Every mail this module and
    `portal_notice_service` send goes through here, which is what makes one
    check enough.
    """
    if not mail_enabled():
        return "skipped_switched_off"
    try:
        day = day or ist_today()
        email = str(recipient.get("email") or "").strip()
        if not email or "@" not in email:
            return "skipped_no_address"
        if kind == "staff":
            if recipient.get("is_active") is False:
                return "skipped_inactive"
            if not rules.wants_email(
                    event_type, chosen_preferences(firm_id, str(recipient.get("id") or ""))):
                return "skipped_preference"
        keys: dict[Ref, str] = {}
        if dedupe:
            keys = {r: rules.dedupe_key(event_type, email, r.ref_id, r.tier, day)
                    for r in refs}
            already = _sent_keys(firm_id, list(keys.values()))
            refs = [r for r in refs if keys[r] not in already]
        if not refs:
            return "duplicate"
        try:
            ok = bool(send(refs))
            detail = None if ok else "the provider did not accept the mail"
        except Exception as exc:                                # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}"
            _logger.warning("caflow.practice_mail: %s send raised", event_type,
                            exc_info=True)
        status = "sent" if ok else "failed"
        _record(firm_id, event_type, recipient, email, kind, refs, day, status,
                keys, detail)
        return status
    except Exception:                                           # noqa: BLE001
        _logger.warning("caflow.practice_mail: %s delivery failed unexpectedly",
                        event_type, exc_info=True)
        return "failed"


def recent_log(firm_id: str, user_id: str, limit: int = 50) -> list[dict]:
    """The mails sent to THIS person, newest first — "why did I not get it?"."""
    limit = max(1, min(int(limit), 200))
    if _USE_MOCK:
        mine = [r for r in MOCK_LOG if r.get("firm_id") == firm_id
                and r.get("recipient_user_id") == str(user_id)]
        return list(reversed(mine))[:limit]
    return ((_db().table("practice_email_log")
             .select("id, event_type, ref_type, ref_id, tier, sent_for_date, status, created_at")
             .eq("firm_id", firm_id).eq("recipient_user_id", user_id)
             .order("created_at", desc=True).limit(limit).execute().data) or [])


# ── who and what a mail is about ─────────────────────────────────────────────

def _staff_member(firm_id: str, user_id: Optional[str]) -> Optional[dict]:
    if not user_id:
        return None
    from repositories.user_repository import user_repo
    try:
        return user_repo.find_by_id(str(user_id), firm_id=firm_id)
    except Exception:                                           # noqa: BLE001
        return None


def client_names(firm_id: str, client_ids: Iterable[str]) -> dict[str, str]:
    """id -> the client's display name, service role, firm-scoped."""
    wanted = sorted({str(c) for c in client_ids if c})
    if not wanted:
        return {}
    if _USE_MOCK:
        from mock_data import CLIENT_INDEX
        return {c: (CLIENT_INDEX.get(c) or {}).get("client_name") or "your client"
                for c in wanted if (CLIENT_INDEX.get(c) or {}).get("firm_id") in (None, firm_id)}
    out: dict[str, str] = {}
    for i in range(0, len(wanted), _IN_CHUNK):
        rows = (_db().table("clients").select("id, client_name, legal_name")
                .eq("firm_id", firm_id).in_("id", wanted[i:i + _IN_CHUNK])
                .execute().data) or []
        for r in rows:
            out[str(r["id"])] = r.get("client_name") or r.get("legal_name") or "a client"
    return out


def practice_sender(firm_id: str) -> tuple[Optional[str], Optional[str]]:
    """(name, contact email) of the PRACTICE, each None where not recorded.

    The practice writing to its own client goes out under the practice's name
    and a reply reaches `firms.email` (migration 003, NOT NULL). A failed read
    or a blank value is None and the mail goes as the product's default sender
    rather than failing over a header.
    """
    if _USE_MOCK:
        return None, None
    try:
        r = (_db().table("firms").select("name, email").eq("id", firm_id)
             .limit(1).execute().data) or []
        row = r[0] if r else {}
        return (row.get("name") or None), (row.get("email") or None)
    except Exception:                                           # noqa: BLE001
        return None, None


def staff_for_client(firm_id: str, client_id: str) -> list[dict]:
    """Who a client's portal message should reach: the staff ASSIGNED to the
    client (`user_client_assignments`, the same source core.authz scopes by) and,
    where nobody is assigned, the firm's Partners — a message must never land
    on nobody. Active people only.

    Service role, because the caller is a portal CLIENT: their JWT has no
    `users` row, so every one of these reads would come back empty under it.
    """
    if _USE_MOCK:
        from repositories.assignment_repository import _MOCK_ASSIGNMENTS
        ids = [a["user_id"] for a in _MOCK_ASSIGNMENTS
               if a.get("firm_id") == firm_id and a.get("client_id") == client_id]
    else:
        rows = (_db().table("user_client_assignments").select("user_id")
                .eq("firm_id", firm_id).eq("client_id", client_id).execute().data) or []
        ids = [r["user_id"] for r in rows]
    people = [p for p in (_staff_member(firm_id, i) for i in dict.fromkeys(ids))
              if p and p.get("is_active") is not False]
    if people:
        return people
    from repositories.user_repository import user_repo
    try:
        partners = user_repo.find_all(firm_id=firm_id, role="Partner")
    except Exception:                                           # noqa: BLE001
        partners = []
    return [p for p in partners if p.get("is_active") is not False]


def app_link(path: str) -> str:
    return f"{frontend_base()}{path}"


def pretty_date(d: object) -> str:
    """'2026-10-20' -> '20 Oct 2026'; anything unreadable is shown as it is."""
    try:
        return date.fromisoformat(str(d)[:10]).strftime("%d %b %Y")
    except ValueError:
        return str(d or "")


# ── task assigned (immediate) ────────────────────────────────────────────────

def task_assigned(task: dict, assignee: dict, assigned_by: Optional[dict]) -> str:
    """ONE mail to the new assignee when somebody else gives them a task.

    NOT when they give it to themselves: the person who just pressed the button
    does not need an email to say so. NOT deduplicated: an assignment is an
    event, and assigning the same task to the same person twice in a day is two
    events — what stops a double-click is that an unchanged assignee raises no
    event at the router at all.
    """
    try:
        if assigned_by and assigned_by.get("id") and assignee.get("id") \
                and str(assigned_by["id"]) == str(assignee["id"]):
            return "skipped_self"
        firm_id = task.get("firm_id") or assignee.get("firm_id")
        if not firm_id or not task.get("id"):
            return "skipped_no_firm"
        client = client_names(firm_id, [task.get("client_id")]).get(
            str(task.get("client_id")), "your client")
        due = task.get("due_date")
        return deliver(
            firm_id, "task_assigned", assignee,
            [Ref("task", str(task["id"]))],
            lambda _refs: email_service.send_task_assigned(
                str(assignee.get("email")), assignee.get("full_name") or "",
                task.get("title") or "A task", client, pretty_date(due) if due else None),
            dedupe=False)
    except Exception:                                           # noqa: BLE001
        _logger.warning("caflow.practice_mail: task_assigned failed", exc_info=True)
        return "failed"


# ── the compliance sweep ─────────────────────────────────────────────────────

_TIER_HEADING = {
    "overdue": "Overdue",
    "due_1": "Due tomorrow",
    "due_3": "Due in 3 days",
    "due_7": "Due in 7 days",
}
_TIER_ORDER = ("overdue", "due_1", "due_3", "due_7")


def send_deadline_mails(firm_id: str, batch: dict[str, list[dict]],
                        today: Optional[date] = None) -> dict:
    """One mail per recipient listing every obligation that reached a tier in
    this sweep. `batch` is `{user_id: [{record_id, tier, client_id, label,
    due_date}, ...]}`, built by `compliance_obligation_service.escalate`.

    Exactly one item reads as the single-obligation notice
    (`email_service.send_compliance_due_soon`); several read as a digest.
    """
    today = today or ist_today()
    tally: dict[str, int] = {}
    names = client_names(firm_id, [i.get("client_id") for items in batch.values() for i in items])
    for user_id, items in batch.items():
        person = _staff_member(firm_id, user_id)
        if not person:
            continue
        by_ref = {Ref("compliance_record", str(i["record_id"]), i["tier"]): i for i in items}

        def send(refs: list[Ref], person=person, by_ref=by_ref) -> bool:
            todo = [by_ref[r] for r in refs]
            to = str(person.get("email"))
            if len(todo) == 1:
                i = todo[0]
                return email_service.send_compliance_due_soon(
                    to, names.get(str(i.get("client_id")), "a client"),
                    i.get("label") or "A compliance obligation", pretty_date(i.get("due_date")))
            groups = []
            for tier in _TIER_ORDER:
                lines = [f"{names.get(str(i.get('client_id')), 'a client')} — "
                         f"{i.get('label')} (due {pretty_date(i.get('due_date'))})"
                         for i in todo if i["tier"] == tier]
                if lines:
                    groups.append((_TIER_HEADING[tier], lines))
            return email_service.send_attention_digest(
                to, person.get("full_name") or "",
                f"{len(todo)} compliance deadlines need attention",
                "These obligations have reached a reminder point:", groups,
                link=app_link("/deadlines"))

        status = deliver(firm_id, "compliance_deadline", person, list(by_ref), send, day=today)
        tally[status] = tally.get(status, 0) + 1
    return tally


# ── the task sweeps ──────────────────────────────────────────────────────────

def _assignee_of(task: dict) -> Optional[str]:
    """`tasks` carries BOTH `assigned_to` and `assignee_id` (migration 424
    repointed both at `users`) and the API writes only the first, so a reader
    that asks one misses rows the other holds."""
    return task.get("assigned_to") or task.get("assignee_id") or None


def _recently_mailed(firm_id: str, event_type: str, today: date) -> dict[tuple[str, str], date]:
    """{(address, ref_id): latest day a SENT mail covered it} within the window
    an overdue reminder is held back for."""
    since = (today - timedelta(days=rules.OVERDUE_RENOTIFY_DAYS)).isoformat()
    if _USE_MOCK:
        rows = [r for r in MOCK_LOG if r.get("firm_id") == firm_id
                and r.get("event_type") == event_type and r.get("status") == "sent"
                and str(r.get("sent_for_date")) >= since]
    else:
        from core.db_paging import fetch_all
        rows = fetch_all(
            lambda: _db().table("practice_email_log")
            .select("id, recipient_email, ref_id, sent_for_date")
            .eq("firm_id", firm_id).eq("event_type", event_type)
            .eq("status", "sent").gte("sent_for_date", since),
            label="practice_mail_service.recently_mailed")
    out: dict[tuple[str, str], date] = {}
    for r in rows:
        key = (str(r.get("recipient_email") or "").strip().lower(), str(r.get("ref_id")))
        d = rules.latest([out.get(key), r.get("sent_for_date")])
        if d is not None:
            out[key] = d
    return out


def send_overdue_task_mails(firm_id: str, tasks: list[dict],
                            today: Optional[date] = None) -> dict:
    """One mail per ASSIGNEE listing their overdue tasks, then a reminder each
    week while they stay open — never daily, which is the shape of the
    forty-one-days-running bug the obligation sweep had to be repaired for."""
    today = today or ist_today()
    today_s = today.isoformat()
    overdue: dict[str, list[dict]] = {}
    for t in tasks:
        who = _assignee_of(t)
        due = str(t.get("due_date") or "")[:10]
        if (not who or not due or due >= today_s
                or (t.get("status") or "") in _DONE_TASK_STATUSES):
            continue
        overdue.setdefault(str(who), []).append(t)
    if not overdue:
        return {}
    mailed = _recently_mailed(firm_id, "task_overdue", today)
    names = client_names(firm_id, [t.get("client_id") for ts in overdue.values() for t in ts])
    tally: dict[str, int] = {}
    for user_id, mine in overdue.items():
        person = _staff_member(firm_id, user_id)
        if not person:
            continue
        email = str(person.get("email") or "").strip().lower()
        due_now = [t for t in mine if rules.overdue_reminder_is_due(
            mailed.get((email, str(t["id"]))), today)]
        if not due_now:
            continue
        by_ref = {Ref("task", str(t["id"]), "overdue"): t for t in due_now}

        def send(refs: list[Ref], person=person, by_ref=by_ref) -> bool:
            todo = sorted((by_ref[r] for r in refs), key=lambda t: str(t.get("due_date")))
            to = str(person.get("email"))
            if len(todo) == 1:
                t = todo[0]
                return email_service.send_task_overdue(
                    to, person.get("full_name") or "", t.get("title") or "A task",
                    names.get(str(t.get("client_id")), "a client"), pretty_date(t.get("due_date")))
            lines = [f"{t.get('title')} — {names.get(str(t.get('client_id')), 'a client')} "
                     f"(was due {pretty_date(t.get('due_date'))})" for t in todo]
            return email_service.send_attention_digest(
                to, person.get("full_name") or "",
                f"{len(todo)} of your tasks are overdue",
                "These tasks assigned to you are past their due date:",
                [("Overdue", lines)], link=app_link("/tasks"))

        status = deliver(firm_id, "task_overdue", person, list(by_ref), send, day=today)
        tally[status] = tally.get(status, 0) + 1
    return tally


def send_escalation_mails(firm_id: str, items: list[dict],
                          today: Optional[date] = None) -> dict:
    """One mail per MANAGER listing what the firm's escalation rules sent them.

    `items` are `{recipient_id, kind, task, new_assignee_name?, days_threshold?}`
    gathered by `EscalationService` where it already creates the in-app
    notification. `kind` is `due_soon`, `overdue` or `reassigned`.
    """
    today = today or ist_today()
    by_manager: dict[str, list[dict]] = {}
    for it in items:
        if it.get("recipient_id") and (it.get("task") or {}).get("id"):
            by_manager.setdefault(str(it["recipient_id"]), []).append(it)
    if not by_manager:
        return {}
    all_tasks = [it["task"] for its in by_manager.values() for it in its]
    names = client_names(firm_id, [t.get("client_id") for t in all_tasks])
    tally: dict[str, int] = {}
    for user_id, its in by_manager.items():
        person = _staff_member(firm_id, user_id)
        if not person:
            continue
        by_ref = {Ref("task", str(it["task"]["id"]), it["kind"]): it for it in its}

        def send(refs: list[Ref], person=person, by_ref=by_ref) -> bool:
            todo = [by_ref[r] for r in refs]
            to = str(person.get("email"))
            if len(todo) == 1 and todo[0]["kind"] in ("overdue", "reassigned"):
                it = todo[0]
                t = it["task"]
                assignee = _staff_member(firm_id, _assignee_of(t))
                return email_service.send_escalation_alert(
                    to, person.get("full_name") or "", t.get("title") or "A task",
                    (assignee or {}).get("full_name") or (assignee or {}).get("email") or "your team",
                    names.get(str(t.get("client_id")), "a client"))
            groups = []
            for kind, heading in (("overdue", "Overdue"), ("reassigned", "Reassigned"),
                                  ("due_soon", "Due soon")):
                lines = [f"{i['task'].get('title')} — "
                         f"{names.get(str(i['task'].get('client_id')), 'a client')}"
                         f"{' (due ' + pretty_date(i['task'].get('due_date')) + ')' if i['task'].get('due_date') else ''}"
                         for i in todo if i["kind"] == kind]
                if lines:
                    groups.append((heading, lines))
            return email_service.send_attention_digest(
                to, person.get("full_name") or "",
                f"{len(todo)} tasks have escalated to you",
                "Your firm's escalation rules sent you these tasks:", groups,
                link=app_link("/tasks"))

        status = deliver(firm_id, "escalation", person, list(by_ref), send, day=today)
        tally[status] = tally.get(status, 0) + 1
    return tally
