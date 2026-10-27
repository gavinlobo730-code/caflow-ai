"""Migration 553 - an intangible asset can name the ledger its accumulated amortisation is kept in, on real Postgres (POST-A-345, stage 1).

The migration adds `fixed_assets.accumulated_account_id` (a pointer, NULL for every existing asset) and gives each firm that keeps an
Intangible Assets ledger an "Accumulated Amortisation" ledger beside it. NOTHING READS OR WRITES EITHER YET: this file holds that the
migration inserts rows and changes no row that exists, that the new ledger classifies where its cost ledger does and stays INVESTING
in the cash-flow statement, that a firm it cannot serve is skipped without aborting the deploy and named in a WARNING, and that the
rollback refuses to lose what the later stages record.

Runs only when HARNESS_PG is set + psql on PATH, like every other *_pg test.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import uuid

import pytest

from domain.reporting.year_end_lines import schedule_line_for_account
from services.coa_seed_service import STANDARD_COA

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

_MIGRATIONS = pathlib.Path(__file__).resolve().parents[1] / "migrations"
_FORWARD = _MIGRATIONS / "553_an_intangible_asset_can_name_the_ledger_its_accumulated_amortisation_is_kept_in.sql"
_ROLLBACK = _MIGRATIONS / "553_an_intangible_asset_can_name_the_ledger_its_accumulated_amortisation_is_kept_in_rollback.sql"

ONBOARDED = "55300000-0000-0000-0000-000000000001"      # the standard chart as it stood
OLD_CHART = "55300000-0000-0000-0000-000000000002"      # migration 093's shape: Intangible Assets is a 'Fixed Asset'
NO_INTANGIBLE = "55300000-0000-0000-0000-000000000003"
CROWDED = "55300000-0000-0000-0000-000000000004"        # 1591 to 1599 all taken
CODE_TAKEN = "55300000-0000-0000-0000-000000000005"     # 1591 taken by another name
INACTIVE_SAME_NAME = "55300000-0000-0000-0000-000000000006"
CLIENT_LEVEL_ONLY = "55300000-0000-0000-0000-000000000007"
ALREADY = "55300000-0000-0000-0000-000000000008"        # has its own Accumulated Amortisation
NO_CHART = "55300000-0000-0000-0000-000000000009"
MAPPED = "55300000-0000-0000-0000-00000000000a"         # the CA mapped the cost ledger
NULL_SUBTYPE = "55300000-0000-0000-0000-00000000000b"   # Intangible Assets with no subtype

CLIENT = "55300000-0000-0000-0000-0000000000c1"         # belongs to CLIENT_LEVEL_ONLY

ALL_FIRMS = (ONBOARDED, OLD_CHART, NO_INTANGIBLE, CROWDED, CODE_TAKEN, INACTIVE_SAME_NAME, CLIENT_LEVEL_ONLY, ALREADY,
             NO_CHART, MAPPED, NULL_SUBTYPE)


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line for line in r.stdout.strip().splitlines() if line]


def _account(firm: str, code: str, name: str, *, account_type: str = "Asset", subtype: str | None = "Fixed Asset",
             client: str | None = None, active: bool = True, mapping: str | None = None, acct_id: str | None = None) -> str:
    cols = "firm_id, client_id, account_code, account_name, account_type, account_subtype, is_active, schedule_iii_mapping"
    client_sql = "'" + client + "'" if client else "NULL"
    subtype_sql = "'" + subtype + "'" if subtype else "NULL"
    mapping_sql = "'" + mapping + "'" if mapping else "NULL"
    vals = (f"'{firm}', {client_sql}, '{code}', '{name}', '{account_type}', {subtype_sql}, "
            f"{'TRUE' if active else 'FALSE'}, {mapping_sql}")
    if acct_id:
        cols, vals = "id, " + cols, f"'{acct_id}', " + vals
    return f"INSERT INTO chart_of_accounts ({cols}) VALUES ({vals});"


def _standard_chart_before_553(firm: str) -> str:
    """The chart seed_firm_coa gave a firm until this change: STANDARD_COA minus the one row 553 is about, read from the real list."""
    return "\n".join(
        _account(firm, code, name.replace("'", "''"), account_type=atype, subtype=sub)
        for code, name, atype, sub in STANDARD_COA if name != "Accumulated Amortisation")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"c19_aa553_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    # The harness template is built with every migration, so the column is already there; the migration is idempotent and these
    # tests run it against charts as they stood, but start each from a database that does not yet have the column.
    try:
        firms = ", ".join(f"('{f}', 'Firm {i}', 'f{i}@t.in')" for i, f in enumerate(ALL_FIRMS))
        crowded = "\n".join(_account(CROWDED, str(c), f"Other {c}") for c in range(1591, 1600))
        seed = _psql(dsn, f"""
            DROP INDEX IF EXISTS fixed_assets_accumulated_account_idx;
            ALTER TABLE fixed_assets DROP COLUMN IF EXISTS accumulated_account_id;
            DELETE FROM chart_of_accounts WHERE account_name = 'Accumulated Amortisation';

            INSERT INTO firms (id, name, email) VALUES {firms};
            INSERT INTO clients (id, firm_id, client_name, entity_type)
              VALUES ('{CLIENT}', '{CLIENT_LEVEL_ONLY}', 'Mine', 'Proprietorship');

            {_standard_chart_before_553(ONBOARDED)}

            {_account(OLD_CHART, '1534', 'Intangible Assets', subtype='Fixed Asset')}
            {_account(OLD_CHART, '1590', 'Accumulated Depreciation', subtype='Contra Asset')}

            {_account(NO_INTANGIBLE, '1501', 'Plant & Machinery')}
            {_account(NO_INTANGIBLE, '1590', 'Accumulated Depreciation')}

            {_account(CROWDED, '1506', 'Intangible Assets', subtype='Intangible Asset')}
            {crowded}

            {_account(CODE_TAKEN, '1506', 'Intangible Assets', subtype='Intangible Asset')}
            {_account(CODE_TAKEN, '1591', 'Some Other Ledger')}

            {_account(INACTIVE_SAME_NAME, '1506', 'Intangible Assets', subtype='Intangible Asset')}
            {_account(INACTIVE_SAME_NAME, '1592', 'Accumulated Amortisation', subtype='Intangible Fixed Asset', active=False)}

            {_account(CLIENT_LEVEL_ONLY, '1506', 'Intangible Assets', subtype='Intangible Asset')}
            {_account(CLIENT_LEVEL_ONLY, '1593', 'Accumulated Amortisation', subtype='Intangible Fixed Asset', client=CLIENT)}

            {_account(ALREADY, '1506', 'Intangible Assets', subtype='Intangible Asset')}
            {_account(ALREADY, '1700', 'Accumulated Amortisation', subtype='Contra Asset')}

            {_account(MAPPED, '1506', 'Intangible Assets', subtype='Intangible Asset', mapping='Intangible Fixed Assets')}

            {_account(NULL_SUBTYPE, '1506', 'Intangible Assets', subtype=None)}
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _apply(dsn: str, path: pathlib.Path = _FORWARD) -> subprocess.CompletedProcess:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True)
    return r


