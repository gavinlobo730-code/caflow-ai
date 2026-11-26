"""Migration 617, proved against real PostgreSQL: a GSTR-8 amendment (Table 4 and Table 4.1) is recorded against the earlier month it amends
(POST-A-056).

WHAT THIS HOLDS
    * a row of each table is stored, with zero as the default of every amount;
    * the CHECKs say what the offline utility says: a GSTIN is a GSTIN, a month is MMYYYY, a place of supply is two digits, an amount is not
      negative, the action is one of the utility's two, and the original month is EARLIER than the statement's, by return-period order (a
      raw string comparison would call '062025' later than '012026');
    * the unique index is the utility's duplicate key: one live row per amended row per statement, a missing original place of supply is a
      VALUE of the key (not a wildcard), a withdrawn row frees its key and another month is another row;
    * no signed-in role holds any privilege on either table and the API's role holds all four, with row security on and the three policies
      the newest client tables carry;
    * the rollback drops both tables and the file can be applied again.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_STEM = "617_a_gstr_8_amendment_is_recorded_against_the_month_it_amends"
FILE, ROLLBACK = MIGRATIONS / f"{_STEM}.sql", MIGRATIONS / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the GSTR-8 amendment proof requires HARNESS_PG + psql",
)

T4, T41 = "ecommerce_operator_supply_amendments", "ecommerce_operator_unregistered_supply_amendments"
FIRM, CLIENT = str(uuid.uuid4()), str(uuid.uuid4())
OPERATOR, SELLER, OTHER = "27AAACA1234C1ZG", "29AABCU9603R1ZJ", "07AAACN2345C1ZZ"
# Foreign keys and guards are set aside so a row needs no firm, client or member; CHECK constraints and unique indexes are not.
SET_ASIDE = "SET session_replication_role = replica; "


def _run(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _scalar(dsn: str, sql: str) -> str:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"t617_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _run(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        assert not any(f.startswith("617_") for f in pg_template.failed), pg_template.failed
        yield f"{admin} dbname={name}"
    finally:
        _run(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _t4(dsn: str, **over) -> subprocess.CompletedProcess:
    cols = dict(firm_id=FIRM, client_id=CLIENT, gstin=OPERATOR, period="062026", original_period="042026", original_supplier_gstin=SELLER,
                original_place_of_supply="29", supplier_gstin=SELLER, place_of_supply="29", action="add")
    cols.update(over)
    names = ", ".join(cols)
    values = ", ".join("NULL" if v is None else (str(v) if isinstance(v, int) else f"'{v}'") for v in cols.values())
    return _run(dsn, f"{SET_ASIDE}INSERT INTO {T4} ({names}) VALUES ({values});")


def _t41(dsn: str, **over) -> subprocess.CompletedProcess:
    cols = dict(firm_id=FIRM, client_id=CLIENT, gstin=OPERATOR, period="062026", original_period="042026", original_enrolment_id="E-1",
                enrolment_id="E-1", action="add")
    cols.update(over)
    names = ", ".join(cols)
    values = ", ".join("NULL" if v is None else (str(v) if isinstance(v, int) else f"'{v}'") for v in cols.values())
    return _run(dsn, f"{SET_ASIDE}INSERT INTO {T41} ({names}) VALUES ({values});")


def test_a_row_of_each_table_is_stored_and_every_amount_defaults_to_nil(db):
    assert _t4(db).returncode == 0 and _t41(db).returncode == 0
    row = _scalar(db, f"SELECT concat_ws('|', gross_registered_paise, returns_registered_paise, gross_unregistered_paise, "
                      f"returns_unregistered_paise, igst_paise, cgst_paise, sgst_paise, action) FROM {T4};")
    assert row == "0|0|0|0|0|0|0|add"
    assert _scalar(db, f"SELECT concat_ws('|', gross_value_paise, returns_paise, action) FROM {T41};") == "0|0|add"


@pytest.mark.parametrize("over,what", [
    (dict(gstin="27AAACA1234C1"), "the operator's GSTIN"),
    (dict(original_supplier_gstin="not-a-gstin"), "the original supplier's GSTIN"),
    (dict(supplier_gstin="29aabcu9603r1zj"), "the revised supplier's GSTIN (upper case only)"),
    (dict(period="132026"), "a month that is not one"),
    (dict(period="12026"), "a month that is not six digits"),
    (dict(original_period="002026"), "an original month 00"),
    (dict(original_place_of_supply="9"), "a one-digit original place of supply"),
    (dict(place_of_supply="ABC"), "a place of supply that is not two digits"),
    (dict(igst_paise=-1), "negative IGST"),
    (dict(cgst_paise=-1), "negative CGST"),
    (dict(sgst_paise=-1), "negative SGST"),
    (dict(gross_registered_paise=-1), "negative gross, registered"),
    (dict(returns_registered_paise=-1), "negative returns, registered"),
    (dict(gross_unregistered_paise=-1), "negative gross, unregistered"),
    (dict(returns_unregistered_paise=-1), "negative returns, unregistered"),
    (dict(action="remove"), "an action that is neither of the utility's two"),
    (dict(action=None), "no action"),
    (dict(original_period="062026"), "the statement's own month"),
    (dict(original_period="072026"), "a later month"),
    (dict(original_period="062027"), "a later year"),
    (dict(period="062025", original_period="012026"), "a month the raw strings call earlier and the calendar calls later"),
])
def test_the_table_refuses_what_the_offline_utility_refuses(db, over, what):
    r = _t4(db, **over)
    assert r.returncode != 0 and ("violates check constraint" in r.stderr or "violates not-null" in r.stderr), (what, r.stderr or "stored")
    assert _scalar(db, f"SELECT count(*) FROM {T4};") == "0", what


@pytest.mark.parametrize("over,what", [
    (dict(period="132026"), "a month that is not one"),
    (dict(gross_value_paise=-1), "negative gross value"),
    (dict(returns_paise=-1), "negative returns"),
    (dict(action="remove"), "an action that is neither of the utility's two"),
    (dict(original_period="062026"), "the statement's own month"),
    (dict(period="062025", original_period="012026"), "a month the raw strings call earlier"),
])
def test_table_4_1_refuses_the_same_things(db, over, what):
    r = _t41(db, **over)
    assert r.returncode != 0 and "violates" in r.stderr, (what, r.stderr or "stored")
    assert _scalar(db, f"SELECT count(*) FROM {T41};") == "0", what


@pytest.mark.parametrize("original,statement", [("122025", "012026"), ("062025", "012026"), ("012026", "022026"), ("042026", "062026")])
def test_an_earlier_original_month_is_stored_across_the_year_end_too(db, original, statement):
    assert _t4(db, original_period=original, period=statement).returncode == 0
    assert _t41(db, original_period=original, period=statement).returncode == 0


def test_one_live_row_per_amended_row_per_statement_and_a_missing_place_of_supply_is_a_value_of_the_key(db):
    assert _t4(db).returncode == 0
    dup = _t4(db, supplier_gstin=OTHER)                               # the revised supplier is not part of the key
    assert dup.returncode != 0 and "uq_ecommerce_operator_supply_amendment" in dup.stderr, dup.stderr or "stored"
    # another original supplier, another original month, another statement month, another operator registration, another client: other rows
    assert _t4(db, original_supplier_gstin=OTHER).returncode == 0
    assert _t4(db, original_period="052026").returncode == 0
    assert _t4(db, period="072026").returncode == 0
    assert _t4(db, gstin="29AABCU9603R1ZJ").returncode == 0
    assert _t4(db, client_id=str(uuid.uuid4())).returncode == 0
    # the original place of supply is part of the key from FY 2025-26; before it the field is NULL and NULL is a value of the key
    assert _t4(db, original_place_of_supply="07").returncode == 0
    assert _t4(db, original_period="022025", period="062025", original_place_of_supply=None, place_of_supply=None).returncode == 0
    again = _t4(db, original_period="022025", period="062025", original_place_of_supply=None, place_of_supply=None)
    assert again.returncode != 0 and "uq_ecommerce_operator_supply_amendment" in again.stderr, "NULL must not be a wildcard"


def test_a_withdrawn_row_frees_its_key(db):
    assert _t4(db).returncode == 0 and _t41(db).returncode == 0
    assert _run(db, f"UPDATE {T4} SET deleted_at = now(); UPDATE {T41} SET deleted_at = now();").returncode == 0
    assert _t4(db).returncode == 0 and _t41(db).returncode == 0
    assert _scalar(db, f"SELECT count(*) FROM {T4} WHERE deleted_at IS NULL;") == "1"


def test_table_4_1_has_one_live_row_per_original_enrolment_id_per_statement(db):
    assert _t41(db).returncode == 0
    dup = _t41(db, enrolment_id="E-9")                               # the revised Enrolment ID is not part of the key
    assert dup.returncode != 0 and "uq_ecommerce_operator_unregistered_supply_amendment" in dup.stderr, dup.stderr or "stored"
    assert _t41(db, original_enrolment_id="E-2").returncode == 0
    assert _t41(db, original_period="052026").returncode == 0


def test_no_signed_in_role_holds_any_privilege_and_the_api_holds_all_four(db):
    for table in (T4, T41):
        for role in ("anon", "authenticated"):
            for verb in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                assert _scalar(db, f"SELECT has_table_privilege('{role}', 'public.{table}', '{verb}');") == "f", (table, role, verb)
            assert _scalar(db, f"SELECT has_any_column_privilege('{role}', 'public.{table}', 'SELECT');") == "f", (table, role)
        for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert _scalar(db, f"SELECT has_table_privilege('service_role', 'public.{table}', '{verb}');") == "t", (table, verb)


def test_row_security_is_on_with_the_three_policies_of_the_newest_client_tables(db):
    for table, short in ((T4, "eo_amendments"), (T41, "eo_unreg_amendments")):
        assert _scalar(db, f"SELECT relrowsecurity::text FROM pg_class WHERE oid = 'public.{table}'::regclass;") == "true"
        names = _scalar(db, f"SELECT string_agg(policyname, ',' ORDER BY policyname) FROM pg_policies WHERE tablename = '{table}';")
        assert names == f"{short}_assignment_scope,{short}_firm_isolation,{short}_internal_partner_only", names
        assert all(len(n) <= 63 for n in names.split(",")), "a policy name is cut at 63 characters"
        kinds = _scalar(db, f"SELECT string_agg(permissive, ',' ORDER BY policyname) FROM pg_policies WHERE tablename = '{table}';")
        assert kinds == "RESTRICTIVE,PERMISSIVE,RESTRICTIVE", kinds


def test_both_row_guards_are_installed_and_refuse_a_client_of_another_firm(db):
    """`guard_client_firm` (migration 565) refuses a row naming a client of another firm: the same statement, with no triggers set aside."""
    other_firm, stranger = str(uuid.uuid4()), str(uuid.uuid4())
    r = _run(db, f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f617@test.in'), ('{other_firm}', 'G', 'g617@test.in');"
                 f"INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}', '{FIRM}', 'C', 'Private Limited'), "
                 f"('{stranger}', '{other_firm}', 'S', 'Private Limited');")
    assert r.returncode == 0, r.stderr

    def insert(client: str) -> subprocess.CompletedProcess:
        return _run(db, f"INSERT INTO {T4} (firm_id, client_id, gstin, period, original_period, original_supplier_gstin, supplier_gstin, action) "
                        f"VALUES ('{FIRM}', '{client}', '{OPERATOR}', '062026', '042026', '{SELLER}', '{SELLER}', 'add');")
    assert insert(CLIENT).returncode == 0, "the control: a client of its own firm is stored"
    refused = insert(stranger)
    assert refused.returncode != 0, "a row naming a client of another firm must be refused"


def test_the_rollback_drops_both_tables_and_the_file_can_be_applied_again(db):
    def present() -> str:
        return _scalar(db, f"SELECT count(*) FROM pg_class WHERE relname IN ('{T4}', '{T41}') AND relkind = 'r';")
    assert present() == "2"
    assert _file(db, FILE).returncode == 0 and present() == "2", "applying the file twice must change nothing"
    assert _file(db, ROLLBACK).returncode == 0 and present() == "0"
    assert _file(db, FILE).returncode == 0 and present() == "2"
