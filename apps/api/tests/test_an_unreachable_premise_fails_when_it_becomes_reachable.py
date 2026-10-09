"""A severity that rests on "nothing reaches this" is a test, and it fails when something does.

── WHY THIS EXISTS ──────────────────────────────────────────────────────────

POST-A-179. The 11 September 2026 verification pass found seven findings
(PAY-08, PAY-07, IT-08, GST-19, PUR-04, TDS-18, ACC-18) whose severity had been
held DOWN by a sentence of the form "no screen reaches this" or "nothing calls
this function", and which went UP when Phase 7 built the screens. Nobody
re-scored them: the sentence was prose, and prose does not fail when it stops
being true. Its process fix was that a finding resting on "nothing reaches
this" must state that premise as a testable claim. This file is where the claim
is stated.

⚠️ IT ANSWERS THE OPPOSITE QUESTION FROM THE REACHABILITY RATCHETS.
`test_every_mounted_endpoint_has_a_way_in.py` counts the routes no screen calls
and holds the NUMBER down; `test_a_computed_answer_nobody_can_open_is_named.py`
freezes the computed GETs among them. Neither can say what rests on any one of
them being unreachable, and when a screen starts calling one the failure they
give is "lower the budget" — which is the exact moment a severity argued from
that silence needs re-scoring. Neither can express a Python-level premise
("no production caller") at all. The tests that go the other way
(`test_the_regime_election_has_a_door.py`, `test_the_year_end_fx_revaluation_has_a_door.py`)
insist something IS reachable, which is a different polarity again.

── THE RULE ─────────────────────────────────────────────────────────────────

Whoever writes "latent because nothing calls this" in a ledger line, a finding
or a comment adds an entry to PREMISES: the claim, and the sentence saying what
rests on it. Whoever CLOSES the item deletes the entry. When a premise stops
being true this file fails, names what now reaches it and quotes what was held
down, and the fix is to re-score that thing as though it were reachable, fix or
accept it in the same commit, and only then edit the entry.

There are two probes and only two, because every premise seen so far is one of
them:

  * a ROUTE no screen names — the way-in test's own reachability scan
    (`_sources`/`_pattern`), so the two files cannot disagree about what a screen
    can reach;
  * a SYMBOL nothing in production references — an AST walk of `apps/api`
    outside tests, migrations and scripts.

── WHAT THE PROBES CANNOT SEE, AND WHICH WAY EACH LIMIT FAILS ───────────────

Where a probe is LOOSE it is loose towards tripping, and where it is BLIND it
is blind towards holding. Both are written down so nobody reads a green run as
more than it proves.

Loose (a false alarm, whose cost is a re-score that finds nothing to change):

  * The route probe matches PATHS, not (method, path), as the way-in test
    does. A screen that wires `GET /api/compliance-records/{id}` also trips a
    premise about `POST /api/compliance-records`, because the second path is a
    literal prefix of the first.
  * The symbol probe matches NAMES. A different function called the same thing
    trips it, and so does a reference passed on as a value
    (`map(compute_amt, rows)`) or used through `import x as alias` /
    `from m import x as alias`.

Blind (a premise can hold while something does reach it):

  * `getattr(module, "name")`, string dispatch, and a name rebound to another
    (`fn = compute_amt; fn(...)`).
  * A second call inside an allowed function: `allowed` is a function, not a
    line. A premise about HOW a function is reached inside its one caller (that
    it is the firm/LLP branch, say) needs a test of its own.
  * A path a screen builds from a variable, and the second data path: the
    browser reads ~83 tables over PostgREST and names no `/api/` URL, so a screen
    built wholly on that path is invisible to the route probe.

── WHAT IS DELIBERATELY NOT HERE ────────────────────────────────────────────

This is not a second budget. The way-in test is the place for "N routes are
unreached"; an entry here needs a stated consequence (`held_down`) and the size
is capped. Nor does it check that the ledger id an entry cites still exists: a
premise can stay true after its item closes, the open-items ledger is edited by
a different commit, and a test coupled to it would go red between two commits
that are each right. A closed item's entry is deleted by whoever closes it.

⚠️ THE TWO PROBES HAVE NEGATIVE CONTROLS IN THIS FILE because guards in this
repository's history have gone inert without anybody noticing (a regex that
stopped matching, a scan that read a directory which had moved). The
`test_the_route_probe_*` and `test_the_symbol_probe_*` tests build a frontend and
a backend in a temporary directory and prove each probe reports a caller where
one exists and ignores one where it should, and two more read the real trees to
prove the probes are not looking at nothing.
"""
from __future__ import annotations

