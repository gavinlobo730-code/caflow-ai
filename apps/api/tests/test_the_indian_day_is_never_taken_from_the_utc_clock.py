"""A calendar date the server writes, posts or compares is the INDIAN day, never the UTC one (POST-A-048 and the sweep it opened).

THE DEFECT
    The container runs on UTC. Between 18:30 and 24:00 UTC, which is 00:00 to 05:30 IST the next day, `date.today()` and
    `datetime.now(timezone.utc).date()` name YESTERDAY. Twenty-two places did the second and three the first: a
    cancellation reversal was dated, and checked against the financial-year lock, a day early (on 1 April before 05:30 IST
    that is the PREVIOUS financial year, possibly a locked one); a payment that carried no date was dated a day early; the
    compensating reversal after a failed settlement likewise; the ageing report, the stock fallback date and the FX
    reporting date said yesterday; the overdue-task count that feeds the executive dashboard and the morning digest
    did not count a task on the morning after it fell due; an escalation rule that fires "in exactly N days"
    measured from yesterday; the timeline filed an event under last month on the first of the month; and the automation
    statistics compared the first ten characters of a UTC stamp with today.

WHAT IS HELD
    * (the rule) no server module takes a calendar date or month from the UTC clock, or from the server's own: not
      `date.today()`, not a bare `datetime.now()`, not `.date()` / `.strftime()` / `[:10]` of a UTC instant, whether the
      instant is written inline or held in a name in the same function. The allowlist is EMPTY and is meant to stay so;
    * (the behaviour) with the clock frozen at 20:10 UTC on 31 March, which is 01:40 IST on 1 April, the helpers and the
      reads that were wrong now say 1 April: the overdue read counts a task due on 31 March, pages past 1,000 rows, and
      a stamp is turned into its Indian day before it is compared.
"""
from __future__ import annotations

import ast
import datetime as _datetime_module
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

import core.ist_clock as ist_clock

API = Path(__file__).resolve().parents[1]
SKIP_TOP = {"tests", "migrations", "scripts", "venv", ".venv", "node_modules"}

#: Production code that may take a date from the UTC clock, with the reason. EMPTY, and meant to stay so.
ALLOWED: dict[tuple[str, int], str] = {}

#: The 20:10 UTC instant on 31 March: 01:40 IST on 1 April, so the two calendars (and the two financial years) disagree.
UTC_EVENING = "2026-03-31T20:10:00"


# ── the rule ─────────────────────────────────────────────────────────────────────────────────────────────────────────
#
# WHAT IT READS, AND WHAT IT DOES NOT. Per module, it resolves the names the module binds to the datetime pieces
# (`from datetime import date as _date`, `import datetime as dt`), so an aliased `today()` is seen. An INSTANT is a UTC
# read (`datetime.utcnow()`, `datetime.now(<anything naming utc>)` positionally or as `tz=`), a call to a function that
# returns one (derived from the code itself: a name qualifies only if EVERY definition of it returns a UTC instant), a name
# held in the SAME function whose every assignment is an instant, and anything derived from one by `.isoformat()`,
# `.replace()`, `.astimezone(utc)`, `str()` or `+`/`-`. It flags a calendar DATE or MONTH taken from an instant: `.date()`,
# `.year`/`.month`/`.day`, `.strftime()` whose format names no time of day, `[:4]`/`[:7]`/`[:10]`, `.split("T")[0]`, and an
# f-string or `format()` spec naming no time of day. A server-clock call (`date.today()`, `datetime.today()`, a bare
# `datetime.now()`) is flagged wherever it is.
#
# WHAT IT CANNOT SEE, and none of it occurs in the production tree today (a sweep for each was made on 17-10-2026):
#   * a stored stamp read out of a row (`row["created_at"][:10]`), a different defect: ledger POST-A-251;
#   * a date computed in SQL (`CURRENT_DATE`): ledger POST-A-252;
#   * an instant held in an attribute, a dict, a closure's enclosing function, a module-level constant, or a parameter;
#   * an instant that reaches a name through `now = now or datetime.now(timezone.utc)`, a conditional expression, a
#     tuple assignment or an augmented assignment (two such fallbacks exist, in `domain/payments/availability.py` and
#     `services/digest_service.py`, and are used for instant arithmetic only);
#   * a UTC zone held in a constant not named like one (`TZ = timezone.utc`), `timezone(timedelta(0))`, `time.gmtime()`;
#   * a helper reached through a two-level wrapper, and a helper NAME shared with a function that returns something else:
#     helpers are derived by name across the whole tree and a name qualifies only if EVERY definition returns a UTC
#     instant, so one new `def _now(): return ist_now()` anywhere switches `_now()[:10]` off everywhere (the test
#     `test_the_helpers_it_derives_include_the_ones_that_hid_the_defect` exists to notice that);
#   * and it reads a zone as UTC by the TEXT `utc` in its expression, so `datetime.now(utc_offset_tz).date()` is flagged.

