"""
Guards on apps/marketing that the marketing site cannot enforce for itself.

WHY THESE LIVE HERE. apps/marketing has no test runner of its own — it lints,
typechecks and builds, and that is all. These four things are each a defect that
ships silently and that CI would otherwise never see, so they are asserted from
the backend suite, which is one of the two required checks on `main`. It is the
same reasoning as tests/test_the_browser_fallback_speaks_the_engines_vocabulary.py:
a guard written inside the thing it guards passes whenever the thing and its
copy drift together.

They read files, not a running site, so they cost nothing and cannot flake.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
MARKETING = REPO / "apps" / "marketing"
GLOBALS_CSS = MARKETING / "app" / "globals.css"


def _sources():
    """Every .tsx/.ts under app/ and components/ — the site's own copy."""
    for sub in ("app", "components"):
        for path in (MARKETING / sub).rglob("*"):
            if path.suffix in {".tsx", ".ts"} and path.is_file():
                yield path, path.read_text(encoding="utf-8")


def _rel(path: Path) -> str:
    return path.relative_to(MARKETING).as_posix()


# ── 1. Manrope renders "(c)" as "©" ──────────────────────────────────────────

def test_clause_letters_do_not_become_a_copyright_symbol():
    """Manrope ships "(c)" → "©" as a COMMON ligature, so it fires by default.

    This site is about Indian tax law and clause letters are everywhere in the
    copy — GSTR-3B Table 3.1 row (c), §16(2)(c), §49(5)(c), §139(1)(a). It was
    live: the GSTR-3B screen in the homepage's product showcase rendered its
    row (c) as "© Nil-rated / Exempt".

    `font-feature-settings` does NOT switch it off. Measured in the built site,
    "(c)" is 12.7px wide under "calt" 0, "rlig" 0 and `normal` alike, and only
    `font-variant-ligatures` widens it to 18.6px (three separate glyphs). So the
    property below is the fix, and nothing else is.
    """
    css = GLOBALS_CSS.read_text(encoding="utf-8")
    assert re.search(r"font-variant-ligatures:\s*(none|no-common-ligatures)", css), (
        "app/globals.css must set font-variant-ligatures to none or "
        "no-common-ligatures on the body. Without it Manrope renders every "
        "'(c)' in the site's statutory copy as '©'."
    )


def test_the_site_really_does_write_clause_letters():
    """Vacuity guard. If no page ever wrote "(c)" the rule above would be
    protecting nothing, and someone would rightly delete it."""
    hits = [_rel(p) for p, src in _sources() if "(c)" in src]
    assert hits, "no source writes '(c)' — has the statutory copy moved?"


# ── 2. The static homepage is retired ────────────────────────────────────────

def test_the_standalone_homepage_file_is_gone():
    """The homepage was public/practicesync-homepage.html — a 717-line static
    document served at `/` by a Cloudflare rewrite, while every other page was
    React. That split is what made the logo, the CTA colour, the header
    typeface, the nav gaps, the content width and the scroll mechanics drift,
    each found separately and fixed twice. It is app/(site)/page.tsx now; if the
    file comes back, so does the drift."""
    stale = MARKETING / "public" / "practicesync-homepage.html"
    assert not stale.exists(), (
        "public/practicesync-homepage.html is back. The homepage is "
        "app/(site)/page.tsx — a second implementation of it is the thing the "
        "port removed."
    )
    home = MARKETING / "app" / "(site)" / "page.tsx"
    assert home.exists(), "app/(site)/page.tsx is missing — what serves `/`?"


def test_nothing_still_points_at_the_retired_homepage():
    """A rewrite or a link to a file that no longer exists is a 404 at `/`."""
    offenders = []
    for path, src in _sources():
        for n, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            # Comments SHOULD name it — several files explain what they were
            # ported from, which is the record of why they look as they do. The
            # defect is a live reference: an href, an import, a fetch.
            if stripped.startswith(("//", "*", "/*")):
                continue
            if "practicesync-homepage" in line:
                offenders.append(f"{_rel(path)}:{n}  {stripped[:110]}")
    redirects = (MARKETING / "public" / "_redirects").read_text(encoding="utf-8")
    # The _redirects file MAY name it — as a 301 away from the old path — but
    # must not still rewrite `/` onto it with a 200.
    assert not re.search(r"^/\s+/practicesync-homepage\s+200", redirects, re.M), (
        "public/_redirects still rewrites `/` onto the deleted static homepage."
    )
    assert not offenders, f"these still reference the retired homepage: {offenders}"


