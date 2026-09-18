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


def _live_lines(src: str):
    """(line number, code with comment spans blanked) for every line.

    WHY THIS IS NOT `line.startswith("//")`. Every scan below is meant to skip
    comments — this module's own docstring promises that documentation may quote
    what it removed — and the first version tested whether a LINE STARTED with a
    comment marker. A multi-line JSX comment,

        {/* the reference reads "500+ CA Firms · 99.9% Uptime"
            and not one of those is true */}

    has continuation lines that begin with ordinary words, so the scan read them
    as shipped copy. It fired on the very comment explaining why those strings
    are banned.

    Comment characters are replaced with spaces rather than deleted, so line
    numbers in a failure message still point at the real line.

    `://` is excluded, or the `//` in every https URL would blank the rest of
    its line — and one of the scans below looks for a path inside a URL.
    """
    out = list(src)
    i, n = 0, len(src)
    in_block = in_line = False
    while i < n:
        if in_block:
            if src.startswith("*/", i):
                out[i] = out[i + 1] = " "
                i += 2
                in_block = False
                continue
            if src[i] != "\n":
                out[i] = " "
            i += 1
            continue
        if in_line:
            if src[i] == "\n":
                in_line = False
            else:
                out[i] = " "
            i += 1
            continue
        if src.startswith("//", i) and not (i and src[i - 1] == ":"):
            in_line = True
            out[i] = out[i + 1] = " "
            i += 2
            continue
        if src.startswith("/*", i):
            in_block = True
            out[i] = out[i + 1] = " "
            i += 2
            continue
        i += 1
    return list(enumerate("".join(out).splitlines(), 1))


def test_the_comment_stripper_understands_a_block():
    """The helper above is load-bearing for every scan in this file, so it is
    checked directly. A block comment's CONTINUATION lines are the case that
    broke the old one."""
    src = 'const a = 1;\n{/* banned words\n    more banned words */}\nconst b = "kept";\n'
    live = dict(_live_lines(src))
    assert "banned" not in live[2] and "banned" not in live[3], live
    assert "kept" in live[4]
    assert "const a" in live[1]
    # A URL's // must not blank the rest of its line.
    assert "homepage" in dict(_live_lines('const u = "https://x/practicesync-homepage";'))[1]


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
        # Comments SHOULD name it — several files explain what they were ported
        # from, which is the record of why they look as they do. The defect is a
        # live reference: an href, an import, a fetch.
        for n, line in _live_lines(src):
            if "practicesync-homepage" in line:
                offenders.append(f"{_rel(path)}:{n}  {line.strip()[:110]}")
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
    # THIS ENTRY USED TO BE `\bSet up in a day\b` AND THAT WAS ONE SPELLING OF
    # ITS OWN RULE. The support FAQ carried "most firms are up and running
    # within a day" — the same unmeasured onboarding-speed claim, in words the
    # literal pattern could not see, and it sat there for as long as the guard
    # did. The rule is the CLAIM, so the pattern is now about any promise that
    # setting up takes a stated length of time.
    r"\b(set up|up and running|live|onboarded)\b[^.]{0,40}\b(in|within)\s+(a|one|1)\s+(day|hour|afternoon|week)\b":
        "nobody has measured how long a firm takes to get running. §16 rules "
        "out unverified claims.",
    r"no return is sent to a government portal automatically":
        "implies the software CAN send one non-automatically. It cannot: "
        "filing needs GSP and ERI registration that is not held "
        "(docs/compliance/07-getting-permission-to-file.md).",
    r"click to submit":
        "same — puts the software in the sentence as the thing that submits.",
    # THE STATS BAR FROM THE SECOND REFERENCE IMAGE (17-09-2026). It reads
    # "500+ CA Firms · 10M+ Documents Processed · 99.9% Uptime · 4.8/5 Customer
    # Rating" and not one of those is true: there are no customers, nothing has
    # measured uptime, and there are no ratings. The hero carries that row now,
    # with figures that are facts about the SOFTWARE — see HERO_FACTS.
    #
    # Written as the CLAIM, not the four literals, because the previous
    # onboarding-speed entry taught that a literal only bans its own spelling:
    # any count of firms, any uptime percentage, any star rating.
    r"\b\d[\d,]*\s*[MKB]?\+?\s*(CA firms|customers|practices served|firms trust)\b":
        "a customer count, and there are no customers yet. §16 rules out "
        "unverified claims; the hero's own figures are properties of the "
        "software instead.",
    r"\b\d+(\.\d+)?\s*%\s*uptime\b":
        "nothing measures uptime. There is no status page and no SLA.",
    r"\b\d(\.\d)?\s*/\s*5\b|\bcustomer rating\b":
        "a star rating with no ratings behind it.",
    r"\b\d[\d,]*\s*[MKB]\+?\s*documents\s+processed\b":
        "a volume claim nobody has counted.",
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
        # The guard's own reasons, and comments explaining what was removed, are
        # allowed to quote the string they are about.
        for n, line in _live_lines(src):
            if rx.search(line):
                offenders.append(f"{_rel(path)}:{n}  {line.strip()[:110]}")
    assert not offenders, f"{reason}\n  " + "\n  ".join(offenders)


