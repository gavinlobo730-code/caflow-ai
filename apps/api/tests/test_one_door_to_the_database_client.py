"""A module asks for its database client in one place (engineering-30).

WHAT WAS WRONG
    About a hundred modules each defined a private function whose whole job was `from core.supabase_client
    import get_supabase; return get_supabase()`: `_db` in 47 of them, `_get_db` in 36, `_supabase` in 11, and
    `_prod_db`, `_filing_db`, `_challan_db`, `_loc_db`, `_svc`, `_service_supabase`, `_db_or_none` once each. They
    came in five shapes (request-scoped or privileged, each with or without a "no database configured is None"
    branch, and four routers that answer 503 instead), so how a client is obtained, which is the thing the
    USE_USER_JWT cutover changed, was a hundred places to read and a hundred and first to get wrong.

    `core/db_provider.py` is the one place now, five functions each named for what it answers. Every module that
    had a shim binds the name it always had to one of them (`_db = db_provider.request_db`), so the hundred
    tests that patch `module._db` are untouched, and the four modules with a `_USE_MOCK` or a 503 branch keep a
    two-line function that calls the provider.

THE RULE, NOT THE NAME
    The scan looks for the SHAPE of a shim, not for `_db`: a function with no parameters whose last statement
    returns a direct call to one of the client getters, after at most a guard clause. So `_client()`, `_sb()` or a
    `_get_database()` written next year is found the same way, and the list of exceptions is empty. The getters
    themselves are called, with arguments, in hundreds of places that are not shims and are not touched: a route
    that needs the client for one statement says `db = get_supabase()` and that is fine. What was duplicated was
    the ACCESSOR, and that is what is forbidden.

THE PROVIDER LOOKS UP AT CALL TIME
    A test that patches `core.supabase_client.get_supabase` expects the next call to see it. A provider that bound
    the getter at import would have frozen the real one for every module at once, which is why the provider
    imports inside each function and a test below fails an import at module level.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import HTTPException

from core import db_provider

API = Path(__file__).resolve().parents[1]
SKIP = {"tests", "migrations", "__pycache__", ".venv", "venv"}
GETTERS = {"get_supabase", "get_service_supabase", "get_request_supabase", "get_user_supabase",
           "get_anon_supabase"}
#: The two modules that define and wrap the getters. Everything else asks for a client through the provider.
EXEMPT = {"core/supabase_client.py", "core/db_provider.py"}


# ═══ The rule ════════════════════════════════════════════════════════════════════════════════════════════════════

def _statements(fn: ast.FunctionDef) -> list[ast.stmt]:
    return [s for s in fn.body if not (isinstance(s, ast.Expr) and isinstance(getattr(s, "value", None), ast.Constant))]


def is_a_client_shim(fn: ast.AST) -> bool:
    """No parameters, at most five statements, and the last one returns a direct call to a client getter."""
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    a = fn.args
    if a.args or a.kwonlyargs or a.vararg or a.kwarg or a.posonlyargs:
        return False
    body = _statements(fn)
    if not body or len(body) > 5 or not isinstance(body[-1], ast.Return):
        return False
    value = body[-1].value
    return isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in GETTERS


def shims(source: str) -> list[str]:
    return [n.name for n in ast.walk(ast.parse(source)) if is_a_client_shim(n)]


def _tree() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for path in sorted(API.rglob("*.py")):
        rel = path.relative_to(API)
        if rel.parts[0] in SKIP or rel.as_posix() in EXEMPT:
            continue
        text = path.read_text(encoding="utf-8")
        if "supabase" not in text:                           # cheap prefilter
            continue
        found = shims(text)
        if found:
            out[rel.as_posix()] = found
    return out


def test_the_detector_finds_a_shim_under_any_name_and_in_each_shape_and_nothing_else():
    plain = "def _client():\n    from core.supabase_client import get_supabase\n    return get_supabase()\n"
    guarded = ("def _sb():\n    if not os.environ.get('SUPABASE_URL'):\n        return None\n"
               "    from core.supabase_client import get_service_supabase\n    return get_service_supabase()\n")
    documented = 'def anything():\n    """Docstring."""\n    return get_supabase()\n'
    not_a_shim = {
        "takes an argument": "def f(token):\n    return get_user_supabase(token)\n",
        "builds a query": "def f():\n    return get_supabase().table('t').select('id')\n",
        "does real work": "def f():\n    a = 1\n    b = 2\n    c = 3\n    d = 4\n    e = 5\n    return get_supabase()\n",
        "returns something else": "def f():\n    db = get_supabase()\n    return db.table('t')\n",
        "calls the provider": "def f():\n    return db_provider.request_db()\n",
    }
    assert shims(plain) == ["_client"] and shims(guarded) == ["_sb"] and shims(documented) == ["anything"]
    for why, source in not_a_shim.items():
        assert shims(source) == [], why


def test_the_scan_reads_enough_modules_to_mean_something():
    """Vacuity floor. The modules below (core/db_provider, the four 503 and `_USE_MOCK` wrappers) must be reachable
    by the same walk, and a tree this size has hundreds of files that mention the client."""
    seen = [p for p in API.rglob("*.py") if p.relative_to(API).parts[0] not in SKIP]
    assert len(seen) > 500


def test_no_module_defines_its_own_accessor_for_the_database_client():
    found = _tree()
    assert not found, ("a private function whose whole job is to return a Supabase client. Ask core.db_provider "
                       "instead (`_db = db_provider.request_db`, or service_db for the privileged client, "
                       "the _or_none forms where mock mode answers without one, service_db_or_503 for a route "
                       "with no in-memory answer): " + ", ".join(f"{p}::{n}" for p, ns in found.items() for n in ns))


def test_the_provider_resolves_the_getters_when_called_not_when_imported():
    tree = ast.parse((API / "core" / "db_provider.py").read_text(encoding="utf-8"))
    top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not [n for n in top_level if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("core.supabase_client")]


# ═══ The provider ════════════════════════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def getters(monkeypatch):
    from core import supabase_client
    monkeypatch.setattr(supabase_client, "get_supabase", lambda: "REQUEST")
    monkeypatch.setattr(supabase_client, "get_service_supabase", lambda: "SERVICE")


def test_each_provider_function_returns_the_client_its_name_says(getters):
    assert db_provider.request_db() == "REQUEST"
    assert db_provider.service_db() == "SERVICE"


def test_the_or_none_forms_answer_none_without_a_database_and_the_client_with_one(getters, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    assert db_provider.request_db_or_none() is None and db_provider.service_db_or_none() is None
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.test")
    assert db_provider.request_db_or_none() == "REQUEST" and db_provider.service_db_or_none() == "SERVICE"


def test_the_503_form_says_why_and_never_hands_back_none(getters, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    with pytest.raises(HTTPException) as exc:
        db_provider.service_db_or_503("The register lives in the database.")
    assert exc.value.status_code == 503 and exc.value.detail == "The register lives in the database."
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.test")
    assert db_provider.service_db_or_503("unused") == "SERVICE"


# ═══ The modules that had a shim keep their name, their client and their branch ══════════════════════════════════

def _module(dotted: str):
    import importlib
    return importlib.import_module(dotted)


# (module, name, the client it must hand back, whether it answers None without SUPABASE_URL)
ALIASES = [
    ("services.collections_service", "_db", "REQUEST", False),            # was get_supabase()
    ("core.authz", "_db", "SERVICE", False),                              # was get_service_supabase()
    ("routers.banking", "_db", "REQUEST", True),                          # env-guarded, request-scoped
    ("routers.payroll", "_db", "SERVICE", True),                          # env-guarded, privileged
    ("services.hub_service", "_db", "SERVICE", False),                    # imported the getter at module level
    ("repositories.assignment_repository", "_db", "REQUEST", False),
    ("domain.compliance_record_service", "_filing_db", "REQUEST", True),
    ("routers.accounting", "_prod_db", "SERVICE", True),
]


@pytest.mark.parametrize("dotted,name,client,none_without_env", ALIASES)
def test_a_module_that_had_a_shim_still_answers_what_it_did(getters, monkeypatch, dotted, name, client,
                                                            none_without_env):
    accessor = getattr(_module(dotted), name)
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.test")
    assert accessor() == client
    if none_without_env:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        assert accessor() is None


@pytest.mark.parametrize("dotted,starts_with", [
    ("routers.late_interest", "Interest is computed from the live books"),
    ("routers.price_lists", "Price lists are kept in the database"),
    ("routers.post_dated_cheques", "The cheque register is kept in the database"),
    ("routers.gst_credit_ledger", "The credit-ledger opening balance is kept in the database"),
])
def test_the_four_routes_with_no_in_memory_answer_still_say_503_in_their_own_words(getters, monkeypatch, dotted,
                                                                                   starts_with):
    module = _module(dotted)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    with pytest.raises(HTTPException) as exc:
        module._db()
    assert exc.value.status_code == 503 and exc.value.detail.startswith(starts_with)
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.test")
    assert module._db() == "SERVICE"


@pytest.mark.parametrize("dotted", ["routers.payments", "routers.portal", "services.portal_data_service"])
def test_a_module_gated_on_its_own_mock_flag_still_answers_none_in_mock_mode(getters, monkeypatch, dotted):
    module = _module(dotted)
    monkeypatch.setattr(module, "_USE_MOCK", True)
    assert module._db() is None
    monkeypatch.setattr(module, "_USE_MOCK", False)
    assert module._db() == "REQUEST"


def test_a_patch_on_the_modules_own_name_still_wins(getters, monkeypatch):
    """A hundred tests do this: they move `module._db`, not the getter."""
    from services import collections_service
    monkeypatch.setattr(collections_service, "_db", lambda: "PATCHED")
    assert collections_service._db() == "PATCHED"
