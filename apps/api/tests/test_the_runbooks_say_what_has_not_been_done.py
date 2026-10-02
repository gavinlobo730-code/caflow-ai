"""The incident runbook, the release procedure and the post-mortem index tell the truth about themselves (ops-29).

THE GAP
    There was useful operational writing (`docs/BETA_OPERATIONS.md`, the JWT-flag runbook, long incident histories
    inside `render.yaml`) and nothing a person on call could follow at 2 am: what to check first, who owns Render,
    Supabase and Cloudflare, how to roll back a deploy, how to rotate the service-role key, what the severity levels
    are, and which post-mortems exist. `docs/operations/` now holds `incident-runbook.md`, `release-and-rollback.md`,
    `post-mortems.md` and `service-levels.md`.

WHAT A RUNBOOK GETS WRONG THAT CODE DOES NOT, AND THE RULE FOR EACH
    * A step names an endpoint, a field or an environment variable that does not exist (a typo is a dead end at the
      moment the reader cannot afford one). Every route a document tells a person to call is in the app's route
      table; every field of `/health` it names is in `main.py`; every environment variable it names is declared in
      `render.yaml`, read by the code, or a secret of a workflow.
    * A pointer into a section that has since moved (`incident-runbook.md` §10). Every `§N` resolves to a heading.
    * A path that no longer exists: `test_the_operations_runbooks_point_at_files_that_exist.py` already reads every
      document in `docs/operations/`, so these four are under it too.
    * A claim of having been tested that nobody has made. The documents say they have not been table-tested, and the
      record in `incident-runbook.md` §10 says "not run" until it holds a date. The test fails the day the record
      is filled in and the sentence above it is not, and the other way round.
    * A fact only a human holds, written down as if known. Owners, on-call people, the backup plan and the pager are
      `[FILL IN: ...]`. The number of blanks has a CEILING that can only come down: filling one in is never blocked,
      inventing a new one is noticed. (The test cannot tell a true name from an invented one, which is why the
      documents leave the blanks and this test cannot be the thing that makes them true.)
    * A credential, an address or a phone number pasted into a public repository.
    * An index row that points at nothing: each post-mortem names where its long account is written and the guard
      that now holds it, by path.

WHAT CANNOT BE ASSERTED HERE
    That any step works. No rollback was performed, no key was rotated, and no Render, Supabase or Cloudflare screen
    was open; `incident-runbook.md` §10 is the exercise that finds out, and its record is empty.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]
REPO = API.parents[1]
OPS = REPO / "docs" / "operations"

RUNBOOK = OPS / "incident-runbook.md"
RELEASE = OPS / "release-and-rollback.md"
POST_MORTEMS = OPS / "post-mortems.md"
SERVICE_LEVELS = OPS / "service-levels.md"
NEW_DOCS = [RUNBOOK, RELEASE, POST_MORTEMS, SERVICE_LEVELS]

# The ceiling on `[FILL IN ...]` across the four documents. It only comes down: fill one in and lower it.
MAX_BLANKS = 60

_BLANK = re.compile(r"\[FILL IN(?::[^\]\n]*)?\]")
_PATH = re.compile(
    r"(?<![\w/.\-])((?:apps|docs|scripts|tests|lib|components|app|core|\.github)/[\w./\-]*[\w]\.(?:md|py|sql|tsx|ts|mjs|yml|yaml|json|toml)(?![\w]))"
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ═══ the documents exist and are reachable ════════════════════════════════════

@pytest.mark.parametrize("doc", NEW_DOCS, ids=lambda p: p.name)
def test_the_document_exists_and_is_not_a_stub(doc):
    assert doc.is_file(), f"{doc.name} is missing"
    assert len(_text(doc)) > 3000, f"{doc.name} is a stub"


def test_the_operations_guide_sends_a_reader_to_all_four():
    guide = _text(REPO / "docs" / "BETA_OPERATIONS.md")
    for doc in NEW_DOCS:
        assert f"docs/operations/{doc.name}" in guide, f"BETA_OPERATIONS.md does not link {doc.name}"


# ═══ it does not claim to have been tested ════════════════════════════════════

def _record_rows() -> list[str]:
    section = _text(RUNBOOK).split("## 10.", 1)[1]
    return [l for l in section.splitlines() if re.match(r"\|\s*[AB]\.", l)]


def test_the_runbook_says_in_its_first_lines_that_it_was_not_table_tested():
    head = "\n".join(_text(RUNBOOK).splitlines()[:12])
    assert "NOT BEEN TABLE-TOP TESTED" in head


def test_the_release_procedure_says_the_same_and_that_no_render_or_cloudflare_step_was_run():
    head = "\n".join(_text(RELEASE).splitlines()[:12])
    assert "NOT BEEN TABLE-TOP TESTED" in head and "never been run" in head


def test_the_table_top_record_is_not_run_until_it_holds_a_date():
    """The sentence at the top and the record at the bottom must agree. A filled-in record with the warning still
    standing is a runbook claiming less than it has earned; the warning removed with the record empty is the opposite."""
    rows = _record_rows()
    assert len(rows) == 2, "the table-top record must have one row per scenario (A and B)"
    dated = [bool(re.search(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{2}-\d{2}-\d{4}\b", r)) for r in rows]
    not_run = ["not run" in r.lower() for r in rows]
    for row, d, n in zip(rows, dated, not_run, strict=True):
        assert d != n, f"a table-top row must say 'not run' or carry a date, never both or neither: {row!r}"
    warned = "NOT BEEN TABLE-TOP TESTED" in "\n".join(_text(RUNBOOK).splitlines()[:12])
    assert warned == (not all(dated)), (
        "the warning at the top and the record at the bottom disagree about whether the exercise has been run")


def test_the_documents_that_are_unverified_say_what_was_not_verified():
    assert "Not verified" in _text(SERVICE_LEVELS)
    assert "What was verified, and what was not" in _text(RELEASE)


# ═══ the facts only a human has are blanks, and the blanks only come down ═════

def test_the_blanks_never_grow_without_this_test_changing():
    total = sum(len(_BLANK.findall(_text(d))) for d in NEW_DOCS)
    assert total <= MAX_BLANKS, (
        f"{total} blanks across the four documents; the ceiling is {MAX_BLANKS}. Fill one in and lower the "
        "ceiling, or raise it on purpose, saying why.")


def test_every_blank_is_closed_and_a_stray_marker_is_not_mistaken_for_one():
    for doc in NEW_DOCS:
        text = _text(doc)
        assert text.count("[FILL IN") == len(_BLANK.findall(text)), f"{doc.name} has an unclosed [FILL IN marker"


def test_the_owners_of_the_three_platforms_are_blanks_or_names_and_never_empty_cells():
    """Render, Supabase and Cloudflare are the three the item names. Each must have a row, and the row's owner cell
    must hold something: a blank to fill, or a name once a person has filled it."""
    section = _text(RUNBOOK).split("## 1. Who owns what", 1)[1].split("## 2.", 1)[0]
    rows = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and cells[0] and not set(cells[0]) <= set("-: "):
            rows[cells[0].lower()] = cells
    for needle in ("the api", "the database and auth", "the product site", "the marketing site"):
        owner = next((c for k, c in rows.items() if needle in k), None)
        assert owner is not None, f"no ownership row for {needle!r}"
        assert owner[2] and owner[3], f"the owner or second person for {needle!r} is an empty cell"


# ═══ nothing that must not be in a public repository ══════════════════════════

_FORBIDDEN = {
    "an email address": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "a phone number": re.compile(r"(?<![\w.])(?:\+?\d{1,3}[\s-]?)?(?:\d[\s-]?){9,12}\d(?![\w.])"),
    "a JWT": re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}"),
    "a Supabase or provider secret key": re.compile(r"\b(?:sb_secret_|sbp_|sk-[A-Za-z0-9]{10,}|gsk_[A-Za-z0-9]{10,}|re_[A-Za-z0-9]{16,})"),
    "a connection string with a password": re.compile(r"postgres(?:ql)?://[^\s:@/]+:[^\s@]+@"),
    "a long opaque token": re.compile(r"\b[A-Za-z0-9+/_-]{40,}\b"),
}


@pytest.mark.parametrize("doc", NEW_DOCS, ids=lambda p: p.name)
@pytest.mark.parametrize("label", sorted(_FORBIDDEN))
def test_no_credential_address_or_phone_number_is_written_in(doc, label):
    # Paths and URLs are long and harmless: blank them first so "a long opaque token" is about tokens.
    text = _PATH.sub("PATH", _text(doc))
    text = re.sub(r"https?://[^\s)`>]+", "URL", text)
    found = _FORBIDDEN[label].findall(text)
    assert not found, f"{doc.name} contains what looks like {label}: {found[:3]}"


def test_the_detectors_do_detect():
    """A detector that finds nothing proves nothing about the documents. The samples are ASSEMBLED here so that no
    token-shaped literal sits in the file for the repository's own secret scan to read."""
    assert _FORBIDDEN["an email address"].search("ask someone" + "@example.com")
    assert _FORBIDDEN["a phone number"].search("call +91 98765 43210 now")
    assert _FORBIDDEN["a JWT"].search("ey" + "J" + "fake-header-aaaa" + "." + "fake-payload-bbbbbb")
    assert _FORBIDDEN["a Supabase or provider secret key"].search("sb_" + "secret_" + "not-a-key")
    assert _FORBIDDEN["a connection string with a password"].search("postgres" + "ql://u:pw" + "@host/db")
    assert _FORBIDDEN["a long opaque token"].search("a" * 45)