TIME_DIRECTIVES = frozenset("HIMSfzZpcXTRrkls")
SAFE_SLICE_STOPS = {4, 7, 10}


def _names_utc(node: ast.AST) -> bool:
    text = ast.unparse(node)
    return "utc" in text.lower() or text == "UTC"


class _Imports:
    """The names a module binds to the datetime module, to `datetime.datetime` and to `datetime.date`."""

    def __init__(self, tree: ast.AST):
        self.module, self.dt_class, self.date_class = set(), set(), set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                self.module |= {a.asname or a.name for a in n.names if a.name == "datetime"}
            elif isinstance(n, ast.ImportFrom) and n.module == "datetime":
                for a in n.names:
                    if a.name == "datetime":
                        self.dt_class.add(a.asname or a.name)
                    elif a.name == "date":
                        self.date_class.add(a.asname or a.name)

    def is_dt_class(self, node: ast.AST) -> bool:
        return (isinstance(node, ast.Name) and node.id in self.dt_class) or (
            isinstance(node, ast.Attribute) and node.attr == "datetime"
            and isinstance(node.value, ast.Name) and node.value.id in self.module)

    def is_date_class(self, node: ast.AST) -> bool:
        return (isinstance(node, ast.Name) and node.id in self.date_class) or (
            isinstance(node, ast.Attribute) and node.attr == "date"
            and isinstance(node.value, ast.Name) and node.value.id in self.module)


def _is_instant(node: ast.AST, imp: _Imports, helpers: frozenset, held: frozenset) -> bool:
    """A UTC instant (a datetime or its ISO string), written inline, returned by a helper, held in a name, or derived."""
    def go(n: ast.AST) -> bool:
        return _is_instant(n, imp, helpers, held)

    if isinstance(node, ast.Name):
        return node.id in held
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
        return go(node.left) or go(node.right)
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    if isinstance(f, ast.Attribute):
        if imp.is_dt_class(f.value):
            if f.attr == "utcnow":
                return True
            if f.attr == "now":
                tz = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "tz"), None)
                return tz is not None and _names_utc(tz)
        if f.attr in {"isoformat", "replace"}:
            return go(f.value)
        if f.attr == "astimezone":
            return go(f.value) and bool(node.args) and _names_utc(node.args[0])
        if f.attr in helpers:
            return True
    if isinstance(f, ast.Name):
        if f.id in helpers:
            return True
        if f.id == "str" and node.args:
            return go(node.args[0])
    return False


def _held_names(fn: ast.AST, imp: _Imports, helpers: frozenset) -> frozenset:
    """Names in THIS function (not nested ones) whose every assignment is an instant."""
    assigns: dict[str, list[ast.AST]] = {}
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    assigns.setdefault(t.id, []).append(n.value)
                else:
                    for x in ast.walk(t):
                        if isinstance(x, ast.Name):
                            assigns.setdefault(x.id, []).append(ast.Constant(None))
        elif isinstance(n, (ast.AnnAssign, ast.AugAssign)) and isinstance(n.target, ast.Name) and n.value is not None:
            assigns.setdefault(n.target.id, []).append(n.value)
        elif isinstance(n, ast.NamedExpr) and isinstance(n.target, ast.Name):
            assigns.setdefault(n.target.id, []).append(n.value)
        elif isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)):
            for x in ast.walk(n.target):
                if isinstance(x, ast.Name):
                    assigns.setdefault(x.id, []).append(ast.Constant(None))
        stack.extend(ast.iter_child_nodes(n))
    held: frozenset = frozenset()
    for _ in range(4):
        grown = frozenset(name for name, values in assigns.items()
                          if all(_is_instant(v, imp, helpers, held) for v in values))
        if grown == held:
            break
        held = grown
    return held


def _date_only(fmt: ast.AST | None) -> bool:
    """A format that names no time of day (or one we cannot read): it extracts a calendar date or month."""
    if isinstance(fmt, ast.Constant) and isinstance(fmt.value, str):
        return not any(d in TIME_DIRECTIVES for d in re.findall(r"%[-#_^0]?([A-Za-z])", fmt.value))
    return True


