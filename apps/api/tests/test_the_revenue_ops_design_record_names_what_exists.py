"""The revenue-operations design record names only what exists, and its open statements expire (POST-A-177).

THE GAP
    The firm's own practice as a client, its four guardrails (G1 to G4), the billing lifecycle with its
    duplicate-invoice index, collections, time capture and the knowledge base were described only in
    `docs/BATCH_*` reports of June 2026. Those were set aside on 8 October 2026 and the description now lives in
    `docs/architecture/11-revenue-ops-and-knowledge.md`, written from the code. A design record is only as good as
    the names it carries, and a prose file nothing reads rots exactly as the reports did: the reports said the
    service role bypasses row-level security, that search was full-text and that the Manager is firm-wide, and
    each was false by the time anyone looked.

WHAT THIS HOLDS, AS RULES AND NOT AS A LIST OF TODAY'S NAMES
    * The record exists, is not a stub, has one heading per guardrail G1 to G4 and names the unique index that
      keeps a schedule from billing a period twice.
    * Every repository path it names resolves. A path written after a commit id and a colon
      (`git show 315e6a19:docs/...`) is history, not a file, and is not asked.
    * Every migration number it names is a migration in `apps/api/migrations`.
    * Every `METHOD /api/...` it names is a mounted route; a route it says is gone is not mounted.
    * Every function it names with `()` is defined: in the module it is qualified with, or anywhere in production
      code for a bare name, or as an SQL function in a migration.
    * Every `rbac("resource", "action")` it names is a pair `core.permissions.PERMISSIONS` holds, and the decisions of
      14 June 2026 it records about who may do what are the ones the table holds.
    * Each guardrail section cites a test that holds it.
    * **Statements about what is NOT built or NOT decided expire.** The record says knowledge-base search is
      title-only, that the Manager is firm-wide in the knowledge base alone, and lists six defects observed while
      writing it. Each is asserted here against the code, so the day one is built or fixed this file fails and says
      to change the record the same day. That is the point of them: a design record that is wrong in the
      reassuring direction is worse than none.

WHAT IT CANNOT SEE
    Whether a sentence is true that names nothing checkable (the reasons, the history, the visibility table's
    cells beyond the two it pins). A function is "defined" by name, so a rename to another existing function of the
    same name would pass. The route extractor reads `METHOD /api/path` pairs only; a route named by its path alone
    is not asked.
"""
from __future__ import annotations

import ast
import functools
import re
from pathlib import Path

import pytest

from core.permissions import PERMISSIONS, Role
from main import app

REPO = Path(__file__).resolve().parents[3]
API = REPO / "apps" / "api"
DOC = REPO / "docs" / "architecture" / "11-revenue-ops-and-knowledge.md"
ROOTS = (REPO, API, REPO / "apps" / "web")
NOT_PRODUCTION = frozenset({"tests", "migrations", "scripts", "__pycache__", "node_modules", "venv", ".venv"})

# The same path shape the runbook guard reads: a known top-level directory, segments, a file suffix.
_PATH = re.compile(
    r"(?<![\w/.\-])((?:apps|docs|scripts|tests|lib|components|app|core|\.github)/[\w./\-]*[\w]\.(?:md|py|sql|tsx|ts|mjs|yml|yaml|json|toml)(?![\w]))"
)
_HISTORY = re.compile(r"\b[0-9a-f]{8}:\S+")
_BARE_TEST = re.compile(r"\b(test_[\w]+\.py)\b")
_MIGRATION_PHRASE = re.compile(r"[Mm]igrations?\s+(\d{3}(?:\s*(?:,|and|to|/|–)\s*\d{3})*)")
_ROUTE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/api/[\w/{}\-]*)")
_FUNCTION = re.compile(r"([A-Za-z_][\w.]*)\(\)")
_RBAC = re.compile(r'rbac\("(\w+)",\s*"(\w+)"\)')

#: Functions the record must keep naming, so deleting the sentence cannot be how a rename escapes this file.
MUST_NAME = (
    "internal_client_service.assert_can_view_client", "internal_client_service.assert_partner_for_internal_id",
    "internal_client_service.assert_not_internal_for_payroll", "internal_client_service.require_client_access",
    "internal_client_service.provision", "billing_service.ensure_customer_link",
    "billing_service.generate_for_schedule", "collections_service.assess_invoice",
    "collections_service.sweep_overdue", "collections_service.flag_overdue_for_internal_followup",
    "knowledge_service.restore_version", "knowledge_service.can_view_client_content",
    "billing_service.mark_time_entries_billed",
)
#: Database objects the record names without `()` and which a migration must create.
SQL_OBJECTS = ("unbilled_time_summary", "my_internal_client_id", "get_my_user_id", "provision_internal_client",
               "clients_external", "uq_client_sales_invoices_billing_run", "uq_clients_one_internal_per_firm")
