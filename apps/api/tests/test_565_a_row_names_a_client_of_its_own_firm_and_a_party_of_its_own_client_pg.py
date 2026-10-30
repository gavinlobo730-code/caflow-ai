"""Migration 565 — a row names a client of its own firm, and a customer or vendor of its own client (ledger POST-A-304).

WHAT WAS WRONG
    The independent review of migration 528 inserted, as a Partner of firm G, rows with G's `firm_id` and the `client_id` of a client of
    firm F into sixteen tables: all accepted, because the Partner branch of the assignment scope short-circuits, the firm policy asks
    `firm_id` alone, and a foreign-key check bypasses row security. As an assigned Manager it stored a recurring template for its own
    client that named ANOTHER client's customer. Nothing is read across tenants by this, but the database stored a row whose client
    belongs to another firm.

WHAT THIS HOLDS (real Postgres)
    * THE REVIEW'S OWN CASE: a signed-in Partner of firm G inserting a row of G's naming F's client is refused by the trigger, in its own
      words, and the same statement is ACCEPTED with the trigger disabled (the negative control: the test sees the hole it closes).
    * An insert is judged as a STATEMENT: one bad row in a batch fails the whole batch.
    * An UPDATE that moves a row to another firm's client is refused; an update that does not touch the client or the firm is not asked
      anything, so a row that already breaks the rule can still be edited and can be repaired by moving it to a client of its own firm.
    * WHAT IT DELIBERATELY LEAVES ALONE: a client or a row with no firm at all, and a `client_id` that names no client (no tenant is
      crossed by either).
    * A customer or a vendor must belong to the row's own client, on insert and on update.
    * THE CATALOG: every table with a uuid `client_id` and `firm_id` carries both client triggers, every table with a foreign key to
      `customers` / `vendors` carries the party triggers, no party trigger sits where there is no such key, and nobody signed in may run
      the installer.
    * The apply-time report counts the rows that already break the rules and changes none of them; the migration is idempotent; its
      rollback takes every trigger away and the review's case goes through again.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
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
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

_STEM = "565_a_row_names_a_client_of_its_own_firm_and_a_party_of_its_own_client"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"

F = "56500000-0000-0000-0000-00000000000f"        # firm F
G = "56500000-0000-0000-0000-000000000009"        # firm G
C_F = "56500000-0000-0000-0000-0000000000f1"      # a client of F
C_G = "56500000-0000-0000-0000-0000000000a1"      # a client of G
C_G2 = "56500000-0000-0000-0000-0000000000a2"     # a second client of G
C_NOFIRM = "56500000-0000-0000-0000-0000000000e1"  # a client that belongs to no firm
CUST_G = "56500000-0000-0000-0000-0000000000c1"   # a customer of C_G
CUST_G2 = "56500000-0000-0000-0000-0000000000c2"  # a customer of C_G2
VEND_G = "56500000-0000-0000-0000-0000000000d1"   # a vendor of C_G
VEND_G2 = "56500000-0000-0000-0000-0000000000d2"  # a vendor of C_G2
PARTNER_AUTH = "56500000-1111-0000-0000-000000000001"
PARTNER_USER = "56500000-0000-0000-0000-00000000000b"
NOWHERE = "56500000-0000-0000-0000-0000000000ff"  # names no client

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the client-in-firm proof requires HARNESS_PG + psql",
)

CLIENT_TRIGGERS = ("row_client_in_firm_ins", "row_client_in_firm_upd")
PARTY_TRIGGERS = {
    "customer": ("row_customer_in_client_ins", "row_customer_in_client_upd"),
    "vendor": ("row_vendor_in_client_ins", "row_vendor_in_client_upd"),
}


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-f", "-"],
                          input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _signed_in_partner(sql: str, dsn: str) -> subprocess.CompletedProcess:
    claims = json.dumps({"sub": PARTNER_AUTH, "role": "authenticated"})
    return _psql(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")


def _run_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    """A migration file as the runner runs it: warnings kept (the runner keeps the `migration NNN:` ones)."""
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)],
                          capture_output=True, text=True, env={**os.environ, "PGOPTIONS": "-c client_min_messages=warning"})


def _proposal(firm: str, client: str, no: str = "P1") -> str:
    return f"INSERT INTO public.proposals (firm_id, client_id, proposal_no, title) VALUES ('{firm}', '{client}', '{no}', 't');"


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m565_{uuid.uuid4().hex[:10]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{PARTNER_AUTH}', 'partner@m565.test');
            INSERT INTO firms (id, name, email) VALUES ('{F}', 'M565 F', 'f@m565.test'), ('{G}', 'M565 G', 'g@m565.test');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                 VALUES ('{PARTNER_USER}', '{G}', '{PARTNER_AUTH}', 'partner@m565.test', 'P', 'Partner', true);
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
                ('{C_F}', '{F}', 'CF', 'Private Limited'), ('{C_G}', '{G}', 'CG', 'Private Limited'),
                ('{C_G2}', '{G}', 'CG2', 'Private Limited'), ('{C_NOFIRM}', NULL, 'CN', 'Private Limited');
            INSERT INTO customers (id, firm_id, client_id, name) VALUES
                ('{CUST_G}', '{G}', '{C_G}', 'cust G'), ('{CUST_G2}', '{G}', '{C_G2}', 'cust G2');
            INSERT INTO vendors (id, firm_id, client_id, name) VALUES
                ('{VEND_G}', '{G}', '{C_G}', 'vend G'), ('{VEND_G2}', '{G}', '{C_G2}', 'vend G2');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── the review's own case ─────────────────────────────────────────────────────────────────────────────────────────
def test_a_signed_in_partner_of_one_firm_cannot_store_a_row_naming_another_firms_client(db):
    r = _signed_in_partner(_proposal(G, C_F), db)
    assert r.returncode != 0 and "another firm" in r.stderr, r.stderr or "it succeeded"
    assert _ok(db, "SELECT count(*) FROM public.proposals;") == "0"


def test_the_same_statement_is_accepted_without_the_trigger_and_so_the_test_sees_the_hole(db):
    """The negative control. Row security lets the Partner of G write a row of G's and the foreign key lets it name any client."""
    _ok(db, "ALTER TABLE public.proposals DISABLE TRIGGER row_client_in_firm_ins;")
    r = _signed_in_partner(_proposal(G, C_F), db)
    assert r.returncode == 0, f"the review's case should be accepted with the trigger off: {r.stderr}"
    assert _ok(db, "SELECT count(*) FROM public.proposals;") == "1"


