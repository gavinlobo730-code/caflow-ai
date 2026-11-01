"""Migration 570 — a row names a ledger account of its own client, or a firm-level account of its own firm (ledger POST-A-353, the account family).

WHAT WAS WRONG
    A journal LINE that names another client's account has been refused since migration 360. The places that STORE a link to an account
    for later (a bank account's ledger account, a rule's suggested account, a budget, a bill of entry, an asset, a landed cost, an order
    line, a bank line and its draft, a split, a recurring template's lines, an account's parent) are each a foreign key to
    chart_of_accounts(id), and a foreign-key check bypasses row security, so each was satisfied by ANY account in the database. A row
    that holds another client's account is not a leak, but it is a stored link into another client's books that fails later, at posting.

WHAT THIS HOLDS (real Postgres)
    * THE CASE ITSELF, on a real table: a bank account naming another client's account is refused in the trigger's words, and the same
      statement is ACCEPTED with the trigger off (the negative control: the test sees the hole it closes);
    * what is allowed: the client's own account, a firm-level account (no client) of the same firm, no account at all;
    * what is refused: another client's account, another firm's account, on insert (a batch fails whole) and on an update that re-points
      the column or moves the row to another client or firm;
    * an update that touches none of those is not asked anything: a row that already breaks the rule can still be edited, and repaired;
    * the same rule on a second real table with a NOT NULL column (a budget), on an account's own parent, through their template on the
      lines of a recurring journal template, and on the four links that have NO foreign key (a year-end adjustment's two accounts, a
      purchase bill line's expense account through its bill, and a year-end mapping's account, judged by the firm alone);
    * a refusal is a business rule written for a person (P0001, its message surfaced as it is), never the 42501 that the API words as a
      fault on our side;
    * THE CATALOG: every foreign key to chart_of_accounts of a table with its own uuid firm_id and client_id carries both triggers, the
      three exceptions (journal lines, two balance tables) carry none, the line tables carry them through their parents, every uuid column
      named for a ledger account that is a key to nothing is guarded or on a reviewed list (empty), no other table has one, and nobody
      signed in may run the installer;
    * the apply-time report counts the rows that already break the rule and changes none; the file can be run again; its rollback
      takes every trigger away and the case goes through again.

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

_STEM = "570_a_row_names_a_ledger_account_of_its_own_client"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the ledger-account proof requires HARNESS_PG + psql",
)

F = "57000000-0000-0000-0000-00000000000f"
G = "57000000-0000-0000-0000-000000000009"
C_F = "57000000-0000-0000-0000-0000000000f1"
C_G = "57000000-0000-0000-0000-0000000000a1"
C_G2 = "57000000-0000-0000-0000-0000000000a2"
A_G = "57000000-0000-0000-0000-0000000000b1"        # an account of C_G
A_G2 = "57000000-0000-0000-0000-0000000000b2"       # an account of C_G2
A_G_FIRM = "57000000-0000-0000-0000-0000000000b3"   # a firm-level account of G (no client)
A_F = "57000000-0000-0000-0000-0000000000b4"        # an account of C_F (firm F)
NOWHERE = "57000000-0000-0000-0000-0000000000ff"
A_F_FIRM = "57000000-0000-0000-0000-0000000000b5"   # a firm-level account of firm F (no client): only the FIRM clause can refuse it on a row of G
PARTNER_G = "57000000-0000-0000-0000-00000000000b"  # a Partner of G, the signed-in caller of the row-security test
PARTNER_AUTH = "57000000-1111-0000-0000-000000000001"

#: Foreign keys to chart_of_accounts that carry no check, and why.
EXCEPTIONS = {
    "journal_lines": "migration 360 asks, at the statement level, for every line",
    "account_period_balances": "written only by the database's own triggers, from lines 360 has checked",
    "ledger_balances": "written only by the database's own triggers, from lines 360 has checked",
}
#: Tables judged through their template.
THROUGH_A_PARENT = {"recurring_journal_template_lines": "account_id", "recurring_purchase_bill_template_lines": "expense_account_id"}
#: Uuid columns named for a ledger account that are a key to NOTHING (so the catalog of foreign keys cannot see them), each guarded by name in the
#: migration. A new one must be added to the migration and to this list, or the test below names it.
UNKEYED = {("year_end_adjustments", "debit_account_id"), ("year_end_adjustments", "credit_account_id"),
           ("purchase_bill_lines", "expense_account_id"), ("account_group_mappings", "account_id")}
#: Unkeyed account columns reviewed and deliberately left unguarded, with the reason. None.
UNKEYED_UNGUARDED: dict[tuple[str, str], str] = {}
TOTAL_GUARDED = 18      # 12 columns of tables with their own client + 2 template lines + the 4 unkeyed links
WORDS = "another client or firm"


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


def _bank(client: str, account: str | None, no: str = "1", firm: str = G) -> str:
    acct = f"'{account}'" if account else "NULL"
    return (f"INSERT INTO public.bank_accounts (firm_id, client_id, bank_name, account_no, coa_account_id) "
            f"VALUES ('{firm}', '{client}', 'B', '{no}', {acct});")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m570_{uuid.uuid4().hex[:10]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert MIGRATION.name not in pg_template.failed, "migration 570 did not apply, so everything below would pass vacuously"
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{PARTNER_AUTH}', 'partner@m570.test');
            INSERT INTO firms (id, name, email) VALUES ('{F}', 'M570 F', 'f@m570.test'), ('{G}', 'M570 G', 'g@m570.test');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
                ('{C_F}', '{F}', 'CF', 'Private Limited'), ('{C_G}', '{G}', 'CG', 'Private Limited'), ('{C_G2}', '{G}', 'CG2', 'Private Limited');
            INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type) VALUES
                ('{A_G}', '{G}', '{C_G}', '1001', 'G cash', 'Asset'),
                ('{A_G2}', '{G}', '{C_G2}', '1002', 'G2 cash', 'Asset'),
                ('{A_G_FIRM}', '{G}', NULL, '1003', 'G shared', 'Asset'),
                ('{A_F}', '{F}', '{C_F}', '2001', 'F cash', 'Asset'),
                ('{A_F_FIRM}', '{F}', NULL, '2002', 'F shared', 'Asset');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                 VALUES ('{PARTNER_G}', '{G}', '{PARTNER_AUTH}', 'partner@m570.test', 'P', 'Partner', true);
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── the case itself ───────────────────────────────────────────────────────────────────────────────────────────────

def test_a_bank_account_cannot_name_another_clients_ledger_account(db):
    r = _psql(db, _bank(C_G, A_G2))
    assert r.returncode != 0 and "another client or firm" in r.stderr, r.stderr or "it succeeded"
    assert _ok(db, "SELECT count(*) FROM public.bank_accounts;") == "0"


def test_the_same_statement_is_accepted_without_the_trigger_and_so_the_test_sees_the_hole(db):
    _ok(db, "ALTER TABLE public.bank_accounts DISABLE TRIGGER row_ledger_account_coa_account_id_ins;")
    assert _psql(db, _bank(C_G, A_G2)).returncode == 0
    assert _ok(db, "SELECT count(*) FROM public.bank_accounts;") == "1"


def test_the_clients_own_account_a_firm_level_account_and_no_account_are_accepted(db):
    for n, acct in enumerate((A_G, A_G_FIRM, None)):
        r = _psql(db, _bank(C_G, acct, no=str(n)))
        assert r.returncode == 0, f"{acct}: {r.stderr}"
    assert _ok(db, "SELECT count(*) FROM public.bank_accounts;") == "3"


def test_another_firms_account_is_refused_even_when_it_is_firm_level_to_that_firm(db):
    assert WORDS in _psql(db, _bank(C_G, A_F)).stderr
    assert WORDS in _psql(db, _bank(C_G, A_F_FIRM)).stderr


def test_a_batch_is_judged_as_a_statement_and_one_bad_row_fails_it_whole(db):
    r = _psql(db, _bank(C_G, A_G, no="a").replace(";", "") + f", ('{G}', '{C_G}', 'B', 'b', '{A_G2}');")
    assert r.returncode != 0 and WORDS in r.stderr
    assert _ok(db, "SELECT count(*) FROM public.bank_accounts;") == "0"


# ── updates ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _one_bank_account(db, acct=A_G) -> None:
    _ok(db, _bank(C_G, acct))


def test_an_update_that_re_points_the_account_or_moves_the_row_is_refused(db):
    _one_bank_account(db)
    assert WORDS in _psql(db, f"UPDATE public.bank_accounts SET coa_account_id = '{A_G2}';").stderr
    assert WORDS in _psql(db, f"UPDATE public.bank_accounts SET client_id = '{C_G2}';").stderr, "moved to a client the account does not belong to"
    assert _psql(db, f"UPDATE public.bank_accounts SET coa_account_id = '{A_G_FIRM}';").returncode == 0
    assert _ok(db, "SELECT coa_account_id FROM public.bank_accounts;") == A_G_FIRM


def test_an_update_that_touches_none_of_it_is_not_asked_and_a_bad_row_can_be_repaired(db):
    _ok(db, "ALTER TABLE public.bank_accounts DISABLE TRIGGER row_ledger_account_coa_account_id_ins;")
    _one_bank_account(db, A_G2)                                            # a row that already breaks the rule
    _ok(db, "ALTER TABLE public.bank_accounts ENABLE TRIGGER row_ledger_account_coa_account_id_ins;")
    assert _psql(db, "UPDATE public.bank_accounts SET bank_name = 'renamed';").returncode == 0
    assert _psql(db, f"UPDATE public.bank_accounts SET coa_account_id = '{A_G2}';").returncode == 0, "re-saving the same value is not a change"
    assert _psql(db, f"UPDATE public.bank_accounts SET coa_account_id = '{A_G}';").returncode == 0, "the repair"
    assert _ok(db, "SELECT coa_account_id FROM public.bank_accounts;") == A_G


def test_deleting_the_account_a_bank_line_drafted_to_still_sets_the_column_null(db):
    """The foreign key's own ON DELETE SET NULL is an UPDATE of the column; the update check must let a NULL through."""
    temp = "57000000-0000-0000-0000-0000000000b6"
    _ok(db, f"""
        INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type)
             VALUES ('{temp}', '{G}', '{C_G}', '1009', 'temp', 'Asset');
        INSERT INTO bank_statements (id, firm_id, client_id, bank_name, statement_from, statement_to)
             VALUES ('57000000-0000-0000-0000-0000000000d1', '{G}', '{C_G}', 'B', '2026-04-01', '2026-04-30');
        INSERT INTO bank_transactions (id, statement_id, firm_id, client_id, transaction_date, description, draft_account_id)
             VALUES ('57000000-0000-0000-0000-0000000000d2', '57000000-0000-0000-0000-0000000000d1', '{G}', '{C_G}', '2026-04-02', 'x', '{temp}');
    """)
    assert _ok(db, "SELECT draft_account_id FROM bank_transactions;") == temp
    r = _psql(db, f"DELETE FROM chart_of_accounts WHERE id = '{temp}';")
    assert r.returncode == 0, r.stderr
    assert _ok(db, "SELECT coalesce(draft_account_id::text, 'NULL') FROM bank_transactions;") == "NULL"


