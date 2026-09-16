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
        for n, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("//", "*", "/*")):
                continue
            if re.search(r"clip-?[Pp]ath.*polygon", line) or re.search(r"\bseam\s*=", line):
                offenders.append(f"{_rel(path)}:{n}  {stripped[:110]}")
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
        for n, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("//", "*", "/*")):
                continue
            if re.search(r"\bnumeral(Corner)?\s*=", line):
                offenders.append(f"{_rel(path)}:{n}  numeral prop: {stripped[:90]}")
            # Any type size at or above 100px is a watermark, whatever it is
            # called — the rule rather than the one spelling that shipped.
            m = re.search(r"text-\[clamp\((\d{3,})px", line)
            if m and int(m.group(1)) >= 100:
                offenders.append(f"{_rel(path)}:{n}  {m.group(1)}px minimum: {stripped[:90]}")
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
        for n, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("//", "*", "/*", "{/*")):
                continue
            if "Our Story" in line and "#story" in line:
                offenders.append(f"{_rel(path)}:{n}  {stripped[:110]}")
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
        for n, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            # Comments may quote the spelling they removed, and the brief's own
            # §3 is quoted verbatim in SiteHeader with its own capitalisation.
            if stripped.startswith(("//", "*", "/*", "{/*")):
                continue
            if re.search(wrong, line):
                offenders.append(f"{_rel(path)}:{n}  {stripped[:110]}")
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
    live = []
    for _, src in _sources():
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith(("//", "*", "/*", "{/*")):
                continue
            live.append(line)
    blob = "\n".join(live)
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
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith(("//", "*", "/*", "{/*")):
                continue
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
