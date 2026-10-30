"""A client's Tally job never outlives its client as a firm-level job (ledger POST-A-303).

THE PREMISE (the other half is `test_nothing_hard_deletes_a_client_but_the_firm_purge.py`)
    `tally_migration_jobs.client_id` is ON DELETE SET NULL and a job with no client is open to the whole firm (migration 528). The
    only statement that removes client rows is `platform_purge_firm`, which removes the whole firm and clears every firm-scoped
    table first. A soft delete (the API's client delete) never touches `client_id`.

WHAT IS HELD (a real database, row counts)
    * a firm purge leaves no Tally job and no item of the firm it purged, a client-linked job and a firm-level one alike, and
      leaves every row of another firm exactly as it was;
    * marking a client deleted (what `client_repo.soft_delete` writes) leaves its job pinned to that client: the job does not
      become firm-level, and a Manager who is not assigned to the client still does not see it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest

from tests._signed_in_postgrest import SignedInDb

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None,
    reason="the Tally job proof requires HARNESS_PG + psql",
)

FIRM = "30300000-0000-0000-0000-000000000001"
OTHER_FIRM = "30300000-0000-0000-0000-000000000002"
CLIENT = "30300000-0000-0000-0000-0000000000c1"
OTHER_CLIENT = "30300000-0000-0000-0000-0000000000c2"
PARTNER = {"id": "30300000-0000-0000-0000-00000000000a", "auth_user_id": "30300000-1111-0000-0000-000000000001"}
MANAGER = {"id": "30300000-0000-0000-0000-00000000000b", "auth_user_id": "30300000-1111-0000-0000-000000000002"}
OTHER_MANAGER = {"id": "30300000-0000-0000-0000-00000000000c", "auth_user_id": "30300000-1111-0000-0000-000000000003"}
# A member of the OTHER firm, who created that firm's job (migration 566: a job cannot name a member of another firm).
OTHER_FIRMS_PARTNER = "30300000-0000-0000-0000-00000000000d"
JOB, FIRM_LEVEL_JOB, OTHER_FIRMS_JOB = (f"30300000-0000-0000-0000-0000000000{n}" for n in ("f1", "f2", "f3"))


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _count(dsn: str, sql: str) -> int:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip())


@pytest.fixture()
def world(pg_template):
    admin = _ADMIN.strip()
    name = f"e303_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{PARTNER["auth_user_id"]}', 'p@t.in'), ('{MANAGER["auth_user_id"]}', 'm@t.in'),
                 ('{OTHER_MANAGER["auth_user_id"]}', 'o@t.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in'), ('{OTHER_FIRM}', 'G', 'g@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
                 VALUES ('{CLIENT}', '{FIRM}', 'A', 'Proprietorship'), ('{OTHER_CLIENT}', '{OTHER_FIRM}', 'B', 'Proprietorship');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                 VALUES ('{PARTNER["id"]}', '{FIRM}', '{PARTNER["auth_user_id"]}', 'p@t.in', 'P', 'Partner', true),
                        ('{MANAGER["id"]}', '{FIRM}', '{MANAGER["auth_user_id"]}', 'm@t.in', 'M', 'Manager', true),
                        ('{OTHER_MANAGER["id"]}', '{FIRM}', '{OTHER_MANAGER["auth_user_id"]}', 'o@t.in', 'O', 'Manager', true),
                        ('{OTHER_FIRMS_PARTNER}', '{OTHER_FIRM}', NULL, 'g@t.in', 'GP', 'Partner', true);
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES ('{FIRM}', '{MANAGER["id"]}', '{CLIENT}');
            INSERT INTO tally_migration_jobs (id, firm_id, client_id, name, source_file_name, target_financial_year, created_by)
                 VALUES ('{JOB}', '{FIRM}', '{CLIENT}', 'A books', 'a.xml', '2025-26', '{PARTNER["id"]}'),
                        ('{FIRM_LEVEL_JOB}', '{FIRM}', NULL, 'firm ledgers', 'f.xml', '2025-26', '{PARTNER["id"]}'),
                        ('{OTHER_FIRMS_JOB}', '{OTHER_FIRM}', '{OTHER_CLIENT}', 'B books', 'b.xml', '2025-26', '{OTHER_FIRMS_PARTNER}');
            INSERT INTO tally_migration_items (firm_id, job_id, item_type)
                 VALUES ('{FIRM}', '{JOB}', 'ledger'), ('{FIRM}', '{JOB}', 'customer'), ('{FIRM}', '{FIRM_LEVEL_JOB}', 'ledger'),
                        ('{OTHER_FIRM}', '{OTHER_FIRMS_JOB}', 'ledger');
        """)
        assert seed.returncode == 0, seed.stderr

        class World:
            pass

        w = World()
        w.dsn = dsn
        w.manager_db = SignedInDb(dsn, auth_user_id=MANAGER["auth_user_id"])
        w.other_manager_db = SignedInDb(dsn, auth_user_id=OTHER_MANAGER["auth_user_id"])
        yield w
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def test_a_firm_purge_leaves_no_tally_job_or_item_of_that_firm_and_touches_no_other(world):
    jobs = lambda f: _count(world.dsn, f"SELECT count(*) FROM tally_migration_jobs WHERE firm_id = '{f}'")
    items = lambda f: _count(world.dsn, f"SELECT count(*) FROM tally_migration_items WHERE firm_id = '{f}'")
    assert (jobs(FIRM), items(FIRM), jobs(OTHER_FIRM), items(OTHER_FIRM)) == (2, 3, 1, 1)

    # as the backend calls it: the service role, with the role claim the function's own authorization reads
    purge = _psql(world.dsn, "SET request.jwt.claims = '{\"role\": \"service_role\"}'; SET ROLE service_role; "
                             f"SELECT public.platform_purge_firm('{FIRM}');")
    assert purge.returncode == 0, purge.stderr

    assert _count(world.dsn, f"SELECT count(*) FROM clients WHERE firm_id = '{FIRM}'") == 0
    assert (jobs(FIRM), items(FIRM)) == (0, 0), "a job of the purged firm survived the purge as a client-less row"
    assert _count(world.dsn, f"SELECT count(*) FROM tally_migration_jobs WHERE client_id IS NULL AND firm_id = '{FIRM}'") == 0
    assert (jobs(OTHER_FIRM), items(OTHER_FIRM)) == (1, 1), "the purge reached another firm"
    assert _count(world.dsn, f"SELECT count(*) FROM tally_migration_jobs WHERE id = '{OTHER_FIRMS_JOB}' AND client_id = '{OTHER_CLIENT}'") == 1


def test_a_soft_deleted_client_keeps_its_job_pinned_to_it_and_hidden_from_a_member_not_assigned(world):
    sees = lambda db: {r["id"] for r in db.table("tally_migration_jobs").select("id").execute().data}
    assert sees(world.manager_db) == {JOB, FIRM_LEVEL_JOB}                 # the assigned Manager: their client's job and the firm-level one
    assert sees(world.other_manager_db) == {FIRM_LEVEL_JOB}                # not assigned: the firm-level job only

    # what client_repo.soft_delete writes
    assert _psql(world.dsn, f"UPDATE clients SET deleted_at = now(), is_deleted = true WHERE id = '{CLIENT}';").returncode == 0

    assert _count(world.dsn, f"SELECT count(*) FROM tally_migration_jobs WHERE id = '{JOB}' AND client_id = '{CLIENT}'") == 1
    assert sees(world.other_manager_db) == {FIRM_LEVEL_JOB}, "a soft delete turned the client's job into one every member reads"