# ── the other tables ──────────────────────────────────────────────────────────────────────────────────────────────

def test_a_budget_cannot_name_another_clients_account(db):
    bad = f"INSERT INTO public.account_budgets (firm_id, client_id, account_id, fy) VALUES ('{G}', '{C_G}', '{A_G2}', '2026-27');"
    good = f"INSERT INTO public.account_budgets (firm_id, client_id, account_id, fy) VALUES ('{G}', '{C_G}', '{A_G}', '2026-27');"
    assert WORDS in _psql(db, bad).stderr
    assert _psql(db, good).returncode == 0


def test_an_accounts_parent_is_its_own_clients_or_a_firm_level_account(db):
    child = lambda parent, code: (f"INSERT INTO chart_of_accounts (firm_id, client_id, account_code, account_name, account_type, parent_id) "  # noqa: E731
                                  f"VALUES ('{G}', '{C_G}', '{code}', 'child {code}', 'Asset', '{parent}');")
    assert WORDS in _psql(db, child(A_G2, "1101")).stderr
    assert _psql(db, child(A_G, "1102")).returncode == 0
    assert _psql(db, child(A_G_FIRM, "1103")).returncode == 0


def _template(db, client, tid):
    _ok(db, f"INSERT INTO public.recurring_journal_templates (id, firm_id, client_id, name, frequency, start_date, next_run_date) "
            f"VALUES ('{tid}', '{G}', '{client}', 't', 'monthly', '2026-04-01', '2026-04-01');")