def _scopes(tree: ast.AST):
    """The module body and every function, each with ITS OWN nodes (a nested function is its own scope)."""
    yield tree, [n for n in ast.iter_child_nodes(tree) if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
        yield fn, list(ast.iter_child_nodes(fn))


def _naive_clock_calls(src: str, helpers: frozenset = frozenset()) -> list[tuple[int, str]]:
    """(line, why) for every place a calendar date or month is read off the server's or the UTC clock."""
    tree = ast.parse(src)
    imp = _Imports(tree)
    found: set[tuple[int, str]] = set()
    for scope, roots in _scopes(tree):
        held = _held_names(scope, imp, helpers)

        def inst(n: ast.AST, held: frozenset = held) -> bool:
            return _is_instant(n, imp, helpers, held)

        stack = list(roots)
        while stack:
            n = stack.pop()
            if n is not scope and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            stack.extend(ast.iter_child_nodes(n))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                f = n.func
                if f.attr == "today" and (imp.is_date_class(f.value) or imp.is_dt_class(f.value)):
                    found.add((n.lineno, "today() is the server's day"))
                elif f.attr == "now" and not n.args and not n.keywords and imp.is_dt_class(f.value):
                    found.add((n.lineno, "a bare datetime.now() is the server's clock"))
                elif f.attr in {"date", "isocalendar", "weekday"} and inst(f.value):
                    found.add((n.lineno, f".{f.attr}() of a UTC instant is the UTC day"))
                elif f.attr == "strftime" and inst(f.value) and _date_only(n.args[0] if n.args else None):
                    found.add((n.lineno, ".strftime() of a UTC instant names the UTC day or month"))
            elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "format" \
                    and len(n.args) == 2 and inst(n.args[0]) and _date_only(n.args[1]):
                found.add((n.lineno, "format() of a UTC instant names the UTC day or month"))
            elif isinstance(n, ast.Attribute) and n.attr in {"year", "month", "day"} and inst(n.value):
                found.add((n.lineno, f".{n.attr} of a UTC instant is the UTC {n.attr}"))
            elif isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Slice) and inst(n.value) \
                    and isinstance(n.slice.upper, ast.Constant) and n.slice.upper.value in SAFE_SLICE_STOPS:
                found.add((n.lineno, "a slice of a UTC instant's text is the UTC day or month"))
            elif isinstance(n, ast.Subscript) and isinstance(n.value, ast.Call) \
                    and isinstance(n.value.func, ast.Attribute) and n.value.func.attr == "split" \
                    and inst(n.value.func.value) and isinstance(n.slice, ast.Constant) and n.slice.value == 0:
                found.add((n.lineno, ".split(...)[0] of a UTC instant's text is the UTC day"))
            elif isinstance(n, ast.FormattedValue) and inst(n.value) and n.format_spec is not None:
                spec = ast.Constant("".join(p.value for p in n.format_spec.values if isinstance(p, ast.Constant)))
                if "%" in spec.value and _date_only(spec):
                    found.add((n.lineno, "an f-string spec on a UTC instant names the UTC day or month"))
    return sorted(found)


def _production_files():
    for path in sorted(API.rglob("*.py")):
        rel = path.relative_to(API)
        if rel.parts[0] in SKIP_TOP:
            continue
        yield rel.as_posix(), path.read_text(encoding="utf-8")


def _utc_helpers(files) -> frozenset:
    """Names of functions, in any production module, whose every definition RETURNS a UTC instant: `_now`, `now_iso`.
    A name qualifies only if all of its definitions do, so a `_now` that returns the Indian clock elsewhere disqualifies it."""
    verdicts: dict[str, list[bool]] = {}
    for _rel, src in files:
        tree = ast.parse(src)
        imp = _Imports(tree)
        for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            returns = [n.value for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None]
            if returns:
                held = _held_names(fn, imp, frozenset())
                verdicts.setdefault(fn.name, []).append(
                    all(_is_instant(r, imp, frozenset(), held) for r in returns))
    return frozenset(name for name, flags in verdicts.items() if flags and all(flags))


def test_no_server_module_takes_a_date_or_month_from_the_utc_clock():
    files = list(_production_files())
    helpers = _utc_helpers(files)
    offenders = []
    for rel, src in files:
        for line, why in _naive_clock_calls(src, helpers):
            if (rel, line) not in ALLOWED:
                offenders.append(f"{rel}:{line}  {why}")
    assert len(files) > 700, f"the scan read only {len(files)} modules"
    assert not offenders, (
        "These take a calendar date or month from the server's or the UTC clock. Between 18:30 and 24:00 UTC that is "
        "yesterday in India (and on 1 April, the previous financial year). Use core.ist_clock.ist_today() / ist_now(), or "
        "ist_date_of(stamp) for a stored instant:\n  " + "\n  ".join(offenders))


