"""
Migration 273 — related_party_loans must isolate by firm AND by client
assignment, against a real Postgres.

WHY THIS IS WORTH A DB TEST
    The table carries s.185 findings: which director borrowed how much from
    which client. Two policies guard it, and the second one is new here —

        related_party_loans_isolation         PERMISSIVE, firm_id = get_my_firm_id()
        related_party_loans_assignment_scope  RESTRICTIVE, can_access_client(...)

    A RESTRICTIVE policy ANDs rather than ORs, so getting it wrong fails in one
    of two directions and only one of them is visible: too tight and legitimate
    reads vanish; too loose and one firm's staff read another client's director
    loans. Neither is something to infer from the DDL by eye.

    The API already calls assert_client_access on every one of these endpoints.
    This asserts the same rule where it cannot be skipped — which matters
    because with USE_USER_JWT on, the API IS the end user as far as Postgres is
    concerned.

Runs only when HARNESS_PG is set + psql is on PATH. The `migrations` CI job
runs it against its real Postgres 16.
"""
from __future__ import annotations

import json
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
    reason="related_party_loans RLS proof requires HARNESS_PG + psql",
)

FIRM = "f2000000-0000-0000-0000-000000000001"
OTHER_FIRM = "f2000000-0000-0000-0000-000000000002"
ASSIGNED = "c2000000-0000-0000-0000-000000000001"
UNASSIGNED = "c2000000-0000-0000-0000-000000000002"
ENTITY = "e2000000-0000-0000-0000-000000000001"
EXEC_AUTH = "22222222-2222-2222-2222-222222222222"
EXEC_USER = "d2000000-0000-0000-0000-000000000001"

LOAN_ASSIGNED = "10000000-0000-0000-0000-000000000001"
LOAN_UNASSIGNED = "10000000-0000-0000-0000-000000000002"

SEED = f"""
INSERT INTO auth.users (id) VALUES ('{EXEC_AUTH}') ON CONFLICT DO NOTHING;
INSERT INTO firms (id,name,email) VALUES
  ('{FIRM}','F','f@t.in'), ('{OTHER_FIRM}','G','g@t.in');
INSERT INTO clients (id,firm_id,client_name,entity_type) VALUES
  ('{ASSIGNED}','{FIRM}','Assigned','Proprietorship'),
  ('{UNASSIGNED}','{FIRM}','Unassigned','Proprietorship');
INSERT INTO entities (id,firm_id,entity_type,full_name)
  VALUES ('{ENTITY}','{FIRM}','Individual','A Director');
INSERT INTO users (id,firm_id,full_name,email,role,auth_user_id)
  VALUES ('{EXEC_USER}','{FIRM}','Exec','exec@t.in','Executive','{EXEC_AUTH}');
INSERT INTO user_client_assignments (user_id,client_id,firm_id)
  VALUES ('{EXEC_USER}','{ASSIGNED}','{FIRM}');
INSERT INTO related_party_loans
  (id, firm_id, client_id, entity_id, loan_type, principal_paise, section_185_flagged)
VALUES
  ('{LOAN_ASSIGNED}','{FIRM}','{ASSIGNED}','{ENTITY}','to_director',10000000,true),
  ('{LOAN_UNASSIGNED}','{FIRM}','{UNASSIGNED}','{ENTITY}','to_director',20000000,true);
"""


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _as_user(sql: str, auth_uid: str = EXEC_AUTH) -> str:
    """Run sql the way PostgREST does: role `authenticated`, JWT claims set."""
    claims = json.dumps({"sub": auth_uid, "role": "authenticated"}).replace("'", "''")
    return (f"SET LOCAL ROLE authenticated; "
            f"SELECT set_config('request.jwt.claims', '{claims}', true); {sql}")


@pytest.fixture()
def seeded_db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"rpl_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, SEED)
        assert seed.returncode == 0, f"seed failed: {seed.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


# ── Shape ────────────────────────────────────────────────────────────────────

def test_the_table_exists_with_both_section_flags(seeded_db):
    r = _psql(seeded_db, """
        SELECT count(*) FROM information_schema.columns
         WHERE table_schema='public' AND table_name='related_party_loans'
           AND column_name IN ('entity_id','sanction_date','due_date',
                               'section_185_flagged','section_186_flagged',
                               'interest_rate','updated_at');
    """, tuples=True)
    assert r.stdout.strip() == "7", "the seven columns `loans` lacked must all be here"


