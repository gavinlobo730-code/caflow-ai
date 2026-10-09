"""Migration 482 - every firm chart has an Office Equipment ledger, on real Postgres.

An asset of category "Office Equipment" is debited to the ledger the pattern
`%Office Equipment%` finds. The chart a firm is onboarded with had none, so
`POST /api/fixed-assets` answered 500 for it (the test beside this one,
test_every_asset_category_has_a_ledger_on_the_standard_chart.py, is the
mock-mode half). 482 adds the ledger to the charts that exist; it inserts rows
and changes nothing already there.

Runs only when HARNESS_PG is set + psql on PATH, like every other *_pg test.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import uuid

import pytest

from services.coa_seed_service import STANDARD_COA

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

_MIGRATIONS = pathlib.Path(__file__).resolve().parents[1] / "migrations"
_FORWARD = _MIGRATIONS / "482_every_firm_has_an_office_equipment_account.sql"
_ROLLBACK = _MIGRATIONS / "482_every_firm_has_an_office_equipment_account_rollback.sql"

ONBOARDED = "48200000-0000-0000-0000-000000000001"     # the standard chart as it stood
CROWDED = "48200000-0000-0000-0000-000000000002"       # 1508 already taken
ONLY_AN_EXPENSE = "48200000-0000-0000-0000-000000000003"
MIGRATION_011 = "48200000-0000-0000-0000-000000000004"  # Office Equipment at 1501
INACTIVE_SAME_NAME = "48200000-0000-0000-0000-000000000005"
INACTIVE_OTHER_NAME = "48200000-0000-0000-0000-000000000006"
CLIENT_LEVEL_ONLY = "48200000-0000-0000-0000-000000000007"
NO_CHART = "48200000-0000-0000-0000-000000000008"

CLIENT = "48200000-0000-0000-0000-0000000000c1"        # belongs to CLIENT_LEVEL_ONLY

ALL_FIRMS = (ONBOARDED, CROWDED, ONLY_AN_EXPENSE, MIGRATION_011, INACTIVE_SAME_NAME,
             INACTIVE_OTHER_NAME, CLIENT_LEVEL_ONLY, NO_CHART)


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [l for l in r.stdout.strip().splitlines() if l]


def _account(firm: str, code: str, name: str, *, account_type: str = "Asset",
             subtype: str = "Fixed Asset", client: str | None = None,
             active: bool = True, key: str | None = None, acct_id: str | None = None) -> str:
    cols = "firm_id, client_id, account_code, account_name, account_type, account_subtype, is_active, system_account_key"
    client_sql = "'" + client + "'" if client else "NULL"
    key_sql = "'" + key + "'" if key else "NULL"
    vals = (f"'{firm}', {client_sql}, '{code}', '{name}', "
            f"'{account_type}', '{subtype}', {'TRUE' if active else 'FALSE'}, {key_sql}")
    if acct_id:
        cols, vals = "id, " + cols, f"'{acct_id}', " + vals
    return f"INSERT INTO chart_of_accounts ({cols}) VALUES ({vals});"


def _standard_chart_before_482(firm: str) -> str:
    """The chart seed_firm_coa gave a firm until this change: STANDARD_COA minus
    the one row 482 is about (read from the real list, not retyped)."""
    return "\n".join(
        _account(firm, code, name.replace("'", "''"), account_type=atype, subtype=sub)
        for code, name, atype, sub in STANDARD_COA if name != "Office Equipment")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"c19_oe482_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        firms = ", ".join(f"('{f}', 'Firm {i}', 'f{i}@t.in')" for i, f in enumerate(ALL_FIRMS))
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES {firms};
            INSERT INTO clients (id, firm_id, client_name, entity_type)
              VALUES ('{CLIENT}', '{CLIENT_LEVEL_ONLY}', 'Mine', 'Proprietorship');

            {_standard_chart_before_482(ONBOARDED)}

            {_standard_chart_before_482(CROWDED)}
            {_account(CROWDED, '1508', 'Leasehold Improvements')}

            {_account(ONLY_AN_EXPENSE, '5004', 'Office Rent', account_type='Expense', subtype='Overhead')}
            {_account(ONLY_AN_EXPENSE, '5100', 'Office Equipment Repairs', account_type='Expense', subtype='Overhead')}

            {_account(MIGRATION_011, '1501', 'Office Equipment')}
            {_account(MIGRATION_011, '1502', 'Computers & Laptops')}

            {_account(INACTIVE_SAME_NAME, '1101', 'Bank Account', subtype='Bank')}
            {_account(INACTIVE_SAME_NAME, '1510', 'Office Equipment', active=False)}

            {_account(INACTIVE_OTHER_NAME, '1101', 'Bank Account', subtype='Bank')}
            {_account(INACTIVE_OTHER_NAME, '1510', 'Office Equipment (old)', active=False)}

            {_account(CLIENT_LEVEL_ONLY, '1101', 'Bank Account', subtype='Bank')}
            {_account(CLIENT_LEVEL_ONLY, '1520', 'Office Equipment', client=CLIENT)}
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _apply(dsn: str, path: pathlib.Path = _FORWARD) -> None:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _office_equipment(dsn: str, firm: str) -> list[str]:
    return _rows(dsn, f"""SELECT account_code || '|' || account_type || '|' || account_subtype || '|' ||
                                 coalesce(client_id::text, 'firm') || '|' ||
                                 CASE WHEN is_active THEN 'active' ELSE 'inactive' END || '|' ||
                                 coalesce(system_account_key, '-') || '|' || account_name
                          FROM chart_of_accounts
                          WHERE firm_id = '{firm}' AND account_name ILIKE '%Office Equipment%'
                          ORDER BY account_code""")


# ── what it adds ────────────────────────────────────────────────────────────

def test_an_onboarded_firm_gets_the_ledger_at_the_first_free_code(db):
    assert _office_equipment(db, ONBOARDED) == []
    _apply(db)
    assert _office_equipment(db, ONBOARDED) == [
        "1508|Asset|Fixed Asset|firm|active|-|Office Equipment"]


def test_a_firm_whose_1508_is_taken_gets_the_next_free_code(db):
    _apply(db)
    assert _office_equipment(db, CROWDED) == [
        "1509|Asset|Fixed Asset|firm|active|-|Office Equipment"]


def test_the_engines_own_lookup_finds_it_afterwards_and_not_before(db):
    """The predicate `phase2_journal_service._find_account` sends to PostgREST,
    asked of the database: active, the firm's, firm-level or the client's own,
    name ILIKE the category's pattern. Zero rows is the 500."""
    ask = (f"SELECT count(*) FROM chart_of_accounts WHERE firm_id = '{ONBOARDED}' "
           f"AND (client_id = '{uuid.uuid4()}' OR client_id IS NULL) "
           "AND account_name ILIKE '%Office Equipment%' AND is_active = TRUE")
    assert _rows(db, ask) == ["0"]
    _apply(db)
    assert _rows(db, ask) == ["1"]