# ── 3. Claims the product cannot support ─────────────────────────────────────

# Each pattern is a claim that was live on the site and had to be removed. The
# reason is carried beside it so an entry cannot outlive its justification.
FORBIDDEN = {
    r"\bRohan Agarwal\b":
        "an invented testimonial attributed to a named CA at a named firm. "
        "There is no such customer, and the redesign brief's §18 forbids "
        "inventing one.",
    r"Trusted by Growing Practices":
        "a customer claim with no customers behind it. It is in the brief's own "
        "reference image and must not be reproduced (§16).",
    r"\bSet up in a day\b":
        "nobody has measured this. §16 rules out unverified claims.",
    r"no return is sent to a government portal automatically":
        "implies the software CAN send one non-automatically. It cannot: "
        "filing needs GSP and ERI registration that is not held "
        "(docs/compliance/07-getting-permission-to-file.md).",
    r"click to submit":
        "same — puts the software in the sentence as the thing that submits.",
    r"\bITR FILING\b":
        "the product prepares an ITR; a human files it.",
    r"\bMCA FILINGS\b":
        "the product prepares MCA forms; a human files them.",
}


@pytest.mark.parametrize("pattern,reason", sorted(FORBIDDEN.items()))
def test_a_claim_the_product_cannot_support_is_not_on_the_site(pattern, reason):
    rx = re.compile(pattern, re.I)
    offenders = []
    for path, src in _sources():
        for n, line in enumerate(src.splitlines(), 1):
            # The guard's own reasons, and comments explaining what was removed,
            # are allowed to quote the string they are about.
            stripped = line.strip()
            if stripped.startswith(("//", "*", "/*")):
                continue
            if rx.search(line):
                offenders.append(f"{_rel(path)}:{n}  {stripped[:110]}")
    assert not offenders, f"{reason}\n  " + "\n  ".join(offenders)


def test_the_forbidden_scan_would_catch_something():
    """Vacuity guard for the parametrised test above: if the patterns stopped
    matching anything at all, it would pass for every repository state."""
    sample = 'const q = "Set up in a day";'
    assert any(re.search(p, sample, re.I) for p in FORBIDDEN)
    assert not any(
        re.search(p, 'const q = "Set up your firm in an afternoon";', re.I)
        for p in FORBIDDEN
    )


# ── 4. The demo form and the endpoint agree ──────────────────────────────────

def test_the_demo_form_posts_where_the_endpoint_listens():
    """The marketing site's one cross-origin call. A path typo here is a lead
    that silently never arrives, which is the whole failure the endpoint's own
    loud-refusal design exists to prevent."""
    form = (MARKETING / "components" / "DemoForm.tsx").read_text(encoding="utf-8")
    router = (
        REPO / "apps" / "api" / "routers" / "demo_request.py"
    ).read_text(encoding="utf-8")

    assert 'prefix="/api/public"' in router
    assert '@router.post("/demo-request")' in router
    assert "/api/public/demo-request" in form, (
        "DemoForm no longer posts to /api/public/demo-request."
    )
    assert "/api/public/demo-request/options" in form
    assert '@router.get("/demo-request/options")' in router


def test_the_demo_form_checks_success_and_not_merely_res_ok():
    """The API answers some refusals inside a 200-shaped envelope, and FastAPI's
    own validation failures are a different shape again. A caller that reads
    only `res.ok` reports a lead as sent that was not — the exact defect
    lib/data/gst.ts had when it wrote a filed status straight over PostgREST."""
    form = (MARKETING / "components" / "DemoForm.tsx").read_text(encoding="utf-8")
    assert "body?.success" in form or "body.success" in form, (
        "DemoForm must check the response envelope's `success`, not just res.ok."
    )
