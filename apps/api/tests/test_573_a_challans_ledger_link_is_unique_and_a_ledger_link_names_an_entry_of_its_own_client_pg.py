"""Migration 573 — one ledger entry pays one TDS challan, and a stored link to a ledger entry names an entry of the row's own client
(POST-A-272, fixes from the independent review of migration 568).

WHAT WAS WRONG
    * "One entry cannot be the payment of two challans" was a read followed by a write; the index 568 added was a lookup, not a rule.
    * A foreign-key check bypasses row security, so `tds_challans.journal_entry_id` (and the older `statutory_remittances.journal_entry_id`)
      was satisfied by ANY entry in the database; only the API asked whose the entry was.
    * 568's header claimed that reversing the payment entry unlinks the challan. It does not: `ON DELETE SET NULL` fires on a hard delete.

WHAT THIS HOLDS (real Postgres)
    * THE RACE'S LAST WORD: a second challan tied to an entry that already pays one is refused by the database (23505, the index's name), the
      same statement is ACCEPTED with the unique index dropped (the negative control: the test sees the hole it closes), two challans with
      no link are still fine (a partial index), and a challan can be tied again once the first is untied;
    * THE TENANT RULE on both tables: an entry of another client or another firm is refused on insert and on an update that points the
      column at it or moves the row to another client, in the trigger's words (P0001, never the 42501 the API words as our fault), the
      same statement is accepted with the trigger off, the row's own client's entry is accepted, no link at all is accepted, a missing
      entry is left to the foreign key, and an update that touches neither the link nor the firm nor the client is not asked anything,
      so a row that already breaks the rule can still be edited and repaired;
    * the installer refuses a column that is not a uuid, a key to something else, or a table without its own firm and client, and nobody
      signed in may run it;
    * the apply-time report counts the rows that already break the rule and changes none; if an entry is already tied to two challans the
      file stops in words; the file can be run again; its rollback takes the guards and the unique index away, puts 568's plain index back,
      and runs before 568's own rollback.

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

_STEM = "573_a_challans_ledger_link_is_unique_and_a_ledger_link_names_an_entry_of_its_own_client"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"
ROLLBACK_568 = next(MIGRATIONS.glob("568_*_rollback.sql"))

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the challan ledger-link proof requires HARNESS_PG + psql",
)

F = "57300000-0000-0000-0000-00000000000f"
G = "57300000-0000-0000-0000-000000000009"
C1 = "57300000-0000-0000-0000-0000000000c1"        # firm F
C2 = "57300000-0000-0000-0000-0000000000c2"        # firm F
CG = "57300000-0000-0000-0000-0000000000c9"        # firm G
JE1 = "57300000-0000-0000-0000-0000000000e1"       # C1's
JE2 = "57300000-0000-0000-0000-0000000000e2"       # C1's
JE_C2 = "57300000-0000-0000-0000-0000000000e3"     # C2's, same firm
JE_G = "57300000-0000-0000-0000-0000000000e4"      # CG's, another firm
CH1 = "57300000-0000-0000-0000-0000000000a1"
CH2 = "57300000-0000-0000-0000-0000000000a2"
NOWHERE = "57300000-0000-0000-0000-0000000000ff"
PARTNER_AUTH = "57300000-0000-0000-0000-0000000000d1"       # a signed-in Partner of firm F
PARTNER_USER = "57300000-0000-0000-0000-0000000000d2"
WORDS = "another client or firm"
UNIQUE_INDEX = "uq_tds_challans_journal_entry"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-f", "-"],
                          input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _run_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)],
                          capture_output=True, text=True, env={**os.environ, "PGOPTIONS": "-c client_min_messages=warning"})


def _challan(cid: str, client: str, no: str, link: str | None = None, firm: str = F) -> str:
    j = f"'{link}'" if link else "NULL"
    return (f"INSERT INTO public.tds_challans (id, firm_id, client_id, bsr_code, challan_no, payment_date, quarter, financial_year, "
            f"tds_paise, total_paise, section, journal_entry_id) VALUES ('{cid}', '{firm}', '{client}', '0510001', '{no}', '2026-07-05', "
            f"'Q1', '2026-27', 1250000, 1250000, '194C', {j});")


def _remittance(client: str, wage_month: str, link: str | None = None, firm: str = F) -> str:
    j = f"'{link}'" if link else "NULL"
    return (f"INSERT INTO public.statutory_remittances (firm_id, client_id, scheme, wage_month, contribution_period, submitted_on, "
            f"journal_entry_id) VALUES ('{firm}', '{client}', 'esic', '{wage_month}', '2026-H1', '2026-07-05', {j});")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m573_{uuid.uuid4().hex[:10]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert MIGRATION.name not in pg_template.failed, "migration 573 did not apply, so everything below would pass vacuously"
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{F}', 'M573 F', 'f@m573.test'), ('{G}', 'M573 G', 'g@m573.test');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
                ('{C1}', '{F}', 'C1', 'Private Limited'), ('{C2}', '{F}', 'C2', 'Private Limited'), ('{CG}', '{G}', 'CG', 'Private Limited');
            INSERT INTO auth.users (id, email) VALUES ('{PARTNER_AUTH}', 'partner@m573.test');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                 VALUES ('{PARTNER_USER}', '{F}', '{PARTNER_AUTH}', 'partner@m573.test', 'P', 'Partner', true);
            INSERT INTO journal_entries (id, firm_id, client_id, entry_date, narration, entry_type, is_posted, status) VALUES
                ('{JE1}', '{F}', '{C1}', '2026-07-05', 'tds paid', 'Payment', true, 'posted'),
                ('{JE2}', '{F}', '{C1}', '2026-07-06', 'tds paid again', 'Payment', true, 'posted'),
                ('{JE_C2}', '{F}', '{C2}', '2026-07-05', 'other client', 'Payment', true, 'posted'),
                ('{JE_G}', '{G}', '{CG}', '2026-07-05', 'other firm', 'Payment', true, 'posted');
        """)
        assert seed.returncode == 0, seed.stderr
        for sql in (_challan(CH1, C1, "00045"), _challan(CH2, C1, "00046")):
            assert _psql(dsn, sql).returncode == 0
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _signed_in_partner(db: str, sql: str) -> subprocess.CompletedProcess:
    claims = json.dumps({"sub": PARTNER_AUTH, "role": "authenticated"})
    return _psql(db, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")


def _link(db, cid: str = CH1) -> str:
    return _ok(db, f"SELECT coalesce(journal_entry_id::text, 'NULL') FROM tds_challans WHERE id = '{cid}';")


def _tie(db, je: str, cid: str = CH1) -> subprocess.CompletedProcess:
    return _psql(db, f"UPDATE tds_challans SET journal_entry_id = '{je}' WHERE id = '{cid}';")


# ── 1. one entry, one challan ─────────────────────────────────────────────────────────────────────────────────────

def test_a_second_challan_cannot_be_tied_to_an_entry_that_already_pays_one(db):
    assert _tie(db, JE1, CH1).returncode == 0
    r = _tie(db, JE1, CH2)
    assert r.returncode != 0 and UNIQUE_INDEX in r.stderr, r.stderr
    assert _link(db, CH2) == "NULL"


def _error_code(db, je: str, cid: str) -> str:
    """The SQLSTATE of the refusal, which psql shows only under VERBOSITY verbose."""
    r = subprocess.run(["psql", db, "-X", "-q", "-v", "VERBOSITY=verbose", "-c",
                        f"UPDATE tds_challans SET journal_entry_id = '{je}' WHERE id = '{cid}';"], capture_output=True, text=True)
    return r.stderr


def test_the_refusal_is_the_unique_index_and_its_state_is_23505(db):
    assert _tie(db, JE1, CH1).returncode == 0
    assert "23505" in _error_code(db, JE1, CH2) and UNIQUE_INDEX in _error_code(db, JE1, CH2)


def test_the_same_statement_is_accepted_without_the_index_and_so_the_test_sees_the_hole(db):
    assert _psql(db, f"DROP INDEX {UNIQUE_INDEX};").returncode == 0
    assert _tie(db, JE1, CH1).returncode == 0 and _tie(db, JE1, CH2).returncode == 0, "the control must show two challans on one entry"


def test_two_challans_with_no_link_are_still_fine_and_a_freed_entry_can_be_tied_again(db):
    assert _link(db, CH1) == "NULL" and _link(db, CH2) == "NULL"
    assert _tie(db, JE1, CH1).returncode == 0
    assert _psql(db, f"UPDATE tds_challans SET journal_entry_id = NULL WHERE id = '{CH1}';").returncode == 0
    assert _tie(db, JE1, CH2).returncode == 0 and _link(db, CH2) == JE1


def test_the_plain_index_568_added_is_replaced_and_the_unique_one_is_partial(db):
    assert _ok(db, "SELECT count(*) FROM pg_indexes WHERE indexname = 'idx_tds_challans_journal_entry';") == "0"
    d = _ok(db, f"SELECT indexdef FROM pg_indexes WHERE indexname = '{UNIQUE_INDEX}';")
    assert "UNIQUE" in d and "journal_entry_id IS NOT NULL" in d, d


# ── 2. the tenant rule ────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("foreign, what", [(JE_C2, "another client of the same firm"), (JE_G, "another firm")])
def test_a_challan_cannot_be_tied_to_an_entry_of_another_client_or_firm(db, foreign, what):
    r = _tie(db, foreign)
    assert r.returncode != 0 and WORDS in r.stderr, (what, r.stderr or "it succeeded")
    assert "P0001" in _error_code(db, foreign, CH1) and _link(db) == "NULL"


@pytest.mark.parametrize("foreign", [JE_C2, JE_G])
def test_a_challan_cannot_be_inserted_already_tied_to_such_an_entry(db, foreign):
    r = _psql(db, _challan("57300000-0000-0000-0000-0000000000b1", C1, "00099", link=foreign))
    assert r.returncode != 0 and WORDS in r.stderr
    assert _ok(db, "SELECT count(*) FROM tds_challans WHERE challan_no = '00099';") == "0"


def test_the_same_statement_is_accepted_without_the_trigger_and_so_the_test_sees_the_tenant_hole(db):
    assert _psql(db, "ALTER TABLE tds_challans DISABLE TRIGGER row_journal_entry_journal_entry_id_upd;").returncode == 0
    assert _tie(db, JE_G).returncode == 0, "the control must show a challan tied to another firm's entry"


def test_the_clients_own_entry_is_accepted_and_so_is_no_link_and_a_missing_entry_is_the_foreign_keys_to_refuse(db):
    assert _tie(db, JE1).returncode == 0 and _link(db) == JE1
    r = _tie(db, NOWHERE, CH2)
    assert r.returncode != 0 and "foreign key" in r.stderr and WORDS not in r.stderr, "an entry that does not exist is the key's to report"
    assert _psql(db, _challan("57300000-0000-0000-0000-0000000000b2", C1, "00100")).returncode == 0


def test_a_signed_in_partner_cannot_tie_their_challan_to_an_entry_of_another_firm_which_row_security_hides_from_them(db):
    """The reason the check is SECURITY DEFINER: the Partner of F cannot SEE firm G's entry, so a check run as them would find nothing and let
    the key (which bypasses row security) accept it."""
    assert _signed_in_partner(db, f"SELECT count(*) FROM journal_entries WHERE id = '{JE_G}';").stdout.strip() == "0", "row security must hide it"
    r = _signed_in_partner(db, f"UPDATE tds_challans SET journal_entry_id = '{JE_G}' WHERE id = '{CH1}';")
    assert r.returncode != 0 and WORDS in r.stderr, r.stderr or "it succeeded"
    assert _link(db) == "NULL"
    own = _signed_in_partner(db, f"UPDATE tds_challans SET journal_entry_id = '{JE1}' WHERE id = '{CH1}';")
    assert own.returncode == 0, own.stderr
    assert _link(db) == JE1, "the same session still ties its own client's entry"


def test_the_firm_is_compared_on_its_own_and_not_only_through_the_client(db):
    """An entry planted past the triggers with the SAME client and ANOTHER firm (the books of one tenant carrying the other's client id): only a
    comparison of the firm itself refuses it, so a check that looks at the client alone is not enough."""
    planted = "57300000-0000-0000-0000-0000000000e6"
    assert _psql(db, f"SET session_replication_role = replica; INSERT INTO journal_entries (id, firm_id, client_id, entry_date, narration, "
                     f"entry_type, is_posted, status) VALUES ('{planted}', '{G}', '{C1}', '2026-07-05', 'wrong firm', 'Payment', true, "
                     f"'posted');").returncode == 0
    r = _tie(db, planted)
    assert r.returncode != 0 and WORDS in r.stderr, r.stderr or "it succeeded"


def test_moving_a_tied_challan_to_another_client_is_refused(db):
    assert _tie(db, JE1).returncode == 0
    r = _psql(db, f"UPDATE tds_challans SET client_id = '{C2}' WHERE id = '{CH1}';")
    assert r.returncode != 0 and WORDS in r.stderr


def test_moving_a_tied_challan_to_another_firm_is_refused_by_the_firm_column_alone(db):
    """The update trigger's own firm disjunct, and `OF firm_id`: the link and the client stay as they were and only the firm moves. Migration
    565's client-in-firm check would refuse this first, so it is set aside here to leave the check under test the only one standing."""
    assert _tie(db, JE1).returncode == 0
    if _ok(db, "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'public.tds_challans'::regclass AND tgname = 'row_client_in_firm_upd';") == "1":
        assert _psql(db, "ALTER TABLE public.tds_challans DISABLE TRIGGER row_client_in_firm_upd;").returncode == 0
    r = _psql(db, f"UPDATE tds_challans SET firm_id = '{G}' WHERE id = '{CH1}';")
    assert r.returncode != 0 and WORDS in r.stderr, r.stderr or "it succeeded"
    assert _ok(db, f"SELECT firm_id FROM tds_challans WHERE id = '{CH1}';") == F


def test_a_guard_whose_column_argument_is_stale_refuses_instead_of_passing(db):
    """FAILS CLOSED: a trigger argument that names a column the row does not have (a later rename) must not turn the guard into a pass."""
    assert _psql(db, "CREATE TRIGGER row_journal_entry_stale BEFORE INSERT ON public.tds_challans FOR EACH ROW "
                     "EXECUTE FUNCTION public.assert_row_names_a_journal_entry_of_its_client('a_column_that_was_renamed');").returncode == 0
    r = _psql(db, _challan("57300000-0000-0000-0000-0000000000b3", C1, "00101"))
    assert r.returncode != 0 and "has no column a_column_that_was_renamed" in r.stderr, r.stderr or "it succeeded"


def test_an_edit_that_touches_neither_the_link_nor_the_firm_nor_the_client_is_not_asked_anything(db):
    """A row that already breaks the rule (planted past the trigger) can still be edited, and repaired by clearing its link."""
    assert _psql(db, f"SET session_replication_role = replica; UPDATE tds_challans SET journal_entry_id = '{JE_G}' WHERE id = '{CH1}';").returncode == 0
    assert _link(db) == JE_G
    assert _psql(db, f"UPDATE tds_challans SET challan_no = '00045A' WHERE id = '{CH1}';").returncode == 0, "an unrelated edit was blocked"
    assert _psql(db, f"UPDATE tds_challans SET journal_entry_id = NULL WHERE id = '{CH1}';").returncode == 0
    assert _link(db) == "NULL"


def test_the_remittance_link_has_the_same_rule(db):
    ok = _psql(db, _remittance(C1, "2026-04", link=JE1))
    assert ok.returncode == 0, ok.stderr
    for foreign in (JE_C2, JE_G):
        r = _psql(db, _remittance(C1, "2026-05", link=foreign))
        assert r.returncode != 0 and WORDS in r.stderr, foreign
    assert _ok(db, "SELECT count(*) FROM statutory_remittances;") == "1"
    row = _psql(db, _remittance(C1, "2026-06"))
    assert row.returncode == 0
    r = _psql(db, f"UPDATE statutory_remittances SET journal_entry_id = '{JE_G}' WHERE wage_month = '2026-06';")
    assert r.returncode != 0 and WORDS in r.stderr


def test_the_remittance_link_is_not_made_unique(db):
    """A single bank debit may settle an ESI and a professional-tax remittance together: nothing says one entry pays one remittance."""
    assert _psql(db, _remittance(C1, "2026-04", link=JE1)).returncode == 0
    both = _psql(db, "INSERT INTO public.statutory_remittances (firm_id, client_id, scheme, wage_month, state, submitted_on, journal_entry_id) "
                     f"VALUES ('{F}', '{C1}', 'professional_tax', '2026-04', 'Maharashtra', '2026-07-05', '{JE1}');")
    assert both.returncode == 0, both.stderr


# ── 3. the installer ──────────────────────────────────────────────────────────────────────────────────────────────

def test_the_installer_refuses_what_it_cannot_judge(db):
    for sql, words in (
        ("SELECT public.guard_journal_entry('public.tds_challans', 'challan_no');", "not a uuid column"),
        ("SELECT public.guard_journal_entry('public.tds_challans', 'client_id');", "foreign key to something other than journal_entries"),
        ("SELECT public.guard_journal_entry('public.firms', 'id');", "client_id and firm_id"),
    ):
        r = _psql(db, sql)
        assert r.returncode != 0 and words in r.stderr, (sql, r.stderr)


def test_nobody_signed_in_may_run_the_installer(db):
    for role in ("anon", "authenticated"):
        assert _ok(db, f"SELECT has_function_privilege('{role}', 'public.guard_journal_entry(regclass, text)', 'EXECUTE');") == "f", role


def test_the_trigger_function_is_not_executable_by_anyone_signed_in_and_pins_its_search_path(db):
    sig = "public.assert_row_names_a_journal_entry_of_its_client()"
    for role in ("anon", "authenticated"):
        assert _ok(db, f"SELECT has_function_privilege('{role}', '{sig}', 'EXECUTE');") == "f", role
    assert _ok(db, f"SELECT prosecdef::text || '|' || coalesce(array_to_string(proconfig, ','), '') FROM pg_proc WHERE oid = '{sig}'::regprocedure;") == \
        "true|search_path=pg_catalog, public"


def test_the_revokes_hold_where_the_platform_grants_execute_on_every_new_function(db):
    """Supabase gives `anon` and `authenticated` EXECUTE on each function created in `public`, which a database built from the migrations does not,
    so the checks above would pass without the REVOKE statements. Grant it the way the platform does, drop both functions, run the file again,
    and the file's own REVOKEs are what stand between a signed-in role and them."""
    assert _psql(db, "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon, authenticated;").returncode == 0
    assert _psql(db, "DROP FUNCTION public.guard_journal_entry(regclass, text); "
                     "DROP FUNCTION public.assert_row_names_a_journal_entry_of_its_client() CASCADE;").returncode == 0
    r = _run_file(db, MIGRATION)
    assert r.returncode == 0, r.stderr
    for sig in ("public.assert_row_names_a_journal_entry_of_its_client()", "public.guard_journal_entry(regclass, text)"):
        for role in ("anon", "authenticated"):
            assert _ok(db, f"SELECT has_function_privilege('{role}', '{sig}', 'EXECUTE');") == "f", (sig, role)


def test_both_columns_carry_both_triggers(db):
    for table in ("tds_challans", "statutory_remittances"):
        names = _ok(db, f"SELECT string_agg(tgname, ',' ORDER BY tgname) FROM pg_trigger WHERE tgrelid = 'public.{table}'::regclass "
                        "AND tgname LIKE 'row_journal_entry_%' AND NOT tgisinternal;")
        assert names == "row_journal_entry_journal_entry_id_ins,row_journal_entry_journal_entry_id_upd", (table, names)


# ── 4. the file itself ────────────────────────────────────────────────────────────────────────────────────────────

def test_the_file_can_be_run_again(db):
    for _ in range(2):
        r = _run_file(db, MIGRATION)
        assert r.returncode == 0, r.stderr


def test_the_apply_report_counts_the_rows_that_already_break_the_rule_and_changes_none(db):
    assert _psql(db, f"SET session_replication_role = replica; UPDATE tds_challans SET journal_entry_id = '{JE_G}' WHERE id = '{CH1}';").returncode == 0
    r = _run_file(db, MIGRATION)
    assert r.returncode == 0, r.stderr
    assert "migration 573: 1 TDS challan(s) and 0 statutory remittance(s) already tie a ledger entry of another client or firm" in r.stderr
    assert _link(db) == JE_G, "the report must change nothing"


def test_the_file_stops_in_words_when_an_entry_is_already_tied_to_two_challans(db):
    assert _psql(db, f"DROP INDEX {UNIQUE_INDEX};").returncode == 0
    assert _tie(db, JE1, CH1).returncode == 0 and _tie(db, JE1, CH2).returncode == 0
    r = _run_file(db, MIGRATION)
    assert r.returncode != 0 and "tied to more than one TDS challan" in r.stderr and "does not choose" in r.stderr
    assert _ok(db, f"SELECT count(*) FROM pg_indexes WHERE indexname = '{UNIQUE_INDEX}';") == "0"
    assert _link(db, CH1) == JE1 and _link(db, CH2) == JE1, "it must not pick a link to drop"


def test_the_rollback_takes_the_guards_and_the_unique_index_away_and_puts_568s_index_back(db):
    r = _run_file(db, ROLLBACK)
    assert r.returncode == 0, r.stderr
    assert _ok(db, f"SELECT count(*) FROM pg_indexes WHERE indexname = '{UNIQUE_INDEX}';") == "0"
    assert _ok(db, "SELECT count(*) FROM pg_indexes WHERE indexname = 'idx_tds_challans_journal_entry';") == "1"
    assert _ok(db, "SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'row_journal_entry_%';") == "0"
    assert _ok(db, "SELECT count(*) FROM pg_proc WHERE proname IN ('guard_journal_entry', 'assert_row_names_a_journal_entry_of_its_client');") == "0"
    assert _tie(db, JE_G).returncode == 0, "after the rollback the case goes through again"


def test_568s_own_rollback_needs_573s_first_and_works_after_it(db):
    before = _run_file(db, ROLLBACK_568)
    assert before.returncode != 0, "a trigger's WHEN clause names the column, so it cannot be dropped while the guard stands"
    assert _run_file(db, ROLLBACK).returncode == 0
    after = _run_file(db, ROLLBACK_568)
    assert after.returncode == 0, after.stderr
    assert _ok(db, "SELECT count(*) FROM information_schema.columns WHERE table_name = 'tds_challans' AND column_name = 'journal_entry_id';") == "0"
