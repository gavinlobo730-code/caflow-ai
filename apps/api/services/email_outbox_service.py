"""The practice's own mail waits in an outbox, is retried, and a bounce marks the address (ops-21).

WHAT WAS WRONG
    `email_service._send` posted to Resend synchronously from the request with a 10-second
    timeout and answered True or False. Nothing retried: an assignment notice or a client's
    portal message that met one provider hiccup was simply never sent, and the only trace was a
    `failed` row nobody reads. A slow provider held one of the worker's ~40 threads for ten
    seconds per mail. And nothing listened to the provider afterwards, so an address that
    hard-bounced was mailed again by every sweep, from the one sending domain every firm shares.

WHAT THIS IS
    `practice_mail_service.deliver` - the ONE door for the practice's own mail, and the only
    place PRACTICE_MAIL_ENABLED is decided - runs each mail's `send` callback inside
    `capturing(...)`, which points `email_service._send` at `enqueue`. The message is written to
    `email_outbox` (migration 472) and `deliver` answers `queued`. `drain` delivers it:

      * the scheduler calls `drain` every minute, and a queued mail kicks a background drain at
        once, so the ordinary mail goes out within seconds and a failed one is retried;
      * a drainer takes rows with `claim_email_outbox` (FOR UPDATE SKIP LOCKED), so two instances
        never hold the same message, and a drainer that dies leaves a row whose lease expires and
        is handed out again - after it has already spent an attempt, so a message that kills its
        drainer cannot be retried for ever;
      * a 5xx, a 429, a timeout, a refused connection and the two credential refusals (401, 403)
        are retried with backoff (1, 5, 15, 60 and 240 minutes, six attempts in all); any other
        4xx says the message itself is wrong and is final at once;
      * every attempt sends `Idempotency-Key: <row id>`, so an attempt that timed out AFTER the
        provider accepted the mail does not become two mails (`[S]`: see email_service.transport);
      * a message that is over - sent, failed, cancelled or suppressed - has its subject and body
        BLANKED, and `final_reason` / `last_error_code` hold short codes and never a provider
        message, which can quote the recipient's address.

THE SWITCH IS ASKED TWICE, and so is the person
    A mail may never be sent while PRACTICE_MAIL_ENABLED is off. `deliver` asks it before it
    queues; `enqueue` asks it again for a practice notice (so a caller that reached the queue some
    other way cannot go round `deliver`); and `drain` asks it AGAIN for every row it takes - a
    mail queued before somebody turned the practice's mail off is CANCELLED, not sent. A staff
    member's own preference and their being active are re-asked at drain too, and an address the
    provider has reported as a permanent bounce or complaint is `suppressed`. A cancelled,
    suppressed or failed message flips its `practice_email_log` rows back to `failed` and clears
    their dedupe keys (`practice_mail_service.mark_not_delivered`), because the log recorded it as
    `sent` when it was accepted and the unique index on sent rows would otherwise stop a later
    sweep from ever trying again.

WHAT IT DELIBERATELY DOES NOT DO
    * It does not carry an attachment. The practice's notices have none; the customer-facing
      invoice, statement and reminder mails (a person pressed Send and is told whether it went)
      stay synchronous and do not use it.
    * It never mails a client's own customers. The vocabulary of recipients is staff and a
      client's own portal contact, `enqueue` refuses anything else, and
      tests/test_the_practices_mail_waits_in_an_outbox_and_a_bounce_marks_the_address.py reads
      the call sites of `enqueue` off the AST so a sweep cannot grow one (D27: sending to a
      client's customers is never automatic, a Send button always).
    * It is not used in mock mode, where `deliver` posts directly as before: the suite's ~30 mail
      tests assert on what reaches the provider, and a mock-mode queue nobody drains would turn
      each of them into a test of nothing.
    * It does not re-queue a mail for a person who has since left: a `staff` row whose user is no
      longer there or no longer active is cancelled.

WHEN THE OUTBOX IS NOT THERE
    Code and migration deploy on separate tracks. A database without migration 472 makes the sink
    fall back to posting directly - once per process, at ERROR - so the practice's mail still goes
    out as it did before this change.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Optional

from core import db_errors, db_provider
from services import email_service

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.email_outbox")

#: Whose mail an outbox row is. Only the practice's own notices go through it today.
ORIGIN_PRACTICE_NOTICE = "practice_notice"
ORIGINS = (ORIGIN_PRACTICE_NOTICE,)
#: Who it may be addressed to. A client's CUSTOMER is not on this list and cannot be added by a
#: caller: D27 says mail to a client's customers is never automatic.
RECIPIENT_KINDS = ("staff", "client_contact")

#: What a log row says about a mail that is accepted but not yet delivered.
QUEUED_DETAIL = "queued for delivery"

MAX_ATTEMPTS = 6
#: Minutes to wait after the Nth failed attempt (the last value repeats). Six attempts in all, so
#: the last try is about 5 hours 20 minutes after the first.
BACKOFF_MINUTES = (1, 5, 15, 60, 240)
LEASE_SECONDS = 300
#: Rows taken per claim, and the time one `drain` call may spend: a worst-case attempt is the
#: transport's 10 seconds, so a batch of 5 is at most about a minute, and the loop stops
#: claiming after DRAIN_SECONDS so the per-minute tick never runs into the next one.
DRAIN_BATCH = 5
DRAIN_SECONDS = 45
#: How long a finished row is kept (it holds no text by then: who, when, how it ended).
RETENTION_DAYS = 30
_PRUNE_EVERY_SECONDS = 3600

# Terminal statuses, and the ones that flip the practice_email_log rows back to `failed`.
_TERMINAL = ("sent", "failed", "cancelled", "suppressed")
_NOT_DELIVERED = ("failed", "cancelled", "suppressed")


class SwitchedOff(Exception):
    """The practice's mail is switched off: nothing may be queued or sent."""


