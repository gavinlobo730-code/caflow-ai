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


def test_the_land_mask_is_a_real_coastline():
    """The globe's continents.

    The hero used to be a WIREFRAME — a graticule and a point cloud with no
    relationship to any landmass — because components/home/geography.ts had
    rejected a coastline: it "would have to be written from memory here, and a
    world map with the wrong coastline on the homepage of a product sold to
    Indian professionals is a worse error than no map at all."

    That reasoning was right and its premise was false. The mask is now
    generated from Natural Earth's own shoreline (world-atlas@2's land-110m,
    vendored at apps/marketing/scripts/land-110m.json, public domain) by
    scripts/build-landmask.mjs.

    So this test is the objection, kept: it decodes the committed artefact and
    puts eleven named coordinates on the right side of the coastline. A
    regenerated mask that puts Mumbai in the sea fails here rather than shipping.
    """
    import base64

    src = (MARKETING / "components" / "home" / "landmask.ts").read_text(encoding="utf-8")

    w = int(re.search(r"export const MASK_W = (\d+);", src).group(1))
    h = int(re.search(r"export const MASK_H = (\d+);", src).group(1))
    packed = re.search(r'const PACKED =\s*\n?\s*"([A-Za-z0-9+/=]+)";', src)
    assert packed, "landmask.ts has no PACKED payload — was it hand-edited?"
    bits = base64.b64decode(packed.group(1))
    assert len(bits) == -(-w * h // 8), "PACKED is the wrong length for MASK_W x MASK_H"

    def is_land(lat: float, lon: float) -> bool:
        wrapped = ((lon + 180) % 360 + 360) % 360 - 180
        row = min(h - 1, max(0, int((90 - lat) / 180 * h)))
        col = min(w - 1, max(0, int((wrapped + 180) / 360 * w)))
        i = row * w + col
        return bool(bits[i >> 3] & (1 << (i & 7)))

    # Deliberately UNAMBIGUOUS points. An earlier draft of this list used
    # Chennai (13.08N, 80.27E), which is a port: at 0.5-degree cells it lands in
    # a cell centred offshore of Mahabalipuram and reported "sea" correctly. A
    # coastal city is a test of the grid resolution, not of the coastline.
    for name, lat, lon, want in [
        ("New Delhi", 28.61, 77.21, True),
        ("Bengaluru", 12.97, 77.59, True),
        ("Nagpur", 21.15, 79.09, True),
        ("the Sahara", 23.0, 10.0, True),
        ("the Amazon basin", -5.0, -60.0, True),
        ("Antarctica", -80.0, 0.0, True),
        ("London", 51.5, -0.1, True),
        ("the Arabian Sea", 15.0, 65.0, False),
        ("the Bay of Bengal", 15.0, 88.0, False),
        ("the mid Atlantic", 30.0, -40.0, False),
        ("the mid Pacific", 0.0, -150.0, False),
    ]:
        assert is_land(lat, lon) is want, (
            f"the land mask puts {name} ({lat}, {lon}) on the wrong side of the "
            f"coastline — expected {'land' if want else 'sea'}. Regenerate with "
            f"`node scripts/build-landmask.mjs`."
        )

    land = sum(bin(b).count("1") for b in bits)
    share = 100 * land / (w * h)
    assert 27.0 <= share <= 31.0, (
        f"the mask is {share:.1f}% land; the real figure is about 29%. A mask "
        f"far off that has been mis-rasterised — most likely the scanline "
        f"crossing rule, which is half-open in y for exactly this reason."
    )


def test_the_globe_data_is_not_a_build_dependency():
    """world-atlas is 8.0 MB installed and this script reads 55 KB of it, for an
    output that is committed. Adding it to package.json would put a registry
    fetch of 8 MB on every Cloudflare Pages build of a file that cannot change
    without somebody deliberately regenerating it. Same discipline as
    domain/income_tax/schemas/ — the artefact is committed, a person regenerates
    it, the build just reads it."""
    pkg = (MARKETING / "package.json").read_text(encoding="utf-8")
    for dep in ("world-atlas", "topojson-client", "topojson"):
        assert dep not in pkg, (
            f"{dep} is in apps/marketing/package.json. The land mask is "
            f"generated offline and committed — see scripts/build-landmask.mjs."
        )
    assert (MARKETING / "scripts" / "land-110m.json").exists()
    assert (MARKETING / "scripts" / "land-110m.LICENSE").exists(), (
        "the vendored coastline must keep its licence beside it."
    )


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


def test_no_hero_card_is_anchored_off_the_edge_of_the_screen():
    """The hero's module cards, and the one bug the hero is built to hide.

    A `side: "right"` card is positioned by its LEFT edge at `x%` of the stage
    and grows rightward, so its outer edge is `stageLeft + x% x 640 + 196`. With
    anchors at 89 and 91 the Payroll and Documents cards ran past the right edge
    of the VIEWPORT — measured at 71px over at 1280, 56px at 1366 and 19px at
    1440, so on the three commonest laptop widths those cards were sliced in
    half. It shipped.

    IT SHIPPED BECAUSE THE HERO IS `overflow-hidden`. The cards were clipped
    rather than pushed out, so the document never gained a horizontal
    scrollbar — and the check that was supposed to catch this measured
    `scrollWidth` against `clientWidth` and saw a clean page at every width.
    Only measuring the CARDS finds it, which is why this reads their anchors.

    The limit lives beside them as MAX_RIGHT_ANCHOR with its derivation; this
    asserts every right-hand entry respects it, and that the constant has not
    been quietly raised past what 1024px allows.
    """
    src = (MARKETING / "components" / "home" / "HeroVisual.tsx").read_text(encoding="utf-8")

    m = re.search(r"const MAX_RIGHT_ANCHOR = ([\d.]+);", src)
    assert m, "HeroVisual no longer declares MAX_RIGHT_ANCHOR"
    limit = float(m.group(1))
    # 1024px is the narrowest width that still renders cards (the `lg:` gate and
    # canRunGlobe() agree on it): content 902px, stage 640px starting at x=323,
    # card 196px, so (1009 - 196 - 323) / 640 = 76.6%.
    assert limit <= 76.6, (
        f"MAX_RIGHT_ANCHOR is {limit}, past what 1024px allows (76.6). A card "
        f"anchored there is clipped by the hero's overflow-hidden rather than "
        f"pushing the page wide, so nothing else will report it."
    )

    entries = re.findall(r'key: "(\w+)".*?x: (\d+), y: (\d+), side: "(left|right)"', src)
    assert len(entries) >= 6, f"only found {len(entries)} module anchors — has the shape changed?"

    offenders = [
        f"{key} at x={x}" for key, x, _y, side in entries
        if side == "right" and float(x) > limit
    ]
    assert not offenders, (
        f"these right-hand hero cards are anchored past MAX_RIGHT_ANCHOR "
        f"({limit}%) and will be clipped at 1024-1440px: {offenders}"
    )

    # Vacuity: the rule protects nothing if no card is a right-hand one, and it
    # is toothless if they all sit far inside the limit anyway.
    rights = [float(x) for _k, x, _y, side in entries if side == "right"]
    assert rights, "no right-hand cards left — this rule has nothing to check"
    assert max(rights) > limit - 15, (
        "every right-hand card now sits well inside the limit, so this test "
        "would pass however wrong the limit was. Either the layout changed "
        "shape or the constant needs re-deriving."
    )

    # The LEFT side has its own limit and it is not the mirror of this one:
    # past the stage's left edge is the hero's own headline and buttons, not
    # background, so a left-hand card must stay inside the stage.
    m = re.search(r"const MIN_LEFT_ANCHOR = ([\d.]+);", src)
    assert m, "HeroVisual no longer declares MIN_LEFT_ANCHOR"
    floor = float(m.group(1))
    widest = re.search(r"const MAX_CARD_PX = (\d+);", src)
    stage = re.search(r"const STAGE_MAX_PX = (\d+);", src)
    assert widest and stage
    needed = 100 * int(widest.group(1)) / int(stage.group(1))
    assert floor >= needed, (
        f"MIN_LEFT_ANCHOR is {floor} but the widest card ({widest.group(1)}px of "
        f"a {stage.group(1)}px stage) needs {needed:.1f}. Below it the card hangs "
        f"into the copy column and sits on the headline."
    )
    under = [
        f"{key} at x={x}" for key, x, _y, side in entries
        if side == "left" and float(x) < floor
    ]
    assert not under, (
        f"these left-hand hero cards are anchored inside MIN_LEFT_ANCHOR "
        f"({floor}%) and will overlap the hero copy: {under}"
    )


def test_a_hero_card_does_not_position_itself_on_the_element_that_bobs():
    """`side: "left"` did nothing at all, for a month, because of one CSS rule.

    Each card carried BOTH its placement transform — `translate(-100%, -50%)`,
    which is what hangs a left-hand card off its anchor — and the `.floaty`
    class. `.floaty`'s keyframes set `transform` outright, and an animation's
    value beats an inline one, so the placement was thrown away on every frame.
    Every card grew rightward from its anchor, left and right alike, and the
    vertical centring went with it.

    MEASURED: the Compliance card's LEFT edge sat exactly at its own `x%`, where
    a left-hand card should have its RIGHT edge there. It reads as a styling
    detail and it is not — it is why the left column had to be crowded onto the
    globe to stay clear of the headline, and why two cards laid out 218px apart
    measured 21px apart.

    The fix is structural: an outer element positions, an inner one is styled.
    This asserts they stay separate, because nothing about the rendered page
    says otherwise — the bug is silent, and CSS has no error for it.

    ⚠️ THE BOB ITSELF IS CURRENTLY OFF, AND THIS RULE OUTLIVES IT. The hero
    rebuild of 17-09-2026 is static by instruction — "no card floating", among
    a list of movement to evaluate the design without — so `.floaty` appears on
    no card today. An earlier version of this test ended by asserting `"floaty"
    in src` as its anti-vacuity check, which would now fail for a reason that
    is not a defect.

    Deleting the test would be wrong: the bug is one CSS class away from coming
    back the moment the animation stage starts, and that is precisely when
    nobody will be re-reading this file. So the rule is kept in force for
    whenever a bob exists, and the vacuity check is moved onto the STRUCTURE
    that makes a bob safe — placement on the outer element, the card's own
    transform on the inner one. That property is true right now, is what the
    fix actually was, and fails loudly if the two elements are ever collapsed
    back into one.
    """
    src = (MARKETING / "components" / "home" / "HeroVisual.tsx").read_text(encoding="utf-8")

    # Find every element that carries a bob class, and check none of them also
    # carries a transform. Elements are matched loosely (the file is JSX, not
    # something with a parser here) but the two attributes are distinctive.
    blocks = re.findall(r"<div\b[^>]*>", src, re.S)

    # THE COUNT IS ASSERTED BEFORE THE RULE, and not out of caution. The first
    # version of this pattern was edited in through `sed`, which turned the `\b`
    # into a literal BACKSPACE byte — `<div\x08[^>]*>` matches nothing, so the
    # loop below ran zero times and this test passed green while the bug it
    # describes was sitting in the file two lines away. That is exactly the
    # failure #527 landed on main for ("the redesign's safety net was reporting
    # green having observed nothing"), reproduced one directory over, within an
    # hour of merging it. A loop over an empty list is not a passing test.
    assert len(blocks) >= 4, (
        f"only matched {len(blocks)} <div> openings in HeroVisual — the pattern "
        f"is broken, and a loop over nothing passes for any input whatsoever."
    )

    for block in blocks:
        bobs = "floaty" in block
        places = "transform:" in block or "translate(" in block
        assert not (bobs and places), (
            "a hero card element carries BOTH a .floaty bob and a transform. "
            "The animation's keyframes set `transform`, so they will not "
            "coexist — the placement is silently discarded. Put the bob on a "
            "child element.\n  " + block[:200]
        )

    # VACUITY, ON THE STRUCTURE RATHER THAN ON THE ANIMATION. See the ⚠️ in the
    # docstring: the bob is off, so "a bob exists" can no longer be the check.
    # What must stay true is the two-element split it was fixed with.
    assert "translate(-100%, -50%)" in src, (
        "no left-hand placement transform left in HeroVisual — this rule "
        "guards nothing"
    )

    placing = [b for b in blocks if "translate(-100%, -50%)" in b]
    assert placing, "the placement transform is no longer on a <div> this pattern sees"
    for block in placing:
        assert "scale(" not in block, (
            "the element that POSITIONS a hero card also carries its scale. "
            "Two transforms on one element means one wins, which is the same "
            "shape as the bug this test is named for — and it leaves nowhere "
            "for the idle animation to go when it is switched back on.\n  "
            + block[:200]
        )


def test_a_card_that_bobs_is_not_inside_something_with_an_opacity():
    """A card's GLASS dies silently if any ancestor sets `opacity`.

    An element with opacity below 1 is a BACKDROP ROOT. `backdrop-filter` on
    anything inside it then samples that element's own contents instead of the
    page behind it — so the card renders as a flat translucent rectangle with no
    blur, and the composition loses the one property that makes it read as glass
    rather than as a grey chip.

    It is entirely silent. There is no console warning, no failed style, nothing
    in a computed-style dump that says the filter did nothing, and the card is
    still there. It shipped for exactly as long as it took to look at a
    screenshot side by side.

    THE OBVIOUS WAY TO PUSH A CARD BACK IS THE WAY THAT BREAKS IT, which is why
    this is worth a test rather than a comment. The hero's capability cards
    carry a `depth`, and the first thing anyone reaches for to express depth is
    `opacity` on the positioning element. Depth is expressed in the card's own
    colours instead — fill, border, blur radius, shadow and text — which is also
    the truer cue: something further away is lower in CONTRAST, not
    see-through.

    The interface FRAGMENTS beside them do set opacity, and that is fine: they
    are bare SVG with no backdrop-filter anywhere inside. So the rule is about
    ancestry, not about the property, and this walks the tree to say so.
    """
    src = (MARKETING / "components" / "home" / "HeroVisual.tsx").read_text(encoding="utf-8")

    # Only div and span nest in this file; every other element (the icons,
    # <svg>, <line>, <circle>) is self-closing or a leaf, so tracking those two
    # is enough to know what is inside what.
    #
    # THE FILTER AND THE OPACITY ARE BOTH ATTRIBUTES OF A TAG, not text between
    # tags — `backdropFilter` lives inside a style={{...}} on the card's own
    # <div>. The first draft of this scan looked for them as separate tokens and
    # found none at all, because the tag pattern had already swallowed them.
    tag_re = re.compile(r"</?(?:div|span)\b[^>]*>")
    stack: list[bool] = []
    seen = 0
    broken = []
    for m in tag_re.finditer(src):
        tag = m.group(0)
        if tag.startswith("</"):
            if stack:
                stack.pop()
            continue
        has_opacity = "opacity" in tag
        has_backdrop = "backdrop-blur" in tag or "backdropFilter" in tag
        if has_backdrop:
            seen += 1
            # An ancestor's opacity is the real failure; the element's OWN is
            # counted too, because an element with opacity is a backdrop root
            # for the subtree it heads and the browsers disagree about whether
            # that includes its own filter. Nothing here needs to find out.
            if any(stack) or has_opacity:
                broken.append(f"HeroVisual.tsx:{src.count(chr(10), 0, m.start()) + 1}")
        if not tag.endswith("/>"):
            stack.append(has_opacity)

    # VACUITY, BOTH WAYS. A scan that found no backdrop filter proves nothing,
    # and one whose stack did not balance was not reading the tree at all — and
    # that second case is the one that passes green for any input whatsoever,
    # which is the failure this file has already shipped twice.
    assert seen, (
        "no backdrop filter left in HeroVisual — this rule guards nothing. The "
        "hero cards are meant to be glass."
    )
    assert not stack, (
        f"the div/span scan ended with {len(stack)} tags unclosed, so it was not "
        f"reading the tree correctly and would pass for any input."
    )
    assert not broken, (
        "a backdrop-filtered hero card sits inside an element that sets "
        "`opacity`. That element is a BACKDROP ROOT, so the blur samples its "
        "own contents rather than the page and the glass silently becomes a "
        "flat rectangle. Express depth in the card's own colours instead:\n  "
        + "\n  ".join(broken)
    )


def test_the_globe_canvas_is_larger_than_the_cell_it_is_given():
    """The planet's size does not come from the grid, and must not be "tidied"
    back into it.

    Owner brief, 17-09-2026: the globe should "dominate the right half of the
    hero" and may "extend beyond the normal boundaries of the hero composition
    slightly" — while the hero's own layout and typography stay as they are. The
    grid cell is 640px and every card anchor in HeroVisual, plus both of the
    limits they are checked against, is a percentage of it. So the cell cannot
    grow; the globe's CANVAS is hung outside it instead.

    That is one `absolute` element with four lg: classes, and it reads exactly
    like something a later tidy-up would replace with `inset-0`. Doing so costs
    the planet about a third of its diameter, changes no anchor, breaks no
    layout and produces no error — the hero simply goes back to the small flat
    globe the brief was written about.
    """
    src = (MARKETING / "components" / "home" / "HeroVisual.tsx").read_text(encoding="utf-8")

    w = re.search(r"lg:w-\[(\d+)%\]", src)
    h = re.search(r"lg:h-\[(\d+)%\]", src)
    assert w and h, (
        "HeroVisual no longer sizes the globe's canvas past its own cell. The "
        "planet's scale comes from that oversize, not from the grid."
    )
    assert int(w.group(1)) > 110 and int(h.group(1)) > 110, (
        f"the globe canvas is {w.group(1)}% x {h.group(1)}% of the stage. Below "
        f"about 110% there is nothing for the atmosphere and the outer orbits "
        f"to spill into and the planet has to shrink to fit."
    )
    # Offset by half the overhang in each axis, or the planet stops being
    # centred on the cell the cards are anchored to.
    for axis, over in (("left", int(w.group(1))), ("top", int(h.group(1)))):
        m = re.search(rf"lg:{axis}-\[-(\d+)%\]", src)
        assert m, f"the canvas has no lg:{axis} offset, so it is not centred on the stage"
        assert abs(int(m.group(1)) - (over - 100) / 2) <= 2, (
            f"lg:{axis} is -{m.group(1)}% for a {over}% canvas; centring it needs "
            f"-{(over - 100) / 2:.0f}%. Off-centre, the globe and the card ring "
            f"no longer share a middle and the control node stops sitting on it."
        )
