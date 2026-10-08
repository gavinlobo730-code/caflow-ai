"""The architecture overview documents name what the code under them has built.

WHY THIS EXISTS

    docs/architecture/01 to 04 were written before the multi-currency phases, the
    two-kinds-of-closed split, the line-order column and the bill-wise opening
    documents, and each carried a sentence that a later change made false:

      01  "Frozen multi-currency architecture (design; not yet implemented)", a
          subsystem table that omitted 06a-06e, 09 and 10, and "nothing
          currency-aware is implemented yet";
      02  a kernel signature of fourteen parameters over a function that takes
          twenty-two, and key-first account resolution described as though a
          seeded firm had keys (`seed_firm_coa` writes none);
      03  "Period-end FX revaluation (a future phase)", over a built service;
      04  no word of the opening documents, the opening register or the trial
          balance import, and a closing note promising masters would gain a
          currency.

    A frozen or foundational document is not reopened for a sentence, so each of
    these was left until a reader was misled. The rule is derived from the code, not
    from the sentences it replaced:

      * 01 names every file beside it in docs/architecture;
      * 02 lists every parameter `_create_journal` has, in its signature block, and
        names each seeding function in `coa_seed_service`;
      * 03 names every SQL function migration 361 defines (the two closures) and every
        module under `domain/currency` that asks the posting-date lock;
      * 04 names every route segment of the form `opening-...` that the routers mount,
        except those listed below with the reason they are another subject.

    It checks that nothing the code has is missing from the overview, not that the
    description is right.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
API = REPO / "apps" / "api"
ARCH = REPO / "docs" / "architecture"

#: Route segments beginning "opening-" that are not about the books' opening position, with why.
OTHER_SUBJECTS = {
    "opening-suggestion": "a bank reconciliation session's suggested opening figure (a GET that "
                          "posts nothing), described in 09-bank-entries.md and not a posting of an "
                          "opening position",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def mentions(doc: str, name: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_-]){re.escape(name)}(?![A-Za-z0-9_-])", doc) is not None


# ── 01 ───────────────────────────────────────────────────────────────────────
def sibling_documents() -> list[str]:
    return sorted(p.name for p in ARCH.glob("*.md") if not p.name.startswith("01-"))


def unnamed_siblings(doc: str, siblings: list[str]) -> list[str]:
    return [s for s in siblings if f"`{s}`" not in doc]


# ── 02 ───────────────────────────────────────────────────────────────────────
def function_parameters(source: str, name: str) -> list[str]:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            a = node.args
            params = [x.arg for x in a.posonlyargs + a.args + a.kwonlyargs]
            return [p for p in params if p != "self"]
    return []


def signature_block(doc: str) -> str:
    m = re.search(r"Signature[^\n]*\n+```[^\n]*\n(.*?)```", doc, re.DOTALL)
    return m.group(1) if m else ""


def missing_parameters(doc: str, params: list[str]) -> list[str]:
    block = signature_block(doc)
    return [p for p in params if not re.search(rf"\b{re.escape(p)}\b", block)]


def top_level_functions(source: str, prefix: str) -> list[str]:
    return [n.name for n in ast.parse(source).body
            if isinstance(n, ast.FunctionDef) and n.name.startswith(prefix)]


# ── 03 ───────────────────────────────────────────────────────────────────────
def sql_functions_defined(sql: str) -> list[str]:
    return re.findall(r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:public\.)?(\w+)\s*\(", sql, re.IGNORECASE)


def modules_asking_the_lock(directory: Path) -> list[str]:
    return sorted(p.stem for p in directory.glob("*.py") if "validate_posting_date" in _read(p))


# ── 04 ───────────────────────────────────────────────────────────────────────
def route_segments(source: str) -> set[str]:
    """Every `opening-...` segment of a route path or router prefix in the module."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        candidates: list[str] = []
        if (isinstance(node.func, ast.Attribute)
                and node.func.attr in {"get", "post", "put", "patch", "delete"}
                and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            candidates.append(node.args[0].value)
        for kw in node.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                candidates.append(kw.value.value)
        for path in candidates:
            out.update(s for s in path.split("/") if re.fullmatch(r"opening-[a-z-]+", s))
    return out


def mounted_opening_segments() -> set[str]:
    found: set[str] = set()
    for path in sorted((API / "routers").glob("*.py")):
        found |= route_segments(_read(path))
    return found


def unnamed_opening_routes(doc: str, segments: set[str]) -> list[str]:
    return sorted(s for s in segments if s not in OTHER_SUBJECTS and not mentions(doc, s))


# ── tests ────────────────────────────────────────────────────────────────────
def test_01_names_every_document_beside_it():
    missing = unnamed_siblings(_read(ARCH / "01-accounting-engine.md"), sibling_documents())
    assert not missing, f"01-accounting-engine.md does not name: {missing}"


def test_02_lists_every_parameter_the_kernel_takes():
    doc = _read(ARCH / "02-posting-kernel.md")
    params = function_parameters(_read(API / "services" / "phase2_journal_service.py"), "_create_journal")
    missing = missing_parameters(doc, params)
    assert not missing, f"02's signature block omits _create_journal's parameters: {missing}"


def test_02_names_the_function_that_seeds_a_firms_chart_of_accounts():
    doc = _read(ARCH / "02-posting-kernel.md")
    seeds = top_level_functions(_read(API / "services" / "coa_seed_service.py"), "seed_")
    unnamed = [s for s in seeds if not mentions(doc, s)]
    assert not unnamed, f"02 does not name the chart seeding function(s): {unnamed}"


def test_03_names_the_closures_and_every_currency_module_that_asks_the_lock():
    doc = _read(ARCH / "03-financial-years.md")
    sql = _read(next(API.glob("migrations/361_*.sql")))
    functions = sorted(set(sql_functions_defined(sql)))
    modules = modules_asking_the_lock(API / "domain" / "currency")
    unnamed = [n for n in functions + modules if not mentions(doc, n)]
    assert not unnamed, f"03-financial-years.md does not name: {unnamed}"


def test_04_names_every_opening_route_the_routers_mount():
    doc = _read(ARCH / "04-opening-balances.md")
    missing = unnamed_opening_routes(doc, mounted_opening_segments())
    assert not missing, f"04-opening-balances.md does not name the route(s): {missing}"


def test_every_exemption_is_still_a_real_route_with_a_reason():
    mounted = mounted_opening_segments()
    for segment, reason in OTHER_SUBJECTS.items():
        assert segment in mounted, f"{segment} is no longer mounted: delete its exemption"
        assert len(reason) > 30


def test_the_collectors_are_not_vacuous():
    assert len(sibling_documents()) >= 12
    params = function_parameters(_read(API / "services" / "phase2_journal_service.py"), "_create_journal")
    assert {"db", "firm_id", "lines", "txn_currency", "currency_policy"} <= set(params), params
    assert signature_block(_read(ARCH / "02-posting-kernel.md")), "02's signature block was not found"
    assert top_level_functions(_read(API / "services" / "coa_seed_service.py"), "seed_")
    sql = _read(next(API.glob("migrations/361_*.sql")))
    assert {"period_closure_reason", "period_lock_reason"} <= set(sql_functions_defined(sql))
    assert "fx_revaluation_service" in modules_asking_the_lock(API / "domain" / "currency")
    assert {"opening-balances", "opening-documents", "opening-register"} <= mounted_opening_segments()


def test_the_rules_fire_on_each_way_an_overview_can_be_stale():
    # 01: a sibling it does not name
    assert unnamed_siblings("`a.md`", ["a.md", "b.md"]) == ["b.md"]
    # 02: a parameter the signature block lacks, and a block that is not there at all
    doc = "Signature (x):\n\n```\nf(db, firm_id)\n```\n"
    assert function_parameters("class K:\n    def f(self, db, firm_id, extra=1): pass", "f") == ["db", "firm_id", "extra"]
    assert missing_parameters(doc, ["db", "firm_id", "extra"]) == ["extra"]
    assert missing_parameters("no block here", ["db"]) == ["db"]
    # 03: a lock-asking module is found by what it calls, not by its name
    assert sql_functions_defined("CREATE OR REPLACE FUNCTION public.a_closure(x uuid) ...") == ["a_closure"]
    # 04: segments come from decorators and prefixes, and a plain /opening is not one of them
    src = ('router = APIRouter(prefix="/api/opening-things")\n'
           '@router.post("/opening-register")\ndef a(): pass\n'
           '@router.get("/opening")\ndef b(): pass\n')
    assert route_segments(src) == {"opening-things", "opening-register"}
    assert unnamed_opening_routes("only opening-things", {"opening-things", "opening-register"}) == ["opening-register"]
    # an exempt segment needs no mention
    assert unnamed_opening_routes("", {"opening-suggestion"}) == []
    # a longer name is not the shorter one
    assert not mentions("opening-registers", "opening-register")