def _must_apply(dsn: str, path: pathlib.Path = _FORWARD) -> str:
    r = _apply(dsn, path)
    assert r.returncode == 0, r.stderr
    return r.stderr


def _amortisation(dsn: str, firm: str) -> list[str]:
    return _rows(dsn, f"""SELECT account_code || '|' || account_type || '|' || coalesce(account_subtype, '-') || '|' ||
                                 coalesce(schedule_iii_mapping, '-') || '|' || coalesce(client_id::text, 'firm') || '|' ||
                                 CASE WHEN is_active THEN 'active' ELSE 'inactive' END
                          FROM chart_of_accounts
                          WHERE firm_id = '{firm}' AND account_name = 'Accumulated Amortisation'
                          ORDER BY account_code""")


# ── what it adds ────────────────────────────────────────────────────────────

def test_an_onboarded_firm_gets_the_ledger_on_the_intangible_line_and_investing(db):
    assert _amortisation(db, ONBOARDED) == []
    _must_apply(db)
    assert _amortisation(db, ONBOARDED) == ["1591|Asset|Intangible Fixed Asset|-|firm|active"]


def test_its_subtype_classifies_where_the_cost_ledger_does_and_is_investing_in_the_cash_flow(db):
    """The two readers of the subtype, asked with the subtype the migration wrote: the Schedule III line, and the cash-flow
    statement's investing test (Python `_classify_activity` and the SQL twin both say a subtype containing 'fixed')."""
    _must_apply(db)
    sub = _rows(db, f"SELECT account_subtype FROM chart_of_accounts WHERE firm_id = '{ONBOARDED}' "
                    "AND account_name = 'Accumulated Amortisation'")[0]
    cost_sub = _rows(db, f"SELECT account_subtype FROM chart_of_accounts WHERE firm_id = '{ONBOARDED}' "
                         "AND account_name = 'Intangible Assets'")[0]
    assert schedule_line_for_account("Asset", sub) == schedule_line_for_account("Asset", cost_sub) == "intangible_assets"
    assert "fixed" in sub.lower()