# ═══ pointers resolve: sections, routes, fields and variables ═════════════════

def _headings(doc: Path) -> set[int]:
    return {int(m) for m in re.findall(r"^## (\d+)\.", _text(doc), re.M)}


def _section_references(doc: Path):
    """(target document, section number, the line) for every `§N` in `doc`. A reference belongs to the last
    `docs/…md` file named earlier on its line, or to `doc` itself when the line names none."""
    for line in _text(doc).splitlines():
        for m in re.finditer(r"§(\d+)", line):
            named = re.findall(r"docs/[\w/\-]+\.md", line[: m.start()])
            target = REPO / named[-1] if named else doc
            yield target, int(m.group(1)), line.strip()


@pytest.mark.parametrize("doc", NEW_DOCS, ids=lambda p: p.name)
def test_every_section_reference_resolves_to_a_heading(doc):
    bad = []
    for target, number, line in _section_references(doc):
        if not target.is_file() or number not in _headings(target):
            bad.append(f"§{number} of {target.name}: {line[:90]}")
    assert not bad, f"{doc.name} points into a section that does not exist: {bad}"


def test_the_section_reference_resolver_would_catch_a_moved_section():
    """Vacuity guard: the references exist in volume, and a doctored heading list makes one fail."""
    refs = [r for d in NEW_DOCS for r in _section_references(d)]
    assert len(refs) >= 15
    runbook_targets = {n for t, n, _ in refs if t == RUNBOOK}
    assert 10 in runbook_targets and 5 in runbook_targets
    assert 99 not in _headings(RUNBOOK)


