"""An hour of recorded time is priced by one rule wherever it is shown (POST-A-169, docs/REVENUE_OPS_BRIDGE.md B1-1).

WHAT WAS WRONG
    `time_entries` carries two rate columns: the legacy `hourly_rate_paise` (migration 064) and `billable_rate_paise` (073), which
    migration 451 made the place an hour is priced when it is recorded. The bridge register said every reader must prefer the second.
    The Time screen and the unbilled-work total did; `domain/billing/time_rate.entry_rate` said so once; and three more places restated
    the order or ignored it. The TIME EXPORT read `hourly_rate_paise` alone (`or 0`), so every hour priced since 451 left in the CSV
    and Excel file at a rate of 0 and an amount of 0, and an hour nobody priced read as worth nothing. `billing_service.unbilled_value_paise`
    restated the order with no caller outside a test, and the Time router restated it again.

WHAT IS HELD
    * The export's rate and amount are `time_rate.entry_worth`'s, which is what the Time screen shows: an hour priced in either column
      is priced; one with no rate, a non-billable hour and a running entry leave the cells EMPTY, never 0.
    * No production module reads `hourly_rate_paise` off a row except `domain/billing/time_rate.py`. The one named exception is the
      legacy `POST /api/invoices/from-time`, which no screen calls and whose replacement is POST-B-194's decision.
    * The restatement that had no caller is gone.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from domain.billing import time_rate
from routers import time_tracking
from services.time_export_service import build_export_rows

API = Path(__file__).resolve().parents[1]

#: Modules allowed to read the legacy column off a row, each with why.
READS_THE_LEGACY_COLUMN = {
    "domain/billing/time_rate.py": "the rule itself: billable_rate_paise first, hourly_rate_paise second",
    "services/invoice_generation_service.py": "the legacy POST /api/invoices/from-time, no screen caller; POST-B-194 replaces or retires it",
}

_BASE = {"user_id": "u1", "client_id": "c1", "started_at": "2026-06-01T09:00:00Z", "ended_at": "2026-06-01T11:00:00Z",
         "duration_minutes": 120, "is_billable": True}


def _row(**entry) -> dict:
    return build_export_rows([{**_BASE, **entry}], {}, {})[0]


def test_an_hour_priced_when_it_was_recorded_leaves_in_the_export_at_its_price():
    """The shape every entry has had since migration 451: the rate is in billable_rate_paise and the legacy column is empty."""
    row = _row(billable_rate_paise=150_000, hourly_rate_paise=None)
    assert row["hourly_rate_paise"] == 150_000
    assert row["amount_paise"] == 300_000 and row["amount_inr"] == "3,000.00"


def test_the_rate_recorded_on_the_entry_outranks_the_legacy_one_in_the_export():
    row = _row(billable_rate_paise=200_000, hourly_rate_paise=100_000)
    assert (row["hourly_rate_paise"], row["amount_paise"]) == (200_000, 400_000)
    legacy_only = _row(hourly_rate_paise=120_000)
    assert (legacy_only["hourly_rate_paise"], legacy_only["amount_paise"]) == (120_000, 240_000)


def test_a_stated_rate_of_nothing_is_a_rate():
    row = _row(billable_rate_paise=0, hourly_rate_paise=120_000)
    assert (row["hourly_rate_paise"], row["amount_paise"], row["amount_inr"]) == (0, 0, "0.00")


@pytest.mark.parametrize("entry", [
    {"billable_rate_paise": None, "hourly_rate_paise": None},                       # nobody said what it is worth
    {"billable_rate_paise": 150_000, "is_billable": False},                          # not billable
    {"billable_rate_paise": 150_000, "ended_at": None},                              # still running
], ids=["no-rate", "non-billable", "running"])
def test_an_hour_with_no_worth_leaves_the_amount_empty_and_never_zero(entry):
    row = _row(**entry)
    assert row["amount_paise"] == "" and row["amount_inr"] == ""


def test_the_export_and_the_time_screen_say_the_same_thing_about_every_entry():
    entries = [
        {**_BASE, "billable_rate_paise": 150_000},
        {**_BASE, "hourly_rate_paise": 90_000},
        {**_BASE, "billable_rate_paise": None, "hourly_rate_paise": None},
        {**_BASE, "billable_rate_paise": 150_000, "is_billable": False},
        {**_BASE, "billable_rate_paise": 150_000, "ended_at": None},
        {**_BASE, "billable_rate_paise": 0},
    ]
    rows = build_export_rows(entries, {}, {})
    for entry, row in zip(entries, rows, strict=True):
        worth = time_tracking._worth(entry)
        assert row["hourly_rate_paise"] == ("" if worth["rate_paise"] is None else worth["rate_paise"]), entry
        assert row["amount_paise"] == ("" if worth["value_paise"] is None else worth["value_paise"]), entry


def _legacy_reads(source: str) -> list[int]:
    lines = []
    for n in ast.walk(ast.parse(source)):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" and n.args
                and isinstance(n.args[0], ast.Constant) and n.args[0].value == "hourly_rate_paise"):
            lines.append(n.lineno)
        elif (isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Load) and isinstance(n.slice, ast.Constant)
              and n.slice.value == "hourly_rate_paise"):
            lines.append(n.lineno)
    return lines


def test_no_module_reads_the_legacy_rate_off_a_row_but_the_rule():
    found = {}
    for folder in ("routers", "services", "domain", "repositories", "jobs", "core", "models"):
        for path in sorted((API / folder).rglob("*.py")):
            rel = path.relative_to(API).as_posix()
            lines = _legacy_reads(path.read_text(encoding="utf-8"))
            if lines:
                found[rel] = lines
    stray = {rel: lines for rel, lines in found.items() if rel not in READS_THE_LEGACY_COLUMN}
    assert not stray, (
        "these read time_entries.hourly_rate_paise off a row themselves; read an entry's rate through "
        f"domain/billing/time_rate.entry_rate (or entry_worth), which knows which column wins: {stray}")
    stale = sorted(set(READS_THE_LEGACY_COLUMN) - set(found))
    assert not stale, f"these no longer read the legacy column; delete them from READS_THE_LEGACY_COLUMN: {stale}"


def test_the_rule_sees_a_read_and_not_a_write():
    assert _legacy_reads('x = e.get("hourly_rate_paise")\ny = e["hourly_rate_paise"]\n') == [1, 2]
    assert _legacy_reads('row = {"hourly_rate_paise": 5}\nrow["hourly_rate_paise"] = 6\nq.select("hourly_rate_paise")\n') == []


def test_the_restatement_with_no_caller_is_gone():
    import services.billing_service as billing
    assert not hasattr(billing, "unbilled_value_paise")
    assert "def entry_worth(" in (API / "domain" / "billing" / "time_rate.py").read_text(encoding="utf-8")
    assert time_rate.entry_worth({"is_billable": True, "billable_rate_paise": None, "hourly_rate_paise": 60_000,
                                  "duration_minutes": 30, "ended_at": "x"}) == {"rate_paise": 60_000, "value_paise": 30_000}
