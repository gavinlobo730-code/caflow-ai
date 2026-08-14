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


def default_allowed_origins() -> str:
    """CORS fallback: local dev plus wherever the frontend actually is.

    Only applies when ALLOWED_ORIGINS is unset. Kept in the same shape the
    parser expects (comma-separated) rather than a list, so the caller's
    parsing stays the single code path for both configured and default values.
    """
    return f"http://localhost:3000,{frontend_base()}"
