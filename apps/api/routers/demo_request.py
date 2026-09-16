"""
Demo requests from the marketing site (public, NO login).

The marketing site's primary call to action is "Book a demo" — an owner
decision of 16-09-2026, taken over the self-serve free-trial funnel that
preceded it. apps/marketing is a static export with no server of its own, so
the form has to post somewhere, and this is that somewhere.

WHY THIS IS AN ENDPOINT AND NOT A THIRD-PARTY SCHEDULER
    The same decision ruled out Cal.com, Calendly and every embedded booking
    widget. A widget on the marketing site is a third party that sees every
    visitor who reaches the page, whether or not they book. This service already
    has a working transport — services/email_service.py on Resend — so a demo
    request is one more email through the same pipe.

WHY IT FAILS LOUDLY
    A demo request is a sales lead, and a lead that vanishes is worse than a
    form that says it is broken: nobody finds out, because nobody knows it was
    sent. So when the transport is unconfigured or the provider rejects the
    message, this returns success=false with a 503 and the page shows the
    visitor an email address to use instead. It never reports a send that did
    not happen. That is the same false-clean-result failure the GSTR-2B
    reconciliation and the error-masking sweep were both written to remove.

WHY IT IS THE ONLY UNAUTHENTICATED WRITE SURFACE, AND WHAT GUARDS IT
    Every other write path in this API is behind a Supabase JWT and rbac(). This
    one cannot be — the whole point is that the sender has no account. Four
    things stand in for that:

      * a HONEYPOT field ("website"), rendered off-screen and left empty by a
        human. Most form spam fills every input it finds.
      * a PER-IP RATE LIMIT, and a global one behind it so a rotating source
        cannot simply spread the load.
      * HARD LENGTH CAPS on every field, enforced by Pydantic before any of
        this code runs.
      * it touches NO tenant data. It reads nothing, writes no row, and takes
        no firm_id or client_id. There is no tenant boundary here to cross
        because the request never reaches one.

    The rate-limiter state is in-process, which is honest rather than ideal: the
    API runs as a single Render service, so one process sees every request. If
    that ever becomes several, this becomes per-instance and the limits want
    moving behind a shared store. It is written down here rather than left to be
    discovered.

Registered in main.py WITHOUT _CLIENT_GUARD, like routers/engagement_sign_public.py.
"""
import logging
import os
import re
import time
from collections import deque
from typing import Deque, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from models.common import api_response
from services import email_service

router = APIRouter(prefix="/api/public", tags=["demo_request"])
_logger = logging.getLogger("caflow.demo_request")

# Where a demo request lands. Declared in render.yaml; when it is unset the
# endpoint refuses rather than guessing an address, for the same reason it
# refuses when Resend is unconfigured — a lead sent nowhere is a lead lost
# silently.
_TO = os.environ.get("DEMO_REQUEST_TO", "")

# Sliding windows. Deliberately generous for a human and useless for a script.
_PER_IP_MAX = 3
_PER_IP_WINDOW_S = 900       # 15 minutes
_GLOBAL_MAX = 60
_GLOBAL_WINDOW_S = 3600      # 1 hour
# Bound the per-IP table so a rotating source cannot grow it without limit; the
# global window is what actually stops that source, this just stops the memory
# going with it.
_MAX_TRACKED_IPS = 4096

_by_ip: Dict[str, Deque[float]] = {}
_global: Deque[float] = deque()

# Deliberately permissive. This is a display/contact address, not a login, and a
# regex that rejects a real address costs a lead. The only thing worth catching
# is a value that is plainly not an address at all.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

# The sizes the marketing form offers. Anything else is recorded verbatim rather
# than rejected — a prospect who typed something into "other" is still a lead.
FIRM_SIZES = [
    "Solo practitioner",
    "2–5 people",
    "6–20 people",
    "21–50 people",
    "More than 50",
]


class DemoRequestIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    firm_name: str = Field(min_length=1, max_length=160)
    # Deliberately no min_length. Pydantic's own failures are raised by FastAPI
    # as {"detail": ...}, which is NOT the {success, data, error} envelope the
    # rest of this API answers in — so a length floor here would mean "a@b" got
    # one response shape and "aaa@bbb" another, for the same mistake. The caps
    # stay (they are the hard payload bound, and a 3 KB message should be
    # refused before this handler runs); the email's own validity is decided in
    # one place below, and answers in the envelope.
    email: str = Field(max_length=254)
    phone: Optional[str] = Field(default=None, max_length=32)
    firm_size: Optional[str] = Field(default=None, max_length=64)
    message: Optional[str] = Field(default=None, max_length=2000)
    # Honeypot. A human never sees this input and never fills it.
    website: Optional[str] = Field(default=None, max_length=256)


