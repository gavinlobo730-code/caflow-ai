"""
The app's public origin is defined once, in core/urls.py, and nowhere else.

THE MISTAKE THIS EXISTS TO CATCH
    Four files each carried their own literal for "where this app lives", and
    exactly one of them was wrong:

      main.py                     -> https://caflow-ai.pages.dev        correct
      routers/onboarding.py       -> https://caflow-ai.pages.dev        correct
      portal_access_service.py    -> .../portal/activate                correct
      portal_access_service.py    -> practicesync.com/portal/login      WRONG

    That is the shape of the problem. Three copies agreeing lends the fourth
    an air of correctness it had not earned: `practicesync.com` is the intended
    marketing domain, not an origin this project serves from, and it had no
    environment variable behind it — so every client invitation named the wrong
    sign-in host, and no dashboard setting could fix it.

    Note the trap this file must NOT fall into. `caflow-ai.pages.dev` looks
    stale next to a Cloudflare project labelled `practicesync-ai`, and it is
    not: a Pages subdomain is fixed at project creation and does not follow a
    dashboard rename. `practicesync-ai.pages.dev` does not resolve. Anyone
    "tidying up" that host would take the whole app's links down, which is why
    the constant in core/urls.py carries a comment saying so.

WHY A LITERAL SCAN AND NOT JUST BEHAVIOUR TESTS
    Behaviour tests below pin what core/urls.py returns. They cannot stop
    someone adding a fifth literal in a new file next month, which is the
    actual failure mode — nobody set out to hardcode a stale host the first
    four times either.
"""
import os
import re
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
URLS_MODULE = API_ROOT / "core" / "urls.py"

_URL_ENV = ("FRONTEND_URL", "PORTAL_BASE_URL")

# Hosts that must not appear outside core/urls.py: any Cloudflare Pages project
# and the bare domain that was written into the invitation email.
_HARDCODED_HOST = re.compile(r"pages\.dev|practicesync\.com", re.I)

_SKIP_DIRS = {"tests", ".venv", "venv", "__pycache__", "node_modules"}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """These helpers read the environment at call time, so a value leaking in
    from the developer's shell (or another test) would silently invalidate
    every default-case assertion here."""
    for name in _URL_ENV:
        monkeypatch.delenv(name, raising=False)


def _sources():
    for path in API_ROOT.rglob("*.py"):
        if set(path.parts) & _SKIP_DIRS or path == URLS_MODULE:
            continue
        try:
            yield path, path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


def test_no_other_module_hardcodes_a_public_host():
    offenders = []
    for path, src in _sources():
        for line_no, line in enumerate(src.splitlines(), 1):
            if _HARDCODED_HOST.search(line):
                offenders.append(f"{path.relative_to(API_ROOT).as_posix()}:{line_no}  {line.strip()}")

    assert not offenders, (
        "these files hardcode a public host instead of asking core/urls.py:\n  "
        + "\n  ".join(offenders)
        + "\n\nUse frontend_base() / portal_activate_url() / portal_login_url() "
          "so pointing the app at a domain stays one environment variable."
    )


def test_the_scan_would_actually_catch_something():
    """Vacuity guard. If the pattern stops matching, the check above passes for
    every possible repository state."""
    assert _HARDCODED_HOST.search('base = "https://caflow-ai.pages.dev/portal"')
    assert _HARDCODED_HOST.search("sign in at practicesync.com/portal/login")
    assert not _HARDCODED_HOST.search('base = f"{frontend_base()}/portal/activate"')


def test_core_urls_is_allowed_to_name_the_default():
    """The exclusion above is deliberate, not an oversight — assert the default
    really does live there, so the scan is not passing because the constant was
    deleted and every caller now returns an empty string."""
    assert _HARDCODED_HOST.search(URLS_MODULE.read_text(encoding="utf-8"))


def test_frontend_url_drives_every_derived_url(monkeypatch):
    from core.urls import (frontend_base, portal_activate_url,
                           portal_login_url, default_allowed_origins)
    monkeypatch.setenv("FRONTEND_URL", "https://books.example-ca.in")

    assert frontend_base() == "https://books.example-ca.in"
    assert portal_activate_url() == "https://books.example-ca.in/portal/activate"
    assert portal_login_url() == "https://books.example-ca.in/portal/login"
    assert default_allowed_origins() == \
        "http://localhost:3000,https://books.example-ca.in"


@pytest.mark.parametrize("configured", ["https://x.example.com/", "https://x.example.com///"])
def test_a_trailing_slash_does_not_produce_a_double_slash(monkeypatch, configured):
    """"https://x/" + "/portal/activate" is a URL that looks fine in a dashboard
    and resolves somewhere else in a browser. Whoever sets this will paste it
    with whatever their address bar gave them."""
    from core.urls import portal_activate_url
    monkeypatch.setenv("FRONTEND_URL", configured)

    assert portal_activate_url() == "https://x.example.com/portal/activate"


@pytest.mark.parametrize("blank", ["", "   ", "/"])
def test_a_blank_frontend_url_falls_back_rather_than_building_a_bare_path(
        monkeypatch, blank):
    """An empty variable is easier to create than to notice — a cleared
    dashboard field, a `KEY=` line. Treat it as unset; do NOT let it through to
    produce "/portal/activate", which is a link to nowhere in an email."""
    from core.urls import portal_activate_url
    monkeypatch.setenv("FRONTEND_URL", blank)

    assert portal_activate_url().startswith("https://")


def test_portal_base_url_still_overrides_the_derived_path(monkeypatch):
    """Kept as a real escape hatch: a deployment may serve the portal from a
    different host than the app. It must beat the derived value."""
    from core.urls import portal_activate_url
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    monkeypatch.setenv("PORTAL_BASE_URL", "https://portal.example.com/activate")

    assert portal_activate_url() == "https://portal.example.com/activate"


def test_the_invitation_email_carries_the_configured_urls(monkeypatch):
    """The end-to-end point of all of this: what a real client receives. Asserts
    against the rendered body, because that is the artefact that was wrong."""
    monkeypatch.setenv("FRONTEND_URL", "https://books.example-ca.in")
    sent = {}

    import services.email_service as email_service
    monkeypatch.setattr(email_service, "_send",
                        lambda to, subject, html: sent.update(to=to, html=html))

    from services.portal_access_service import _send_invite_email
    _send_invite_email("client@example.com", "c1", "f1", "tok-123")

    assert "https://books.example-ca.in/portal/activate?invite=tok-123" in sent["html"]
    assert "https://books.example-ca.in/portal/login" in sent["html"]
    assert "practicesync.com" not in sent["html"]
