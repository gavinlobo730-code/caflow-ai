"""Migration 551: a signed-in session reads and writes none of the document tables and opens no stored file (POST-A-339, the document
group and Supabase Storage).

WHAT IS HELD
    * THE GROUP IS A RULE, NOT A LIST OF FILES. The five tables the migration revokes are exactly the document tables
      `tests/_sensitive_tables.py` names, less `entity_documents`, which migration 538 closed to the signed-in role already. That part
      needs no database.
    * NOTHING IS LEFT TO A SIGNED-IN ROLE ON THE TABLES. `authenticated` and `anon` hold no privilege on any of them, effective
      (through PUBLIC, through another role, or on a column), and a PostgREST-shaped call as either is refused by the database on
      each of SELECT, INSERT, UPDATE and DELETE. The service role keeps what the API needs.
    * NOTHING IS LEFT TO A SIGNED-IN ROLE IN STORAGE. After the migration `storage.objects` carries no policy that does not ask for the
      service role, a signed-in Partner who could read, store and remove an object before the migration finds no object and stores
      none, and the service role's own policies are exactly the ones they were.
    * THE ROLLBACK IS EXACT: it gives back what the earlier migrations granted on the tables and re-creates the object policies with
      the very text they had (compared to the catalogue of a database built from the migrations), and the migration can be applied
      again afterwards and twice in a row.
    * THE POLICIES OF THE TABLES STAY (the second lock): apply and rollback leave every row policy of the five tables byte for byte.
    * THE CLOSING CHECK IS A CHECK: a privilege another role handed to `authenticated` survives a REVOKE by the owner and the
      migration refuses (rolls back) rather than report a lockdown it did not make; so does a service role left without a privilege
      and an object policy that does not ask for the service role, and a refused migration drops no policy.

Runs only when HARNESS_PG is set + psql on PATH; the group rule needs neither and runs in the mock-mode job.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from tests._sensitive_tables import DOCUMENT_TABLES
from tests._signed_in_postgrest import SignedInDb, SignedInError

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_STEM = "551_a_signed_in_session_reads_and_writes_none_of_the_document_tables_and_opens_no_stored_file"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

_NEEDS_PG = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the document revoke proof requires HARNESS_PG + psql",
)

AUTH_ID = "55101000-0000-0000-0000-00000000000a"
FIRM = "55101000-0000-0000-0000-0000000000f1"
CLIENT = "55101000-0000-0000-0000-0000000000c1"
USER = "55101000-0000-0000-0000-0000000000b1"
#: Closed to the signed-in role by migration 538 (nothing reads or writes it), so not this migration's.
ALREADY_CLOSED = {"entity_documents"}
SIGNED_IN_OBJECT_POLICIES = {
    "documents_storage_select", "documents_storage_insert", "documents_storage_delete",
    "year_end_exports_storage_select", "year_end_exports_storage_insert",
}


def _array_in(path: Path) -> set[str]:
    sql = re.sub(r"--[^\n]*", "", path.read_text())
    body = re.search(r"(?:tables text\[\] := ARRAY\[|FOREACH t IN ARRAY ARRAY\[)(.*?)\]", sql, re.S).group(1)
    return set(re.findall(r"'([a-z_]+)'", body))


def _group() -> set[str]:
    return set(DOCUMENT_TABLES) - ALREADY_CLOSED


# ── no database ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_migration_revokes_exactly_the_document_group_and_the_rollback_restores_exactly_it():
    group = _group()
    assert _array_in(MIGRATION) == group, (sorted(group ^ _array_in(MIGRATION)))
    assert _array_in(ROLLBACK) == group, (sorted(group ^ _array_in(ROLLBACK)))
    assert len(group) == 5, "the header of the migration says five; change both together"


def test_the_one_table_left_out_is_closed_by_the_migration_that_says_so():
    sql = re.sub(r"--[^\n]*", "", (MIGRATIONS / "538_tables_no_signed_in_route_writes_are_closed_to_the_signed_in_role.sql").read_text())
    assert all(f"'{t}'" in sql for t in ALREADY_CLOSED)


def test_the_migration_names_the_object_policies_and_the_rollback_makes_the_same_ones_again():
    up, down = MIGRATION.read_text(), ROLLBACK.read_text()
    for policy in SIGNED_IN_OBJECT_POLICIES:
        assert f"'{policy}'" in up, policy
        assert f'CREATE POLICY "{policy}" ON storage.objects' in down, policy
    # the service role's own policies are not this migration's to touch
    assert not [p for p in re.findall(r"'([a-z_]+_storage_[a-z_]+)'", re.sub(r"--[^\n]*", "", up)) if "service_role" in p]


# ── a database ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _query(dsn: str, sql: str):
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line for line in r.stdout.splitlines() if line.strip()]


def _apply_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "--single-transaction", "-f", str(path)],
                          capture_output=True, text=True)


def _privileges(dsn: str, role: str, relations: list[str]) -> dict[str, list[str]]:
    names = ", ".join(f"'{r}'" for r in relations)
    rows = _query(dsn, f"""
        SELECT r.rel || '|' || coalesce(string_agg(v.verb, ',' ORDER BY v.verb) FILTER (WHERE
            has_table_privilege('{role}', 'public.' || r.rel, v.verb)
            OR (v.verb IN ('SELECT', 'INSERT', 'UPDATE') AND has_any_column_privilege('{role}', 'public.' || r.rel, v.verb))), '')
        FROM unnest(ARRAY[{names}]) AS r(rel)
        CROSS JOIN unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE']) AS v(verb)
        GROUP BY r.rel ORDER BY r.rel""")
    return {line.split("|")[0]: [v for v in line.split("|")[1].split(",") if v] for line in rows}


def _object_policies(dsn: str) -> dict[str, str]:
    """{policy name: its command, roles and expressions, whitespace folded} for `storage.objects`."""
    rows = _query(dsn, """
        SELECT policyname || '|' || cmd || '|' || roles::text || '|' || coalesce(qual, '') || '|' || coalesce(with_check, '')
        FROM pg_policies WHERE schemaname = 'storage' AND tablename = 'objects' ORDER BY policyname""")
    return {r.split("|", 1)[0]: " ".join(r.split()) for r in rows}


#: What hosted Supabase has and the compat bootstrap does not (the access matrix applies the same): row security on for
#: `storage.objects` and the privileges its defaults hand `anon` and `authenticated`. The POLICIES decide, which is what is measured.
_STORAGE_SQL = """
ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;
GRANT ALL ON storage.objects TO anon, authenticated;
INSERT INTO storage.buckets (id, name, public) VALUES ('Documents', 'Documents', false), ('year-end-exports', 'year-end-exports', false)
  ON CONFLICT DO NOTHING;
