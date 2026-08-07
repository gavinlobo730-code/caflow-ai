"""
Supporting documents on a bank transaction (Tier 1.8).

A bank line is a number and a narration. The receipt, the vendor invoice, the
cheque image — the things that justify how it was coded — have had nowhere to
live, so they end up in somebody's email and the reason for a coding is lost the
moment that person moves on.

WHY THE URL IS VALIDATED AT ALL
    An attachment is a name and a URL that the UI renders as a link. A stored
    `javascript:` URL becomes script execution the moment a CA clicks it, and a
    `data:` URL can carry an HTML document that runs in the app's own origin —
    both are stored XSS, delivered by the person who uploaded the "receipt".

    So the scheme vocabulary is closed rather than sanitised. Sanitising is a
    losing game (`java\\tscript:`, `JaVaScRiPt:`, percent-encoding); accepting
    only http/https is a rule with no edge cases.

WHY NAMES ARE BOUNDED AND STRIPPED OF PATH SEPARATORS
    The name is display text, but it is also what a download would be called.
    A name containing `../` or a leading `/` is asking to be interpreted as a
    path by something downstream. Rejecting them here costs nothing.

Pure and side-effect free.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import urlparse

# Matches the CHECK in migration 259. More than a handful of documents on one
# bank line means the line is doing too much work, not that the limit is wrong.
MAX_ATTACHMENTS = 20
MAX_NAME_LENGTH = 255
MAX_URL_LENGTH = 2048

# A closed vocabulary, deliberately. See the module docstring: sanitising
# dangerous schemes is a losing game; allowing exactly two is not.
ALLOWED_SCHEMES = ("http", "https")


class AttachmentError(ValueError):
    """An attachment that cannot be stored, with a message meant for a CA."""


@dataclass(frozen=True)
class Attachment:
    name: str
    url: str

    def to_dict(self) -> dict:
        return {"name": self.name, "url": self.url}


def _validate_url(url: str) -> str:
    text = (url or "").strip()
    if not text:
        raise AttachmentError("An attachment needs a link.")
    if len(text) > MAX_URL_LENGTH:
        raise AttachmentError(f"That link is too long (limit {MAX_URL_LENGTH} characters).")
    try:
        parsed = urlparse(text)
    except ValueError:
        raise AttachmentError("That link could not be read as a URL.")
    # `scheme` is already lower-cased and whitespace-stripped by urlparse, which
    # is what makes an allow-list safe against JaVaScRiPt: and friends.
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise AttachmentError(
            "An attachment link must be an http or https address. "
            "Links that can run code are not accepted.")
    if not parsed.netloc:
        raise AttachmentError("That link has no address in it.")
    return text


def _validate_name(name: str) -> str:
    text = (name or "").strip()
    if not text:
        raise AttachmentError("An attachment needs a name.")
    if len(text) > MAX_NAME_LENGTH:
        raise AttachmentError(f"That name is too long (limit {MAX_NAME_LENGTH} characters).")
    # The name is display text AND what a download would be called. A path
    # separator in it is asking to be interpreted as a path downstream.
    if "/" in text or "\\" in text or text.startswith("."):
        raise AttachmentError(
            "An attachment name cannot contain a path — use a plain file name.")
    return text


def parse_attachment(raw: dict) -> Attachment:
    if not isinstance(raw, dict):
        raise AttachmentError("Each attachment must be a name and a link.")
    return Attachment(name=_validate_name(raw.get("name")),
                      url=_validate_url(raw.get("url")))


def parse_attachments(raw: Optional[Iterable]) -> list[Attachment]:
    """Validate a whole attachment list. Order is preserved."""
    if raw is None:
        return []
    if isinstance(raw, (str, bytes, dict)):
        raise AttachmentError("Attachments must be a list.")
    items = list(raw)
    if len(items) > MAX_ATTACHMENTS:
        raise AttachmentError(
            f"A transaction can carry at most {MAX_ATTACHMENTS} attachments.")
    out: list[Attachment] = []
    for i, r in enumerate(items):
        try:
            out.append(parse_attachment(r))
        except AttachmentError as e:
            raise AttachmentError(f"Attachment {i + 1}: {e}")
    return out


def add(existing: Optional[Iterable], name: str, url: str) -> list[dict]:
    """Append one attachment to a stored list, validating the WHOLE result.

    Re-validating what is already there is deliberate: a row could have been
    written before a rule existed, and silently carrying an invalid entry
    forward because "only the new one is checked" is how a bad value survives a
    tightening.
    """
    current = parse_attachments(existing)
    fresh = parse_attachment({"name": name, "url": url})
    if len(current) + 1 > MAX_ATTACHMENTS:
        raise AttachmentError(
            f"A transaction can carry at most {MAX_ATTACHMENTS} attachments.")
    # The same URL twice is almost always a double-click, not two documents.
    if any(a.url == fresh.url for a in current):
        raise AttachmentError("That document is already attached.")
    return [a.to_dict() for a in current] + [fresh.to_dict()]


def remove(existing: Optional[Iterable], url: str) -> list[dict]:
    """Drop one attachment by URL. Absent is not an error — removing something
    already gone leaves the list in the state the caller asked for."""
    current = parse_attachments(existing)
    target = (url or "").strip()
    return [a.to_dict() for a in current if a.url != target]