def test_a_recurring_templates_lines_are_judged_through_their_template(db):
    t1, t2 = "57000000-0000-0000-0000-0000000000c1", "57000000-0000-0000-0000-0000000000c2"
    _template(db, C_G, t1)
    _template(db, C_G2, t2)
    line = lambda tid, acct: (f"INSERT INTO public.recurring_journal_template_lines (template_id, account_id, debit_paise, credit_paise) "  # noqa: E731
                              f"VALUES ('{tid}', '{acct}', 100, 0);")
    assert WORDS in _psql(db, line(t1, A_G2)).stderr
    assert _psql(db, line(t1, A_G)).returncode == 0
    assert _psql(db, line(t1, A_G_FIRM)).returncode == 0
    assert _psql(db, line(t2, A_G2)).returncode == 0
    # moving a good line to the other client's template makes its account foreign there
    assert WORDS in _psql(db, f"UPDATE public.recurring_journal_template_lines SET template_id = '{t2}' WHERE account_id = '{A_G}';").stderr


# ── the links that have no foreign key ───────────────────────────────────────────────────────────────────────────────

def test_a_refusal_is_a_business_rule_for_a_person_and_not_a_permission_fault(db):
    """P0001 (core/exceptions surfaces its message as written); 42501 would be worded to the CA as a fault on our side."""
    r = _psql(db, "\\set VERBOSITY verbose\n" + _bank(C_G, A_G2))
    assert "P0001" in r.stderr and "42501" not in r.stderr and "That ledger account belongs to another client or firm" in r.stderr, r.stderr