# ── the switch, asked of the one place that owns it ──────────────────────────────

def _practice_mail_enabled() -> bool:
    # Imported at call time: practice_mail_service imports this module.
    from services import practice_mail_service
    return practice_mail_service.mail_enabled()


# ── stores ───────────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryOutboxStore:
    """The outbox in a list: what the suite and mock mode use, and a model of the SQL.

    `claim_due` mirrors `claim_email_outbox` clause for clause; the real-Postgres test drives the
    same scenarios at the function."""

    def __init__(self, clock: Callable[[], datetime] = _now) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self.rows: dict[str, dict] = {}
        self.suppressions: dict[str, dict] = {}

    def now(self) -> datetime:
        return self._clock()

    # outbox ------------------------------------------------------------------------
    def insert(self, row: dict) -> dict:
        now = self._clock()
        stored = {
            "id": str(uuid.uuid4()), "status": "pending", "attempts": 0, "max_attempts": MAX_ATTEMPTS,
            "next_attempt_at": now, "lease_expires_at": None, "last_attempt_at": None, "sent_at": None,
            "provider_message_id": None, "last_status_code": None, "last_error_code": None,
            "final_reason": None, "delivery_event": None, "delivery_event_at": None,
            "created_at": now, "updated_at": now, **row,
        }
        with self._lock:
            self.rows[stored["id"]] = stored
        return dict(stored)

    def claim_due(self, limit: int, lease_seconds: int) -> list[dict]:
        if not 1 <= limit <= 200 or not 30 <= lease_seconds <= 3600:
            raise ValueError("out of range")
        now = self._clock()
        with self._lock:
            due = sorted(
                (r for r in self.rows.values()
                 if (r["status"] == "pending" and r["next_attempt_at"] <= now)
                 or (r["status"] == "sending" and r["lease_expires_at"] <= now)),
                key=lambda r: r["next_attempt_at"])[:limit]
            for r in due:
                r.update(status="sending", attempts=r["attempts"] + 1,
                         lease_expires_at=now + timedelta(seconds=lease_seconds),
                         last_attempt_at=now, updated_at=now)
            return [dict(r) for r in due]

    def _held(self, row_id: str, attempts: int) -> Optional[dict]:
        r = self.rows.get(row_id)
        return r if r and r["status"] == "sending" and r["attempts"] == attempts else None

    def mark_sent(self, row_id: str, attempts: int, *, provider_message_id, status_code) -> bool:
        with self._lock:
            r = self._held(row_id, attempts)
            if r is None:
                return False
            r.update(status="sent", sent_at=self._clock(), provider_message_id=provider_message_id,
                     last_status_code=status_code, last_error_code=None, lease_expires_at=None,
                     subject="", html="", updated_at=self._clock())
            return True

    def mark_retry(self, row_id: str, attempts: int, *, next_attempt_at: datetime, status_code,
                   error_code) -> bool:
        with self._lock:
            r = self._held(row_id, attempts)
            if r is None:
                return False
            r.update(status="pending", next_attempt_at=next_attempt_at, last_status_code=status_code,
                     last_error_code=error_code, lease_expires_at=None, updated_at=self._clock())
            return True

    def mark_final(self, row_id: str, attempts: int, *, status: str, final_reason, status_code,
                   error_code) -> bool:
        with self._lock:
            r = self._held(row_id, attempts)
            if r is None:
                return False
            r.update(status=status, final_reason=final_reason, last_status_code=status_code,
                     last_error_code=error_code, lease_expires_at=None, subject="", html="",
                     updated_at=self._clock())
            return True

    def by_provider_message(self, message_id: str) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.rows.values() if r["provider_message_id"] == message_id]

    def set_delivery_event(self, message_id: str, event: str) -> int:
        n = 0
        with self._lock:
            for r in self.rows.values():
                if r["provider_message_id"] == message_id:
                    r.update(delivery_event=event, delivery_event_at=self._clock())
                    n += 1
        return n

    def prune(self, older_than_days: int) -> int:
        cutoff = self._clock() - timedelta(days=older_than_days)
        with self._lock:
            old = [k for k, r in self.rows.items()
                   if r["status"] in _TERMINAL and r["updated_at"] < cutoff]
            for k in old:
                del self.rows[k]
        return len(old)

    # suppressions --------------------------------------------------------------------
    def is_suppressed(self, address: str) -> bool:
        with self._lock:
            return address in self.suppressions

    def suppress(self, address: str, reason: str, message_id: Optional[str]) -> None:
        now = self._clock()
        with self._lock:
            row = self.suppressions.get(address)
            if row is None:
                self.suppressions[address] = {"address": address, "reason": reason,
                                              "provider_message_id": message_id,
                                              "first_event_at": now, "last_event_at": now}
            else:
                # A complaint outranks a bounce: it is the stronger statement about this person.
                row.update(reason="complaint" if "complaint" in (row["reason"], reason) else reason,
                           provider_message_id=message_id, last_event_at=now)