import ast
import functools
import pathlib
from dataclasses import dataclass

import pytest

from tests.test_every_mounted_endpoint_has_a_way_in import _pattern, _routes, _sources

_API = pathlib.Path(__file__).resolve().parents[1]

#: Directories that are not production code. A call from a test, a migration
#: or a one-off script is not a way in for a CA.
_NOT_PRODUCTION = frozenset({"tests", "migrations", "scripts", "__pycache__",
                             "node_modules", "venv", ".venv"})

#: A register of premises, not a second budget (see the module docstring).
MAX_PREMISES = 12


@dataclass(frozen=True)
class Premise:
    """One claim of the form 'nothing reaches this', and what rests on it."""

    claim: str
    held_down: str
    kind: str                                   # "route" | "symbol"
    routes: tuple[tuple[str, str], ...] = ()    # kind == "route": (METHOD, path)
    symbol: str = ""                            # kind == "symbol"
    #: kind == "symbol": the (path under apps/api, 'Class.function') pairs that
    #: ARE allowed to reference it — empty for 'no production caller at all'.
    allowed: frozenset[tuple[str, str]] = frozenset()


#: Every premise below was verified true on 08-10-2026 against origin/main.
PREMISES: dict[str, Premise] = {
    "compliance_records_create": Premise(
        claim=("No screen names /api/compliance-records: `api.complianceRecords.*` "
               "has no caller outside lib/api/index.ts, so nobody can send the "
               "create that POST /api/compliance-records takes."),
        held_down=("POST-A-209 is rated low and latent: ComplianceRecordIn.status "
                   "defaults to 'pending', which migration 108's CHECK refuses, so "
                   "the first screen that creates a record without a status fails "
                   "against a real database while the mock suite accepts it."),
        kind="route",
        routes=(("POST", "/api/compliance-records"),),
    ),
    "ai_copilot_firm_context_and_chat": Premise(
        claim=("No screen calls GET /api/ai-copilot/firm-context or "
               "POST /api/ai-copilot/chat."),
        held_down=("POST-A-054 is rated low because the firm AI-copilot's counts "
                   "(overdue tasks, compliance overdue, high-risk clients, open "
                   "risks) are not scoped to the caller's clients and reach the "
                   "model prompt firm-wide for an assignment-scoped Executive or "
                   "Manager; the exposure was judged small only because nobody "
                   "can call it."),
        kind="route",
        routes=(("GET", "/api/ai-copilot/firm-context"),
                ("POST", "/api/ai-copilot/chat")),
    ),
    "amt_only_for_firms": Premise(
        claim=("compute_amt has one non-test caller, ITREngine._compute_entity, "
               "and the branch that reaches it is the firm/LLP one."),
        held_down=("POST-C-093 with IT-21 and IT-07: the missing regime parameter "
                   "(s.115BAC disapplies Chapter XII-BA) and the firm's surcharge "
                   "ladder applied to an individual are both called latent because "
                   "an individual or HUF never reaches the AMT."),
        kind="symbol",
        symbol="compute_amt",
        allowed=frozenset({("domain/income_tax/itr_engine.py",
                            "ITREngine._compute_entity")}),
    ),
    "higher_rate_206ab_unused": Premise(
        claim=("TDSValidator.is_higher_rate_applicable has no production caller."),
        held_down=("TDS-24: the financial-year parameter that answers the ordinary "
                   "rate from FY 2025-26 (SECTION_206AB_OMITTED_FROM_FY, graded [S] "
                   "and unconfirmed) 'changes no live figure' only because nothing "
                   "calls it; tds_computer's header says the same. The first caller "
                   "makes that constant decide real withholding."),
        kind="symbol",
        symbol="is_higher_rate_applicable",
    ),
}


