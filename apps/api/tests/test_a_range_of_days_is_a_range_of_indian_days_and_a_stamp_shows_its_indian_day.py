"""A range of days is a range of INDIAN days, and a stored stamp is shown as the Indian day it fell on (POST-A-251).

THE DEFECT
    A `timestamptz` column comes back as UTC, and its first ten characters are the UTC day, which between 18:30 and 24:00 UTC is
    the day BEFORE the one in India. Three kinds of site took those ten characters or a UTC midnight for an Indian day:
      * a range of days handed to the database as `started_at >= 'YYYY-MM-DDT00:00:00Z'` and `<= 'YYYY-MM-DDT23:59:59Z'` (the
        time-entry list, the seven time-analytics reads and the three "completed in the period" reads of the analytics router):
        a time entry started at 01:40 IST on 1 April is stored as 31 March 20:10 UTC and was counted in March, and the last
        second of every day was dropped;
      * the same range applied in memory to mock data with `started_at[:10]`;
      * a stamp printed or exported as its first ten characters (the time export's date column, the bank reconciliation's
        completed and reopened dates, the year-end pack's approval history) or aged against `ist_today()` (an open risk's age).
    `tests/test_the_indian_day_is_never_taken_from_the_utc_clock.py` catches a calendar date taken from a clock read; it cannot
    tell that `row["created_at"][:10]` is a UTC day, because the same slice is right for a column that holds a date.

WHAT IS HELD
    * the three helpers in `core.ist_clock` (`ist_day_window`, `in_ist_window`, `ist_day_iso`) at the 20:10 UTC / 31 March
      boundary, which is where the defect lives;
    * every time-entry read hands the database midnight-IST bounds, the end EXCLUSIVE, and the in-memory twin agrees with it;
    * the export's date column and the ageing of an open risk are the Indian day;
    * a RULE over the whole API: no `[:10]` slice of a value that names a stored stamp (`..._at`) outside a short frozen list
      with a reason each. The rule is a count of a shape, not a list of today's lines, and it has a negative control. Its blind
      spots are named below.

THE RULE'S KEYS ARE THE SCHEMA'S, NOT A SUFFIX (POST-A-251, 31-10-2026). A stamp is a value named `..._at` OR named for a column that
    production's schema snapshot types `timestamptz` everywhere it appears (nine are not named `..._at`: `ack_date`, `activity_date`,
    `at`, `ewb_date`, `ewb_valid_upto`, `payroll_enabled_on`, `scheduled_for`, `snoozed_until`, `upload_date`). The three sites that sliced
    one (`ewb_date` and `ewb_valid_upto` in routers/eway_bill.py and `ack_date` in services/invoice_pdf_service.py) read through the
    Indian-day helpers now, and the doors that write them (`RecordEWBGeneratedRequest`, `RecordIRNRequest`) store the day the portal
    printed as a bare date through `core.ist_clock.portal_day`, so a reader no longer has to guess whether a longer value was Indian
    wall-clock labelled UTC or a true instant.
    CLOSED on 2-11-2026: a stamp sliced after being copied into a variable with another name (`ts = row["created_at"]` then `ts[:10]`); its
    first run found one real site (`compliance_record_service._compute_risk_score`, which aged an awaiting-documents record a day early
    between 00:00 and 05:30 IST). The copy is followed IN THE ORDER THE CODE RUNS, which the first version was not (it read a function's names as
    they stood at its END, so a cut before a later rebinding was missed and a rebinding to a converted value was forgotten by a name ending in
    `_at`): plain, annotated, chained and `:=` assignments, a conditional expression and an `or` chain; an `if` and its `else`, the arms of a `try`,
    a `with` and a `match` JOIN (a name that is a stamp on either path is one afterwards, because a cut that can be a stamp is the one to look
    at); a loop is read until the state at its top stops growing, so a name bound late in the body is seen at the top of the next trip; a
    function, a lambda and a comprehension start from the names around them less their own parameters and targets; a name read inside a
    function defined EARLIER than the copy still counts, because a closure reads a name when it is called; module-level code is a scope.
    A name assigned something that is not a stamp (`ts = ist_date_of(ts)`, even `approved_at = ist_date_of(approved_at)`) is cleared; one that is
    unpacked, looped over, bound by `as` or augmented goes back to being judged by its own spelling.
    STILL A BLIND SPOT: a stamp that is passed to another function or returned from one and cut there (the scan never crosses a call), one
    unpacked from a tuple (`a, b = r["created_at"], r["x"]` binds both names as unknown), one held on an attribute (`self.ts = ...`), one put
    in a container and read back (`d["k"] = r["created_at"]`), and one written through `global` or `nonlocal`. `break`, `continue` and
    `return` are not followed, so a path that cannot reach a cut is still counted as if it could. CLOSED on 28-10-2026: a `.split("T")[0]` /
    `.partition("T")[0]` of a stamp and a `.strftime(...)` called on a value that names one (the server holds none of either), and the
    four private copies of the stamp-to-day conversion: three are folded onto `ist_date_of` and the fourth
    (`domain/health/overrides._ist_date`) stays because it reads a naive value as Indian and raises on junk, which the helper does not,
    and says so.
"""
from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core import ist_clock
from core.ist_clock import in_ist_window, ist_day_iso, ist_day_window

