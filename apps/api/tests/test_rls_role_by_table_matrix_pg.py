"""Every actor against every table the browser reaches, observed and held to a reviewed file
(security_privacy-34).

WHY THIS EXISTS
    The browser reads and writes ~83 tables over PostgREST with the caller's own
    JWT, where `rbac()` never runs and row-level security is the only control.
    Every hole found there so far (payroll, slips, fx_rates, Storage, a suspended
    member's token) was found by READING policies. The suite had 139 real-
    Postgres modules before this one and 43 of them set JWT claims, each proving
    one table or one function; none tried every role against every table, so a
    table nobody thought to read stayed unproved. This does it for all of them
    and keeps the answer in a file whose diff is reviewable cell by cell.

THE RULE (and what it replaced)
    **The table list is `_frontend_select_parser.browser_tables`, the parser the
    column and assignment-scope checks already use, and the actors are the ten
    principals a request can be.** A hand list is what a new screen outgrows:
    add `.from("x")` to apps/web and `test_the_table_list_...` fails until the
    new row has been observed and reviewed. 83 tables the browser reaches (82
    `.from()` calls and `journal_lines`, reached only through an embed), 4 that
    DECIDE who reaches the rest (`user_client_assignments`, `user_permissions`,
    `client_firm_customer_links`) or already had an incident (`fx_rates`), and
    the two Storage buckets: 89 tables x 10 actors x 4 operations = 3,560 cells.

    Actors: Partner; Manager, assigned executive and Reviewer (each assigned to
    client A only); an Executive assigned to NOTHING; the portal client of A (a
    contact row AND `clients.portal_user_id`); an employee of A; the Partner of
    ANOTHER firm; a SUSPENDED Partner (migration 468); anon.

HOW A CELL IS OBSERVED
    A throwaway copy of the migrated schema is stripped of everything that can
    make a probe fail for a reason that is not access (foreign keys, CHECK,
    UNIQUE and EXCLUDE constraints, non-key unique indexes, NOT NULL), seeded
    with one row per label per table (A and B are firm 1's clients, X firm 2's;
    a child row points at its parent's same-labelled row) and given a probe per
    (table, operation, label). One PL/pgSQL function then runs every probe as
    each actor (`request.jwt.claims` set, `SET LOCAL ROLE`), one savepoint per
    probe, always rolled back, and records the row count or the error.
    `x` no privilege, `-` nothing (RLS), otherwise the labels reached. Insert
    probes insert a COPY of a seeded row held in a scratch table, so the target
    table's own policy is all that stands between the statement and success.
    **`allowed` therefore means admitted by privileges and policies, with
    integrity constraints out of the way: a Partner's DELETE of their own firm
    row is `allowed` here and would meet a foreign key in production.**
    A probe that fails for any other reason (a trigger's error, a privilege
    on another table) is INCONCLUSIVE and fails the run rather than being
    guessed, and `test_the_instrument_agrees_with_a_plain_session` re-asks
    sixteen cells the way every other test in this directory does.

THE FILE, AND WHAT IT IS ALLOWED TO SAY
    `fixtures/rls_expected_access.json` holds what the PRODUCT INTENDS. It was
    generated from observation (`RLS_MATRIX_REGENERATE=1`) and reviewed by
    grouping the 89 tables into 29 observed row patterns and judging each
    against five rules, then the cells that break one individually:
        R1 one firm never reaches another's rows;
        R2 a non-Partner reaches a client's rows only through an assignment
           (084), except where migration 079 makes a Manager firm-wide;
        R3 a write needs the tier core/permissions gives the resource, and a
           Reviewer writes nothing but the activity log and their own name;
        R4 a portal client and an employee reach their own rows, and an
           employee writes only their own unverified declaration (297);
        R5 anon and a suspended member reach nothing but reference data.
    `cardinal_violations` states them as code and `test_the_expectation_obeys_
    the_five_rules` holds the FILE to them without a database, so a hand edit
    that waives one fails in the mock-mode job too.

    **Where observation breaks a rule the cell is NOT baked in**: the file holds
    what is intended, `DEVIATION_CLASSES` holds what the database does instead
    and why, as an equality in both directions. A fix deletes its entry; a new
    gap, a looser or a TIGHTER cell, fails and names (actor, table, operation).
    12 cells over 4 tables in 3 classes today. Classes are closed by a
    migration, and each entry is deleted with its fix: `any-member-assigns-
    themselves` (any member of the firm could write `user_client_assignments`
    and assign themselves to any client; migration 478), in one migration (483)
    `executive-writes-manager-tier`, `cross-client-matches-have-no-client-scope`
    and `year-end-children-have-no-client-id`, and (484)
    `portal-contacts-are-not-scoped-for-staff`, and (485) the three payroll classes
    (`payroll-tier-not-in-rls`, `payroll-children-have-no-client-id`, `payroll-children-manager-delete`). The others await their own
    migration: merging one applies it to production, and the tier of each is
    decided by the API's own guard for the resource. The READ of the
    assignment rows stays firm-wide (`READABLE_BY_EVERY_MEMBER`): the API reads
    the caller's own rows under the caller's JWT. Where the intended tier is undocumented (what an
    Executive may write in `ai_insights`, `renewals` or the banking tables, and
    who may READ accounting, banking or year-end data below Executive), the
    observed value is recorded and nothing claims it is right.

BREAKING IT ON PURPOSE
    Sixteen holes this repository already closed once are put back in a copy of the
    world, thirteen of them by running the migration's own rollback file (468, 469,
    470, 478, 483, 484, 485, 487, 488, 489, 490, 495, 499): each must turn named cells red. `liveness-dropped-from-every-helper`
    is migration 468 reversed; dropping the check from `get_my_role` ALONE
    turns only two cells red (a suspended Partner writes `fx_rates`, whose
    policy asks the role and never the firm) because `get_my_firm_id` still
    answers NULL for them everywhere else.

DELIBERATELY NOT DONE
    Nothing moves a row to another tenant (an UPDATE that re-points firm_id or
    client_id is a fifth operation); `user_permissions` grants are never seeded,
    so the role decides every cell; a signed-out session (migration 468's other
    half) stays in its own test; the internal practice client's Partner-only
    policy is not probed (nobody is assigned to it); the 234 other base tables
    granted to `authenticated` (321 in all) that the browser does not reach are
    not covered, and a JWT can reach them as readily as the screens reach the
    others; and `supabase_storage_admin`, the role storage-api
    connects as, is covered by test_a_suspended_member_is_nobody_to_the_
    database_pg.py, not here. The anon grants on `storage.objects` are assumed
    to be hosted Supabase's defaults (ALL, with the policies deciding).

Runs only when HARNESS_PG is set + psql on PATH. The table list, the file and
the rules need neither, and run in the mock-mode job.
"""
from __future__ import annotations

import functools
import hashlib
import json
import re
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _frontend_select_parser import browser_tables  # noqa: E402

API_ROOT = Path(__file__).resolve().parents[1]
WEB = API_ROOT.parents[1] / "apps" / "web"
EXPECTED_PATH = Path(__file__).resolve().parent / "fixtures" / "rls_expected_access.json"
#: The seventeen payroll tables migration 499 revokes the signed-in write privilege on, as the row policies of 485/490 and the
#: triggers of 498 (the SECOND LOCK) decide them once the privilege (the first lock) is given back. It holds the cells
#: EXPECTED_PATH held for those tables before 499, so the policies stay measured although the main matrix now reads "no
#: privilege" in every write cell of them.
SECOND_LOCK_PATH = Path(__file__).resolve().parent / "fixtures" / "rls_expected_second_lock.json"
_M499_ROLLBACK = "499_a_signed_in_session_writes_none_of_the_payroll_tables_the_browser_never_writes_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

_NEEDS_PG = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not WEB.is_dir(),
    reason="the role-by-table matrix needs HARNESS_PG + psql + apps/web",
)
# The checks on the table list, the reviewed file and the rules read source and
# JSON only, so they are NOT behind the database skip: the mock-mode job runs
# them, and it is the one that sees a pull request that adds a screen.
_NEEDS_PG_SOURCE = pytest.mark.skipif(not WEB.is_dir(), reason="needs apps/web")

# ── who is asking ────────────────────────────────────────────────────────────
FIRM1 = "a1000000-0000-0000-0000-0000000000f1"
FIRM2 = "a2000000-0000-0000-0000-0000000000f2"
CLIENT_A = "c1000000-0000-0000-0000-00000000000a"   # firm 1
CLIENT_B = "c1000000-0000-0000-0000-00000000000b"   # firm 1
CLIENT_X = "c2000000-0000-0000-0000-00000000000c"   # firm 2

AUTH = {
    "partner":     "91000000-0000-0000-0000-000000000001",
    "manager":     "91000000-0000-0000-0000-000000000002",
    "exec_a":      "91000000-0000-0000-0000-000000000003",
    "exec_n":      "91000000-0000-0000-0000-000000000004",
    "reviewer":    "91000000-0000-0000-0000-000000000005",
    "suspended":   "91000000-0000-0000-0000-000000000006",
    "other":       "91000000-0000-0000-0000-000000000007",
    "portal_a":    "92000000-0000-0000-0000-00000000000a",
    "portal_b":    "92000000-0000-0000-0000-00000000000b",
    "portal_x":    "92000000-0000-0000-0000-00000000000c",
    "employee_a":  "93000000-0000-0000-0000-00000000000a",
}
USER_ID = {k: AUTH[k].replace("91", "b1", 1) for k in
           ("partner", "manager", "exec_a", "exec_n", "reviewer", "suspended", "other")}

#: (label, role, firm, is_active)
STAFF = [
    ("partner",   "Partner",   FIRM1, True),
    ("manager",   "Manager",   FIRM1, True),
    ("exec_a",    "Executive", FIRM1, True),
    ("exec_n",    "Executive", FIRM1, True),
    ("reviewer",  "Reviewer",  FIRM1, True),
    ("suspended", "Partner",   FIRM1, False),
    ("other",     "Partner",   FIRM2, True),
]
#: who is assigned to which client of firm 1. exec_n is assigned to NOTHING.
ASSIGNED_TO_A = ("manager", "exec_a", "reviewer", "suspended")