def test_a_firm_with_only_an_expense_of_that_name_gets_the_asset_ledger(db):
    """Judged the way the engine judges it, but an expense called "Office
    Equipment Repairs" is not an asset ledger, and the right one has to exist."""
    _apply(db)
    assert _office_equipment(db, ONLY_AN_EXPENSE) == [
        "1508|Asset|Fixed Asset|firm|active|-|Office Equipment",
        "5100|Expense|Overhead|firm|active|-|Office Equipment Repairs",
    ]


def test_an_inactive_account_with_another_name_does_not_serve_the_firm(db):
    _apply(db)
    assert _office_equipment(db, INACTIVE_OTHER_NAME) == [
        "1508|Asset|Fixed Asset|firm|active|-|Office Equipment",
        "1510|Asset|Fixed Asset|firm|inactive|-|Office Equipment (old)",
    ]


# ── what it leaves alone ────────────────────────────────────────────────────

def test_a_firm_that_already_has_the_ledger_is_untouched(db):
    before = _office_equipment(db, MIGRATION_011)
    _apply(db)
    assert _office_equipment(db, MIGRATION_011) == before == [
        "1501|Asset|Fixed Asset|firm|active|-|Office Equipment"]


def test_a_name_already_taken_by_an_inactive_or_client_level_account_skips_without_aborting(db):
    """Both UNIQUE (firm_id, account_code) and UNIQUE (firm_id, account_name)
    exist, so the insert cannot go in. `ON CONFLICT DO NOTHING` with no target
    leaves the firm as it was and lets the rest of the deploy run."""
    inactive = _office_equipment(db, INACTIVE_SAME_NAME)
    client_level = _office_equipment(db, CLIENT_LEVEL_ONLY)
    _apply(db)
    assert _office_equipment(db, INACTIVE_SAME_NAME) == inactive
    assert _office_equipment(db, CLIENT_LEVEL_ONLY) == client_level
    # …and the firms after them in the statement were still served.
    assert len(_office_equipment(db, ONBOARDED)) == 1