API_ROOT = Path(__file__).resolve().parents[1]

# 01:40 IST on 1 April: stored as 31 March 20:10 UTC. The day the defect lives on.
APRIL_FIRST_IST = "2026-03-31T20:10:00+00:00"
# 00:10 IST on 1 May: stored as 30 April 18:40 UTC.
MAY_FIRST_IST = "2026-04-30T18:40:00+00:00"
MID_APRIL = "2026-04-15T10:00:00+00:00"


# ── the helpers ──────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_window_is_midnight_ist_to_midnight_ist_with_the_end_exclusive():
    assert ist_day_window("2026-04-01", "2026-04-30") == ("2026-04-01T00:00:00+05:30", "2026-05-01T00:00:00+05:30")
    assert ist_day_window(None, "2026-04-30") == (None, "2026-05-01T00:00:00+05:30")
    assert ist_day_window("2026-04-01", None) == ("2026-04-01T00:00:00+05:30", None)
    assert ist_day_window(date(2026, 4, 1), date(2026, 12, 31)) == ("2026-04-01T00:00:00+05:30", "2027-01-01T00:00:00+05:30")


def test_an_entry_started_after_midnight_ist_on_the_first_belongs_to_that_month():
    assert in_ist_window(APRIL_FIRST_IST, "2026-04-01", "2026-04-30") is True
    assert in_ist_window(APRIL_FIRST_IST, "2026-03-01", "2026-03-31") is False


def test_the_last_indian_minutes_of_a_month_belong_to_the_next_one():
    assert in_ist_window(MAY_FIRST_IST, "2026-04-01", "2026-04-30") is False
    assert in_ist_window(MAY_FIRST_IST, "2026-05-01", "2026-05-31") is True
    assert in_ist_window("2026-04-30T18:29:59+00:00", "2026-04-01", "2026-04-30") is True       # 23:59:59 IST


def test_open_ends_and_unreadable_stamps():
    assert in_ist_window(MID_APRIL, None, None) is True
    assert in_ist_window(MID_APRIL, "2026-04-16", None) is False
    assert in_ist_window(None, "2026-04-01", "2026-04-30") is False
    assert in_ist_window("not a stamp", "2026-04-01", "2026-04-30") is False


def test_a_stamp_shows_its_indian_day_and_a_missing_one_shows_the_default():
    assert ist_day_iso(APRIL_FIRST_IST) == "2026-04-01"          # the UTC slice would say 2026-03-31
    assert ist_day_iso("2026-04-01T09:00:00Z") == "2026-04-01"
    assert ist_day_iso(None) == "" and ist_day_iso("") == "" and ist_day_iso(None, "—") == "—"
    assert ist_day_iso(date(2026, 4, 1)) == "2026-04-01"         # a date is already a day


# ── the time-entry reads ─────────────────────────────────────────────────────────────────────────────────────────────
def _calls(mock: MagicMock, verb: str) -> list[tuple]:
    return [c.args for c in mock.mock_calls if c[0].split(".")[-1] == verb and c.args]


ANALYTICS_READS = ["get_hours_by_employee", "get_hours_by_client", "get_firm_hours", "get_effort_by_engagement",
                   "get_cost_by_client", "get_cost_by_engagement", "get_metrics_by_team_member"]


@pytest.mark.parametrize("method", ANALYTICS_READS)
def test_every_analytics_read_hands_the_database_indian_midnights(monkeypatch, method):
    import repositories.time_tracking_analytics_repository as mod
    db = MagicMock()
    monkeypatch.setattr(mod, "_USE_MOCK", False)
    monkeypatch.setattr(mod, "_get_db", lambda: db)
    getattr(mod.TimeTrackingAnalyticsRepository(), method)("F1", "2026-04-01", "2026-04-30")
    assert ("started_at", "2026-04-01T00:00:00+05:30") in _calls(db, "gte"), db.mock_calls
    assert ("started_at", "2026-05-01T00:00:00+05:30") in _calls(db, "lt"), db.mock_calls
    assert _calls(db, "lte") == [], "an inclusive upper bound drops the last second of the day"


@pytest.mark.parametrize("method", ["get_hours_by_employee", "get_hours_by_client", "get_firm_hours"])
def test_the_in_memory_twin_counts_the_same_entries_the_database_would(monkeypatch, method):
    import repositories.time_tracking_analytics_repository as mod
    entry = {"firm_id": "F1", "ended_at": "x", "user_id": "U1", "client_id": "C1", "duration_minutes": 60, "is_billable": True}
    rows = [{**entry, "id": "a", "started_at": APRIL_FIRST_IST}, {**entry, "id": "b", "started_at": MAY_FIRST_IST},
            {**entry, "id": "c", "started_at": MID_APRIL}]
    monkeypatch.setattr(mod, "_USE_MOCK", True)
    monkeypatch.setattr(mod, "MOCK_TIME_ENTRIES", rows, raising=False)
    out = getattr(mod.TimeTrackingAnalyticsRepository(), method)("F1", "2026-04-01", "2026-04-30")
    total = (out["total_minutes"] if "total_minutes" in out
             else sum(v["total_minutes"] for v in out.values() if isinstance(v, dict) and "total_minutes" in v))
    assert total == 120, f"April holds entries a and c (the 01:40 IST one counts, the 00:10 IST on 1 May does not): {out}"


