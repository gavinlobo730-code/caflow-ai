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


def test_our_story_is_a_page_and_the_nav_holds_no_fragment():
    """Owner review: "our story is a big page if you see i guess we have to
    split it".

    There was no Our Story page — the nav pointed at `/#story`, an anchor onto a
    homepage panel headed "Every CA firm runs like this", which is a statement
    about the READER's practice rather than a story about this one. A fragment
    in the primary nav is also invisible to a reader arriving from another page,
    since the browser restores it without a page change."""
    assert (MARKETING / "app" / "(site)" / "story" / "page.tsx").exists(), (
        "app/(site)/story/page.tsx is missing — the nav's Our Story link 404s."
    )
    site = (MARKETING / "lib" / "site.ts").read_text(encoding="utf-8")
    nav = re.search(r"export const NAV = \[(.*?)\];", site, re.S)
    assert nav, "lib/site.ts no longer exports a NAV array"
    hrefs = re.findall(r'href:\s*"([^"]+)"', nav.group(1))
    assert hrefs, "NAV has no entries"
    assert "/story" in hrefs, "NAV must link to the Our Story page"
    bad = [h for h in hrefs if "#" in h]
    assert not bad, (
        f"these primary nav entries are fragments rather than pages: {bad}. "
        f"A fragment link does not navigate for a reader on another page."
    )

    # AND THE FOOTER, because checking NAV alone missed it. Pointing the header
    # at /story left SiteFooter's Company column still on /#story — the same
    # link, the same label, one file over. A guard that names one of two doors
    # is one edit from naming neither.
    offenders = []
    for path, src in _sources():
        for n, line in _live_lines(src):
            if "Our Story" in line and "#story" in line:
                offenders.append(f"{_rel(path)}:{n}  {line.strip()[:110]}")
    assert not offenders, (
        "an Our Story link still points at the homepage anchor rather than the "
        "page:\n  " + "\n  ".join(offenders)
    )
    # The old anchor is in the wild, so the homepage keeps the id.
    home = (MARKETING / "app" / "(site)" / "page.tsx").read_text(encoding="utf-8")
    assert 'id="story"' in home, (
        "the homepage dropped id=\"story\"; /#story is a link people already hold."
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
    art = MARKETING / "public" / "hero" / "earth-network.webp"
    assert art.exists(), (
        "apps/marketing/public/hero/earth-network.webp is missing. The hero has "
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

    assert "/hero/earth-network.webp" in hero, (
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


def test_the_artwork_names_the_eight_modules_it_has_baked_in():
    """The one real cost of artwork over code, and the only mitigation there is.

    The eight capability cards are PIXELS now — "Compliance", "Payroll", "AI
    assistant" and five more. A screen reader cannot read them, they do not
    reflow, and they cannot be translated. Everything else in the hero stayed
    real HTML precisely so it would keep those properties; the cards could not,
    because they arrived inside the image.

    So the `alt` text has to carry them, and that is not decoration — it is the
    only route by which a third of the hero's content reaches assistive
    technology at all. An empty or generic alt would silently drop it."""
    hero = (MARKETING / "components" / "home" / "Hero.tsx").read_text(encoding="utf-8")

    for label in (
        "Compliance", "Clients", "Practice analytics", "Banking",
        "Accounting", "Payroll", "Documents", "AI assistant",
    ):
        assert label in hero, (
            f"the artwork shows a {label!r} card and Hero.tsx never says so. "
            f"It is baked into the image, so if it is not in the alt text it "
            f"is not anywhere a screen reader can reach."
        )

    # And the alt must actually be wired to the image rather than the labels
    # merely existing somewhere in the file.
    assert "alt={" in hero and "ARTWORK_CARDS" in hero, (
        "the module names are in Hero.tsx but are not reaching the image's alt "
        "attribute, which is the only thing that makes them readable."
    )
    # AND THE EMPTY-ALT CHECK IS PER IMAGE, NOT PER FILE, because the hero has
    # two of them and they need OPPOSITE alts. The artwork carries eight
    # content labels and must never have `alt=""`; the star field behind it
    # carries nothing and must always have one, since a decorative image with
    # descriptive alt text makes a screen reader read out scenery. A file-level
    # `'alt=""' not in hero` was the first version of this and it failed the
    # moment the correct second image was added — a guard that forbids the
    # right answer somewhere else in the file.
    # Comment spans blanked first: the artwork's own note says "A plain <img>,
    # deliberately", and a raw scan counts that prose as a third image.
    live = "\n".join(line for _no, line in _live_lines(hero))
    tags = [("<img" + chunk).split(">")[0] for chunk in live.split("<img")[1:]]
    assert len(tags) == 2, (
        f"expected the hero to have exactly two images — the artwork and the "
        f"decorative star field — and found {len(tags)}. If a third arrived, "
        f"decide which kind it is and extend this check."
    )
    for tag in tags:
        if "ARTWORK" in tag and "STARS" not in tag:
            assert 'alt=""' not in tag, (
                "the hero artwork has an empty alt. It is not decorative — it "
                "carries eight of the page's content labels, and the alt is "
                "the only route by which they reach assistive technology."
            )
            assert "alt={" in tag, "the artwork's alt is not an expression naming the cards."
        elif "STARS" in tag:
            assert 'alt=""' in tag, (
                "the decorative star field needs an empty alt. It carries no "
                "content, so describing it makes a screen reader read out "
                "scenery between the eyebrow and the headline."
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
