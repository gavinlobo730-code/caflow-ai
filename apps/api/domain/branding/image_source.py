"""
Which URLs the server is allowed to fetch a branding image from.

WHAT WAS WRONG (no finding; the 12 September probe pass found it)
    `services/invoice_pdf_service._remote_image` fetches any `http(s)` URL,
    server-side, with `follow_redirects=True`, on every fee-invoice render. The
    URLs are free-form strings: `logo_url`, `secondary_logo_url` and
    `upi_qr_url` are `Optional[str]` on the branding models, the settings screen
    offers a text box for the first, and `PUT /api/settings/branding` validated
    the colours and the font family and nothing else.

    So a Partner could point the API — which runs in Singapore, inside a
    provider network — at `169.254.169.254`, at `localhost`, or at any internal
    address, and have it issue the request when a PDF is built. It is blind
    (the body is decoded as an image and every failure returns None by design)
    and bounded (3 seconds, 2 MB), so it is a probe primitive rather than an
    exfiltration path — but the missing control costs a few lines and the
    module next door already had the right instinct: `_accent_colour`
    re-validates on the way out "rather than trusting a row written before that
    validation".

WHAT THIS REFUSES, AND WHAT IT DELIBERATELY DOES NOT
    * A scheme that is not http or https.
    * A host that IS a private, loopback, link-local, reserved or unspecified
      address — 127.0.0.1, ::1, 10/8, 172.16/12, 192.168/16, 169.254/16
      (which is where every cloud metadata service lives), and the rest.
    * A host that RESOLVES to one. Checked with `getaddrinfo`, and EVERY
      address it returns must be public — a name with one public and one
      private answer is refused, because which one the client picks is not
      ours to predict.
    * A redirect to any of the above. The caller must follow redirects itself,
      one hop at a time, re-asking this — `follow_redirects=True` performs the
      request before anything can inspect where it went, which is the whole
      vector.

    It does NOT restrict the host to the firm's own storage bucket, and that is
    deliberate: the settings screen has always offered a free-text logo URL, so
    a firm hosting its logo on its own site is a supported flow and narrowing
    to the bucket would break it silently.

    It cannot stop DNS REBINDING — a name that resolves publicly here and
    privately when httpx resolves it again a moment later. Closing that needs
    the resolved address pinned into the connection, which is a bigger change
    than this risk warrants; the single 3-second request makes the window
    small, and it is written down rather than left implied.
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Optional
from urllib.parse import urlparse

#: Names that are never a legitimate branding host, whatever they resolve to.
_FORBIDDEN_NAMES = frozenset({
    "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback",
    # The cloud metadata endpoints, by their well-known names as well as by
    # address — the address check below catches 169.254.169.254 anyway, but a
    # provider that fronts it with a name should not need a code change.
    "metadata", "metadata.google.internal", "metadata.goog",
    "instance-data",
})

#: Suffixes that name an internal zone by convention.
_FORBIDDEN_SUFFIXES = (".internal", ".local", ".localdomain", ".localhost")


def _as_ip(text: str):
    """The address, or None when `text` is a name rather than a literal.

    Written as a function returning None rather than a `try/except ValueError:
    pass`, which is what this was: the shape reads as a swallowed failure and
    `tests/test_soft_failure_visibility.py` counts it as one, correctly — the
    fact that here it was control flow is not something a reader (or an AST)
    can tell from the shape.
    """
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def _address_is_public(addr: str) -> bool:
    ip = _as_ip(addr)
    if ip is None:
        return False
    return not (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def refusal(url: Optional[str]) -> Optional[str]:
    """Why this URL must not be fetched server-side, or None.

    A sentence rather than a boolean, so a caller can log or report WHICH rule
    refused it. Never raises: a URL that cannot even be parsed is refused, not
    an exception in the middle of building a document.
    """
    text = str(url or "").strip()
    if not text:
        return "No image URL."
    try:
        parsed = urlparse(text)
    except Exception:                                              # noqa: BLE001
        return "The image URL could not be read."
    if parsed.scheme not in ("http", "https"):
        return f"Only http and https are fetched; this is '{parsed.scheme or 'no scheme'}'."
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        return "The image URL names no host."
    if host in _FORBIDDEN_NAMES or host.endswith(_FORBIDDEN_SUFFIXES):
        return f"'{host}' is an internal name and is not fetched."

    # A literal address is answered without asking a resolver.
    if _as_ip(host) is not None:
        return (None if _address_is_public(host)
                else f"'{host}' is a private or loopback address and is not fetched.")

    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except Exception:                                              # noqa: BLE001
        # A name that does not resolve cannot be fetched anyway. Refusing here
        # rather than letting httpx fail keeps the reason readable and saves
        # the request.
        return f"'{host}' could not be resolved."
    addresses = {str(info[4][0]) for info in infos}
    private = sorted(a for a in addresses if not _address_is_public(a))
    if private:
        return (f"'{host}' resolves to {private[0]}, which is a private or "
                f"loopback address, and is not fetched.")
    return None


def is_allowed(url: Optional[str]) -> bool:
    """`refusal(url) is None`, for a caller that only needs the verdict."""
    return refusal(url) is None