def test_the_time_entry_list_hands_the_database_indian_midnights(monkeypatch):
    import repositories.time_tracking_repository as mod
    db = MagicMock()
    monkeypatch.setattr(mod, "_get_db", lambda: db)
    mod.TimeTrackingRepository()._filtered("F1", None, None, None, "2026-04-01", "2026-04-30")
    assert ("started_at", "2026-04-01T00:00:00+05:30") in _calls(db, "gte")
    assert ("started_at", "2026-05-01T00:00:00+05:30") in _calls(db, "lt")
    assert _calls(db, "lte") == []


def test_no_bound_is_added_for_a_range_nobody_asked_for(monkeypatch):
    import repositories.time_tracking_repository as mod
    db = MagicMock()
    monkeypatch.setattr(mod, "_get_db", lambda: db)
    mod.TimeTrackingRepository()._filtered("F1", None, None, None, None, None)
    assert _calls(db, "gte") == [] and _calls(db, "lt") == []


def test_analytics_holds_no_utc_day_boundary():
    """`routers/analytics.py` once filtered tasks completed in a period on `updated_at` in three roll-ups, each through the one
    Indian-day window. Those three routes had no screen and were deleted (POST-A-185), so the window is gone with them; what
    stays true, and is held here, is that no UTC end-of-day string was left in the module and the window is not half-used."""
    source = (API_ROOT / "routers" / "analytics.py").read_text(encoding="utf-8")
    assert "T23:59:59Z" not in source and "T00:00:00Z" not in source
    assert "ist_day_window" not in source, "a half of the Indian-day window came back; use both bounds through the one helper"


# ── the export and the ageing of a risk ──────────────────────────────────────────────────────────────────────────────
def test_the_export_dates_an_entry_by_its_indian_day():
    from services.time_export_service import build_export_rows
    rows = build_export_rows([{"started_at": APRIL_FIRST_IST, "duration_minutes": 30, "hourly_rate_paise": 100000,
                               "user_id": "U1", "client_id": "C1"}], {"U1": {"full_name": "A"}}, {"C1": {"client_name": "B"}})
    assert rows[0]["date"] == "2026-04-01"
    assert rows[0]["started_at"] == APRIL_FIRST_IST, "the stored instant itself is exported as it is"


def test_an_open_risk_is_old_after_seven_indian_days_not_seven_utc_days(monkeypatch):
    """Created at 01:40 IST on 1 April (31 March 20:10 UTC): on 8 April IST it is seven days old, on 9 April eight."""
    import domain.ai_insight_service as mod
    src = (API_ROOT / "domain" / "ai_insight_service.py").read_text(encoding="utf-8")
    assert 'str(r["created_at"])[:10]' not in src and 'ist_date_of(r["created_at"])' in src
    created = ist_clock.ist_date_of(APRIL_FIRST_IST)
    assert created == date(2026, 4, 1)
    assert (date(2026, 4, 8) - created).days == 7 and (date(2026, 4, 9) - created).days == 8
    assert mod.ist_date_of is ist_clock.ist_date_of


# ── the rule ─────────────────────────────────────────────────────────────────────────────────────────────────────────
#: Frozen: a `[:10]` slice of a value named `..._at` that is knowingly left, with the reason. It may only shrink.
LEFT_ALONE: dict[tuple[str, str], str] = {}


def _timestamptz_only_names() -> frozenset[str]:
    """Every column name production's schema snapshot types `timestamptz` in EVERY table that has it. A name that is a `date` or text
    column anywhere is left out: a slice of that is not provably a stamp, and the suffix rule below does not need it."""
    from tests.production_types import _SCHEMA
    seen: dict[str, set[str]] = {}
    for columns in _SCHEMA.values():
        for name, meta in columns.items():
            seen.setdefault(name, set()).add(str(meta.get("type")))
    return frozenset(name for name, kinds in seen.items() if kinds == {"timestamp with time zone"})


#: The names a slice is judged by: the `_at` suffix, plus every column the schema says is a timestamptz whatever it is called.
STAMP_NAMES = _timestamptz_only_names()


def _is_stamp_name(name: str) -> bool:
    return name.endswith("_at") or name in STAMP_NAMES