class PostgrestOutboxStore:
    """Production: `email_outbox`, `email_suppressions` and `claim_email_outbox` over PostgREST as
    the service role. Every payload is a dict LITERAL at its call, because
    tests/_backend_query_parser reads a literal's keys against the real schema and a payload held
    in a variable is a blind spot whose budget is exact."""

    def __init__(self, db: Callable[[], object]) -> None:
        self._db = db

    def now(self) -> datetime:
        return _now()

    def insert(self, row: dict) -> dict:
        res = self._db().table("email_outbox").insert({
            "firm_id": row["firm_id"],
            "origin": row["origin"],
            "event_type": row["event_type"],
            "recipient_kind": row["recipient_kind"],
            "recipient_user_id": row.get("recipient_user_id"),
            "to_address": row["to_address"],
            "subject": row["subject"],
            "html": row["html"],
            "sender_name": row.get("sender_name"),
            "reply_to": row.get("reply_to"),
            "max_attempts": row.get("max_attempts", MAX_ATTEMPTS),
            "log_ids": list(row.get("log_ids") or []),
        }).execute()
        data = res.data
        if isinstance(data, list):
            data = data[0] if data else None
        if not isinstance(data, dict) or not data.get("id"):
            raise RuntimeError("the outbox insert returned no row")
        return data

    def claim_due(self, limit: int, lease_seconds: int) -> list[dict]:
        res = self._db().rpc("claim_email_outbox", {
            "p_limit": int(limit), "p_lease_seconds": int(lease_seconds)}).execute()
        return list(res.data or [])

    def mark_sent(self, row_id: str, attempts: int, *, provider_message_id, status_code) -> bool:
        res = (self._db().table("email_outbox").update({
            "status": "sent",
            "sent_at": _now().isoformat(),
            "provider_message_id": provider_message_id,
            "last_status_code": status_code,
            "last_error_code": None,
            "lease_expires_at": None,
            "subject": "",
            "html": "",
            "updated_at": _now().isoformat(),
        }).eq("id", row_id).eq("status", "sending").eq("attempts", attempts).execute())
        return bool(res.data)

    def mark_retry(self, row_id: str, attempts: int, *, next_attempt_at: datetime, status_code,
                   error_code) -> bool:
        res = (self._db().table("email_outbox").update({
            "status": "pending",
            "next_attempt_at": next_attempt_at.isoformat(),
            "last_status_code": status_code,
            "last_error_code": error_code,
            "lease_expires_at": None,
            "updated_at": _now().isoformat(),
        }).eq("id", row_id).eq("status", "sending").eq("attempts", attempts).execute())
        return bool(res.data)

    def mark_final(self, row_id: str, attempts: int, *, status: str, final_reason, status_code,
                   error_code) -> bool:
        res = (self._db().table("email_outbox").update({
            "status": status,
            "final_reason": final_reason,
            "last_status_code": status_code,
            "last_error_code": error_code,
            "lease_expires_at": None,
            "subject": "",
            "html": "",
            "updated_at": _now().isoformat(),
        }).eq("id", row_id).eq("status", "sending").eq("attempts", attempts).execute())
        return bool(res.data)

    def by_provider_message(self, message_id: str) -> list[dict]:
        return list(self._db().table("email_outbox")
                    .select("id, firm_id, status, to_address, provider_message_id")
                    .eq("provider_message_id", message_id).execute().data or [])

    def set_delivery_event(self, message_id: str, event: str) -> int:
        res = (self._db().table("email_outbox").update({
            "delivery_event": event,
            "delivery_event_at": _now().isoformat(),
        }).eq("provider_message_id", message_id).execute())
        return len(res.data or [])

    def prune(self, older_than_days: int) -> int:
        cutoff = (_now() - timedelta(days=older_than_days)).isoformat()
        res = (self._db().table("email_outbox").delete()
               .in_("status", list(_TERMINAL)).lt("updated_at", cutoff).execute())
        return len(res.data or [])

    def is_suppressed(self, address: str) -> bool:
        rows = (self._db().table("email_suppressions").select("address")
                .eq("address", address).limit(1).execute().data) or []
        return bool(rows)

    def suppress(self, address: str, reason: str, message_id: Optional[str]) -> None:
        now = _now().isoformat()
        existing = (self._db().table("email_suppressions").select("reason")
                    .eq("address", address).limit(1).execute().data) or []
        if existing:
            keep = "complaint" if "complaint" in (existing[0].get("reason"), reason) else reason
            (self._db().table("email_suppressions").update({
                "reason": keep,
                "provider_message_id": message_id,
                "last_event_at": now,
            }).eq("address", address).execute())
            return
        self._db().table("email_suppressions").insert({
            "address": address,
            "reason": reason,
            "provider_message_id": message_id,
            "first_event_at": now,
            "last_event_at": now,
        }).execute()


