"""THE MARKETING SITE CAN BE FOUND, AND SAYS WHICH PAGE IS WHICH (market_and_trust-29).

The site shipped no robots.txt, no sitemap and no canonical tags. A static export
has no server to answer `/robots.txt` from, so the gap was structural: nothing
would ever appear there unless the build wrote it.

What this change does:

  * `app/robots.ts` and `app/sitemap.ts` are metadata routes Next writes to
    `out/robots.txt` and `out/sitemap.xml` at build. The sitemap is built from
    ONE list, `INDEXABLE_PATHS` in `lib/site.ts`, and the list is compared here
    with the page files on disk, so a page added without an entry fails.
  * The root layout declares `alternates: { canonical: "./" }`, which Next
    resolves per page against `metadataBase` — every page names itself, in the
    trailing-slash form the export serves.

What it deliberately does NOT do, and this file holds that too:

  * NO ANALYTICS SCRIPT OF ANY KIND. An owner decision: no third-party trackers
    on the marketing site. The finding's second half — "the owner can read weekly
    demo-form views and submissions" — therefore cannot be met by pasting a
    snippet, and is recorded as a design that needs a migration and a Privacy
    Notice to name it (the footer's "Privacy" link goes to /support today). This
    file asserts the absence so a snippet cannot arrive unnoticed.
  * NO `lastModified` in the sitemap (it would be the build time of every page on
    every deploy) and no Disallow in robots.txt (the `/access` sign-in chooser is
    left out of the SITEMAP instead: a URL blocked in robots.txt can still be
    listed, without a description, which is the opposite of the intent).

THE GUARD IS ON THE PYTHON SIDE: apps/marketing has no test runner, and this is
the suite whose required check runs on a marketing-only diff (backend-ci's `scope`
job counts apps/marketing).
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
MARKETING = REPO / "apps" / "marketing"
SITE_PAGES = MARKETING / "app" / "(site)"


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*[\s\S]*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), src)
    return re.sub(r"(?<!:)//.*", "", src)


def _code(p: Path) -> str:
    return _strip_comments(p.read_text(encoding="utf-8"))


def _sources():
    for sub in ("app", "components", "lib"):
        for p in (MARKETING / sub).rglob("*"):
            if p.is_file() and p.suffix in {".ts", ".tsx"}:
                yield p


def _routes_on_disk() -> set:
    """`/` for app/(site)/page.tsx and `/x` for app/(site)/x/page.tsx."""
    routes = set()
    for page in SITE_PAGES.rglob("page.tsx"):
        rel = page.parent.relative_to(SITE_PAGES).as_posix()
        routes.add("/" if rel == "." else "/" + rel)
    return routes


def _indexable_paths() -> list:
    m = re.search(r"export const INDEXABLE_PATHS = \[([^\]]*)\] as const", _code(MARKETING / "lib" / "site.ts"))
    assert m, "INDEXABLE_PATHS is not declared in lib/site.ts"
    return re.findall(r'"([^"]+)"', m.group(1))


# ── the sitemap is the pages that exist ──────────────────────────────────────

def test_the_scan_reads_the_site():
    assert len(_routes_on_disk()) >= 5, "fewer than five pages found under app/(site) — the scan is broken"


def test_every_page_is_in_the_sitemap_and_every_entry_is_a_page():
    on_disk, listed = _routes_on_disk(), set(_indexable_paths())
    assert on_disk - listed == set(), (
        f"these pages exist and are not in INDEXABLE_PATHS, so a search engine is never told: {sorted(on_disk - listed)}"
    )
    assert listed - on_disk == set(), (
        f"INDEXABLE_PATHS names pages that do not exist (the sitemap would list a 404): {sorted(listed - on_disk)}"
    )


def test_the_sign_in_chooser_is_left_out_on_purpose_and_not_blocked():
    """`/access` has nothing to rank. It is omitted from the sitemap and NOT
    disallowed, because a blocked URL that other pages link to can still be
    listed — with no description."""
    assert (MARKETING / "app" / "access" / "page.tsx").exists(), "premise: the chooser exists"
    assert "/access" not in _indexable_paths()
    assert "disallow" not in _code(MARKETING / "app" / "robots.ts").lower()


def test_the_list_has_no_duplicates():
    paths = _indexable_paths()
    assert len(paths) == len(set(paths))


# ── robots.txt and sitemap.xml are written at build, statically ──────────────

def test_robots_is_a_static_route_that_allows_everything_and_names_the_sitemap():
    src = _code(MARKETING / "app" / "robots.ts")
    assert 'export const dynamic = "force-static"' in src, "a static export refuses a metadata route without this"
    assert re.search(r'userAgent:\s*"\*"', src) and re.search(r'allow:\s*"/"', src)
    assert re.search(r'sitemap:\s*fileUrl\("/sitemap\.xml"\)', src), (
        "the sitemap URL must come from SITE_URL, so it follows a custom domain"
    )


def test_the_sitemap_is_a_static_route_built_from_the_one_list_and_states_only_what_is_true():
    src = _code(MARKETING / "app" / "sitemap.ts")
    assert 'export const dynamic = "force-static"' in src
    assert "INDEXABLE_PATHS.map" in src and "pageUrl(path)" in src
    for invented in ("lastModified", "changeFrequency", "priority"):
        assert invented not in src, (
            f"{invented} on every entry would state the build time of every page on every deploy "
            "(lastModified) or a hint Google has said it ignores — the sitemap lists URLs and nothing else"
        )


def test_page_urls_take_the_trailing_slash_the_export_serves():
    config = (MARKETING / "next.config.mjs").read_text(encoding="utf-8")
    assert re.search(r"trailingSlash:\s*true", _strip_comments(config)), "premise: the export serves /page/"
    site = _code(MARKETING / "lib" / "site.ts")
    fn = re.search(r"export function pageUrl\(path: string\): string \{([\s\S]*?)\n\}", site)
    assert fn and 'path.endsWith("/") ? path : `${path}/`' in fn.group(1), (
        "pageUrl must end every path in a slash, or a crawler starts from a redirect"
    )
    file_fn = re.search(r"export function fileUrl\(path: string\): string \{([\s\S]*?)\n\}", site)
    assert file_fn and "`${path}/`" not in file_fn.group(1), (
        "a FILE url must not gain a slash (/sitemap.xml/ does not exist)"
    )


# ── every page names itself canonical ────────────────────────────────────────

def test_the_root_layout_declares_a_relative_canonical_every_page_inherits():
    layout = _code(MARKETING / "app" / "layout.tsx")
    assert re.search(r'alternates:\s*\{\s*canonical:\s*"\./"\s*\}', layout), (
        'app/layout.tsx must declare alternates: { canonical: "./" } so each page resolves to its own URL'
    )
    assert "metadataBase" in layout, "a relative canonical resolves against metadataBase"


def test_no_page_overrides_alternates_and_so_drops_the_inherited_canonical():
    """A page-level `alternates` REPLACES the layout's object (metadata merges
    per top-level key), so a page that adds only `languages` would quietly lose
    its canonical."""
    offenders = [
        p.relative_to(MARKETING).as_posix()
        for p in (MARKETING / "app").rglob("page.tsx")
        if re.search(r"\balternates\b", _code(p))
    ]
    assert offenders == [], f"these pages set their own alternates and lose the inherited canonical: {offenders}"


# ── the owner's decision: nothing third-party measures visitors ──────────────

_TRACKERS = (
    "gtag", "googletagmanager", "google-analytics", "plausible", "posthog", "segment.com", "hotjar",
    "clarity.ms", "cloudflareinsights", "umami", "matomo", "fathom", "mixpanel", "amplitude",
    "fullstory", "heap.io", "mouseflow", "logrocket", "sentry.io", "datadoghq", "hubspot", "intercom",
)


def test_no_third_party_measurement_script_is_on_the_site():
    """An owner decision: no third-party analytics or trackers on the marketing
    site. Asserted so a pasted snippet cannot arrive unnoticed — the same shape
    as the booking widgets the demo form's own header rules out."""
    hits = []
    for p in _sources():
        code = _code(p).lower()
        for tracker in _TRACKERS:
            if tracker in code:
                hits.append(f"{p.relative_to(MARKETING).as_posix()}: {tracker}")
        if re.search(r"from\s+[\"']next/script[\"']", code):
            hits.append(f"{p.relative_to(MARKETING).as_posix()}: imports next/script, the way a tracker is loaded")
    assert hits == [], "a measurement script is on the marketing site, against the owner's decision:\n  " + "\n  ".join(hits)


def test_the_tracker_scan_would_catch_a_snippet():
    """A list that matches nothing would make the test above pass for ever."""
    snippet = '<script async src="https://www.googletagmanager.com/gtag/js?id=G-XXXX"></script>'
    assert any(t in snippet.lower() for t in _TRACKERS)
    assert any(t in "https://plausible.io/js/script.js" for t in _TRACKERS)
