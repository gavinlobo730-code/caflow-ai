"""The Team screen says what a block reaches, in words the API serves (POST-A-005).

THE FAULT THIS ANSWERS
    The per-person grid (migration 403) is enforced by `rbac()` on every staff
    route and by the write policies of a few tables (415, 470, 478). No table's
    READ policy asks it, and several screens read tables straight from the
    browser over PostgREST (when this was written: payroll attendance and reports, the
    documents pages, the bank-account pickers; POST-A-010 moved each behind the API). So a Partner who unticks Payroll for a Manager
    stops the server answering that Manager's payroll requests and leaves the
    Manager able to select the same data with their own sign-in — and the Team
    screen said nothing about it, which is the localStorage grid's mistake with
    a working server behind it. The drawer now shows one sentence about it,
    `DENIAL_REACH_NOTICE`.

WHAT THIS MODULE HOLDS, AND WHAT IT LEAVES TO THE DATABASE
    The sentence is a claim about `pg_policies`; the real-Postgres module
    `test_the_per_person_grid_reaches_the_database_pg.py` is the guard that
    keeps it TRUE (no table read asks the grid; some table writes do and some do
    not). This module holds the rest, which needs no database:

      * the API serves the sentence, beside the pairs it belongs to;
      * the browser holds no copy of it — it renders what it is told, and
        renders nothing when told nothing ("not told" is not "nothing to tell");
      * the parts of the sentence that are claims about THIS repository are
        measured from it rather than assumed: that every staff request is
        refused through the grid, and that each screen the sentence names still
        reads a table directly;
      * the Team screen's other sentence about access, on the role card, no
        longer says the thing the grid made false.

THE RULE, NOT A SPELLING
    Nothing here pins the sentence's wording. It pins what the wording relies
    on: no count in it (a count goes stale), no six-word run of it anywhere in
    the browser's source, and every screen it names backed by a direct read.
"""
from __future__ import annotations

import ast
import html
import inspect
import re
import textwrap
from pathlib import Path

from core import permissions
from routers.identity import permission_vocabulary
from services.user_permission_service import DENIAL_REACH_NOTICE, vocabulary

WEB = Path(__file__).resolve().parents[2] / "web"


def _read(rel: str) -> str:
    return (WEB / rel).read_text(encoding="utf-8")


def _code(src: str) -> str:
    """Source with comments removed, whitespace folded — what a person is shown
    plus what the program does, none of what a programmer said about it."""
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    src = re.sub(r"^\s*//.*$", " ", src, flags=re.M)
    return " ".join(src.split())


def _words(text: str) -> list[str]:
    """Words, with the apostrophe spelled every way JSX makes you spell it.

    `react/no-unescaped-entities` forbids a bare `'` in JSX text, so a copy of
    "person's requests" in a component is written `person&apos;s` — and a scan
    that did not read the entity would find a copy of every sentence except one
    that contains an apostrophe.
    """
    text = html.unescape(text).replace("’", "'").replace("‘", "'")
    return re.findall(r"[a-z0-9']+", text.lower())


def _browser_sources() -> dict[str, str]:
    """Every non-test TypeScript source the browser is built from."""
    out: dict[str, str] = {}
    for top in ("app", "components", "lib"):
        for path in (WEB / top).rglob("*"):
            if path.suffix not in (".ts", ".tsx") or ".test." in path.name:
                continue
            out[path.relative_to(WEB).as_posix()] = path.read_text(encoding="utf-8")
    assert out, "no browser source was found — every scan below would pass on nothing"
    return out


# ── The API serves it ────────────────────────────────────────────────────────

def test_the_vocabulary_endpoint_serves_the_notice_beside_the_pairs():
    body = permission_vocabulary(
        current_user={"id": "u1", "firm_id": "f1", "role": "Partner"})
    assert body["success"] is True
    assert body["data"]["notice"] == DENIAL_REACH_NOTICE
    assert isinstance(DENIAL_REACH_NOTICE, str) and DENIAL_REACH_NOTICE.strip()
    # The pairs are what they were: the notice is added to the answer, not
    # swapped for part of it.
    assert body["data"]["permissions"] == vocabulary()