def _on_failure(premise: Premise, found: list[str]) -> str:
    return (
        f"A premise that held a severity down is no longer true.\n"
        f"  claim:     {premise.claim}\n"
        f"  now:       {'; '.join(found)}\n"
        f"  held down: {premise.held_down}\n"
        f"Something now reaches it. The severity argued for the item above assumed "
        f"it did not. Re-score it as if it were reachable (the 11 September 2026 "
        f"verification pass found seven defects that rose when a screen was built "
        f"and nobody re-scored them), fix or accept it in the same commit, and "
        f"only then edit or delete this entry."
    )


# ---------------------------------------------------------------------------
# The two probes
# ---------------------------------------------------------------------------

def routes_a_screen_names(routes, roots: tuple = ()) -> list[str]:
    """The (method, path) entries whose path some screen can reach.

    `roots` is a tuple of frontend roots; empty means the repository's own two
    (apps/web and apps/marketing), which is what the way-in test reads.
    """
    blob = _sources(roots)
    return [f"{method} {path} is named by a screen"
            for method, path in routes if _pattern(path).search(blob)]


def _python_files(root: pathlib.Path):
    for path in sorted(root.rglob("*.py")):
        if _NOT_PRODUCTION.isdisjoint(path.relative_to(root).parts[:-1]):
            yield path


class _Scan(ast.NodeVisitor):
    """References to, and definitions of, a set of names in ONE module."""

    def __init__(self, symbols: frozenset[str]):
        self.symbols = symbols
        #: local name -> the symbol it stands for. `from m import x as alias`
        #: adds `alias`; an attribute access is matched on its own name instead.
        self.local = {s: s for s in symbols}
        self.scope: list[str] = []      # class names, then at most one function
        self.function_depth = 0
        self.refs: dict[str, set[str]] = {}
        self.defs: dict[str, int] = {}

    def _note(self, symbol: str) -> None:
        self.refs.setdefault(symbol, set()).add(".".join(self.scope) or "<module>")

    def _enter(self, node, is_function: bool) -> None:
        if node.name in self.symbols:
            self.defs[node.name] = self.defs.get(node.name, 0) + 1
        # Stop naming once inside a function: a closure belongs to the function
        # that defines it, which is the thing a person can point at.
        named = self.function_depth == 0
        if named:
            self.scope.append(node.name)
        self.function_depth += is_function
        self.generic_visit(node)
        self.function_depth -= is_function
        if named:
            self.scope.pop()

    def visit_ClassDef(self, node):
        self._enter(node, False)

    def visit_FunctionDef(self, node):
        self._enter(node, True)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and node.id in self.local:
            self._note(self.local[node.id])

    def visit_Attribute(self, node):
        if isinstance(node.ctx, ast.Load) and node.attr in self.symbols:
            self._note(node.attr)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        for item in node.names:
            if item.name in self.symbols and item.asname:
                self.local[item.asname] = item.name


def scan_python(symbols: frozenset[str], root: pathlib.Path):
    """({symbol: {(relative path, enclosing)}}, {symbol: [definition paths]}).

    One pass over every production module that mentions any of the names. A
    substring test comes first so the parse is only paid where it can matter:
    an alias still names the symbol at its import.
    """
    refs: dict[str, set[tuple[str, str]]] = {s: set() for s in symbols}
    defs: dict[str, list[str]] = {s: [] for s in symbols}
    for path in _python_files(root):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not any(s in text for s in symbols):
            continue
        rel = path.relative_to(root).as_posix()
        scan = _Scan(symbols)
        scan.visit(ast.parse(text, filename=rel))
        for symbol, enclosings in scan.refs.items():
            refs[symbol] |= {(rel, enclosing) for enclosing in enclosings}
        for symbol, count in scan.defs.items():
            defs[symbol] += [rel] * count
    return refs, defs


@functools.lru_cache(maxsize=None)
def _real_scan():
    """The register's own symbols, read once from the real backend."""
    return scan_python(
        frozenset(p.symbol for p in PREMISES.values() if p.kind == "symbol"), _API)


