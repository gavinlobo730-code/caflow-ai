"""No AI route serves a sample, claims an execution nobody performed, or offers a
context that carries no data (ai-10).

WHAT WAS WRONG
    Several things read as AI features and were stubs:

      * `GET /api/ai-insights/cross-client` returned a HARDCODED list — a director
        called Rajesh Mehta, three client ids that exist in no firm — for every
        firm, under a docstring promising cross-client intelligence;
      * `GET /api/copilot/summaries` filtered the in-memory `MOCK_SUMMARIES` list
        whatever the mode, so in production it answered an empty list;
      * `POST /api/copilot/actions` wrote a row, set it `executed` and returned
        `{"status": "executed"}` having executed nothing;
      * the recommendations tab listed a table nothing ever wrote to, and its empty
        state congratulated the CA that "All insights have been actioned";
      * the /copilot dropdown offered "Executive" and "Relationships" contexts for
        which `_build_context` injected no figure at all, so the model answered
        ungrounded and had no way to say so.

THE RULE, NOT A LIST OF THE FIVE
    Each guard below states what a fake looks like and derives the routes to
    check from the application's own route table, so a sixth stub added next year
    is caught by shape and not by name:

      1. an AI route's own source never names a `MOCK_*` fixture;
      2. a function an AI router imports and serves never RETURNS a literal list
         of records (a hardcoded sample is a `return [{...}, {...}]` with nothing
         computed in it);
      3. an AI router never writes a status of `executed`, `completed`, `sent`
         or `filed` into a literal — those are claims about the world and a
         literal makes them without checking;
      4. a context the page offers is a context the server attaches data for,
         and the two lists are asserted equal against what `_build_context`
         actually injects.

    The detectors are tested against snippets that DO the thing, so a guard that
    stopped matching would fail here rather than pass quietly.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import pathlib
import re
import textwrap
import typing

import pytest

from main import app

API = pathlib.Path(__file__).resolve().parents[1]
WEB = API.parents[1] / "apps" / "web"

#: Every router whose prefix is an AI surface. DERIVED from the route table — a
#: new router under one of these prefixes is covered the day it is mounted.
AI_PREFIXES = ("/api/copilot", "/api/ai-copilot", "/api/ai-insights", "/api/memory",
               "/api/assistant")

#: A status literal that is a claim about something that happened.
EARNED_ONLY_STATUSES = {"executed", "completed", "sent", "filed", "submitted"}


# ── the detectors ────────────────────────────────────────────────────────────

def names_a_mock_fixture(source: str) -> list[str]:
    """`MOCK_*` identifiers a function's source refers to."""
    tree = ast.parse(textwrap.dedent(source))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id.startswith("MOCK_"):
            found.add(node.id)
        elif isinstance(node, ast.alias) and node.name.startswith("MOCK_"):
            found.add(node.name)
    return sorted(found)


def returns_a_literal_sample(source: str) -> bool:
    """True if the function RETURNS a list of >= 1 dicts made only of constants.

    `ast.literal_eval` succeeding is the test: a computed answer has a name or a
    call in it, and a sample does not. A dict with fewer than three keys is not
    counted — `[{"id": 1}]` is a stub, but `[{"a": 1}]` as a status response is
    ordinary — which is why the bar is a RECORD, not a scrap.
    """
    tree = ast.parse(textwrap.dedent(source))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError, TypeError):
            continue
        if (isinstance(value, list) and value
                and all(isinstance(r, dict) and len(r) >= 3 for r in value)):
            return True
    return False


def writes_an_unearned_status(source: str) -> list[str]:
    """Statuses written as a literal into a dict: `{"status": "executed"}`."""
    tree = ast.parse(textwrap.dedent(source))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and k.value == "status"
                        and isinstance(v, ast.Constant)
                        and v.value in EARNED_ONLY_STATUSES):
                    found.append(v.value)
    return found


# ── the detectors do detect ──────────────────────────────────────────────────

def test_the_detectors_find_each_of_the_fakes_that_were_deleted():
    """Negative controls: the shapes of the code that was removed, verbatim in
    kind. A detector that stops finding them is the failure."""
    assert names_a_mock_fixture('''
        def list_summaries():
            from repositories.ai_copilot_repository import MOCK_SUMMARIES
            return [s for s in MOCK_SUMMARIES if s["firm_id"] == "f"]
    ''') == ["MOCK_SUMMARIES"]

    assert returns_a_literal_sample('''
        def get_cross_client_patterns(firm_id=None):
            return [
                {"pattern_type": "shared_director", "title": "Rajesh Mehta",
                 "confidence": 72},
                {"pattern_type": "same_issue", "title": "ITC mismatch",
                 "confidence": 85},
            ]
    ''')

    assert writes_an_unearned_status('''
        def execute_ai_action(payload):
            result = {"action_id": "a", "status": "executed"}
            return result
    ''') == ["executed"]


