"""Migration 768 — a deleted client's portal contact is nobody's contact to the DATABASE either (POST-A-503).

THE GAP. POST-A-447 closed the API door: the one function every client-portal route resolves its principal through drops a
client whose `deleted_at` is set. The policies a signed-in contact meets through PostgREST were not touched: ten of them on four
tables read the contact's membership with an inline subquery and never looked at the client's `deleted_at`, and
`my_portal_client_ids()`, which every other portal branch of every policy is built on, did the same. A contact of a deleted
client who still held a valid session could read the client's portal messages and fee invoices and write portal messages with
the public key and their own token. (Shared reports, documents and document requests were never reachable that way by a
contact: shared_reports by its restrictive assignment-scope policy, which has no portal branch, and the other two since migration
551 took the signed-in role's privileges. Their policies are brought in line anyway, so the rule below holds over all ten.)

WHAT IS PROVEN, AS A SIGNED-IN CONTACT (the rows, not the helper's answer):
  * a contact of a LIVE client reads their messages and their fee invoices and posts a message;
  * a contact of a DELETED client reads none of them and cannot post: both of the two ways of being a contact (the
    `client_portal_users` row, and the legacy `clients.portal_user_id` link);
  * a contact of two clients, one deleted, reads only the live one's;
  * an ARCHIVED client is untouched (the decision recorded with POST-A-447: archiving is the practice putting a client aside);
  * the check is on the client's LIVE state: restoring the client gives the contact their rows back;
  * ONE RULE OVER THE WHOLE CATALOGUE: no policy in `public` reads the contact table directly any more (they ask a function),
    every policy that names the legacy link also tests the client's deletion, and every function that answers who a portal
    contact is tests it, so the next policy or function written cannot forget the deletion.

NEGATIVE CONTROL (run by hand when written): with the migration's function and ten policies replaced by migration 443's bodies,
every "deleted" assertion fails and the live ones still pass.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
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
    reason="the deleted-client portal proof requires HARNESS_PG + psql",
)

FIRM = "f7680000-0000-0000-0000-000000000001"
INTERNAL = "c7680000-0000-0000-0000-0000000000a0"      # the practice's own client: it issues the fee invoices
LIVE = "c7680000-0000-0000-0000-0000000000a1"
GONE = "c7680000-0000-0000-0000-0000000000a2"          # deleted
ARCHIVED = "c7680000-0000-0000-0000-0000000000a3"      # archived, not deleted
LEGACY_LIVE = "c7680000-0000-0000-0000-0000000000a4"   # reached by clients.portal_user_id
LEGACY_GONE = "c7680000-0000-0000-0000-0000000000a5"   # ... and deleted

A_LIVE = "a7680000-0000-0000-0000-0000000000b1"        # contact of LIVE
A_GONE = "a7680000-0000-0000-0000-0000000000b2"        # contact of GONE
A_ARCH = "a7680000-0000-0000-0000-0000000000b3"        # contact of ARCHIVED
A_BOTH = "a7680000-0000-0000-0000-0000000000b4"        # contact of LIVE and GONE
A_LEG_LIVE = "a7680000-0000-0000-0000-0000000000b5"
A_LEG_GONE = "a7680000-0000-0000-0000-0000000000b6"

CUSTOMERS = {LIVE: "d7680000-0000-0000-0000-0000000000c1", GONE: "d7680000-0000-0000-0000-0000000000c2",
             LEGACY_LIVE: "d7680000-0000-0000-0000-0000000000c4", LEGACY_GONE: "d7680000-0000-0000-0000-0000000000c5"}


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _as(auth: str) -> str:
    return f"SET request.jwt.claims = '{{\"sub\": \"{auth}\", \"role\": \"authenticated\"}}'; SET ROLE authenticated; "


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m768_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create a throwaway database")
    dsn = f"{admin} dbname={name}"
    try:
        auths = [A_LIVE, A_GONE, A_ARCH, A_BOTH, A_LEG_LIVE, A_LEG_GONE]
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES
              {", ".join(f"('{a}', 'c{i}@m768.in')" for i, a in enumerate(auths))};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'M768', 'm768@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type, deleted_at, is_archived, portal_user_id) VALUES
              ('{INTERNAL}', '{FIRM}', 'The Practice', 'Private Limited', NULL, false, NULL),
              ('{LIVE}', '{FIRM}', 'Live Co', 'Private Limited', NULL, false, NULL),
              ('{GONE}', '{FIRM}', 'Gone Co', 'Private Limited', now(), false, NULL),
              ('{ARCHIVED}', '{FIRM}', 'Archived Co', 'Private Limited', NULL, true, NULL),
              ('{LEGACY_LIVE}', '{FIRM}', 'Legacy Live', 'Private Limited', NULL, false, '{A_LEG_LIVE}'),
              ('{LEGACY_GONE}', '{FIRM}', 'Legacy Gone', 'Private Limited', now(), false, '{A_LEG_GONE}');
            INSERT INTO client_portal_users (firm_id, client_id, auth_user_id, email, status) VALUES
              ('{FIRM}', '{LIVE}', '{A_LIVE}', 'l@m768.in', 'active'),
              ('{FIRM}', '{GONE}', '{A_GONE}', 'g@m768.in', 'active'),
              ('{FIRM}', '{ARCHIVED}', '{A_ARCH}', 'a@m768.in', 'active'),
              ('{FIRM}', '{LIVE}', '{A_BOTH}', 'b1@m768.in', 'active'),
              ('{FIRM}', '{GONE}', '{A_BOTH}', 'b2@m768.in', 'active');
            INSERT INTO portal_messages (firm_id, client_id, sender_type, sender_name, body) VALUES
              {", ".join(f"('{FIRM}', '{c}', 'ca', 'Practice', 'hello {i}')" for i, c in enumerate([LIVE, GONE, ARCHIVED, LEGACY_LIVE, LEGACY_GONE]))};
            INSERT INTO shared_reports (firm_id, client_id, report_type, report_label, financial_year, storage_path, file_name) VALUES
              {", ".join(f"('{FIRM}', '{c}', 'pl', 'P&L', '2025-26', '{c}/pl.pdf', 'pl.pdf')" for c in [LIVE, GONE, ARCHIVED, LEGACY_LIVE, LEGACY_GONE])};
            INSERT INTO customers (id, firm_id, client_id, name) VALUES
              {", ".join(f"('{cid}', '{FIRM}', '{INTERNAL}', 'Customer for {c[-2:]}')" for c, cid in CUSTOMERS.items())};
            INSERT INTO client_firm_customer_links (firm_id, client_id, internal_customer_id) VALUES
              {", ".join(f"('{FIRM}', '{c}', '{cid}')" for c, cid in CUSTOMERS.items())};
            INSERT INTO client_sales_invoices (firm_id, client_id, customer_id, invoice_no, invoice_date) VALUES
              {", ".join(f"('{FIRM}', '{INTERNAL}', '{cid}', 'FEE-{c[-2:]}', '2026-04-30')" for c, cid in CUSTOMERS.items())};
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _n(dsn: str, auth: str, table: str) -> int:
    r = _psql(dsn, _as(auth) + f"SELECT count(*) FROM public.{table};", tuples=True)
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip().splitlines()[-1])


def _post(dsn: str, auth: str, client: str) -> subprocess.CompletedProcess:
    return _psql(dsn, _as(auth) + f"INSERT INTO portal_messages (firm_id, client_id, sender_type, sender_name, body) "
                                  f"VALUES ('{FIRM}', '{client}', 'client', 'Contact', 'from the portal');")


def _ids(dsn: str, auth: str) -> set[str]:
    r = _psql(dsn, _as(auth) + "SELECT public.my_portal_client_ids();", tuples=True)
    assert r.returncode == 0, r.stderr
    return {l.strip() for l in r.stdout.splitlines() if l.strip() and not l.startswith("SET")}


# ── a contact of a live client keeps everything ──────────────────────────────────────────────────────────────────────
def test_a_contact_of_a_live_client_reads_and_posts(db):
    assert _n(db, A_LIVE, "portal_messages") == 1
    assert _n(db, A_LIVE, "client_sales_invoices") == 1
    assert _post(db, A_LIVE, LIVE).returncode == 0
    assert _ids(db, A_LIVE) == {LIVE}


def test_a_contact_of_a_live_client_by_the_legacy_link_reads_their_fee_invoice(db):
    """The legacy link reaches the fee tables through my_portal_client_ids(); its portal-message policy reads `clients` under the
    caller's own row security, as it did before this migration, and is not asserted here (this migration does not widen it)."""
    assert _n(db, A_LEG_LIVE, "client_sales_invoices") == 1
    assert _ids(db, A_LEG_LIVE) == {LEGACY_LIVE}