#: actor -> (auth id or None, Postgres role the request runs as)
ACTORS: dict[str, tuple[str | None, str]] = {
    "partner":      (AUTH["partner"], "authenticated"),
    "manager":      (AUTH["manager"], "authenticated"),
    "exec_assigned": (AUTH["exec_a"], "authenticated"),
    "exec_unassigned": (AUTH["exec_n"], "authenticated"),
    "reviewer":     (AUTH["reviewer"], "authenticated"),
    "portal_client": (AUTH["portal_a"], "authenticated"),
    "employee":     (AUTH["employee_a"], "authenticated"),
    "other_firm_partner": (AUTH["other"], "authenticated"),
    "suspended_partner": (AUTH["suspended"], "authenticated"),
    "anon":         (None, "anon"),
}
OPS = ("select", "insert", "update", "delete")

#: Tables the browser does not parse as read but that DECIDE who may read the
#: rest, or whose access has already had its own incident.
ALSO_COVERED = {
    "user_client_assignments": "what can_access_client() reads: a write here is a self-service assignment (478)",
    "user_permissions": "what my_permission() reads (migration 403): the per-person grid",
    "client_firm_customer_links": "what my_portal_customer_ids() reads: the portal principal's reach",
    "fx_rates": "migration 470 repaired its write policy; it has its own regression test",
    # The payroll tables the API reads and writes with the service role and the browser never touches (490): the
    # threat the matrix models is a direct call with a person's own JWT, whoever the application itself calls as.
    # The browser stopped reading this table (POST-B-024): the Compliance tab asks GET /api/compliance/engagement-status.
    "fee_engagements": "the practice's engagements and their fees, read by the API under billing:read (495)",
    "payroll_salary_revisions": "payroll (490): salary history, read and written only by the payroll router",
    "salary_structures": "payroll (490): a client's salary template",
    "payroll_perquisites": "payroll (490): an employee's perquisites",
    "payroll_loans": "payroll (490): an employee's loans",
    "payroll_loan_recoveries": "payroll (490): what a run recovered from a loan",
    "payroll_settlements": "payroll (490): a leaver's full and final settlement",
    "payroll_settlement_components": "payroll (490): the lines of a settlement",
    "payroll_one_time_earnings": "payroll (490): a month's one-off earnings",
    "bonus_disqualifications": "payroll (490): the employer's own bonus determination",
    "payroll_run_transitions": "payroll (490): the history of a run's status changes",
    "statutory_remittances": "payroll (490): PF, ESI and professional tax paid over",
    "epfo_ecr_filings": "payroll (490): the ECR filed for a month",
    "bonus_declarations": "payroll (490): the employer's own bonus determination for a year",
}

#: rows seeded per table: label -> (firm, client). Anything else is per table.
KEYS = {"A": (FIRM1, CLIENT_A), "B": (FIRM1, CLIENT_B), "X": (FIRM2, CLIENT_X)}
GLOBAL_TABLES = {"currencies", "fx_rates"}

#: The stored files. Migrations 005/204/426/469 scope `storage.objects` by the
#: path `{firm}/{client}/...`, so a bucket is one more table to the matrix, with
#: a row per label whose NAME carries the firm and client. The second path
#: segment is the one migration 469 made the policies ask.
STORAGE = {
    "storage/Documents": ("Documents", "vault"),
    "storage/year-end-exports": ("year-end-exports", "2025-26"),
}


def is_storage(table: str) -> bool:
    return table in STORAGE


def physical_name(table: str) -> str:
    return "objects" if is_storage(table) else table


def _uuid_of(*parts: str) -> str:
    return str(uuid.UUID(hashlib.md5(":".join(parts).encode()).hexdigest()))


def lit(s) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def qi(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-f", "-"]
    return subprocess.run(args, input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql, tuples=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-2000:])
    return r.stdout.strip()


# ── the table list ───────────────────────────────────────────────────────────
@functools.lru_cache(maxsize=1)
def _browser_tables() -> frozenset[str]:
    # three passes over ~800 files: once per process is enough
    return frozenset(browser_tables(WEB))


def matrix_tables() -> list[str]:
    """Every table the browser reaches (the parser's own answer), the few that
    decide who reaches the rest, and the two Storage buckets."""
    return sorted(_browser_tables() | set(ALSO_COVERED)) + sorted(STORAGE)


def public_tables(tables: list[str]) -> list[str]:
    return [t for t in tables if not is_storage(t)]


# ── catalogue ────────────────────────────────────────────────────────────────
_META_SQL = """
SELECT coalesce(json_object_agg(t.relname, json_build_object(
  'cols', (SELECT json_agg(json_build_object('name', a.attname,
                  'generated', (a.attgenerated <> '' OR a.attidentity = 'a'),
                  'type', format_type(a.atttypid, a.atttypmod)) ORDER BY a.attnum)
             FROM pg_attribute a WHERE a.attrelid = t.oid AND a.attnum > 0 AND NOT a.attisdropped),
  'pk', (SELECT json_agg(a.attname ORDER BY k.ord)
           FROM pg_index i
           CROSS JOIN LATERAL unnest(i.indkey::int2[]) WITH ORDINALITY k(attnum, ord)
           JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
          WHERE i.indrelid = t.oid AND i.indisprimary),
  'fks', (SELECT coalesce(json_agg(json_build_object(
              'cols', (SELECT json_agg(a.attname ORDER BY k.ord)
                         FROM unnest(con.conkey) WITH ORDINALITY k(attnum, ord)
                         JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum),
              'ref', rc.relname,
              'refcols', (SELECT json_agg(a.attname ORDER BY k.ord)
                            FROM unnest(con.confkey) WITH ORDINALITY k(attnum, ord)
                            JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.attnum))), '[]'::json)
            FROM pg_constraint con JOIN pg_class rc ON rc.oid = con.confrelid
           WHERE con.conrelid = t.oid AND con.contype = 'f'),
  'update_cols', (SELECT coalesce(json_agg(a.attname ORDER BY a.attnum), '[]'::json)
                    FROM pg_attribute a
                   WHERE a.attrelid = t.oid AND a.attnum > 0 AND NOT a.attisdropped
                     AND has_column_privilege('authenticated', t.oid, a.attnum, 'UPDATE'))
)), '{}'::json)
FROM pg_class t
WHERE t.relnamespace = 'public'::regnamespace AND t.relkind = 'r'
  AND t.relname = ANY(string_to_array({tables}, ','))
"""


def read_meta(dsn: str, tables: list[str]) -> dict:
    meta = json.loads(_ok(dsn, _META_SQL.replace("{tables}", lit(",".join(tables)))))
    missing = sorted(set(tables) - set(meta))
    if missing:
        raise RuntimeError(f"tables named by the frontend but absent from the schema: {missing}")
    return meta


_PREPARE_SQL = """
DO $$
DECLARE
  r record;
  tbls text[] := string_to_array({tables}, ',');
BEGIN
  -- Everything that can make a probe fail for a reason that is not access:
  -- FK, CHECK, UNIQUE and EXCLUDE constraints, non-key unique indexes, NOT NULL.
  FOR r IN SELECT c.relname, con.conname FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid
            WHERE c.relnamespace = 'public'::regnamespace AND c.relname = ANY(tbls)
              AND con.contype IN ('f', 'c', 'u', 'x')
  LOOP
    EXECUTE format('ALTER TABLE public.%I DROP CONSTRAINT IF EXISTS %I CASCADE', r.relname, r.conname);
  END LOOP;
  FOR r IN SELECT i.indexrelid::regclass::text AS idx
             FROM pg_index i JOIN pg_class c ON c.oid = i.indrelid
            WHERE c.relnamespace = 'public'::regnamespace AND c.relname = ANY(tbls)
              AND i.indisunique AND NOT i.indisprimary
  LOOP
    EXECUTE 'DROP INDEX IF EXISTS ' || r.idx;
  END LOOP;
  FOR r IN SELECT c.relname, a.attname
             FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
            WHERE c.relnamespace = 'public'::regnamespace AND c.relname = ANY(tbls)
              AND a.attnum > 0 AND NOT a.attisdropped AND a.attnotnull
              AND a.attidentity = '' AND a.attgenerated = ''
              AND NOT EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.oid
                                 AND i.indisprimary AND a.attnum = ANY(i.indkey::int2[]))
  LOOP
    EXECUTE format('ALTER TABLE public.%I ALTER COLUMN %I DROP NOT NULL', r.relname, r.attname);
  END LOOP;
  -- Migration 498's two triggers refuse a signed-in write to a finalized or paid payroll run and its payslips. They
  -- answer BEFORE row security does, and this world seeds those runs as finalized, so every write cell on the two
  -- tables would read as the trigger's refusal and no longer say what row security decides. This instrument
  -- measures row security; the freeze is measured by test_498_a_released_payroll_run_is_not_written_by_a_signed_in_
  -- session_pg.py. Disabled by name, and only where they exist, so the world still builds from an older template.
  IF EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'a_released_payroll_run_is_not_written_by_a_session'
                AND tgrelid = 'public.payroll_runs'::regclass) THEN
    ALTER TABLE public.payroll_runs DISABLE TRIGGER a_released_payroll_run_is_not_written_by_a_session;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'a_released_runs_payslips_are_not_written_by_a_session'
                AND tgrelid = 'public.payroll_slips'::regclass) THEN
    ALTER TABLE public.payroll_slips DISABLE TRIGGER a_released_runs_payslips_are_not_written_by_a_session;
  END IF;
END $$;
"""

#: What hosted Supabase has and the compat bootstrap does not: row-level
#: security switched on for `storage.objects`, and the privileges its default
#: grants hand `anon` and `authenticated` (ALL on the storage tables; the
#: POLICIES decide). `supabase_storage_admin` is the role storage-api connects
#: as; migration 204's header is the record of what happens without its grants.
#: The buckets are created if no migration did.
_STORAGE_SQL = """
ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;
GRANT USAGE ON SCHEMA storage, auth, public TO supabase_storage_admin;
GRANT ALL ON storage.objects TO anon, authenticated, supabase_storage_admin;
GRANT SELECT ON storage.buckets TO anon, authenticated, supabase_storage_admin;
INSERT INTO storage.buckets (id, name, public) VALUES
  ('Documents', 'Documents', false), ('year-end-exports', 'year-end-exports', false)
  ON CONFLICT DO NOTHING;
"""