def test_the_notice_states_no_count_because_a_count_goes_stale():
    """"Several screens" ages well and "eleven tables" does not. The sentence is
    held to the policies by a test, but a number in it would need that test to
    count, and a count is the thing that drifts silently."""
    assert not re.search(r"\d", DENIAL_REACH_NOTICE), DENIAL_REACH_NOTICE


def test_the_notice_names_payroll_and_banking_as_reached_only_through_the_server_and_billing_as_read_through_the_grid():
    """Payroll and the bank tables are not the browser's at all since migrations 549 and 550 (POST-A-339): a signed-in session
    holds no privilege on them and may not run the two bank reports or read the foreign bank balances, so the sentence says that and no longer says what the
    database CHECKS on them (a block on reading, a block on writing, the employee's own declaration, the bank account list the
    database did not cover). Billing is still read through the grid (495) and keeps its sentence. The real-Postgres siblings
    hold that the claims are true (`test_549_*_pg.py`, `test_550_*_pg.py`, `test_the_per_person_grid_reaches_the_database_pg.py`);
    this holds that the SENTENCE still names each family and says the thing, and has stopped saying the things that went false."""
    text = " ".join(DENIAL_REACH_NOTICE.lower().split())
    for family in ("payroll", "billing", "banking"):
        assert family in text, f"the notice no longer names {family}"
    assert "reached only through that server" in text
    assert "no signed-in browser session read or write the payroll records" in text
    assert "or the bank records" in text and "reconciliations" in text and "the two bank reports and the foreign-currency bank balances are closed to it" in text
    assert "a block on payroll or on banking is applied in one place" in text
    # the sentences that were true until 549 and 550 and are false now
    for stale in ("one payroll record the database still lets", "list of bank accounts is not covered by the database",
                  "the database also refuses a tax declaration and its items to a person blocked from writing payroll",
                  "a block on writing payroll is applied by the practicesync server, where the payroll records are written"):
        assert stale not in text, f"the notice still says: {stale}"


def _array_of(migration: str) -> set[str]:
    sql = re.sub(r"--[^\n]*", "", (Path(__file__).resolve().parents[1] / "migrations" / migration).read_text())
    body = re.search(r"tables text\[\] := ARRAY\[(.*?)\]", sql, re.S).group(1)
    return set(re.findall(r"'([a-z_]+)'", body))


def test_what_the_notice_lists_as_payroll_and_bank_records_is_what_the_two_migrations_close():
    """The sentence lists the records in words; the migrations list them as tables. Each word the sentence uses must be a
    family one of the tables belongs to, and each family a table belongs to must be named, so a payroll or bank table added to
    a migration (a new record kind) is a sentence that needs a word, and a word with no table behind it fails."""
    text = " ".join(DENIAL_REACH_NOTICE.lower().split())
    payroll = _array_of("549_a_signed_in_session_reads_and_writes_none_of_the_payroll_tables.sql")
    bank = _array_of("550_a_signed_in_session_reads_and_writes_none_of_the_bank_tables_and_runs_neither_bank_report.sql")
    # (the word the sentence uses, a table of the migration it stands for)
    words_for_payroll = {"employees": "payroll_employees", "runs": "payroll_runs", "payslips": "payroll_slips",
                         "attendance": "attendance", "leave balances": "leave_balances",
                         "tax declarations": "payroll_it_declarations", "salary history": "payroll_salary_revisions",
                         "salary structures": "salary_structures", "loans": "payroll_loans",
                         "settlements": "payroll_settlements", "bonus records": "bonus_declarations",
                         "remittances": "statutory_remittances", "ecr filings": "epfo_ecr_filings",
                         "payroll settings": "client_payroll_settings"}
    words_for_bank = {"accounts": "bank_accounts", "statements": "bank_statements", "transactions": "bank_transactions",
                      "splits": "bank_transaction_splits", "reconciliations": "bank_reconciliations",
                      "matching rules": "bank_matching_rules", "saved statement layouts": "bank_statement_column_mappings"}
    for word, table in words_for_payroll.items():
        assert word in text and table in payroll, (word, table)
    for word, table in words_for_bank.items():
        assert word in text and table in bank, (word, table)
    # every table the migrations close is one the sentence has a word for (a table with no word is a record kind nobody was told)
    covered = set(words_for_payroll.values()) | set(words_for_bank.values())
    # the match rows, the tax-declaration lines, the pt settings, the ECR/loan helpers and the like ride with their parent's word
    rides_with_a_parent = {"payroll_run_transitions", "payroll_perquisites", "payroll_one_time_earnings", "bonus_disqualifications",
                           "payroll_loan_recoveries", "payroll_settlement_components", "payroll_it_declaration_items",
                           "client_pt_registrations", "firm_pt_slabs", "bank_reconciliation_matches"}
    unnamed = (payroll | bank) - covered - rides_with_a_parent
    assert not unnamed, f"the migrations close tables the notice has no word for and that are not listed as riding with one: {sorted(unnamed)}"