def test_the_scan_covers_the_places_that_once_held_the_defect():
    scanned = {rel for rel, _ in _production_files()}
    for rel in ("services/phase2_journal_service.py", "routers/sales_invoices.py", "routers/purchase_bills.py",
                "routers/purchase_payments.py", "services/receipt_service.py", "repositories/task_repository.py",
                "services/opening_balance_service.py", "services/trial_balance_import_service.py",
                "services/bank_posting_service.py", "services/timeline_service.py"):
        assert rel in scanned, f"{rel} is no longer scanned"


def test_the_helpers_it_derives_include_the_ones_that_hid_the_defect():
    helpers = _utc_helpers(list(_production_files()))
    assert {"_now", "now_iso"} <= helpers, sorted(helpers)[:20]


def test_the_allowlist_is_empty():
    assert ALLOWED == {}, "an exception to the Indian-day rule needs a decision, and a reason written here"


#: (source, flagged). `H` below stands for a module that defines `def _now(): return datetime.now(timezone.utc).isoformat()`.
_HEADER = "from datetime import datetime, timezone, timedelta, date\n"
CASES = [
    # the three server-clock calls, and their aliases
    (_HEADER + "x = date.today()\n", True),
    ("import datetime\nx = datetime.date.today()\n", True),
    ("from datetime import date as _date\nx = _date.today()\n", True),
    ("import datetime as dt\nx = dt.date.today()\n", True),
    (_HEADER + "x = datetime.today()\n", True),
    (_HEADER + "x = datetime.now()\n", True),
    # a calendar date or month taken from a UTC instant, whatever the spelling
    (_HEADER + "x = datetime.now(timezone.utc).date()\n", True),
    (_HEADER + "x = datetime.now(tz=timezone.utc).date()\n", True),
    ("import datetime as dt\nx = dt.datetime.now(dt.timezone.utc).date()\n", True),
    (_HEADER + "x = datetime.utcnow().date()\n", True),
    (_HEADER + "x = (datetime.now(timezone.utc) - timedelta(days=1)).date()\n", True),
    (_HEADER + "x = datetime.now(timezone.utc).replace(hour=0).date()\n", True),
    (_HEADER + "x = datetime.now(timezone.utc).year\n", True),
    (_HEADER + "x = datetime.now(timezone.utc).month\n", True),
    (_HEADER + "x = datetime.now(timezone.utc).strftime('%Y-%m')\n", True),
    (_HEADER + "x = datetime.now(timezone.utc).strftime(fmt)\n", True),
    (_HEADER + "x = datetime.utcnow().isoformat()[:10]\n", True),
    (_HEADER + "x = str(datetime.now(timezone.utc))[:10]\n", True),
    (_HEADER + "x = datetime.now(timezone.utc).isoformat().split('T')[0]\n", True),
    (_HEADER + "now = datetime.now(timezone.utc)\nx = f'{now:%Y-%m-%d}'\n", True),
    (_HEADER + "x = format(datetime.now(timezone.utc), '%Y-%m')\n", True),
    # held in a name, in the same function, in any binding form
    (_HEADER + "def f():\n    now = datetime.now(timezone.utc)\n    return now.date()\n", True),
    (_HEADER + "def f():\n    now: datetime = datetime.now(timezone.utc)\n    return now.date()\n", True),
    (_HEADER + "def f():\n    if (now := datetime.now(timezone.utc)):\n        return now.month\n", True),
    (_HEADER + "def f():\n    now = datetime.now(timezone.utc).isoformat()\n    return now[:10]\n", True),
    (_HEADER + "async def f():\n    now = datetime.now(timezone.utc)\n    return now.strftime('%Y-%m-%d')\n", True),
    (_HEADER + "now = datetime.now(timezone.utc)\ndef f():\n    return now.date()\n", False),     # not this function's name
    (_HEADER + "now = datetime.now(timezone.utc)\nx = now.date()\n", True),                         # module level
    # a helper that returns a UTC instant
    ("def f(helpers_are_given):\n    return _now()[:10]\n", True),
    ("def f(repo):\n    return repo.now_iso()[:10]\n", True),
    # what the rule must NOT flag: an INSTANT is fine, and so is the Indian clock
    (_HEADER + "x = datetime.now(timezone.utc).isoformat()\n", False),
    (_HEADER + "x = datetime.now(timezone.utc)\n", False),
    (_HEADER + "x = datetime.now(timezone.utc) + timedelta(hours=1)\n", False),
    (_HEADER + "x = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')\n", False),        # a time of day is named
    (_HEADER + "x = datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')\n", False),
    (_HEADER + "x = datetime.now(timezone.utc).timestamp()\n", False),
    ("from core.ist_clock import ist_today\nx = ist_today().isoformat()\n", False),
    ("from core.ist_clock import ist_now\nx = ist_now().strftime('%Y-%m')\n", False),
    ("from core.ist_clock import ist_now\nx = ist_now().year\n", False),
    (_HEADER + "def f(row):\n    return row['created_at'][:10]\n", False),                         # a stored stamp: another defect
    # a name that is an instant in one function does not poison an Indian-clock name in another
    (_HEADER + "from core.ist_clock import ist_now\ndef a():\n    now = datetime.now(timezone.utc)\n    return now\n"
               "def b():\n    now = ist_now()\n    return now.date()\n", False),
    # a name reassigned to something else is no longer held
    (_HEADER + "from core.ist_clock import ist_now\ndef f():\n    now = datetime.now(timezone.utc)\n    now = ist_now()\n    return now.date()\n", False),
]


