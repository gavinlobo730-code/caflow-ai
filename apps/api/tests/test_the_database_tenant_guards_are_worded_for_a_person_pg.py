"""The sentence a person gets for a tenant guard is built from what the LIVE triggers send, not from a copy of their text (POST-A-353).

`test_the_database_tenant_guards_are_worded_for_a_person.py` reads the migration files. This fires five of the guards in a database the
whole migration set built and hands the SQLSTATE and message Postgres really sent to the same wording function, so a guard whose text
or error code the migration text does not show (a function redefined by a later migration, a code set in a `USING` clause the scan
reads differently) cannot slip past it. The five are the ones a signed-in person can reach with a stale pick list: a client, a customer,
a supplier, a member and a ledger account of another client or firm. The journal-line, cost-centre and ledger-entry guards are covered
by the migration text only (their tables need a posted entry to fire).

Each case also asserts the RAW message is the log-style one (it names the other client's id), which is the control: the sentence is
different because the wording function changed it, and a database whose guards were already plain would pass vacuously.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from core.exceptions import tenant_guard_sentence, unhandled_failure

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

F = "58000000-0000-0000-0000-00000000000f"
G = "58000000-0000-0000-0000-000000000009"
C_F = "58000000-0000-0000-0000-0000000000f1"
C_G = "58000000-0000-0000-0000-0000000000a1"
C_G2 = "58000000-0000-0000-0000-0000000000a2"
CUST_G2 = "58000000-0000-0000-0000-0000000000c2"
VEND_G2 = "58000000-0000-0000-0000-0000000000d2"
ACCT_G2 = "58000000-0000-0000-0000-0000000000b2"
MEMBER_F = "58000000-0000-0000-0000-0000000000e1"
MEMBER_G = "58000000-0000-0000-0000-0000000000e2"

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the live-trigger proof requires HARNESS_PG + psql",
)


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-f", "-"],
                          input=sql, capture_output=True, text=True)


class Refusal(Exception):
    """Shaped like supabase-py's APIError for the code and message Postgres sent."""

    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__({"code": code, "message": message})


def _refusal(dsn: str, sql: str) -> Refusal:
    """Run one statement that must be refused and return the SQLSTATE and message the database sent (VERBOSITY verbose prints both)."""
    r = _psql(dsn, "\\set VERBOSITY verbose\n" + sql)
    assert r.returncode != 0, "the statement was accepted: the guard did not fire"
    m = re.search(r"ERROR:\s+(\w{5}):\s+(.*)", r.stderr)
    assert m, r.stderr
    return Refusal(m.group(1), m.group(2).strip())


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m353_{uuid.uuid4().hex[:10]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        for stem in ("565_a_row_names_a_client_of_its_own_firm_and_a_party_of_its_own_client",
                     "566_a_row_names_a_member_of_its_own_firm", "570_a_row_names_a_ledger_account_of_its_own_client"):
            assert f"{stem}.sql" not in pg_template.failed, f"migration {stem[:3]} did not apply, so everything below would pass vacuously"
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{F}', 'M353 F', 'f@m353.test'), ('{G}', 'M353 G', 'g@m353.test');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES
                ('{MEMBER_F}', '{F}', NULL, 'f1@m353.test', 'F1', 'Manager', true),
                ('{MEMBER_G}', '{G}', NULL, 'g1@m353.test', 'G1', 'Manager', true);
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
                ('{C_F}', '{F}', 'CF', 'Private Limited'), ('{C_G}', '{G}', 'CG', 'Private Limited'), ('{C_G2}', '{G}', 'CG2', 'Private Limited');
            INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{CUST_G2}', '{G}', '{C_G2}', 'cust G2');
            INSERT INTO vendors (id, firm_id, client_id, name) VALUES ('{VEND_G2}', '{G}', '{C_G2}', 'vend G2');
            INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type)
                VALUES ('{ACCT_G2}', '{G}', '{C_G2}', '1002', 'G2 cash', 'Asset');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


CASES = {
    "client": (f"INSERT INTO public.proposals (firm_id, client_id, proposal_no, title) VALUES ('{G}', '{C_F}', 'P1', 't');",
               "42501", "That client was not found.", C_F),
    "customer": (f"INSERT INTO public.receipts (firm_id, client_id, customer_id, receipt_no, receipt_date) "
                 f"VALUES ('{G}', '{C_G}', '{CUST_G2}', 'R1', DATE '2026-04-01');",
                 "42501", "That customer was not found.", CUST_G2),
    "vendor": (f"INSERT INTO public.purchase_orders (firm_id, client_id, vendor_id, document_no, document_date) "
               f"VALUES ('{G}', '{C_G}', '{VEND_G2}', 'PO1', DATE '2026-04-01');",
               "42501", "That vendor was not found.", VEND_G2),
    "member": (f"INSERT INTO public.godowns (firm_id, client_id, name, created_by) VALUES ('{G}', '{C_G}', 'g1', '{MEMBER_F}');",
               "42501", "That team member was not found.", MEMBER_F),
    "ledger account": (f"INSERT INTO public.bank_accounts (firm_id, client_id, bank_name, account_no, coa_account_id) "
                       f"VALUES ('{G}', '{C_G}', 'B', '1', '{ACCT_G2}');",
                       "P0001", "That ledger account was not found.", ACCT_G2),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_live_guard_is_worded_from_what_postgres_really_sent(db, name):
    sql, state, sentence, stranger = CASES[name]
    raised = _refusal(db, sql)
    assert raised.code == state, f"{name}: the guard raised {raised.code}, the wording table expects {state}"
    assert "another" in raised.message and stranger in raised.message, (
        f"{name}: the raw message is not the log-style one this test is about: {raised.message!r}")
    assert tenant_guard_sentence(raised) == sentence
    assert unhandled_failure(raised) == (404, sentence)
    assert stranger not in sentence