_SCHEMA_SQL = """
CREATE SCHEMA rlsm;
CREATE TABLE rlsm.seed_index (tbl text NOT NULL, label text NOT NULL, key text NOT NULL, pk text NOT NULL);
CREATE TABLE rlsm.probe (id serial PRIMARY KEY, tbl text NOT NULL, op text NOT NULL, label text NOT NULL, sql text NOT NULL);
CREATE TABLE rlsm.obs (actor text NOT NULL, probe_id int NOT NULL, outcome text NOT NULL);

CREATE FUNCTION rlsm.run(p_actor text, p_claims text, p_role text, p_tables text[] DEFAULT NULL) RETURNS void
LANGUAGE plpgsql AS $fn$
DECLARE r record; n bigint; outcome text;
BEGIN
  FOR r IN SELECT * FROM rlsm.probe WHERE p_tables IS NULL OR tbl = ANY(p_tables) ORDER BY id LOOP
    BEGIN
      PERFORM set_config('request.jwt.claims', p_claims, true);
      EXECUTE format('SET LOCAL ROLE %I', p_role);
      EXECUTE r.sql;
      GET DIAGNOSTICS n = ROW_COUNT;
      RAISE EXCEPTION USING ERRCODE = 'RLSMX', MESSAGE = n::text;
    EXCEPTION WHEN OTHERS THEN
      IF SQLSTATE = 'RLSMX' THEN
        outcome := 'rows:' || SQLERRM;
      ELSE
        outcome := 'err:' || SQLSTATE || ':' || replace(SQLERRM, E'\\n', ' ');
      END IF;
    END;
    INSERT INTO rlsm.obs (actor, probe_id, outcome) VALUES (p_actor, r.id, outcome);
  END LOOP;
END $fn$;
"""

# ── what is seeded ───────────────────────────────────────────────────────────
#: Columns a policy reads that no foreign key can supply. Everything else a
#: seeded row holds is its primary key, its firm, its client, and the
#: same-labelled row of every table it points at.
SEED_VALUES: dict[tuple[str, str], dict] = {
    # the portal principal's two doors (clients.portal_user_id and an active
    # contact row) and the employee principal's (an enabled portal login)
    ("clients", "A"): {"portal_user_id": AUTH["portal_a"]},
    ("clients", "B"): {"portal_user_id": AUTH["portal_b"]},
    ("clients", "X"): {"portal_user_id": AUTH["portal_x"]},
    ("client_portal_users", "A"): {"auth_user_id": AUTH["portal_a"], "status": "active", "email": "a@x.in"},
    ("client_portal_users", "B"): {"auth_user_id": AUTH["portal_b"], "status": "active", "email": "b@x.in"},
    ("client_portal_users", "X"): {"auth_user_id": AUTH["portal_x"], "status": "active", "email": "x@x.in"},
    ("payroll_employees", "A"): {"auth_user_id": AUTH["employee_a"], "portal_enabled": True},
    ("payroll_employees", "B"): {"portal_enabled": True},
    ("payroll_employees", "X"): {"portal_enabled": True},
    # an employee reads a run only once it is released
    ("payroll_runs", "A"): {"status": "finalized"},
    ("payroll_runs", "B"): {"status": "finalized"},
    ("payroll_runs", "X"): {"status": "finalized"},
    # fx_rates' policies read `source`
    ("fx_rates", "A"): {"source": "manual"},
    # a match names TWO clients and no foreign key says which: both are the row's own
    ("cross_client_matches", "A"): {"client_id_a": CLIENT_A, "client_id_b": CLIENT_A},
    ("cross_client_matches", "B"): {"client_id_a": CLIENT_B, "client_id_b": CLIENT_B},
    ("cross_client_matches", "X"): {"client_id_a": CLIENT_X, "client_id_b": CLIENT_X},
}

#: Every table's labelled rows, in the order a cell prints them.
SPECIAL_LABELS = {
    "firms": ["F1", "F2"],
    "users": [s[0] for s in STAFF],
}
FOREIGN_LABELS = {"firms": {"F2"}, "users": {"other"}}


def labels_of(table: str) -> list[str]:
    if table in SPECIAL_LABELS:
        return SPECIAL_LABELS[table]
    if table in GLOBAL_TABLES:
        return ["G"]
    return ["A", "B", "X"]


def foreign_labels_of(table: str) -> set[str]:
    return FOREIGN_LABELS.get(table, {"X"} if table not in GLOBAL_TABLES else set())


def _key_of(label: str) -> str:
    return {"F1": "A", "F2": "X", "G": "A"}.get(label, label)


def seed_pk(table: str, label: str) -> str:
    if table == "firms":
        return {"F1": FIRM1, "F2": FIRM2}[label]
    if table == "clients":
        return {"A": CLIENT_A, "B": CLIENT_B, "X": CLIENT_X}[label]
    if table == "users":
        return USER_ID[label]
    if table == "currencies":
        return "ZZG"
    return _uuid_of(table, label)


def _parent_pk(table: str, meta: dict, ref: str, refcol: str, key: str) -> str | None:
    """The primary key of the row `ref` holds for this label, when this table
    points at it. A foreign key to `users` or `currencies` is left empty: the
    first would name a person, the second is reference data, and neither is read
    by any policy."""
    if ref in ("users", "currencies") or ref == table or ref not in meta:
        return None
    if ref == "firms":
        return KEYS[key][0]
    if ref == "clients":
        return KEYS[key][1]
    if meta[ref]["pk"] != [refcol]:
        return None
    return seed_pk(ref, key if ref not in GLOBAL_TABLES else "A")


def seed_values(table: str, label: str, meta: dict) -> dict:
    """Column -> value for the row `label` of `table`."""
    m = meta[table]
    key = _key_of(label)
    firm, client = KEYS[key]
    vals: dict = {}
    for col in m["pk"]:
        vals[col] = seed_pk(table, label)
    names = {c["name"] for c in m["cols"]}
    if "firm_id" in names and table != "firms":
        vals["firm_id"] = firm
    if "client_id" in names and table != "clients" and table not in GLOBAL_TABLES:
        vals["client_id"] = client
    for fk in m["fks"]:
        for col, refcol in zip(fk["cols"], fk["refcols"], strict=True):
            if col in vals:
                continue
            p = _parent_pk(table, meta, fk["ref"], refcol, key)
            if p is not None:
                vals[col] = p
    vals.update(SEED_VALUES.get((table, key), {}))
    if table == "clients":
        vals.setdefault("client_name", f"Client {label}")
    return vals


def storage_name(table: str, label: str, leaf: str | None = None) -> str:
    firm, client = KEYS[label]
    _bucket, folder = STORAGE[table]
    return f"{firm}/{client}/{folder}/{leaf or label}.pdf"


def _insert_stmt(table: str, vals: dict) -> str:
    cols = ", ".join(qi(c) for c in vals)
    vs = ", ".join("NULL" if v is None else ("true" if v is True else "false" if v is False else lit(v))
                   for v in vals.values())
    return f"INSERT INTO public.{qi(table)} ({cols}) VALUES ({vs});"


def seed_sql(meta: dict, tables: list[str]) -> str:
    """The identity graph (people, assignments) plus one row per label per table."""
    out = ["SET session_replication_role = replica;"]
    # people
    for label, auth in AUTH.items():
        out.append(f"INSERT INTO auth.users (id, email) VALUES ({lit(auth)}, {lit(label + '@rlsm.test')});")
    out.append(_insert_stmt("firms", {"id": FIRM1, "name": "Firm One", "email": "f1@rlsm.test"}))
    out.append(_insert_stmt("firms", {"id": FIRM2, "name": "Firm Two", "email": "f2@rlsm.test"}))
    # the labelled rows of every table, then the identity rows of `users`
    index: list[tuple[str, str, str, str]] = []
    for t in tables:
        if is_storage(t):
            bucket, folder = STORAGE[t]
            for label in KEYS:
                oid = _uuid_of(t, label)
                out.append(
                    "INSERT INTO storage.objects (id, bucket_id, name) VALUES "
                    f"({lit(oid)}, {lit(bucket)}, {lit(storage_name(t, label))});")
                index.append((t, label, label, oid))
            continue
        for label in labels_of(t):
            if t == "users":
                continue
            if t == "firms":
                index.append((t, label, _key_of(label), seed_pk(t, label)))
                continue
            vals = seed_values(t, label, meta)
            out.append(_insert_stmt(t, vals))
            index.append((t, label, _key_of(label), seed_pk(t, label)))
    for label, role, firm, active in STAFF:
        out.append(_insert_stmt("users", {
            "id": USER_ID[label], "firm_id": firm, "auth_user_id": AUTH[label],
            "email": f"{label}@rlsm.test", "full_name": label, "role": role,
            "is_active": active, "status": "active"}))
        index.append(("users", label, "A" if firm == FIRM1 else "X", USER_ID[label]))
    for label in ASSIGNED_TO_A:
        out.append(_insert_stmt("user_client_assignments", {
            "id": _uuid_of("assign", label), "firm_id": FIRM1,
            "user_id": USER_ID[label], "client_id": CLIENT_A}))
    out.append("SET session_replication_role = DEFAULT;")
    out.append("INSERT INTO rlsm.seed_index (tbl, label, key, pk) VALUES\n  " + ",\n  ".join(
        f"({lit(t)}, {lit(l)}, {lit(k)}, {lit(p)})" for t, l, k, p in index) + ";")
    return "\n".join(out)


# ── the probes ───────────────────────────────────────────────────────────────
def _pk_expr(pk: list[str], alias: str = "") -> str:
    pre = f"{alias}." if alias else ""
    cols = [f"{pre}{qi(c)}::text" for c in pk]
    return cols[0] if len(cols) == 1 else "concat_ws('|', " + ", ".join(cols) + ")"


def _fresh_pk(table: str, m: dict) -> str | None:
    """An expression for a primary key no seeded row holds, for the insert
    probe's copy of a seeded row. None where the key is not a single column of
    a type that can be minted."""
    if len(m["pk"]) != 1:
        return None
    typ = next(c["type"] for c in m["cols"] if c["name"] == m["pk"][0])
    if typ == "uuid":
        return "gen_random_uuid()"
    if typ.startswith("character(") or typ.startswith("char("):
        return "upper(substr(md5(random()::text), 1, 3))"
    if typ == "text" or typ.startswith("character varying"):
        return "md5(random()::text)"
    return None


