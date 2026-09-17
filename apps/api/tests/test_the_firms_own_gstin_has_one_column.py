"""The firm's own GSTIN is written to one column, and read through one function.

WHAT WAS WRONG

`public.firms` carries BOTH `gst_number` (migration 003) and `gstin` (migration
014, given its CHECK by 112/316). Nothing has ever synced them, and the two
sides of the product picked different ones:

  * BOTH screens that edit the firm profile wrote `gst_number`, straight over
    PostgREST — `app/settings/page.tsx` and the onboarding wizard's UPDATE step
    — so `rbac()` never ran and no validator did either;
  * every backend reader read `gstin`.

So a CA who typed their GSTIN into Settings got a fee invoice with no supplier
GSTIN on it (CGST Rule 46(a)) and, because `_state_code(None)` is None, the
whole tax on a LOCAL supply landed in IGST rather than splitting CGST+SGST.

`POST /api/onboarding/firm` has always written `gstin` correctly. It is the
screens' own UPDATE path that did not — so which route a firm came in through
decided whether its own GSTIN was readable at all.

MEASURED before acting, because the severity turns on it: on 17-09-2026
production held 2 firms with BOTH columns NULL. Latent, not live — and live the
moment anybody typed a GSTIN into Settings. The `capital_wip` shape: built,
reachable, structurally nil.

THE RULE, WHICH IS THE DURABLE HALF

    One writer — PATCH /api/firms/profile — and one reader,
    domain/firm/identity.gstin_of.

The endpoint is where the CHECK DIGIT is tested; `firms_gstin_format` is a shape
regex and cannot. `gstin_of` falls back to `gst_number` so a row saved before
17-09-2026 still answers, which is what lets this ship with no migration —
back-filling and dropping a column is an owner decision, because merging a
migration applies it to production.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = API_ROOT.parents[1] / "apps" / "web"


# ── the resolver ────────────────────────────────────────────────────────────

def test_the_canonical_column_is_the_one_the_backend_reads():
    from domain.firm import identity
    assert identity.CANONICAL_COLUMN == "gstin"
    assert identity.LEGACY_COLUMN == "gst_number"
    assert identity.COLUMNS == ("gstin", "gst_number")


@pytest.mark.parametrize("row,expected", [
    ({"gstin": "27AABCS1429B1ZU"}, "27AABCS1429B1ZU"),
    ({"gst_number": "27AABCS1429B1ZU"}, "27AABCS1429B1ZU"),
    # The canonical column wins where both carry a value — a row written after
    # 17-09-2026 needs no fallback and must not be overridden by history.
    ({"gstin": "27AABCS1429B1ZU", "gst_number": "27AAAAA0000A1Z5"}, "27AABCS1429B1ZU"),
    ({"gst_number": " 27aabcs1429b1zu "}, "27AABCS1429B1ZU"),
    ({"gstin": "", "gst_number": "   "}, None),
    ({}, None),
    (None, None),
])
def test_gstin_of_resolves_or_answers_none(row, expected):
    from domain.firm.identity import gstin_of
    assert gstin_of(row) == expected


def test_a_save_writes_only_the_canonical_column():
    """Writing both would make `gst_number` a cache with two writers, which is
    the shape CLAUDE.md records going wrong on `clients.gstin` and on
    the retired supplier table (PUR-16). Left alone it is inert history the resolver can read."""
    from domain.firm.identity import writes
    assert writes("27AABCS1429B1ZU") == {"gstin": "27AABCS1429B1ZU"}
    assert writes(None) == {"gstin": None}
    assert "gst_number" not in writes("27AABCS1429B1ZU")


# ── nothing reads the column directly any more ──────────────────────────────

#: `firm.get("gstin")` on a `public.firms` row. A CLIENT's or a CUSTOMER's
#: gstin is a different column on a different table and is not this rule's
#: business, so the scan is anchored on the variable name.
_BARE_READ = re.compile(r"""\bfirm(?:_row|_rec|_data)?\s*(?:\.get\(\s*["']gst(?:in|_number)["']|\[\s*["']gst(?:in|_number)["']\s*\])""")


def _python_sources():
    for path in sorted(API_ROOT.rglob("*.py")):
        rel = path.relative_to(API_ROOT).as_posix()
        if rel.startswith(("tests/", "domain/firm/")):
            continue
        yield rel, path.read_text(errors="ignore")


def test_no_module_reads_a_firms_gstin_column_directly():
    offenders = [
        f"{rel}:{text[:m.start()].count(chr(10)) + 1}"
        for rel, text in _python_sources()
        for m in _BARE_READ.finditer(text)
    ]
    assert not offenders, (
        "these read a firm's GSTIN column directly instead of through "
        "domain/firm/identity.gstin_of, so they see only ONE of the two "
        "columns the table carries:\n  " + "\n  ".join(offenders))


def test_a_narrow_projection_names_both_columns():
    """The fallback is a silent no-op when the row never carried the column.

    `routers/practice.py` used to `select("name, pan, gstin, state")`, which
    would have made `gstin_of` answer None for exactly the rows the fallback
    exists for. Same trap `domain/accounting/opening_documents` records for
    `is_opening`.

    READ OFF THE AST, NOT A REGEX, and the first draft is why. It matched a
    ``.select(`` followed by one quoted run containing "gstin", which sees the
    OPENING string
    of the call and nothing else — so a projection written across three
    adjacent literals (the shape `routers/firms.py` ended up with, because
    fifteen columns do not fit on a line) matched on `"id, name, email, …"`,
    found no `gstin` in it, and skipped the query. The two reads this guard
    exists for were invisible to it. Python folds adjacent literals into one
    `ast.Constant` before this code ever runs, which is exactly the rule wanted:
    a projection that is a constant string can be checked, and one reached
    through a name — a `", ".join(identity.COLUMNS)`, a module constant — is
    refused below rather than silently skipped.
    """
    from domain.firm import identity
    seen = []
    for rel, text in _python_sources():
        for node in ast.walk(ast.parse(text)):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "select"
                    and node.args):
                continue
            chain = ast.unparse(node.func)
            if '"firms"' not in chain and "'firms'" not in chain:
                continue          # not a read of public.firms
            arg = node.args[0]
            assert isinstance(arg, ast.Constant) and isinstance(arg.value, str), (
                f"{rel}:{node.lineno} projects off `firms` through a name rather "
                f"than a literal, so neither this guard nor "
                f"tests/test_backend_columns_exist_pg.py can read which columns "
                f"it asks for. Write the projection out at the call site — "
                f"routers/firms.py says why.\n  {ast.unparse(arg)}")
            projection = arg.value
            if not any(c in projection for c in identity.COLUMNS):
                continue          # a firms read that wants no GSTIN at all
            seen.append(f"{rel}:{node.lineno} {projection}")
            named = [c for c in identity.COLUMNS
                     if re.search(rf"\b{c}\b", projection)]
            assert len(named) != 1, (
                f"{rel}:{node.lineno} projects {named[0]!r} off `firms` without "
                f"the other column, so domain/firm/identity.gstin_of cannot fall "
                f"back. Name both — identity.COLUMNS is the list.\n  {projection}")

    # A FLOOR, BECAUSE THIS GUARD WAS VACUOUS ON ITS FIRST DAY — twice over, for
    # two different reasons, which is why it is worth a number. The three reads
    # first assembled their projection with `", ".join(identity.COLUMNS)`, which
    # no string check can see; made literals, they became MULTI-LINE literals,
    # which the regex above could not see either. Both times the test passed
    # having looked at nothing, on exactly the queries it exists for.
    assert len(seen) >= 3, (
        "fewer than the three firms projections that must name both gstin "
        "columns were found — one was probably moved, or narrowed to drop the "
        "GSTIN entirely:\n  " + "\n  ".join(seen))


# ── the browser writes it through the API, not PostgREST ────────────────────

_TS_COMMENT = re.compile(r"/\*[\s\S]*?\*/|^\s*//.*$", re.M)


def _web_sources():
    """Comments stripped, because the rule is about what the CODE names.

    A comment explaining why `gst_number` is not written is the record this
    change exists to leave; a `.select("gst_number")` is the defect. The
    frontend guards in apps/web/scripts strip comments for the same reason.
    """
    for folder in ("app", "components", "lib"):
        root = WEB_ROOT / folder
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix in (".ts", ".tsx") and ".test." not in path.name:
                text = _TS_COMMENT.sub(" ", path.read_text(errors="ignore"))
                yield path.relative_to(WEB_ROOT).as_posix(), text


def test_no_screen_names_the_legacy_column_at_all():
    offenders = [rel for rel, text in _web_sources() if "gst_number" in text]
    assert not offenders, (
        "these still name `gst_number`. The browser has no business choosing "
        "between the two columns — GET /api/firms/profile serves the resolved "
        f"`gstin`: {offenders}")


def test_no_screen_writes_the_firms_table_over_postgrest():
    """rbac() runs only through /api, and so does the GSTIN check digit.

    `firms_gstin_format` (migrations 112/316) is a shape regex: it accepts a
    transposition that `domain/gst/gstin.problem_with` catches, and the firm's
    own GSTIN goes on every fee invoice it raises.
    """
    write = re.compile(r'\.from\(\s*["\']firms["\']\s*\)\s*(?:\n\s*)?\.(update|insert|upsert|delete)\b')
    offenders = [
        f"{rel}:{text[:m.start()].count(chr(10)) + 1} .{m.group(1)}()"
        for rel, text in _web_sources()
        for m in write.finditer(text)
    ]
    assert not offenders, (
        "these write `public.firms` straight over PostgREST, where neither "
        "rbac() nor the GSTIN check digit runs. Use "
        "api.firm.saveProfile():\n  " + "\n  ".join(offenders))


def test_both_screens_go_through_the_one_endpoint():
    for rel in ("app/settings/page.tsx", "app/onboarding/page.tsx"):
        text = (WEB_ROOT / rel).read_text()
        assert "api.firm.saveProfile(" in text, (
            f"{rel} no longer saves the firm profile through the API")


# ── the endpoint itself ─────────────────────────────────────────────────────

def test_the_endpoint_is_mounted_once_and_is_a_patch():
    from main import app
    routes = {
        (method, r.path)
        for r in app.routes
        for method in (getattr(r, "methods", set()) or set())
        if getattr(r, "path", "").startswith("/api/firms")
    }
    assert ("PATCH", "/api/firms/profile") in routes
    assert ("GET", "/api/firms/profile") in routes
    assert not [p for _, p in routes if p != "/api/firms/profile"], routes


def test_the_write_is_partner_only():
    """The firm's own legal identity, not a per-client setting."""
    from core.permissions import PERMISSIONS, Role
    assert PERMISSIONS["firm"]["write"] == {Role.PARTNER}


def test_the_endpoint_tests_the_check_digit_and_the_column_check_cannot():
    """The whole reason the write moved off PostgREST.

    Asserted on the FUNCTION the router calls rather than on a live request,
    because the refusal happens before any database handle is touched — which
    is also what makes it testable in mock mode.
    """
    import inspect

    from routers import firms
    from domain.gst.gstin import problem_with

    source = inspect.getsource(firms.update_firm_profile)
    assert "gstin_problem(" in source, (
        "the PATCH no longer runs domain/gst/gstin.problem_with, so a "
        "transposed check digit would reach every invoice the firm raises")
    # The shape regex `firms_gstin_format` accepts this; the check digit does not.
    assert problem_with("27AABCS1429B1ZB") is not None
    assert problem_with("27AABCS1429B1ZU") is None


def test_the_served_row_carries_one_resolved_gstin():
    """A screen that could see both columns would have to choose between them,
    and choosing is domain/firm/identity's job."""
    from routers.firms import _served
    served = _served({"id": "f1", "name": "X", "gstin": None,
                      "gst_number": "27AABCS1429B1ZU"})
    assert served["gstin"] == "27AABCS1429B1ZU"
    assert "gst_number" not in served