@pytest.mark.parametrize("source,flagged", CASES)
def test_negative_control_the_rule_flags_every_spelling_and_only_those(source, flagged):
    helpers = frozenset({"_now", "now_iso"})
    assert bool(_naive_clock_calls(source, helpers)) is flagged, source


def test_the_helper_derivation_needs_every_definition_to_return_a_utc_instant():
    utc = ("from datetime import datetime, timezone\n"
           "def _now():\n    return datetime.now(timezone.utc).isoformat()\n"
           "def _shared():\n    return datetime.now(timezone.utc)\n")
    ist = ("from core.ist_clock import ist_now\n"
           "def _shared():\n    return ist_now()\n")
    helpers = _utc_helpers([("a.py", utc), ("b.py", ist)])
    assert "_now" in helpers and "_shared" not in helpers
    assert _utc_helpers([("a.py", utc)]) >= {"_now", "_shared"}


# ── the behaviour, with the clock frozen where the two calendars disagree ────────────────────────────────────────────

def _freeze(monkeypatch, utc_iso: str = UTC_EVENING) -> None:
    fixed = datetime.fromisoformat(utc_iso).replace(tzinfo=timezone.utc)

    class _Frozen(_datetime_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz is not None else fixed

    monkeypatch.setattr(ist_clock, "datetime", _Frozen)


def test_the_frozen_instant_really_is_two_different_days(monkeypatch):
    _freeze(monkeypatch)
    assert ist_clock.ist_today() == date(2026, 4, 1)
    assert datetime.fromisoformat(UTC_EVENING).date() == date(2026, 3, 31)


@pytest.mark.parametrize("stamp,expected", [
    ("2026-03-31T20:10:00+00:00", date(2026, 4, 1)),
    ("2026-03-31T20:10:00Z", date(2026, 4, 1)),
    ("2026-03-31T20:10:00", date(2026, 4, 1)),                      # naive is read as UTC, which is what the database stores
    ("2026-03-31T20:10:00.123456+00:00", date(2026, 4, 1)),
    ("2026-04-01T01:40:00+05:30", date(2026, 4, 1)),
    ("2026-03-31T10:00:00+00:00", date(2026, 3, 31)),
    (datetime(2026, 3, 31, 20, 10, tzinfo=timezone.utc), date(2026, 4, 1)),
    (date(2026, 3, 31), date(2026, 3, 31)),
    (None, None), ("", None), ("not a stamp", None), (12, None),
])
def test_a_stored_instant_is_turned_into_its_indian_day(stamp, expected):
    assert ist_clock.ist_date_of(stamp) == expected


def test_the_helpers_that_name_today_say_the_indian_day(monkeypatch):
    _freeze(monkeypatch)
    from domain import inventory_service
    from services import ageing_schedule_service, fx_reporting_service

    assert inventory_service._today() == "2026-04-01"
    assert fx_reporting_service._today() == "2026-04-01"
    assert ageing_schedule_service._today() == date(2026, 4, 1)


def test_a_task_that_fell_due_on_the_day_before_is_overdue_on_the_indian_morning(monkeypatch):
    """Mock-mode branch of find_overdue: 01:40 IST on 1 April, a task due 31 March is overdue; one due today is not."""
    _freeze(monkeypatch)
    import repositories.task_repository as tasks

    rows = [
        {"id": "t1", "firm_id": "f1", "due_date": "2026-03-31", "status": "pending"},
        {"id": "t2", "firm_id": "f1", "due_date": "2026-04-01", "status": "pending"},
        {"id": "t3", "firm_id": "f1", "due_date": "2026-03-30", "status": "completed"},
    ]
    monkeypatch.setattr(tasks, "_USE_MOCK", True)
    monkeypatch.setattr(tasks, "MOCK_TASKS", rows, raising=False)
    assert [t["id"] for t in tasks.TaskRepository().find_overdue(firm_id="f1")] == ["t1"]


class _CappedTasks:
    """Just enough of a PostgREST builder over in-memory rows, with the response cap PostgREST applies and reports nothing of."""
    CAP = 1000

    def __init__(self, rows):
        self._rows, self._filters, self._order, self._limit, self.executes = rows, [], None, None, 0

    def table(self, name):
        assert name == "tasks"
        return _CappedTasks(self._rows).bind(self)

    def bind(self, parent):
        self._parent = parent
        return self

    def select(self, *_a, **_k):
        return self

    def lt(self, col, val):
        self._filters.append(lambda r: r[col] < val)
        return self

    def gt(self, col, val):
        self._filters.append(lambda r: r[col] > val)
        return self

    def eq(self, col, val):
        self._filters.append(lambda r: r.get(col) == val)
        return self

    def neq(self, col, val):
        self._filters.append(lambda r: r.get(col) != val)
        return self

    def is_(self, col, val):
        self._filters.append(lambda r: (r.get(col) is None) == (val in (None, "null")))
        return self

    def order(self, col, **_k):
        self._order = col
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        class _R:
            pass

        out = _R()
        rows = [r for r in self._rows if all(f(r) for f in self._filters)]
        if self._order:
            rows.sort(key=lambda r: r[self._order])
        out.data = rows[: min(self._limit or self.CAP, self.CAP)]
        getattr(self, "_parent", self).executes += 1
        return out


def test_the_overdue_read_pages_past_the_thousand_row_cap_and_uses_the_indian_day(monkeypatch):
    _freeze(monkeypatch)
    import repositories.task_repository as tasks

    rows = [{"id": f"{i:05d}", "firm_id": "f1", "due_date": "2026-03-31", "status": "pending", "deleted_at": None}
            for i in range(2500)]
    rows += [{"id": "z-today", "firm_id": "f1", "due_date": "2026-04-01", "status": "pending", "deleted_at": None},
             {"id": "z-other", "firm_id": "f2", "due_date": "2026-03-31", "status": "pending", "deleted_at": None},
             {"id": "z-done", "firm_id": "f1", "due_date": "2026-03-30", "status": "completed", "deleted_at": None},
             {"id": "z-deleted", "firm_id": "f1", "due_date": "2026-03-30", "status": "pending",
              "deleted_at": "2026-03-31T00:00:00+00:00"}]
    double = _CappedTasks(rows)
    monkeypatch.setattr(tasks, "_USE_MOCK", False)
    monkeypatch.setattr(tasks, "_get_db", lambda: double)

    got = tasks.TaskRepository().find_overdue(firm_id="f1")

    assert len(got) == 2500, "the read stopped at the cap"
    assert double.executes >= 3, "it should have asked for page after page"
    assert {t["id"] for t in got}.isdisjoint({"z-today", "z-other", "z-done", "z-deleted"}), (
        "due today, another firm's, completed and soft-deleted tasks are not overdue tasks of this firm")


def test_automation_statistics_count_the_executions_of_the_indian_day(monkeypatch):
    _freeze(monkeypatch)
    from repositories.automation_repository import AutomationRepository

    repo = AutomationRepository()
    monkeypatch.setattr(repo, "get_rules", lambda firm_id=None: [{"is_enabled": True}])
    monkeypatch.setattr(repo, "get_executions", lambda firm_id=None, limit=1000: [
        {"executed_at": "2026-03-31T19:00:00+00:00", "status": "success"},      # 00:30 IST on 1 April: today
        {"executed_at": "2026-03-31T10:00:00+00:00", "status": "success"},      # 15:30 IST on 31 March: yesterday
        {"executed_at": None, "status": "success"},
    ])
    assert repo.get_stats(firm_id="f1")["executions_today"] == 1


def test_the_timeline_files_an_event_under_the_indian_month(monkeypatch):
    """01:40 IST on 1 April: the UTC clock still reads March."""
    _freeze(monkeypatch)
    import services.timeline_service as timeline

    monkeypatch.setattr(timeline, "_USE_MOCK", True)
    timeline.MOCK_TIMELINE_EVENTS.clear()
    timeline.TimelineService().log_timeline_event(
        client_id="c1", firm_id="f1", financial_year="2026-27", category="work", event_type="x", title="t")
    assert timeline.MOCK_TIMELINE_EVENTS[-1]["period"] == "2026-04"
    assert timeline.MOCK_TIMELINE_EVENTS[-1]["created_at"].endswith("+00:00"), "the stored instant stays UTC"


def test_an_escalation_rule_measures_days_from_the_indian_day(monkeypatch):
    _freeze(monkeypatch)
    import repositories.escalation_rule_repository as esc

    monkeypatch.setattr(esc, "_USE_MOCK", False)
    repo = esc.EscalationRuleRepository()
    monkeypatch.setattr(repo, "find_active_by_firm", lambda firm_id: [
        {"rule_type": "due_soon", "days_threshold": 2, "id": "r2"},
        {"rule_type": "due_soon", "days_threshold": 3, "id": "r3"},
    ])
    task = {"due_date": "2026-04-03", "status": "pending", "id": "t"}
    hits = repo.get_applicable_escalations("f1", task)
    assert [r["id"] for r in hits] == ["r2"], "due 3 April is 2 days from 1 April (IST), not 3 days from 31 March"


def test_a_stamp_at_the_edge_of_the_calendar_has_no_indian_day_and_a_date_passes_through():
    assert ist_clock.ist_date_of("9999-12-31T23:00:00+00:00") is None
    assert ist_clock.ist_date_of(date(2026, 3, 31)) == date(2026, 3, 31)


def test_the_scheduler_and_the_recurring_task_check_use_the_same_conversion():
    from jobs.claims import ist_date_of as claims_day

    assert claims_day("2026-03-31T20:10:00Z", date(2000, 1, 1)) == date(2026, 4, 1)
    assert claims_day("not a stamp", date(2000, 1, 1)) == date(2000, 1, 1)
    assert claims_day(None, date(2000, 1, 1)) == date(2000, 1, 1)


class _NoDatabase:
    def table(self, _name):
        raise RuntimeError("no database in this test")


@pytest.mark.parametrize("utc,expected", [
    ("2027-03-31T20:10:00", "2027-04-01"),        # 01:40 IST on 1 April 2027: the new financial year
    ("2027-03-31T10:00:00", "2026-04-01"),        # 15:30 IST on 31 March: still the old one
    ("2027-04-01T02:00:00", "2027-04-01"),
])
def test_an_opening_entry_with_no_date_lands_in_the_indian_financial_year(monkeypatch, utc, expected):
    """Both services fall back to 1 April of the current year when the client carries no financial_year_start (nothing
    writes that column today). On 1 April before 05:30 IST the UTC clock still read March, and the opening position would
    be posted into the year that had just closed."""
    _freeze(monkeypatch, utc)
    import services.opening_balance_service as opening
    import services.trial_balance_import_service as trial_balance

    assert trial_balance._default_opening_date(_NoDatabase(), "c1") == expected
    assert opening._default_opening_date(_NoDatabase(), "f1", "c1", [], [], []) == expected


def test_a_proposal_or_engagement_numbered_after_midnight_in_india_carries_the_new_year(monkeypatch):
    _freeze(monkeypatch, "2026-12-31T20:10:00")           # 01:40 IST on 1 January 2027
    import routers.engagement_letters as letters
    import routers.lifecycle as lifecycle

    assert letters._next_engagement_no(None, "f1").startswith("EL-2027-")
    assert lifecycle._next_proposal_no(None, "f1").startswith("PROP-2027-")


def test_an_allocation_made_after_midnight_in_india_is_a_july_allocation(monkeypatch):
    """Table 11 is measured against the Indian month; an allocation stamped 19:00 UTC on 30 June was made at 00:30 IST on
    1 July. Before, its UTC day put the same advance in neither June's 11A nor July's 11B."""
    import services.gst_advance_service as advance

    class _Rows:
        def __init__(self, data):
            self.data = data

    class _Table:
        def __init__(self, rows):
            self._rows = rows

        def select(self, *_a, **_k):
            return self

        def in_(self, *_a, **_k):
            return self

        def execute(self):
            return _Rows(self._rows)

    class _Db:
        def table(self, name):
            assert name == "receipt_allocations"
            return _Table([{"receipt_id": "r1", "allocated_paise": 100, "created_at": "2027-06-30T19:00:00+00:00"},
                           {"receipt_id": "r1", "allocated_paise": 50, "created_at": "2027-07-01T10:00:00+00:00"},
                           {"receipt_id": "r1", "allocated_paise": 7, "created_at": None}])

    got = advance._allocations_by_receipt(_Db(), ["r1"])["r1"]
    assert got == [(100, "2027-07-01"), (50, "2027-07-01"), (7, "9999-12-31")]


def test_the_in_memory_automation_statistic_counts_the_executions_of_the_indian_day(monkeypatch):
    _freeze(monkeypatch)
    import domain.automation_engine as engine

    monkeypatch.setattr(engine, "MOCK_AUTOMATION_EXECUTIONS", [
        {"executed_at": "2026-03-31T19:00:00", "status": "success"},            # naive UTC, 00:30 IST on 1 April: today
        {"executed_at": "2026-03-31T10:00:00", "status": "success"},            # 15:30 IST on 31 March: yesterday
    ])
    assert engine.get_automation_stats()["executions_today"] == 1


class _MemoryRepoDouble:
    def __init__(self):
        self.triggers = []

    def get_current_profile(self, firm_id, client_id):
        return None

    def get_recent_triggers(self, firm_id, client_id, trigger_type, days=7):
        return []

    def create_trigger(self, **kw):
        self.triggers.append(kw)
        return kw


class _RecordsDouble:
    def __init__(self, rows):
        self.rows = rows

    def find_all(self, firm_id=None, **_):
        return list(self.rows)


def test_the_deadline_at_risk_detector_counts_days_from_the_indian_day_and_reads_a_date(monkeypatch):
    """`compliance_records.due_date` is a DATE ('2026-04-03'). The detector parsed it to a naive datetime and subtracted
    it from an aware clock, which raises TypeError, and the `except` beside it swallowed that: it had never produced a
    trigger. At 01:40 IST on 1 April a deadline on 3 April is two days away (the UTC date, 31 March, would say three)."""
    _freeze(monkeypatch)
    import domain.memory_pipeline as mp

    memory = _MemoryRepoDouble()
    monkeypatch.setattr(mp, "_get_memory_repo", lambda: memory)
    monkeypatch.setattr(mp, "_get_compliance_records_repo", lambda: _RecordsDouble([
        {"client_id": "c1", "status": "Not Started", "due_date": "2026-04-03", "compliance_type": "GST"},
        {"client_id": "c1", "status": "Filed", "due_date": "2026-04-03", "compliance_type": "TDS"},          # filed: not at risk
        {"client_id": "c1", "status": "Not Started", "due_date": "2026-03-31", "compliance_type": "MCA"},    # already past
        {"client_id": "c1", "status": "Not Started", "due_date": "2026-06-30", "compliance_type": "Payroll"},  # far away
        {"client_id": "c2", "status": "Not Started", "due_date": "2026-04-03", "compliance_type": "GST"},     # another client
    ]))
    triggers = mp.MemoryPipeline().detect_deadline_at_risk("f1", "c1")
    assert [t["title"] for t in triggers] == ["Deadline At Risk: GST due in 2 days"]


def test_task_volume_is_bucketed_by_the_indian_month(monkeypatch):
    """Eight tasks created at 19:00 UTC on 31 March are April tasks in India. Bucketed by the UTC month they sat in March
    and April showed none, so a real spike was read as an ordinary month."""
    _freeze(monkeypatch)
    import domain.memory_pipeline as mp

    created = [f"{m}-15T10:00:00+00:00" for m in ("2025-11", "2025-12", "2026-01", "2026-02", "2026-03")]
    created += ["2026-03-31T19:00:00+00:00"] * 8
    anomalies = []

    class _Memory(_MemoryRepoDouble):
        def create_anomaly(self, **kw):
            anomalies.append(kw)
            return kw

    class _Tasks:
        def find_all(self, firm_id=None, client_id=None, **_):
            return [{"created_at": stamp} for stamp in created]

    monkeypatch.setattr(mp, "_get_memory_repo", lambda: _Memory())
    monkeypatch.setattr(mp, "_get_task_repo", lambda: _Tasks())
    found = mp.MemoryPipeline().detect_pattern_anomalies("f1", "c1")
    assert [a["period"] for a in found] == ["2026-04"]
    assert anomalies[0]["actual"] == 8.0 and anomalies[0]["anomaly_type"] == "activity_spike"