def _app_routes() -> set[str]:
    sys.path.insert(0, str(API))
    from main import app
    return {getattr(r, "path", "") for r in app.routes}


def test_every_endpoint_a_document_tells_a_person_to_call_exists():
    routes = _app_routes()
    wanted = set()
    for doc in NEW_DOCS:
        for m in re.finditer(r"(?:GET|POST|PUT|PATCH)\s+`?(/(?:api/)?[\w/\-]+)", _text(doc)):
            wanted.add(m.group(1))
        for m in re.finditer(r"curl -sS(?: -m \d+)? https://practicesync-api\.onrender\.com(/[\w/\-]+)", _text(doc)):
            wanted.add(m.group(1))
    assert {"/health", "/ready", "/api/security/posture", "/api/audit"} <= wanted, (
        "the documents no longer name the endpoints this test exists to hold")
    missing = sorted(p for p in wanted if p not in routes)
    assert not missing, f"the documents tell a person to call routes that do not exist: {missing}"


def test_every_health_field_the_runbook_names_is_one_health_returns():
    main_src = _text(API / "main.py")
    section = _text(RUNBOOK).split("## 3.", 1)[1].split("## 4.", 1)[0]
    for field in ("schema_drift", "schema_objects", "missing_tables", "missing_functions", "error_reporting", "checking"):
        assert field in section, f"the runbook no longer explains /health's `{field}`"
        assert field in main_src, f"/health no longer returns `{field}`, which the runbook explains"
    for cause in ("config", "database", "auth"):
        assert f"`{cause}`" in _text(RUNBOOK)
        assert cause in _text(API / "core" / "readiness.py")


