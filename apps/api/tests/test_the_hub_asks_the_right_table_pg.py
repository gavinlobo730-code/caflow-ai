"""The hub's status vocabularies, against the CHECKs themselves.

The sibling module holds the SHAPE. This holds the FACT, and it is the one
that matters: four of the nine vocabularies in the first draft of
`services/hub_service.py` were written from memory and wrong, every one of
them plausible, and three of the four would have produced a confidently wrong
number on a screen whose entire purpose is a number a CA acts on.

A remembered list cannot catch that. Only the constraint can.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from services import hub_service as svc

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the hub vocabulary proof requires HARNESS_PG + psql",
)

#: Which table and column each key of `_ALL` describes. Kept here rather than
#: in the service because the service has no business naming a constraint —
#: and because this is the mapping the guard is ABOUT.
SOURCE = {
    "journal_entries": ("journal_entries", "status"),
    "payroll_runs": ("payroll_runs", "status"),
    "itr_filings": ("itr_filings", "status"),
    "compliance_records": ("compliance_records", "status"),
    "year_end_engagements": ("year_end_engagements", "status"),
    # One key, two tables — GSTR-1 and GSTR-3B carry the same four, and the
    # tile counts both. If they ever diverge this test is where it shows.
    "gst_returns": ("gstr1_returns", "status"),
}


@pytest.fixture(scope="module")
def dsn(pg_template):
    return f"{_ADMIN.strip()} dbname={pg_template.name}"


def _allowed_values(dsn: str, table: str, column: str) -> set[str]:
    """The literals a CHECK on that column admits, read off the constraint."""
    sql = (
        "SELECT pg_get_constraintdef(x.oid) FROM pg_constraint x "
        "JOIN pg_class c ON c.oid = x.conrelid "
        f"WHERE x.contype='c' AND c.relname='{table}' "
        f"AND pg_get_constraintdef(x.oid) LIKE '%({column} =%'"
    )
    r = subprocess.run(["psql", dsn, "-tA", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    body = r.stdout.strip()
    assert body, f"no CHECK on {table}.{column} — the hub's filter is unconstrained"
    import re
    return set(re.findall(r"'([^']+)'::text", body))


@pytest.mark.parametrize("key", sorted(SOURCE))
def test_the_services_vocabulary_is_the_checks_vocabulary(dsn, key):
    table, column = SOURCE[key]
    live = _allowed_values(dsn, table, column)
    held = set(svc._ALL[key])
    assert held == live, (
        f"{key}: hub_service._ALL and {table}.{column}'s CHECK disagree.\n"
        f"  only in the service: {sorted(held - live)}\n"
        f"  only in the CHECK:   {sorted(live - held)}\n\n"
        f"A value only in the CHECK is the dangerous direction: the tile's "
        f"outstanding set is the COMPLEMENT of the finished ones, so a new "
        f"intermediate status is meant to join the count automatically — and "
        f"it cannot if this list has not heard of it.")


def test_gstr1_and_gstr3b_still_share_one_vocabulary(dsn):
    """The hub counts both under one key. If their CHECKs ever diverge, that
    key becomes a lie about one of them."""
    assert _allowed_values(dsn, "gstr1_returns", "status") == \
           _allowed_values(dsn, "gstr3b_returns", "status")


def test_every_column_the_hub_filters_on_exists(dsn):
    """The `documents.status` defect, stated as a rule. PostgREST answers
    42703 for a column that is not there, so this would have surfaced as a
    failed tile rather than a wrong number — but a failed tile on every hub,
    for ever, is not much better."""
    wanted = [
        ("compliance_records", "status"), ("gstr1_returns", "status"),
        ("gstr3b_returns", "status"), ("bank_transactions", "entry_state"),
        ("journal_entries", "status"), ("client_sales_invoices", "outstanding_paise"),
        ("purchase_bills", "outstanding_paise"), ("tds_deductions", "tds_paise"),
        ("tds_deductions", "challan_no"), ("payroll_runs", "status"),
        ("itr_filings", "status"), ("fixed_assets", "depreciation_posted_through"),
        ("year_end_engagements", "status"), ("documents", "review_status"),
    ]
    missing = []
    for table, column in wanted:
        r = subprocess.run(
            ["psql", dsn, "-tA", "-c",
             "SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
             f"AND table_name='{table}' AND column_name='{column}'"],
            capture_output=True, text=True)
        if r.stdout.strip() != "1":
            missing.append(f"{table}.{column}")
    assert not missing, f"the hub filters on columns that do not exist: {missing}"


def test_this_guard_is_not_vacuous(dsn):
    # The parser really reads a CHECK, and really rejects a wrong one.
    live = _allowed_values(dsn, "journal_entries", "status")
    assert live == {"draft", "posted", "void"}, live
    assert "nonsense" not in live