def test_a_firm_whose_cost_ledger_is_not_on_the_intangible_line_gets_a_ledger_that_classifies_the_same(db):
    """Migration 093's chart seeded 'Intangible Assets' with subtype 'Fixed Asset'. The new ledger copies it, so the pair classify
    identically by construction and nothing is put on a line its cost is not on."""
    _must_apply(db)
    assert _amortisation(db, OLD_CHART) == ["1591|Asset|Fixed Asset|-|firm|active"]


def test_the_cost_ledgers_mapping_is_copied(db):
    _must_apply(db)
    assert _amortisation(db, MAPPED) == ["1591|Asset|Intangible Fixed Asset|Intangible Fixed Assets|firm|active"]


def test_a_firm_whose_1591_is_taken_gets_the_next_free_code(db):
    _must_apply(db)
    assert _amortisation(db, CODE_TAKEN) == ["1592|Asset|Intangible Fixed Asset|-|firm|active"]


def test_the_engines_own_lookup_finds_it_afterwards_and_not_before(db):
    """The predicate `phase2_journal_service._find_account` sends to PostgREST, asked of the database."""
    ask = (f"SELECT count(*) FROM chart_of_accounts WHERE firm_id = '{ONBOARDED}' "
           f"AND (client_id = '{uuid.uuid4()}' OR client_id IS NULL) "
           "AND account_name ILIKE '%Accumulated Amortisation%' AND is_active = TRUE")
    assert _rows(db, ask) == ["0"]
    _must_apply(db)
    assert _rows(db, ask) == ["1"]


def test_neither_pattern_the_engine_already_searches_can_find_it(db):
    _must_apply(db)
    for pattern in ("%Intangible Assets%", "%Accumulated Depreciation%"):
        found = _rows(db, f"SELECT count(*) FROM chart_of_accounts WHERE firm_id = '{ONBOARDED}' "
                          f"AND account_name ILIKE '{pattern}' AND account_name = 'Accumulated Amortisation'")
        assert found == ["0"], pattern


# ── what it leaves alone ────────────────────────────────────────────────────

def test_firms_it_cannot_serve_are_skipped_without_aborting_the_rest(db):
    stderr = _must_apply(db)
    assert _amortisation(db, NO_INTANGIBLE) == []
    assert _amortisation(db, NULL_SUBTYPE) == []
    assert _amortisation(db, CROWDED) == []
    assert _amortisation(db, NO_CHART) == []
    assert _amortisation(db, INACTIVE_SAME_NAME) == ["1592|Asset|Intangible Fixed Asset|-|firm|inactive"]
    # a client-level account of the name does not serve the FIRM (the engine's lookup is firm-level or the client's own), but the
    # name is UNIQUE per firm, so the insert is skipped, and the firm is named below
    assert _amortisation(db, CLIENT_LEVEL_ONLY) == [f"1593|Asset|Intangible Fixed Asset|-|{CLIENT}|active"]
    assert _amortisation(db, ALREADY) == ["1700|Asset|Contra Asset|-|firm|active"]
    # …and the firms after them in the statement were still served.
    assert len(_amortisation(db, ONBOARDED)) == 1 and len(_amortisation(db, MAPPED)) == 1
    # Each skipped firm is NAMED, with the reason, because a silent skip leaves a firm unable to use the feature.
    for firm in (NO_INTANGIBLE, NULL_SUBTYPE):
        assert f"firm {firm} was not given an Accumulated Amortisation ledger: it has no active firm-level Intangible Assets" in stderr
    assert f"firm {CROWDED} was not given" in stderr and "codes 1591 to 1599 are all taken" in stderr
    assert f"firm {ALREADY} was not given" not in stderr, "a firm that already has the ledger is not a skip"
    assert f"firm {ONBOARDED} was not given" not in stderr


def test_it_inserts_rows_and_changes_none_that_exist_and_posts_nothing(db):
    assert _psql(db, "CREATE TABLE _before AS TABLE chart_of_accounts;").returncode == 0
    lines_before = _rows(db, "SELECT count(*) FROM journal_lines")
    assets_before = _rows(db, "SELECT count(*) FROM fixed_assets")
    before = int(_rows(db, "SELECT count(*) FROM chart_of_accounts")[0])
    _must_apply(db)
    after = int(_rows(db, "SELECT count(*) FROM chart_of_accounts")[0])
    assert after - before == 4          # ONBOARDED, OLD_CHART, CODE_TAKEN, MAPPED
    changed = _rows(db, """SELECT count(*) FROM _before b
                           WHERE NOT EXISTS (SELECT 1 FROM chart_of_accounts c
                                             WHERE c.id = b.id AND to_jsonb(c) = to_jsonb(b))""")
    assert changed == ["0"]
    assert _rows(db, "SELECT count(*) FROM journal_lines") == lines_before
    assert _rows(db, "SELECT count(*) FROM fixed_assets") == assets_before