# ── which store, and whether to queue at all ─────────────────────────────────────

_store_override = None
_shared_memory = MemoryOutboxStore()
_queueing_override: Optional[bool] = None
_kick_override: Optional[bool] = None


_db = db_provider.service_db


def set_store(store) -> None:
    """Tests: use this store whatever the mode. `None` puts the default back."""
    global _store_override
    _store_override = store


def set_queueing(value: Optional[bool]) -> None:
    """Tests: force queueing on or off. `None` puts the default back."""
    global _queueing_override
    _queueing_override = value


def set_kick(value: Optional[bool]) -> None:
    """Tests: allow (True) or forbid (False) the background drain a queued mail starts."""
    global _kick_override
    _kick_override = value


def memory_store() -> MemoryOutboxStore:
    return _shared_memory


def current_store():
    if _store_override is not None:
        return _store_override
    return _shared_memory if _USE_MOCK else PostgrestOutboxStore(_db)


def queueing_enabled() -> bool:
    """Whether `deliver` queues. True against a database, False in mock mode (see the header)."""
    if _queueing_override is not None:
        return _queueing_override
    return not _USE_MOCK


# ── suppression ──────────────────────────────────────────────────────────────────

_suppression_unavailable_warned = False


def normalise_address(address: str) -> str:
    return (address or "").strip().lower()