# ── What it says about THIS repository is measured from it ───────────────────

def _is_the_products_own(route) -> bool:
    """A route the PRODUCT defines, as opposed to one a test module registered on
    the shared `main.app`.

    `tests/test_every_request_carries_an_id.py` adds four real routes to that app
    (two of them take `get_current_user` and no `rbac()`), and whether they are
    in the table when this walk runs depends on which tests ran earlier in the
    same process: the required backend job runs `-n auto --dist loadfile`, so
    grouping decides. The rule is "where the endpoint is DEFINED", read off its
    module name, the one `test_every_public_route_is_rate_limited` already uses;
    it is not a path prefix, because a product route mounted outside `/api` that
    reaches firm data without the grid is exactly what this walk exists to find.
    """
    module = getattr(route.endpoint, "__module__", "") or ""
    parts = module.split(".")
    return not (parts[0].startswith("test") or "tests" in parts)


def _grid_census(routes):
    """(how many product routes ask `rbac()`, the paths of those that take a
    staff principal and do NOT ask it). Pure over the routes it is handed."""
    from fastapi.routing import APIRoute

    def calls(dep, out):
        call = getattr(dep, "call", None)
        if call is not None:
            out.append(call)
        for d in dep.dependencies:
            calls(d, out)
        return out

    without_grid = set()
    guarded = 0
    for route in routes:
        if not isinstance(route, APIRoute) or not _is_the_products_own(route):
            continue
        fns = calls(route.dependant, [])
        takes_staff = any(getattr(f, "__name__", "") == "get_current_user" for f in fns)
        asks_grid = any(getattr(f, "__qualname__", "").startswith("rbac.<locals>") for f in fns)
        if asks_grid:
            guarded += 1
        elif takes_staff:
            without_grid.add(route.path)
    return guarded, without_grid


def test_every_staff_request_but_two_goes_through_the_grid():
    """"A block here is enforced by the PracticeSync server, which refuses that
    person's requests for that permission."

    True of a route only if it asks `rbac()`. The route table says which do not:
    exactly the two below, neither of which serves firm data.
    """
    import main

    guarded, without_grid = _grid_census(main.app.routes)

    assert guarded > 100, "the scan found almost no rbac() route — it is reading nothing"
    allowed = {
        # Reports the caller's OWN resolved answer, computed from the same
        # overrides the grid stores; it is how a screen learns what to draw.
        "/api/identity/permissions",
        # Must be reachable at aal1 by exactly the people the policy locks out.
        "/api/security/mfa-policy",
    }
    assert without_grid == allowed, (
        "a staff route is reached without the per-person grid (or one of the two "
        f"known exceptions moved): {sorted(without_grid ^ allowed)}. A block on "
        "the Team screen does not stop it, and DENIAL_REACH_NOTICE says the "
        "server refuses a blocked person's requests.")


