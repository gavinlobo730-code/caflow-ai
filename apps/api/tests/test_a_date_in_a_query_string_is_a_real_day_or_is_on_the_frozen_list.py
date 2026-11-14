"""A route's date-named query parameter is judged as a day, or it is on a list that only shrinks (POST-A-380, the query-string half).

THE RULE, NOT A SPELLING OF IT
    A route function (a handler decorated `.get|post|put|patch|delete|api_route(...)`) with a parameter whose NAME says it is a day (`..._date`, `..._on`, `..._dt`, `date_from`, `date_to`,
    `as_of`, `as_at`, `occurrence`, `start`, `end`, `period_start`, `period_end`, `effective_from`, `effective_to`, `valid_until`) that FastAPI reads from the query string and that is
    annotated as a bare `str` or `Optional[str]` hands whatever a caller typed to a date parser or to a comparison of text, and a script gets a 500 with no sentence (or, in the fee billing,
    every schedule due). A parameter is a query parameter when it is not named in the route's path and its default is not a `Body`, `Form`, `File`, `Header`, `Cookie`, `Depends`, `Security`
    or `Path`: so `as_of: Optional[str] = None` is one, with or without `Query(...)`.

    It is JUDGED when the handler passes it to `query_day` (`core/query_day`, the one rule), `a_real_date` or `real_day_problem` (`core/validators`), directly, by `value=`, through a
    module-level helper that does so, or as one element of a literal tuple the handler loops over and judges each of. A `pattern=` ALONE IS NOT JUDGING: a four-two-two pattern admits
    `2026-02-30` (the docstring of `real_day_problem` says so), and `GET /api/late-interest/preview` carried one and answered 500 for it. A bare helper named `_as_of` is not judging either;
    what the helper does is what counts. The call is looked for anywhere in the handler's body (its ORDER is not read: that a template's access is asked first is held by the door tests).

    Everything else is on `tests/fixtures/bare_date_query_params.txt`, one `file::function.parameter` per line, SHRINK-ONLY in both directions: a new unjudged parameter FAILS (call
    `query_day`, do not add a line), and a line whose parameter is now judged or gone FAILS (delete it), so a fixed entry cannot be put back unseen. A rename or a move of a still-bare
    parameter replaces its line.

    A day TYPE (`IsoDate`, `OptionalIsoDate`, `PatchIsoDate`) is judged only as `Annotated[<type>, Query(...)]`. Written as `x: OptionalIsoDate = Query(None)` FastAPI discards the type's
    validator (the trap `fy: FYLabel = Query(...)` is recorded for in CLAUDE.md) and the parameter validates nothing, so that spelling FAILS.

    The list is not a verdict that the parameter is wrong: most are filters and report windows, where a malformed day answers an empty list or the handler's own sentence, and a few are
    inputs to a calculation or a delete. Each is read against its callers before it is narrowed. The name rule is a heuristic and says so (a day called `since` or `fy_start` is not matched).
"""
from __future__ import annotations

import ast
import functools
import re
from pathlib import Path

API = Path(__file__).resolve().parent.parent
LIST = API / "tests" / "fixtures" / "bare_date_query_params.txt"
SKIP_DIRS = ("tests", "migrations", "scripts", "node_modules", ".venv", "venv")
NAME = re.compile(r"(_date|_on|_dt)$|^date_(from|to)$|^(as_of|as_at|as_of_date|occurrence|start|end|period_start|period_end|effective_from|effective_to|valid_until)$")
ROUTE = re.compile(r"\.(get|post|put|patch|delete|api_route)\(")
NOT_QUERY = re.compile(r"\b(Body|Form|File|Header|Cookie|Depends|Security|Path)\s*\(")
BARE = {"str", "Optional[str]"}
DAY_TYPES = {"IsoDate", "OptionalIsoDate", "PatchIsoDate"}
JUDGES = ("query_day", "a_real_date", "real_day_problem")

# The doors a manual run or a preview comes in by: each must read as judged, so the scan cannot lose one quietly.
DOORS = (
    "routers/recurring_invoices.py::run_one_recurring.as_of",
    "routers/recurring_invoices.py::run_due_recurring.as_of",
    "routers/recurring_purchase_bills.py::run_one_recurring_bill.as_of",
    "routers/recurring_purchase_bills.py::run_due_recurring_bills.as_of",
    "routers/recurring_journals.py::generate_one.occurrence",
    "routers/recurring_journals.py::run_due.as_of",
    "routers/billing.py::preview_run.as_of",
    "routers/billing.py::run.as_of",
    "routers/late_interest.py::preview.as_of",
)


