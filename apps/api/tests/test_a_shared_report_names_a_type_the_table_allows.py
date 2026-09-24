"""A report the screen offers to share is a type the table will accept, and the
browser holds neither privileged write.

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

It failed in the worst possible order. `shareToPortal` uploaded the workbook to
Supabase Storage FIRST and inserted the row second, so every press left a file in
storage with no row pointing at it and put a raw Postgres constraint message
into an `alert()`.

── AND THE WRITES THEMSELVES WERE THE BROWSER'S ─────────────────────────────
Both of them: an upload into the `Documents` bucket and an INSERT over
PostgREST. So `rbac()` ran on neither, and what that button publishes is a
client's Profit & Loss, Balance Sheet or Trial Balance to that client's own
portal, with RLS as the only control. `POST /api/accounting/shared-reports` is
the one door now, under `rbac("accounting", "write")` with `can_access_client`
beside it, and `domain/reporting/shared_report.py` owns the vocabulary — so the
browser names no report type at all and cannot post one the CHECK refuses.

── THE RULE ─────────────────────────────────────────────────────────────────
A value anything can WRITE must be one the column will ACCEPT, and the screen
that OFFERS a report must be offering one that authority knows. The second half
is what keeps the first honest: a fourth report added to `REPORT_LINKS` with no
entry in `REPORT_TYPES` is refused with a sentence rather than reaching the
database.

Held from the PYTHON side deliberately, and that is not merely where the
authority now lives. A guard written in `apps/web` asserting the browser's list
against a copy of the vocabulary passes exactly when both have drifted together
— the Schedule III caption lesson, which this repository has had to learn three
times. The migration is the authority for the column; the domain module is the
authority for what this screen may share; this reads all three files.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from domain.reporting.shared_report import ALLOWED_REPORT_TYPES, REPORT_TYPES

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


def test_every_type_the_authority_writes_is_one_the_table_accepts():
    allowed = _allowed_report_types()
    rejected = {k: v for k, v in REPORT_TYPES.items() if v not in allowed}
    assert not rejected, (
        "domain/reporting/shared_report.py maps a report to a value the "
        f"shared_reports CHECK will refuse: {rejected}. Allowed: "
        f"{sorted(allowed)}. The INSERT fails AFTER the workbook has already "
        "been uploaded, so the file would be orphaned in storage."
    )


def test_the_module_and_the_migration_agree_about_the_whole_vocabulary():
    """`ALLOWED_REPORT_TYPES` exists so a caller can be told what the column
    would take rather than only what this screen offers. A copy of a CHECK is a
    thing that drifts, so it is pinned to the CHECK itself."""
    assert set(ALLOWED_REPORT_TYPES) == _allowed_report_types(), (
        "ALLOWED_REPORT_TYPES no longer matches the migration's CHECK — the "
        "module would refuse a value the column takes, or let one through that "
        "it does not"
    )


def test_the_screen_offers_no_report_the_authority_cannot_name():
    """A report with a button and no entry in the map is the original bug.

    The conditional this replaced was not missing a case in an obvious way — it
    handled "bs" and let everything else through unchanged, which reads as
    deliberate. A total map cannot do that: a fourth report added to REPORT_LINKS
    with no entry in REPORT_TYPES is refused with a sentence.
    """
    src = SCREEN.read_text()
    offered = set(re.findall(r'\{\s*id:\s*"(pl|bs|trial)"', src))
    assert offered, "REPORT_LINKS no longer lists the shareable reports by id"
    missing = offered - set(REPORT_TYPES)
    assert not missing, (
        f"the screen offers {sorted(missing)} to share and "
        "domain/reporting/shared_report.REPORT_TYPES does not name them, so "
        "the share would be refused as an unknown report"
    )


#: How a WRITE is spelled over PostgREST, and how one is spelled against a
#: storage bucket. A READ of either is deliberately not in this list: the screen
#: still lists what has been shared and signs a URL so the CA can open it, and
#: both are reads RLS already scopes. What moved to the server is the writing.
_POSTGREST_WRITES = ("insert(", "upsert(", "update(", "delete(")
_STORAGE_WRITES = ("upload(", "remove(", "move(", "copy(")


def test_the_browser_holds_neither_privileged_write():
    """The upload and the insert are the server's.

    Stated as the RULE rather than as a spelling of it: what matters is that
    this screen no longer WRITES `shared_reports` and no longer writes into a
    storage bucket, whatever the call happens to be named. It still BUILDS the
    workbook, which is formatting of figures `/api/accounting/*` already
    computed, and it still READS both — a list of what has been shared, and a
    signed URL to open one.
    """
    src = SCREEN.read_text()
    body = re.sub(r"/\*[\s\S]*?\*/", " ", src)
    body = re.sub(r"^\s*//.*$", " ", body, flags=re.M)

    # A PostgREST chain is fluent, so the verb follows the table within one
    # statement. Read to the end of the statement rather than a fixed window:
    # a window is a spelling, and a reformat moves it.
    for m in re.finditer(r'from\(\s*"shared_reports"\s*\)', body):
        stmt = body[m.end(): body.find(";", m.end()) + 1 or len(body)]
        wrote = [v for v in _POSTGREST_WRITES if v in stmt]
        assert not wrote, (
            f"the accounting screen writes shared_reports over PostgREST again "
            f"({', '.join(wrote)}) — rbac() does not run there, and what this "
            "publishes is a client's statements to that client's own portal"
        )

    for m in re.finditer(r"\.storage\s*\.?\s*from\(", body):
        stmt = body[m.end(): body.find(";", m.end()) + 1 or len(body)]
        wrote = [v for v in _STORAGE_WRITES if v in stmt]
        assert not wrote, (
            f"the accounting screen writes into a storage bucket again "
            f"({', '.join(wrote)}); the upload belongs behind "
            "POST /api/accounting/shared-reports"
        )

    assert "api.accounting.shareReport" in body, (
        "the screen no longer posts the share to the server — if the endpoint "
        "moved, point this guard at it rather than deleting it"
    )


def test_the_probe_still_finds_the_calls_it_is_about():
    """A scan that matches nothing passes for ever. Both halves of the rule are
    about calls that ARE still in this file — a read of the table and a signed
    URL off the bucket — so their absence means the probe went blind, not that
    the screen got safer."""
    body = SCREEN.read_text()
    assert re.search(r'from\(\s*"shared_reports"\s*\)', body), (
        "the probe no longer finds shared_reports on the accounting screen; a "
        "moved read means this guard is asserting nothing"
    )
    assert re.search(r"\.storage\s*\.?\s*from\(", body), (
        "the probe no longer finds a storage call on the accounting screen"
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