# ── a contact of a deleted client is nobody ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("auth", [A_GONE, A_LEG_GONE], ids=["contact row", "legacy link"])
def test_a_contact_of_a_deleted_client_reads_nothing_and_posts_nothing(db, auth):
    assert _n(db, auth, "portal_messages") == 0
    assert _n(db, auth, "client_sales_invoices") == 0, "the fee invoice of a deleted client is still readable by its contact"
    assert _ids(db, auth) == set()
    client = GONE if auth == A_GONE else LEGACY_GONE
    refused = _post(db, auth, client)
    assert refused.returncode != 0 and "row-level security" in refused.stderr


def test_the_rows_are_still_there_for_the_practice(db):
    """The fix hides them from the contact; nothing was deleted."""
    admin_view = _psql(db, "SELECT count(*) FROM portal_messages WHERE client_id IN "
                           f"('{GONE}', '{LEGACY_GONE}');", tuples=True)
    assert admin_view.stdout.strip() == "2"


def test_a_contact_of_two_clients_reads_only_the_live_ones(db):
    assert _ids(db, A_BOTH) == {LIVE}
    assert _n(db, A_BOTH, "portal_messages") == 1
    assert _post(db, A_BOTH, GONE).returncode != 0
    assert _post(db, A_BOTH, LIVE).returncode == 0