def test_the_walk_leaves_out_a_route_a_test_module_registered():
    """The census must not depend on what other tests did to the shared app.

    A throw-away app (never `main.app`, so this test cannot cause the very
    pollution it guards against) carries one route defined in THIS module that
    takes a staff principal and no `rbac()`, beside one that does ask the grid.
    Against a walk that counted every `APIRoute`, the first would be reported as
    a staff route reached without the grid.
    """
    from fastapi import Depends, FastAPI

    from core.auth import get_current_user
    from core.permissions import rbac

    app = FastAPI()

    @app.get("/__grid__/registered-by-a-test")
    def registered_by_a_test(user=Depends(get_current_user)):  # noqa: B008
        return {}

    @app.get("/__grid__/asks-the-grid")
    def asks_the_grid(user=Depends(rbac("client", "read"))):  # noqa: B008
        return {}

    # Premise: the stand-in really is a staff route without the grid, defined in
    # a module the rule must recognise as a test's.
    assert registered_by_a_test.__module__ == __name__
    stand_in = next(r for r in app.routes
                    if getattr(r, "path", "") == "/__grid__/registered-by-a-test")
    assert not _is_the_products_own(stand_in)

    guarded, without_grid = _grid_census(app.routes)
    assert without_grid == set(), without_grid
    assert guarded == 0, (
        "the route registered by a test module was counted as the product's own "
        "(or the rbac() stand-in was: neither belongs in the census)")


def test_the_walk_still_finds_the_products_own_routes():
    """The other direction: leaving test routes out must not leave everything
    out. The two named exceptions are product routes and must be in the walk."""
    import main

    products = {r.path for r in main.app.routes if _is_the_products_own(r)}
    assert {"/api/identity/permissions", "/api/security/mfa-policy"} <= products


def test_rbac_asks_the_per_person_resolver_and_not_the_role_alone():
    tree = ast.parse(textwrap.dedent(inspect.getsource(permissions.rbac)))
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "can_user" in called, "rbac() no longer asks the per-person resolver"
    assert "can" not in called, (
        "rbac() reads the role directly again; a per-person block would then "
        "stop nothing at the server either")


# The surfaces the notice may name as read directly, each with where in the browser it reads and which tables count. A
# surface the notice NAMES must still read a table directly, or the sentence promises an exposure that is gone (or, worse,
# that moved behind the API without anybody updating what a Partner is told).
#
# NONE TODAY. The sentence used to name the payroll attendance and reports screens, then the bank-account pickers and the
# documents pages; POST-A-010 moved each behind the API in turn and the last two payroll screens went with the staff
# payroll step, so the notice now says "several screens read tables directly" and names none. An entry goes back in here
# the day the sentence names a screen again.
_SURFACES: dict[str, tuple[str, set[str]]] = {}


def _names_read_directly(notice: str) -> list[str]:
    """The screens a notice names as read directly: the `(… among them)` it may put after "read tables directly from the
    browser". A notice that names none returns an empty list, and that is a sentence with nothing to hold."""
    text = " ".join(notice.split())
    found = re.search(r"read tables directly from the browser \(([^)]*?) among them\)", text)
    if not found:
        return []
    return [n.strip() for n in re.split(r",| and ", found.group(1)) if n.strip()]


def _problems_with_the_names(names: list[str], surfaces: dict, reads: dict[str, set[str]]) -> list[str]:
    """Every name the notice gives that this module cannot measure, or that nothing in the browser reads any more."""
    problems = []
    for name in names:
        if name not in surfaces:
            problems.append(f"'{name}' is named as read directly, and no surface here measures it")
            continue
        prefixes, family = surfaces[name]
        prefixes = (prefixes,) if isinstance(prefixes, str) else prefixes
        if not [rel for rel, tables in reads.items() if rel.startswith(prefixes) and tables & family]:
            problems.append(f"'{name}' is named as read directly from the browser, and nothing under {prefixes} reads "
                            f"{sorted(family)} any more; if that read moved behind the API the sentence should stop saying so")
    return problems


def _direct_reads() -> dict[str, set[str]]:
    reads: dict[str, set[str]] = {}
    for rel, text in _browser_sources().items():
        tables = set(re.findall(r'\.from\(\s*"([a-z_0-9]+)"\s*\)', text))
        if tables:
            reads[rel] = tables
    return reads