def _stamp_key(node: ast.AST, aliases: dict[str, str | None] | None = None) -> str | None:
    """The stamp key a value denotes, or None: `x["started_at"]`, `x.get("started_at", "")`, `str(...)` of either,
    `(... or "")`, and a bare name or attribute that names a stamp column (`..._at`, or one the schema types timestamptz)."""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id == "str" and node.args:
            return _stamp_key(node.args[0], aliases)
        if (isinstance(func, ast.Attribute) and func.attr == "get" and node.args
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                and _is_stamp_name(node.args[0].value)):
            return node.args[0].value
        return None
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
        return node.slice.value if _is_stamp_name(node.slice.value) else None
    if isinstance(node, ast.BoolOp):
        return next((k for k in (_stamp_key(v, aliases) for v in node.values) if k), None)
    if isinstance(node, ast.IfExp):
        return _stamp_key(node.body, aliases) or _stamp_key(node.orelse, aliases)
    if isinstance(node, ast.Attribute):
        return node.attr if _is_stamp_name(node.attr) else None
    if isinstance(node, ast.Name):
        if aliases is not None and node.id in aliases:
            return aliases[node.id]               # a stamp's key, or None: assigned something that is not a stamp (even if named `..._at`)
        return node.id if _is_stamp_name(node.id) else None
    return None


_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)

#: What the scan knows about the names in scope at one point: name -> the stamp key it holds, or None when it was just assigned something
#: that is not a stamp (a converted day, whatever it is called). A name that is NOT in the map is unknown, and is judged by its own spelling
#: (`..._at`, or a column the schema types timestamptz). A map is never changed in place: every binding makes a new one, because the nodes
#: already read under the old one keep it.
State = dict


def _names_bound_by(target: ast.AST):
    """Every plain name a binding target (a name, a tuple or list of them, a starred one) sets."""
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            yield from _names_bound_by(elt)
    elif isinstance(target, ast.Starred):
        yield from _names_bound_by(target.value)


def _param_names(args: ast.arguments) -> list[str]:
    return [a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg] if a is not None]


def _without(state: State, names) -> State:
    """`state` with these names unknown again: a parameter, a loop variable, an `as` name or an unpacked name could hold anything."""
    names = [n for n in names if n in state]
    return {k: v for k, v in state.items() if k not in names} if names else state


def _merge(a: State, b: State) -> State:
    """The state where two paths join (an if and its else, the end of a loop body and its start): a name is a stamp if it is one on
    EITHER path, because a cut that can be a stamp is the one to look at; it is cleared only if it is cleared on both."""
    out: State = {}
    for name in a.keys() | b.keys():
        key = a.get(name) or b.get(name)
        if key:
            out[name] = key
        elif name in a and name in b:
            out[name] = None
    return out


def _mark(root: ast.AST, state: State, out: dict) -> None:
    """Record, for every node under the expression `root`, the state it is read under. A lambda's parameters and a comprehension's targets
    shadow the names of the scope around them; the first iterable of a comprehension is read in that scope."""
    stack = [(root, state)]
    while stack:
        node, st = stack.pop()
        out[node] = st
        if isinstance(node, ast.Lambda):
            stack.extend((d, st) for d in [*node.args.defaults, *[d for d in node.args.kw_defaults if d is not None]])
            stack.append((node.body, _without(st, _param_names(node.args))))
        elif isinstance(node, _COMPREHENSIONS):
            inner = st
            for i, g in enumerate(node.generators):
                stack.append((g.iter, st if i == 0 else inner))
                inner = _without(inner, _names_bound_by(g.target))
                stack.append((g.target, inner))
                stack.extend((cond, inner) for cond in g.ifs)
            stack.extend((e, inner) for e in ([node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]))
        else:
            stack.extend((child, st) for child in ast.iter_child_nodes(node))


def _read(exprs, state: State, out: dict) -> State:
    """Mark the expressions a statement evaluates, then apply the names a `:=` inside them bound."""
    exprs = [e for e in exprs if e is not None]
    for e in exprs:
        _mark(e, state, out)
    walruses = sorted((n for e in exprs for n in ast.walk(e) if isinstance(n, ast.NamedExpr) and isinstance(n.target, ast.Name)),
                      key=lambda n: (n.lineno, n.col_offset))
    for n in walruses:
        state = {**state, n.target.id: _stamp_key(n.value, state)}
    return state


def _looped(entry: State, run) -> State:
    """Run a loop body until the state coming round to its top stops growing: a name bound late in the body is seen at the top of the next
    trip. `run(top)` marks the body under `top` and returns the state at its end; the state after the loop is zero trips or more."""
    top = entry
    for _ in range(4):
        merged = _merge(entry, run(top))
        if merged == top:
            break
        top = merged
    return top


def _flow(stmts: list[ast.stmt], state: State, out: dict, defer: dict, pin: State | None = None) -> State:
    """Read a list of statements in the order they run and return the state at their end. `defer` collects the functions defined on the
    way (node -> the state where the LAST pass over it saw it defined): their bodies are read afterwards, because a closure reads a name
    when it is called. `pin` is set inside a class body, whose own names are not visible to its methods."""
    for s in stmts:
        state = _statement(s, state, out, defer, pin)
    return state