def _client_ip(request: Request) -> str:
    """Best-effort caller identity for rate limiting.

    Render terminates TLS and proxies, so request.client.host is the proxy.
    X-Forwarded-For's FIRST entry is the original client as the platform saw it.
    This is spoofable by anyone willing to set the header, which is why it is
    the per-IP limiter's input and not an authorization decision — the global
    window is what holds when this value cannot be trusted.
    """
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        first = fwd.split(",")[0].strip()
        if first:
            return first[:64]
    client = request.client
    return (client.host if client else "unknown")[:64]


def _prune(dq: Deque[float], now: float, window: float) -> None:
    while dq and now - dq[0] > window:
        dq.popleft()


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()

    _prune(_global, now, _GLOBAL_WINDOW_S)
    if len(_global) >= _GLOBAL_MAX:
        return True

    dq = _by_ip.get(ip)
    if dq is None:
        if len(_by_ip) >= _MAX_TRACKED_IPS:
            # Drop the coldest entries rather than refusing everyone. Sorting a
            # bounded table on an event this rare is cheaper than the bug of
            # letting it grow forever.
            for stale in sorted(_by_ip, key=lambda k: _by_ip[k][-1])[: _MAX_TRACKED_IPS // 4]:
                _by_ip.pop(stale, None)
        dq = _by_ip[ip] = deque()
    _prune(dq, now, _PER_IP_WINDOW_S)
    if len(dq) >= _PER_IP_MAX:
        return True

    dq.append(now)
    _global.append(now)
    return False


def _esc(value: str) -> str:
    """Escape for the HTML email body.

    Every field here is attacker-controlled free text arriving over an
    unauthenticated endpoint, and it is interpolated into HTML that a person on
    this team will open. Escaping is the whole defence.
    """
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


@router.get("/demo-request/options")
def demo_request_options():
    """The firm-size choices, so the form holds no list of its own.

    Same reasoning as GET /api/itr/forms and GET /api/rcm-documents/registration-states:
    one vocabulary, served, rather than a copy in the browser that drifts.
    """
    return api_response(True, {"firm_sizes": FIRM_SIZES})


@router.post("/demo-request")
def create_demo_request(body: DemoRequestIn, request: Request):
    # The honeypot is checked first and answers 200 with success=true. Telling a
    # bot it was detected teaches whoever wrote it to stop filling the field.
    if (body.website or "").strip():
        _logger.info("demo request rejected — honeypot filled")
        return api_response(True, {"received": True})

    email = body.email.strip()
    if not _EMAIL_RE.match(email):
        return JSONResponse(
            status_code=422,
            content=api_response(False, None, "That doesn't look like an email address."),
        )

    if _rate_limited(_client_ip(request)):
        _logger.warning("demo request rate-limited")
        return JSONResponse(
            status_code=429,
            content=api_response(
                False, None,
                "Too many requests from here just now. Please email us instead.",
            ),
        )

    if not _TO:
        # Configuration, not the visitor's problem — but it must not look like
        # a success. The true cause goes to the log, the visitor gets a way
        # through.
        _logger.error(
            "Demo request NOT delivered — DEMO_REQUEST_TO is unset. "
            "from=%r firm=%r", email, body.firm_name,
        )
        return JSONResponse(
            status_code=503,
            content=api_response(
                False, None,
                "We couldn't send that just now — please use the email address "
                "below and we'll come straight back to you.",
            ),
        )

    rows = [
        ("Name", body.name.strip()),
        ("Firm", body.firm_name.strip()),
        ("Email", email),
        ("Phone", (body.phone or "").strip() or "—"),
        ("Firm size", (body.firm_size or "").strip() or "—"),
    ]
    html = (
        "<p><strong>New demo request from the PracticeSync website.</strong></p>"
        "<table cellpadding='6' style='border-collapse:collapse'>"
        + "".join(
            f"<tr><td style='color:#64748B'>{_esc(label)}</td>"
            f"<td><strong>{_esc(value)}</strong></td></tr>"
            for label, value in rows
        )
        + "</table>"
    )
    note = (body.message or "").strip()
    if note:
        html += f"<p style='margin-top:16px'><strong>What they said</strong></p><p>{_esc(note)}</p>"

    sent = email_service._send(
        _TO,
        f"Demo request — {body.firm_name.strip()[:80]}",
        html,
    )
    if not sent:
        # email_service has already logged the provider's real reason. Never
        # repeat it to the caller: it names the provider and can carry the
        # sending domain's configuration.
        return JSONResponse(
            status_code=503,
            content=api_response(
                False, None,
                "We couldn't send that just now — please use the email address "
                "below and we'll come straight back to you.",
            ),
        )

    _logger.info("demo request delivered firm=%r", body.firm_name.strip()[:80])
    return api_response(True, {"received": True})
