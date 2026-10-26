"""The service that files a declaration, run against the REAL `file_it_declaration` in a real database (POST-A-340, migration 548).

`test_548_..._pg.py` proves the function; `test_the_declaration_filing_service_speaks_the_function_it_calls.py` proves the service's
payload and its mapping of refusals against doubles. This is the join: the service's own arguments, as the API sends them, through
the function as the service role, with the answer and the refusals the service would turn into words. It also proves the
function is not callable on a signed-in session, so a door that handed it the wrong client is a failure the caller sees as one.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from services import it_declaration_service as svc
from tests._signed_in_postgrest import SignedInDb, SignedInError

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the declaration-service proof requires HARNESS_PG + psql",
)

FIRM = "54801000-0000-0000-0000-000000000001"
CLIENT = "54801000-0000-0000-0000-0000000000a1"
EMPLOYEE = "54801000-0000-0000-0000-0000000000e1"
CA_AUTH = "54801000-1111-0000-0000-00000000000a"
FY = "2026-27"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e548s_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        seed = _psql(d, f"""
            INSERT INTO auth.users (id, email) VALUES ('{CA_AUTH}', 'ca@t.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}', '{FIRM}', 'A', 'Proprietorship');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                VALUES ('54801000-0000-0000-0000-00000000000a', '{FIRM}', '{CA_AUTH}', 'ca@t.in', 'ca', 'Partner', true);
            INSERT INTO payroll_employees (id, firm_id, client_id, name) VALUES ('{EMPLOYEE}', '{FIRM}', '{CLIENT}', 'E');
        """)
        assert seed.returncode == 0, seed.stderr
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _file(db, *, refuse_verified: bool, items=None, **over):
    args = dict(firm_id=FIRM, client_id=CLIENT, employee_id=EMPLOYEE, fy=FY, regime="old", rent_paid_declared_paise=120000,
                landlord_name="L", landlord_address="A", landlord_pan="ABCDE1234F", rent_is_metro=True, lta_declared_paise=5000,
                home_loan_interest_declared_paise=70000, lender_name="B", lender_pan="ABCDE1234G", other_income_declared_paise=100,
                house_property_loss_declared_paise=200,
                items=items if items is not None else [{"section": "80C", "label": "PPF", "amount_declared_paise": 150000,
                                                        "proof_reference": "r-1", "proof_attachments": [{"name": "a.pdf"}]}],
                refuse_verified=refuse_verified)
    args.update(over)
    return svc.file_declaration(db, **args)


def test_the_service_files_through_the_real_function_and_returns_the_id(dsn):
    db = SignedInDb(dsn, role="service_role")
    declaration_id = _file(db, refuse_verified=True)
    assert [r[0] for r in _rows(dsn, f"SELECT id FROM payroll_it_declarations WHERE employee_id = '{EMPLOYEE}'")] == [declaration_id]
    assert _rows(dsn, f"SELECT section, amount_declared_paise, label, proof_reference, proof_attachments::text "
                      f"FROM payroll_it_declaration_items WHERE declaration_id = '{declaration_id}'") == [
        ["80C", "150000", "PPF", "r-1", '[{"name": "a.pdf"}]']]
    # EVERY header column, each with its own value: the service's argument under the wrong key, a flag negated or a figure dropped is a
    # different row here, and the mock-mode tests of the payload cannot see what the database stored.
    assert _rows(dsn, "SELECT firm_id, client_id, employee_id, fy, regime, rent_paid_declared_paise, landlord_name, landlord_address, "
                      "landlord_pan, rent_is_metro, lta_declared_paise, home_loan_interest_declared_paise, lender_name, lender_pan, "
                      "other_income_declared_paise, house_property_loss_declared_paise "
                      f"FROM payroll_it_declarations WHERE id = '{declaration_id}'") == [
        [FIRM, CLIENT, EMPLOYEE, FY, "old", "120000", "L", "A", "ABCDE1234F", "t", "5000", "70000", "B", "ABCDE1234G", "100", "200"]]


def test_a_second_filing_is_the_same_declaration_with_the_lines_replaced(dsn):
    db = SignedInDb(dsn, role="service_role")
    first = _file(db, refuse_verified=True)
    second = _file(db, refuse_verified=True, items=[{"section": "80D", "label": "", "amount_declared_paise": 2, "proof_reference": "",
                                                    "proof_attachments": []}], regime="new")
    assert first == second
    assert _rows(dsn, f"SELECT section FROM payroll_it_declaration_items WHERE declaration_id = '{first}'") == [["80D"]]
    assert _rows(dsn, f"SELECT regime FROM payroll_it_declarations WHERE id = '{first}'") == [["new"]]


def test_a_verified_declaration_is_refused_to_the_employees_door_and_replaced_by_the_staff_door(dsn):
    db = SignedInDb(dsn, role="service_role")
    declaration_id = _file(db, refuse_verified=True)
    assert _psql(dsn, f"UPDATE payroll_it_declarations SET proofs_verified = true, rent_paid_verified_paise = 777 "
                      f"WHERE id = '{declaration_id}'").returncode == 0
    with pytest.raises(svc.DeclarationVerified):
        _file(db, refuse_verified=True, regime="new")
    assert _rows(dsn, f"SELECT regime, proofs_verified, rent_paid_verified_paise FROM payroll_it_declarations "
                      f"WHERE id = '{declaration_id}'") == [["old", "t", "777"]], "the refusal changed nothing"
    assert _file(db, refuse_verified=False, regime="new") == declaration_id
    assert _rows(dsn, f"SELECT regime, proofs_verified, rent_paid_verified_paise FROM payroll_it_declarations "
                      f"WHERE id = '{declaration_id}'") == [["new", "f", "0"]], "the staff door replaces it and resets the verdict"


def test_a_signed_in_session_cannot_call_the_function_and_the_refusal_is_not_taken_for_a_missing_employee(dsn):
    db = SignedInDb(dsn, role="authenticated", auth_user_id=CA_AUTH)
    with pytest.raises(SignedInError) as e:
        _file(db, refuse_verified=True)
    assert "permission denied" in e.value.message, e.value.message
    assert not isinstance(e.value, (svc.DeclarationOutOfScope, svc.DeclarationBusy, svc.DeclarationVerified))