"""


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e551_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        seeded = _psql(d, f"""
            {_STORAGE_SQL}
            INSERT INTO auth.users (id, email) VALUES ('{AUTH_ID}', 'p@t.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                 VALUES ('{USER}', '{FIRM}', '{AUTH_ID}', 'p@t.in', 'P', 'Partner', true);
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}', '{FIRM}', 'C', 'Proprietorship');
            INSERT INTO storage.objects (id, bucket_id, name)
                 VALUES (gen_random_uuid(), 'Documents', '{FIRM}/{CLIENT}/vault/seed.pdf'),
                        (gen_random_uuid(), 'year-end-exports', '{FIRM}/{CLIENT}/2025-26/pack.pdf');
        """)
        assert seeded.returncode == 0, seeded.stderr
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _as_partner(dsn: str, sql: str) -> subprocess.CompletedProcess:
    claims = f'{{"sub": "{AUTH_ID}", "role": "authenticated"}}'
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c",
                           f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}"], capture_output=True, text=True)


@_NEEDS_PG
def test_the_group_exists_in_a_migrated_database_exactly_as_the_rule_says(dsn):
    present = set(_query(dsn, "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'p') "
                              "AND relname = ANY(ARRAY[" + ", ".join(f"'{t}'" for t in sorted(DOCUMENT_TABLES)) + "])"))
    assert present == set(DOCUMENT_TABLES), sorted(present ^ set(DOCUMENT_TABLES))


@_NEEDS_PG
@pytest.mark.parametrize("role", ["authenticated", "anon"])
def test_no_signed_in_role_holds_any_privilege_on_a_document_table(dsn, role):
    held = {rel: verbs for rel, verbs in _privileges(dsn, role, sorted(DOCUMENT_TABLES)).items() if verbs}
    assert held == {}, f"{role} still holds: {held}"


@_NEEDS_PG
def test_the_service_role_keeps_what_the_api_needs(dsn):
    held = _privileges(dsn, "service_role", sorted(_group()))
    for table in _group():
        assert {"SELECT", "INSERT", "UPDATE", "DELETE"} <= set(held[table]), (table, held[table])
    server = SignedInDb(dsn, role="service_role")
    for table in sorted(_group()):
        assert isinstance(server.table(table).select("*").limit(1).execute().data, list), table


@_NEEDS_PG
@pytest.mark.parametrize("role", ["authenticated", "anon"])
def test_a_postgrest_shaped_call_as_a_signed_in_role_is_refused_on_every_verb(dsn, role):
    db = SignedInDb(dsn, role=role, auth_user_id=AUTH_ID if role == "authenticated" else None)
    refused = []
    for table in sorted(_group()):
        calls = {"select": lambda t=table: db.table(t).select("*").limit(1).execute(),
                 "insert": lambda t=table: db.table(t).insert({"id": str(uuid.uuid4())}).execute(),
                 "update": lambda t=table: db.table(t).update({"id": str(uuid.uuid4())}).eq("id", str(uuid.uuid4())).execute(),
                 "delete": lambda t=table: db.table(t).delete().eq("id", str(uuid.uuid4())).execute()}
        for verb, call in calls.items():
            with pytest.raises(SignedInError) as caught:
                call()
            if not re.search(r"permission denied for (table|view) [a-z_]+", caught.value.message):
                refused.append((table, verb, caught.value.message[:120]))
    assert refused == [], refused


def _policies_of_the_tables(dsn: str) -> list[str]:
    names = ", ".join(f"'{t}'" for t in sorted(_group()))
    return _query(dsn, f"""
        SELECT c.relname || '|' || p.polname || '|' || p.polcmd::text || '|' || p.polpermissive::text || '|'
               || regexp_replace(coalesce(pg_get_expr(p.polqual, p.polrelid), ''), '\\s+', ' ', 'g') || '|'
               || regexp_replace(coalesce(pg_get_expr(p.polwithcheck, p.polrelid), ''), '\\s+', ' ', 'g')
        FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid WHERE c.relname IN ({names}) ORDER BY 1""")


@_NEEDS_PG
def test_apply_and_rollback_leave_every_row_policy_of_the_tables_as_it_was(dsn):
    before = _policies_of_the_tables(dsn)
    assert len(before) >= 20, "the document tables lost their row policies: the second lock is gone"
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    assert _policies_of_the_tables(dsn) == before
    assert _apply_file(dsn, MIGRATION).returncode == 0
    assert _policies_of_the_tables(dsn) == before
    assert {r.split("|")[0] for r in before} == _group(), "every table keeps at least one policy"


@_NEEDS_PG
def test_no_policy_or_view_of_another_table_reads_a_document_table(dsn):
    names = ", ".join(f"'{t}'" for t in sorted(DOCUMENT_TABLES))
    rows = _query(dsn, f"""
        SELECT 'policy ' || pc.relname || '.' || p.polname || ' reads ' || s.relname
        FROM pg_depend d JOIN pg_policy p ON d.classid = 'pg_policy'::regclass AND d.objid = p.oid
        JOIN pg_class s ON s.oid = d.refobjid AND s.relnamespace = 'public'::regnamespace AND s.relname IN ({names})
        JOIN pg_class pc ON pc.oid = p.polrelid AND pc.relname NOT IN ({names})
        UNION ALL
        SELECT 'view ' || vc.relname || ' reads ' || s.relname
        FROM pg_depend d JOIN pg_rewrite rw ON d.classid = 'pg_rewrite'::regclass AND d.objid = rw.oid
        JOIN pg_class vc ON vc.oid = rw.ev_class AND vc.relkind IN ('v', 'm') AND vc.relname NOT IN ({names})
        JOIN pg_class s ON s.oid = d.refobjid AND s.relnamespace = 'public'::regnamespace AND s.relname IN ({names})""")
    assert rows == [], rows


# ── Storage ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
@_NEEDS_PG
def test_a_signed_in_partner_reads_stores_and_removes_in_storage_before_the_migration_and_not_after(dsn):
    """The policies are the lock, so the premise is measured: with the rollback applied (the policies back) a Partner of the firm
    sees both seeded objects and can store one; after the migration the same Partner sees none and the same insert is refused."""
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    seen = _as_partner(dsn, "SELECT count(*) FROM storage.objects;")
    assert seen.returncode == 0 and seen.stdout.strip().splitlines()[-1] == "2", (seen.stdout, seen.stderr)
    stored = _as_partner(dsn, f"INSERT INTO storage.objects (bucket_id, name) VALUES ('Documents', '{FIRM}/{CLIENT}/vault/new.pdf');")
    assert stored.returncode == 0, stored.stderr

    assert _apply_file(dsn, MIGRATION).returncode == 0
    after = _as_partner(dsn, "SELECT count(*) FROM storage.objects;")
    assert after.returncode == 0 and after.stdout.strip().splitlines()[-1] == "0", (after.stdout, after.stderr)
    refused = _as_partner(dsn, f"INSERT INTO storage.objects (bucket_id, name) VALUES ('Documents', '{FIRM}/{CLIENT}/vault/again.pdf');")
    assert refused.returncode != 0 and "row-level security" in refused.stderr, (refused.stdout, refused.stderr)
    gone = _as_partner(dsn, "DELETE FROM storage.objects WHERE bucket_id = 'Documents' RETURNING 1;")
    assert gone.returncode == 0 and gone.stdout.strip().splitlines()[-1:] != ["1"], "a signed-in Partner removed an object"
    # and nothing was lost: the objects are all still there for the server
    assert _query(dsn, "SELECT count(*) FROM storage.objects;") == ["3"]


@_NEEDS_PG
def test_after_the_migration_every_policy_left_on_storage_asks_for_the_service_role_and_they_are_the_ones_there_were(dsn):
    # (the template database is built from every migration in the directory, 551 included, so the policies are put back first)
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    before = _object_policies(dsn)
    assert SIGNED_IN_OBJECT_POLICIES <= set(before), "the premise: there are signed-in policies to drop"
    service_before = {n: v for n, v in before.items() if n not in SIGNED_IN_OBJECT_POLICIES}
    assert service_before, "a database built from the migrations has service-role object policies (204, 426)"
    assert _apply_file(dsn, MIGRATION).returncode == 0
    after = _object_policies(dsn)
    assert after == service_before
    assert all("service_role" in v for v in after.values()), after


@_NEEDS_PG
def test_the_rollback_makes_the_object_policies_again_exactly_as_migration_469_made_them(dsn):
    """The reference is not the rollback's own output: it is the catalogue after migration 469's file is applied to a database
    from which the policies were dropped, so a typing slip in the rollback is a difference here."""
    assert _apply_file(dsn, MIGRATION).returncode == 0
    assert set(_object_policies(dsn)).isdisjoint(SIGNED_IN_OBJECT_POLICIES)
    m469 = MIGRATIONS / "469_a_stored_file_opens_only_for_the_staff_assigned_to_its_client.sql"
    done = _apply_file(dsn, m469)
    assert done.returncode == 0, done.stderr
    as_469 = _object_policies(dsn)
    assert SIGNED_IN_OBJECT_POLICIES <= set(as_469), "the premise: 469 makes the signed-in policies"
    assert _apply_file(dsn, MIGRATION).returncode == 0
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    assert _object_policies(dsn) == as_469


@_NEEDS_PG
def test_the_migration_refuses_a_policy_on_storage_that_does_not_ask_for_the_service_role_and_drops_nothing(dsn):
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    assert _psql(dsn, "CREATE POLICY rogue_documents_read ON storage.objects FOR SELECT USING (bucket_id = 'Documents')").returncode == 0
    before = _object_policies(dsn)
    refused = _apply_file(dsn, MIGRATION)
    assert refused.returncode != 0 and "rogue_documents_read on storage.objects does not ask for the service role" in refused.stderr, \
        refused.stderr
    assert _object_policies(dsn) == before, "a refused migration dropped a policy"
    assert "SELECT" in _privileges(dsn, "authenticated", ["documents"])["documents"], "a refused migration revoked a privilege"


@_NEEDS_PG
def test_the_migration_refuses_a_policy_that_names_the_service_role_beside_an_or(dsn):
    """`... OR auth.role() = 'service_role'` mentions the service role and still admits everyone its other limb admits, so a
    substring test for the role is not a test that the policy lets in the service role and nobody else."""
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    assert _psql(dsn, "CREATE POLICY rogue_either ON storage.objects FOR SELECT "
                      "USING (bucket_id = 'Documents' OR auth.role() = 'service_role')").returncode == 0
    refused = _apply_file(dsn, MIGRATION)
    assert refused.returncode != 0 and "rogue_either on storage.objects does not ask for the service role and nobody else" in refused.stderr, \
        refused.stderr
    assert SIGNED_IN_OBJECT_POLICIES <= set(_object_policies(dsn)), "a refused migration dropped a policy"


@_NEEDS_PG
def test_the_migration_refuses_to_close_storage_where_row_security_is_off(dsn):
    """With the signed-in policies gone, row security is what says nobody: a table with it OFF and no policy is open to every role
    that holds a privilege on it, and the platform grants `authenticated` one. The migration refuses rather than report a lockdown
    it did not make, and drops nothing."""
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    assert _psql(dsn, "ALTER TABLE storage.objects DISABLE ROW LEVEL SECURITY").returncode == 0
    refused = _apply_file(dsn, MIGRATION)
    assert refused.returncode != 0 and "row security is off for storage.objects" in refused.stderr, refused.stderr
    assert SIGNED_IN_OBJECT_POLICIES <= set(_object_policies(dsn)), "a refused migration dropped a policy"


# ── the rollback and the closing check ───────────────────────────────────────────────────────────────────────────────────────────
@_NEEDS_PG
def test_the_rollback_gives_back_what_the_earlier_migrations_granted_and_nothing_more(dsn):
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    assert _privileges(dsn, "authenticated", sorted(_group())) == {t: ["DELETE", "INSERT", "SELECT", "UPDATE"] for t in _group()}
    assert _privileges(dsn, "anon", sorted(_group())) == {t: [] for t in _group()}
    for _ in range(2):
        again = _apply_file(dsn, MIGRATION)
        assert again.returncode == 0, again.stderr
    assert {r: v for r, v in _privileges(dsn, "authenticated", sorted(DOCUMENT_TABLES)).items() if v} == {}


@_NEEDS_PG
def test_the_closing_check_refuses_a_privilege_a_revoke_by_the_owner_cannot_take(dsn):
    """A privilege that another role handed to `authenticated` (it holds the privilege WITH GRANT OPTION) survives the owner's
    REVOKE, and the closing check, which asks the EFFECTIVE privilege, refuses the whole migration. (Membership of another role
    does not do it here: the signed-in roles are NOINHERIT, as the hosting platform makes them.)"""
    admin_dsn = f"{_ADMIN.strip()} dbname=postgres"
    role = f"g551_{uuid.uuid4().hex[:8]}"
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    try:
        assert _psql(admin_dsn, f"CREATE ROLE {role} NOLOGIN").returncode == 0
        done = _psql(dsn, f"GRANT SELECT ON public.documents TO {role} WITH GRANT OPTION; SET ROLE {role}; "
                          f"GRANT SELECT ON public.documents TO authenticated; RESET ROLE")
        assert done.returncode == 0, done.stderr
        refused = _apply_file(dsn, MIGRATION)
        assert refused.returncode != 0 and "authenticated still holds SELECT on documents" in refused.stderr, refused.stderr
        assert "SELECT" in _privileges(dsn, "authenticated", ["client_documents"])["client_documents"], "the whole migration must roll back"
        assert SIGNED_IN_OBJECT_POLICIES <= set(_object_policies(dsn)), "the whole migration must roll back"
    finally:
        _psql(dsn, f"REVOKE ALL ON public.documents FROM {role} CASCADE")
        _psql(admin_dsn, f"DROP ROLE IF EXISTS {role}")


@_NEEDS_PG
def test_what_the_hosting_platform_hands_out_by_default_and_a_grant_to_public_are_taken_too(dsn):
    """A database built from the migrations alone holds only the four verbs the earlier migrations granted. The hosting platform's
    default privileges also give `anon` and `authenticated` TRUNCATE (and REFERENCES and TRIGGER) on every table, and a table can be
    granted to PUBLIC; production held the first. This puts all of it there (the rollback first, then every privilege the platform
    adds, then SELECT to PUBLIC) and applies the migration: nothing a row can be read or changed or removed through is left, and
    REFERENCES and TRIGGER, which are not privileges on rows, are left as they were."""
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    tables = ", ".join(f"public.{t}" for t in sorted(_group()))
    done = _psql(dsn, f"GRANT ALL ON {tables} TO authenticated, anon; GRANT SELECT ON {tables} TO PUBLIC;")
    assert done.returncode == 0, done.stderr
    applied = _apply_file(dsn, MIGRATION)
    assert applied.returncode == 0, applied.stderr
    for role in ("authenticated", "anon"):
        held = {rel: verbs for rel, verbs in _privileges(dsn, role, sorted(_group())).items() if verbs}
        assert held == {}, f"{role} still holds: {held}"
        assert all(_query(dsn, f"SELECT has_table_privilege('{role}', 'public.{t}', 'REFERENCES') AND has_table_privilege('{role}', 'public.{t}', 'TRIGGER')")
                   == ["t"] for t in sorted(_group())), "REFERENCES and TRIGGER are privileges on no row and are left as they were"


@_NEEDS_PG
def test_the_closing_check_refuses_a_column_privilege_a_table_level_revoke_cannot_take(dsn):
    """The same, one level down: a column-level SELECT that another role handed to `authenticated` is not a table privilege and is
    not removed by the owner's table-level REVOKE, so only the column check sees it."""
    admin_dsn = f"{_ADMIN.strip()} dbname=postgres"
    role = f"c551_{uuid.uuid4().hex[:8]}"
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    try:
        assert _psql(admin_dsn, f"CREATE ROLE {role} NOLOGIN").returncode == 0
        done = _psql(dsn, f"GRANT SELECT (id) ON public.documents TO {role} WITH GRANT OPTION; SET ROLE {role}; "
                          f"GRANT SELECT (id) ON public.documents TO authenticated; RESET ROLE")
        assert done.returncode == 0, done.stderr
        refused = _apply_file(dsn, MIGRATION)
        assert refused.returncode != 0 and "authenticated still holds a column-level privilege on documents" in refused.stderr, refused.stderr
        assert SIGNED_IN_OBJECT_POLICIES <= set(_object_policies(dsn)), "the whole migration must roll back"
    finally:
        _psql(dsn, f"REVOKE ALL ON public.documents FROM {role} CASCADE")
        _psql(admin_dsn, f"DROP ROLE IF EXISTS {role}")


@_NEEDS_PG
def test_the_closing_check_refuses_a_service_role_left_without_a_privilege_the_api_needs(dsn):
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    assert _psql(dsn, "REVOKE UPDATE ON public.client_documents FROM service_role").returncode == 0
    refused = _apply_file(dsn, MIGRATION)
    assert refused.returncode != 0 and "service_role no longer holds UPDATE on client_documents" in refused.stderr, refused.stderr