def is_suppressed(address: str, *, store=None) -> bool:
    """Has the provider told us not to mail this address? Fails OPEN and says so once: the list
    protects the sending domain's reputation, and a mail the practice needs to send must not wait
    on a table that cannot be read."""
    global _suppression_unavailable_warned
    addr = normalise_address(address)
    if not addr:
        return False
    try:
        return bool((store or current_store()).is_suppressed(addr))
    except Exception as exc:                                    # noqa: BLE001
        if not _suppression_unavailable_warned:
            _suppression_unavailable_warned = True
            _logger.warning("caflow.email_outbox: the suppression list could not be read, so "
                            "addresses are not being checked against it: %s: %s",
                            type(exc).__name__, exc)
        return False


# ── queueing ─────────────────────────────────────────────────────────────────────

def enqueue(*, firm_id: str, to: str, subject: str, html: str,
            sender_name: Optional[str] = None, reply_to: Optional[str] = None,
            origin: str, event_type: str, recipient_kind: str,
            recipient_user_id: Optional[str] = None, log_ids: Iterable[str] = (),
            store=None) -> str:
    """Put one message on the outbox and return its id.

    Refuses an origin or a recipient kind outside the vocabulary (a client's customer is not one),
    an address with no `@`, and - for a practice notice - a deployment whose practice mail is
    switched off (`SwitchedOff`): the switch is asked here as well as at `deliver`, so nothing that
    reaches the queue by another road can go round it."""
    if origin not in ORIGINS:
        raise ValueError(f"{origin!r} is not an outbox origin (one of: {', '.join(ORIGINS)}).")
    if recipient_kind not in RECIPIENT_KINDS:
        raise ValueError(f"{recipient_kind!r} may not be queued mail (one of: "
                         f"{', '.join(RECIPIENT_KINDS)}). Mail to a client's customers is never "
                         "automatic: a person presses Send.")
    if not firm_id:
        raise ValueError("a queued mail belongs to a firm")
    if "@" not in (to or ""):
        raise ValueError("a queued mail needs an address")
    if origin == ORIGIN_PRACTICE_NOTICE and not _practice_mail_enabled():
        raise SwitchedOff()
    row = (store or current_store()).insert({
        "firm_id": str(firm_id), "origin": origin, "event_type": event_type,
        "recipient_kind": recipient_kind,
        "recipient_user_id": str(recipient_user_id) if recipient_user_id else None,
        "to_address": to.strip(), "subject": subject or "", "html": html or "",
        "sender_name": sender_name, "reply_to": reply_to,
        "log_ids": [str(i) for i in log_ids],
    })
    return str(row["id"])


@dataclass
class Capture:
    """What happened to the ONE mail a `deliver` callback sent."""
    queued: int = 0
    direct: int = 0
    ids: list = field(default_factory=list)


_unavailable_warned = False


@contextmanager
def capturing(*, firm_id: str, event_type: str, recipient_kind: str,
              recipient_user_id: Optional[str], log_ids: Iterable[str],
              origin: str = ORIGIN_PRACTICE_NOTICE, store=None):
    """Point `email_service._send` at the outbox for the duration of one delivery.

    The sink answers True for "accepted for delivery". It refuses a SECOND message in one
    delivery (the log rows a delivery records map to one mail), answers False when the switch has
    been turned off since `deliver` asked, and - the one fallback - posts the mail directly, once
    per process at ERROR, when the database has no outbox yet (migration 472 not applied)."""
    capture = Capture()
    ids = [str(i) for i in log_ids]

    def sink(to, subject, html, sender_name, reply_to) -> bool:
        global _unavailable_warned
        if capture.queued or capture.direct:
            raise RuntimeError("one mail per delivery: a second message was sent inside one "
                               "practice_mail_service.deliver call")
        try:
            oid = enqueue(firm_id=firm_id, to=to, subject=subject, html=html,
                          sender_name=sender_name, reply_to=reply_to, origin=origin,
                          event_type=event_type, recipient_kind=recipient_kind,
                          recipient_user_id=recipient_user_id, log_ids=ids, store=store)
        except SwitchedOff:
            return False
        except Exception as exc:                                # noqa: BLE001
            if db_errors.is_missing_store(exc):
                if not _unavailable_warned:
                    _unavailable_warned = True
                    _logger.error(
                        "the mail outbox is NOT in force: this database has no email_outbox "
                        "(migration 472 has not been applied). The practice's mail is being "
                        "posted directly, as it was before the outbox. %s", exc)
                capture.direct += 1
                return email_service.transport(
                    to, subject, html, sender_name=sender_name, reply_to=reply_to).ok
            _logger.error("could not queue a %s mail: %s: %s", event_type, type(exc).__name__, exc)
            return False
        capture.queued += 1
        capture.ids.append(oid)
        return True

    token = email_service._OUTBOX_SINK.set(sink)
    try:
        yield capture
    finally:
        email_service._OUTBOX_SINK.reset(token)