def _statement(s: ast.stmt, state: State, out: dict, defer: dict, pin: State | None) -> State:
    if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
        _read([*s.decorator_list, *s.args.defaults, *s.args.kw_defaults, s.returns], state, out)
        defer[s] = pin if pin is not None else state
        return {**state, s.name: None}
    if isinstance(s, ast.ClassDef):
        _read([*s.decorator_list, *s.bases, *[k.value for k in s.keywords]], state, out)
        _flow(s.body, state, out, defer, pin if pin is not None else state)
        return {**state, s.name: None}
    if isinstance(s, ast.Assign):
        state = _read([s.value, *s.targets], state, out)
        key = _stamp_key(s.value, state)
        for t in s.targets:
            state = {**state, t.id: key} if isinstance(t, ast.Name) else _without(state, _names_bound_by(t))
        return state
    if isinstance(s, ast.AnnAssign):
        state = _read([s.value, s.target, s.annotation], state, out)
        if s.value is not None and isinstance(s.target, ast.Name):
            return {**state, s.target.id: _stamp_key(s.value, state)}
        return state
    if isinstance(s, ast.AugAssign):
        state = _read([s.value, s.target], state, out)
        return _without(state, _names_bound_by(s.target))
    if isinstance(s, ast.If):
        state = _read([s.test], state, out)
        return _merge(_flow(s.body, state, out, defer, pin), _flow(s.orelse, state, out, defer, pin))
    if isinstance(s, (ast.For, ast.AsyncFor)):
        state = _read([s.iter], state, out)
        bound = list(_names_bound_by(s.target))

        def trip(top: State) -> State:
            inside = _without(top, bound)
            _mark(s.target, inside, out)
            return _flow(s.body, inside, out, defer, pin)
        return _flow(s.orelse, _looped(state, trip), out, defer, pin)
    if isinstance(s, ast.While):
        def trip(top: State) -> State:
            _mark(s.test, top, out)
            return _flow(s.body, top, out, defer, pin)
        return _flow(s.orelse, _looped(state, trip), out, defer, pin)
    if isinstance(s, (ast.With, ast.AsyncWith)):
        for item in s.items:
            state = _read([item.context_expr], state, out)
            if item.optional_vars is not None:
                _mark(item.optional_vars, state, out)
                state = _without(state, _names_bound_by(item.optional_vars))
        return _flow(s.body, state, out, defer, pin)
    if isinstance(s, (ast.Try, getattr(ast, "TryStar", ast.Try))):
        body_end = _flow(s.body, state, out, defer, pin)
        into_handler = _merge(state, body_end)
        ends = [_flow(s.orelse, body_end, out, defer, pin)]
        for h in s.handlers:
            _read([h.type], into_handler, out)
            ends.append(_flow(h.body, _without(into_handler, [h.name] if h.name else []), out, defer, pin))
        joined = ends[0]
        for e in ends[1:]:
            joined = _merge(joined, e)
        return _flow(s.finalbody, _merge(joined, into_handler), out, defer, pin)
    if isinstance(s, getattr(ast, "Match", ())):
        state = _read([s.subject], state, out)
        ends = [state]
        for case in s.cases:
            ends.append(_flow(case.body, _read([case.guard], state, out), out, defer, pin))
        joined = ends[0]
        for e in ends[1:]:
            joined = _merge(joined, e)
        return joined
    # Expr, Return, Raise, Assert, Delete and the rest: they read, and bind nothing the scan follows.
    return _read([c for c in ast.iter_child_nodes(s) if isinstance(c, ast.expr)], state, out)


def _scopes_with_aliases(tree: ast.AST) -> dict[ast.AST, State]:
    """node -> the names it is read under: flow-sensitive within a scope (an `if` and its `else` join, a loop is run until its top stops
    growing), and a function starts from what its enclosing scope held where it was defined JOINED with what that scope holds at its
    end, less its own parameters, which shadow. Module-level code is a scope too. The scan never follows a stamp across a call."""
    out: dict[ast.AST, State] = {}

    def scope(body: list[ast.stmt], state: State) -> None:
        defer: dict = {}
        end = _flow(body, state, out, defer)
        for fn, at_def in defer.items():
            scope(fn.body, _without(_merge(at_def, end), _param_names(fn.args)))

    scope(tree.body if isinstance(tree, ast.Module) else [], {})
    return out


def _first_ten_characters_of_a_stamp(source: str):
    """(function, line, key) for every `<stamp>[:10]` in `source`."""
    tree = ast.parse(source)
    owner: dict[ast.AST, str] = {}
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for child in ast.walk(fn):
            owner.setdefault(child, fn.name)
    scope = _scopes_with_aliases(tree)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice) and node.slice.lower is None
                and node.slice.step is None and isinstance(node.slice.upper, ast.Constant) and node.slice.upper.value == 10):
            key = _stamp_key(node.value, scope.get(node))
            if key:
                yield owner.get(node, "<module>"), node.lineno, key


def test_no_stored_stamp_is_cut_to_its_first_ten_characters_outside_the_frozen_list():
    found, scanned = [], 0
    for path in sorted(API_ROOT.rglob("*.py")):
        rel = path.relative_to(API_ROOT)
        if rel.parts[0] in {"tests", "scripts", "venv", ".venv", "migrations"}:
            continue
        scanned += 1
        for fn, line, key in _first_ten_characters_of_a_stamp(path.read_text(encoding="utf-8")):
            found.append((rel.as_posix(), fn, line, key))
    assert scanned > 500, "the scan read too few files to mean anything"
    unlisted = [f for f in found if (f[0], f[1]) not in LEFT_ALONE]
    assert unlisted == [], (
        "a stored stamp is cut to its first ten characters, which is the UTC day: use core.ist_clock.ist_date_of / "
        f"ist_day_iso (display) or ist_day_window / in_ist_window (a range). {unlisted}")
    stale = [k for k in LEFT_ALONE if not any((f[0], f[1]) == k for f in found)]
    assert stale == [], f"a frozen entry no longer matches a slice: delete it ({stale})"