def test_a_year_end_adjustment_cannot_name_another_clients_account_in_either_column(db):
    eng = "57000000-0000-0000-0000-0000000000e1"
    _ok(db, f"INSERT INTO year_end_engagements (id, firm_id, client_id, financial_year, fy_start, fy_end, created_by) "
            f"VALUES ('{eng}', '{G}', '{C_G}', '2026-27', '2026-04-01', '2027-03-31', '{eng}');")

    def adjustment(debit, credit):
        return (f"INSERT INTO public.year_end_adjustments (engagement_id, firm_id, client_id, adjustment_type, description, amount_paise, "
                f"created_by, debit_account_id, credit_account_id) VALUES ('{eng}', '{G}', '{C_G}', 'manual', 'x', 100, '{eng}', "
                f"'{debit}', '{credit}');")
    assert WORDS in _psql(db, adjustment(A_G2, A_G)).stderr
    assert WORDS in _psql(db, adjustment(A_G, A_G2)).stderr
    assert _psql(db, adjustment(A_G, A_G_FIRM)).returncode == 0
    assert WORDS in _psql(db, f"UPDATE public.year_end_adjustments SET credit_account_id = '{A_F}';").stderr


def test_a_purchase_bill_lines_expense_account_is_judged_through_its_bill(db):
    vendor, bill = "57000000-0000-0000-0000-0000000000f1", "57000000-0000-0000-0000-0000000000f2"
    _ok(db, f"INSERT INTO vendors (id, firm_id, client_id, name) VALUES ('{vendor}', '{G}', '{C_G}', 'V');"
            f"INSERT INTO purchase_bills (id, firm_id, client_id, vendor_id, bill_date) VALUES ('{bill}', '{G}', '{C_G}', '{vendor}', '2026-05-01');")
    line = lambda acct: (f"INSERT INTO public.purchase_bill_lines (bill_id, description, expense_account_id) "          # noqa: E731
                         f"VALUES ('{bill}', 'x', '{acct}');")
    assert WORDS in _psql(db, line(A_G2)).stderr
    assert _psql(db, line(A_G)).returncode == 0
    assert _psql(db, line(A_G_FIRM)).returncode == 0
    assert _psql(db, f"INSERT INTO public.purchase_bill_lines (bill_id, description) VALUES ('{bill}', 'no account');").returncode == 0