def test_an_archived_client_is_untouched(db):
    assert _ids(db, A_ARCH) == {ARCHIVED}
    assert _n(db, A_ARCH, "portal_messages") == 1


def test_restoring_the_client_gives_the_contact_their_rows_back(db):
    assert _n(db, A_GONE, "portal_messages") == 0
    assert _psql(db, f"UPDATE clients SET deleted_at = NULL WHERE id = '{GONE}';").returncode == 0
    assert _n(db, A_GONE, "portal_messages") == 1
    assert _ids(db, A_GONE) == {GONE}


# ── one rule over the catalogue ──────────────────────────────────────────────────────────────────────────────────────
def test_no_policy_reads_the_contact_table_directly_and_every_legacy_link_read_tests_the_deletion(db):
    """A policy that names the membership itself is a policy that can forget the deletion. The contact-table reads all go
    through the one function; the legacy link, read inline as it always was, now tests the client's deletion in every policy."""
    r = _psql(db, "SELECT tablename || '.' || policyname FROM pg_policies WHERE schemaname = 'public' "
                  "AND (coalesce(qual, '') || coalesce(with_check, '')) ~ 'client_portal_users' ORDER BY 1;", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "", f"these policies read the contact table themselves, not through the function:\n{r.stdout}"
    r = _psql(db, "SELECT tablename || '.' || policyname FROM pg_policies WHERE schemaname = 'public' "
                  "AND (coalesce(qual, '') || coalesce(with_check, '')) ~ 'portal_user_id' "
                  "AND (coalesce(qual, '') || coalesce(with_check, '')) !~ 'deleted_at' ORDER BY 1;", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "", f"these policies read the legacy portal link and never ask whether the client is deleted:\n{r.stdout}"


def test_every_function_that_answers_who_is_a_portal_contact_tests_the_deletion(db):
    r = _psql(db, "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public' "
                  "AND p.prokind = 'f' AND pg_get_functiondef(p.oid) ~ 'client_portal_users|portal_user_id' "
                  "AND pg_get_functiondef(p.oid) !~ 'deleted_at' ORDER BY 1;", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "", f"these functions read the portal membership and never ask whether the client is deleted:\n{r.stdout}"


def test_the_two_functions_keep_the_privileges_of_the_family(db):
    r = _psql(db, "SELECT p.proname, has_function_privilege('authenticated', p.oid, 'EXECUTE'), "
                  "has_function_privilege('anon', p.oid, 'EXECUTE'), p.prosecdef "
                  "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                  "WHERE n.nspname = 'public' AND p.proname IN ('my_portal_client_ids', 'my_portal_contact_client_ids') ORDER BY 1;",
              tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines() == ["my_portal_client_ids|t|f|t", "my_portal_contact_client_ids|t|f|t"]
