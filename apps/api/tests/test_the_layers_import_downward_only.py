"""The layers of the backend import downward only, and today's exceptions are a list that can only shrink (POST-A-032).

THE RULE. `domain/` is the lowest layer: it holds the rules and the arithmetic and must not reach up into `services/` (which talk to the
database and to each other) or `routers/` (the HTTP doors). `services/` must not import `routers/`. A router must not import another router:
the thing it wanted is a helper that belongs in a service. Nothing enforced any of this, and on 28-11-2026 the tree had 106 upward import statements in 47 files: 40 statements in 15
files of `domain/` reaching into `services` (`domain/inventory_service.py` fifteen, `domain/compliance_record_service.py` eleven), 18 in 10
services importing a router (mostly to reuse a document-creation function that lives there) and 48 in 22 routers importing another router.

WHAT IS HELD. The scan reads every module of the three layers with `ast`, resolves a relative import against the importer's own package, and
counts each import STATEMENT once, wherever it sits (a lazy import inside a function is the usual way an upward import hides, so it counts).
`from services import x` is an import of `services.x`. The exceptions are `tests/fixtures/upward_imports.txt`, one line per
(contract, importer, imported module) with the number of statements, and the figure is an EXACT equality in both directions: a new upward
import fails until somebody decides it is fine and writes the line, and a line whose import has gone fails until it is taken off. So the
list can shrink and cannot grow by accident. Moving a function down into the layer that should own it is the way to take a line off.

WHAT IT DOES NOT HOLD. `core/`, `repositories/`, `models/`, `jobs/`, `middleware/` and `main.py` are outside the contract (their place in the
order has not been decided); a `services` module that imports `domain` is the intended direction and is not looked at; and an import made
by `importlib` or by name in a string is not seen.
"""
from __future__ import annotations

import ast
import collections
from pathlib import Path

API = Path(__file__).resolve().parents[1]
LIST = API / "tests" / "fixtures" / "upward_imports.txt"

#: contract name -> (layer of the importer, the test of an imported module that breaks it)
CONTRACTS = {
    "domain must not import services": ("domain", lambda importer, imported: imported.split(".")[0] == "services"),
    "domain must not import routers": ("domain", lambda importer, imported: imported.split(".")[0] == "routers"),
    "services must not import routers": ("services", lambda importer, imported: imported.split(".")[0] == "routers"),
    "a router must not import another router": ("routers", lambda importer, imported: imported.split(".")[0] == "routers" and imported != importer),
}


def modules(root: Path = API) -> dict[str, str]:
    """{dotted module name: text} for every module of the three layers."""
    found = {}
    for layer in ("domain", "services", "routers"):
        for p in (root / layer).rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            found[".".join(p.relative_to(root).with_suffix("").parts)] = p.read_text(encoding="utf-8")
    return found


def _package_of(module: str, is_package: bool) -> list[str]:
    parts = module.split(".")
    return parts if is_package else parts[:-1]


def imported_modules(module: str, text: str, is_package: bool = False) -> list[str]:
    """The dotted module each import statement of `module` names (one entry per statement and name, relative imports resolved)."""
    out: list[str] = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            out.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = _package_of(module, is_package)
                if node.level - 1 >= len(base):
                    continue      # beyond the top-level package: Python refuses it (ImportError), so no such import can exist
                base = base[: len(base) - (node.level - 1)]
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            if not target:
                continue
            if "." not in target and target in ("services", "routers", "domain"):
                # `from services import x` imports services.x
                out.extend(f"{target}.{alias.name}" for alias in node.names)
            else:
                out.append(target)
    return out


def violations(sources: dict[str, str]) -> dict[tuple[str, str, str], int]:
    """{(contract, importer module, imported module): number of import statements} for every upward import the contracts forbid."""
    found: dict[tuple[str, str, str], int] = collections.Counter()
    for module, text in sources.items():
        layer = module.split(".")[0]
        is_package = module.endswith(".__init__")
        name = module[: -len(".__init__")] if is_package else module
        for imported in imported_modules(name, text, is_package):
            for contract, (importer_layer, breaks) in CONTRACTS.items():
                if layer == importer_layer and breaks(name, imported):
                    found[(contract, module, imported)] += 1
    return dict(found)


def listed() -> dict[tuple[str, str, str], int]:
    out = {}
    for raw in LIST.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        contract, importer, imported, count = (part.strip() for part in line.split("|"))
        out[(contract, importer, imported)] = int(count)
    return out


