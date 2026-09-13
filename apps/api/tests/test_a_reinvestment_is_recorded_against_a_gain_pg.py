"""Migration 385 — where the money went after the sale, on real PostgreSQL
(IT-19).

WHY THIS NEEDS A REAL DATABASE. Three of the design decisions are CONSTRAINTS
rather than code: the CHECK that keeps the four sections and the four asset
natures honest, the nullability that makes an unrecorded fact refusable rather
than defaulted, and the grant model — SELECT to the browser and nothing else,
because the exemption is computed server-side. None of that is observable in
mock mode, where the in-memory double accepts anything.

Runs only when HARNESS_PG is set + psql on PATH, like every other *_pg test.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid

import pytest

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
GAIN = "33333333-3333-3333-3333-333333333333"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [l for l in r.stdout.strip().splitlines() if l]


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"reinvest_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan)
            VALUES ('{CLIENT}', '{FIRM}', 'C1', 'Individual', 'AAAPA1234A');
            INSERT INTO capital_gains
                (id, firm_id, client_id, asset_description, asset_type,
                 purchase_date, sale_date, purchase_cost_paise, sale_value_paise)
            VALUES ('{GAIN}', '{FIRM}', '{CLIENT}', 'Plot at Wagholi', 'property',
                    DATE '2019-04-01', DATE '2025-06-10', 6000000000, 10000000000);
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _insert(dsn: str, **cols) -> subprocess.CompletedProcess:
    base = {"firm_id": f"'{FIRM}'", "client_id": f"'{CLIENT}'",
            "capital_gain_id": f"'{GAIN}'", "section": "'54F'",
            "new_asset_description": "'Flat 402'"}
    base.update(cols)
    return _psql(dsn, "INSERT INTO capital_gain_reinvestments ("
                      + ", ".join(base) + ") VALUES ("
                      + ", ".join(base.values()) + ");")


# ── the column on the parent ────────────────────────────────────────────────

def test_the_nature_column_is_nullable_with_no_default(db):
    got = _rows(db, """
        SELECT is_nullable, coalesce(column_default,'') FROM information_schema.columns
         WHERE table_schema='public' AND table_name='capital_gains'
           AND column_name='transferred_asset_nature';
    """)
    assert got == ["YES|"], got
    # And the existing row really is NULL — nothing backfilled a guess.
    assert _rows(db, f"SELECT transferred_asset_nature IS NULL "
                     f"FROM capital_gains WHERE id = '{GAIN}';") == ["t"]


@pytest.mark.parametrize("nature", ["residential_house", "agricultural_land",
                                    "land_or_building", "other"])
def test_every_nature_the_engine_knows_is_accepted(db, nature):
    r = _psql(db, f"UPDATE capital_gains SET transferred_asset_nature = '{nature}' "
                  f"WHERE id = '{GAIN}';")
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("nature", ["house", "plot", "RESIDENTIAL_HOUSE", ""])
def test_a_nature_the_engine_does_not_know_is_refused(db, nature):
    r = _psql(db, f"UPDATE capital_gains SET transferred_asset_nature = '{nature}' "
                  f"WHERE id = '{GAIN}';")
    assert r.returncode != 0


def test_the_check_accepts_exactly_the_natures_the_engine_knows(db):
    """THE RULE, NOT FOUR SPELLINGS OF IT. Naming a handful of bad values
    catches a CHECK that was dropped and misses one that was WIDENED — and a
    widened CHECK is how a value the engine has never heard of reaches
    `_reaches`, falls through every section, and silently exempts nothing.
    The accepted set is compared to `rex.ASSET_NATURES` itself."""
    from domain.income_tax import reinvestment_exemption as rex
    definition = _rows(db, """
        SELECT pg_get_constraintdef(oid) FROM pg_constraint
         WHERE conrelid = 'public.capital_gains'::regclass
           AND conname = 'capital_gains_transferred_asset_nature_check';
    """)
    assert definition, "the CHECK is gone"
    accepted = set(re.findall(r"'([^']*)'", definition[0]))
    assert accepted == set(rex.ASSET_NATURES), accepted


@pytest.mark.parametrize("column,constant", [
    ("section", "SECTIONS"),
    ("acquisition_kind", "ACQUISITION_KINDS"),
])
def test_each_claim_check_accepts_exactly_what_the_engine_knows(db, column, constant):
    from domain.income_tax import reinvestment_exemption as rex
    definition = _rows(db, f"""
        SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c
         WHERE c.conrelid = 'public.capital_gain_reinvestments'::regclass
           AND c.contype = 'c'
           AND pg_get_constraintdef(c.oid) LIKE '%{column}%'
           AND pg_get_constraintdef(c.oid) LIKE '%ANY%';
    """)
    assert definition, f"no CHECK on {column}"
    accepted = set(re.findall(r"'([^']*)'", definition[0]))
    assert accepted == set(getattr(rex, constant)), accepted


# ── the claim table ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("section", ["54", "54B", "54EC", "54F"])
def test_each_section_is_accepted(db, section):
    assert _insert(db, section=f"'{section}'").returncode == 0


@pytest.mark.parametrize("section", ["54EE", "80C", "54f", ""])
def test_a_section_outside_the_family_is_refused(db, section):
    assert _insert(db, section=f"'{section}'").returncode != 0


@pytest.mark.parametrize("kind", ["purchase", "construction", "bonds"])
def test_each_acquisition_kind_is_accepted(db, kind):
    assert _insert(db, acquisition_kind=f"'{kind}'").returncode == 0


@pytest.mark.parametrize("kind", ["gift", "inheritance"])
def test_an_unknown_acquisition_kind_is_refused(db, kind):
    assert _insert(db, acquisition_kind=f"'{kind}'").returncode != 0


def test_the_two_eligibility_facts_default_to_null_not_to_an_answer(db):
    """Blank must be a THIRD state. A 0 here would assert the assessee owned
    no other house, and a false would assert the land was not farmed."""
    assert _insert(db).returncode == 0
    got = _rows(db, "SELECT other_residential_houses_owned IS NULL, "
                    "agricultural_use_two_years IS NULL "
                    "FROM capital_gain_reinvestments;")
    assert got == ["t|t"]


def test_a_recorded_zero_is_kept_as_zero(db):
    assert _insert(db, other_residential_houses_owned="0").returncode == 0
    assert _rows(db, "SELECT other_residential_houses_owned "
                     "FROM capital_gain_reinvestments;") == ["0"]


def test_a_negative_amount_is_refused(db):
    for column in ("cost_paise", "cgas_deposit_paise", "other_residential_houses_owned"):
        assert _insert(db, **{column: "-1"}).returncode != 0, column


def test_several_claims_may_sit_against_one_transfer(db):
    """s.54EC bonds and a s.54F house are not mutually exclusive on a sale of
    land — nothing here is unique per gain."""
    assert _insert(db, section="'54EC'", acquisition_kind="'bonds'").returncode == 0
    assert _insert(db, section="'54F'").returncode == 0
    assert _rows(db, "SELECT count(*) FROM capital_gain_reinvestments;") == ["2"]


def test_deleting_the_register_entry_takes_its_claims_with_it(db):
    assert _insert(db).returncode == 0
    assert _psql(db, f"DELETE FROM capital_gains WHERE id = '{GAIN}';").returncode == 0
    assert _rows(db, "SELECT count(*) FROM capital_gain_reinvestments;") == ["0"]


def test_no_exemption_amount_is_stored(db):
    """The caps and the sections move by Finance Act, so a stored figure would
    be right on the day it was written and silently wrong afterwards."""
    cols = _rows(db, "SELECT column_name FROM information_schema.columns "
                     "WHERE table_schema='public' "
                     "AND table_name='capital_gain_reinvestments';")
    assert not [c for c in cols if "exempt" in c], cols


# ── the guards ──────────────────────────────────────────────────────────────

def test_the_browser_gets_select_and_nothing_else(db):
    """Migration 164's shape on the parent table: the exemption is computed
    server-side and there is no legitimate frontend write path."""
    got = _rows(db, """
        SELECT privilege_type FROM information_schema.role_table_grants
         WHERE table_schema='public' AND table_name='capital_gain_reinvestments'
           AND grantee='authenticated' ORDER BY privilege_type;
    """)
    assert got == ["SELECT"], got


def test_the_service_role_can_write(db):
    got = sorted(_rows(db, """
        SELECT privilege_type FROM information_schema.role_table_grants
         WHERE table_schema='public' AND table_name='capital_gain_reinvestments'
           AND grantee='service_role';
    """))
    assert got == ["DELETE", "INSERT", "SELECT", "UPDATE"], got


def test_row_level_security_is_on(db):
    assert _rows(db, "SELECT relrowsecurity FROM pg_class "
                     "WHERE oid = 'public.capital_gain_reinvestments'::regclass;") == ["t"]


def test_the_table_is_assignment_scoped(db):
    """Migration 084's one-shot loop has never run again (see 370), so a table
    created now carries only its firm-wide policy unless it says otherwise."""
    got = _rows(db, """
        SELECT policyname, permissive FROM pg_policies
         WHERE schemaname='public' AND tablename='capital_gain_reinvestments'
         ORDER BY policyname;
    """)
    assert "capital_gain_reinvestments_assignment_scope|RESTRICTIVE" in got, got
    assert any(g.startswith("firm_staff_read_capital_gain_reinvestments|PERMISSIVE")
               for g in got), got
