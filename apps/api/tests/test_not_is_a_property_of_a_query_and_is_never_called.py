"""`.not_` on a PostgREST builder is a PROPERTY, and calling it raises before any request.

WHAT WAS WRONG
    `repositories/time_tracking_analytics_repository.py` wrote
    `.not_("ended_at", "is", None)` at seven sites. In postgrest 0.18 — the
    version this API runs on — `not_` is a `@property` returning the builder
    with its next filter negated, so the call was `builder("ended_at", ...)`
    and raised `TypeError: 'SyncSelectRequestBuilder' object is not callable`
    before a single byte left for PostgREST. Every one of the six
    /api/analytics/* endpoints that reached it answered 500 in production,
    and the mock suite never saw it, because the mock branch does not build a
    query at all.

    The right spelling, already used at a dozen sites elsewhere, is
    `.not_.is_("ended_at", "null")` / `.not_.in_(...)`.

WHY A GUARD
    The mistake is a shape — a CALL of an attribute named `not_` — and a shape
    an AST can see in every module, including one written next year, without
    running anything. It is the rule rather than a list of known-good files.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

API = pathlib.Path(__file__).resolve().parent.parent


def _modules():
    for p in sorted(API.rglob("*.py")):
        rel = p.relative_to(API)
        if rel.parts[0] in ("tests", "migrations", ".venv", "venv"):
            continue
        yield p, rel


def _called_not(source: str) -> list[int]:
    """Line numbers of every `<expr>.not_(...)` call in the source."""
    tree = ast.parse(source)
    return [node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "not_"]


def test_the_library_makes_not_a_property():
    """The premise. If a later postgrest turns `not_` back into a method, this
    fails first and the guard below should be revisited rather than obeyed."""
    from postgrest._sync.request_builder import SyncSelectRequestBuilder
    assert isinstance(inspect.getattr_static(SyncSelectRequestBuilder, "not_"), property)


def test_no_module_calls_not_as_a_function():
    offenders = []
    for path, rel in _modules():
        try:
            source = path.read_text(encoding="utf-8")
            lines = _called_not(source)
        except SyntaxError:                               # pragma: no cover
            continue
        offenders += [f"{rel}:{n}" for n in lines]
    assert not offenders, (
        "`.not_` is a property on a postgrest builder — write "
        "`.not_.is_(col, 'null')` / `.not_.in_(col, [...])`, never "
        f"`.not_(col, op, value)`: {offenders}"
    )


def test_the_guard_sees_the_call_and_passes_the_property():
    """Negative control: the scanner flags the form that shipped and leaves the
    correct form alone, so a green run above is not a blind one."""
    broken = 'q = db.table("t").select("*").not_("ended_at", "is", None)\n'
    right = 'q = db.table("t").select("*").not_.is_("ended_at", "null")\n'
    assert _called_not(broken) == [1]
    assert _called_not(right) == []


def test_the_guard_is_not_vacuous():
    """It must actually walk the tree: the property form is in use, so a scan
    that read nothing would find none of it."""
    uses = 0
    for path, _rel in _modules():
        uses += path.read_text(encoding="utf-8").count(".not_.")
    assert uses >= 10