def test_the_detectors_leave_computed_answers_alone():
    assert not names_a_mock_fixture("def f(x):\n    return x + 1\n")
    assert not returns_a_literal_sample('''
        def suggestions():
            return {"suggestions": GLOBAL_SUGGESTED_QUESTIONS}
    ''')
    assert not returns_a_literal_sample('''
        def f(rows):
            return [{"id": r["id"], "name": r["name"], "n": len(r)} for r in rows]
    ''')
    assert not writes_an_unearned_status('def f():\n    return {"status": "pending"}\n')


# ── the routes ───────────────────────────────────────────────────────────────

def _ai_routes():
    out = []
    for r in app.routes:
        path = getattr(r, "path", "")
        endpoint = getattr(r, "endpoint", None)
        if endpoint is None or not path.startswith(AI_PREFIXES):
            continue
        for m in sorted(getattr(r, "methods", set()) - {"HEAD", "OPTIONS"}):
            out.append((m, path, endpoint))
    return out


AI_ROUTES = _ai_routes()


def test_the_walk_finds_the_ai_routes():
    """Non-vacuity: a guard that scans nothing asserts nothing."""
    prefixes = {p for _, path, _ in AI_ROUTES for p in AI_PREFIXES if path.startswith(p)}
    assert prefixes == set(AI_PREFIXES), f"found only {sorted(prefixes)}"
    assert len(AI_ROUTES) > 30


@pytest.mark.parametrize("method,path,endpoint",
                         [pytest.param(*r, id=f"{r[0]} {r[1]}") for r in AI_ROUTES])
def test_no_ai_route_names_a_mock_fixture(method, path, endpoint):
    src = inspect.getsource(endpoint)
    assert not names_a_mock_fixture(src), (
        f"{method} {path} reads a MOCK_* fixture directly — in production that is "
        f"either an empty answer or a stranger's sample")