def _env_haystack() -> str:
    parts = [_text(REPO / "render.yaml")]
    for p in (REPO / ".github" / "workflows").glob("*.yml"):
        parts.append(_text(p))
    for p in API.rglob("*.py"):
        if "tests" in p.parts or "__pycache__" in p.parts or "venv" in p.parts:
            continue
        parts.append(_text(p))
    web = REPO / "apps" / "web"
    for sub in ("lib", "app", "components"):
        for p in (web / sub).rglob("*.ts*"):
            parts.append(_text(p))
    for name in ("next.config.mjs", "wrangler.toml"):
        if (web / name).is_file():
            parts.append(_text(web / name))
    parts.append(_text(API / "tests" / "test_render_manifest_matches_code.py"))   # the exemption map names CI-only ones
    return "\n".join(parts)


def test_every_environment_variable_or_secret_a_document_names_is_one_the_system_uses():
    haystack = _env_haystack()
    named = set()
    for doc in (RUNBOOK, RELEASE):
        named |= set(re.findall(r"`([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)`", _text(doc)))
    # What a backticked CONSTANT is not: a pattern prefix (`RAZORPAY_*` is written with a star) or a SQL/HTTP word.
    named -= {"GET_ONLY"}
    assert {"SUPABASE_SERVICE_ROLE_KEY", "USE_USER_JWT", "REQUIRE_MFA", "SUPABASE_DB_URL", "GROQ_TEXT_MODEL",
             "PRACTICE_MAIL_ENABLED", "ENABLE_SCHEDULER"} <= named, "the documents no longer name what this test holds"
    unknown = sorted(n for n in named if n not in haystack)
    assert not unknown, f"the documents tell a person to set names the system never uses: {unknown}"


def test_the_environment_check_would_catch_a_typo():
    assert "SUPABASE_SERVICE_ROLE_KEY" in _env_haystack()
    assert "SUPABASE_SERVICE_ROL_KEY" not in _env_haystack()


# ═══ the post-mortem index ════════════════════════════════════════════════════

def _pm_rows() -> dict[int, list[str]]:
    rows = {}
    for line in _text(POST_MORTEMS).splitlines():
        m = re.match(r"\|\s*(\d+)\s*\|", line)
        if m:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows[int(m.group(1))] = cells
    return rows


def test_every_post_mortem_row_has_all_five_cells():
    rows = _pm_rows()
    assert len(rows) >= 10
    for n, cells in rows.items():
        assert len(cells) == 5 and all(cells), f"row {n} of the post-mortem index has an empty or missing cell"


def test_every_row_names_where_it_is_written_and_a_guard_by_path():
    for n, cells in _pm_rows().items():
        written, guard = cells[3], cells[4]
        assert _PATH.search(written) or "render.yaml" in written or "CLAUDE.md" in written, (
            f"row {n} does not say where its long account is written")
        assert _PATH.search(guard), f"row {n} names no guard by path: 'be more careful' is not a guard"


def test_the_rows_other_documents_cite_are_the_rows_they_mean():
    """`incident-runbook.md` and `release-and-rollback.md` say 'row 9' for the redirect incident."""
    rows = _pm_rows()
    cited = {int(n) for d in (RUNBOOK, RELEASE) for n in re.findall(r"post-mortems\.md`? row (\d+)", _text(d))}
    assert cited == {9}, f"the documents cite post-mortem rows {cited}; this test knows only row 9"
    assert "redirect" in rows[9][2].lower()


def test_the_incidents_the_repository_already_recorded_are_indexed():
    """The incidents the repository's own prose already recorded, found by the phrase that identifies each."""
    text = _text(POST_MORTEMS)
    for phrase in ("USE_USER_JWT", "health check", "unapplied", "055", "cold start",
                   "model_not_found", "redirect rules", "Sentry"):
        assert phrase in text, f"the index no longer mentions {phrase!r}"