def test_the_rules_stamp_names_come_from_the_schema_and_not_only_from_a_suffix():
    """The nine timestamptz columns that are not named `..._at` are in the rule, and a name the schema types as a date is not."""
    assert {"ack_date", "ewb_date", "ewb_valid_upto"} <= STAMP_NAMES
    assert "invoice_date" not in STAMP_NAMES and "due_date" not in STAMP_NAMES, "a date column is not a stamp"
    assert len(STAMP_NAMES) > 100, "the snapshot was read: it holds well over a hundred stamp columns"


def test_negative_control_the_rule_catches_each_spelling_and_spares_a_date_column():
    bad = {
        "get with a default": "def f(e):\n    return e.get('started_at', '')[:10]\n",
        "str of a get": "def f(e):\n    return str(e.get('completed_at') or '—')[:10]\n",
        "str of a subscript": "def f(r):\n    return str(r['created_at'])[:10]\n",
        "a name": "def f(created_at):\n    return created_at[:10]\n",
        "an attribute": "def f(row):\n    return row.approved_at[:10]\n",
    }
    bad |= {
        "a timestamptz column not named _at (subscript)": "def f(r):\n    return r['ewb_valid_upto'][:10]\n",
        "a timestamptz column not named _at (get)": "def f(r):\n    return str(r.get('ack_date') or '')[:10]\n",
    }
    for why, source in bad.items():
        assert [k for _f, _l, k in _first_ten_characters_of_a_stamp(source)], why
    fine = {
        "a date column": "def f(r):\n    return r['invoice_date'][:10]\n",
        "a list cut": "def f(rows):\n    return sorted(rows, key=lambda a: a.get('created_at', ''))[:10]\n",
        "another width": "def f(e):\n    return e.get('started_at', '')[:7]\n",
        "a due date": "def f(r):\n    return str(r.get('due_date'))[:10]\n",
    }
    for why, source in fine.items():
        assert [k for _f, _l, k in _first_ten_characters_of_a_stamp(source)] == [], why


# ── POST-A-251: the other spellings of the same cut ──────────────────────────────────────────────────────────────────────
def _other_cuts_of_a_stamp(source: str):
    """(function, line, key, how) for `<stamp>.split("T")[0]` (also " "), `<stamp>.partition("T")[0]` and `<stamp>.strftime(...)`."""
    tree = ast.parse(source)
    owner: dict[ast.AST, str] = {}
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for child in ast.walk(fn):
            owner.setdefault(child, fn.name)
    scope = _scopes_with_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "strftime":
                key = _stamp_key(node.func.value, scope.get(node))
                if key:
                    yield owner.get(node, "<module>"), node.lineno, key, "strftime"
            elif (node.func.attr in {"split", "partition"} and node.args and isinstance(node.args[0], ast.Constant)
                  and node.args[0].value in {"T", " "}):
                key = _stamp_key(node.func.value, scope.get(node))
                if key:
                    yield owner.get(node, "<module>"), node.lineno, key, node.func.attr


def test_no_stamp_is_split_at_its_time_or_formatted_unconverted():
    found = []
    for path in sorted(API_ROOT.rglob("*.py")):
        rel = path.relative_to(API_ROOT)
        if rel.parts[0] in {"tests", "scripts", "venv", ".venv", "migrations"}:
            continue
        for fn, line, key, how in _other_cuts_of_a_stamp(path.read_text(encoding="utf-8")):
            found.append((rel.as_posix(), fn, line, key, how))
    assert found == [], ("a stored stamp is cut at its time or formatted without being converted to the Indian day: use "
                         f"core.ist_clock.ist_date_of / ist_day_iso. {found}")


def test_negative_control_the_other_spellings_are_caught_and_a_date_column_is_spared():
    bad = {
        "split at T": "def f(r):\n    return r['created_at'].split('T')[0]\n",
        "split at a space": "def f(r):\n    return str(r.get('updated_at')).split(' ')[0]\n",
        "partition": "def f(r):\n    return r.approved_at.partition('T')[0]\n",
        "strftime of a stamp": "def f(row):\n    return row['started_at'].strftime('%d-%m-%Y')\n",
        "strftime of a name": "def f(created_at):\n    return created_at.strftime('%Y-%m')\n",
    }
    for why, source in bad.items():
        assert list(_other_cuts_of_a_stamp(source)), why
    fine = {
        "a date column": "def f(r):\n    return r['invoice_date'].strftime('%d-%m-%Y')\n",
        "a split on something else": "def f(r):\n    return r['created_at'].split('-')[0]\n",
        "a name that is not a stamp": "def f(label):\n    return label.split('T')[0]\n",
    }
    for why, source in fine.items():
        assert list(_other_cuts_of_a_stamp(source)) == [], why