def symbol_references(premise: Premise, root: pathlib.Path | None = None) -> list[str]:
    """Production references to the premise's symbol, less the allowed ones.

    `root` is for the negative controls; omitted it reads the real backend.
    """
    refs, _ = (_real_scan() if root is None
               else scan_python(frozenset({premise.symbol}), root))
    return [f"{premise.symbol} is referenced from {rel}::{where}"
            for rel, where in sorted(refs[premise.symbol] - premise.allowed)]


def offenders(premise: Premise, *, frontend_roots: tuple = (),
              api_root: pathlib.Path | None = None) -> list[str]:
    """What reaches the premise's subject now. Empty means the premise holds."""
    if premise.kind == "route":
        return routes_a_screen_names(premise.routes, frontend_roots)
    if premise.kind == "symbol":
        return symbol_references(premise, api_root)
    raise AssertionError(f"unknown premise kind {premise.kind!r}")


# ---------------------------------------------------------------------------
# The register
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("premise_id", sorted(PREMISES))
def test_every_premise_still_holds(premise_id):
    premise = PREMISES[premise_id]
    found = offenders(premise)
    assert not found, f"[{premise_id}]\n" + _on_failure(premise, found)


# ---------------------------------------------------------------------------
# Negative controls: the probes can see a caller
# ---------------------------------------------------------------------------

def _write(root: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


ROUTE = Premise(claim="c", held_down="h" * 50, kind="route",
                routes=(("POST", "/api/compliance-records"),))


def test_the_route_probe_sees_a_screen_that_names_the_path(tmp_path):
    root = _write(tmp_path, {
        "app/x/page.tsx": 'export default function P(){ fetch("/api/compliance-records", {method:"POST"}); return null }',
    })
    assert offenders(ROUTE, frontend_roots=(root,)), (
        "a screen that writes the URL down is a caller and the probe did not see it")


def test_the_route_probe_follows_a_unit_a_screen_names(tmp_path):
    root = _write(tmp_path, {
        "app/x/page.tsx": 'import { used } from "@/lib/u"; export default function P(){ used(); return null }',
        "lib/u.ts": 'export function used(){ return fetch("/api/compliance-records") }',
    })
    assert offenders(ROUTE, frontend_roots=(root,)), (
        "a lib unit a screen names is live and the URL it holds is reached")


def test_the_route_probe_ignores_a_unit_no_screen_names(tmp_path):
    """The api client writing the URL down is NOT a caller: that is the point."""
    root = _write(tmp_path, {
        "app/x/page.tsx": "export default function P(){ return null }",
        "lib/u.ts": 'export function neverCalled(){ return fetch("/api/compliance-records") }',
        "components/x.test.tsx": 'fetch("/api/compliance-records")',
    })
    assert offenders(ROUTE, frontend_roots=(root,)) == []


def test_the_route_probe_reads_the_real_frontend():
    """A probe whose blob went empty would pass every route premise for ever."""
    reached = [p for _, p in _routes() if _pattern(p).search(_sources())]
    assert len(reached) > 300, (
        f"only {len(reached)} mounted routes are named by a screen — the scan is "
        f"reading a hollow frontend, and every route premise would hold vacuously")


SYMBOL = Premise(claim="c", held_down="h" * 50, kind="symbol", symbol="widget_total")


def _backend(tmp_path, **files):
    return _write(tmp_path, {k.replace("__", "/") + ".py": v for k, v in files.items()})


@pytest.mark.parametrize("label, body", [
    ("a plain call", "from lib.w import widget_total\n\ndef run():\n    return widget_total(1)\n"),
    ("a method-style call", "import lib.w as w\n\ndef run():\n    return w.widget_total(1)\n"),
    ("an aliased import", "from lib.w import widget_total as wt\n\ndef run():\n    return wt(1)\n"),
    ("a reference passed on", "from lib.w import widget_total\n\ndef run(rows):\n    return list(map(widget_total, rows))\n"),
])
def test_the_symbol_probe_sees_how_a_caller_writes_it(tmp_path, label, body):
    root = _backend(tmp_path,
                    lib__w="def widget_total(x):\n    return x\n",
                    routers__caller=body)
    found = symbol_references(SYMBOL, root)
    assert found == ["widget_total is referenced from routers/caller.py::run"], (label, found)


def test_the_symbol_probe_ignores_what_is_not_production(tmp_path):
    root = _backend(
        tmp_path,
        lib__w="def widget_total(x):\n    return x\n",
        tests__test_w="from lib.w import widget_total\n\ndef test_it():\n    widget_total(1)\n",
        migrations__m="widget_total(1)\n",
        scripts__s="widget_total(1)\n",
        routers__docs='"""widget_total is described here but never called."""\n',
    )
    assert symbol_references(SYMBOL, root) == []


def test_the_symbol_probe_honours_an_allowed_caller_and_only_that_one(tmp_path):
    root = _backend(
        tmp_path,
        lib__w="def widget_total(x):\n    return x\n",
        domain__engine="from lib.w import widget_total\n\nclass Engine:\n    def compute(self):\n        return widget_total(1)\n",
    )
    allowed = Premise(claim="c", held_down="h" * 50, kind="symbol",
                      symbol="widget_total",
                      allowed=frozenset({("domain/engine.py", "Engine.compute")}))
    assert symbol_references(allowed, root) == []
    # A second caller in a different function is exactly what must trip.
    _write(root, {"domain/other.py":
                  "from lib.w import widget_total\n\ndef also():\n    return widget_total(2)\n"})
    assert symbol_references(allowed, root) == [
        "widget_total is referenced from domain/other.py::also"]


def test_the_symbol_probe_reads_the_real_backend():
    """A probe that stopped seeing the tree would pass every symbol premise."""
    refs, defs = scan_python(frozenset({"fetch_all"}), _API)
    assert len(refs["fetch_all"]) > 20, (
        f"only {len(refs['fetch_all'])} references to fetch_all found under apps/api; "
        f"the scan is not reading the backend")
    assert defs["fetch_all"] == ["core/db_paging.py"]


def _defines(path: pathlib.Path, enclosing: str) -> bool:
    """Whether `path` defines the function or class.method that `enclosing` names."""
    body = ast.parse(path.read_text(encoding="utf-8")).body
    *classes, function = enclosing.split(".")
    for name in classes:
        body = next((n.body for n in body
                     if isinstance(n, ast.ClassDef) and n.name == name), None)
        if body is None:
            return False
    return any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
               and n.name == function for n in body)