def _split_top(text: str) -> list[str]:
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def _normal(annotation: str) -> str:
    text = annotation.replace('"', "").replace("'", "").replace("typing.", "").replace(" ", "")
    if text.startswith("Annotated[") and text.endswith("]"):
        return _normal(_split_top(text[len("Annotated["):-1])[0])
    if text in ("str|None", "None|str", "Union[str,None]", "Union[None,str]"):
        return "Optional[str]"
    return text


def _call_name(node: ast.Call) -> str:
    return getattr(node.func, "attr", getattr(node.func, "id", ""))


def _names_in(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _is_the_value(call: ast.Call, names: set[str]) -> bool:
    first = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == "value"), None)
    return isinstance(first, ast.Name) and first.id in names


def _judged_in_body(fn: ast.AST, param: str, helpers: frozenset[str] = frozenset()) -> bool:
    """True when the handler passes the parameter (or an element of a literal tuple it loops over that holds the parameter) to a judge or to a module-level helper that judges."""
    names = {param}
    for loop in (n for n in ast.walk(fn) if isinstance(n, ast.For) and isinstance(n.iter, (ast.Tuple, ast.List))):
        if param in _names_in(loop.iter):
            names |= _names_in(loop.target)
    return any(isinstance(n, ast.Call) and _call_name(n) in (*JUDGES, *helpers) and _is_the_value(n, names) for n in ast.walk(fn))


def _judging_helpers(tree: ast.Module) -> frozenset[str]:
    """Module-level functions that pass one of their own parameters to a judge: `recurring_invoices._as_of` does, `late_interest._as_of` (a bare `fromisoformat`) does not."""
    return frozenset(
        fn.name for fn in tree.body
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(_judged_in_body(fn, a.arg) for a in fn.args.args)
    )


def _path_names(fn: ast.AST) -> set[str]:
    out: set[str] = set()
    for dec in getattr(fn, "decorator_list", []):
        if isinstance(dec, ast.Call) and dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
            out |= set(re.findall(r"\{(\w+)", dec.args[0].value))
    return out


def _parameters(fn: ast.AST):
    a = fn.args
    positional = a.posonlyargs + a.args
    defaults = [None] * (len(positional) - len(a.defaults)) + list(a.defaults)
    return list(zip(positional, defaults, strict=True)) + list(zip(a.kwonlyargs, a.kw_defaults, strict=True))


def scan_source(rel: str, source: str) -> tuple[set[str], set[str], set[str]]:
    """(unjudged, judged, mis-spelt day types) date-named query parameters of one module, as `file::function.param`."""
    tree = ast.parse(source)
    helpers = _judging_helpers(tree)
    bare: set[str] = set()
    judged: set[str] = set()
    misplaced: set[str] = set()
    for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
        if not any(ROUTE.search(ast.unparse(d)) for d in fn.decorator_list):
            continue
        in_path = _path_names(fn)
        for arg, default in _parameters(fn):
            if not NAME.search(arg.arg) or arg.arg in in_path:
                continue
            ann = ast.unparse(arg.annotation) if arg.annotation is not None else ""
            default_text = ast.unparse(default) if default is not None else ""
            if NOT_QUERY.search(default_text) or NOT_QUERY.search(ann):
                continue
            key = f"{rel}::{fn.name}.{arg.arg}"
            kind = _normal(ann)
            if kind in DAY_TYPES:
                if not ann.startswith("Annotated") and "Query(" in default_text:
                    misplaced.add(key)
                continue
            if kind not in BARE:
                continue
            (judged if _judged_in_body(fn, arg.arg, helpers) else bare).add(key)
    return bare, judged, misplaced