def _served_functions():
    """Functions an AI router serves: its own, and those it IMPORTS BY NAME from
    a domain/service/repository module (`from domain.x import (a, b)`), which is
    how `get_cross_client_patterns` hid its sample one call below the route."""
    seen: dict[str, object] = {}
    modules = {e.__module__ for _, _, e in AI_ROUTES}
    for modname in sorted(modules):
        mod = importlib.import_module(modname)
        tree = ast.parse(pathlib.Path(mod.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in (
                    "domain", "services", "repositories"):
                try:
                    target = importlib.import_module(node.module)
                except ImportError:
                    continue
                for alias in node.names:
                    fn = getattr(target, alias.name, None)
                    if inspect.isfunction(fn):
                        seen[f"{node.module}.{alias.name}"] = fn
        for name, fn in inspect.getmembers(mod, inspect.isfunction):
            if fn.__module__ == modname:
                seen[f"{modname}.{name}"] = fn
    return seen


SERVED = _served_functions()


def test_the_served_function_walk_is_not_empty():
    assert len(SERVED) > 30
    assert "routers.ai_insights.insight_feed" in SERVED


@pytest.mark.parametrize("name", sorted(SERVED))
def test_no_function_an_ai_router_serves_returns_a_literal_sample(name):
    src = inspect.getsource(SERVED[name])
    assert not returns_a_literal_sample(src), (
        f"{name} returns a hardcoded list of records — a sample presented as the "
        f"firm's own data")


@pytest.mark.parametrize("modname", sorted({e.__module__ for _, _, e in AI_ROUTES}))
def test_no_ai_router_writes_an_unearned_status(modname):
    mod = importlib.import_module(modname)
    src = pathlib.Path(mod.__file__).read_text()
    assert not writes_an_unearned_status(src), (
        f"{modname} writes a status of executed/completed/sent/filed as a literal: "
        f"that is a claim about the world made without checking it")


def test_the_routes_that_were_deleted_are_not_mounted():
    mounted = {(m, p) for m, p, _ in AI_ROUTES}
    for gone in [("GET", "/api/ai-insights/cross-client"),
                 ("GET", "/api/copilot/summaries"),
                 ("POST", "/api/copilot/actions"),
                 ("GET", "/api/copilot/recommendations"),
                 ("POST", "/api/copilot/recommendations/{rec_id}/action")]:
        assert gone not in mounted, f"{gone} is mounted again — see ai-10"


# ── the contexts the page may offer ──────────────────────────────────────────

class _Clients:
    def find_all(self, **kw):
        return [{"id": "c1", "client_name": "A", "status": "active", "health_score": 80}]

    def find_by_id(self, *a, **kw):
        return {"id": "c1", "client_name": "A", "status": "active", "health_score": 80}


class _Tasks:
    def find_overdue(self, **kw):
        return [{"id": "t1", "client_id": "c1"}]


class _Compliance:
    def find_all(self, **kw):
        return [{"client_id": "c1", "status": "Overdue", "due_date": "2026-01-01"}]


class _Workflows:
    def list_failures(self, *a, **kw):
        return [{"instance_id": "i"}]

    def list_approvals(self, *a, **kw):
        return []

    def client_ids_for_instances(self, firm_id, ids):
        return {i: "c1" for i in ids}


@pytest.fixture
def world(monkeypatch):
    import domain.ai_copilot_service as mod
    monkeypatch.setattr(mod, "_get_client_repo", lambda: _Clients())
    monkeypatch.setattr(mod, "_get_task_repo", lambda: _Tasks())
    monkeypatch.setattr(mod, "_get_compliance_records_repo", lambda: _Compliance())
    monkeypatch.setattr(mod, "_get_workflow_repo", lambda: _Workflows())
    return mod.ai_copilot_service


HEADER = ("FIRM:", "DATE:", "CONTEXT TYPE:", "CONTEXT NOTE:")


def _figures(context: str) -> list[str]:
    return [ln for ln in context.splitlines() if not ln.startswith(HEADER)]


def test_every_context_the_server_accepts_attaches_data(world):
    """`ContextType` IS the list a request may name; each must inject at least one
    figure beyond the three header lines."""
    from models.ai_copilot import CONTEXTS_WITH_DATA, ContextType
    assert tuple(typing.get_args(ContextType)) == CONTEXTS_WITH_DATA
    for ctx in CONTEXTS_WITH_DATA:
        context = world._build_context("f1", ctx, "c1" if ctx == "client" else None, None)
        assert _figures(context), f"context {ctx!r} attaches no data — it would answer ungrounded"


def test_a_context_with_no_data_is_refused_at_the_door():
    from pydantic import ValidationError
    from models.ai_copilot import ConversationCreateIn, MessageIn
    for ctx in ("executive", "relationship"):
        with pytest.raises(ValidationError):
            MessageIn(content="hello", context_type=ctx)
        with pytest.raises(ValidationError):
            ConversationCreateIn(context_type=ctx)


def test_a_conversation_already_stored_under_a_dead_context_is_answered_as_global(world):
    """Rows created from the old dropdown still exist. They are answered with the
    firm-wide figures and the model is told the context carried none of its own."""
    context = world._build_context("f1", "executive", None, None)
    assert "CONTEXT TYPE: global" in context
    assert "CONTEXT NOTE:" in context and "'executive'" in context
    assert _figures(context), "the fallback must attach the global figures"


def test_the_copilot_page_offers_only_contexts_that_attach_data():
    """The page's dropdown, read from source, is a subset of what the server
    attaches data for — and `client` is absent because the page has no client
    picker to give it an id."""
    from models.ai_copilot import CONTEXTS_WITH_DATA
    src = (WEB / "app/copilot/page.tsx").read_text()
    block = re.search(r"const CONTEXT_CHOICES[^=]*=\s*\[(.*?)\];", src, re.S)
    assert block, "CONTEXT_CHOICES not found — the guard cannot check what it cannot read"
    offered = re.findall(r'value:\s*"([a-z]+)"', block.group(1))
    assert offered, "no contexts parsed from the page"
    assert set(offered) <= set(CONTEXTS_WITH_DATA), (
        f"the page offers {sorted(set(offered) - set(CONTEXTS_WITH_DATA))}, which the server "
        f"attaches no data for")
    assert "client" not in offered
    # And the old spellings are not hiding as <option> literals elsewhere.
    assert not re.search(r'<option value="(executive|relationship)"', src)


def test_the_copilot_page_has_no_recommendations_tab_or_calls():
    src = (WEB / "app/copilot/page.tsx").read_text()
    for gone in ("listRecommendations", "actRecommendation", "executeAction",
                 "All insights have been actioned"):
        assert gone not in re.sub(r"/\*.*?\*/", "", src, flags=re.S), gone
