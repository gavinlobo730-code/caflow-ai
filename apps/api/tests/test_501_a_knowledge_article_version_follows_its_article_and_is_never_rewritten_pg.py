"""Migration 501 — a knowledge-base version is visible only with its article, written only by the tier that writes the
article, and never rewritten or deleted by a signed-in session (ledger POST-A-009).

THE FIVE ARTICLES (one version row each), seen by each kind of member:
    FIRM      firm-wide article                            everybody in the firm
    CLIENT_A  article of client A                          Partner, Manager (079: firm-wide) and staff assigned to A
    CLIENT_B  article of client B                          Partner and Manager; NOT an Executive assigned only to A
    INTERNAL  article of the practice's own internal client  Partner only (079, G1)
    OTHER     an article of ANOTHER firm                    nobody here

WHAT IS HELD
    * `authenticated` holds SELECT and INSERT on the table and nothing else (the API only reads and appends), `anon` holds
      nothing, `service_role` keeps its four;
    * a version is readable exactly when its article is: an Executive assigned to A reads the versions of FIRM and CLIENT_A
      and not CLIENT_B or INTERNAL; a Manager reads all but INTERNAL; a Partner reads all four of the firm's; the other firm's
      Partner reads none of these;
    * appending a version needs the article's write tier: a Manager appends to CLIENT_A, is refused for INTERNAL (the article is
      invisible to them) and an Executive is refused even for an article they can see; nobody appends to another firm's;
    * UPDATE and DELETE are refused by the PRIVILEGE ("permission denied for table"), history is unchanged afterwards;
    * deleting an article (what a foreign-key cascade does) still removes its versions, so the revoke broke no integrity rule;
    * the migration removes what the platform grants and what reaches a role through PUBLIC or a column grant, FAILS when
      another grantor's grant cannot be revoked, is idempotent, and its own rollback puts the holes back (the negative control:
      the Executive then reads CLIENT_B's text, a Manager rewrites a version and the Executive appends one).

Runs only when HARNESS_PG is set + psql on PATH.
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
_STEM = "501_a_knowledge_article_version_follows_its_article_and_is_never_rewritten"
MIGRATION = API_ROOT / "migrations" / f"{_STEM}.sql"
ROLLBACK = API_ROOT / "migrations" / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the knowledge-version proofs require HARNESS_PG + psql",
)

TABLE = "knowledge_article_versions"
FIRM, FIRM2 = "aaaaaaaa-0000-0000-0000-000000000501", "aaaaaaaa-0000-0000-0000-000000000502"
CLIENT_A, CLIENT_B, INTERNAL = (f"cccccccc-0000-0000-0000-00000000a50{i}" for i in (1, 2, 3))
AUTH = {n: f"11111111-1111-1111-1111-00000000050{i}" for i, n in enumerate(
    ("partner", "manager", "executive", "other_partner"), 1)}
USER = {n: f"bbbbbbbb-1111-1111-1111-00000000050{i}" for i, n in enumerate(
    ("partner", "manager", "executive", "other_partner"), 1)}
ART = {n: f"dddddddd-0000-0000-0000-00000000050{i}" for i, n in enumerate(
    ("firm", "client_a", "client_b", "internal", "other"), 1)}


def _psql(dsn: str, sql: str, tuples: bool = True) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else []) + ["-f", "-"]
    return subprocess.run(args, input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _as(who: str, dsn: str, sql: str) -> subprocess.CompletedProcess:
    claims = json.dumps({"sub": AUTH[who], "role": "authenticated"})
    return _psql(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")


def _readable(who: str, dsn: str) -> set[str]:
    """The article keys whose version row the member can read."""
    r = _as(who, dsn, f"SELECT article_id FROM {TABLE};")
    assert r.returncode == 0, r.stderr
    seen = {line.strip() for line in r.stdout.splitlines() if line.strip() and not line.startswith("SET")}
    return {k for k, v in ART.items() if v in seen}


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"kav_m501_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES
              ('{AUTH['partner']}','p@m501.test'), ('{AUTH['manager']}','m@m501.test'),
              ('{AUTH['executive']}','e@m501.test'), ('{AUTH['other_partner']}','x@m501.test');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M501 Firm','m501@test.in'),
              ('{FIRM2}','M501 Other','m501b@test.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
              ('{CLIENT_A}','{FIRM}','Client A','Private Limited'), ('{CLIENT_B}','{FIRM}','Client B','Private Limited'),
              ('{INTERNAL}','{FIRM}','The practice','Partnership');
            UPDATE firms SET internal_client_id = '{INTERNAL}' WHERE id = '{FIRM}';
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES
              ('{USER['partner']}','{FIRM}','{AUTH['partner']}','p@m501.test','P','Partner',true),
              ('{USER['manager']}','{FIRM}','{AUTH['manager']}','m@m501.test','M','Manager',true),
              ('{USER['executive']}','{FIRM}','{AUTH['executive']}','e@m501.test','E','Executive',true),
              ('{USER['other_partner']}','{FIRM2}','{AUTH['other_partner']}','x@m501.test','X','Partner',true);
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES
              ('{FIRM}','{USER['manager']}','{CLIENT_A}'), ('{FIRM}','{USER['executive']}','{CLIENT_A}');
            INSERT INTO knowledge_articles (id, firm_id, scope, client_id, title) VALUES
              ('{ART['firm']}','{FIRM}','firm',NULL,'Firm article'),
              ('{ART['client_a']}','{FIRM}','client','{CLIENT_A}','A article'),
              ('{ART['client_b']}','{FIRM}','client','{CLIENT_B}','B article'),
              ('{ART['internal']}','{FIRM}','client','{INTERNAL}','Internal article'),
              ('{ART['other']}','{FIRM2}','firm',NULL,'Other firm article');
            INSERT INTO {TABLE} (firm_id, article_id, version, content) VALUES
              ('{FIRM}','{ART['firm']}',1,'v1'), ('{FIRM}','{ART['client_a']}',1,'v1'),
              ('{FIRM}','{ART['client_b']}',1,'v1'), ('{FIRM}','{ART['internal']}',1,'v1'),
              ('{FIRM2}','{ART['other']}',1,'v1');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _holds(dsn: str, role: str, op: str) -> bool:
    return _ok(dsn, f"SELECT has_table_privilege('{role}', 'public.{TABLE}', '{op}');") == "t"


def _append(who: str, dsn: str, article: str, firm: str = FIRM, version: int = 2) -> subprocess.CompletedProcess:
    return _as(who, dsn, f"INSERT INTO {TABLE} (firm_id, article_id, version, content) "
                         f"VALUES ('{firm}', '{ART[article]}', {version}, 'edited');")


# ── privileges ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_signed_in_role_can_read_and_append_and_nothing_else_and_the_api_keeps_its_own(db):
    for op in ("SELECT", "INSERT"):
        assert _holds(db, "authenticated", op), f"authenticated lost {op}, which the API needs"
    for op in ("UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
        assert not _holds(db, "authenticated", op), f"authenticated still holds {op}"
    assert _ok(db, f"SELECT has_any_column_privilege('authenticated', 'public.{TABLE}', 'UPDATE');") == "f"
    for op in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
        assert not _holds(db, "anon", op), f"anon holds {op}"
    for op in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert _holds(db, "service_role", op), f"service_role lost {op}"


# ── visibility follows the article ────────────────────────────────────────────────────────────────────────────────────

def test_an_executive_assigned_to_one_client_reads_only_the_versions_of_articles_they_can_see(db):
    assert _readable("executive", db) == {"firm", "client_a"}


def test_a_manager_reads_every_client_article_but_not_the_practices_own(db):
    assert _readable("manager", db) == {"firm", "client_a", "client_b"}


def test_a_partner_reads_all_of_their_firms_versions_and_not_another_firms(db):
    assert _readable("partner", db) == {"firm", "client_a", "client_b", "internal"}
    assert _readable("other_partner", db) == {"other"}


# ── appending needs the article's write tier ──────────────────────────────────────────────────────────────────────────

def test_a_manager_appends_a_version_to_an_article_they_can_see(db):
    r = _append("manager", db, "client_a")
    assert r.returncode == 0, r.stderr
    assert _ok(db, f"SELECT count(*) FROM {TABLE} WHERE article_id = '{ART['client_a']}';") == "2"


def test_a_manager_cannot_append_to_the_practices_own_article_or_to_another_firms(db):
    r = _append("manager", db, "internal")
    assert r.returncode != 0 and "row-level security" in r.stderr, r.stderr or "it succeeded"
    r = _append("manager", db, "other", firm=FIRM2)
    assert r.returncode != 0 and "row-level security" in r.stderr, r.stderr or "it succeeded"
    assert _ok(db, f"SELECT count(*) FROM {TABLE};") == "5"


def test_an_executive_cannot_append_even_to_an_article_they_can_see(db):
    r = _append("executive", db, "client_a")
    assert r.returncode != 0 and "row-level security" in r.stderr, r.stderr or "it succeeded"
    assert _ok(db, f"SELECT count(*) FROM {TABLE};") == "5"


def test_a_version_cannot_claim_another_firm_than_its_article_belongs_to(db):
    r = _as("manager", db, f"INSERT INTO {TABLE} (firm_id, article_id, version, content) "
                           f"VALUES ('{FIRM2}', '{ART['client_a']}', 2, 'x');")
    assert r.returncode != 0 and "row-level security" in r.stderr, r.stderr or "it succeeded"


# ── history is never rewritten ────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("who", ["partner", "manager"])
def test_nobody_signed_in_rewrites_or_deletes_a_version(db, who):
    for sql in (f"UPDATE {TABLE} SET content = 'rewritten';",
                f"DELETE FROM {TABLE};",
                f"TRUNCATE {TABLE};"):
        r = _as(who, db, sql)
        assert r.returncode != 0 and "permission denied for table" in r.stderr, (sql, r.stderr or "it succeeded")
    assert _ok(db, f"SELECT count(*) FROM {TABLE} WHERE content = 'v1';") == "5"


def test_deleting_an_article_still_removes_its_versions(db):
    """What a foreign-key cascade does (the client delete, the firm delete): the revoke is not a privilege of the caller there."""
    _ok(db, f"DELETE FROM knowledge_articles WHERE id = '{ART['client_a']}';")
    assert _ok(db, f"SELECT count(*) FROM {TABLE} WHERE article_id = '{ART['client_a']}';") == "0"


def test_the_two_restrictive_policies_and_row_security_are_in_place(db):
    assert _ok(db, f"SELECT count(*) FROM pg_policies WHERE schemaname = 'public' AND tablename = '{TABLE}' "
                   "AND permissive = 'RESTRICTIVE' AND policyname IN "
                   "('knowledge_article_versions_article_visible', 'knowledge_article_versions_role_insert');") == "2"
    assert _ok(db, f"SELECT relrowsecurity FROM pg_class WHERE oid = 'public.{TABLE}'::regclass;") == "t"
    assert _ok(db, f"SELECT count(*) FROM pg_policies WHERE schemaname = 'public' AND tablename = '{TABLE}' "
                   "AND policyname = 'knowledge_article_versions_own_firm';") == "1"


# ── what the API does with it, as a Manager on their own JWT ──────────────────────────────────────────────────────────

def test_the_statements_the_knowledge_service_issues_still_work_for_a_manager(db):
    """`services/knowledge_service` runs on the caller's own sign-in (`db_provider.request_db`) and issues exactly these
    statements: create (article, then its first version, each answered with the row it wrote, which is why the new
    version must be READABLE by the policy that gates it), edit (a new version, then the pointer), restore (read a version,
    append it as the next), the current content and the history list. A policy that broke one of them would break the
    knowledge base for every Manager and Partner."""
    new_article = "dddddddd-0000-0000-0000-0000000005ff"
    r = _as("manager", db, f"""
        INSERT INTO knowledge_articles (id, firm_id, scope, client_id, title, current_version, tags, is_archived, created_by)
          VALUES ('{new_article}', '{FIRM}', 'client', '{CLIENT_A}', 'New', 1, '{{}}', false, '{USER['manager']}') RETURNING id;
        INSERT INTO {TABLE} (firm_id, article_id, version, content, changed_by)
          VALUES ('{FIRM}', '{new_article}', 1, 'first', '{USER['manager']}') RETURNING version;
        INSERT INTO {TABLE} (firm_id, article_id, version, content, changed_by)
          VALUES ('{FIRM}', '{new_article}', 2, 'second', '{USER['manager']}') RETURNING version;
        UPDATE knowledge_articles SET current_version = 2, updated_at = now() WHERE id = '{new_article}' RETURNING current_version;
        SELECT content FROM {TABLE} WHERE article_id = '{new_article}' AND version = 1 LIMIT 1;
        INSERT INTO {TABLE} (firm_id, article_id, version, content, changed_by)
          VALUES ('{FIRM}', '{new_article}', 3, 'first', '{USER['manager']}') RETURNING version;
        SELECT version, changed_by, changed_at FROM {TABLE} WHERE article_id = '{new_article}' ORDER BY version DESC;
    """)
    assert r.returncode == 0, r.stderr
    assert _ok(db, f"SELECT count(*) FROM {TABLE} WHERE article_id = '{new_article}';") == "3"
    assert _ok(db, f"SELECT content FROM {TABLE} WHERE article_id = '{new_article}' AND version = 3;") == "first"


# ── the migration itself ──────────────────────────────────────────────────────────────────────────────────────────────

def test_501_removes_what_the_platform_grants_and_what_reaches_a_role_another_way(db):
    """The throwaway database holds none of the platform's default privileges, so the TRUNCATE and `anon` halves of the
    REVOKE would otherwise be exercised by nothing. Give them, plus a write through PUBLIC and through a column grant,
    then apply the migration."""
    _ok(db, f"""
        GRANT TRUNCATE, REFERENCES, TRIGGER ON public.{TABLE} TO authenticated, anon;
        GRANT SELECT, INSERT, UPDATE, DELETE ON public.{TABLE} TO anon;
        GRANT DELETE ON public.{TABLE} TO PUBLIC;
        GRANT UPDATE (content) ON public.{TABLE} TO authenticated;
    """)
    assert _holds(db, "anon", "TRUNCATE") and _holds(db, "authenticated", "DELETE")
    r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
    for op in ("UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
        assert not _holds(db, "authenticated", op), f"authenticated still holds {op}"
    assert _ok(db, f"SELECT has_any_column_privilege('authenticated', 'public.{TABLE}', 'UPDATE');") == "f"
    for op in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
        assert not _holds(db, "anon", op), f"anon still holds {op}"
    assert _holds(db, "authenticated", "SELECT") and _holds(db, "authenticated", "INSERT")
    assert _holds(db, "service_role", "UPDATE")


def test_the_closing_check_fails_the_migration_when_a_privilege_cannot_be_revoked(db):
    """A grant made by another grantor (a role holding GRANT OPTION) is not the owner's to take back; the migration must
    fail, and so the deploy, not finish green with history still rewritable."""
    grantor = f"m501_g_{uuid.uuid4().hex[:8]}"
    _ok(db, f"""
        CREATE ROLE {grantor} NOLOGIN;
        GRANT UPDATE ON public.{TABLE} TO {grantor} WITH GRANT OPTION;
        SET ROLE {grantor};
        GRANT UPDATE ON public.{TABLE} TO authenticated;
        RESET ROLE;
    """)
    try:
        r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
        assert r.returncode != 0 and f"migration 501: authenticated still holds UPDATE on {TABLE}" in r.stderr, (
            r.stdout, r.stderr)
    finally:
        _psql(db, f"DROP OWNED BY {grantor}; DROP ROLE IF EXISTS {grantor};")


def test_501_is_idempotent(db):
    for _ in range(2):
        r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
        assert r.returncode == 0, r.stderr
    assert not _holds(db, "authenticated", "UPDATE")
    assert _readable("executive", db) == {"firm", "client_a"}


def test_its_own_rollback_puts_the_holes_back(db):
    """The negative control: without the policies and the revoke, the statements refused above go through."""
    r = _psql(db, ROLLBACK.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
    assert "client_b" in _readable("executive", db), "the Executive should read an unassigned client's article text again"
    assert _append("executive", db, "client_a").returncode == 0, "the Executive should append again"
    wrote = _as("manager", db, f"UPDATE {TABLE} SET content = 'rewritten' WHERE article_id = '{ART['client_a']}' AND version = 1;")
    assert wrote.returncode == 0, wrote.stderr
    assert _ok(db, f"SELECT content FROM {TABLE} WHERE article_id = '{ART['client_a']}' AND version = 1;") == "rewritten"
