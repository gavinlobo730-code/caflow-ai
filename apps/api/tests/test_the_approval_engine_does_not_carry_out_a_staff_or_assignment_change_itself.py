"""The approval engine holds no staff or assignment write of its own (ledger POST-A-240, 19-10-2026).

WHAT WAS WRONG
    `services/approval_service` carried six request types whose handlers lived in the engine module and wrote the
    repositories directly: user create, user activation, role change, assignment create, remove and transfer. Nothing in
    the product ever raised one. Each skipped what the direct route asks first (that the user and, for an assignment, the
    client belong to this firm; the invitation a new user needs), and a handler whose update matched no user returned an
    empty result, so the request read `approved` and nothing had happened. They were retired.

WHAT IS HELD (the rule, so the next type cannot be added the same way)
    * no registered handler is DEFINED in the engine module. A request type's action lives in its own service module, as
      the lost-authenticator reset's does, where it owns its validation and calls the function the route calls;
    * the engine module names no staff or assignment repository, imported or used.

A scan that cannot fail is not a guard, so the scanners below are run on source written to break each rule.
"""
from __future__ import annotations

import ast
import inspect

import services.approval_service as svc

STAFF_AND_ASSIGNMENT_REPOSITORIES = frozenset({
    "user_repo", "user_repository", "UserRepository",
    "assignment_repo", "assignment_repository", "AssignmentRepository",
})


def _repositories_named(source: str) -> set[str]:
    """Every staff or assignment repository the source imports or uses, by any spelling the import system offers."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and node.id in STAFF_AND_ASSIGNMENT_REPOSITORIES:
            found.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in STAFF_AND_ASSIGNMENT_REPOSITORIES:
            found.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                for part in (alias.name.split(".") + [alias.asname or ""]):
                    if part in STAFF_AND_ASSIGNMENT_REPOSITORIES:
                        found.add(part)
            if isinstance(node, ast.ImportFrom) and node.module:
                found.update(p for p in node.module.split(".") if p in STAFF_AND_ASSIGNMENT_REPOSITORIES)
    return found


def _handlers_defined_in(specs: dict, module_name: str) -> list[str]:
    """The request types whose handler is a function defined in `module_name` (a def or a lambda written there)."""
    return sorted(t for t, spec in specs.items() if getattr(spec["handler"], "__module__", None) == module_name)


# ── the rules on the real engine ──────────────────────────────────────────────────────────────────────────────────

def test_the_engine_has_at_least_one_registered_type_so_the_scan_below_is_not_vacuous():
    assert "mfa_reset" in svc._SPECS


def test_no_registered_handler_is_defined_in_the_engine_module():
    assert _handlers_defined_in(svc._SPECS, svc.__name__) == [], (
        "a request type's action belongs in its own service module, where it owns its validation and calls the function "
        "the route calls; see this file's docstring")


def test_the_engine_module_names_no_staff_or_assignment_repository():
    assert _repositories_named(inspect.getsource(svc)) == set()


# ── negative controls: each scanner fails on source written to break its rule ────────────────────────────────────

def test_the_repository_scan_finds_every_spelling_of_a_staff_or_assignment_write():
    spellings = {
        "from repositories.user_repository import user_repo\n": {"user_repository", "user_repo"},
        "import repositories.assignment_repository as assignment_repository\n": {"assignment_repository"},
        "from repositories import assignment_repository\n": {"assignment_repository"},
        "def h(p):\n    return user_repo.update(p['id'], {'role': 'Partner'}, firm_id='f')\n": {"user_repo"},
        "def h(p, repos):\n    return repos.assignment_repo.create('f', 'u', 'c')\n": {"assignment_repo"},
        "from repositories.user_repository import UserRepository as U\n": {"user_repository", "UserRepository"},
    }
    for source, expected in spellings.items():
        assert expected <= _repositories_named(source), source
    assert _repositories_named("def h(p):\n    return {'ok': True}\n") == set()


def test_the_handler_scan_finds_a_def_and_a_lambda_written_in_the_engine_module():
    def written_here(firm, payload):
        return {}

    written_here.__module__ = "services.approval_service"
    lam = (lambda firm, payload: {})
    lam.__module__ = "services.approval_service"

    def written_elsewhere(firm, payload):
        return {}

    written_elsewhere.__module__ = "services.mfa_reset_service"
    specs = {"a": {"handler": written_here}, "b": {"handler": lam}, "c": {"handler": written_elsewhere}}
    assert _handlers_defined_in(specs, "services.approval_service") == ["a", "b"]
