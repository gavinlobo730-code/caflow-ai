"""Who is on the other end of a request, decided by the last proxy hop WE trust.

WHY THIS EXISTS (SECURITY-PRIVACY-25)
    Two public surfaces took the address from the FIRST entry of X-Forwarded-For:
    the demo-request rate limiter and the `signed_ip` recorded beside a client's
    e-signature on an engagement letter. The first entry is the one a caller
    writes themselves. Every proxy APPENDS the address of whoever connected to
    it, so the header a caller sends arrives as

        <whatever the caller wrote>, <the real client>, <proxy>, ...

    and the leftmost value is the caller's own. `demo_request._client_ip` said so
    in its own comment ("spoofable by anyone willing to set the header"), and then
    used it to key a limiter — so rotating the header defeated the limit. For the
    signing evidence it is worse: the address stored next to a signature was
    whatever the signer, or anyone holding the link, chose to type.

THE RULE
    Count from the RIGHT, because the right-hand entries are the ones OUR
    infrastructure wrote. With N trusted proxies in front of the app the client is
    the Nth entry from the right; everything to its left is unverified and
    ignored. N is `TRUSTED_PROXY_HOPS` (default 1).

    Fewer entries than N means the request did not pass through all the proxies
    we were told about, so the whole chain is ours and the leftmost entry is the
    best answer there is. No header at all means a direct connection, and the
    answer is the socket's own peer.

WHY THE DEFAULT IS 1 AND NOT A GUESS AT RENDER'S TOPOLOGY
    The error is asymmetric, and the default takes the side that is never
    attacker-controlled. Too SMALL a count names a proxy (Render's own edge)
    instead of the client: the per-IP limiter is coarser than intended and the
    recorded signing address is not the signer's — wrong, but not something a
    caller can choose. Too LARGE a count reads into the caller's own entries and
    is exactly the defect being fixed. How many hops Render puts in front of a
    service was recalled, not read (medium-low confidence), and `[S]`-grade
    claims do not get to set a security default.

    So it is a setting, and the two facts that let an operator set it right are
    kept: `forwarded_for_evidence` records the raw chain on the signing event, and
    the posture of a live deployment can be checked with one request — send
    `X-Forwarded-For: 203.0.113.9` to the API and read what the signing event
    (or a log line) shows beside it. If the chain ends in an address that is a
    proxy's, raise TRUSTED_PROXY_HOPS by one.

WHAT IT IS NOT
    Not an authorization decision. It keys a rate limiter and labels evidence;
    nothing grants access on the strength of an address.
"""
from __future__ import annotations

import ipaddress
import os
from typing import Optional

DEFAULT_TRUSTED_PROXY_HOPS = 1
#: A deployment does not sit behind more than a handful of proxies; a larger value
#: is a typo, and reading it would reach into the caller's own entries.
_MAX_TRUSTED_PROXY_HOPS = 8
#: Only the right-hand end of the header is ever read.
_MAX_ENTRIES = 32
#: What `forwarded_for_evidence` keeps. The RIGHT end survives truncation, because
#: that is the end the trusted hops wrote.
_EVIDENCE_CAP = 256


def trusted_proxy_hops() -> int:
    """TRUSTED_PROXY_HOPS, or the default when it is unset, blank or not 0..8.

    0 means "no proxy in front": the socket's peer is the client and the header
    is never read. An unreadable value falls to the DEFAULT, not to a larger
    number — see the module header for which way the error must run.
    """
    raw = os.environ.get("TRUSTED_PROXY_HOPS", "").strip()
    if not raw:
        return DEFAULT_TRUSTED_PROXY_HOPS
    try:
        hops = int(raw)
    except ValueError:
        return DEFAULT_TRUSTED_PROXY_HOPS
    if 0 <= hops <= _MAX_TRUSTED_PROXY_HOPS:
        return hops
    return DEFAULT_TRUSTED_PROXY_HOPS


def _as_ip(value: str) -> Optional[str]:
    """The canonical form of an address, or None if it is not one.

    Tolerates the `host:port` and `[v6]:port` spellings some proxies write, and
    canonicalises (`::ffff:1.2.3.4`, `0:0:...:1`) so two spellings of one address
    are one limiter key.
    """
    v = (value or "").strip().strip('"')
    if v.startswith("["):
        host = v[1:].split("]", 1)[0]
    elif v.count(":") == 1:
        host = v.split(":", 1)[0]
    else:
        host = v
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


def _chain(request) -> list[str]:
    raw = request.headers.get("x-forwarded-for", "") or ""
    entries = [e.strip() for e in raw.split(",")]
    return [e for e in entries if e][-_MAX_ENTRIES:]


def _peer(request) -> Optional[str]:
    client = getattr(request, "client", None)
    return client.host if client else None


def client_ip(request) -> Optional[str]:
    """The caller's address as far as our own proxies can vouch for it.

    `None` only when there is neither a usable header entry nor a socket peer.
    Accepts anything with `.headers` (a mapping with lower-case keys, as
    Starlette's is) and `.client`.
    """
    hops = trusted_proxy_hops()
    if hops:
        chain = _chain(request)
        if chain:
            chosen = _as_ip(chain[max(len(chain) - hops, 0)])
            if chosen:
                return chosen
    return _peer(request)


def forwarded_for_evidence(request) -> Optional[str]:
    """The raw X-Forwarded-For chain as received, capped, for the record.

    UNVERIFIED and labelled so wherever it is stored: it is what the caller's
    connection arrived with, kept so that a human can reconstruct the real client
    if `client_ip` was configured for the wrong number of hops. Never used for a
    decision.
    """
    raw = (request.headers.get("x-forwarded-for", "") or "").strip()
    return raw[-_EVIDENCE_CAP:] if raw else None
