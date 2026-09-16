"""
Where this app lives on the public internet — one definition, not four.

WHY THIS EXISTS
    The deployed origin was written as a literal in four places:

      * main.py                        -> https://caflow-ai.pages.dev
      * routers/onboarding.py          -> https://caflow-ai.pages.dev
      * services/portal_access_service -> https://caflow-ai.pages.dev/portal/activate
      * services/portal_access_service -> practicesync.com/portal/login  (email body)

    The first three are RIGHT. `caflow-ai.pages.dev` is the live subdomain for
    apps/web: a Cloudflare Pages subdomain is fixed at project creation and does
    not follow a dashboard rename, so the project reading `practicesync-ai` in
    the dashboard still serves from `caflow-ai.pages.dev`. apps/marketing/README
    says so explicitly, and DNS agrees — `practicesync-ai.pages.dev` does not
    resolve at all.

    The fourth is wrong. `practicesync.com` is the intended marketing domain,
    not a domain this project serves from today (the marketing site is on
    `practicesync.pages.dev`), and it had no environment variable behind it —
    so every client invitation told its recipient to sign in somewhere that is
    not the app, and no dashboard setting could correct it.

    Four literals for one fact is really four facts that can disagree, which is
    how one of them came to be wrong while the others were fine. This module is
    the single place that knows the answer, so attaching a custom domain later
    is one environment variable rather than a code hunt.

HOW TO POINT THIS AT A REAL DOMAIN
    Set FRONTEND_URL. Everything below follows from it. PORTAL_BASE_URL exists
    only to override the activation path independently, and is not needed in
    the normal case.
"""
import os

# The live Cloudflare Pages subdomain for apps/web. Used ONLY when FRONTEND_URL
# is unset. Do NOT "modernise" this to match the dashboard label — the label is
# cosmetic and `practicesync-ai.pages.dev` does not exist.
#
# This is deliberately the single occurrence of a hard-coded host in the
# backend; tests/test_public_urls_have_one_source.py fails if another appears.
_FALLBACK_ORIGIN = "https://caflow-ai.pages.dev"

# The live Cloudflare Pages subdomain for apps/marketing, which is a SEPARATE
# Pages project from apps/web and therefore a separate origin. Used only when
# MARKETING_URL is unset.
#
# It has to be known here because the marketing site makes exactly one
# cross-origin request to this API — POST /api/public/demo-request, the "Book a
# demo" form — and a browser will not send it unless this origin is in the CORS
# allow-list. That is also why this host is in core/urls.py rather than beside
# the endpoint: tests/test_public_urls_have_one_source.py forbids a public host
# anywhere else, and it is right to.
_MARKETING_FALLBACK_ORIGIN = "https://practicesync.pages.dev"


def frontend_base() -> str:
    """The app's public origin, without a trailing slash.

    Empty or slash-only values fall through to the default rather than
    producing "//portal/activate", which is a valid-looking URL that resolves
    somewhere nobody intended.
    """
    raw = (os.environ.get("FRONTEND_URL") or "").strip().rstrip("/")
    return raw or _FALLBACK_ORIGIN


def portal_activate_url() -> str:
    """Where a client-portal invitation link points.

    PORTAL_BASE_URL still wins if set, because a deployment may serve the
    portal from somewhere other than the main app. Unset — the normal case —
    it derives from FRONTEND_URL so the two cannot disagree.
    """
    explicit = (os.environ.get("PORTAL_BASE_URL") or "").strip().rstrip("/")
    return explicit or f"{frontend_base()}/portal/activate"


def portal_login_url() -> str:
    """Where a client signs in once their account exists.

    This is the one that was actually broken: the invitation email named
    `practicesync.com` as a bare literal with no override, so it was wrong in
    every invitation at once and unfixable without a deploy. The portal is
    served by apps/web, so its login page is on the same origin as everything
    else here.
    """
    return f"{frontend_base()}/portal/login"


def marketing_base() -> str:
    """The MARKETING site's public origin, without a trailing slash.

    A different Cloudflare Pages project from the app, so a different origin,
    so its own variable. Blank falls through to the default for the same reason
    frontend_base() does: an empty dashboard field is easier to create than to
    notice, and an empty origin in a CORS allow-list silently matches nothing.
    """
    raw = (os.environ.get("MARKETING_URL") or "").strip().rstrip("/")
    return raw or _MARKETING_FALLBACK_ORIGIN


def default_allowed_origins() -> str:
    """CORS fallback: local dev plus the two origins this API actually serves.

    Only applies when ALLOWED_ORIGINS is unset. Kept in the same shape the
    parser expects (comma-separated) rather than a list, so the caller's
    parsing stays the single code path for both configured and default values.

    THE MARKETING ORIGIN IS IN HERE AND THAT IS NOT COSMETIC. apps/marketing
    posts the "Book a demo" form to /api/public/demo-request, and a browser
    refuses a cross-origin POST whose origin is not on this list — so a demo
    request from the live site would fail in the browser before reaching any of
    the endpoint's own careful refusals. Local dev gets both ports because the
    two sites run side by side (apps/web on 3000, apps/marketing on 3001).

    ⚠️ This is the fallback only. A deployment that SETS ALLOWED_ORIGINS
    overrides all of it, and must list the marketing origin itself.
    """
    return (
        "http://localhost:3000,http://localhost:3001,"
        f"{frontend_base()},{marketing_base()}"
    )
