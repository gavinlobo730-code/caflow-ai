"""Every first-party import resolves, and every global a function reads exists.

WHAT WAS WRONG
    On 27-09-2026 a sweep of production found three kinds of NameError-class
    defect, all shipped, all invisible to a mock suite of ~18,000 tests:

      * `from core.config import settings` in TEN routers (fourteen imports)
        and `from core.database import get_db` in the employee-portal service.
        Neither module has ever existed. Every import sat inside a function —
        the routers' own `_mock_enabled()` — so the module loaded, the app
        booted, and every endpoint that asked "am I in mock mode?" answered
        with a bare 500 before it touched the database: CWIP, opening
        documents, quotations and orders, purchase orders and goods receipts,
        bills of entry, additional GST registrations, RCM documents, the
        e-commerce operator returns, GSTR-9C and GSTR-4. Employee portal
        invites could never be sent.
      * `from domain.reporting.sources import mock_ledger_source` in the cash
        flow forecast — the name lives in `domain.reporting.service` — which
        broke that endpoint in production too, because the import ran before
        the SUPABASE_URL branch.
      * Ten globals read and never defined or imported: the cash book's
        `_db()`, three `log_event` calls on the §10 bonus register, the TDS
        deductor endpoint's `get_supabase` and `api_response`, and the
        `capture_posting_failure` / `capture_soft_failure` hooks in the
        journal and receipt services — the last three only on the FAILURE
        path, so an ordinary failure became a NameError that hid it.

    The mock suite could not see any of them because none of those tests ever
    CALLED the function: most read its source with `inspect.getsource`, and a
    source scan passes whatever the source says.

WHY THE STANDARD LIBRARY
    pyflakes finds the second kind directly, and is not a dependency — adding
    it to requirements.txt would ship a linter in the production image. The
    import half needs importlib anyway (a static tool cannot know what a
    first-party module exports), and the undefined-name half is `symtable`,
    which is the compiler's own scope analysis.
"""
from __future__ import annotations

import ast
import builtins
import importlib
import importlib.util
import pathlib
import symtable
import sys

import pytest

_API = pathlib.Path(__file__).resolve().parents[1]

# Top-level directories that are not application code: this file's own
# neighbours, one-off scripts, SQL.
_SKIP_TOP = {"tests", "scripts", "migrations", "__pycache__", ".venv", "venv"}

