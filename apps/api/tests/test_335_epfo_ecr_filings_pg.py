"""
Migration 335 — the rules about EPFO returns that only the database can hold.

WHY THESE ARE HERE AND NOT IN THE MOCK SUITE

domain/payroll/ecr_sequence.py decides what a month needs from the filings it is
handed. It is tested exhaustively in mock mode. What it CANNOT test is whether
the database will accept a row that would make its answer wrong, and there is
one such row: a second Regular return for a wage month.

That is the most likely wrong entry a CA can make — a late joiner looks exactly
like "I need to file this month again" to someone not watching — and its effect
is silent. A duplicate Regular clears a month that actually needed a
Supplementary, so the sequence says "nothing outstanding" and the portal says
otherwise. A unique index that does not bite is the same as no rule, so it is
proved here against real PostgreSQL rather than reasoned about.

The other three assertions are the CHECK constraints that stop a row from
claiming a state it has no evidence for.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="migration 335 proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000335"
CLIENT = "bbbbbbbb-0000-0000-0000-000000000335"
OTHER_CLIENT = "bbbbbbbb-0000-0000-0000-000000000336"
MONTH = "2026-06"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _insert(dsn: str, *, month: str = MONTH, return_type: str = "regular",
            status: str = "submitted", submitted: str = "2026-07-10",
            approved: str | None = None, client: str = CLIENT) -> subprocess.CompletedProcess:
    approved_sql = f"'{approved}'" if approved else "NULL"
    return _psql(dsn, f"""
        INSERT INTO public.epfo_ecr_filings
          (firm_id, client_id, wage_month, return_type, status, submitted_on, approved_on)
        VALUES ('{FIRM}','{client}','{month}','{return_type}','{status}',
                '{submitted}', {approved_sql});
    """)


@pytest.fixture()
def seeded(pg_template):
    admin = _ADMIN.strip()
    dbname = f"m335_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        assert "335_the_ecr_knows_which_months_are_outstanding.sql" not in pg_template.failed
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M335 Firm','m335@test.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
              ('{CLIENT}','{FIRM}','M335 Client','Private Limited'),
              ('{OTHER_CLIENT}','{FIRM}','M335 Other','Private Limited');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def test_a_second_regular_for_the_same_month_is_refused(seeded):
    """The entry that silently clears a month which still needs a Supplementary."""
    assert _insert(seeded).returncode == 0
    second = _insert(seeded)
    assert second.returncode != 0
    assert "epfo_ecr_one_regular_per_month" in second.stderr


def test_supplementary_and_revised_are_repeatable(seeded):
    """A month can genuinely need several of either, so the index is partial on
    return_type. If it were on the pair, a second correction would be refused."""
    for kind in ("supplementary", "supplementary", "revised", "revised"):
        r = _insert(seeded, return_type=kind)
        assert r.returncode == 0, r.stderr
    n = _psql(seeded, f"SELECT count(*) FROM public.epfo_ecr_filings "
                      f"WHERE client_id='{CLIENT}';", tuples=True)
    assert n.stdout.strip() == "4"


def test_retracting_a_regular_frees_the_month(seeded):
    """Soft delete has to actually release the unique index, or a mis-recorded
    filing would lock its month for ever with no way back."""
    assert _insert(seeded).returncode == 0
    assert _psql(seeded, f"UPDATE public.epfo_ecr_filings SET deleted_at = now() "
                         f"WHERE client_id='{CLIENT}';").returncode == 0
    again = _insert(seeded)
    assert again.returncode == 0, again.stderr


def test_two_clients_may_each_file_the_same_month(seeded):
    """The index is per client. Scoping it to the firm would let one client's
    filing clear another's month."""
    assert _insert(seeded).returncode == 0
    assert _insert(seeded, client=OTHER_CLIENT).returncode == 0


def test_an_approved_return_must_carry_an_approval_date(seeded):
    """Approved is the state that clears a month. A row claiming it with no date
    records the clearance and no evidence of when it happened."""
    r = _insert(seeded, status="approved", approved=None)
    assert r.returncode != 0
    assert "epfo_ecr_approved_needs_a_date" in r.stderr


def test_approval_cannot_predate_submission(seeded):
    r = _insert(seeded, status="approved", submitted="2026-07-10", approved="2026-07-01")
    assert r.returncode != 0
    assert "epfo_ecr_approved_not_before_submitted" in r.stderr


def test_a_wage_month_must_be_a_wage_month(seeded):
    """The sequence sorts these as text. A malformed month sorts into the wrong
    place, and a wrong ORDER is a wrong answer about what to file first."""
    for bad in ("2026-13", "June 2026", "2026-6"):
        r = _insert(seeded, month=bad)
        assert r.returncode != 0, f"{bad!r} was accepted as a wage month"


def test_deleting_the_run_keeps_the_filing(seeded):
    """ON DELETE SET NULL, never CASCADE. The filing happened at the portal and
    outlives anything we hold about how the file was prepared."""
    run_id = "cccccccc-0000-0000-0000-000000000335"
    assert _psql(seeded, f"""
        INSERT INTO payroll_runs (id, firm_id, client_id, month, status)
          VALUES ('{run_id}','{FIRM}','{CLIENT}','{MONTH}','finalized');
        INSERT INTO public.epfo_ecr_filings
          (firm_id, client_id, run_id, wage_month, return_type, status, submitted_on)
        VALUES ('{FIRM}','{CLIENT}','{run_id}','{MONTH}','regular','submitted','2026-07-10');
    """).returncode == 0
    assert _psql(seeded, f"DELETE FROM payroll_runs WHERE id='{run_id}';").returncode == 0
    left = _psql(seeded, f"SELECT count(*), count(run_id) FROM public.epfo_ecr_filings "
                         f"WHERE client_id='{CLIENT}';", tuples=True)
    assert left.stdout.strip() == "1|0"


def test_members_must_be_an_array(seeded):
    """[] is a positive record — a return filed for no members. A scalar would
    make jsonb_array_length raise wherever the payload is read."""
    r = _psql(seeded, f"""
        INSERT INTO public.epfo_ecr_filings
          (firm_id, client_id, wage_month, return_type, status, submitted_on, members)
        VALUES ('{FIRM}','{CLIENT}','{MONTH}','regular','submitted','2026-07-10',
                '"not an array"'::jsonb);
    """)
    assert r.returncode != 0
