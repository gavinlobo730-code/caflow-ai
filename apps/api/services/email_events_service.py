"""What the email provider's signed webhook does to our records (ops-21).

`domain/email_events` decides whether a request is genuine and what it means; this module
writes. Three places learn of a permanent bounce or a complaint:

  * `email_suppressions` - the address is not mailed again by the practice's own mail
    (`practice_mail_service.deliver` asks it, and so does the outbox drain). Global, not per
    firm: all firms send from one domain and share one reputation;
  * `email_outbox` - the message the provider names is marked `bounced` or `complained`;
  * `invoice_deliveries` and `customer_statement_deliveries` - their `bounced` status has existed
    since migrations 097 and 105 ("for future webhook reconciliation") and nothing ever set it,
    so an invoice the customer's mail server refused sat as `sent` for ever. A hard bounce now
    sets it. A complaint does not: the mail was delivered.

A SOFT bounce writes nothing durable. And a request that is not signed writes NOTHING at all
(SECURITY-PRIVACY-23): it leaves a log line and a counter in this process, and past
UNSIGNED_PER_IP_MAX a minute from one address it is throttled, exactly as the payment webhook's
unsigned requests are.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Mapping, Optional

from core.rate_window import SlidingWindowLimiter
from domain import email_events
from services import email_outbox_service

_logger = logging.getLogger("caflow.email_events")

UNSIGNED_PER_IP_MAX = 100
UNSIGNED_WINDOW_SECONDS = 60
_unsigned_per_ip = SlidingWindowLimiter(UNSIGNED_PER_IP_MAX, UNSIGNED_WINDOW_SECONDS)
_unsigned_lock = threading.Lock()
_unsigned_total = 0

_BOUNCED_MESSAGE = ("The recipient's mail server refused this message (a permanent bounce), so it "
                    "was not delivered.")


def unsigned_total() -> int:
    return _unsigned_total


def _reset_unsigned_state() -> None:  # test seam
    global _unsigned_total
    with _unsigned_lock:
        _unsigned_total = 0
    _unsigned_per_ip.reset()


def _refuse(reason: str, client_ip: Optional[str]) -> dict:
    global _unsigned_total
    ip = client_ip or "unknown"
    with _unsigned_lock:
        _unsigned_total += 1
        count = _unsigned_total
    within_budget = _unsigned_per_ip.hit(ip)
    if count <= 10 or count % 100 == 0:
        _logger.warning("email webhook: delivery #%d refused (%s, ip=%s%s)", count, reason, ip,
                        "" if within_budget else ", rate limited")
    return {"ok": False, "reason": "rate_limited" if not within_budget else "invalid_signature"}


def _mark_deliveries_bounced(db, message_id: str) -> int:
    """Set `bounced` on the delivery rows that carry this provider message id."""
    n = 0
    res = (db.table("invoice_deliveries")
           .update({"status": "bounced", "error_message": _BOUNCED_MESSAGE})
           .eq("provider_message_id", message_id).eq("status", "sent").execute())
    n += len(res.data or [])
    res = (db.table("customer_statement_deliveries")
           .update({"status": "bounced", "error_message": _BOUNCED_MESSAGE})
           .eq("provider_message_id", message_id).eq("status", "sent").execute())
    n += len(res.data or [])
    return n


def handle(event: email_events.Event, *, store=None, db=None) -> dict:
    """Apply one genuine event. A permanent bounce or complaint suppresses the address and marks
    the message; a hard bounce also marks the delivery rows. Anything else writes nothing."""
    if event.kind == email_events.IGNORED:
        return {"handled": False, "kind": event.kind}
    if event.kind == email_events.SOFT_BOUNCE:
        _logger.info("email webhook: a soft bounce for message %s (no address marked)",
                     event.message_id)
        return {"handled": True, "kind": event.kind, "suppressed": 0}
    store = store or email_outbox_service.current_store()
    reason = "hard_bounce" if event.kind == email_events.HARD_BOUNCE else "complaint"
    for address in event.addresses:
        store.suppress(address, reason, event.message_id)
    marked = deliveries = 0
    if event.message_id:
        marked = store.set_delivery_event(
            event.message_id, "bounced" if event.kind == email_events.HARD_BOUNCE else "complained")
        if event.kind == email_events.HARD_BOUNCE and db is not None:
            deliveries = _mark_deliveries_bounced(db, event.message_id)
    return {"handled": True, "kind": event.kind, "suppressed": len(event.addresses),
            "messages_marked": marked, "deliveries_marked": deliveries}


def process(secret: str, headers: Mapping[str, str], raw_body: bytes, client_ip: Optional[str],
            *, store=None, db=None, now: Optional[float] = None) -> dict:
    """Verify -> read -> apply. `{"ok": False, "reason": ...}` for a request that is not
    signed or is throttled (nothing written), `{"ok": False, "reason": "unreadable"}` for a signed
    body that is not an event, and `{"ok": True, ...}` otherwise."""
    verdict = email_events.verify(secret, headers, raw_body, now=now)
    if not verdict.ok:
        return _refuse(verdict.reason, client_ip)
    try:
        payload = json.loads((raw_body or b"").decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return {"ok": False, "reason": "unreadable"}
    result = handle(email_events.classify(payload), store=store, db=db)
    return {"ok": True, **result}