def test_a_signed_in_partner_still_stores_a_row_for_a_client_of_their_own_firm(db):
    r = _signed_in_partner(_proposal(G, C_G), db)
    assert r.returncode == 0, r.stderr


# ── an insert is judged as a statement ────────────────────────────────────────────────────────────────────────────
def test_one_bad_row_in_a_batch_fails_the_whole_batch(db):
    r = _psql(db, f"""INSERT INTO public.proposals (firm_id, client_id, proposal_no, title) VALUES
        ('{G}', '{C_G}', 'GOOD', 't'), ('{G}', '{C_F}', 'BAD', 't');""")
    assert r.returncode != 0 and "another firm" in r.stderr
    assert _ok(db, "SELECT count(*) FROM public.proposals;") == "0"


# ── an update ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_an_update_that_moves_a_row_to_another_firms_client_is_refused(db):
    _ok(db, _proposal(G, C_G))
    r = _psql(db, f"UPDATE public.proposals SET client_id = '{C_F}' WHERE proposal_no = 'P1';")
    assert r.returncode != 0 and "another firm" in r.stderr
    assert _ok(db, "SELECT client_id FROM public.proposals WHERE proposal_no = 'P1';") == C_G


def test_an_update_that_moves_a_row_to_another_firm_while_keeping_its_client_is_refused(db):
    _ok(db, _proposal(G, C_G))
    r = _psql(db, f"UPDATE public.proposals SET firm_id = '{F}' WHERE proposal_no = 'P1';")
    assert r.returncode != 0 and "another firm" in r.stderr


def test_a_row_that_already_breaks_the_rule_can_still_be_edited_and_repaired(db):
    """The triggers fire on writes that touch the client or the firm. A row found by the apply-time report is not bricked."""
    _ok(db, "ALTER TABLE public.proposals DISABLE TRIGGER row_client_in_firm_ins;")
    _ok(db, _proposal(G, C_F))
    _ok(db, "ALTER TABLE public.proposals ENABLE TRIGGER row_client_in_firm_ins;")
    _ok(db, "UPDATE public.proposals SET title = 'edited' WHERE proposal_no = 'P1';")
    _ok(db, f"UPDATE public.proposals SET client_id = '{C_F}' WHERE proposal_no = 'P1';")  # same value: not a change
    _ok(db, f"UPDATE public.proposals SET client_id = '{C_G}' WHERE proposal_no = 'P1';")  # the repair
    assert _ok(db, "SELECT client_id FROM public.proposals WHERE proposal_no = 'P1';") == C_G


# ── what it deliberately leaves alone ─────────────────────────────────────────────────────────────────────────────
def test_a_client_that_belongs_to_no_firm_is_not_refused(db):
    _ok(db, _proposal(G, C_NOFIRM))


