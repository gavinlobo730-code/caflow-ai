"""The email provider's delivery events, read (ops-21).

Two questions, both pure: is this request really from the provider, and what is it telling us.

WHO SIGNED IT
    Resend delivers webhooks through Svix, and a delivery carries three headers: `svix-id`,
    `svix-timestamp` (whole seconds) and `svix-signature` (a space-separated list of
    `<version>,<base64>`). The signed content is `"{svix-id}.{svix-timestamp}.{raw body}"`, the key is
    the base64-decoded part of the endpoint's signing secret after its `whsec_` prefix, and the
    signature is the base64 of the HMAC-SHA256 of the content. A request is genuine if ANY `v1`
    entry matches (the list carries several while a secret is being rotated) and its timestamp is
    within five minutes of now, which is what stops a captured delivery being replayed later.

    `[S]`-GRADED. Egress is refused in this environment, so the scheme is written from the
    published Svix / Standard Webhooks specification as recalled, not read off the provider's page
    today, and `tests/test_the_practices_mail_waits_in_an_outbox_and_a_bounce_marks_the_address.py`
    pins it with vectors computed in the test from the specification. A human confirms it once, by
    sending Resend's "test event" from the dashboard to the live endpoint and seeing a 200: until
    then a mismatch fails CLOSED (a 400 and nothing written), which is the safe way to be wrong.
    The comparison is `hmac.compare_digest` on bytes, never `==`.

WHAT IT SAYS
    `email.bounced` carries `data.bounce.type`: `Permanent` is an address that cannot receive mail
    (a hard bounce) and the only bounce that marks an address bad; `Transient` (a full mailbox, a
    busy server) and `Undetermined` are a bad moment, recorded in the log and nothing more, and a
    bounce that says nothing about its type is treated as one of those, because suppressing an
    address on an ambiguity costs a real person their mail. `email.complained` is a recipient
    pressing "spam" and always marks the address: it is the strongest statement a recipient makes
    and mailing them again is how a sending domain loses its reputation. Anything else
    (`email.sent`, `email.delivered`, `email.opened` ...) is ignored.
    `[S]`: the event names and the `bounce.type` values are from the provider's documentation as
    recalled.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Mapping, Optional

#: How far a delivery's timestamp may be from now, either side. Svix's own default.
SIGNATURE_TOLERANCE_SECONDS = 300
_MAX_ADDRESSES = 50

HARD_BOUNCE = "hard_bounce"
SOFT_BOUNCE = "soft_bounce"
COMPLAINT = "complaint"
IGNORED = "ignored"


def decode_secret(secret: str) -> Optional[bytes]:
    """The signing key from an endpoint secret (`whsec_` + base64), or None if it is not one."""
    text = (secret or "").strip()
    if text.startswith("whsec_"):
        text = text[len("whsec_"):]
    if not text:
        return None
    try:
        key = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        return None
    return key or None


def sign(secret: str, svix_id: str, timestamp: str, body: bytes) -> str:
    """`v1,<signature>` for a body - what the provider would send. Used by the tests, and
    only here so the verifier and the test cannot disagree about the scheme."""
    key = decode_secret(secret)
    if key is None:
        raise ValueError("not a signing secret")
    content = f"{svix_id}.{timestamp}.".encode("utf-8") + body
    return "v1," + base64.b64encode(hmac.new(key, content, hashlib.sha256).digest()).decode("ascii")


@dataclass(frozen=True)
class Verification:
    ok: bool
    reason: str


def verify(secret: str, headers: Mapping[str, str], body: bytes, *,
           now: Optional[float] = None) -> Verification:
    """Is this delivery signed by the holder of `secret`, and fresh? `headers` are lower-cased.

    The reason is for a log line and a counter, never for the caller: a stranger is told
    "rejected" and nothing more."""
    key = decode_secret(secret)
    if key is None:
        return Verification(False, "secret_unusable")
    svix_id = (headers.get("svix-id") or "").strip()
    timestamp = (headers.get("svix-timestamp") or "").strip()
    signatures = (headers.get("svix-signature") or "").split()
    if not svix_id or not timestamp or not signatures:
        return Verification(False, "missing_headers")
    try:
        sent_at = int(timestamp)
    except ValueError:
        return Verification(False, "bad_timestamp")
    moment = time.time() if now is None else now
    if abs(moment - sent_at) > SIGNATURE_TOLERANCE_SECONDS:
        return Verification(False, "stale_timestamp")
    expected = base64.b64encode(hmac.new(
        key, f"{svix_id}.{timestamp}.".encode("utf-8") + (body or b""), hashlib.sha256).digest())
    for entry in signatures:
        version, _, candidate = entry.partition(",")
        if version == "v1" and candidate and hmac.compare_digest(
                candidate.encode("utf-8"), expected):
            return Verification(True, "ok")
    return Verification(False, "bad_signature")


@dataclass(frozen=True)
class Event:
    kind: str
    event_type: str
    addresses: tuple
    message_id: Optional[str]


def _addresses(raw: object) -> tuple:
    items = raw if isinstance(raw, list) else [raw]
    seen: list[str] = []
    for item in items:
        # Resend lists recipients as bare addresses, but a display form ("Name <a@b>") is
        # reduced to the address rather than refused.
        text = str(item or "").strip()
        if "<" in text and ">" in text:
            text = text[text.rindex("<") + 1:text.rindex(">")]
        text = text.strip().lower()
        if "@" in text and text not in seen:
            seen.append(text)
    return tuple(seen[:_MAX_ADDRESSES])


def classify(payload: object) -> Event:
    """What a delivery event means for an address. Anything unreadable is IGNORED, never an
    address marked bad on a guess."""
    if not isinstance(payload, dict):
        return Event(IGNORED, "", (), None)
    event_type = str(payload.get("type") or "")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    message_id = str(data.get("email_id")) if data.get("email_id") else None
    addresses = _addresses(data.get("to"))
    if event_type == "email.complained":
        return Event(COMPLAINT, event_type, addresses, message_id)
    if event_type == "email.bounced":
        bounce = data.get("bounce") if isinstance(data.get("bounce"), dict) else {}
        kind = HARD_BOUNCE if str(bounce.get("type") or "").strip().lower() == "permanent" else SOFT_BOUNCE
        return Event(kind, event_type, addresses, message_id)
    return Event(IGNORED, event_type, (), message_id)