@functools.lru_cache(maxsize=1)
def scan() -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    bare: set[str] = set()
    judged: set[str] = set()
    misplaced: set[str] = set()
    for path in sorted(API.rglob("*.py")):
        rel = path.relative_to(API).as_posix()
        if rel.split("/")[0] in SKIP_DIRS:
            continue
        try:
            b, j, m = scan_source(rel, path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        bare |= b
        judged |= j
        misplaced |= m
    return frozenset(bare), frozenset(judged), frozenset(misplaced)


def _frozen() -> set[str]:
    return {ln.strip() for ln in LIST.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")}


def test_the_scan_sees_what_it_is_for():
    bare, judged, _ = scan()
    for door in DOORS:
        assert door in judged, f"{door} is not read as judged"
    assert len(bare) + len(judged) >= len(_frozen()) + len(DOORS), f"the scan found only {len(bare) + len(judged)} date-named query parameters; it has stopped reading what it reads"
    # The list was emptied on 14-11-2026, so the line above no longer bounds anything: the judged parameters only grow (108 that day).
    assert len(judged) >= 100, f"only {len(judged)} date-named query parameters are read as judged; the scan has stopped reading what it reads"


def test_no_unjudged_query_day_is_new():
    bare, _, _ = scan()
    new = sorted(bare - _frozen())
    assert not new, ("A route takes a date-named query parameter as a bare string (pass it to core.query_day.query_day in the handler, after the caller's access is asked; "
                     "do not add it to tests/fixtures/bare_date_query_params.txt):\n  " + "\n  ".join(new))


def test_the_frozen_list_names_only_parameters_that_are_still_unjudged():
    bare, _, _ = scan()
    fixed = sorted(_frozen() - bare)
    assert not fixed, ("These are no longer unjudged query days: delete their lines from tests/fixtures/bare_date_query_params.txt:\n  " + "\n  ".join(fixed))


def test_the_frozen_list_is_sorted_and_has_no_duplicates():
    lines = [ln.strip() for ln in LIST.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    assert lines == sorted(set(lines))


def test_a_day_type_is_written_inside_annotated_and_never_in_the_default_position():
    _, _, misplaced = scan()
    assert not misplaced, ("FastAPI discards a day type's validator when it is annotated bare and given `= Query(...)`, so these validate nothing; write `Annotated[<type>, Query(...)]`:\n  "
                           + "\n  ".join(sorted(misplaced)))


# ── the scan itself, on throwaway source, so that what it does not see is stated and not assumed ──────────────────────────────────────────────────────────────────────────────────────────

def _read(src: str):
    return scan_source("routers/x.py", "from typing import Optional, Annotated, Union\n" + src)


def test_the_scan_reads_the_spellings_it_says_it_reads():
    assert {_normal(a) for a in ("Optional[str]", "str | None", "Optional['str']", "Union[str, None]")} == {"Optional[str]"}
    assert _normal("Annotated[Optional[str], Query()]") == "Optional[str]" and _normal("int") == "int"
    assert _normal("Annotated[Union[str, None], Query(description='a, b')]") == "Optional[str]"
    assert _normal("Annotated[OptionalIsoDate, Query(None)]") == "OptionalIsoDate"
    fn = ast.parse("def f(as_of):\n    d = query_day(as_of, 'as_of')\n").body[0]
    assert _judged_in_body(fn, "as_of") and not _judged_in_body(fn, "other")


def test_a_plain_default_is_a_query_parameter_and_a_path_or_body_name_is_not():
    bare, judged, _ = _read("@router.get('/a')\ndef f(as_of: Optional[str] = None): ...\n"
                            "@router.get('/b')\ndef g(as_at: str): ...\n"
                            "@router.get('/c/{start}')\ndef h(start: str): ...\n"
                            "@router.post('/d')\ndef i(valid_until: Optional[str] = Body(None)): ...\n"
                            "@app.api_route('/e')\ndef j(date_from: Annotated[Union[str, None], Query()] = None): ...\n"
                            "def not_a_route(as_of: Optional[str] = None): ...\n")
    assert bare == {"routers/x.py::f.as_of", "routers/x.py::g.as_at", "routers/x.py::j.date_from"} and not judged


def test_a_pattern_alone_does_not_judge_and_a_helper_is_judged_by_what_it_does():
    bare, judged, _ = _read("_P = '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'\n"
                            "def _as_of(value): return date.fromisoformat(value) if value else None\n"
                            "def _real(value): return query_day(value, 'as_of')\n"
                            "@router.get('/a')\ndef a(as_of: Annotated[Optional[str], Query(pattern=_P)] = None): return _as_of(as_of)\n"
                            "@router.get('/b')\ndef b(as_of: Optional[str] = Query(None)): return _real(as_of)\n"
                            "@router.get('/c')\ndef c(as_of: Optional[str] = Query(None)): return query_day(value=as_of, name='as_of')\n"
                            "@router.get('/d')\ndef d(start_date: Optional[str] = None, end_date: Optional[str] = None):\n"
                            "    for label, day in (('start_date', start_date), ('end_date', end_date)):\n"
                            "        real_day_problem(day, label)\n"
                            "@router.get('/e')\ndef e(as_of: Optional[str] = None):\n    other = 1\n    query_day(other, 'as_of')\n")
    assert bare == {"routers/x.py::a.as_of", "routers/x.py::e.as_of"}
    assert judged == {"routers/x.py::b.as_of", "routers/x.py::c.as_of", "routers/x.py::d.start_date", "routers/x.py::d.end_date"}


def test_a_day_type_in_the_default_position_is_found_and_inside_annotated_is_not():
    bare, judged, misplaced = _read("@router.get('/a')\ndef a(as_of: OptionalIsoDate = Query(None)): ...\n"
                                    "@router.get('/b')\ndef b(as_of: Annotated[OptionalIsoDate, Query(None)] = None): ...\n"
                                    "@router.get('/c')\ndef c(as_of: OptionalIsoDate = None): ...\n")
    assert misplaced == {"routers/x.py::a.as_of"} and not bare and not judged