def test_three_private_copies_of_the_stamp_to_day_conversion_are_folded_onto_the_helper():
    """`gst_amendment_service._ist_date`, `report_schedule.created_on` and `ai.budget.month_for`'s own astimezone each re-did what
    `ist_date_of` does, and a copy is how a fourth reading of a naive value appears. They read through the helper now."""
    for rel, gone in (("services/gst_amendment_service.py", "_ist_date"), ("domain/reporting/report_schedule.py", "created_on")):
        tree = ast.parse((API_ROOT / rel).read_text(encoding="utf-8"))
        defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert gone not in defined, f"{rel} defines {gone} again"
        assert "ist_date_of" in (API_ROOT / rel).read_text(encoding="utf-8")
    budget = (API_ROOT / "domain/ai/budget.py").read_text(encoding="utf-8")
    assert "month_of(ist_date_of(instant))" in budget and "astimezone(IST)" not in budget.split("def month_for", 1)[1].split("def ", 1)[0]
    # the one copy that stays says why, and keeps its two differences
    kept = (API_ROOT / "domain/health/overrides.py").read_text(encoding="utf-8")
    assert "KEPT AS ITS OWN FUNCTION" in kept and "except ValueError:\n        raise" in kept


# ── POST-A-251: a stamp copied into a variable with another name ─────────────────────────────────────

