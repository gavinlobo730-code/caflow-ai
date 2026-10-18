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

THE RULE'S BLIND SPOTS (not a claim of coverage): a stamp sliced after being copied into a variable with another name, a
    `.split("T")[0]`, a `strftime` of an un-converted datetime, and a column that holds a stamp but is not named `..._at`.
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
LEFT_ALONE = {
    ("services/intelligence_service.py", "compute_compliance_risk"):
        "reads compliance_records.filed_at, a column that does not exist (the table has filed_date, a date), so the slice never "
        "runs; making the late-history rule live changes every client's risk score and is a decision (POST-A-261)",
}


def _stamp_key(node: ast.AST) -> str | None:
    """The `..._at` key a value denotes, or None: `x["started_at"]`, `x.get("started_at", "")`, `str(...)` of either,
    `(... or "")`, and a bare name or attribute ending `_at`."""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id == "str" and node.args:
            return _stamp_key(node.args[0])
        if (isinstance(func, ast.Attribute) and func.attr == "get" and node.args
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                and node.args[0].value.endswith("_at")):
            return node.args[0].value
        return None
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
        return node.slice.value if node.slice.value.endswith("_at") else None
    if isinstance(node, ast.BoolOp):
        return next((k for k in (_stamp_key(v) for v in node.values) if k), None)
    if isinstance(node, ast.Attribute):
        return node.attr if node.attr.endswith("_at") else None
    if isinstance(node, ast.Name):
        return node.id if node.id.endswith("_at") else None
    return None


def _first_ten_characters_of_a_stamp(source: str):
    """(function, line, key) for every `<stamp>[:10]` in `source`."""
    tree = ast.parse(source)
    owner: dict[ast.AST, str] = {}
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for child in ast.walk(fn):
            owner.setdefault(child, fn.name)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice) and node.slice.lower is None
                and node.slice.step is None and isinstance(node.slice.upper, ast.Constant) and node.slice.upper.value == 10):
            key = _stamp_key(node.value)
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


def test_negative_control_the_rule_catches_each_spelling_and_spares_a_date_column():
    bad = {
        "get with a default": "def f(e):\n    return e.get('started_at', '')[:10]\n",
        "str of a get": "def f(e):\n    return str(e.get('completed_at') or '—')[:10]\n",
        "str of a subscript": "def f(r):\n    return str(r['created_at'])[:10]\n",
        "a name": "def f(created_at):\n    return created_at[:10]\n",
        "an attribute": "def f(row):\n    return row.approved_at[:10]\n",
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
