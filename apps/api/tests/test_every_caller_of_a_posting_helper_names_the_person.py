"""A posting a person makes is stored with that person as its poster and creator (POST-A-376).

WHAT WAS WRONG
    `phase2_journal_service._create_journal` stores `created_by` and `posted_by` from its `created_by` parameter, and the helpers that build
    the entry for a document (`journal_for_sales_invoice`, `journal_for_receipt`, the note, bill, payment, payroll, asset and capital
    work-in-progress helpers) took no person at all, so every posting a person made through a document stored NULL in both columns. Read-only
    on production on 3-11-2026: of 13,073 live posted entries, 6,448 had no poster, and 28 of those were real typed postings made by people
    (sales invoices, purchase bills, fixed assets, depreciation, vendor payments, credit and debit notes, asset disposals). The edit log was
    not affected (the ledger door carries the person's sign-in id to the audit trigger, migration 545); what was blank is the "posted by" a
    reader of the entry shows.

WHAT THIS HOLDS (mock mode, no database)
    * EVERY HELPER THAT BUILDS A DOCUMENT'S ENTRY TAKES THE PERSON. Derived from the class's own source: every `journal_for_*` method must
      have a `created_by` parameter, so a helper added later is held to it without anyone listing it.
    * EVERY CALLER NAMES THE PERSON. Every call to one of them anywhere in the API (outside the tests and the service itself) passes
      `created_by=`. The one exception is listed with its reason and the list is an equality in both directions, so an exception that has
      since passed the person (or gone) fails until it is deleted.
    * WHICH ID IS NOT THIS FILE'S QUESTION. `created_by` and `posted_by` are foreign keys to `users.id`, the INTERNAL id, and
      `test_a_bare_person_column_takes_the_id_it_holds.py` follows the kernel's `posted_by` through its whole caller graph and fails an
      origin that is the sign-in id. Together they are the rule: a person is named, and it is the right one.
    * THE SCAN IS NOT BLIND: synthetic sources show a call with the person passed, a call without it, a positional person and a helper
      without the parameter each judged correctly.
"""
from __future__ import annotations

import ast
from pathlib import Path

API = Path(__file__).resolve().parent.parent
SERVICE = "services/phase2_journal_service.py"
#: Everything in the API that is not a test: a caller in `scripts/` or `seed/` is a caller too (the first version scanned six folders and
#: an independent read pointed out the rest).
SKIP_DIRS = ("tests", "node_modules", "__pycache__")

#: (file, enclosing function) -> why it names nobody. Shrink-only.
EXEMPT: dict[tuple[str, str], str] = {
    ("services/banking_service.py", "post_transaction"):
        "no caller anywhere (the bank screen posts through the bank posting service, not this method); it only hands its `actor_id` to the "
        "timeline log and nothing says which id a caller would give it, so it names nobody rather than guess at a foreign-keyed column, and "
        "wiring a person into dead code would be a second posting path nobody asked for",
}


def _helpers(source: str) -> dict[str, bool]:
    """{helper name: takes created_by} for every `journal_for_*` method of the service."""
    tree = ast.parse(source)
    out: dict[str, bool] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("journal_for_"):
            args = node.args
            names = {a.arg for a in args.args + args.kwonlyargs}
            out[node.name] = "created_by" in names
    return out


def _is_a_person(value: ast.AST) -> bool:
    """A value that names a person: not a constant (None, an empty string), and not the sign-in id. The id's KIND is the trace's job; this
    only refuses what is plainly not an id."""
    return not isinstance(value, ast.Constant) and "auth_user_id" not in ast.unparse(value)


def _calls(source: str, helper_names: set[str]) -> list[tuple[str, int, bool]]:
    """[(enclosing function, line, names a person by keyword)] for every call of a listed helper in this source. A constant or the sign-in id names nobody."""
    tree = ast.parse(source)
    parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in helper_names:
            scope = node
            while scope in parents and not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scope = parents[scope]
            fn = scope.name if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)) else "<module>"
            named = any(k.arg == "created_by" and _is_a_person(k.value) for k in node.keywords)
            found.append((fn, node.lineno, named))
    return found


def _all_calls() -> list[tuple[str, str, int, bool]]:
    helper_names = set(_helpers((API / SERVICE).read_text(encoding="utf-8")))
    rows = []
    for path in sorted(API.rglob("*.py")):
        rel = path.relative_to(API).as_posix()
        if rel == SERVICE or any(part in SKIP_DIRS or part.startswith(".") for part in path.relative_to(API).parts):
            continue
        for fn, line, passes in _calls(path.read_text(encoding="utf-8"), helper_names):
            rows.append((rel, fn, line, passes))
    return rows