def probe_sql(meta: dict, tables: list[str], index: list[tuple[str, str, str, str]]) -> tuple[str, list[tuple]]:
    """(the script that creates the copies, the probe rows).

    select/update/delete each address ONE seeded row by its key, so the row
    count of the statement says whether that row was visible, changeable or
    removable to the caller. Insert addresses a COPY of a seeded row (under a
    fresh key) held in a scratch table the caller can read, so that the only
    thing between the statement and success is the target table's own policy:
    the copy is taken from rlsm, never from the table under test."""
    script: list[str] = []
    probes: list[tuple] = []
    for i, t in enumerate(tables):
        if is_storage(t):
            bucket, _folder = STORAGE[t]
            for tt, label, _key, pkval in index:
                if tt != t:
                    continue
                where = f"id = {lit(pkval)}"
                probes.append((t, "select", label, f"SELECT 1 FROM storage.objects WHERE {where}"))
                probes.append((t, "update", label, f"UPDATE storage.objects SET name = name WHERE {where}"))
                probes.append((t, "delete", label, f"DELETE FROM storage.objects WHERE {where}"))
                probes.append((t, "insert", label,
                               "INSERT INTO storage.objects (bucket_id, name) VALUES "
                               f"({lit(bucket)}, {lit(storage_name(t, label, 'probe'))})"))
            continue
        m = meta[t]
        pk = m["pk"]
        script.append(
            f"CREATE TABLE rlsm.src_{i} AS SELECT * FROM public.{qi(t)} "
            f"WHERE {_pk_expr(pk)} IN (SELECT pk FROM rlsm.seed_index WHERE tbl = {lit(t)});")
        insertable = [c["name"] for c in m["cols"] if not c["generated"]]
        fresh = _fresh_pk(t, m)
        sel_list = ", ".join(fresh if (fresh and c == pk[0]) else qi(c) for c in insertable)
        touch = (pk[0] if not m["update_cols"] or pk[0] in m["update_cols"] else m["update_cols"][0])
        for tt, label, _key, pkval in index:
            if tt != t:
                continue
            where = f"{_pk_expr(pk)} = {lit(pkval)}"
            probes.append((t, "select", label, f"SELECT 1 FROM public.{qi(t)} WHERE {where}"))
            probes.append((t, "update", label,
                           f"UPDATE public.{qi(t)} SET {qi(touch)} = {qi(touch)} WHERE {where}"))
            probes.append((t, "delete", label, f"DELETE FROM public.{qi(t)} WHERE {where}"))
            probes.append((t, "insert", label,
                           f"INSERT INTO public.{qi(t)} ({', '.join(qi(c) for c in insertable)}) "
                           f"SELECT {sel_list} FROM rlsm.src_{i} WHERE {_pk_expr(pk)} = {lit(pkval)}"))
    script.append("GRANT USAGE ON SCHEMA rlsm TO PUBLIC;")
    script.append("GRANT SELECT ON ALL TABLES IN SCHEMA rlsm TO PUBLIC;")
    return "\n".join(script), probes


def claims_for(actor: str) -> str:
    auth, _role = ACTORS[actor]
    if auth is None:
        return json.dumps({"role": "anon"})
    return json.dumps({"sub": auth, "role": "authenticated", "iat": int(time.time())})


@dataclass
class World:
    dsn: str
    tables: list[str]
    meta: dict
    index: list[tuple[str, str, str, str]] = field(default_factory=list)


def build_world(admin: str, template: str, tables: list[str] | None = None, name: str | None = None) -> World:
    """Clone the migrated template, strip what is not access, seed, install."""
    admin = admin.strip()
    dbname = name or f"rlsmatrix_{uuid.uuid4().hex[:10]}"
    for attempt in range(8):
        r = _psql(f"{admin} dbname=postgres", f'CREATE DATABASE "{dbname}" TEMPLATE "{template}";')
        if r.returncode == 0 or "being accessed by other users" not in r.stderr:
            break
        time.sleep(1 + attempt)
    if r.returncode != 0:
        raise RuntimeError(f"could not create the world database: {r.stderr}")
    dsn = f"{admin} dbname={dbname}"
    tables = tables or matrix_tables()
    try:
        meta = read_meta(dsn, public_tables(tables))
        _ok(dsn, _PREPARE_SQL.replace("{tables}", lit(",".join(public_tables(tables)))))
        _ok(dsn, _STORAGE_SQL)
        _ok(dsn, _SCHEMA_SQL)
        _ok(dsn, seed_sql(meta, tables))
        index = [tuple(r.split("\x1f")) for r in
                 _ok(dsn, "SELECT tbl || chr(31) || label || chr(31) || key || chr(31) || pk "
                          "FROM rlsm.seed_index ORDER BY tbl, label;").splitlines()]
        script, probes = probe_sql(meta, tables, index)
        _ok(dsn, script)
        _ok(dsn, "INSERT INTO rlsm.probe (tbl, op, label, sql) VALUES\n  " + ",\n  ".join(
            f"({lit(t)}, {lit(op)}, {lit(label)}, {lit(sql)})" for t, op, label, sql in probes) + ";")
    except BaseException:
        drop_world(admin, dbname)
        raise
    return World(dsn=dsn, tables=tables, meta=meta, index=index)