def test_a_firm_with_no_chart_gets_nothing(db):
    _apply(db)
    assert _office_equipment(db, NO_CHART) == []


def test_it_inserts_rows_and_changes_none_that_exist(db):
    assert _psql(db, "CREATE TABLE _before AS TABLE chart_of_accounts;").returncode == 0
    before = int(_rows(db, "SELECT count(*) FROM chart_of_accounts")[0])
    _apply(db)
    after = int(_rows(db, "SELECT count(*) FROM chart_of_accounts")[0])
    assert after - before == 4          # ONBOARDED, CROWDED, ONLY_AN_EXPENSE, INACTIVE_OTHER_NAME
    changed = _rows(db, """SELECT count(*) FROM _before b
                           WHERE NOT EXISTS (SELECT 1 FROM chart_of_accounts c
                                             WHERE c.id = b.id AND to_jsonb(c) = to_jsonb(b))""")
    assert changed == ["0"]


def test_rerunning_adds_nothing(db):
    _apply(db)
    first = int(_rows(db, "SELECT count(*) FROM chart_of_accounts")[0])
    _apply(db)
    assert int(_rows(db, "SELECT count(*) FROM chart_of_accounts")[0]) == first
    assert len(_office_equipment(db, ONBOARDED)) == 1


# ── the rollback ────────────────────────────────────────────────────────────

REFERENCED_BY_A_JOURNAL = "48200000-0000-0000-0000-0000000000a1"
REFERENCED_BY_A_BUDGET = "48200000-0000-0000-0000-0000000000a2"