# ── delivering ───────────────────────────────────────────────────────────────────

def backoff_for(attempts: int) -> timedelta:
    """How long to wait after the `attempts`th failed attempt."""
    minutes = BACKOFF_MINUTES[min(max(attempts, 1), len(BACKOFF_MINUTES)) - 1]
    return timedelta(minutes=minutes)


def _gate(row: dict, store) -> Optional[tuple[str, str]]:
    """Is there a reason NOT to send this row now? (status, reason) or None.

    The switch, the person's own preference and their still being active are asked again
    here, because the row may have waited minutes or hours since `deliver` asked them."""
    if row.get("origin") == ORIGIN_PRACTICE_NOTICE and not _practice_mail_enabled():
        return "cancelled", "switched_off"
    if row.get("recipient_kind") == "staff":
        from domain import practice_notices as rules
        from services import practice_mail_service as pm
        user_id = row.get("recipient_user_id")
        person = pm._staff_member(str(row["firm_id"]), user_id) if user_id else None
        if not person or person.get("is_active") is False:
            return "cancelled", "inactive_recipient"
        if not rules.wants_email(str(row["event_type"]),
                                 pm.chosen_preferences(str(row["firm_id"]), str(user_id))):
            return "cancelled", "preference_off"
    if is_suppressed(row["to_address"], store=store):
        return "suppressed", "suppressed"
    return None


def _finish(store, row: dict, status: str, *, reason: Optional[str], status_code=None,
            error_code=None) -> str:
    held = store.mark_final(row["id"], row["attempts"], status=status, final_reason=reason,
                            status_code=status_code, error_code=error_code)
    if not held:
        _logger.warning("caflow.email_outbox: lost the lease on message %s before it could be "
                        "marked %s", row["id"], status)
        return "lost"
    if status in _NOT_DELIVERED:
        from services import practice_mail_service as pm
        pm.mark_not_delivered(str(row["firm_id"]), row.get("log_ids") or [],
                              f"not delivered ({reason or status})")
    if status == "failed":
        _logger.error("caflow.email_outbox: message %s to a %s recipient of firm %s was not "
                      "delivered after %s attempt(s): %s", row["id"], row.get("recipient_kind"),
                      row["firm_id"], row["attempts"], reason)
        try:
            from core.observability import capture_soft_failure
            capture_soft_failure(
                RuntimeError(f"queued mail undeliverable: {reason}"),
                operation="email_outbox_undeliverable", firm_id=row["firm_id"],
                outbox_id=row["id"], event_type=row.get("event_type"))
        except Exception:                                       # noqa: BLE001
            # Reporting that a mail was undeliverable must not itself fail the drain: the ERROR line above
            # is the record. Saying so keeps this from being a silent swallow.
            _logger.warning("caflow.email_outbox: could not report message %s as undeliverable", row["id"],
                            exc_info=True)
    return status