def test_rerunning_adds_nothing(db):
    _must_apply(db)
    first = int(_rows(db, "SELECT count(*) FROM chart_of_accounts")[0])
    _must_apply(db)
    assert int(_rows(db, "SELECT count(*) FROM chart_of_accounts")[0]) == first
    assert len(_amortisation(db, ONBOARDED)) == 1


# ── the column ──────────────────────────────────────────────────────────────

def test_the_column_is_a_nullable_pointer_with_no_default_and_every_existing_asset_reads_null(db):
    firm_asset = "55300000-0000-0000-0000-0000000000d1"
    r = _psql(db, f"""
        INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
          ('55300000-0000-0000-0000-0000000000c2', '{ONBOARDED}', 'Holder', 'Proprietorship');
        INSERT INTO fixed_assets (id, firm_id, client_id, asset_code, asset_name, asset_category, purchase_date,
                                  purchase_cost_paise, useful_life_years, depreciation_method)
          VALUES ('{firm_asset}', '{ONBOARDED}', '55300000-0000-0000-0000-0000000000c2', 'FA-1', 'Licence', 'Intangibles',
                  '2026-04-01', 1000000, 5, 'SL');
    """)
    assert r.returncode == 0, r.stderr
    _must_apply(db)
    assert _rows(db, f"SELECT accumulated_account_id IS NULL FROM fixed_assets WHERE id = '{firm_asset}'") == ["t"]
    assert _rows(db, """SELECT is_nullable || '|' || coalesce(column_default, '-') FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = 'fixed_assets'
                          AND column_name = 'accumulated_account_id'""") == ["YES|-"]


def test_a_ledger_an_asset_points_at_cannot_be_deleted(db):
    _must_apply(db)
    asset = "55300000-0000-0000-0000-0000000000d2"
    client = "55300000-0000-0000-0000-0000000000c3"
    ledger = _rows(db, f"SELECT id FROM chart_of_accounts WHERE firm_id = '{ONBOARDED}' AND account_name = 'Accumulated Amortisation'")[0]
    r = _psql(db, f"""
        INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{client}', '{ONBOARDED}', 'Holder', 'Proprietorship');
        INSERT INTO fixed_assets (id, firm_id, client_id, asset_code, asset_name, asset_category, purchase_date,
                                  purchase_cost_paise, useful_life_years, depreciation_method, accumulated_account_id)
          VALUES ('{asset}', '{ONBOARDED}', '{client}', 'FA-2', 'Licence', 'Intangibles', '2026-04-01', 1000000, 5, 'SL', '{ledger}');
    """)
    assert r.returncode == 0, r.stderr
    refused = _psql(db, f"DELETE FROM chart_of_accounts WHERE id = '{ledger}';")
    assert refused.returncode != 0 and "violates foreign key constraint" in refused.stderr


def test_a_signed_in_session_cannot_write_the_pointer(db):
    """The API writes it. `fixed_assets` is granted to the signed-in role for SELECT only (migrations 166 and 245), and a new column
    inherits the table's grants, so this holds without a grant of its own; the assertion is here so a later grant cannot widen it."""
    _must_apply(db)
    roles = _rows(db, "SELECT rolname FROM pg_roles WHERE rolname IN ('authenticated', 'anon')")
    if "authenticated" not in roles:
        pytest.skip("the harness has no authenticated role")
    for role in roles:
        assert _rows(db, f"SELECT has_column_privilege('{role}', 'public.fixed_assets', 'accumulated_account_id', 'UPDATE')") == ["f"], role
        assert _rows(db, f"SELECT has_column_privilege('{role}', 'public.fixed_assets', 'accumulated_account_id', 'INSERT')") == ["f"], role


# ── the rollback ────────────────────────────────────────────────────────────