def _two_firms_that_use_their_ledger(dsn: str) -> None:
    """After the forward migration: one 1508 ledger carries a journal line, one
    carries a budget (ON DELETE CASCADE - a blind DELETE would take it with it)."""
    used_by_journal = "48200000-0000-0000-0000-0000000000f1"
    used_by_budget = "48200000-0000-0000-0000-0000000000f2"
    entry = "48200000-0000-0000-0000-0000000000e1"
    c1 = "48200000-0000-0000-0000-0000000000c2"
    c2 = "48200000-0000-0000-0000-0000000000c3"
    r = _psql(dsn, f"""
        INSERT INTO firms (id, name, email) VALUES
          ('{used_by_journal}', 'Posts', 'p482@t.in'), ('{used_by_budget}', 'Budgets', 'b482@t.in');
        INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
          ('{c1}', '{used_by_journal}', 'One', 'Proprietorship'),
          ('{c2}', '{used_by_budget}', 'Two', 'Proprietorship');
        {_account(used_by_journal, '1101', 'Bank Account', subtype='Bank', acct_id='48200000-0000-0000-0000-0000000000b1')}
        {_account(used_by_journal, '1508', 'Office Equipment', acct_id=REFERENCED_BY_A_JOURNAL)}
        {_account(used_by_budget, '1508', 'Office Equipment', acct_id=REFERENCED_BY_A_BUDGET)}
        INSERT INTO journal_entries (id, firm_id, client_id, entry_date, reference_no,
                                     narration, entry_type, is_posted, status)
          VALUES ('{entry}', '{used_by_journal}', '{c1}', '2026-08-20', 'OE-1', 'n', 'Journal', true, 'posted');
        INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise) VALUES
          ('{entry}', '{REFERENCED_BY_A_JOURNAL}', 500000, 0),
          ('{entry}', '48200000-0000-0000-0000-0000000000b1', 0, 500000);
        INSERT INTO account_budgets (firm_id, client_id, account_id, fy, budget_paise)
          VALUES ('{used_by_budget}', '{c2}', '{REFERENCED_BY_A_BUDGET}', '2026-27', 100000);
    """)
    assert r.returncode == 0, r.stderr


def test_the_rollback_removes_only_a_ledger_nothing_refers_to(db):
    _apply(db)
    _two_firms_that_use_their_ledger(db)
    assert len(_office_equipment(db, ONBOARDED)) == 1

    _apply(db, _ROLLBACK)

    # unreferenced: gone, as are the other three 482 added
    assert _office_equipment(db, ONBOARDED) == []
    assert _office_equipment(db, CROWDED) == []
    assert _office_equipment(db, ONLY_AN_EXPENSE) == [
        "5100|Expense|Overhead|firm|active|-|Office Equipment Repairs"]
    # a journal line points at it: stays, and the entry still has both legs
    assert _rows(db, f"SELECT count(*) FROM chart_of_accounts WHERE id = '{REFERENCED_BY_A_JOURNAL}'") == ["1"]
    assert _rows(db, f"SELECT count(*) FROM journal_lines WHERE account_id = '{REFERENCED_BY_A_JOURNAL}'") == ["1"]
    # a budget cascades off the account: the account stays, so the budget does
    assert _rows(db, f"SELECT count(*) FROM chart_of_accounts WHERE id = '{REFERENCED_BY_A_BUDGET}'") == ["1"]
    assert _rows(db, f"SELECT count(*) FROM account_budgets WHERE account_id = '{REFERENCED_BY_A_BUDGET}'") == ["1"]
    # never a candidate: the migration-011 chart's own ledger (code 1501), and a
    # client-level or inactive account that merely shares the name
    assert _office_equipment(db, MIGRATION_011) == [
        "1501|Asset|Fixed Asset|firm|active|-|Office Equipment"]
    assert len(_office_equipment(db, CLIENT_LEVEL_ONLY)) == 1
    assert len(_office_equipment(db, INACTIVE_SAME_NAME)) == 1


def test_the_rollback_can_run_twice_and_the_forward_migration_restores_what_it_took(db):
    _apply(db)
    _apply(db, _ROLLBACK)
    _apply(db, _ROLLBACK)
    assert _office_equipment(db, ONBOARDED) == []
    _apply(db)
    assert _office_equipment(db, ONBOARDED) == [
        "1508|Asset|Fixed Asset|firm|active|-|Office Equipment"]


def test_no_foreign_key_to_the_chart_is_composite(db):
    """The rollback reads each referencing column of pg_constraint. A composite
    key would make "this column equals the account's id" the wrong question, so
    the day one is added this fails and the rollback is rewritten for it."""
    assert _rows(db, """SELECT count(*) FROM pg_constraint
                        WHERE contype = 'f' AND confrelid = 'public.chart_of_accounts'::regclass
                          AND array_length(conkey, 1) > 1""") == ["0"]