def test_every_helper_that_builds_a_documents_entry_takes_the_person():
    helpers = _helpers((API / SERVICE).read_text(encoding="utf-8"))
    assert len(helpers) >= 18, sorted(helpers)       # floor: a scan that stops matching must not pass on an empty list
    assert [h for h, takes in helpers.items() if not takes] == [], "a helper that posts a document's entry takes no person"


def _kernel_calls_that_drop_the_person(source: str) -> list[tuple[str, int]]:
    """[(helper, line)] for every `self._create_journal(...)` inside a `journal_for_*` method that does not pass `created_by=`."""
    tree = ast.parse(source)
    bad = []
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name.startswith("journal_for_"):
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_create_journal"
                        and not any(k.arg == "created_by" for k in node.keywords)):
                    bad.append((fn.name, node.lineno))
    return bad


def _methods_that_call_the_kernel(source: str) -> dict[str, bool]:
    """{method: takes created_by} for every method of the service, whatever its name, that calls `self._create_journal(`."""
    out = {}
    for fn in ast.walk(ast.parse(source)):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name != "_create_journal":
            if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "_create_journal" for n in ast.walk(fn)):
                out[fn.name] = "created_by" in {a.arg for a in fn.args.args + fn.args.kwonlyargs}
    return out


def test_a_method_that_calls_the_kernel_takes_the_person_whatever_it_is_called():
    """The helper rule above finds `journal_for_*`; a future helper named otherwise would escape it, so this one asks the other question."""
    found = _methods_that_call_the_kernel((API / SERVICE).read_text(encoding="utf-8"))
    assert len(found) >= 18 and "reverse_entry" in found, sorted(found)
    assert [m for m, takes in found.items() if not takes] == []
    assert _methods_that_call_the_kernel("class S:\n    def post_it(self):\n        return self._create_journal(db=1)\n") == {"post_it": False}


def test_every_helper_hands_the_person_on_to_the_kernel():
    """A helper that ACCEPTS the person and does not forward it is the same defect with a better signature."""
    source = (API / SERVICE).read_text(encoding="utf-8")
    assert _kernel_calls_that_drop_the_person(source) == []
    assert source.count("self._create_journal(") >= 19, "the scan has stopped seeing the kernel calls"
    synthetic = "class S:\n    def journal_for_x(self, created_by=None):\n        return self._create_journal(db=1)\n"
    assert _kernel_calls_that_drop_the_person(synthetic) == [("journal_for_x", 3)]


def test_every_caller_of_a_posting_helper_passes_the_person():
    rows = _all_calls()
    assert len(rows) >= 26, f"the scan found only {len(rows)} callers: it has stopped seeing them"
    missing = {(rel, fn) for rel, fn, _line, passes in rows if not passes}
    unexplained = missing - set(EXEMPT)
    assert not unexplained, (
        f"these callers post a document's entry without naming the person who made it, so the entry's poster and creator are NULL: "
        f"{sorted(unexplained)}. Pass `created_by=current_user.get('id')` (the INTERNAL id; the sign-in id is `auth_user_id` and the "
        "column does not take it).")
    now_pass = set(EXEMPT) - missing
    assert not now_pass, f"listed as exempt but they pass the person (or are gone): delete them from EXEMPT: {sorted(now_pass)}"


def test_the_exemption_has_a_reason_and_names_a_real_function():
    for (rel, fn), why in EXEMPT.items():
        tree = ast.parse((API / rel).read_text(encoding="utf-8"))
        assert any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn for n in ast.walk(tree)), (rel, fn)
        assert len(why) > 40


def test_the_scan_is_not_blind():
    service = ("class S:\n    def journal_for_a(self, x, *, created_by=None): pass\n"
               "    def journal_for_b(self, x): pass\n    def journal_for_c(self, x, created_by=None): pass\n")
    helpers = _helpers(service)
    assert helpers == {"journal_for_a": True, "journal_for_b": False, "journal_for_c": True}
    caller = ("def ok(svc, cu):\n    svc.journal_for_a(1, created_by=cu.get('id'))\n"
              "def bad(svc):\n    svc.journal_for_a(1)\n"
              "def positional(svc, cu):\n    svc.journal_for_c(1, cu.get('id'))\n"
              "def nobody(svc):\n    svc.journal_for_a(1, created_by=None)\n"
              "def blank(svc):\n    svc.journal_for_a(1, created_by='')\n"
              "def signin(svc, cu):\n    svc.journal_for_a(1, created_by=cu.get('auth_user_id'))\n"
              "def unrelated(svc):\n    svc.other_helper(1)\n")
    assert _calls(caller, set(helpers)) == [("ok", 2, True), ("bad", 4, False), ("positional", 6, False), ("nobody", 8, False),
                                            ("blank", 10, False), ("signin", 12, False)]