def test_the_rollback_removes_an_unreferenced_ledger_and_the_column_and_the_forward_migration_restores_them(db):
    _must_apply(db)
    _must_apply(db, _ROLLBACK)
    assert _amortisation(db, ONBOARDED) == []
    assert _rows(db, """SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public'
                        AND table_name = 'fixed_assets' AND column_name = 'accumulated_account_id'""") == ["0"]
    # never a candidate: an inactive account, a client-level one, or one the CA created under another name or code
    assert _amortisation(db, INACTIVE_SAME_NAME) == ["1592|Asset|Intangible Fixed Asset|-|firm|inactive"]
    assert _amortisation(db, CLIENT_LEVEL_ONLY) == [f"1593|Asset|Intangible Fixed Asset|-|{CLIENT}|active"]
    assert _amortisation(db, ALREADY) == ["1700|Asset|Contra Asset|-|firm|active"]
    _must_apply(db)
    assert _amortisation(db, ONBOARDED) == ["1591|Asset|Intangible Fixed Asset|-|firm|active"]


def test_the_rollback_can_run_twice(db):
    _must_apply(db)
    _must_apply(db, _ROLLBACK)
    _must_apply(db, _ROLLBACK)


def _post_to_the_ledger(dsn: str) -> None:
    """A journal line against the seeded ledger of ONBOARDED: what stage 3's reclassification will do."""
    ledger = _rows(dsn, f"SELECT id FROM chart_of_accounts WHERE firm_id = '{ONBOARDED}' AND account_name = 'Accumulated Amortisation'")[0]
    bank = _rows(dsn, f"SELECT id FROM chart_of_accounts WHERE firm_id = '{ONBOARDED}' AND account_name = 'Accumulated Depreciation'")[0]
    client = "55300000-0000-0000-0000-0000000000c4"
    entry = "55300000-0000-0000-0000-0000000000e1"
    r = _psql(dsn, f"""
        INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{client}', '{ONBOARDED}', 'Poster', 'Proprietorship');
        INSERT INTO journal_entries (id, firm_id, client_id, entry_date, reference_no, narration, entry_type, is_posted, status)
          VALUES ('{entry}', '{ONBOARDED}', '{client}', '2026-08-20', 'AA-1', 'n', 'Journal', true, 'posted');
        INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise) VALUES
          ('{entry}', '{bank}', 500000, 0), ('{entry}', '{ledger}', 0, 500000);
    """)
    assert r.returncode == 0, r.stderr


def test_the_rollback_refuses_while_a_journal_line_is_posted_to_the_ledger_and_changes_nothing(db):
    _must_apply(db)
    _post_to_the_ledger(db)
    refused = _apply(db, _ROLLBACK)
    assert refused.returncode != 0 and "rollback REFUSED" in refused.stderr
    assert _amortisation(db, ONBOARDED) == ["1591|Asset|Intangible Fixed Asset|-|firm|active"]
    assert _rows(db, """SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public'
                        AND table_name = 'fixed_assets' AND column_name = 'accumulated_account_id'""") == ["1"]


def test_the_rollback_refuses_while_an_asset_points_at_a_ledger_and_changes_nothing(db):
    _must_apply(db)
    client = "55300000-0000-0000-0000-0000000000c5"
    ledger = _rows(db, f"SELECT id FROM chart_of_accounts WHERE firm_id = '{ONBOARDED}' AND account_name = 'Accumulated Amortisation'")[0]
    r = _psql(db, f"""
        INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{client}', '{ONBOARDED}', 'Holder', 'Proprietorship');
        INSERT INTO fixed_assets (firm_id, client_id, asset_code, asset_name, asset_category, purchase_date,
                                  purchase_cost_paise, useful_life_years, depreciation_method, accumulated_account_id)
          VALUES ('{ONBOARDED}', '{client}', 'FA-3', 'Licence', 'Intangibles', '2026-04-01', 1000000, 5, 'SL', '{ledger}');
    """)
    assert r.returncode == 0, r.stderr
    refused = _apply(db, _ROLLBACK)
    assert refused.returncode != 0 and "rollback REFUSED" in refused.stderr and "1 asset(s) point" in refused.stderr
    assert _amortisation(db, ONBOARDED) == ["1591|Asset|Intangible Fixed Asset|-|firm|active"]


def test_no_foreign_key_to_the_chart_is_composite(db):
    """The rollback reads each referencing column of pg_constraint. A composite key would make "this column equals the account's id"
    the wrong question, so the day one is added this fails and the rollback is rewritten for it."""
    _must_apply(db)
    assert _rows(db, """SELECT count(*) FROM pg_constraint
                        WHERE contype = 'f' AND confrelid = 'public.chart_of_accounts'::regclass
                          AND array_length(conkey, 1) > 1""") == ["0"]