def test_a_year_end_mapping_belongs_to_the_firm_so_only_the_firm_is_judged(db):
    mapping = lambda acct: (f"INSERT INTO public.account_group_mappings (firm_id, account_id, schedule_line) "          # noqa: E731
                            f"VALUES ('{G}', '{acct}', 'cash_and_bank');")
    assert _psql(db, mapping(A_G)).returncode == 0
    assert _psql(db, mapping(A_G2)).returncode == 0, "another client of the same firm: a firm-wide mapping may name it"
    assert WORDS in _psql(db, mapping(A_F)).stderr


def test_every_uuid_column_named_for_a_ledger_account_that_is_a_key_to_nothing_is_guarded_or_reviewed(db):
    found = {tuple(line.split("|")) for line in _ok(db, """
        SELECT c.relname, a.attname FROM pg_attribute a
          JOIN pg_class c ON c.oid = a.attrelid AND c.relkind = 'r'
          JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
         WHERE a.attnum > 0 AND NOT a.attisdropped AND a.atttypid = 'uuid'::regtype AND a.attname ~ 'account_id$'
           AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.contype = 'f' AND k.conrelid = c.oid AND a.attnum = ANY (k.conkey));""").splitlines()}
    assert found == UNKEYED | set(UNKEYED_UNGUARDED), f"a ledger-account column with no key is neither guarded nor reviewed: {sorted(found ^ (UNKEYED | set(UNKEYED_UNGUARDED)))}"
    triggers = _ok(db, "SELECT g.tgrelid::regclass::text || '|' || g.tgname FROM pg_trigger g WHERE NOT g.tgisinternal AND g.tgname LIKE 'row\\_ledger\\_account\\_%'")
    for table, col in UNKEYED:
        assert f"{table}|row_ledger_account_{col}_ins" in triggers and f"{table}|row_ledger_account_{col}_upd" in triggers, (table, col)


# ── the catalog ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_every_foreign_key_to_the_chart_of_accounts_is_guarded_or_named_as_an_exception(db):
    fks = [line.split("|") for line in _ok(db, """
        SELECT c.relname, a.attname,
               (SELECT count(*) FROM pg_attribute x WHERE x.attrelid = c.oid AND x.attname IN ('client_id', 'firm_id')
                   AND x.atttypid = 'uuid'::regtype AND x.attnum > 0 AND NOT x.attisdropped)
          FROM pg_constraint k
          JOIN pg_class c ON c.oid = k.conrelid AND c.relkind = 'r'
          JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
          JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = k.conkey[1]
         WHERE k.contype = 'f' AND k.confrelid = 'public.chart_of_accounts'::regclass
         ORDER BY 1, 2;""").splitlines()]
    triggers = {tuple(line.split("|")) for line in _ok(db, """
        SELECT g.tgrelid::regclass::text, g.tgname FROM pg_trigger g
         WHERE NOT g.tgisinternal AND g.tgname LIKE 'row\\_ledger\\_account\\_%';""").splitlines()}
    assert len(fks) >= 14, "the catalog query found too few foreign keys to mean anything"
    unguarded = []
    for table, col, own in fks:
        has = {(table, f"row_ledger_account_{col}_ins"), (table, f"row_ledger_account_{col}_upd")} <= triggers
        if table in EXCEPTIONS:
            assert not has, f"{table}.{col} is named an exception and carries the check"
        elif table in THROUGH_A_PARENT or own == "2":
            if not has:
                unguarded.append(f"{table}.{col}")
        else:
            unguarded.append(f"{table}.{col} (no firm_id and client_id of its own, and not named as judged through a parent)")
    assert unguarded == [], f"these foreign keys to chart_of_accounts carry no account check: {unguarded}"
    # and nothing else carries one
    guarded = {t[0] for t in triggers}
    assert guarded == {t for t, _c, own in fks if t not in EXCEPTIONS} | {t for t, _c in UNKEYED}, "a ledger-account trigger sits on a table that has no such key"
    for table, col in THROUGH_A_PARENT.items():
        assert any(t == table and c == col for t, c, _o in fks)


