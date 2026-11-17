"""Migration 640 - the payroll ledger accounts carry a key, on real Postgres (POST-A-083).

A key goes on an account only where exactly one active firm-level account matches the pattern the posting already uses and
no client-level one does; anything less certain stays unkeyed and is found by its name as before. The salary TDS account
loses migration 092's `tds_payable`. One payroll key per firm and scope.

Runs only when HARNESS_PG is set + psql on PATH, like every other *_pg test.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import uuid

import pytest

from domain.payroll import ledger_accounts as L
from services.coa_seed_service import STANDARD_COA

_ADMIN = os.environ.get("HARNESS_PG")
pytestmark = pytest.mark.skipif(not _ADMIN or not shutil.which("psql"), reason="needs HARNESS_PG and psql on PATH")

_MIG = pathlib.Path(__file__).resolve().parents[1] / "migrations"
_FORWARD = _MIG / "640_payroll_ledger_accounts_carry_a_key.sql"
_ROLLBACK = _MIG / "640_payroll_ledger_accounts_carry_a_key_rollback.sql"

STANDARD = "64000000-0000-0000-0000-000000000001"     # the standard chart, with 092's key on both TDS accounts
TWO_PF = "64000000-0000-0000-0000-000000000002"       # "PF Payable" and "EPF Payable": not certain, so not keyed
CLIENT_PF = "64000000-0000-0000-0000-000000000003"    # a client-level PF account beside the firm's: not keyed
INACTIVE = "64000000-0000-0000-0000-000000000004"     # the only match is inactive: not keyed
CLIENT = "64000000-0000-0000-0000-0000000000c3"
FIRMS = (STANDARD, TWO_PF, CLIENT_PF, INACTIVE)


def _psql(dsn, sql):
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _rows(dsn, sql):
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line for line in r.stdout.strip().splitlines() if line]


def _account(firm, code, name, *, atype="Liability", sub="Current Liability", client=None, active=True, key=None):
    return ("INSERT INTO chart_of_accounts (firm_id, client_id, account_code, account_name, account_type, account_subtype, "
            f"is_active, system_account_key) VALUES ('{firm}', {repr(client) if client else 'NULL'}, '{code}', "
            f"'{name}', '{atype}', '{sub}', {'TRUE' if active else 'FALSE'}, {repr(key) if key else 'NULL'});")


def _apply(dsn, path):
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"c5_pl640_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        # The template was built with 640 applied; begin from before it.
        _apply(dsn, _ROLLBACK)
        firms = ", ".join(f"('{f}', 'Firm {i}', 'f{i}@t.in')" for i, f in enumerate(FIRMS))
        standard = "\n".join(
            _account(STANDARD, code, name.replace("'", "''"), atype=atype, sub=sub,
                     key=("tds_payable" if name.startswith("TDS Payable") else None))
            for code, name, atype, sub in STANDARD_COA)
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES {firms};
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}', '{CLIENT_PF}', 'C', 'Proprietorship');
            {standard}
            {_account(TWO_PF, '2005', 'PF Payable')}
            {_account(TWO_PF, '2015', 'EPF Payable')}
            {_account(TWO_PF, '2006', 'ESI Payable')}
            {_account(CLIENT_PF, '2005', 'PF Payable')}
            {_account(CLIENT_PF, '2055', 'PF Payable - Unit 2', client=CLIENT)}
            {_account(INACTIVE, '2006', 'ESI Payable', active=False)}
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _keys(dsn, firm):
    return dict(r.split("|") for r in _rows(dsn, f"""SELECT account_name || '|' || coalesce(system_account_key, '-')
                                                     FROM chart_of_accounts WHERE firm_id = '{firm}'"""))


def test_the_standard_chart_gets_every_payroll_key_and_the_salary_tds_loses_092s(db):
    _apply(db, _FORWARD)
    keys = _keys(db, STANDARD)
    assert {ledger.name: keys[ledger.name] for ledger in L.ALL} == {ledger.name: ledger.key for ledger in L.ALL}
    assert keys["TDS Payable"] == "tds_payable"


def test_an_uncertain_answer_is_left_to_the_name_as_before(db):
    _apply(db, _FORWARD)
    two = _keys(db, TWO_PF)
    assert two["PF Payable"] == "-" and two["EPF Payable"] == "-"
    assert two["ESI Payable"] == L.ESI_PAYABLE.key
    assert set(_keys(db, CLIENT_PF).values()) == {"-"}
    assert _keys(db, INACTIVE) == {"ESI Payable": "-"}


def test_it_is_safe_to_run_twice_and_one_key_per_firm_and_scope_is_enforced(db):
    _apply(db, _FORWARD)
    before = _keys(db, STANDARD)
    _apply(db, _FORWARD)
    assert _keys(db, STANDARD) == before
    dup = _psql(db, _account(STANDARD, "2099", "Second PF", key=L.PF_PAYABLE.key))
    assert dup.returncode != 0 and "uq_chart_of_accounts_payroll_key" in dup.stderr
    ok = _psql(db, _account(CLIENT_PF, "2098", "PF Dues - client", client=CLIENT, key=L.PF_PAYABLE.key))
    assert ok.returncode == 0, ok.stderr


def test_the_rollback_takes_the_payroll_keys_off(db):
    _apply(db, _FORWARD)
    _apply(db, _ROLLBACK)
    assert not any(v.startswith("payroll_") for v in _keys(db, STANDARD).values())