def _deliver_one(store, row: dict) -> str:
    """Send one claimed row, or end it. Returns what became of it."""
    if row["attempts"] > row["max_attempts"]:
        # The drainer that held it died, attempt after attempt. Give up rather than retry for ever.
        return _finish(store, row, "failed", reason="abandoned")
    try:
        gate = _gate(row, store)
    except Exception as exc:                                    # noqa: BLE001
        _logger.warning("caflow.email_outbox: could not check message %s before sending: %s",
                        row["id"], exc, exc_info=True)
        return _retry(store, row, status_code=None, code="gate_error")
    if gate is not None:
        return _finish(store, row, gate[0], reason=gate[1])
    outcome = email_service.transport(
        row["to_address"], row.get("subject") or "", row.get("html") or "",
        sender_name=row.get("sender_name"), reply_to=row.get("reply_to"),
        idempotency_key=str(row["id"]))
    if outcome.ok:
        if not store.mark_sent(row["id"], row["attempts"], provider_message_id=outcome.message_id,
                               status_code=outcome.status_code):
            _logger.warning("caflow.email_outbox: message %s was sent but its lease had gone; "
                            "another drainer may send it too", row["id"])
            return "lost"
        return "sent"
    if outcome.retryable and row["attempts"] < row["max_attempts"]:
        return _retry(store, row, status_code=outcome.status_code, code=outcome.code)
    return _finish(store, row, "failed", reason=outcome.code or "unknown",
                   status_code=outcome.status_code, error_code=outcome.code)


def _retry(store, row: dict, *, status_code, code) -> str:
    when = store.now() + backoff_for(row["attempts"])
    if not store.mark_retry(row["id"], row["attempts"], next_attempt_at=when,
                            status_code=status_code, error_code=code):
        return "lost"
    return "retry"


_last_prune: Optional[float] = None


def drain(*, max_seconds: float = DRAIN_SECONDS, batch: int = DRAIN_BATCH, store=None) -> dict:
    """Deliver what is due. Never raises. Returns a count per outcome.

    Claims a few rows at a time and stops claiming once `max_seconds` has passed, so the
    per-minute tick cannot run into the next one. Safe to run from several places at once (the
    tick, a kick, another instance, the external trigger): the claim hands each row to one."""
    global _last_prune
    store = store or current_store()
    counts: Counter = Counter()
    deadline = time.monotonic() + max_seconds
    while time.monotonic() < deadline:
        try:
            rows = store.claim_due(batch, LEASE_SECONDS)
        except Exception as exc:                                # noqa: BLE001
            if db_errors.is_missing_store(exc, name="claim_email_outbox"):
                _logger.debug("caflow.email_outbox: no outbox in this database; nothing to drain")
            else:
                _logger.error("caflow.email_outbox: could not claim queued mail: %s: %s",
                              type(exc).__name__, exc)
            break
        if not rows:
            break
        for row in rows:
            try:
                counts[_deliver_one(store, row)] += 1
            except Exception:                                   # noqa: BLE001
                _logger.error("caflow.email_outbox: message %s raised while being delivered",
                              row.get("id"), exc_info=True)
                counts["error"] += 1
    if _last_prune is None or time.monotonic() - _last_prune > _PRUNE_EVERY_SECONDS:
        _last_prune = time.monotonic()
        try:
            pruned = store.prune(RETENTION_DAYS)
            if pruned:
                counts["pruned"] = pruned
        except Exception:                                       # noqa: BLE001
            # Housekeeping: a failed prune is retried on the next pass and costs only table size. It is
            # said, not swallowed, so a prune that can never succeed shows in the log.
            _logger.warning("caflow.email_outbox: prune of finished messages failed", exc_info=True)
    return dict(counts)


# ── the drain a queued mail starts ───────────────────────────────────────────────

_kick_lock = threading.Lock()
_kick_again = threading.Event()
_kick_thread: Optional[threading.Thread] = None


def _kick_allowed() -> bool:
    if _kick_override is not None:
        return _kick_override
    return not _USE_MOCK and _store_override is None


def _kick_worker() -> None:
    while True:
        _kick_again.clear()
        try:
            drain()
        except Exception:                                       # noqa: BLE001
            _logger.error("caflow.email_outbox: background drain failed", exc_info=True)
        if not _kick_again.is_set():
            return


def kick() -> None:
    """Ask for a drain soon, off the caller's thread, so the ordinary mail goes out in seconds and
    does not wait for the minute tick. One drain thread at a time; a kick while it runs asks it to
    go round again. If a kick is lost in the instant a thread is finishing, the minute tick is the
    backstop."""
    global _kick_thread
    if not _kick_allowed():
        return
    with _kick_lock:
        if _kick_thread is not None and _kick_thread.is_alive():
            _kick_again.set()
            return
        _kick_thread = threading.Thread(target=_kick_worker, name="email-outbox-drain", daemon=True)
        _kick_thread.start()
