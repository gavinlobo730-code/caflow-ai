"""Migration 484 — only a Partner reads the audit log, and staff see only the portal contacts of clients they reach.

THE BUGS THIS PINS (security_privacy-34, ledger POST-B-010 and the row-scoping half of POST-B-027)
    1. PRODUCTION's `audit_log` carries `audit_log_own_firm` (SELECT, firm only) beside `audit_log_partner_read`
       (SELECT, firm AND Partner). Permissive policies OR, so every member of the firm read the whole edit log.
       A database built from this repository's migrations has only the second, which is why no test saw it:
       the fixture below adds the production-only policy by hand, as production has it, BEFORE the migration.
    2. `client_portal_users` had a firm-wide staff SELECT, so every member read every client's portal contacts,
       their e-mail and their live invite_token.

WHAT IS ASSERTED, AND WHY IT IS A DATABASE FACT
    * with production's extra policy in place, an Executive, a Reviewer and a Manager read the whole log (the hole,
      proved, so the fix has something to turn red against);
    * after the migration only a Partner of the firm reads it: the other roles, a suspended Partner and another
      firm's Partner read none;
    * a portal contact reads their OWN row and nobody else's (`client_portal_users_self` must keep working: the
      portal's whole sign-in depends on it), and staff read a client's contacts exactly when they reach the
      client: a Partner all of the firm's, an assigned Manager/Executive/Reviewer their client's, an unassigned
      Executive none, a suspended Partner none, another firm's Partner none;
    * the migration is idempotent;
    * its own rollback puts both holes back, which is the negative control that makes the rest mean something.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
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
MIGRATIONS = API_ROOT / "migrations"
MIGRATION = MIGRATIONS / "484_only_a_partner_reads_the_audit_log_and_staff_see_only_their_clients_portal_contacts.sql"
ROLLBACK = MIGRATIONS / "484_only_a_partner_reads_the_audit_log_and_staff_see_only_their_clients_portal_contacts_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the audit-log and portal-contact policy proofs require HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000484"
OTHER_FIRM = "aaaaaaaa-0000-0000-0000-000000000485"
CLIENT_A = "cccccccc-0000-0000-0000-00000000a484"
CLIENT_B = "cccccccc-0000-0000-0000-00000000b484"
CLIENT_OTHER = "cccccccc-0000-0000-0000-00000000c484"

AUTH = {
    "partner": "11111111-1111-1111-1111-111111111484",
    "manager": "22222222-2222-2222-2222-222222222484",
    "exec_assigned": "33333333-3333-3333-3333-333333333484",
    "exec_unassigned": "44444444-4444-4444-4444-444444444484",
    "reviewer": "55555555-5555-5555-5555-555555555484",
    "suspended": "66666666-6666-6666-6666-666666666484",
    "other_partner": "77777777-7777-7777-7777-777777777484",
    "portal_a": "88888888-8888-8888-8888-888888888484",
}
USER = {k: v.replace(v[:8], "bbbbbbbb", 1) for k, v in AUTH.items() if k != "portal_a"}
STAFF_ASSIGNED_TO_A = ("manager", "exec_assigned", "reviewer")


def _psql(dsn: str, sql: str, tuples: bool = True) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else []) + ["-f", "-"]
    return subprocess.run(args, input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _as(dsn: str, who: str, sql: str) -> str:
    """Run `sql` as `authenticated` with `who`'s JWT claim; return its (single-value) output."""
    claims = json.dumps({"sub": AUTH[who], "role": "authenticated"})
    r = _psql(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""


def _audit_rows(dsn: str, who: str) -> int:
    return int(_as(dsn, who, "SELECT count(*) FROM audit_log;"))


def _contacts(dsn: str, who: str) -> set[str]:
    out = _as(dsn, who, "SELECT coalesce(string_agg(email, ',' ORDER BY email), '') FROM client_portal_users;")
    return {e for e in out.split(",") if e}


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"rlsmatrix_m484_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        roles = (("partner", "Partner", "true"), ("manager", "Manager", "true"),
                 ("exec_assigned", "Executive", "true"), ("exec_unassigned", "Executive", "true"),
                 ("reviewer", "Reviewer", "true"), ("suspended", "Partner", "false"),
                 ("other_partner", "Partner", "true"))
        auth_rows = ", ".join(f"('{v}', '{k}@m484.test')" for k, v in AUTH.items())
        users = ", ".join(
            f"('{USER[k]}', '{OTHER_FIRM if k == 'other_partner' else FIRM}', '{AUTH[k]}', '{k}@m484.test', "
            f"'{k}', '{role}', {active})" for k, role, active in roles)
        assigned = ", ".join(f"('{FIRM}', '{USER[k]}', '{CLIENT_A}')" for k in STAFF_ASSIGNED_TO_A)
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES {auth_rows};
            INSERT INTO firms (id, name, email) VALUES
              ('{FIRM}','M484 Firm','m484@test.in'), ('{OTHER_FIRM}','M484 Other','m484o@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {users};
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
              ('{CLIENT_A}','{FIRM}','Client A','Private Limited'),
              ('{CLIENT_B}','{FIRM}','Client B','Private Limited'),
              ('{CLIENT_OTHER}','{OTHER_FIRM}','Client Other','Private Limited');
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES {assigned};
            INSERT INTO client_portal_users (firm_id, client_id, email, auth_user_id, status) VALUES
              ('{FIRM}','{CLIENT_A}','contact-a@m484.test','{AUTH['portal_a']}','active'),
              ('{FIRM}','{CLIENT_B}','contact-b@m484.test',NULL,'invited'),
              ('{OTHER_FIRM}','{CLIENT_OTHER}','contact-other@m484.test',NULL,'invited');
            INSERT INTO audit_log (firm_id, entity_type, entity_id, action) VALUES
              ('{FIRM}','client','{CLIENT_A}','update'), ('{FIRM}','payroll_slip','s1','update'),
              ('{OTHER_FIRM}','client','{CLIENT_OTHER}','update');
        """)
        assert seed.returncode == 0, seed.stderr
        # PRODUCTION'S extra policy, which no migration in this repository creates (read from production's
        # pg_policies on 14-10-2026): the firm-only SELECT beside audit_log_partner_read.
        _ok(dsn, 'CREATE POLICY "audit_log_own_firm" ON public.audit_log FOR SELECT TO authenticated '
                 "USING (firm_id = public.get_my_firm_id());")
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _apply(dsn: str, path: Path) -> None:
    r = _psql(dsn, path.read_text(), tuples=False)
    assert r.returncode == 0, r.stderr


# ── the audit log ────────────────────────────────────────────────────────────
def test_with_production_policy_in_place_every_member_reads_the_whole_firms_log(db):
    """The hole, proved: the fix below has something to turn red against."""
    for who in ("manager", "exec_assigned", "exec_unassigned", "reviewer", "partner"):
        assert _audit_rows(db, who) == 2, who


def test_after_484_only_a_partner_of_the_firm_reads_the_log(db):
    _apply(db, MIGRATION)
    assert _audit_rows(db, "partner") == 2
    for who in ("manager", "exec_assigned", "exec_unassigned", "reviewer", "suspended"):
        assert _audit_rows(db, who) == 0, who


def test_another_firms_partner_reads_only_their_own_firms_log(db):
    _apply(db, MIGRATION)
    # the other firm's Partner is a Partner of OTHER_FIRM: the one row of theirs is visible to them alone
    assert int(_as(db, "other_partner", "SELECT count(*) FROM audit_log WHERE firm_id = '%s';" % FIRM)) == 0
    assert int(_as(db, "other_partner", "SELECT count(*) FROM audit_log WHERE firm_id = '%s';" % OTHER_FIRM)) == 1


# ── the portal contacts ──────────────────────────────────────────────────────
def test_after_484_staff_see_only_the_contacts_of_clients_they_reach(db):
    _apply(db, MIGRATION)
    assert _contacts(db, "partner") == {"contact-a@m484.test", "contact-b@m484.test"}
    for who in STAFF_ASSIGNED_TO_A:
        assert _contacts(db, who) == {"contact-a@m484.test"}, who
    assert _contacts(db, "exec_unassigned") == set()
    assert _contacts(db, "suspended") == set()
    assert _contacts(db, "other_partner") == {"contact-other@m484.test"}


def test_a_portal_contact_still_reads_their_own_row_and_nobody_elses(db):
    """`client_portal_users_self` is what the client portal signs in through; the staff scope must not refuse it."""
    _apply(db, MIGRATION)
    assert _contacts(db, "portal_a") == {"contact-a@m484.test"}


def test_before_484_every_member_read_every_clients_contacts(db):
    """The template is built from every migration, 484 included, so 'before' is its own rollback."""
    _apply(db, ROLLBACK)
    for who in ("exec_unassigned", "reviewer"):
        assert _contacts(db, who) == {"contact-a@m484.test", "contact-b@m484.test"}, who


# ── the migration itself ─────────────────────────────────────────────────────
def test_484_is_idempotent(db):
    _apply(db, MIGRATION)
    _apply(db, MIGRATION)
    assert _audit_rows(db, "exec_unassigned") == 0
    assert _contacts(db, "exec_unassigned") == set()


def test_its_own_rollback_puts_both_holes_back(db):
    """The negative control: without it the assertions above would pass on a database that never had a hole."""
    _apply(db, MIGRATION)
    assert _audit_rows(db, "reviewer") == 0
    _apply(db, ROLLBACK)
    assert _audit_rows(db, "reviewer") == 2
    assert _contacts(db, "exec_unassigned") == {"contact-a@m484.test", "contact-b@m484.test"}
