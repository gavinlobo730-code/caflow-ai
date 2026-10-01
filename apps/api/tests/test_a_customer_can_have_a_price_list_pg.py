"""Migration 459 — price lists, on real PostgreSQL (accounting-20).

WHY THIS NEEDS A REAL DATABASE. The design is mostly constraints: that a rate is
strictly positive (the catalogue's own "0 means no default price" is the
precedent), that a list's name is unique per client without regard to case or
spacing, that an item filed under the WRONG client is refused by the database
rather than by every writer remembering, that a customer's pointer survives the
list going away by becoming NULL, and that both new tables carry the firm policy
and the RESTRICTIVE assignment scope every `client_id` table needs. None of it is
observable in mock mode, where the in-memory double accepts anything.

Runs only with HARNESS_PG set and psql on PATH, like every other `*_pg.py` test.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

MIGRATION = "459_a_customer_can_have_a_price_list.sql"
FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
OTHER = "33333333-3333-3333-3333-333333333333"
CUSTOMER = "44444444-4444-4444-4444-444444444444"
ITEM = "55555555-5555-5555-5555-555555555555"
ITEM_B = "66666666-6666-6666-6666-666666666666"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line for line in r.stdout.strip().splitlines() if line]


@pytest.fixture()
def db(pg_template):
    assert MIGRATION not in pg_template.failed, (
        f"{MIGRATION} did not apply cleanly to a fresh database")
    admin = _ADMIN.strip()
    name = f"pl_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan)
            VALUES ('{CLIENT}', '{FIRM}', 'C1', 'Private Limited', 'AAACA1234A'),
                   ('{OTHER}',  '{FIRM}', 'C2', 'Private Limited', 'AAACB1234B');
            INSERT INTO customers (id, firm_id, client_id, name)
            VALUES ('{CUSTOMER}', '{FIRM}', '{CLIENT}', 'Dealer Co');
            INSERT INTO service_catalogue (id, firm_id, client_id, name)
            VALUES ('{ITEM}',   '{FIRM}', '{CLIENT}', 'Widget'),
                   ('{ITEM_B}', '{FIRM}', '{CLIENT}', 'Gadget');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _list(dsn, name="Dealer", client=CLIENT):
    return _psql(dsn, f"""
        INSERT INTO price_lists (firm_id, client_id, name)
        VALUES ('{FIRM}', '{client}', '{name}');
    """)


def _list_id(dsn, name="Dealer", client=CLIENT) -> str:
    return _rows(dsn, f"SELECT id FROM price_lists WHERE client_id = '{client}' "
                      f"AND name = '{name}';")[0]


def _item(dsn, list_id, rate=100000, item=ITEM, client=CLIENT):
    return _psql(dsn, f"""
        INSERT INTO price_list_items (firm_id, client_id, price_list_id, service_catalogue_id, rate_paise)
        VALUES ('{FIRM}', '{client}', '{list_id}', '{item}', {rate});
    """)


# ── the lists ────────────────────────────────────────────────────────────────

def test_a_list_is_accepted(db):
    assert _list(db).returncode == 0


def test_a_blank_name_is_refused(db):
    assert _list(db, name="   ").returncode != 0


def test_a_name_is_unique_per_client_whatever_its_case_or_spacing(db):
    assert _list(db, name="Dealer").returncode == 0
    assert _list(db, name="DEALER").returncode != 0
    assert _list(db, name="  dealer ").returncode != 0


def test_another_client_may_use_the_same_name(db):
    assert _list(db, name="Dealer").returncode == 0
    assert _list(db, name="Dealer", client=OTHER).returncode == 0


# ── the rates ────────────────────────────────────────────────────────────────

def test_a_rate_is_strictly_positive(db):
    """0 means "no default price" on the catalogue itself, so a list rate of 0
    would be indistinguishable from "this list has no price for the item"."""
    _list(db)
    lid = _list_id(db)
    assert _item(db, lid, rate=1).returncode == 0
    assert _item(db, lid, rate=0, item=ITEM_B).returncode != 0
    assert _item(db, lid, rate=-5, item=ITEM_B).returncode != 0


def test_an_item_has_one_rate_per_list(db):
    _list(db)
    lid = _list_id(db)
    assert _item(db, lid).returncode == 0
    assert _item(db, lid, rate=200000).returncode != 0


def test_the_same_item_may_be_priced_on_two_lists(db):
    _list(db, name="Dealer")
    _list(db, name="Retail")
    assert _item(db, _list_id(db, "Dealer")).returncode == 0
    assert _item(db, _list_id(db, "Retail"), rate=150000).returncode == 0


def test_an_item_filed_under_the_wrong_client_is_refused_by_the_database(db):
    """The composite key (price_list_id, client_id) -> price_lists(id, client_id):
    a writer that gets the client wrong is refused, not trusted."""
    _list(db)
    lid = _list_id(db)
    r = _item(db, lid, client=OTHER)
    assert r.returncode != 0
    assert "foreign key" in r.stderr.lower() or "violates" in r.stderr.lower()


def test_deleting_a_list_takes_its_rates_and_clears_a_customers_pointer(db):
    _list(db)
    lid = _list_id(db)
    assert _item(db, lid).returncode == 0
    assert _psql(db, f"UPDATE customers SET price_list_id = '{lid}' "
                     f"WHERE id = '{CUSTOMER}';").returncode == 0
    assert _psql(db, f"DELETE FROM price_lists WHERE id = '{lid}';").returncode == 0
    assert _rows(db, "SELECT count(*) FROM price_list_items;") == ["0"]
    assert _rows(db, f"SELECT price_list_id IS NULL FROM customers WHERE id = '{CUSTOMER}';") == ["t"]


def test_a_customer_has_no_list_until_somebody_gives_one(db):
    """No backfill, no default: NULL means none."""
    assert _rows(db, f"SELECT price_list_id IS NULL FROM customers WHERE id = '{CUSTOMER}';") == ["t"]
    assert _rows(db, "SELECT is_nullable FROM information_schema.columns "
                     "WHERE table_name = 'customers' AND column_name = 'price_list_id';") == ["YES"]
    assert _rows(db, "SELECT column_default IS NULL FROM information_schema.columns "
                     "WHERE table_name = 'customers' AND column_name = 'price_list_id';") == ["t"]


# ── the guards every client_id table carries ─────────────────────────────────

@pytest.mark.parametrize("table", ["price_lists", "price_list_items"])
def test_each_table_has_rls_the_firm_policy_and_the_restrictive_assignment_scope(db, table):
    assert _rows(db, f"SELECT relrowsecurity FROM pg_class WHERE relname = '{table}';") == ["t"]
    policies = set(_rows(db, f"""
        SELECT policyname || ':' || permissive FROM pg_policies
         WHERE schemaname = 'public' AND tablename = '{table}';"""))
    assert f"firm_isolation:PERMISSIVE" in policies
    assert f"{table}_assignment_scope:RESTRICTIVE" in policies


@pytest.mark.parametrize("table", ["price_lists", "price_list_items"])
def test_the_signed_in_role_reads_and_only_the_service_role_writes(db, table):
    grants = {tuple(r.split("|")) for r in _rows(db, f"""
        SELECT grantee || '|' || privilege_type FROM information_schema.role_table_grants
         WHERE table_schema = 'public' AND table_name = '{table}'
           AND grantee IN ('authenticated', 'service_role');""")}
    assert ("authenticated", "SELECT") in grants
    assert not {g for g in grants if g[0] == "authenticated" and g[1] != "SELECT"}
    assert {("service_role", p) for p in ("SELECT", "INSERT", "UPDATE", "DELETE")} <= grants