def test_nobody_signed_in_may_run_the_installer(db):
    for role in ("authenticated", "anon"):
        assert _ok(db, f"SELECT has_function_privilege('{role}', 'public.guard_ledger_account(regclass, text, regclass, text, boolean)', 'EXECUTE');") == "f", role


def test_the_installer_refuses_a_column_that_is_not_a_key_to_the_chart(db):
    r = _psql(db, "SELECT public.guard_ledger_account('public.bank_accounts'::regclass, 'bank_name');")
    assert r.returncode != 0 and "is not a uuid column" in r.stderr


# ── the apply report, re-running, rollback ─────────────────────────────────────────────────────────────────────

def test_the_apply_report_counts_the_rows_that_already_break_the_rule_and_changes_none(db):
    _ok(db, "SELECT public.guard_ledger_account('public.bank_accounts'::regclass, 'coa_account_id');"
            "ALTER TABLE public.bank_accounts DISABLE TRIGGER row_ledger_account_coa_account_id_ins;")
    _ok(db, _bank(C_G, A_G2, no="x") + _bank(C_G, A_F, no="y") + _bank(C_G, A_G, no="z"))
    before = _ok(db, "SELECT string_agg(account_no || ':' || coa_account_id::text, ',' ORDER BY account_no) FROM public.bank_accounts;")
    r = _run_file(db, MIGRATION)
    assert r.returncode == 0, r.stderr
    assert "migration 570:" in r.stderr and "2 existing row(s) in 1 column(s)" in r.stderr, r.stderr
    assert _ok(db, "SELECT string_agg(account_no || ':' || coa_account_id::text, ',' ORDER BY account_no) FROM public.bank_accounts;") == before


def test_the_file_can_be_run_again_and_leaves_one_pair_of_triggers_per_column(db):
    assert _run_file(db, MIGRATION).returncode == 0
    assert _run_file(db, MIGRATION).returncode == 0
    assert _ok(db, "SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE 'row\\_ledger\\_account\\_%\\_ins';") == str(TOTAL_GUARDED)
    assert _ok(db, "SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE 'row\\_ledger\\_account\\_%\\_upd';") == str(TOTAL_GUARDED)


def test_the_rollback_takes_every_trigger_and_function_away_and_the_case_goes_through_again(db):
    r = _run_file(db, ROLLBACK)
    assert r.returncode == 0, r.stderr
    assert _ok(db, "SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE 'row\\_ledger\\_account\\_%';") == "0"
    assert _ok(db, "SELECT count(*) FROM pg_proc WHERE proname IN ('guard_ledger_account', 'assert_inserted_rows_name_a_ledger_account_of_their_client', "
                   "'assert_updated_row_names_a_ledger_account_of_its_client');") == "0"
    assert _psql(db, _bank(C_G, A_G2)).returncode == 0


# ── what the independent review of the merged migration found no test for (1-11-2026) ──────────────────────────────────
# Five mutants of the migration passed every test above: the update path's firm clause, SECURITY DEFINER, the template-line parent table,
# the update path's early return on two tables, the parent-path insert's firm clause, and four branches of the apply report.