def test_the_forbidden_scan_would_catch_something():
    """Vacuity guard for the parametrised test above: if the patterns stopped
    matching anything at all, it would pass for every repository state.

    Both spellings of the onboarding-speed claim are here, because the literal
    one is what shipped and the paraphrase is what slipped past it."""
    for sample in (
        'const q = "Set up in a day";',
        'a: "most firms are up and running within a day.",',
    ):
        assert any(re.search(p, sample, re.I) for p in FORBIDDEN), sample
    assert not any(
        re.search(p, 'const q = "Import your clients and start work.";', re.I)
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


# ── 5. The second redesign, 16 September 2026 ────────────────────────────────
#
# Six things the owner named on reviewing the live site, plus what auditing them
# turned up. Each is a defect that ships silently and that lint, typecheck and
# `next build` all pass on — which is why they are asserted here rather than
# left to the next screenshot. docs/marketing/2026-09-16-the-second-redesign.md
# is the reasoning.


def test_the_diagonal_seams_are_gone():
    """Owner review: "in the whole website the diagonal cards dont look good".

    It was three clip-path polygons in components/cinematic.tsx applied on 20
    panels across six pages, each pulled up 64px with a negative margin and each
    compensating with 64px of extra top padding. The replacement is a rounded
    light card floating on the navy canvas.

    `seam` was removed from Panel's props rather than defaulted to "none", so a
    call site cannot quietly keep passing one — that is what this asserts."""
    offenders = []
    for path, src in _sources():
        for n, line in _live_lines(src):
            if re.search(r"clip-?[Pp]ath.*polygon", line) or re.search(r"\bseam\s*=", line):
                offenders.append(f"{_rel(path)}:{n}  {line.strip()[:110]}")
    assert not offenders, (
        "the diagonal panel seam is back:\n  " + "\n  ".join(offenders)
    )


def test_the_watermark_numerals_are_gone():
    """Owner review: "the 01 and the numbering in the big light on all pages
    they also dont look asthetic".

    They were `clamp(200px, 28vw, 400px)` glyphs at 5% opacity in a panel
    corner. Section numbering now lives in SerifHeading's `index` at 13px, so
    both the prop and the type size are forbidden here."""
    offenders = []
    for path, src in _sources():
        for n, line in _live_lines(src):
            if re.search(r"\bnumeral(Corner)?\s*=", line):
                offenders.append(f"{_rel(path)}:{n}  numeral prop: {line.strip()[:90]}")
            # Any type size at or above 100px is a watermark, whatever it is
            # called — the rule rather than the one spelling that shipped.
            m = re.search(r"text-\[clamp\((\d{3,})px", line)
            if m and int(m.group(1)) >= 100:
                offenders.append(f"{_rel(path)}:{n}  {m.group(1)}px minimum: {line.strip()[:90]}")
    assert not offenders, (
        "a watermark numeral is back:\n  " + "\n  ".join(offenders)
    )


def test_the_header_is_brand_navy_and_not_a_grey():
    """Owner review: "the top bar is grey right we shouldnt keep it gry you know
    we should keep it blue the same blue that is our whole websote and the
    platform".

    The scrolled state was `bg-[#f3f5f8]/80` — a colour the Tailwind palette
    does not contain. Navy in both states also deleted the light/dark fork that
    swapped the logo, every link and the mobile sheet."""
    header = (MARKETING / "components" / "SiteHeader.tsx").read_text(encoding="utf-8")
    live = "\n".join(
        line for line in header.splitlines()
        if not line.strip().startswith(("//", "*", "/*"))
    )
    assert "bg-brand-dark" in live, (
        "SiteHeader's filled state must use the brand navy token."
    )
    stray = re.findall(r"bg-\[#(?!5876c7|4d68af)[0-9a-fA-F]{6}\]", live)
    assert not stray, (
        f"SiteHeader carries an off-palette background {stray}. The only raw "
        f"hexes allowed here are the accent CTA blue and its hover."
    )
    # The 68px bar and the inset-shadow hairline are a prior fix (830fd21f): a
    # border adds a 69th pixel and the bar changes height as you start
    # scrolling. Re-asserted because this rewrite touched the same element.
    assert "h-[68px]" in live
    assert "shadow-[inset_0_-1px_0" in live, (
        "the scrolled hairline must stay an inset shadow, not a border."
    )


def test_our_story_is_the_homepage_and_every_door_to_it_agrees():
    """⚠️ THIS GUARD USED TO ASSERT THE OPPOSITE, AND THE REVERSAL IS THE POINT.

    Until 16-09-2026 "Our Story" was `/#story`, an anchor onto a homepage panel.
    That day it was given a page, on the note "our story is a big page if you
    see i guess we have to split it", and this test asserted the page existed
    and that no nav entry was a fragment.

    The split was made by COPYING the homepage panel and the copy was never
    re-written. For two days both pages carried the same section 02 heading and
    the same gold callout; the owner found it by clicking the logo and then the
    nav item and landing on the same panel twice, and on 18-09-2026 settled it
    the other way: *"at first the our story and the home were the same page
    right so our story must contain the homepage only not the existing our
    story page delete that page."*

    So the fragment objection stands as a fact and is OUTRANKED: a fragment does
    nothing visible for a reader already at that scroll position, and that is
    accepted in exchange for there being exactly one of this content. What this
    guard holds now is the part that broke last time — that every door agrees.
    Three files link to Our Story (the header's NAV, the footer's Company
    column, and the homepage panel's own id) and the previous incarnation of
    this test was written because pointing the header somewhere left the footer
    behind."""
    story_page = MARKETING / "app" / "(site)" / "story" / "page.tsx"
    assert not story_page.exists(), (
        "app/(site)/story/page.tsx is back. Our Story is the homepage's own "
        "panel — a second page of it is what the owner had deleted, because the "
        "two carried the same copy. If it is wanted again, the heading and the "
        "callout have to be written fresh rather than copied."
    )

    home = (MARKETING / "app" / "(site)" / "page.tsx").read_text(encoding="utf-8")
    assert 'id="story"' in home, (
        'the homepage has no id="story", so every Our Story link on the site '
        "now scrolls nowhere."
    )

    site = (MARKETING / "lib" / "site.ts").read_text(encoding="utf-8")
    nav = re.search(r"export const NAV = \[(.*?)\];", site, re.S)
    assert nav, "lib/site.ts no longer exports a NAV array"
    nav_entries = dict(re.findall(r'label:\s*"([^"]+)",\s*href:\s*"([^"]+)"', nav.group(1)))
    assert nav_entries.get("Our Story") == "/", (
        f"the header's Our Story entry points at {nav_entries.get('Our Story')!r}. "
        f"It has to be `/` — the top of the homepage. It was `/#story` for a "
        f"few hours on 18-09-2026 and the owner said what that did: \"when we "
        f"click the our story it its starting from below the heropage it should "
        f"gp tp the hero right directly?\""
    )

    # EVERY OTHER DOOR, by searching rather than by naming the file: the footer
    # was missed exactly once by a test that checked NAV alone. Both the deleted
    # page and the fragment are wrong destinations now.
    offenders = []
    for path, src in _sources():
        for n, line in _live_lines(src):
            if "Our Story" in line and ("/story" in line or "#story" in line):
                offenders.append(f"{_rel(path)}:{n}  {line.strip()[:110]}")
    assert not offenders, (
        "an Our Story link points somewhere other than the top of the "
        "homepage — either the deleted page or the panel below the hero:\n  "
        + "\n  ".join(offenders)
    )

    # The page was live and linkable for two days, so the route is redirected
    # rather than left to 404.
    redirects = (MARKETING / "public" / "_redirects").read_text(encoding="utf-8")
    assert re.search(r"^/story\s+\S+\s+301", redirects, re.M), (
        "public/_redirects has no 301 for /story. The page was live from 16 to "
        "18 September 2026 and anything that linked to it now 404s."
    )


# One canonical spelling per call to action. The site carried four: "Book a
# demo" x18 against "Book a Demo" x1, and "Start free trial" x6 against "Start a
# free trial" x4 plus a lone "Get started".
CANONICAL_CTA = {
    r"Book a Demo": "Book a demo",
    r"Start a free trial": "Start free trial",
}


@pytest.mark.parametrize("wrong,right", sorted(CANONICAL_CTA.items()))
def test_one_spelling_of_each_call_to_action(wrong, right):
    offenders = []
    for path, src in _sources():
        # Comments may quote the spelling they removed, and the brief's own §3 is
        # quoted verbatim in SiteHeader with its own capitalisation.
        for n, line in _live_lines(src):
            if re.search(wrong, line):
                offenders.append(f"{_rel(path)}:{n}  {line.strip()[:110]}")
    assert not offenders, (
        f'"{wrong}" is not the canonical label — it is "{right}". Prose that '
        f"needs the phrase grammatically should be reworded.\n  "
        + "\n  ".join(offenders)
    )


def test_ui_tsx_is_the_button_and_not_a_second_design_system():
    """components/ui.tsx exported nine things and exactly ONE of them, Button,
    was imported anywhere. The other eight were the site's previous look, left
    behind when cinematic.tsx replaced it — and not inert: CTASection carried
    its own closing copy which had already drifted from CineCTA's, and
    SectionHeading and PageHero were second answers to "what does a heading look
    like". Two implementations drift, and the dead one is what the next person
    reaches for because it is shorter."""
    ui = (MARKETING / "components" / "ui.tsx").read_text(encoding="utf-8")
    exports = set(re.findall(r"export (?:function|const) (\w+)", ui))
    assert exports == {"Button"}, (
        f"components/ui.tsx exports {sorted(exports)}. It is the Button and "
        f"nothing else; headings, panels, heroes and CTAs live in "
        f"components/cinematic.tsx. A second one of any of those drifts."
    )


def test_the_canonical_calls_to_action_are_actually_on_the_site():
    """Vacuity guard for the pair above, and it is not theoretical: against the
    pre-change tree, `Book a Demo` fired on NOTHING, because its one occurrence
    was inside a JSX comment quoting the brief — which the scan skips by design.
    A rule with nothing to catch reads as enforcement and is not. So the
    canonical spellings must appear in live markup, and the wrong ones must
    still be recognisable when they do appear."""
    blob = "\n".join(
        line for _, src in _sources() for _n, line in _live_lines(src)
    )
    for label in ("Book a demo", "Start free trial"):
        assert label in blob, f'no live markup says "{label}" — has the funnel moved?'
    for wrong in CANONICAL_CTA:
        assert re.search(wrong, f'<Button>{wrong.replace(chr(92) + "b", "")}</Button>')


def test_the_product_is_described_the_same_way_everywhere():
    """One sentence says what this is, and the site had three of it.

    The hero's eyebrow and the homepage title said "the AI-first platform for
    Indian CA firms"; the root metadata said "an AI-first platform BUILT FOR
    Indian CA firms"; and the footer said "the AI-first OPERATING SYSTEM for
    Indian CA PRACTICES" — two nouns for the product and two words for the
    customer. Nobody reads all three at once, which is exactly why it survived:
    each one reads fine on its own page.

    The rule is the NOUN and the CUSTOMER, not the whole sentence — a
    description is allowed to be phrased for its position."""
    variants = set()
    for _, src in _sources():
        for _n, line in _live_lines(src):
            for m in re.finditer(
                r"AI-first\s+([a-z]+(?:\s+[a-z]+)?)\s+(?:for|built for)\s+Indian\s+CA\s+([a-z]+)",
                line,
            ):
                variants.add((m.group(1).strip(), m.group(2).strip()))
    assert variants, (
        "no source describes the product as an AI-first something for Indian "
        "CA someone — has the positioning line moved? This guard is then "
        "protecting nothing."
    )
    assert variants == {("platform", "firms")}, (
        f"the product is described {len(variants)} different ways: "
        f"{sorted(variants)}. It is a PLATFORM for Indian CA FIRMS, everywhere."
    )


# ── 6. The hero's Earth is artwork, 17 September 2026 ────────────────────────


def test_the_hero_earth_is_artwork_and_is_not_drawn_in_code():
    """Four passes tried to DRAW this globe and the owner rejected every one.

    A dotted globe, a golden one, a shaded planet, then a WebGL night Earth
    generated from a coastline mask and a table of world cities — each reviewed
    on a deploy preview, each still not the thing they had in mind. On
    17-09-2026 they supplied finished artwork and closed the question: "This is
    a static image, not something to draw with code ... Do not attempt to
    recreate the globe, city lights, starfield, or card artwork with SVG,
    Canvas, or CSS shapes."

    THIS GUARD EXISTS BECAUSE THE DELETION IS THE EASY THING TO UNDO. 3,365
    lines came out — ten scene modules, the vendored three.min.js, its loader,
    the Natural Earth mask and its generator — and the tempting next move, for
    anyone asked to make the hero move, is to start drawing again. The decision
    is an owner's, not a technical one, so it is asserted rather than left in a
    comment.

    It replaces six guards that protected the code globe: two on the land mask
    (gone with the mask) and four on the DOM capability cards and the oversized
    canvas (gone with both — the cards are baked into the artwork now). Those
    were good guards about a design that no longer exists; keeping them would
    have been asserting the shape of deleted files."""
    hero = (MARKETING / "components" / "home" / "Hero.tsx").read_text(encoding="utf-8")

    # The artwork is present, is really a WebP, and is a sane weight for
    # something above the fold on a marketing homepage.
    art = MARKETING / "public" / "hero" / "space-earth.webp"
    assert art.exists(), (
        "apps/marketing/public/hero/space-earth.webp is missing. The hero has "
        "no Earth at all without it — this is the artwork itself, not a cache."
    )
    head = art.read_bytes()[:12]
    assert head[:4] == b"RIFF" and head[8:12] == b"WEBP", (
        f"the hero artwork is not a WebP (header {head[:4]!r}). If the format "
        f"changed, the reference in Hero.tsx has to change with it."
    )
    kb = art.stat().st_size / 1024
    assert kb < 900, (
        f"the hero artwork is {kb:.0f}KB. It is the Largest Contentful Paint on "
        f"the homepage, so a heavy export is felt directly."
    )

    assert "/hero/space-earth.webp" in hero, (
        "Hero.tsx no longer references the artwork. Nothing else does either — "
        "it is the only consumer."
    )

    # NO SECOND GLOBE, DRAWN. The check is on the whole of apps/marketing
    # rather than on Hero.tsx, because a reintroduced scene would arrive as its
    # own module and be imported, exactly as the deleted one was.
    banned = {
        "three.min.js": "the vendored Three.js build was deleted with the scene",
        "WebGLRenderer": "a WebGL scene is back in the marketing site",
        "SphereGeometry": "something is building a globe out of geometry again",
        "landmask": "the coastline mask was deleted; nothing should read it",
        "canRunGlobe": "the WebGL capability gate was deleted with the loader",
    }
    offenders = []
    for path, src in _sources():
        for n, line in _live_lines(src):
            for needle, why in banned.items():
                if needle in line:
                    offenders.append(f"{_rel(path)}:{n}  {needle} — {why}")
    assert not offenders, (
        "the hero Earth is artwork by owner decision, and something is drawing "
        "one again:\n  " + "\n  ".join(offenders)
    )

    # Vacuity: the scan above proves nothing if it looked at no files.
    assert len(list(_sources())) > 20, (
        "the source walk found almost nothing, so the ban list checked nothing."
    )


def test_the_hero_picture_is_decorative_and_the_modules_are_named_on_the_page():
    """⚠️ THIS GUARD HAS NOW BEEN WRITTEN THREE WAYS IN TWO DAYS, WHICH IS THE
    LESSON RATHER THAN A FOOTNOTE.

    First it required the hero artwork's `alt` to NAME all eight capability
    modules, because they were pixels baked into the image and the alt was the
    only route by which they reached a screen reader. Then the owner supplied a
    clean render, asked for the cards as HTML, and it required the opposite —
    labels as text and an empty alt. Then, on the deploy preview the same day:
    *"remove the cards it doesnt look good you know"*. So the hero has no
    labels in it at all now.

    Two of those three versions asserted a TRANSIENT design. What is durable is
    the pair of facts underneath, and that is all this holds now:

      * the hero's picture carries no content, so its alt is empty. Whether the
        module names are baked in, rendered over it, or absent, a decorative
        photograph with descriptive alt text makes a screen reader read out
        scenery between the eyebrow and the headline.

      * the eight modules are named SOMEWHERE on the homepage. They were in the
        hero for a day and are not any more, and the thing that would actually
        be a defect is the page ceasing to list them at all — which is why this
        looks at the whole page rather than at Hero.tsx."""
    hero = (MARKETING / "components" / "home" / "Hero.tsx").read_text(encoding="utf-8")
    live_hero = "\n".join(line for _no, line in _live_lines(hero))

    tags = [("<img" + chunk).split(">")[0] for chunk in live_hero.split("<img")[1:]]
    assert 1 <= len(tags) <= 2, (
        f"the hero has {len(tags)} images. It should have one — the background "
        f"— or two, where the second is the masked brightness lift over the "
        f"asteroid field. A third means something is carrying content as a "
        f"picture again, which is what the module labels used to do."
    )
    # EVERY one of them is decorative, which is the durable rule. The second
    # image is the SAME src as the first, filtered and masked to one corner, so
    # describing it would make a screen reader read the same scenery twice.
    for i, tag in enumerate(tags):
        assert 'alt=""' in tag, (
            f"hero image {i + 1} of {len(tags)} has a non-empty alt. Both are "
            f"decorative: the background carries no content since the module "
            f"labels became the Ecosystem section's job, and the lift is a "
            f"second copy of that same file."
        )
    assert all("ARTWORK" in t for t in tags), (
        "a hero image is not the committed artwork. Both layers have to be the "
        "same `src` — that is what makes the second one free to decode."
    )

    # The modules, anywhere the homepage renders. Ecosystem is where they live
    # today; naming that file here would be the same mistake as naming a
    # method in a guard, so the search is the page's whole component tree.
    homepage_text = "\n".join(
        src for path, src in _sources()
        if "/home/" in _rel(path) or _rel(path).endswith("(site)/page.tsx")
    )
    for label in (
        "Compliance", "Clients", "Banking", "Accounting", "Payroll",
        "Documents",
    ):
        assert label in homepage_text, (
            f"the homepage no longer names the {label!r} module anywhere. The "
            f"eight were in the hero until 18-09-2026 and the section below it "
            f"is what carries them now — if that has gone too, the page has "
            f"stopped saying what the product does."
        )


def test_no_two_pages_carry_the_same_headline():
    """A READER HAS TO BE ABLE TO TELL WHICH PAGE THEY ARE ON.

    `/story` exists because "Our Story" in the nav used to point at `/#story`,
    an anchor onto a homepage panel. The page was made by COPYING that panel
    and then growing around it, and the copy was never re-written — so for a
    day both pages carried a section 02 headed "Where it starts / Every CA firm
    runs like this. / Five tools. Five logins. / One deadline through the
    cracks.", with the same eyebrow, the same three lines and the same index.

    Owner review, 17-09-2026, having clicked the logo and then the nav item:
    *"if i click the practicesync then our story page is different and if i
    click our story then the page is different see that that is fully a bug"*.
    It is the right word. A duplicated headline is not a cosmetic repeat — it
    is two pages claiming to be the same one, and the reader's only way of
    knowing where they are is what the section says.

    So the rule is per PAGE and not per file: a heading may repeat within one
    page (a recurring section is a design), and may not appear on two. The
    check is on the (eyebrow, lines) PAIR, because that is what a reader sees
    as the heading — and then on the lines alone, since the same headline under
    a re-typed eyebrow is the same defect. `Security & trust` is the one
    allowed overlap and it is allowed on evidence rather than by name: its two
    instances differ in their second line and their subtitle, so it is a
    recurring section written twice, not one panel pasted twice."""
    import collections
    import re

    pages = sorted((MARKETING / "app").rglob("page.tsx"))
    assert len(pages) >= 6, (
        f"only found {len(pages)} pages to compare; this guard is vacuous "
        f"below about six and the site has more than that."
    )

    headings: dict[tuple, set[str]] = collections.defaultdict(set)
    lines_at: dict[str, set[str]] = collections.defaultdict(set)
    for page in pages:
        src = "\n".join(line for _no, line in _live_lines(page.read_text(encoding="utf-8")))
        rel = _rel(page)
        for m in re.finditer(r'eyebrow="([^"]+)"([\s\S]{0,700}?)(?:/>|subtitle=)', src):
            lines = tuple(l.lower() for l in re.findall(r'\{\s*text:\s*"([^"]+)"', m.group(2)))
            if not lines:
                continue
            headings[(m.group(1).lower(), lines)].add(rel)
        for line in re.findall(r'\{\s*text:\s*"([^"]+)"', src):
            lines_at[line.lower()].add(rel)

    assert len(headings) >= 15, (
        f"only parsed {len(headings)} headings out of {len(pages)} pages. "
        f"SerifHeading's call shape has changed and this guard is now looking "
        f"at almost nothing — fix the pattern rather than the count."
    )

    shared = {k: v for k, v in headings.items() if len(v) > 1}
    assert not shared, "the same heading appears on more than one page:\n" + "\n".join(
        f'  eyebrow {eyebrow!r} lines {list(lines)} on {sorted(where)}'
        for (eyebrow, lines), where in shared.items()
    )

    # And the headline alone, which catches the same panel re-eyebrowed.
    repeated = {
        line: where
        for line, where in lines_at.items()
        if len(where) > 1 and line != "your clients' data —"
    }
    assert not repeated, (
        "a headline line is used on more than one page:\n"
        + "\n".join(f"  {line!r} on {sorted(where)}" for line, where in repeated.items())
        + "\nIf this is a recurring SECTION rather than a pasted panel, its "
        "other lines and its subtitle should differ — say so here with the "
        "evidence, the way \"Your clients' data —\" is exempted."
    )


def _page_prose(src: str) -> set[str]:
    """Sentences of body copy on a page, with the markup taken out.

    Class names are the trap. An earlier version of this collected every string
    literal of sentence length and reported `mt-14 grid gap-x-12 gap-y-9
    sm:grid-cols-2` as shared copy, which is true and means nothing — two pages
    using the same Tailwind classes is the design working. So `className` is
    removed first, along with imports, and what is left is filtered to things
    that read like English: a run of words with no `-[`, no `:` and at least
    one space."""
    src = re.sub(r"/\*[\s\S]*?\*/", " ", src)
    src = re.sub(r"^\s*//.*$", " ", src, flags=re.M)
    src = re.sub(r'className=(?:"[^"]*"|\{`[^`]*`\}|\{[^}]*\})', " ", src)
    src = re.sub(r"^\s*import[\s\S]*?;\s*$", " ", src, flags=re.M)

    out: set[str] = set()
    # Quoted copy: subtitles, and the `body`/`title` of a mapped array.
    for m in re.finditer(r'"([^"\\]{35,})"', src):
        out.add(" ".join(m.group(1).split()))
    # JSX text nodes: the paragraphs written inline in the markup. The run may
    # START after a `}` as well as after a `>` — `<span>Bold bit.</span>{" "}
    # then the sentence` is how every callout on this site is written, and
    # anchoring only on `>` missed the whole paragraph of the one duplicate
    # this guard was added for.
    for m in re.finditer(r"[>}]([^<>{}]{35,})[<{]", src):
        out.add(" ".join(m.group(1).split()))
    # What survives has to READ like a sentence. Anchoring a run on `}` buys
    # the callout paragraphs and also drags in code — `, ]; export default
    # function PricingPage()` is a run between a `}` and a `{` — so the
    # punctuation and keywords that only occur in code are rejected, while
    # parentheses are KEPT, because this site's copy cites "Rule 3(1) of the
    # Companies (Accounts) Rules".
    banned_chars = set(";[]=`$<>{}")
    banned_words = ("export ", "function ", "const ", "return ", "import ")
    return {
        s
        for s in out
        if " " in s
        and len(s.split()) >= 5
        and not (banned_chars & set(s))
        and ":" not in s
        and "/" not in s
        and "-[" not in s
        and not any(w in s for w in banned_words)
    }


# Duplicated copy this guard found on its first run, OUTSIDE the pair it was
# written for, and which is deliberately still duplicated. Each entry is debt
# with a reason, not an exemption: the pages they sit on were not in scope
# ("DO NOT redesign the website ... DO NOT redesign the sections below the
# hero"), and de-duplicating either means CHOOSING one of two wordings, which
# is a copy decision for the owner rather than a refactor. Reported to them on
# 17-09-2026 with the offer to fix.
#
# Matching is by substring, so these two pairs are silenced and nothing else
# is: a NEW duplicate still fails.
_KNOWN_DUPLICATED_COPY = (
    # The gold Shield callout, identical on the homepage and /products (the
    # homepage's adds "Not a batch, not a scheduler, not a retry."). It was on
    # /story too until 17-09-2026, which is the half the owner found.
    "Nothing leaves your hands on its own.",
    # /pricing says "stays on", /products says "is stored on" — the same
    # sentence twice, 90% similar, about data residency.
    "data stays on infrastructure hosted in India",
    "data is stored on infrastructure hosted in India",
)


def test_no_two_pages_carry_the_same_body_copy():
    """THE HEADLINE GUARD CAUGHT HALF OF THIS AND THE OWNER CAUGHT THE REST.

    `/story` was made by splitting a panel out of the homepage, and the copy
    was never re-written. Comparing SerifHeading headings found the section 02
    duplicate; it could not find the SECOND one, because that was body copy — a
    gold callout with the same Shield icon, the same classes and the same bold
    lead sentence, "Nothing leaves your hands on its own.", with a body
    differing from the homepage's only in its final clause. The owner found it
    by reading the deploy preview: *"The our story bug is not fixed in this?"*

    That is the lesson this file keeps re-learning and its own header states:
    a guard that asserts one SPELLING of its rule passes on every other
    spelling of the same defect. The rule is that two pages must not carry the
    same copy. Headings are one place copy lives; paragraphs are another.

    Pages only. Shared copy inside `components/` is a component being reused,
    which is the point of a component."""
    pages = sorted((MARKETING / "app").rglob("page.tsx"))
    assert len(pages) >= 6, f"only found {len(pages)} pages; this guard needs more to compare."

    prose = {_rel(p): _page_prose(p.read_text(encoding="utf-8")) for p in pages}
    total = sum(len(v) for v in prose.values())
    assert total >= 60, (
        f"only extracted {total} sentences of copy from {len(pages)} pages, "
        f"which is too few for this to be checking anything. The extractor has "
        f"stopped matching how the copy is written — fix it, do not lower this."
    )

    # ⚠️ NOT AN EXACT MATCH, AND THAT IS THE WHOLE DIFFICULTY. The duplicate
    # this guard exists for was not identical on the two pages: the homepage's
    # version ends "...on the portal. Not a batch, not a scheduler, not a
    # retry." and the story page's stopped at "...on the portal." A set
    # intersection finds nothing, and the first version of this test passed its
    # own negative control for exactly that reason. Copy-paste followed by a
    # small trim is the NORMAL shape of duplicated copy, not an edge case.
    #
    # So: identical, or one contains the other, or 85% similar. Containment is
    # checked from 55 characters up, because a short phrase legitimately
    # appears inside a longer sentence.
    import difflib

    def same_copy(a: str, b: str) -> str | None:
        if a == b:
            return "identical"
        if len(a) >= 55 and len(b) >= 55 and (a in b or b in a):
            return "one is contained in the other"
        r = difflib.SequenceMatcher(None, a, b).ratio()
        return f"{r:.0%} similar" if r >= 0.85 else None

    shared: list[str] = []
    names = sorted(prose)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            for sa in sorted(prose[a]):
                for sb in sorted(prose[b]):
                    how = same_copy(sa, sb)
                    if how and not any(k in sa or k in sb for k in _KNOWN_DUPLICATED_COPY):
                        shared.append(f"  [{how}] {a} / {b}\n      {sa[:100]!r}\n      {sb[:100]!r}")

    assert not shared, (
        "the same body copy appears on more than one page:\n"
        + "\n".join(shared)
        + "\nIf the same words genuinely belong on both, they belong in a "
        "component that both pages render, not typed twice."
    )


def test_a_tailwind_opacity_modifier_is_one_tailwind_generates():
    """AN OFF-SCALE OPACITY MODIFIER GENERATES NO RULE AT ALL, SILENTLY.

    Tailwind's opacity modifiers are the multiples of five. `bg-black/70` works;
    `bg-black/72` is not a step, is not bracketed, and so produces NOTHING — no
    warning, no fallback, no rule in the bundle. The element simply has no
    background, and it looks like a design choice rather than a broken class.

    It shipped. The hero's cards were written with `bg-[#081b3d]/72` and an icon
    tile with `bg-[#2f7dff]/20`'s predecessor `/18`, and `grep -F 081b3d` over
    the built CSS returned ZERO. The panels were not translucent navy over the
    artwork, they were absent — so the Accounting card, which sits on the
    picture's sunrise glow, rendered white text on a near-white background at
    1.1:1 against a 4.5:1 requirement, and three more cards were under 4:1. The
    screenshots looked plausible, because over the dark parts of the picture a
    card with no panel looks much like a card with one. Only measuring the
    composited pixels found it.

    It was also not new: `components/home/Ecosystem.tsx` carried
    `border-white/12` on the ecosystem dial's resting state, a border that has
    never once rendered, in a file whose other five borders are all on-scale.

    The bracketed form `/[0.72]` is legal and is allowed here, because that one
    does generate. What is rejected is the bare off-scale number, which is
    indistinguishable from a working class by eye."""
    allowed = {str(n) for n in range(0, 101, 5)}
    utils = (
        "bg", "text", "border", "ring", "ring-offset", "from", "via", "to",
        "divide", "placeholder", "decoration", "outline", "shadow", "accent",
        "caret", "fill", "stroke",
    )
    pattern = re.compile(
        r"\b(" + "|".join(utils) + r")-(\[[^\]\s]+\]|[a-z]+(?:-\d{2,3})?)/(\d{1,3})\b"
    )

    offenders, seen = [], 0
    for path, src in _sources():
        for n, line in _live_lines(src):
            for m in pattern.finditer(line):
                seen += 1
                if m.group(3) not in allowed:
                    offenders.append(f"{_rel(path)}:{n}  {m.group(0)}")

    assert seen >= 90, (
        f"only found {seen} colour-with-opacity classes to check (118 at the time this was written), which is too "
        f"few for this scan to be doing anything on a site built in Tailwind. "
        f"The pattern has stopped matching — fix it rather than this number."
    )
    assert not offenders, (
        "these Tailwind opacity modifiers are not on Tailwind's scale, so they "
        "generate no CSS and the colour is simply absent:\n"
        + "\n".join("  " + o for o in offenders)
        + "\nUse the nearest multiple of five, or the bracketed arbitrary form "
        "(/[0.72]), which does generate."
    )


def test_the_heros_vertical_rhythm_is_measured_against_the_window():
    """A HERO THAT ASKS FOR A FIXED HEIGHT DOES NOT FIT MOST LAPTOPS.

    The section is `min-h-screen`, so it is never SHORTER than the window — but
    its copy was a fixed 677px whatever the window did, and with 88px of padding
    above and 56px below it always needed 821px. Measured before the fix:

        page area 955px (1080p, no bookmarks bar)    821 — fits
        page area 880px (1080p, bookmarks + taskbar) 821 — fits
        page area 780px (13-inch MacBook Air)        833 — over by 53
        page area 760px (the owner's own window)     821 — over by 61
        page area 730px (1536x864 at 125% scaling)   821 — over by 91

    The owner reported it twice, the second time asking the right question:
    *"does it differ really to laptop to laptop or its a website thing?"* It is
    one thing from two sides — the page asked for a fixed height and a laptop
    supplies a variable one, moved as much by display scaling, browser zoom and
    a bookmarks bar as by the screen itself.

    So every vertical gap in the copy column is `clamp(min, Nvh, previous
    value)`: unchanged where there is room, compressed where there is not. This
    guard holds the PROPERTY — that those gaps are measured against the window —
    because the failure mode is somebody tidying `mt-[clamp(12px,2.4vh,28px)]`
    back to `mt-7`, which looks like a simplification, restores the fixed
    height, and cannot be seen without a browser. This suite has none, so what
    is checked is the expression rather than the outcome."""
    hero = (MARKETING / "components" / "home" / "Hero.tsx").read_text(encoding="utf-8")
    live = [line for _no, line in _live_lines(hero)]

    # The grid container carries the section's own top and bottom padding.
    container = [l for l in live if "lg:grid-cols-[" in l and "className=" in l]
    assert len(container) == 1, f"expected one hero grid container, found {len(container)}"
    # Matched with a regex rather than by splitting on whitespace: the first
    # utility in a className is glued to `className="`, so a token test misses
    # it — which is how this guard failed on correct code the first time it ran.
    def utilities(line: str, prefix: str) -> list[str]:
        return re.findall(rf"(?<![\w-]){prefix}-(?:\[[^\]]*\]|[\w.]+)", line)

    for prop, label in (("pt", "top padding"), ("pb", "bottom padding")):
        seg = utilities(container[0], prop)
        assert seg and "vh" in seg[0], (
            f"the hero's {label} is {seg or 'a fixed step'}, which does not "
            f"respond to the window's height. At a 760px page area — an "
            f"ordinary laptop — a fixed 88px/56px pair is what pushed the "
            f"figures below the fold."
        )

    # And each gap between the copy's own blocks.
    expected = {
        "<h1 ": "the headline",
        "max-w-[48ch]": "the supporting paragraph",
        "flex flex-wrap items-center gap-6": "the calls to action",
        "flex flex-wrap gap-x-7": "the trust chips",
        "grid max-w-[32rem]": "the four figures",
    }
    found = 0
    for needle, label in expected.items():
        lines = [l for l in live if needle in l and "mt-" in l]
        assert lines, f"could not find {label} in the hero to check its top margin"
        for l in lines:
            mt = utilities(l, "mt")
            assert mt and "vh" in mt[0], (
                f"{label} has a fixed top margin ({mt}). Every vertical gap in "
                f"the hero has to be window-aware or the section goes back to "
                f"needing 821px on a screen that may only have 730."
            )
            found += 1
    assert found >= 5, f"only checked {found} gaps; the copy column has more than that"


def test_the_hero_copy_does_not_drift_away_from_an_edge_bleeding_artwork():
    """THE HERO IS THE ONE SECTION THAT MAY NOT CENTRE ITS CONTENT COLUMN.

    Every other section sits in a capped, centred column, so its left gutter
    grows by half of every pixel added to the window. That is right when both
    sides of a section are measured from the same origin, and wrong here: the
    hero's artwork is pinned to the VIEWPORT's right edge and grows at a
    fraction of the viewport. A centred column and a viewport-anchored image
    advance at different rates from different origins — they converge, and then
    the text is on the picture.

    It was not theoretical. Measured on the page shipped 17-09-2026, the copy's
    left gutter ran 72px at 1280, 125 at 1440, 205 at 1600 and 365 at 1920
    against a right gutter of 0 at every one of them, and a render harness
    (copy column hidden, so every bright pixel is the artwork's) found the
    supporting paragraph over visible artwork at 1366, 1440, 1600 AND 1920 —
    the four commonest desktop widths there are. At 1920 the rotating word, the
    second headline line and a trust figure were over it too.

    The rule this guard states is the DRIFT, not a spelling of the fix: if the
    hero's content container caps or centres itself, it must neutralise both
    from `lg` up, where the artwork exists. A browser is what proves the
    clearance and this suite has none, so what is held here is the property
    that made the clearance disappear."""
    hero = (MARKETING / "components" / "home" / "Hero.tsx").read_text(encoding="utf-8")

    # The container is the one element that holds both the copy column and the
    # reserved artwork track, so it is the one carrying `grid-cols` at `lg`.
    containers = [
        line
        for _no, line in _live_lines(hero)
        if "className=" in line and "grid" in line and "lg:grid-cols-[" in line
    ]
    assert len(containers) == 1, (
        f"expected exactly one hero grid container to check, found "
        f"{len(containers)}. If the hero's layout moved, move this guard with "
        f"it — do not delete it."
    )
    container = containers[0]

    if "mx-auto" in container:
        assert "lg:mx-0" in container, (
            "the hero's content container centres itself (`mx-auto`) and never "
            "stops. The artwork is anchored to the viewport's right edge, so a "
            "centred column drifts away from it as the window widens until the "
            "copy is sitting on the planet. Neutralise it with `lg:mx-0`."
        )
    if "max-w-[" in container:
        assert "lg:max-w-none" in container, (
            "the hero's content container is capped, so past the cap its left "
            "gutter grows at half the viewport's rate while the artwork grows "
            "at 62% of it. Release the cap from `lg` up with `lg:max-w-none`."
        )

    # And the copy itself must stay bounded, or releasing the cap hands the
    # headline the whole viewport and runs it back under the artwork — the
    # opposite failure, reached by the same fix applied carelessly.
    assert "lg:grid-cols-[minmax(0,clamp(" in container, (
        "the hero's copy column is not capped. With the container uncapped, a "
        "plain `1fr` copy column takes the full viewport width and the "
        "headline runs out under the artwork. Cap the first track."
    )