@pytest.mark.parametrize("premise_id", sorted(PREMISES))
def test_a_premise_names_something_that_exists(premise_id):
    """A rename must not leave a premise vacuously true."""
    premise = PREMISES[premise_id]
    if premise.kind == "route":
        mounted = _routes()
        assert premise.routes, f"{premise_id}: a route premise names no route"
        for key in premise.routes:
            assert key in mounted, (
                f"{premise_id}: {key} is not mounted — it moved (update the entry) "
                f"or it was deleted (and so was the premise)")
        return
    refs, defs = _real_scan()
    assert len(defs[premise.symbol]) == 1, (
        f"{premise_id}: {premise.symbol} is defined {len(defs[premise.symbol])} "
        f"times under apps/api ({defs[premise.symbol]}); a premise about a name "
        f"needs exactly one definition")
    for rel, enclosing in sorted(premise.allowed):
        assert _defines(_API / rel, enclosing), (
            f"{premise_id}: allowed caller {rel}::{enclosing} no longer exists")
        assert (rel, enclosing) in refs[premise.symbol], (
            f"{premise_id}: {rel}::{enclosing} is allowed to reference "
            f"{premise.symbol} and does not — the entry is stale, delete the pair")


def test_the_register_is_not_a_second_budget():
    assert len(PREMISES) <= MAX_PREMISES, (
        f"{len(PREMISES)} premises. This is a register of what a severity rests on, "
        f"not a list of unreached endpoints — for those, "
        f"test_every_mounted_endpoint_has_a_way_in.BUDGET is the place.")
    for premise_id, premise in PREMISES.items():
        assert premise.kind in ("route", "symbol"), premise_id
        assert len(premise.claim) > 20, f"{premise_id}: say what is claimed to be unreachable"
        assert len(premise.held_down) >= 40, (
            f"{premise_id}: name the severity that rests on it, not a note that none does")
        assert (premise.kind == "route") == bool(premise.routes), premise_id
        assert (premise.kind == "symbol") == bool(premise.symbol), premise_id