def _signed_in_partner(dsn: str, sql: str) -> subprocess.CompletedProcess:
    claims = json.dumps({"sub": PARTNER_AUTH, "role": "authenticated"})
    return _psql(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")


def test_an_update_to_another_firms_firm_level_account_is_refused_by_the_firm_clause_alone(db):
    """A firm-level account has no client, so the client clause cannot refuse it: only the firm clause of the UPDATE check can. Every other
    update test re-points to an account that also differs by client, so removing the firm clause left them all green."""
    _one_bank_account(db)
    r = _psql(db, f"UPDATE public.bank_accounts SET coa_account_id = '{A_F_FIRM}';")
    assert r.returncode != 0 and WORDS in r.stderr, r.stderr or "the update was accepted"
    assert _ok(db, "SELECT coa_account_id FROM public.bank_accounts;") == A_G


def test_the_check_sees_an_account_that_row_security_hides_from_the_signed_in_writer(db):
    """The two trigger functions are SECURITY DEFINER because the writer cannot see another firm's account. As superuser nothing is ever
    hidden, so a version without it passed. Here the writer is a signed-in Partner of firm G: the control shows the account really is
    invisible to them, and the budget naming it is still refused in the trigger's words (not accepted, and not an opaque foreign-key error)."""
    hidden = _signed_in_partner(db, f"SELECT count(*) FROM public.chart_of_accounts WHERE id = '{A_F}';")
    assert hidden.returncode == 0 and hidden.stdout.strip() == "0", f"this test's premise: firm F's account is invisible to firm G's Partner ({hidden.stdout!r} {hidden.stderr!r})"
    r = _signed_in_partner(db, f"INSERT INTO public.account_budgets (firm_id, client_id, account_id, fy) VALUES ('{G}', '{C_G}', '{A_F}', '2026-27');")
    assert r.returncode != 0 and WORDS in r.stderr, r.stderr or "the signed-in insert was accepted"
    own = _signed_in_partner(db, f"INSERT INTO public.account_budgets (firm_id, client_id, account_id, fy) VALUES ('{G}', '{C_G}', '{A_G}', '2026-27');")
    assert own.returncode == 0, f"the control: a Partner's own client's account is allowed ({own.stderr})"


def _purchase_template(db, client: str, tid: str) -> None:
    vendor = f"57000000-0000-0000-0000-0000000000{'f3' if client == C_G else 'f4'}"
    _ok(db, f"INSERT INTO vendors (id, firm_id, client_id, name) VALUES ('{vendor}', '{G}', '{client}', 'V');"
            f"INSERT INTO public.recurring_purchase_bill_templates (id, firm_id, client_id, vendor_id, title, frequency, start_date, next_run_date) "
            f"VALUES ('{tid}', '{G}', '{client}', '{vendor}', 't', 'monthly', '2026-04-01', '2026-04-01');")


def test_a_recurring_purchase_bills_lines_are_judged_through_their_own_template(db):
    """The line table names its parent in the migration; a mutant that judged these lines against the OTHER template table (or none) passed."""
    t1, t2 = "57000000-0000-0000-0000-0000000000c3", "57000000-0000-0000-0000-0000000000c4"
    _purchase_template(db, C_G, t1)
    _purchase_template(db, C_G2, t2)
    line = lambda tid, acct: (f"INSERT INTO public.recurring_purchase_bill_template_lines (template_id, description, expense_account_id) "  # noqa: E731
                              f"VALUES ('{tid}', 'x', '{acct}');")
    assert WORDS in _psql(db, line(t1, A_G2)).stderr
    assert _psql(db, line(t1, A_G)).returncode == 0
    assert _psql(db, line(t1, A_G_FIRM)).returncode == 0
    assert _psql(db, line(t2, A_G2)).returncode == 0
    assert WORDS in _psql(db, f"UPDATE public.recurring_purchase_bill_template_lines SET template_id = '{t2}' WHERE expense_account_id = '{A_G}';").stderr
    # the parent path judges the FIRM too: a firm-level account of another firm has no client to differ by
    assert WORDS in _psql(db, line(t1, A_F_FIRM)).stderr


def test_a_purchase_bill_line_and_a_year_end_mapping_are_asked_on_an_update_too(db):
    """The update trigger returned early for these two tables in a mutant and nothing noticed, because no test updated either."""
    vendor, bill = "57000000-0000-0000-0000-0000000000f5", "57000000-0000-0000-0000-0000000000f6"
    _ok(db, f"INSERT INTO vendors (id, firm_id, client_id, name) VALUES ('{vendor}', '{G}', '{C_G}', 'V');"
            f"INSERT INTO purchase_bills (id, firm_id, client_id, vendor_id, bill_date) VALUES ('{bill}', '{G}', '{C_G}', '{vendor}', '2026-05-01');"
            f"INSERT INTO public.purchase_bill_lines (bill_id, description, expense_account_id) VALUES ('{bill}', 'x', '{A_G}');"
            f"INSERT INTO public.account_group_mappings (firm_id, account_id, schedule_line) VALUES ('{G}', '{A_G}', 'cash_and_bank');")
    assert WORDS in _psql(db, f"UPDATE public.purchase_bill_lines SET expense_account_id = '{A_G2}';").stderr
    assert WORDS in _psql(db, f"UPDATE public.purchase_bill_lines SET expense_account_id = '{A_F_FIRM}';").stderr
    assert _psql(db, f"UPDATE public.purchase_bill_lines SET expense_account_id = '{A_G_FIRM}';").returncode == 0
    assert WORDS in _psql(db, f"UPDATE public.account_group_mappings SET account_id = '{A_F}';").stderr
    assert _psql(db, f"UPDATE public.account_group_mappings SET account_id = '{A_G2}';").returncode == 0, "a firm-wide mapping may name any client of the firm"


def test_the_apply_report_counts_a_bad_row_in_every_kind_of_column(db):
    """Only a bank account was planted before; the report has a branch for a plain table, a line through its parent (two kinds), a firm-wide
    table and the two unkeyed year-end columns, and a mutant that ignored any of the four others still reported the right number for the one tested."""
    eng = "57000000-0000-0000-0000-0000000000e2"
    t_j, t_p = "57000000-0000-0000-0000-0000000000c5", "57000000-0000-0000-0000-0000000000c6"
    vendor, bill = "57000000-0000-0000-0000-0000000000f7", "57000000-0000-0000-0000-0000000000f8"
    _purchase_template(db, C_G, t_p)
    _template(db, C_G, t_j)
    _ok(db, f"INSERT INTO vendors (id, firm_id, client_id, name) VALUES ('{vendor}', '{G}', '{C_G}', 'V2');"
            f"INSERT INTO purchase_bills (id, firm_id, client_id, vendor_id, bill_date) VALUES ('{bill}', '{G}', '{C_G}', '{vendor}', '2026-05-01');"
            f"INSERT INTO year_end_engagements (id, firm_id, client_id, financial_year, fy_start, fy_end, created_by) "
            f"VALUES ('{eng}', '{G}', '{C_G}', '2026-27', '2026-04-01', '2027-03-31', '{eng}');")
    # Planted past the triggers (replica mode skips them for the session), one bad row in each of eight columns.
    _ok(db, f"""SET session_replication_role = replica;
        {_bank(C_G, A_G2, no="r1")}
        INSERT INTO public.account_budgets (firm_id, client_id, account_id, fy) VALUES ('{G}', '{C_G}', '{A_G2}', '2026-27');
        INSERT INTO public.recurring_journal_template_lines (template_id, account_id, debit_paise, credit_paise) VALUES ('{t_j}', '{A_G2}', 100, 0);
        INSERT INTO public.recurring_purchase_bill_template_lines (template_id, description, expense_account_id) VALUES ('{t_p}', 'x', '{A_G2}');
        INSERT INTO public.purchase_bill_lines (bill_id, description, expense_account_id) VALUES ('{bill}', 'x', '{A_G2}');
        INSERT INTO public.account_group_mappings (firm_id, account_id, schedule_line) VALUES ('{G}', '{A_F}', 'cash_and_bank');
        INSERT INTO public.year_end_adjustments (engagement_id, firm_id, client_id, adjustment_type, description, amount_paise, created_by, debit_account_id, credit_account_id)
             VALUES ('{eng}', '{G}', '{C_G}', 'manual', 'x', 100, '{eng}', '{A_G2}', '{A_G}');
        INSERT INTO public.year_end_adjustments (engagement_id, firm_id, client_id, adjustment_type, description, amount_paise, created_by, debit_account_id, credit_account_id)
             VALUES ('{eng}', '{G}', '{C_G}', 'manual', 'y', 100, '{eng}', '{A_G}', '{A_G2}');""")
    r = _run_file(db, MIGRATION)
    assert r.returncode == 0, r.stderr
    assert "8 existing row(s) in 8 column(s)" in r.stderr, r.stderr