def test_every_screen_the_notice_names_still_reads_a_table_directly():
    text = " ".join(DENIAL_REACH_NOTICE.split())
    assert "read tables directly from the browser" in text, "the notice no longer says that screens read directly"
    assert _direct_reads(), "the scan of the browser found no direct read at all — it checks nothing"
    problems = _problems_with_the_names(_names_read_directly(DENIAL_REACH_NOTICE), _SURFACES, _direct_reads())
    assert not problems, problems


def test_the_notice_names_no_directly_read_surface_that_this_module_cannot_check():
    """If the sentence says which screens read directly, every name in it must be a surface above, so that a name added to
    the sentence (or left in it after the screen moved behind the API, as the bank-account pickers, the document screens and
    the payroll screens did in POST-A-010) is measured against a read, and an unknown one fails here."""
    unknown = [n for n in _names_read_directly(DENIAL_REACH_NOTICE) if n not in _SURFACES]
    assert not unknown, f"the notice names {unknown} as read directly, and no surface here measures it"


def test_negative_control_a_named_screen_with_no_read_left_is_caught_and_a_screen_that_still_reads_is_not():
    """The two checks above are vacuous while the notice names nothing; this is what they would catch."""
    surfaces = {"attendance": ("app/payroll/attendance/", {"attendance", "payroll_employees"})}
    notice = "several screens read tables directly from the browser (attendance among them): there only the firm decides."
    assert _names_read_directly(notice) == ["attendance"]
    assert _problems_with_the_names(["attendance"], surfaces, {"app/payroll/attendance/page.tsx": {"clients"}})
    assert not _problems_with_the_names(["attendance"], surfaces, {"app/payroll/attendance/page.tsx": {"attendance"}})
    assert _problems_with_the_names(["documents"], surfaces, {}) , "a name this module cannot measure is a problem"
    assert _names_read_directly("several screens read tables directly from the browser: there only the firm decides.") == []


# ── The browser renders it and holds no copy ─────────────────────────────────

def test_the_drawer_renders_what_it_is_told_and_nothing_when_told_nothing():
    drawer = _code(_read("components/team/MemberAccessDrawer.tsx"))
    # What counts as "told" is `lib/team/denialNotice` (a non-blank string,
    # returned as received; behaviour tested beside it). The drawer must put the
    # response's own field through it and render the result only when there is
    # one.
    assert re.search(r"denialNotice\(vocab\.data\.notice\)", drawer), (
        "the drawer does not read the notice off the vocabulary response")
    assert re.search(r"\{notice &&", drawer), "the notice is rendered unconditionally"
    assert re.search(r"\{notice\}", drawer), "the drawer does not render the received value"


def test_no_six_word_run_of_the_notice_is_in_the_browser():
    """The sentence lives beside the guard that keeps it true. A copy in the
    TSX would outlive the policies it describes — the way a browser copy of the
    permission vocabulary drifted before.

    Comments are not scanned: they are never shown, and a programmer explaining
    what the server says is not the screen saying it. What is scanned is what
    could reach a person — JSX text and string literals.
    """
    words = _words(DENIAL_REACH_NOTICE)
    runs = {" ".join(words[i:i + 6]) for i in range(len(words) - 5)}
    assert runs, "the notice is too short to hold the test's six-word window"
    for rel, text in _browser_sources().items():
        flat = " ".join(_words(_code(text)))
        copied = sorted(r for r in runs if r in flat)
        assert not copied, f"{rel} carries a copy of the served notice: {copied[:2]}"


# ── The role card no longer denies the grid exists ───────────────────────────

def test_the_team_screen_does_not_say_access_is_decided_by_role_alone():
    """The card read "Access is decided by role — there is no per-person
    override" for as long as the grid beside it was being built, and after.
    The rule is that this screen may not say the opposite of what `rbac()` does;
    `test_rbac_asks_the_per_person_resolver_and_not_the_role_alone` is what
    makes the opposite true."""
    page = _code(_read("app/team/page.tsx"))
    assert not re.search(r"no per[- ]person", page, re.I)
    assert not re.search(r"(decided|determined|set) by (the )?role\b", page, re.I)
    assert not re.search(r"role (alone|only)", page, re.I)