def render(found: dict[tuple[str, str, str], int]) -> str:
    return "\n".join(f"{c} | {i} | {m} | {n}" for (c, i, m), n in sorted(found.items()))


# ── the rule over the tree ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _lines(found: dict) -> str:
    return "\n  ".join(f"{c} | {i} | {m} | {n}" for (c, i, m), n in sorted(found.items()))


def test_every_upward_import_is_on_the_list_and_every_listed_one_still_happens():
    found, allowed = violations(modules()), listed()
    new = {k: n for k, n in found.items() if k not in allowed}
    changed = {k: (allowed[k], n) for k, n in found.items() if k in allowed and allowed[k] != n}
    gone = {k: n for k, n in allowed.items() if k not in found}
    parts = ["The layers import downward only (domain, then services, then routers)."]
    if new:
        parts.append("NEW upward imports, not on tests/fixtures/upward_imports.txt (move what you need down into the layer that should own it; "
                     "if it is genuinely right, add the line and say why in the commit):\n  " + _lines(new))
    if changed:
        parts.append(f"COUNT CHANGED (listed, now): {sorted(changed.items())}")
    if gone:
        parts.append("LISTED BUT NO LONGER IMPORTED, take the line off:\n  " + _lines(gone))
    assert not (new or changed or gone), "\n".join(parts)


def test_the_list_is_sorted_and_says_what_it_is():
    lines = [l.strip() for l in LIST.read_text(encoding="utf-8").splitlines() if l.strip() and not l.strip().startswith("#")]
    assert lines == sorted(lines), "keep the list sorted"
    assert all(l.split("|")[0].strip() in CONTRACTS for l in lines), "a line names a contract that does not exist"


def test_the_scan_reads_enough_to_mean_something():
    sources = modules()
    per_layer = collections.Counter(m.split(".")[0] for m in sources)
    assert per_layer["domain"] >= 100 and per_layer["services"] >= 150 and per_layer["routers"] >= 80, per_layer
    assert sum(len(imported_modules(m, t, m.endswith(".__init__"))) for m, t in sources.items()) >= 3000


# ── the rule can fail, and it reads what it claims to ─────────────────────────────────────────────────────────────────────────────────────────

def test_a_domain_module_importing_a_service_is_found_wherever_the_import_sits():
    top = violations({"domain.a": "from services.x import f\n"})
    lazy = violations({"domain.a": "def g():\n    from services.x import f\n    return f()\n"})
    plain = violations({"domain.a": "import services.x\n"})
    assert top == lazy == plain == {("domain must not import services", "domain.a", "services.x"): 1}


def test_from_a_layer_import_a_name_is_an_import_of_that_module():
    assert violations({"domain.a": "from services import audit_service\n"}) == {
        ("domain must not import services", "domain.a", "services.audit_service"): 1}


def test_a_relative_import_is_resolved_against_the_importers_own_package():
    assert violations({"domain.gst.a": "from ..x import f\n"}) == {}
    assert violations({"domain.gst.a": "from ...services.x import f\n"}) == {}, "three dots from domain.gst leaves the top-level package: Python refuses it"
    assert violations({"domain.a": "from .x import f\n"}) == {}
    assert violations({"domain.gst.a": "from .. import services\n"}) == {}, "'..' of domain.gst is the package domain"
    assert imported_modules("domain.gst.a", "from .b import f\n") == ["domain.gst.b"]
    assert imported_modules("domain.gst", "from .b import f\n", is_package=True) == ["domain.gst.b"]
    assert imported_modules("domain.gst.a", "from ..b import f\n") == ["domain.b"]


def test_the_downward_direction_is_not_flagged():
    assert violations({"services.s": "from domain.x import f\n", "routers.r": "from services.s import g\nfrom domain.x import f\n"}) == {}


def test_a_service_importing_a_router_and_a_router_importing_a_router_are_found():
    assert violations({"services.s": "def f():\n    from routers.sales_invoices import make\n"}) == {
        ("services must not import routers", "services.s", "routers.sales_invoices"): 1}
    assert violations({"routers.a": "from routers.b import h\n"}) == {
        ("a router must not import another router", "routers.a", "routers.b"): 1}
    assert violations({"routers.a": "from routers.a import h\n"}) == {}, "a module importing itself is not another router"


def test_two_statements_of_one_pair_are_counted_twice():
    both = "from services.x import f\ndef g():\n    from services.x import h\n"
    assert violations({"domain.a": both}) == {("domain must not import services", "domain.a", "services.x"): 2}