_FIRST_PARTY = sorted(
    {p.name for p in _API.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    | {p.stem for p in _API.glob("*.py")}
)
_FIRST_PARTY = [m for m in _FIRST_PARTY if m not in _SKIP_TOP]

_MODULE_DUNDERS = {
    "__file__", "__name__", "__doc__", "__builtins__", "__spec__", "__loader__",
    "__package__", "__path__", "__annotations__", "__dict__", "__module__",
    "__qualname__", "__class__", "__debug__",
}
_BUILTINS = set(dir(builtins)) | _MODULE_DUNDERS


def _application_files() -> list[pathlib.Path]:
    out = []
    for p in sorted(_API.rglob("*.py")):
        rel = p.relative_to(_API)
        if rel.parts[0] in _SKIP_TOP or "__pycache__" in rel.parts:
            continue
        out.append(p)
    return out


def _module_name(path: pathlib.Path) -> str:
    rel = path.relative_to(_API).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


# ── Half one: every global a function (or the module) reads is defined ─────────

def undefined_globals(source: str, filename: str = "<src>") -> list[tuple[int, str, str]]:
    """(line of the enclosing scope, name, scope) for every name read as a
    global that the module never binds and builtins do not provide.

    A module doing `from x import *` is skipped: what it binds cannot be known
    without importing x, and none of this codebase does it.
    """
    if "import *" in source:
        return []
    top = symtable.symtable(source, filename, "exec")
    bound = {s.get_name() for s in top.get_symbols()
             if s.is_assigned() or s.is_imported() or s.is_namespace()}

    def declared_global(t):
        for s in t.get_symbols():
            if s.is_declared_global() and s.is_assigned():
                bound.add(s.get_name())
        for c in t.get_children():
            declared_global(c)

    declared_global(top)

    found: list[tuple[int, str, str]] = []

    def walk(t):
        is_module = t.get_type() == "module"
        for s in t.get_symbols():
            name = s.get_name()
            if name in bound or name in _BUILTINS or not s.is_referenced():
                continue
            if is_module:
                found.append((t.get_lineno(), name, "<module>"))
            # A local or a parameter is never a global read. Asking is_local()
            # as well as is_global() is not redundancy: CPython 3.11's symtable
            # decides "module scope" from the table's NAME being "top", so a
            # nested function literally called `top` reports its own
            # parameters as globals (domain/practice/concentration.py has one).
            elif (s.is_global() and not s.is_declared_global()
                  and not s.is_local() and not s.is_parameter()):
                found.append((t.get_lineno(), name, t.get_name()))
        for c in t.get_children():
            walk(c)

    walk(top)
    return found


# ── Half two: every first-party import resolves ─────────────────────────────────

def _guarded_import_nodes(tree: ast.AST) -> set[int]:
    """ids of Import/ImportFrom nodes inside a `try` that catches ImportError —
    an optional import is allowed to be absent, that is what the try says."""
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        catches = False
        for h in node.handlers:
            names = []
            if h.type is None:
                catches = True
            elif isinstance(h.type, ast.Tuple):
                names = [e.id for e in h.type.elts if isinstance(e, ast.Name)]
            elif isinstance(h.type, ast.Name):
                names = [h.type.id]
            if {"ImportError", "ModuleNotFoundError", "Exception"} & set(names):
                catches = True
        if catches:
            for stmt in node.body:
                for sub in ast.walk(stmt):
                    if isinstance(sub, (ast.Import, ast.ImportFrom)):
                        guarded.add(id(sub))
    return guarded


def imports_of(source: str, module_name: str, is_package: bool,
               first_party: list[str]) -> list[tuple[int, str, str | None]]:
    """(line, absolute module, imported name or None) for every first-party
    import in the source — module level AND inside functions, which is where
    every defect this file was written for lived."""
    tree = ast.parse(source)
    guarded = _guarded_import_nodes(tree)
    package = module_name if is_package else module_name.rpartition(".")[0]
    out: list[tuple[int, str, str | None]] = []
    for node in ast.walk(tree):
        if id(node) in guarded:
            continue
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in first_party:
                    out.append((node.lineno, a.name, None))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                mod = importlib.util.resolve_name("." * node.level + (node.module or ""), package)
            else:
                mod = node.module or ""
            if mod.split(".")[0] not in first_party:
                continue
            for a in node.names:
                out.append((node.lineno, mod, None if a.name == "*" else a.name))
    return out


def import_problem(module: str, name: str | None) -> str | None:
    """None when `import module` / `from module import name` would succeed."""
    try:
        if importlib.util.find_spec(module) is None:
            return f"no module named {module!r}"
    except ModuleNotFoundError:
        return f"no module named {module!r}"
    if name is None:
        return None
    m = importlib.import_module(module)
    if hasattr(m, name):
        return None
    # `from package import submodule` — only a package has submodules, and
    # find_spec on "<plain module>.<name>" raises rather than answering None.
    if hasattr(m, "__path__") and importlib.util.find_spec(f"{module}.{name}") is not None:
        return None
    return f"{module!r} has no {name!r}"


# ── The rules ───────────────────────────────────────────────────────────────────

_FILES = _application_files()


def test_the_scan_sees_the_application():
    # A floor, so a path change that empties the scan fails here rather than
    # making both rules below pass on nothing.
    assert len(_FILES) > 500, len(_FILES)
    assert {"core", "domain", "routers", "services"} <= set(_FIRST_PARTY)


def test_every_global_a_function_reads_is_defined():
    problems = []
    for p in _FILES:
        for line, name, scope in undefined_globals(p.read_text(encoding="utf-8"), str(p)):
            problems.append(f"{p.relative_to(_API)}: {name!r} read in {scope} "
                            f"(scope opens at line {line}) is never defined or imported")
    assert not problems, "\n".join(problems)


def test_every_first_party_import_resolves():
    if str(_API) not in sys.path:
        sys.path.insert(0, str(_API))
    problems = []
    seen: dict[tuple[str, str | None], str | None] = {}
    checked = 0
    for p in _FILES:
        is_package = p.name == "__init__.py"
        for line, mod, name in imports_of(p.read_text(encoding="utf-8"),
                                          _module_name(p), is_package, _FIRST_PARTY):
            key = (mod, name)
            if key not in seen:
                seen[key] = import_problem(mod, name)
            checked += 1
            if seen[key]:
                problems.append(f"{p.relative_to(_API)}:{line}: {seen[key]}")
    assert checked > 3000, checked  # the lazy imports are most of them
    assert not problems, "\n".join(problems)


# ── Negative controls: each rule catches the defect it was written for ─────────

def test_the_name_rule_catches_a_helper_nobody_defined():
    src = "import os\n\ndef get_cash_book():\n    db = _db()\n    return os.sep, db\n"
    assert [(n, s) for _, n, s in undefined_globals(src)] == [("_db", "get_cash_book")]


def test_the_name_rule_catches_a_call_on_the_failure_path_only():
    src = ("def post():\n    try:\n        return 1\n"
           "    except Exception as e:\n        capture_posting_failure(e)\n")
    assert [n for _, n, _ in undefined_globals(src)] == ["capture_posting_failure"]


def test_the_name_rule_is_quiet_about_locals_imports_and_builtins():
    src = ("from x import y\nZ = 1\n\ndef top(n):\n    return [c for c in range(n)] + [y, Z, len]\n"
           "\ndef later():\n    global W\n    W = 2\n\ndef reads_w():\n    return W\n")
    assert undefined_globals(src) == []


def test_the_import_rule_catches_a_module_that_never_existed():
    src = "def _mock_enabled():\n    from core.config import settings\n    return settings.USE_MOCK\n"
    found = imports_of(src, "routers.cwip", False, _FIRST_PARTY)
    assert found == [(2, "core.config", "settings")]
    assert import_problem("core.config", "settings") == "no module named 'core.config'"


def test_the_import_rule_catches_a_name_imported_from_the_wrong_module():
    assert import_problem("domain.reporting.sources", "mock_ledger_source") == (
        "'domain.reporting.sources' has no 'mock_ledger_source'")
    assert import_problem("domain.reporting.service", "mock_ledger_source") is None


def test_the_import_rule_resolves_relative_imports_and_submodules():
    found = imports_of("from .tds_computer import TDSComputer\n", "domain.tds", True, _FIRST_PARTY)
    assert found == [(1, "domain.tds.tds_computer", "TDSComputer")]
    assert import_problem("domain.tds.tds_computer", "TDSComputer") is None
    assert import_problem("domain", "tds") is None


def test_an_import_the_code_says_is_optional_is_allowed_to_be_absent():
    src = "try:\n    from core.config import settings\nexcept ImportError:\n    settings = None\n"
    assert imports_of(src, "x", False, _FIRST_PARTY) == []


@pytest.mark.parametrize("name", ["_db", "log_event", "api_response"])
def test_premise_a_bare_name_really_does_raise_at_call_time(name):
    # Why a module that imports cleanly can still 500: the lookup is deferred
    # to the call, so nothing short of calling it — or this scan — notices.
    ns: dict = {}
    exec(f"def f():\n    return {name}()\n", ns)
    with pytest.raises(NameError):
        ns["f"]()