def test_loan_type_permits_the_values_the_feature_uses(seeded_db):
    """`loans` rejects these; that mismatch was half the original bug."""
    for value in ("to_director", "from_director", "inter_company", "other"):
        r = _psql(seeded_db, f"""
            INSERT INTO related_party_loans
              (firm_id, client_id, entity_id, loan_type, principal_paise)
            VALUES ('{FIRM}','{ASSIGNED}','{ENTITY}','{value}',100);
        """)
        assert r.returncode == 0, f"loan_type {value!r} was rejected: {r.stderr}"


def test_a_nonsense_loan_type_is_still_refused(seeded_db):
    r = _psql(seeded_db, f"""
        INSERT INTO related_party_loans
          (firm_id, client_id, entity_id, loan_type, principal_paise)
        VALUES ('{FIRM}','{ASSIGNED}','{ENTITY}','term_loan',100);
    """)
    assert r.returncode != 0, "a bank product is not a related-party loan type"


def test_principal_must_be_positive(seeded_db):
    r = _psql(seeded_db, f"""
        INSERT INTO related_party_loans
          (firm_id, client_id, entity_id, loan_type, principal_paise)
        VALUES ('{FIRM}','{ASSIGNED}','{ENTITY}','other',0);
    """)
    assert r.returncode != 0, "a zero-principal loan is not a loan"


def test_deleting_the_entity_cannot_erase_the_finding(seeded_db):
    """ON DELETE RESTRICT: a s.185 record must outlive tidying up the entity
    list, or the evidence disappears with the counterparty."""
    r = _psql(seeded_db, f"DELETE FROM entities WHERE id='{ENTITY}';")
    assert r.returncode != 0, "the entity delete should have been restricted"


# ── Isolation ────────────────────────────────────────────────────────────────

def test_an_assigned_client_is_visible(seeded_db):
    r = _psql(seeded_db, _as_user(
        f"SELECT count(*) FROM related_party_loans WHERE client_id='{ASSIGNED}';"),
        tuples=True)
    assert r.stdout.strip().splitlines()[-1] == "1", (
        "the assignment-scope policy is too tight — a user assigned to this "
        "client cannot read its own loans"
    )


def test_an_unassigned_client_is_not_visible(seeded_db):
    """Same firm, so firm isolation alone would let this through. The
    RESTRICTIVE assignment policy is what stops it."""
    r = _psql(seeded_db, _as_user(
        f"SELECT count(*) FROM related_party_loans WHERE client_id='{UNASSIGNED}';"),
        tuples=True)
    assert r.stdout.strip().splitlines()[-1] == "0", (
        "a staff member unassigned from this client read its director loans"
    )


def test_another_firms_rows_are_not_visible(seeded_db):
    r = _psql(seeded_db, f"""
        INSERT INTO related_party_loans
          (firm_id, client_id, entity_id, loan_type, principal_paise)
        SELECT '{OTHER_FIRM}', id, '{ENTITY}', 'to_director', 999
          FROM clients WHERE id='{ASSIGNED}';
    """)
    assert r.returncode == 0, f"admin seed of the other firm's row failed: {r.stderr}"
    r = _psql(seeded_db, _as_user(
        f"SELECT count(*) FROM related_party_loans WHERE firm_id='{OTHER_FIRM}';"),
        tuples=True)
    assert r.stdout.strip().splitlines()[-1] == "0"


def test_a_write_for_an_unassigned_client_is_refused(seeded_db):
    """WITH CHECK, not just USING — otherwise a user could write rows they
    would then be unable to read."""
    r = _psql(seeded_db, _as_user(f"""
        INSERT INTO related_party_loans
          (firm_id, client_id, entity_id, loan_type, principal_paise)
        VALUES ('{FIRM}','{UNASSIGNED}','{ENTITY}','to_director',100);
    """))
    assert r.returncode != 0, "wrote a director loan for a client not assigned to the caller"


def test_service_role_still_sees_everything(seeded_db):
    """Background jobs bypass RLS and must keep doing so."""
    r = _psql(seeded_db,
              "SET LOCAL ROLE service_role; SELECT count(*) FROM related_party_loans;",
              tuples=True)
    assert int(r.stdout.strip().splitlines()[-1]) >= 2


def test_the_api_role_holds_dml(seeded_db):
    """With USE_USER_JWT on the API runs as `authenticated`; without these
    grants every write here would be a 42501, which is the bug that started
    this whole sequence."""
    r = _psql(seeded_db, """
        SELECT has_table_privilege('authenticated','public.related_party_loans','SELECT'),
               has_table_privilege('authenticated','public.related_party_loans','INSERT'),
               has_table_privilege('authenticated','public.related_party_loans','UPDATE'),
               has_table_privilege('service_role','public.related_party_loans','INSERT');
    """, tuples=True)
    assert r.stdout.strip() == "t|t|t|t", r.stdout