def test_a_row_that_belongs_to_no_firm_is_not_refused(db):
    _ok(db, "ALTER TABLE public.proposals ALTER COLUMN firm_id DROP NOT NULL;")
    _ok(db, f"INSERT INTO public.proposals (firm_id, client_id, proposal_no, title) VALUES (NULL, '{C_F}', 'NOFIRM', 't');")


def test_a_client_id_that_names_no_client_is_not_refused(db):
    """Thirty-six of these tables have no foreign key to clients; an id that matches nothing cannot belong to another firm."""
    _ok(db, _proposal(G, NOWHERE))


# ── customers and vendors ─────────────────────────────────────────────────────────────────────────────────────────
def _receipt(client: str, customer: str, no: str = "R1") -> str:
    return (f"INSERT INTO public.receipts (firm_id, client_id, customer_id, receipt_no, receipt_date) "
            f"VALUES ('{G}', '{client}', '{customer}', '{no}', DATE '2026-04-01');")


def _purchase_order(client: str, vendor: str, no: str = "PO1") -> str:
    return (f"INSERT INTO public.purchase_orders (firm_id, client_id, vendor_id, document_no, document_date) "
            f"VALUES ('{G}', '{client}', '{vendor}', '{no}', DATE '2026-04-01');")


def test_a_row_naming_a_customer_of_another_client_is_refused_and_one_of_its_own_is_not(db):
    r = _psql(db, _receipt(C_G, CUST_G2))
    assert r.returncode != 0 and "another client" in r.stderr, r.stderr or "it succeeded"
    _ok(db, _receipt(C_G, CUST_G))


def test_a_row_naming_a_vendor_of_another_client_is_refused_and_one_of_its_own_is_not(db):
    r = _psql(db, _purchase_order(C_G, VEND_G2))
    assert r.returncode != 0 and "another client" in r.stderr, r.stderr or "it succeeded"
    _ok(db, _purchase_order(C_G, VEND_G))


def test_an_update_to_a_customer_or_vendor_of_another_client_is_refused(db):
    _ok(db, _receipt(C_G, CUST_G))
    r = _psql(db, f"UPDATE public.receipts SET customer_id = '{CUST_G2}' WHERE receipt_no = 'R1';")
    assert r.returncode != 0 and "another client" in r.stderr
    _ok(db, _purchase_order(C_G, VEND_G))
    r = _psql(db, f"UPDATE public.purchase_orders SET vendor_id = '{VEND_G2}' WHERE document_no = 'PO1';")
    assert r.returncode != 0 and "another client" in r.stderr


def test_moving_a_row_to_another_client_that_keeps_its_customer_is_refused(db):
    """Changing the CLIENT of a document whose customer stays is the same crossing seen from the other side."""
    _ok(db, _receipt(C_G, CUST_G))
    r = _psql(db, f"UPDATE public.receipts SET client_id = '{C_G2}' WHERE receipt_no = 'R1';")
    assert r.returncode != 0 and "another client" in r.stderr


# ── the catalog ───────────────────────────────────────────────────────────────────────────────────────────────────
def _tables_with_both_columns(db: str) -> set[str]:
    rows = _ok(db, """
        SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relkind = 'r'
           AND (SELECT count(*) FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attname IN ('client_id', 'firm_id')
                   AND a.atttypid = 'uuid'::regtype AND a.attnum > 0 AND NOT a.attisdropped) = 2;""")
    return set(rows.splitlines())


def _tables_with_trigger(db: str, name: str) -> set[str]:
    rows = _ok(db, f"SELECT tgrelid::regclass::text FROM pg_trigger WHERE NOT tgisinternal AND tgname = '{name}';")
    return {r.removeprefix("public.") for r in rows.splitlines()}


def _tables_with_party_key(db: str, party: str) -> set[str]:
    rows = _ok(db, f"""
        SELECT DISTINCT k.conrelid::regclass::text FROM pg_constraint k
         WHERE k.contype = 'f' AND k.confrelid = 'public.{party}s'::regclass
           AND k.conkey = ARRAY[(SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = k.conrelid AND a.attname = '{party}_id' AND NOT a.attisdropped)]
           AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = k.conrelid AND a.attname = 'client_id' AND NOT a.attisdropped);""")
    return {r.removeprefix("public.") for r in rows.splitlines()}


def test_every_table_with_a_client_and_a_firm_carries_both_client_triggers(db):
    tables = _tables_with_both_columns(db)
    assert len(tables) >= 200, f"only {len(tables)} tables found: the scan has stopped seeing the schema"
    for trigger in CLIENT_TRIGGERS:
        missing = sorted(tables - _tables_with_trigger(db, trigger))
        assert not missing, f"{trigger} is missing on: {missing}. Call public.guard_client_firm('<table>') in the migration that creates a table."
        assert not (_tables_with_trigger(db, trigger) - tables), f"{trigger} sits on a table that lacks client_id or firm_id"