def drop_world(admin: str, dbname: str) -> None:
    _psql(f"{admin.strip()} dbname=postgres", f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def dbname_of(dsn: str) -> str:
    return dsn.rsplit("dbname=", 1)[1].strip()


# ── observing ────────────────────────────────────────────────────────────────
@dataclass
class Observation:
    #: (actor, table) -> op -> "A,B" | "-" | "x"
    cells: dict[tuple[str, str], dict[str, str]]
    #: probes whose outcome is not an access decision: (actor, table, op, label, outcome)
    inconclusive: list[tuple[str, str, str, str, str]]
    seconds: float = 0.0


def _classify(table: str, outcome: str) -> str:
    """'row' | 'none' | 'nopriv' | 'other'."""
    if outcome.startswith("rows:"):
        return "row" if int(outcome[5:]) >= 1 else "none"
    _, state, msg = outcome.split(":", 2)
    if state == "42501":
        if "violates row-level security policy" in msg:
            return "none"
        if msg.startswith(f"permission denied for table {table}") or msg.startswith("permission denied for column"):
            return "nopriv"
    return "other"


def observe(world: World, actors: list[str] | None = None, tables: list[str] | None = None) -> Observation:
    started = time.time()
    actors = actors or list(ACTORS)
    tables = tables or world.tables
    _ok(world.dsn, "TRUNCATE rlsm.obs;")
    only = "NULL" if tables is world.tables else f"ARRAY[{', '.join(lit(t) for t in tables)}]::text[]"
    for actor in actors:
        _auth, role = ACTORS[actor]
        _ok(world.dsn, f"SET statement_timeout = '300s'; "
                       f"SELECT rlsm.run({lit(actor)}, {lit(claims_for(actor))}, {lit(role)}, {only});")
    rows = json.loads(_ok(world.dsn, """
        SELECT coalesce(json_agg(json_build_object('actor', o.actor, 'tbl', p.tbl, 'op', p.op,
                                                   'label', p.label, 'outcome', o.outcome)), '[]'::json)
          FROM rlsm.obs o JOIN rlsm.probe p ON p.id = o.probe_id;"""))
    per: dict[tuple[str, str, str], list[tuple[str, str, str]]] = {}
    for r in rows:
        if r["tbl"] in tables:
            per.setdefault((r["actor"], r["tbl"], r["op"]), []).append(
                (r["label"], _classify(physical_name(r["tbl"]), r["outcome"]), r["outcome"]))
    cells: dict[tuple[str, str], dict[str, str]] = {}
    bad: list[tuple[str, str, str, str, str]] = []
    for (actor, tbl, op), probes in per.items():
        kinds = {k for _l, k, _o in probes}
        for label, kind, outcome in probes:
            if kind == "other" or (op == "insert" and outcome == "rows:0"):
                bad.append((actor, tbl, op, label, outcome))
        if kinds & {"nopriv"} and kinds - {"nopriv"}:
            # a privilege that holds for one row and not another is not a thing
            bad.extend((actor, tbl, op, label, outcome) for label, _k, outcome in probes)
        if "other" in kinds or (kinds & {"nopriv"} and kinds - {"nopriv"}):
            continue
        if kinds == {"nopriv"}:
            value = "x"
        else:
            order = labels_of(tbl)
            got = sorted((l for l, k, _o in probes if k == "row"), key=order.index)
            value = ",".join(got) if got else "-"
        cells.setdefault((actor, tbl), {})[op] = value
    return Observation(cells=cells, inconclusive=bad, seconds=time.time() - started)


def clone_world(admin: str, world: World) -> World:
    """A byte copy of an already-seeded world, to break on purpose."""
    admin = admin.strip()
    dbname = f"rlsmatrix_c{uuid.uuid4().hex[:9]}"
    for attempt in range(8):
        r = _psql(f"{admin} dbname=postgres", f'CREATE DATABASE "{dbname}" TEMPLATE "{dbname_of(world.dsn)}";')
        # a freshly seeded database may still have its autovacuum worker attached
        if r.returncode == 0 or "being accessed by other users" not in r.stderr:
            break
        time.sleep(1 + attempt)
    if r.returncode != 0:
        raise RuntimeError(f"could not clone the world: {r.stderr}")
    return World(dsn=f"{admin} dbname={dbname}", tables=world.tables, meta=world.meta, index=world.index)


# ── reading the result ───────────────────────────────────────────────────────
def code_of(table: str, value: str) -> str:
    """One character for a cell: `#` no privilege, `.` nothing, `*` every row of
    the caller's own firm, `A`/`B` that client's row alone, `+` some of them,
    `F` a row of the OTHER firm (for the other firm's own Partner, its own)."""
    if value == "x":
        return "#"
    if value == "-":
        return "."
    got = value.split(",")
    foreign = foreign_labels_of(table)
    if set(got) & foreign:
        return "F"
    own = [lab for lab in labels_of(table) if lab not in foreign]
    if got == own:
        return "*"
    if len(got) == 1 and got[0] in ("A", "B"):
        return got[0]
    return "+"


def render_matrix(cells: dict[tuple[str, str], dict[str, str]], tables: list[str]) -> str:
    actors = list(ACTORS)
    head = "".join(f"{a[:10]:<11}" for a in actors)
    lines = [
        "",
        "  select|insert|update|delete per actor.  # no privilege   . nothing   * every row of the caller's firm",
        "  A / B that client's row only   + some   F the other firm's row (its own Partner's own)",
        f"  {'table':<34}{head}",
    ]
    for t in tables:
        row = ""
        for a in actors:
            c = cells.get((a, t), {})
            row += f"{''.join(code_of(t, c[op]) if op in c else '?' for op in OPS):<11}"
        lines.append(f"  {t:<34}{row}")
    return "\n".join(lines)


def signatures(cells: dict[tuple[str, str], dict[str, str]], tables: list[str]) -> dict[tuple, list[str]]:
    out: dict[tuple, list[str]] = {}
    for t in tables:
        sig = tuple(tuple(cells[(a, t)].get(op, "?") for op in OPS) for a in ACTORS)
        out.setdefault(sig, []).append(t)
    return out


# ── the reviewed expectation ─────────────────────────────────────────────────
def dump_expected(table_cells: dict[str, dict[str, list[str]]]) -> str:
    """One line per (table, actor): diffs read cell by cell."""
    lines = [
        "{",
        '  "_what": "What each actor may select, insert, update and delete in each table, as the PRODUCT INTENDS it. '
        'A value is the seeded rows reached (A and B are clients of firm 1, X the client of firm 2, F1/F2 firms, G a '
        'global row), - nothing, x no privilege. Generated from observation by RLS_MATRIX_REGENERATE=1 and then '
        'reviewed cell by cell; the cells that observation disagrees with are NOT here, they are KNOWN_DEVIATIONS in '
        'test_rls_role_by_table_matrix_pg.py, which holds their observed value, the intended one and why.",',
        f'  "actors": {json.dumps(list(ACTORS))},',
        f'  "ops": {json.dumps(list(OPS))},',
        '  "tables": {',
    ]
    names = sorted(table_cells)
    for ti, t in enumerate(names):
        lines.append(f"    {json.dumps(t)}: {{")
        for ai, a in enumerate(ACTORS):
            comma = "," if ai < len(ACTORS) - 1 else ""
            lines.append(f"      {json.dumps(a)}: {json.dumps(table_cells[t][a])}{comma}")
        lines.append("    }" + ("," if ti < len(names) - 1 else ""))
    lines += ["  }", "}", ""]
    return "\n".join(lines)


# ── what observation disagrees with ──────────────────────────────────────────
WRITES = ("insert", "update", "delete")
STAFF_ACTORS = ("manager", "exec_assigned", "exec_unassigned", "reviewer")


def _cells(actors: tuple[str, ...], ops: tuple[str, ...], observed: str, intended: str) -> dict:
    return {(a, op): (observed, intended) for a in actors for op in ops}


@dataclass(frozen=True)
class Deviation:
    """A group of cells where the database does something the product does not
    intend, with ONE reason. `cells` maps (actor, op) to (observed, intended)
    and holds for every table in `tables`; the two values are what the database
    does today and what the cited rule says, and neither is the expected file's
    to decide: the file holds `intended`, the database holds `observed`."""
    id: str
    reason: str
    tables: tuple[str, ...]
    cells: dict


#: FROZEN. Every cell in it is a place the database lets somebody do what the
#: product's own rules forbid (the five rules are in this module's docstring).
#: A fix deletes its entry in the same commit and a new gap fails the build; a
#: line is never added to make a failing run green. Merging a migration applies
#: it to production, so each class is closed by its own migration once the
#: owner's rule (Claude decides the tier under the standing instructions) is
#: applied; the classes still listed have not been closed yet.
DEVIATION_CLASSES: tuple[Deviation, ...] = (
    # `year-end-children-have-no-client-id`, `cross-client-matches-have-no-client-scope` and
    # `executive-writes-manager-tier` stood here (54 cells over 5 tables, plus 6 Reviewer cells on vendors and knowledge_articles that
    # left the 41-table class with them). Migration 483 closed them
    # and their entries went in the same commit; `test_the_matrix_turns_red_when_a_known_hole_is_put_back
    # [role-tiers-483-reopened]` puts them back on purpose.
    # `portal-contacts-are-not-scoped-for-staff` stood here (4 cells over client_portal_users). Migration 484
    # closed it; `test_the_matrix_turns_red_when_a_known_hole_is_put_back[portal-contacts-484-reopened]` puts it back.
    # `any-member-assigns-themselves` stood here: user_client_assignments' one policy had no role test,
    # so any member could assign themselves to any client. Migration 478 closed it (12 write cells) and
    # its entry went in the same commit; `test_the_matrix_turns_red_when_a_known_hole_is_put_back
    # [assignment-writes-reopened]` puts it back on purpose.
    # `reviewer-writes-where-no-resource-allows-it` stood here: 39 tables whose writes a Reviewer assigned to the client
    # could make, with no resource in the API allowing it. Migrations 487, 488 and 489 closed them in three slices (13, 17
    # and 9 tables, 117 cells) and the class was deleted with the last one; `test_the_matrix_turns_red_when_a_known_hole_is_put_back`
    # [reviewer-writes-slice-1-487-reopened / -2-488-reopened / -3-489-reopened] put each slice back on purpose.
    # `billing-reads-are-partner-only` and `fee-receipts-have-no-client-id` stood here (10 cells over the three fee
    # tables: an assigned Manager, Executive or Reviewer read the practice's fee economics, and every member read every
    # client's fee receipts). Migration 495 closed them; `test_the_matrix_turns_red_when_a_known_hole_is_put_back
    # [fee-read-tier-495-reopened]` puts them back on purpose.
    # `payroll-tier-not-in-rls`, `payroll-children-have-no-client-id` and `payroll-children-manager-delete` stood
    # here (a payroll tier missing from three tables, and four children with no client scope). Migration 485
    # closed them and their entries went in the same commit; `test_the_matrix_turns_red_when_a_known_hole_is_put_back
    # [payroll-tier-485-reopened]` puts them back on purpose.
    # `suspended-member-keeps-their-own-user-row` stood here, the last one (2 cells over users): users_own_row_select and
    # users_own_row_rename compared auth_user_id with auth.uid() directly and never asked whether the session is live.
    # Migration 506 closed it; `test_the_matrix_turns_red_when_a_known_hole_is_put_back[suspended-own-row-506-reopened]`
    # puts it back on purpose. The tuple is empty now, which is the goal: every cell of the matrix agrees with the five rules.
)


def known_deviations() -> dict[tuple[str, str, str], tuple[str, str, str, str]]:
    """{(actor, table, op): (observed, intended, class id, reason)}."""
    out: dict[tuple[str, str, str], tuple[str, str, str, str]] = {}
    for d in DEVIATION_CLASSES:
        for table in d.tables:
            for (actor, op), (observed, intended) in d.cells.items():
                key = (actor, table, op)
                assert key not in out, f"{key} is in two deviation classes: {out[key][2]} and {d.id}"
                out[key] = (observed, intended, d.id, d.reason)
    return out


KNOWN_DEVIATIONS = known_deviations()


def _load_cells(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    doc = json.loads(path.read_text())
    assert doc["ops"] == list(OPS) and doc["actors"] == list(ACTORS), (
        f"{path.name} was written for different actors or operations: regenerate it")
    return {(a, t): dict(zip(OPS, vals, strict=True)) for t, per in doc["tables"].items() for a, vals in per.items()}


def load_expected() -> dict[tuple[str, str], dict[str, str]]:
    return _load_cells(EXPECTED_PATH)


def load_second_lock() -> dict[tuple[str, str], dict[str, str]]:
    return _load_cells(SECOND_LOCK_PATH)


def intended_cells(observed: dict[tuple[str, str], dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    """What the expectation holds: what was observed, except where a known
    deviation says the database does something the product does not intend."""
    out = {k: dict(v) for k, v in observed.items()}
    for (actor, table, op), (obs, intended, _cid, _why) in KNOWN_DEVIATIONS.items():
        assert out[(actor, table)][op] == obs, (
            f"KNOWN_DEVIATIONS says {actor} {op} {table} is {obs!r} today; the database says "
            f"{out[(actor, table)][op]!r}")
        out[(actor, table)][op] = intended
    return out


# ── the five rules the expectation must obey, whatever else it says ─────────
#: Where a Manager is firm-wide by design. Migration 079 says so of the first
#: two; `user_permissions` describes STAFF, not a client's books, and its policy
#: (user_permissions_role_select) is Manager and up.
FIRM_WIDE_BY_DESIGN = {"client_instructions", "knowledge_articles", "user_permissions"}
#: The assignment rows are what the scope itself is made of, and every member
#: reads them: `core.authz.assigned_client_ids` and `is_client_assigned` read the
#: CALLER'S OWN rows under the caller's JWT when USE_USER_JWT is on, so an
#: Executive cannot lose this read without losing their own scope. The policy is
#: firm-wide, wider than "own rows", and the harness cannot say "own": its seeded
#: rows belong to nobody. Narrowing it is a decision, not made by migration 478,
#: which closed the WRITES only (this was three select cells of the first
#: deviation class until it was seen that the API needs the read).
READABLE_BY_EVERY_MEMBER = {("user_client_assignments", "select")}
#: Migration 261: the activity log is written by every staff role. A member's
#: own display name is theirs to change.
REVIEWER_MAY_WRITE = {("client_timeline_events", "insert"), ("client_timeline_events", "update"),
                      ("users", "update")}
#: Rule 26C: the declaration is the employee's own statement (migration 297).
EMPLOYEE_MAY_WRITE = {("payroll_it_declarations", "insert"), ("payroll_it_declarations", "update"),
                      ("payroll_it_declaration_items", "insert"), ("payroll_it_declaration_items", "update"),
                      ("payroll_it_declaration_items", "delete")}
#: Reference data any signed-in principal reads, a suspended member's token too.
REFERENCE_DATA = {"currencies", "fx_rates"}
NOTHING = ("-", "x")


def cardinal_violations(cells: dict[tuple[str, str], dict[str, str]]) -> list[str]:
    """Every cell that breaks a rule stated in CLAUDE.md or a migration's own
    header, independent of what the expectation or the database says."""
    bad: list[str] = []
    for (actor, table), per in sorted(cells.items()):
        foreign = foreign_labels_of(table)
        generic = labels_of(table) == ["A", "B", "X"]
        for op, value in per.items():
            got = set(value.split(",")) - {"-", "x"}
            where = f"{actor} {op} {table} = {value!r}"
            # R1: one firm never reaches another's rows
            if actor == "other_firm_partner":
                if got - foreign - ({"G"} if table in GLOBAL_TABLES else set()):
                    bad.append(f"R1 the other firm's Partner reaches this firm's rows: {where}")
            elif actor != "anon" and got & foreign:
                bad.append(f"R1 a member reaches the other firm's rows: {where}")
            # R5: anon and a suspended member reach nothing (reference data aside)
            if actor == "anon" and got:
                bad.append(f"R5 anon reaches rows: {where}")
            if actor == "suspended_partner" and got and not (table in REFERENCE_DATA and op == "select"):
                bad.append(f"R5 a suspended member reaches rows: {where}")
            # R2: a non-Partner reaches a client's rows only through an assignment
            readable = (table, op) in READABLE_BY_EVERY_MEMBER
            if generic and not readable and actor == "exec_unassigned" and got & {"A", "B"}:
                bad.append(f"R2 an Executive assigned to nothing reaches a client's rows: {where}")
            if generic and not readable and actor in ("manager", "exec_assigned", "reviewer") and "B" in got and not (
                    actor == "manager" and table in FIRM_WIDE_BY_DESIGN):
                bad.append(f"R2 a member reaches a client they are not assigned to: {where}")
            # R3: a Reviewer writes nothing the role model has not given them
            if actor == "reviewer" and op in WRITES and got and (table, op) not in REVIEWER_MAY_WRITE:
                bad.append(f"R3 a Reviewer writes: {where}")
            # R4: a portal client and an employee reach their own rows and write next to nothing
            if actor == "portal_client":
                if op in WRITES and got:
                    bad.append(f"R4 a portal client writes: {where}")
                if got - {"A", "G"}:
                    bad.append(f"R4 a portal client reaches another's rows: {where}")
            if actor == "employee":
                if op in WRITES and got and (table, op) not in EMPLOYEE_MAY_WRITE:
                    bad.append(f"R4 an employee writes outside their own declaration: {where}")
                if got - {"A", "G"}:
                    bad.append(f"R4 an employee reaches another's rows: {where}")
    return bad


# ── breaking it on purpose ───────────────────────────────────────────────────
_MIGRATIONS = API_ROOT / "migrations"


def _migration_sql(name: str) -> str:
    return (_MIGRATIONS / name).read_text()


#: The controls that apply migration 499's rollback before the rollback they are about; see the use below.
_AGAINST_THE_SECOND_LOCK = {"payroll-tier-485-reopened", "payroll-tier-490-reopened"}

#: (id, what is re-introduced, SQL, tables observed, cells that must turn red)
#: A cell is (actor, table, op). Each control is a hole this repository already
#: closed once, put back in a throwaway copy of the world; none edits a migration.
CONTROLS = (
    ("liveness-dropped-from-every-helper",
     "migration 468 rolled back: get_my_firm_id/get_my_role/get_my_user_id, can_access_client and "
     "my_permission stop asking whether the session is live",
     lambda: _migration_sql("468_a_suspended_or_signed_out_member_is_nobody_to_the_database_rollback.sql"),
     ("clients", "tasks", "leave_balances", "storage/Documents"),
     {("suspended_partner", "clients", "select"), ("suspended_partner", "tasks", "delete"),
      ("suspended_partner", "leave_balances", "update"), ("suspended_partner", "storage/Documents", "select")}),
    ("payroll-write-tier-dropped",
     "the payroll:write policies of migration 261 dropped from leave_balances (attendance is no longer a candidate: migration 499 took its write privilege away), and with them the parent scope of "
     "485 that would otherwise still refuse an Executive or a Reviewer (two layers close this hole now)",
     lambda: "".join(f"DROP POLICY leave_balances_role_{c} ON public.leave_balances;" for c in ("insert", "update", "delete"))
     + "DROP POLICY leave_balances_employee_in_reach ON public.leave_balances;",
     ("leave_balances",),
     {("exec_assigned", "leave_balances", "insert"), ("reviewer", "leave_balances", "update"),
      ("reviewer", "leave_balances", "delete")}),
    ("fx-rates-write-check-true-again",
     "migration 470 rolled back: the fx_rates write policies go back to WITH CHECK (true)",
     lambda: _migration_sql("470_only_a_partner_may_write_a_manual_exchange_rate_rollback.sql"),
     ("fx_rates",),
     {("exec_assigned", "fx_rates", "insert"), ("reviewer", "fx_rates", "update"),
      ("portal_client", "fx_rates", "insert")}),
    ("storage-second-folder-dropped",
     "migration 469 rolled back: the Documents and year-end policies ask only the FIRM folder again",
     lambda: _migration_sql("469_a_stored_file_opens_only_for_the_staff_assigned_to_its_client_rollback.sql"),
     ("storage/Documents", "storage/year-end-exports"),
     {("exec_unassigned", "storage/Documents", "select"), ("exec_unassigned", "storage/Documents", "insert"),
      ("reviewer", "storage/Documents", "delete")}),
    ("assignment-scope-dropped-from-one-table",
     "tasks_assignment_scope dropped: the RESTRICTIVE can_access_client() policy of migration 084",
     lambda: "DROP POLICY tasks_assignment_scope ON public.tasks;",
     ("tasks",),
     {("exec_unassigned", "tasks", "select"), ("exec_unassigned", "tasks", "update"),
      ("reviewer", "tasks", "select")}),
    ("assignment-writes-reopened",
     "migration 478 rolled back: user_client_assignments is FOR ALL on firm_id alone again, so any member "
     "can assign themselves to any client",
     lambda: _migration_sql("478_only_a_partner_may_change_who_is_assigned_to_a_client_rollback.sql"),
     ("user_client_assignments",),
     {("exec_unassigned", "user_client_assignments", "insert"), ("reviewer", "user_client_assignments", "update"),
      ("manager", "user_client_assignments", "delete"), ("exec_assigned", "user_client_assignments", "insert")}),
    ("role-tiers-483-reopened",
     "migration 483 rolled back: vendors and knowledge_articles take any assigned writer, cross_client_matches "
     "and the year-end notes and review events are firm-wide again",
     lambda: _migration_sql("483_the_role_tiers_and_client_scopes_the_api_gives_four_more_tables_reach_the_database_rollback.sql"),
     ("vendors", "knowledge_articles", "cross_client_matches", "year_end_notes", "year_end_review_events"),
     {("exec_assigned", "vendors", "insert"), ("exec_assigned", "knowledge_articles", "update"),
      ("exec_assigned", "cross_client_matches", "delete"), ("exec_unassigned", "year_end_notes", "select"),
      ("reviewer", "year_end_review_events", "insert"), ("manager", "vendors", "delete")}),
    ("portal-contacts-484-reopened",
     "migration 484 rolled back: every member of the firm reads every client's portal contacts, e-mail and "
     "invite_token again",
     lambda: _migration_sql("484_only_a_partner_reads_the_audit_log_and_staff_see_only_their_clients_portal_contacts_rollback.sql"),
     ("client_portal_users",),
     {("exec_unassigned", "client_portal_users", "select"), ("manager", "client_portal_users", "select"),
      ("reviewer", "client_portal_users", "select")}),
    ("payroll-tier-485-reopened",
     "migration 485 rolled back: an assigned Executive or Reviewer reads and writes employees, runs and payslips, "
     "and every member reads every client's attendance, leave and tax declarations",
     # 499 revoked the signed-in write privilege on these tables, so the write cells stay closed after 485 alone is
     # rolled back; the privilege comes back first so the policy rollback is what the control measures.
     lambda: _migration_sql("499_a_signed_in_session_writes_none_of_the_payroll_tables_the_browser_never_writes_rollback.sql") + "\n"
     + _migration_sql("485_the_database_asks_the_payroll_tier_and_the_clients_in_reach_of_the_employee_run_and_payslip_rows_rollback.sql"),
     ("payroll_employees", "payroll_runs", "payroll_slips", "attendance", "leave_balances",
      "payroll_it_declarations", "payroll_it_declaration_items"),
     {("exec_assigned", "payroll_employees", "select"), ("reviewer", "payroll_slips", "update"),
      ("exec_assigned", "payroll_runs", "insert"), ("exec_unassigned", "attendance", "select"),
      ("manager", "leave_balances", "delete"), ("reviewer", "payroll_it_declarations", "select"),
      ("exec_assigned", "payroll_it_declaration_items", "select")}),
    ("reviewer-writes-slice-1-487-reopened",
     "migration 487 rolled back: a Reviewer assigned to the client writes its invoices, bills, receipts, payments, notes, "
     "catalogue items, bank accounts and bank transactions again",
     lambda: _migration_sql("487_a_reviewer_cannot_write_the_accounting_documents_or_the_bank_tables_rollback.sql"),
     ("client_sales_invoices", "purchase_bills", "receipts", "receipt_allocations", "purchase_payments",
      "purchase_payment_allocations", "credit_notes", "debit_notes", "purchase_credit_notes", "sales_debit_notes",
      "service_catalogue", "bank_accounts", "bank_transactions"),
     {("reviewer", "client_sales_invoices", "insert"), ("reviewer", "purchase_bills", "update"),
      ("reviewer", "receipts", "delete"), ("reviewer", "bank_transactions", "update"),
      ("reviewer", "credit_notes", "insert"), ("reviewer", "bank_accounts", "delete"),
      ("exec_assigned", "service_catalogue", "insert"), ("exec_assigned", "credit_notes", "update")}),
    ("reviewer-writes-slice-2-488-reopened",
     "migration 488 rolled back: a Reviewer assigned to the client writes its returns, filings, year-end records and "
     "company registrations again",
     lambda: _migration_sql("488_a_reviewer_cannot_write_the_tax_filing_year_end_or_company_filing_tables_rollback.sql"),
     ("gstr1_returns", "gstr3b_returns", "gstr2a_records", "gstr2b_reconciliations", "itr_filings",
      "tax_computation_snapshots", "tax_disallowances", "brought_forward_losses", "form_26as_uploads",
      "form_26as_reconciliations", "xbrl_packages", "year_end_adjustments", "year_end_engagements",
      "year_end_exports", "financial_statement_versions", "mca_companies", "mca_directors"),
     {("reviewer", "gstr1_returns", "insert"), ("reviewer", "itr_filings", "update"),
      ("reviewer", "year_end_engagements", "delete"), ("reviewer", "mca_directors", "insert"),
      ("reviewer", "tax_disallowances", "update"), ("reviewer", "xbrl_packages", "insert")}),
    ("reviewer-writes-slice-3-489-reopened",
     "migration 489 rolled back: a Reviewer assigned to the client writes its instructions, compliance records, "
     "notices, health records, onboarding workflows and renewals again",
     lambda: _migration_sql("489_a_reviewer_cannot_write_the_client_level_tables_rollback.sql"),
     # `ai_insights` is not in this list since migration 507: no signed-in role holds a write on it at all, so rolling back
     # 489 changes nothing there and the control cannot turn a cell red on it.
     ("client_instructions", "compliance_records", "government_notices", "health_alerts",
      "health_score_history", "health_scores", "onboarding_workflows", "renewals"),
     {("reviewer", "client_instructions", "update"),
      ("reviewer", "compliance_records", "delete"), ("reviewer", "renewals", "insert"),
      ("reviewer", "health_scores", "update"), ("reviewer", "government_notices", "insert")}),
    ("payroll-tier-490-reopened",
     "migration 490 rolled back: every member of the firm reads salary history, loans, perquisites, settlements, "
     "salary structures, remittances and ECR filings again, and writes the four tables that had no write tier",
     lambda: _migration_sql("499_a_signed_in_session_writes_none_of_the_payroll_tables_the_browser_never_writes_rollback.sql") + "\n"
     + _migration_sql("490_the_database_asks_the_payroll_tier_of_the_other_payroll_tables_rollback.sql"),
     ("payroll_salary_revisions", "salary_structures", "payroll_perquisites", "payroll_loans",
      "payroll_loan_recoveries", "payroll_settlements", "payroll_settlement_components",
      "payroll_one_time_earnings", "bonus_disqualifications", "payroll_run_transitions",
      "statutory_remittances", "epfo_ecr_filings", "bonus_declarations"),
     {("exec_assigned", "payroll_loans", "select"), ("reviewer", "payroll_salary_revisions", "select"),
      ("exec_unassigned", "payroll_settlements", "select"), ("exec_assigned", "salary_structures", "select"),
      ("reviewer", "statutory_remittances", "select"), ("exec_assigned", "epfo_ecr_filings", "select"),
      ("reviewer", "payroll_settlement_components", "select"), ("exec_assigned", "salary_structures", "insert"),
      ("reviewer", "epfo_ecr_filings", "update"), ("exec_assigned", "statutory_remittances", "insert"),
      ("reviewer", "payroll_run_transitions", "insert"), ("reviewer", "bonus_disqualifications", "update"),
      ("exec_assigned", "bonus_declarations", "select"), ("reviewer", "bonus_declarations", "insert")}),
    ("payroll-writes-499-reopened",
     "migration 499 rolled back: an assigned Manager writes the payroll runs, payslips, employees, run history and the "
     "tables a run is computed from over PostgREST again",
     lambda: _migration_sql("499_a_signed_in_session_writes_none_of_the_payroll_tables_the_browser_never_writes_rollback.sql"),
     ("payroll_employees", "payroll_runs", "payroll_slips", "payroll_run_transitions", "salary_structures",
      "payroll_loans", "payroll_loan_recoveries", "statutory_remittances", "epfo_ecr_filings", "attendance"),
     {("manager", "payroll_runs", "insert"), ("manager", "payroll_employees", "update"),
      ("partner", "payroll_slips", "delete"), ("manager", "payroll_run_transitions", "insert"),
      ("manager", "salary_structures", "insert"), ("manager", "attendance", "update"),
      ("manager", "epfo_ecr_filings", "insert"), ("manager", "statutory_remittances", "update")}),
    ("fee-read-tier-495-reopened",
     "migration 495 rolled back: an assigned Manager, Executive or Reviewer reads the fees of their clients again, and "
     "every member of the firm reads every client's fee receipts",
     lambda: _migration_sql("495_the_practices_fee_tables_are_read_only_by_someone_with_billing_access_rollback.sql"),
     ("fee_engagements", "fee_invoices", "fee_receipts"),
     {("manager", "fee_engagements", "select"), ("exec_assigned", "fee_invoices", "select"),
      ("reviewer", "fee_invoices", "select"), ("reviewer", "fee_receipts", "select"),
      ("exec_unassigned", "fee_receipts", "select")}),
    ("suspended-own-row-506-reopened",
     "migration 506 rolled back: users_own_row_select and users_own_row_rename ask only the sign-in id again, so a "
     "suspended member still reads and renames their own users row",
     lambda: _migration_sql("506_a_suspended_member_does_not_read_or_rename_their_own_users_row_rollback.sql"),
     ("users",),
     {("suspended_partner", "users", "select"), ("suspended_partner", "users", "update")}),
    ("anon-granted-a-table",
     "GRANT SELECT ON clients TO anon: no policy would show a row, but the privilege itself is the hole",
     lambda: "GRANT SELECT ON public.clients TO anon;",
     ("clients",),
     {("anon", "clients", "select")}),
)


# ═════════════════════════════ the tests ═════════════════════════════════════
@pytest.fixture(scope="module")
def world(pg_template):
    w = build_world(_ADMIN, pg_template.name)
    try:
        yield w
    finally:
        drop_world(_ADMIN, dbname_of(w.dsn))


@pytest.fixture(scope="module")
def observed(world):
    return observe(world)


def _regenerating() -> bool:
    return os.environ.get("RLS_MATRIX_REGENERATE") == "1"


def _differences(expected, got) -> dict[tuple[str, str, str], tuple[str, str]]:
    """{(actor, table, op): (expected, observed)} for every cell that disagrees."""
    out = {}
    for key, per in expected.items():
        for op, want in per.items():
            have = got.get(key, {}).get(op)
            if have != want:
                out[(key[0], key[1], op)] = (want, have)
    return out


# ── no database needed: the list, the file and the rules ────────────────────
@_NEEDS_PG_SOURCE
def test_the_table_list_is_the_parsers_own_answer_and_the_file_covers_exactly_it():
    tables = matrix_tables()
    found = set(_browser_tables())
    assert len(found) >= 75, f"only {len(found)} browser tables found: the parser stopped finding them"
    assert set(tables) == found | set(ALSO_COVERED) | set(STORAGE)
    expected = load_expected()
    in_file = {t for _a, t in expected}
    assert in_file == set(tables), (
        f"the expectation covers a different set of tables than apps/web now reaches: "
        f"missing {sorted(set(tables) - in_file)}, no longer reached {sorted(in_file - set(tables))}. "
        f"Review the new rows and regenerate with RLS_MATRIX_REGENERATE=1")
    assert len(expected) == len(tables) * len(ACTORS)


@_NEEDS_PG_SOURCE
def test_the_expectation_obeys_the_five_rules():
    bad = cardinal_violations(load_expected())
    assert not bad, "the expectation itself breaks a rule it exists to hold:\n  " + "\n  ".join(bad)


@_NEEDS_PG_SOURCE
def test_every_known_deviation_is_one_sentence_a_real_cell_and_not_in_the_expectation():
    expected = load_expected()
    # The list has been EMPTY since migration 506 closed the last class: every cell agrees with the five rules. The assertion
    # that used to stand here ("an empty list is a claim that nothing deviates: delete the machinery with it") is gone with
    # the last entry, and the machinery stays on purpose: it is how a gap an audit finds LATER is written down, with a
    # ledger line, in the commit that finds it, and deleting it would touch the expected-file writer and four tests of a
    # guard that CI runs on every migration. While the list is empty the loop below has nothing to check.
    for (actor, table, op), (observed_value, intended, cid, reason) in KNOWN_DEVIATIONS.items():
        assert actor in ACTORS and op in OPS and (actor, table) in expected, (actor, table, op)
        assert observed_value != intended, f"{(actor, table, op)} is not a deviation: observed == intended"
        assert expected[(actor, table)][op] == intended, (
            f"{(actor, table, op)}: the expectation holds {expected[(actor, table)][op]!r}, the deviation says "
            f"the product intends {intended!r}")
        assert "\n" not in reason and reason.endswith(".") and reason.count(". ") == 0, (
            f"{cid}: the reason is one sentence")


def test_the_classifier_reads_every_outcome_the_instrument_can_meet():
    assert _classify("tasks", "rows:1") == "row"
    assert _classify("tasks", "rows:0") == "none"
    assert _classify("tasks", 'err:42501:new row violates row-level security policy for table "tasks"') == "none"
    assert _classify("tasks", 'err:42501:permission denied for table tasks') == "nopriv"
    assert _classify("tasks", 'err:42501:permission denied for column id of relation tasks') == "nopriv"
    # a privilege failure on a DIFFERENT table is a trigger's, not this table's decision
    assert _classify("tasks", 'err:42501:permission denied for table audit_log') == "other"
    assert _classify("tasks", 'err:42501:permission denied for function get_my_role') == "other"
    for state in ("23502", "23503", "23505", "23514", "42P01", "P0001"):
        assert _classify("tasks", f"err:{state}:anything") == "other", state
    assert code_of("tasks", "x") == "#" and code_of("tasks", "-") == "." and code_of("tasks", "A,B") == "*"
    assert code_of("tasks", "A") == "A" and code_of("tasks", "X") == "F" and code_of("tasks", "A,X") == "F"
    assert code_of("users", "partner,exec_a") == "+" and code_of("firms", "F1") == "*"
    assert code_of("firms", "F2") == "F" and code_of("fx_rates", "G") == "*"
    assert dump_expected({"t": {a: ["A", "-", "x", "A,B"] for a in ACTORS}}).count("\n") > len(ACTORS)


def test_the_seeded_labels_name_the_actors_the_policies_ask_about():
    assert len(set(AUTH.values())) == len(AUTH)
    assert set(ACTORS) == {"partner", "manager", "exec_assigned", "exec_unassigned", "reviewer", "portal_client",
                           "employee", "other_firm_partner", "suspended_partner", "anon"}
    assert "exec_n" not in ASSIGNED_TO_A, "the unassigned Executive is assigned to nothing, that is the point"
    assert [s for s in STAFF if not s[3]] == [("suspended", "Partner", FIRM1, False)]
    assert labels_of("users") == [s[0] for s in STAFF] and labels_of("firms") == ["F1", "F2"]
    assert foreign_labels_of("firms") == {"F2"} and foreign_labels_of("fx_rates") == set()


# ── the instrument ───────────────────────────────────────────────────────────
@_NEEDS_PG
def test_the_world_is_what_the_matrix_says_it_is(world):
    """Not vacuous: every labelled row exists for a superuser, so a `nothing`
    in a cell is a policy's doing and never a row that was not there."""
    probes = []
    for t, label, _key, pk in world.index:
        if is_storage(t):
            probes.append(f"SELECT {lit(t)}, {lit(label)}, count(*) FROM storage.objects WHERE id = {lit(pk)}")
        else:
            probes.append(f"SELECT {lit(t)}, {lit(label)}, count(*) FROM public.{qi(t)} "
                          f"WHERE {_pk_expr(world.meta[t]['pk'])} = {lit(pk)}")
    rows = _ok(world.dsn, "\nUNION ALL\n".join(probes) + ";").splitlines()
    missing = [r for r in rows if not r.endswith("|1")]
    assert len(rows) == len(world.index) and not missing, f"seeded rows that are not there: {missing[:10]}"
    assert len(world.tables) >= 85 and len(ACTORS) == 10
    # constraints that could make a probe fail for a reason that is not access are gone
    left = _ok(world.dsn, "SELECT count(*) FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
                          "WHERE t.relnamespace = 'public'::regnamespace AND c.contype IN ('f','c','u','x') "
                          f"AND t.relname = ANY(string_to_array({lit(','.join(public_tables(world.tables)))}, ','))")
    assert left == "0", f"{left} constraints survived the preparation"


@_NEEDS_PG
def test_every_actor_was_observed_on_every_table_and_no_probe_was_inconclusive(world, observed):
    assert not observed.inconclusive, (
        "a probe failed for a reason that is not an access decision, so its cell would be a guess:\n  "
        + "\n  ".join(map(str, observed.inconclusive[:20])))
    assert len(observed.cells) == len(world.tables) * len(ACTORS)
    assert all(set(per) == set(OPS) for per in observed.cells.values())


@_NEEDS_PG
def test_the_instrument_agrees_with_a_plain_session(world, observed):
    """The probe loop runs inside one PL/pgSQL function with a savepoint per
    probe. This asks the same question the way every other real-Postgres test in
    this directory does, in a session of its own, and demands the same answer."""
    ask = [
        ("partner", "tasks", "select", "A"), ("exec_assigned", "tasks", "select", "B"),
        ("exec_assigned", "tasks", "delete", "A"), ("manager", "tasks", "delete", "A"),
        ("reviewer", "tasks", "insert", "A"), ("exec_unassigned", "tasks", "update", "A"),
        ("other_firm_partner", "clients", "select", "X"), ("other_firm_partner", "clients", "select", "A"),
        ("suspended_partner", "tasks", "select", "A"), ("employee", "payroll_slips", "select", "A"),
        ("employee", "payroll_slips", "select", "B"), ("portal_client", "customers", "select", "A"),
        ("portal_client", "customers", "select", "B"), ("exec_unassigned", "user_client_assignments", "insert", "A"),
        ("partner", "user_client_assignments", "insert", "A"), ("manager", "user_client_assignments", "delete", "A"),
    ]
    pk = {(t, label): p for t, label, _k, p in world.index}
    for actor, table, op, label in ask:
        _auth, role = ACTORS[actor]
        where = f"{_pk_expr(world.meta[table]['pk'])} = {lit(pk[(table, label)])}"
        stmt = {"select": f"SELECT count(*) FROM public.{qi(table)} WHERE {where}",
                "delete": f"DELETE FROM public.{qi(table)} WHERE {where}",
                "update": f"UPDATE public.{qi(table)} SET id = id WHERE {where}"}.get(op)
        if op == "insert":
            m = world.meta[table]
            cols = [c["name"] for c in m["cols"] if not c["generated"]]
            stmt = (f"INSERT INTO public.{qi(table)} ({', '.join(qi(c) for c in cols)}) "
                    f"SELECT {', '.join('gen_random_uuid()' if c == 'id' else qi(c) for c in cols)} "
                    f"FROM rlsm.src_{world.tables.index(table)} WHERE {where}")
        script = (f"BEGIN; SET LOCAL request.jwt.claims = {lit(claims_for(actor))}; SET LOCAL ROLE {role}; "
                  f"{stmt}; ROLLBACK;")
        r = subprocess.run(["psql", world.dsn, "-X", "-A", "-t", "-f", "-"], input=script,
                           capture_output=True, text=True)
        # psql prints a result table for a SELECT and a command tag for the rest
        lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
        counted = [ln for ln in lines if ln.isdigit()] or [
            ln.split(" ")[-1] for ln in lines if ln.split(" ")[0] in ("INSERT", "UPDATE", "DELETE")]
        plain = int(counted[0]) if counted else 0
        value = observed.cells[(actor, table)][op]
        assert (plain >= 1) == (label in value.split(",")), (
            f"{actor} {op} {table} row {label}: a plain session changed/saw {plain} row(s) "
            f"({r.stderr.strip()[:120]!r}) but the matrix says {value!r}")


@_NEEDS_PG
def test_a_member_cannot_update_the_users_columns_that_decide_who_they_are(world):
    """The matrix updates one column per table; on `users` that is full_name.
    The rest is a privilege question the rows cannot answer."""
    cols = world.meta["users"]["update_cols"]
    assert cols == ["full_name"], (
        f"`authenticated` may update {cols} on users. role, firm_id, auth_user_id, is_active and "
        f"sessions_revoked_at decide who a request is; none of them may be a member's to write.")


# ── the matrix ───────────────────────────────────────────────────────────────
@_NEEDS_PG
def test_no_cell_differs_from_the_expectation_except_the_known_deviations(world, observed, capsys):
    tables = world.tables
    with capsys.disabled():
        print(render_matrix(observed.cells, tables))
        sigs = signatures(observed.cells, tables)
        print(f"\n  {len(tables)} tables x {len(ACTORS)} actors x {len(OPS)} operations = "
              f"{len(tables) * len(ACTORS) * len(OPS)} cells, {len(sigs)} distinct row patterns, "
              f"observed in {observed.seconds:.1f}s; {len(KNOWN_DEVIATIONS)} cells deviate from the product's "
              f"intent ({len({d[2] for d in KNOWN_DEVIATIONS.values()})} classes)")
    if _regenerating():
        intended = intended_cells(observed.cells)
        table_cells = {t: {a: [intended[(a, t)][op] for op in OPS] for a in ACTORS} for t in tables}
        EXPECTED_PATH.write_text(dump_expected(table_cells))
        pytest.skip(f"rewrote {EXPECTED_PATH.name} from observation: read `git diff` cell by cell before committing")
    expected = load_expected()
    diff = _differences(expected, observed.cells)
    known = KNOWN_DEVIATIONS
    unexplained = {k: v for k, v in diff.items() if k not in known or known[k][0] != v[1]}
    assert not unexplained, (
        "These cells differ from the reviewed expectation and are not known deviations. LOOSER means the "
        "database now lets somebody do more than the product intends; TIGHTER means it stopped letting "
        "somebody do their job. Either fix the policy, or review the cell and regenerate the expectation "
        "(RLS_MATRIX_REGENERATE=1):\n  "
        + "\n  ".join(f"{a} / {t} / {op}: expected {w!r}, the database gives {h!r}"
                      for (a, t, op), (w, h) in sorted(unexplained.items())))


def test_the_second_lock_file_covers_exactly_the_tables_migration_499_revokes():
    """No database: the file measuring the policies and the list the migration revokes are one set, so a table added to
    the revoke without a second-lock row (its policies would then be measured by nothing) fails here."""
    sql = (_MIGRATIONS / "499_a_signed_in_session_writes_none_of_the_payroll_tables_the_browser_never_writes.sql").read_text()
    revoked = set(re.findall(r"'([a-z_]+)'", sql.split("tables text[] := ARRAY[", 1)[1].split("]", 1)[0]))
    second = load_second_lock()
    assert {t for _a, t in second} == revoked, (
        f"rls_expected_second_lock.json covers a different set of tables than migration 499 revokes: "
        f"missing {sorted(revoked - {t for _a, t in second})}, extra {sorted({t for _a, t in second} - revoked)}")
    assert len(second) == len(revoked) * len(ACTORS)
    # and the main expectation reads "no privilege" in every write cell of them, which is what 499 does
    main = load_expected()
    for (actor, table), per in second.items():
        for op in WRITES:
            assert main[(actor, table)][op] == "x", (actor, table, op, main[(actor, table)][op])
        assert main[(actor, table)]["select"] == per["select"], (actor, table)


@_NEEDS_PG
def test_the_second_lock_decides_when_the_first_is_lifted(world):
    """Migration 499 took the write privilege from every signed-in role on seventeen payroll tables, so the main matrix
    reads "no privilege" in all their write cells and can no longer see a row policy move. This gives the privilege back
    in a copy of the world (the migration's own rollback) and asks every actor again: the policies of 485 and 490 and the
    triggers of 498 must still decide each cell exactly as they did before 499."""
    copy = clone_world(_ADMIN, world)
    try:
        _ok(copy.dsn, _migration_sql(_M499_ROLLBACK))
        expected = load_second_lock()
        tables = sorted({t for _a, t in expected})
        again = observe(copy, tables=tables)
        assert not again.inconclusive, again.inconclusive[:5]
        diff = {k: v for k, v in _differences(expected, again.cells).items()
                if k not in KNOWN_DEVIATIONS or KNOWN_DEVIATIONS[k][0] != v[1]}
        assert not diff, (
            "with the write privilege given back, these payroll cells differ from what the row policies decided before "
            "migration 499. LOOSER means a policy now lets somebody do more; TIGHTER means one stopped letting somebody "
            "do their job. Fix the policy, or review the cell and edit fixtures/rls_expected_second_lock.json:\n  "
            + "\n  ".join(f"{a} / {t} / {op}: expected {w!r}, the database gives {h!r}"
                          for (a, t, op), (w, h) in sorted(diff.items())))
    finally:
        drop_world(_ADMIN, dbname_of(copy.dsn))


@_NEEDS_PG
def test_a_fixed_deviation_deletes_its_entry(world, observed):
    expected = load_expected()
    diff = _differences(expected, observed.cells)
    stale = sorted(k for k in KNOWN_DEVIATIONS if k not in diff)
    assert not stale, (
        "these known deviations no longer deviate (a policy was fixed, or the cell now matches): delete "
        "their entries from DEVIATION_CLASSES in the same commit as the fix:\n  "
        + "\n  ".join(f"{a} / {t} / {op}  [{KNOWN_DEVIATIONS[(a, t, op)][2]}]" for a, t, op in stale))


# ── breaking it on purpose ───────────────────────────────────────────────────
@_NEEDS_PG
@pytest.mark.parametrize("control", CONTROLS, ids=[c[0] for c in CONTROLS])
def test_the_matrix_turns_red_when_a_known_hole_is_put_back(world, observed, control):
    cid, what, sql, tables, must_be_red = control
    copy = clone_world(_ADMIN, world)
    try:
        _ok(copy.dsn, sql())
        again = observe(copy, tables=list(tables))
        assert not again.inconclusive, again.inconclusive[:5]
        expected = {key: per for key, per in load_expected().items() if key[1] in tables}
        if cid in _AGAINST_THE_SECOND_LOCK:
            # These controls put the 499 rollback back FIRST, so the write privilege is present and the main expectation
            # reads "no privilege" in every write cell of the seventeen tables: measured against it, those cells go red
            # from the privilege alone and would prove nothing about the policy rollback that follows. Against the cells
            # the policies decided before 499, only the policy rollback can turn them red.
            expected.update({k: v for k, v in load_second_lock().items() if k[1] in tables})
        # red = disagrees with the expectation AND is not merely a known deviation, unchanged
        changed = {k for k, (_w, h) in _differences(expected, again.cells).items()
                   if k not in KNOWN_DEVIATIONS or KNOWN_DEVIATIONS[k][0] != h}
        missed = must_be_red - changed
        assert not missed, f"`{what}` did not turn these cells red: {sorted(missed)}"
    finally:
        drop_world(_ADMIN, dbname_of(copy.dsn))