TABLES_FROM_073 = ("billing_schedules", "client_firm_customer_links", "knowledge_articles",
                   "knowledge_article_versions", "client_instructions")


# ── readers ──────────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=1)
def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


@functools.lru_cache(maxsize=1)
def _production() -> dict[str, str]:
    out = {}
    for path in sorted(API.rglob("*.py")):
        rel = path.relative_to(API)
        if NOT_PRODUCTION.isdisjoint(rel.parts[:-1]):
            out[rel.as_posix()] = path.read_text(encoding="utf-8", errors="ignore")
    return out


@functools.lru_cache(maxsize=1)
def _migrations() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8", errors="ignore")
            for p in sorted((API / "migrations").glob("*.sql")) if not p.name.endswith("_rollback.sql")}


@functools.lru_cache(maxsize=1)
def _routes() -> frozenset[tuple[str, str]]:
    out = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        for method in getattr(route, "methods", set()) or set():
            if path.startswith("/api/") and method not in ("HEAD", "OPTIONS"):
                out.add((method, path))
    return frozenset(out)


def _section(text: str, start: str) -> str:
    """From the line beginning `start` to the next heading of the same or a higher level."""
    lines, out, level = text.splitlines(), [], None
    for line in lines:
        if level is None:
            if line.startswith(start):
                level, out = len(line) - len(line.lstrip("#")), [line]
            continue
        if line.startswith("#") and len(line) - len(line.lstrip("#")) <= level:
            break
        out.append(line)
    return "\n".join(out)


# ── extractors (each is exercised by a negative control below) ───────────────

def paths_named(text: str) -> list[str]:
    return _PATH.findall(_HISTORY.sub(" ", text))


def migrations_named(text: str) -> set[str]:
    out = {n for group in _MIGRATION_PHRASE.findall(text) for n in re.findall(r"\d{3}", group)}
    index = _section(text, "## 10. Index")
    paragraph = index.split("**Migrations**", 1)[-1].split("\n\n", 1)[0] if "**Migrations**" in index else ""
    return out | set(re.findall(r"\b(\d{3})\b", paragraph))


def routes_named(text: str) -> set[tuple[str, str]]:
    return {(m, p) for m, p in _ROUTE.findall(text)}


def functions_named(text: str) -> set[str]:
    return set(_FUNCTION.findall(text))


def rbac_named(text: str) -> set[tuple[str, str]]:
    return set(_RBAC.findall(text))


# ── resolution ───────────────────────────────────────────────────────────────

