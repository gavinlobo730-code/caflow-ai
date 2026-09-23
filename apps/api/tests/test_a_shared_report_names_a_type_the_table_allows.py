"""A report the screen offers to share is a type the table will accept.

── THE DEFECT ───────────────────────────────────────────────────────────────
`app/clients/[id]/accounting/page.tsx` offers three reports to share with the
client's own portal — Profit & Loss, Balance Sheet and Trial Balance — and
mapped one of them:

    report_type: reportType === "bs" ? "balance_sheet" : reportType

"pl" is a legal value by coincidence and "bs" is translated, so two of the three
worked. "trial" fell through the conditional unchanged, and migration 032's

    CHECK (report_type IN ('pl', 'balance_sheet', 'gst_summary', 'tds_summary'))

has never contained it. So sharing a Trial Balance was refused by the database
every single time, on a button the screen has always rendered.

It failed in the worst possible order. `shareToPortal` uploads the workbook to
Supabase Storage FIRST and inserts the row second, so every press left a file in
storage with no row pointing at it and put a raw Postgres constraint message
into an `alert()`.

── THE RULE ─────────────────────────────────────────────────────────────────
A value the browser can WRITE must be one the column will ACCEPT. That is the
general shape and it is worth more than the one bug: roughly 83 tables are
written directly from the browser over PostgREST, where `rbac()` never runs and
the only thing standing between a typo and a refused write is a CHECK nobody
reads on the way past.

Held from the PYTHON side deliberately. A guard written in `apps/web` asserting
the browser's map against a copy of the vocabulary passes exactly when both have
drifted together — the Schedule III caption lesson, which this repository has
now had to learn three times. The migration is the authority; the browser is the
copy; this reads both files and compares them.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]
WEB = API.parent / "web"
SCREEN = WEB / "app" / "clients" / "[id]" / "accounting" / "page.tsx"


def _allowed_report_types() -> set[str]:
    """The values the CHECK admits, read from the migration that LAST set it.

    Found by NUMBER rather than from memory, the same discipline
    `CREATE OR REPLACE FUNCTION` needs: a constraint is dropped and re-added, so
    an earlier migration's list is not the live one.
    """
    setters = sorted(
        p for p in (API / "migrations").glob("*.sql")
        if re.search(r"report_type IN \(", p.read_text())
        and "shared_reports" in p.read_text()
    )
    assert setters, "no migration declares shared_reports.report_type's CHECK"
    body = setters[-1].read_text()
    # The LAST occurrence in that file: 412 drops the old constraint and adds the
    # new one, and a scan finding the first would read the comment quoting 032's.
    matches = re.findall(r"report_type IN \(([^)]*)\)", body)
    assert matches, f"{setters[-1].name} names shared_reports but sets no CHECK"
    return {v.strip().strip("'") for v in matches[-1].split(",")}


def _browser_report_types() -> dict[str, str]:
    """What the screen writes, read out of its own map."""
    src = SCREEN.read_text()
    m = re.search(
        r"const SHARED_REPORT_TYPE:[^=]*=\s*\{(.*?)\}", src, re.S
    )
    assert m, (
        "the accounting screen no longer declares SHARED_REPORT_TYPE. If the "
        "mapping moved, point this guard at it — do not delete the guard, "
        "because the defect it caught was a value falling through a conditional."
    )
    return dict(re.findall(r"(\w+):\s*\"([^\"]+)\"", m.group(1)))


def test_every_type_the_browser_writes_is_one_the_table_accepts():
    allowed = _allowed_report_types()
    written = _browser_report_types()
    rejected = {k: v for k, v in written.items() if v not in allowed}
    assert not rejected, (
        "the accounting screen shares a report the shared_reports CHECK will "
        f"refuse: {rejected}. Allowed: {sorted(allowed)}. The INSERT fails AFTER "
        "the workbook has already been uploaded, so the file is orphaned in "
        "storage and the CA sees a raw constraint error."
    )


def test_the_screen_maps_every_report_it_offers():
    """A report with a button and no entry in the map is the original bug.

    The conditional this replaced was not missing a case in an obvious way — it
    handled "bs" and let everything else through unchanged, which reads as
    deliberate. A total map cannot do that: a fourth report added to REPORT_LINKS
    with no entry here fails this test rather than reaching the database.
    """
    src = SCREEN.read_text()
    offered = set(re.findall(r'\{\s*id:\s*"(pl|bs|trial)"', src))
    assert offered, "REPORT_LINKS no longer lists the shareable reports by id"
    missing = offered - set(_browser_report_types())
    assert not missing, (
        f"the screen offers {sorted(missing)} to share and the map does not "
        "name them, so they would be written as their own screen id"
    )


@pytest.mark.parametrize("dead", ["payroll_summary"])
def test_the_vocabulary_holds_no_value_nothing_writes(dead: str):
    """A member no writer emits is one the next reader has to check before
    trusting — the `capital_wip` shape this codebase keeps finding. Migration 031
    put `payroll_summary` on the EMPLOYEE portal's table; it is deliberately not
    on this one, and this pins that decision so it is not 'tidied' in later.
    """
    assert dead not in _allowed_report_types(), (
        f"{dead} was added to shared_reports.report_type. Nothing writes it "
        "through this table — if something now does, delete this test and say "
        "what writes it."
    )