@pytest.mark.parametrize("party", ["customer", "vendor"])
def test_every_table_with_a_foreign_key_to_the_party_carries_its_triggers_and_no_other_does(db, party):
    keyed = _tables_with_party_key(db, party)
    assert len(keyed) >= 8, f"only {len(keyed)} {party} tables found: the scan has stopped seeing the schema"
    for trigger in PARTY_TRIGGERS[party]:
        assert _tables_with_trigger(db, trigger) == keyed, trigger


def test_the_trigger_functions_pin_their_search_path_and_take_no_argument(db):
    rows = _ok(db, """
        SELECT p.proname, p.prosecdef, p.proconfig::text, p.pronargs
          FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace AND p.proname ~ '^assert_(inserted_rows|updated_row)_names?_a_(client|customer|vendor)_' ORDER BY 1;""")
    lines = rows.splitlines()
    assert len(lines) == 6, lines
    for line in lines:
        name, secdef, config, nargs = line.split("|")
        assert secdef == "t" and "search_path" in config and nargs == "0", line


def test_nobody_signed_in_may_run_the_installer(db):
    for role in ("anon", "authenticated", "public"):
        who = "0" if role == "public" else f"'{role}'"
        sql = (f"SELECT has_function_privilege({who}, 'public.guard_client_firm(regclass)', 'EXECUTE');" if role != "public"
               else "SELECT has_function_privilege(0::oid, 'public.guard_client_firm(regclass)', 'EXECUTE');")
        got = _ok(db, sql)
        assert got == "f", f"{role} may run public.guard_client_firm"


def test_the_installer_refuses_a_table_without_the_columns(db):
    r = _psql(db, "SELECT public.guard_client_firm('public.fx_rates'::regclass);")
    assert r.returncode != 0 and "has no uuid client_id and firm_id" in r.stderr


# ── the report, idempotence, the rollback ─────────────────────────────────────────────────────────────────────────
def test_the_apply_time_report_counts_what_already_breaks_the_rules_and_changes_none_of_it(db):
    _ok(db, "ALTER TABLE public.proposals DISABLE TRIGGER row_client_in_firm_ins;")
    _ok(db, _proposal(G, C_F))
    _ok(db, "ALTER TABLE public.proposals ENABLE TRIGGER row_client_in_firm_ins;")
    r = _run_file(db, MIGRATION)
    assert r.returncode == 0, r.stderr
    assert "migration 565:" in r.stderr and "1 existing row(s) in 1 table(s) already name a client of another firm" in r.stderr, r.stderr
    assert _ok(db, "SELECT count(*) FROM public.proposals;") == "1"


def test_a_clean_database_reports_none(db):
    r = _run_file(db, MIGRATION)
    assert r.returncode == 0, r.stderr
    assert "0 existing row(s) in 0 table(s) already name a client of another firm" in r.stderr
    assert "0 existing row(s) in 0 table(s) name a customer or vendor of another client" in r.stderr


def test_the_migration_is_idempotent(db):
    before = {t: _tables_with_trigger(db, t) for t in (*CLIENT_TRIGGERS, *PARTY_TRIGGERS["customer"], *PARTY_TRIGGERS["vendor"])}
    assert _run_file(db, MIGRATION).returncode == 0
    after = {t: _tables_with_trigger(db, t) for t in before}
    assert before == after


def test_the_rollback_takes_every_trigger_away_and_the_review_case_goes_through_again(db):
    r = _signed_in_partner(_proposal(G, C_F, "BEFORE"), db)
    assert r.returncode != 0, "refused while the triggers are on"
    back = _run_file(db, ROLLBACK)
    assert back.returncode == 0, back.stderr
    for trigger in (*CLIENT_TRIGGERS, *PARTY_TRIGGERS["customer"], *PARTY_TRIGGERS["vendor"]):
        assert _tables_with_trigger(db, trigger) == set(), trigger
    assert _ok(db, "SELECT count(*) FROM pg_proc WHERE proname = 'guard_client_firm' OR proname ~ '^assert_(inserted_rows|updated_row)_names?_a_(client|customer|vendor)_';") == "0"
    assert _signed_in_partner(_proposal(G, C_F, "AFTER"), db).returncode == 0, "the rollback should give the old behaviour back"
    assert _run_file(db, MIGRATION).returncode == 0
    assert _signed_in_partner(_proposal(G, C_F, "AGAIN"), db).returncode != 0