def test_negative_control_a_stamp_copied_into_a_variable_is_still_a_stamp():
    bad = {
        "a get copied then cut": "def f(r):\n    updated = r.get('updated_at', '')\n    return updated[:10]\n",
        "a subscript copied then split": "def f(r):\n    ts = r['created_at']\n    return ts.split('T')[0]\n",
        "copied twice": "def f(r):\n    a = r['approved_at']\n    b = a\n    return b[:10]\n",
        "a schema timestamptz copied": "def f(r):\n    when = str(r.get('ack_date') or '')\n    return when[:10]\n",
        "formatted": "def f(r):\n    when = r['started_at']\n    return when.strftime('%d-%m-%Y')\n",
        "an annotated copy": "def f(r):\n    ts: str = r['created_at']\n    return ts[:10]\n",
        "a copy read by a closure": "def f(r):\n    ts = r['created_at']\n    def g():\n        return ts[:10]\n    return g\n",
        "a method": "class C:\n    def f(self, r):\n        ts = r['created_at']\n        return ts[:10]\n",
    }
    # The 2-11-2026 review: the first version read a function's names as they stood at its END, so each of these was missed.
    bad |= {
        "a cut and THEN a rebinding to its converted value": "def f(r):\n    ts = r['created_at']\n    label = ts[:10]\n    ts = ist_date_of(ts)\n    return label, ts\n",
        "a cut and then a rebinding to a date column": "def f(r):\n    d = r['created_at']\n    a = d[:10]\n    d = r['invoice_date']\n    return a, d\n",
        "a stamp in one branch only": "def f(r, x):\n    if x:\n        ts = r['created_at']\n    else:\n        ts = r['invoice_date']\n    return ts[:10]\n",
        "a stamp in the else branch only": "def f(r, x):\n    if x:\n        ts = r['invoice_date']\n    else:\n        ts = r['created_at']\n    return ts.split('T')[0]\n",
        "bound late in a loop and cut at the top of the next trip": "def f(rows):\n    ts = ''\n    for r in rows:\n        print(ts[:10])\n        ts = r['created_at']\n",
        "a conditional-expression copy": "def f(r):\n    ts = r['created_at'] if r else ''\n    return ts[:10]\n",
        "a walrus copy": "def f(r):\n    if (ts := r['created_at']):\n        return ts[:10]\n",
        "a chained copy": "def f(r):\n    a = b = r['created_at']\n    return b[:10]\n",
        "a copy read inside a lambda": "def f(r, rows):\n    ts = r['created_at']\n    return sorted(rows, key=lambda x: ts[:10])\n",
        "a copy read inside a comprehension": "def f(r, rows):\n    ts = r['created_at']\n    return [ts[:10] for _ in rows]\n",
        "a copy at module level read in a function": "ts = ROW['created_at']\ndef f():\n    return ts[:10]\n",
        "a function defined under an if": "if True:\n    def f(r):\n        ts = r['created_at']\n        return ts[:10]\n",
        "a function defined inside a try": "try:\n    def f(r):\n        ts = r['created_at']\n        return ts[:10]\nexcept Exception:\n    pass\n",
        "a closure defined BEFORE the copy is made": "def f(r):\n    def g():\n        return ts[:10]\n    ts = r['created_at']\n    return g\n",
        "a copy in a with block": "def f(r, lock):\n    with lock:\n        ts = r['created_at']\n    return ts[:10]\n",
        "a copy in a try block": "def f(r):\n    try:\n        ts = r['created_at']\n    except KeyError:\n        ts = None\n    return ts[:10]\n",
        "a named parameter that is a stamp": "def f(created_at):\n    return created_at[:10]\n",
    }
    for why, source in bad.items():
        assert list(_first_ten_characters_of_a_stamp(source)) or list(_other_cuts_of_a_stamp(source)), why
    fine = {
        "a date column copied": "def f(r):\n    d = r['invoice_date']\n    return d[:10]\n",
        "a name reused in another function": "def f(r):\n    ts = r['created_at']\n    return ts\ndef g(ts):\n    return ts[:10]\n",
        "an alias converted first and then formatted": "def f(r):\n    ts = r['created_at']\n    d = ist_date_of(ts)\n    return d.strftime('%d-%m-%Y')\n",
        "a name rebound to its converted value": "def f(r):\n    approved = r['approved_at']\n    approved = ist_date_of(approved)\n    return approved.strftime('%d-%m-%Y')\n",
        "a name rebound and then cut": "def f(r):\n    ts = r['created_at']\n    ts = ist_day_iso(ts)\n    return ts[:10]\n",
        "a parameter that shadows an outer alias": "def f(r):\n    ts = r['created_at']\n    def g(ts):\n        return ts[:10]\n    return g\n",
        "a name unpacked from something else": "def f(r):\n    ts = r['created_at']\n    ts, other = r['a'], r['b']\n    return ts[:10]\n",
        "a loop variable over other values": "def f(rows):\n    ts = rows[0]['created_at']\n    for ts in rows:\n        print(ts[:10])\n",
        "another width": "def f(r):\n    ts = r['created_at']\n    return ts[:7]\n",
    }
    fine |= {
        # a variable whose OWN name ends in `_at` and was assigned its converted value is the commonest spelling of a correct rebinding
        "an _at name rebound to its converted value": "def f(r):\n    approved_at = r['approved_at']\n    approved_at = ist_date_of(approved_at)\n    return approved_at.strftime('%d-%m-%Y')\n",
        "an _at name assigned a converted day and cut": "def f(r):\n    created_at = ist_day_iso(r['created_at'])\n    return created_at[:10]\n",
        "an _at parameter converted first": "def f(created_at):\n    created_at = ist_day_iso(created_at)\n    return created_at[:10]\n",
        # the cut comes BEFORE the name becomes a stamp
        "converted when it is cut and a stamp only afterwards": "def f(r, x):\n    ts = ist_date_of(x)\n    a = ts[:10]\n    ts = r['created_at']\n    return a, ts\n",
        "both branches convert": "def f(r, x):\n    if x:\n        ts = ist_date_of(r['created_at'])\n    else:\n        ts = ist_day_iso(r['updated_at'])\n    return ts[:10]\n",
        "a loop that converts before it cuts": "def f(rows):\n    for r in rows:\n        ts = r['created_at']\n        ts = ist_day_iso(ts)\n        print(ts[:10])\n",
        # names that shadow an alias without being plain assignments
        "a comprehension variable that shadows an alias": "def f(r, dates):\n    ts = r['created_at']\n    return [ts[:10] for ts in dates]\n",
        "a lambda parameter that shadows an alias": "def f(r, rows):\n    ts = r['created_at']\n    return sorted(rows, key=lambda ts: ts[:10])\n",
        "a with-as name that shadows an alias": "def f(r, path):\n    ts = r['created_at']\n    with open(path) as ts:\n        return ts[:10]\n",
        "an except-as name that shadows an alias": "def f(r):\n    ts = r['created_at']\n    try:\n        pass\n    except ValueError as ts:\n        return str(ts)[:10]\n",
        "a function name that shadows an alias": "def f(r):\n    ts = r['created_at']\n    def ts():\n        return 'x'\n    return ts()[:10]\n",
        "a closure whose parameter shadows an alias defined later": "def f(r):\n    def g(ts):\n        return ts[:10]\n    ts = r['created_at']\n    return g, ts\n",
    }
    for why, source in fine.items():
        assert not list(_first_ten_characters_of_a_stamp(source)) and not list(_other_cuts_of_a_stamp(source)), why


def test_a_record_awaiting_documents_is_at_risk_after_fourteen_indian_days_not_fourteen_utc_days(monkeypatch):
    """The cut this found: `updated[:10]` read 31 March for a change at 01:40 IST on 1 April, so on 14 April (13 Indian days later) the
    record read as 14 days old and tipped to AT RISK a day early."""
    import domain.compliance_record_service as crs
    import datetime as dt
    record = {"status": "Awaiting Documents", "due_date": "2026-09-30", "created_at": "2026-03-01T00:00:00+00:00",
              "updated_at": "2026-03-31T20:10:00+00:00"}
    monkeypatch.setattr(crs, "ist_today", lambda: dt.date(2026, 4, 14))
    assert crs._compute_risk_score(record) == 30, "13 Indian days waiting is not yet AT RISK"
    monkeypatch.setattr(crs, "ist_today", lambda: dt.date(2026, 4, 15))
    assert crs._compute_risk_score(record) == 60, "14 Indian days waiting is AT RISK"
    assert crs._compute_risk_score({**record, "updated_at": "not a stamp"}) == 30, "an unreadable stamp is skipped, not guessed"