def _top_level_defs(rel: str) -> set[str]:
    tree = ast.parse(_production()[rel])
    return {n.name for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


def _defined_anywhere(name: str) -> bool:
    pattern = re.compile(rf"^\s*(?:async\s+)?(?:def|class)\s+{re.escape(name)}\b", re.M)
    return any(pattern.search(text) for text in _production().values())


def _sql_function(name: str) -> bool:
    pattern = re.compile(rf"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:public\.)?{re.escape(name)}\b", re.I)
    return any(pattern.search(text) for text in _migrations().values())


def function_problem(token: str) -> str | None:
    """Why `token` (`module.function` or `function`) names nothing, or None when it names something."""
    *qualifier, name = token.split(".")
    if qualifier:
        files = [rel for rel in _production() if rel.rsplit("/", 1)[-1] == qualifier[-1] + ".py"]
        if files:
            if any(name in _top_level_defs(rel) for rel in files):
                return None
            return f"{qualifier[-1]} ({', '.join(files)}) defines no {name}"
    if _defined_anywhere(name) or _sql_function(name):
        return None
    return f"no function or class {name} is defined in production code or in a migration"


# ── the record exists and is whole ───────────────────────────────────────────

def test_the_record_exists_and_is_not_a_stub():
    text = _doc()
    assert len(text) > 8000, "the design record is a stub; it replaces ~40 KB of reports"
    for guardrail in ("G1", "G2", "G3", "G4"):
        assert re.search(rf"^### {guardrail} ", text, re.M), f"no heading for guardrail {guardrail}"
    assert "uq_client_sales_invoices_billing_run" in text, "the duplicate-invoice index is the lifecycle's authority"
    assert "## 9." in text and "## 1. The decisions of 14 June 2026" in text


def test_each_guardrail_section_cites_a_test_that_holds_it():
    """A guardrail with no test named is a claim."""
    for guardrail in ("G1", "G2", "G3", "G4"):
        section = _section(_doc(), f"### {guardrail} ")
        assert _BARE_TEST.search(section) or re.search(r"\.test\.ts", section), (
            f"{guardrail} cites no test; say which one holds it")


# ── names resolve ────────────────────────────────────────────────────────────

def test_the_extractors_find_something():
    """A vacuity floor: an extractor that matched nothing would pass every rule below."""
    text = _doc()
    assert len(set(paths_named(text))) >= 20
    assert len(migrations_named(text)) >= 15
    assert len(routes_named(text)) >= 15
    assert len(functions_named(text)) >= 15
    assert len(rbac_named(text)) >= 4


def test_every_path_it_names_exists():
    missing = [p for p in dict.fromkeys(paths_named(_doc())) if not any((root / p).is_file() for root in ROOTS)]
    bare = [t for t in dict.fromkeys(_BARE_TEST.findall(_doc())) if not (API / "tests" / t).is_file()]
    assert not missing and not bare, f"the record names files that do not exist: {missing + bare}"


def test_every_migration_it_names_exists():
    have = {name.split("_", 1)[0] for name in _migrations()}
    missing = sorted(migrations_named(_doc()) - have)
    assert not missing, f"the record names migrations that do not exist: {missing}"


def test_every_route_it_names_is_mounted():
    missing = sorted(routes_named(_doc()) - _routes())
    assert not missing, f"the record names routes that are not mounted: {missing}"


def test_the_route_the_record_says_is_gone_is_gone():
    """§5: the route that said "send reminders" and sent nothing was replaced by flag-followups."""
    assert ("POST", "/api/billing/collections/send-reminders") not in _routes()
    assert "send-reminders" in _doc(), "the record no longer says what replaced it; update this test with it"


@pytest.mark.parametrize("token", sorted(functions_named(_doc())) if DOC.is_file() else [])
def test_every_function_it_names_is_defined(token):
    problem = function_problem(token)
    assert problem is None, f"the record names {token}(): {problem}"


@pytest.mark.parametrize("token", MUST_NAME)
def test_the_functions_the_record_must_keep_naming_are_named_and_defined(token):
    assert token in functions_named(_doc()), f"the record stopped naming {token}()"
    assert function_problem(token) is None, function_problem(token)


def test_every_sql_object_it_names_is_created_by_a_migration():
    sql = "\n".join(_migrations().values())
    for name in SQL_OBJECTS:
        assert name in _doc(), f"the record no longer names {name}; remove it from SQL_OBJECTS"
        assert name in sql, f"the record names {name} and no migration creates it"
    for table in TABLES_FROM_073:
        assert re.search(rf"CREATE TABLE IF NOT EXISTS {table}\b", _migrations()["073_revenue_ops_foundation.sql"]), table
        assert table in _doc(), f"the record no longer names {table}"


def test_every_uq_index_it_names_is_created_by_a_migration():
    sql = "\n".join(_migrations().values())
    for index in sorted(set(re.findall(r"\buq_\w+", _doc()))):
        assert index in sql, f"the record names the index {index} and no migration creates it"


# ── the decisions it records are the ones the code holds ─────────────────────

def test_every_resource_it_names_is_a_pair_the_permission_table_holds():
    for resource, action in sorted(rbac_named(_doc())):
        assert resource in PERMISSIONS and action in PERMISSIONS[resource], f'rbac("{resource}", "{action}")'


def test_the_decisions_of_14_june_are_what_the_permission_table_holds():
    staff = {Role.PARTNER, Role.MANAGER, Role.EXECUTIVE, Role.REVIEWER}
    for resource in ("practice", "billing"):                         # Option A: Partner-only
        assert set(PERMISSIONS[resource]["read"]) == {Role.PARTNER} == set(PERMISSIONS[resource]["write"])
    assert set(PERMISSIONS["knowledge"]["read"]) == staff            # a portal client never reads it
    assert set(PERMISSIONS["knowledge"]["write"]) == {Role.PARTNER, Role.MANAGER}    # Manager and above author
    assert set(PERMISSIONS["client_instruction"]["read"]) == staff
    assert set(PERMISSIONS["client_instruction"]["write"]) == {Role.PARTNER, Role.MANAGER, Role.EXECUTIVE}


def _function_nodes(rel: str) -> list[ast.AST]:
    return [n for n in ast.walk(ast.parse(_production()[rel]))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _route_functions(rel: str) -> list[ast.AST]:
    def is_route(fn) -> bool:
        return any(isinstance(d, ast.Call) and getattr(d.func, "attr", "") in ("get", "post", "put", "patch", "delete")
                   for d in fn.decorator_list)
    return [fn for fn in _function_nodes(rel) if is_route(fn)]


@pytest.mark.parametrize("rel, resource", [("routers/billing.py", "billing"), ("routers/practice.py", "practice")])
def test_every_route_of_a_partner_only_router_asks_the_resource(rel, resource):
    """G1's API layer for these two routers is the permission table, so a route that skipped it is a hole."""
    routes = _route_functions(rel)
    assert len(routes) >= 3, f"found {len(routes)} routes in {rel}; the reader is not seeing them"
    bare = [fn.name for fn in routes if f'rbac("{resource}"' not in ast.get_source_segment(_production()[rel], fn)]
    assert not bare, f"{rel}: these routes do not ask rbac(\"{resource}\", ...): {bare}"


def test_the_unique_indexes_and_generated_column_are_what_the_record_says():
    m = _migrations()
    assert re.search(r"CREATE UNIQUE INDEX IF NOT EXISTS uq_client_sales_invoices_billing_run\s+ON client_sales_invoices"
                     r"\(billing_schedule_id, billing_period\)\s+WHERE billing_schedule_id IS NOT NULL",
                     m["075_billing_traceability.sql"])
    assert "uq_clients_one_internal_per_firm" in m["080_one_internal_client_per_firm.sql"]
    assert "UNIQUE (firm_id, client_id)" in m["073_revenue_ops_foundation.sql"]
    assert "UNIQUE (article_id, version)" in m["073_revenue_ops_foundation.sql"]
    assert "GENERATED ALWAYS AS (billed_invoice_id IS NOT NULL)" in m["078_billable_capture.sql"]


# ── statements about what is NOT built or NOT decided expire ─────────────────

_KB_FILES = ("services/knowledge_service.py", "routers/knowledge.py")
_FULL_TEXT = re.compile(r"text_search|textSearch|tsquery|ts_rank|websearch", re.I)


def _calls_ilike_on_title(fn: ast.AST) -> bool:
    return any(isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "ilike"
               and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "title"
               for n in ast.walk(fn))


def test_knowledge_base_search_is_title_only_and_the_record_says_so():
    """EXPIRES. The day article content is searched, the record's "Search is by title only" is false.

    When this fails: someone built (or began) full-text search. Rewrite §7 and the first row of the §9 table to
    say what it searches and how it ranks, then change this test to hold that instead.
    """
    assert "Search is by title only" in _doc(), "the record's claim moved; move this test with it"
    search = next(fn for fn in _function_nodes("services/knowledge_service.py") if fn.name == "search_articles")
    assert _calls_ilike_on_title(search), "search_articles no longer filters on the title with ilike"
    for rel in _KB_FILES:
        assert not _FULL_TEXT.search(_production()[rel]), f"{rel} now uses a text-search construct"
    kb_sql = [name for name, text in _migrations().items() if "knowledge_article" in text and _FULL_TEXT.search(text)]
    assert not kb_sql, f"a migration builds knowledge-base text search: {kb_sql}; the record says there is none"


def test_the_manager_is_firm_wide_in_the_knowledge_base_alone_and_the_record_says_so():
    """EXPIRES. POST-B-029 is the decision; when it is taken one of these two sets changes.

    When this fails: the Manager's scope was decided. Rewrite the Manager column of the §7 table and the §9 row,
    then change this test to hold the decision.
    """
    from core import authz
    from services import knowledge_service
    assert "firm-wide in the knowledge base alone" in _doc(), "the record's claim moved; move this test with it"
    assert "manager" in knowledge_service._FIRMWIDE_ROLES
    assert Role.MANAGER not in authz._FIRMWIDE_ROLES
    assert "get_my_role() IN ('Partner','Manager')" in _migrations()["079_knowledge_rls.sql"]


def _called_names(rel: str, scope: str) -> set[str]:
    fn = next(n for n in _function_nodes(rel) if n.name == scope)
    return {getattr(c.func, "attr", getattr(c.func, "id", "")) for c in ast.walk(fn) if isinstance(c, ast.Call)}


def test_the_defects_observed_while_writing_the_record_are_still_there():
    """EXPIRES. §9 lists six things seen on 8 October 2026 and changed by nobody. Each is asserted here.

    When one fails: it was fixed. Delete its bullet from §9, delete its assertion, and say so in the commit.
    """
    from routers import sales_invoices
    from services import billing_service

    # 1. A due schedule whose period already has an invoice returns without advancing, so it stays due.
    generate = next(n for n in _function_nodes("services/billing_service.py") if n.name == "generate_for_schedule")
    early = next(n for n in ast.walk(generate) if isinstance(n, ast.If) and ast.unparse(n.test) == "existing")
    assert not any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_advance_schedule"
                   for c in ast.walk(early)), "the early return now advances the schedule; fix §9"

    # 2. Cadence arithmetic is the schedule's own, and a run date above the 28th becomes the 28th.
    assert billing_service.next_run_after("monthly", "2026-10-31") == "2026-11-28"

    # 3. Nothing at issue refuses a number that still begins DRAFT-.
    sales_invoices._assert_invoice_no_legal(billing_service.draft_placeholder_invoice_no())

    # 4. edit_article has no retry on the version collision.
    edit = next(n for n in _function_nodes("services/knowledge_service.py") if n.name == "edit_article")
    assert not any(isinstance(n, (ast.Try, ast.For, ast.While)) for n in ast.walk(edit)), (
        "edit_article now handles the UNIQUE (article_id, version) collision; fix §7 and §9")

    # 5. The G3 customer is a snapshot: only the billing service and the portal reader touch the link at all.
    touching = {rel for rel, text in _production().items()
                if re.search(r"""table\(["']client_firm_customer_links["']\)""", text)}
    assert touching == {"services/billing_service.py", "services/portal_data_service.py"}, (
        f"{sorted(touching)} touch client_firm_customer_links; if one refreshes the customer, fix §3 and §9")

    # 6. Nothing schedules draft generation, and nothing bills time.
    for name in ("run_due", "mark_time_entries_billed"):
        users = {rel for rel, text in _production().items()
                 if re.search(rf"billing_service\.{name}\b|from services\.billing_service import[^\n]*\b{name}\b", text)}
        allowed = {"routers/billing.py"} if name == "run_due" else set()
        assert users == allowed, f"{name} is now reached from {sorted(users - allowed)}; fix §4/§6 and §9"


def test_nothing_reads_the_clients_external_view():
    """EXPIRES. §3 G2 says the view was meant to be the single source and nothing reads it."""
    quoted = re.compile(r"""["']clients_external["']""")
    readers = [rel for rel, text in _production().items() if quoted.search(text)]
    web = REPO / "apps" / "web"
    for folder in ("app", "components", "lib"):
        readers += [str(p.relative_to(REPO)) for p in (web / folder).rglob("*.ts*") if quoted.search(p.read_text(errors="ignore"))]
    assert not readers, f"{readers} read clients_external; G2 in the record says nothing does"


# ── negative controls: the extractors can see what they claim to ─────────────

def test_the_path_reader_skips_history_and_finds_a_missing_file():
    text = "`git show 315e6a19:docs/BATCH_3_COMPLETION_REPORT.md` and `docs/architecture/11-nope.md`"
    assert paths_named(text) == ["docs/architecture/11-nope.md"]


def test_the_migration_reader_reads_phrases_lists_and_the_index_paragraph():
    assert migrations_named("see migration 075, and migrations 074, 079 and 080") == {"075", "074", "079", "080"}
    text = "## 10. Index\n\n**Migrations** (x):\n073 foundation, 142 other.\n\n**Tests**: 999"
    assert migrations_named(text) == {"073", "142"}


def test_the_route_reader_wants_a_method_and_the_function_reader_a_pair_of_brackets():
    assert routes_named("`POST /api/receipts/` and `/api/billing` and POST /collections/x") == {("POST", "/api/receipts/")}
    assert functions_named("`a.b.c()` then rbac() but not f(x)") == {"a.b.c", "rbac"}
    assert rbac_named('`rbac("billing", "write")`') == {("billing", "write")}


def test_the_function_resolver_tells_a_real_name_from_a_renamed_one():
    assert function_problem("billing_service.generate_for_schedule") is None
    assert function_problem("billing_service.generate_for_schedulez") is not None
    assert function_problem("collections_service.assess_invoice") is None         # three modules define it
    assert function_problem("get_my_role") is None                                  # an SQL function
    assert function_problem("no_such_thing") is not None


def test_a_section_stops_at_the_next_heading_of_its_level():
    text = "### G1 a\nbody\n### G2 b\nother\n## 9\nmore"
    assert _section(text, "### G1 ") == "### G1 a\nbody"
