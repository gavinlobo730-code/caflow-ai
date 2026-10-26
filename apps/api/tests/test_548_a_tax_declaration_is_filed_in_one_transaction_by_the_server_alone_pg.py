"""A tax declaration is filed in one transaction, by the server alone (migration 548, POST-A-340).

WHAT THIS IS FOR
    The employee's door (`PUT /api/portal/employee/tax-declaration`) and the staff door (`PUT /api/payroll/declarations`) each wrote an
    employee's Form 12BB declaration as several separate requests: header, then the new lines, then the removal of the old ones.
    Two filings by one employee at the same instant could leave the header of one beside the lines of the other, and a failure
    part-way needed a put-back (the employee door) or left a half-written declaration (the staff door). Migration 548 is one function,
    `file_it_declaration(p_declaration, p_items, p_refuse_verified)`, that does all of it in one transaction under a row lock.

WHAT THIS HOLDS (real Postgres)
    * A FIRST FILING creates the header (submitted, every verified column zero or false) and its lines and returns the declaration's id.
    * A RE-FILING REPLACES: same declaration id, the lines are exactly the new ones (a withdrawn line is gone), the declared figures are
      the new ones, and a header the CA had verified is RESET (verified columns, `proofs_verified`, `verified_at`, `verified_by`).
    * THE EMPLOYEE'S DOOR REFUSES A VERIFIED DECLARATION (`p_refuse_verified`): `declaration_verified:` and nothing changes; the
      staff door (false) replaces it, as it always has.
    * A SCOPE THAT IS NOT THE EMPLOYEE'S WRITES NOTHING: an employee of another firm or another client, a missing key, lines that are
      not an array.
    * ONE TRANSACTION: a line the database refuses (a section that is null, an amount that is not a number, a negative amount) rolls
      the whole call back, so the header and the old lines are exactly what they were.
    * TWO FILINGS AT ONCE ARE ONE AFTER THE OTHER: a second caller waits for the first's lock, then files over it; the final header and
      lines are the second filing's, never a mixture (a re-filing and a first filing).
    * THE SHAPE: SECURITY INVOKER, closed to anon and authenticated, open to the service role; the closing check fails when each claim is
      spoiled; the rollback drops it and a re-apply brings it back; applying twice changes nothing.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the declaration-filing proof requires HARNESS_PG + psql",
)

FIRM = "54800000-0000-0000-0000-000000000001"
OTHER_FIRM = "54800000-0000-0000-0000-000000000002"
CLIENT = "54800000-0000-0000-0000-0000000000a1"
OTHER_CLIENT = "54800000-0000-0000-0000-0000000000a2"
EMPLOYEE = "54800000-0000-0000-0000-0000000000e1"
OTHER_FIRM_EMPLOYEE = "54800000-0000-0000-0000-0000000000e2"
OTHER_CLIENT_EMPLOYEE = "54800000-0000-0000-0000-0000000000e3"
CA = "54800000-0000-0000-0000-00000000000a"
FY = "2026-27"
FN = "public.file_it_declaration(jsonb, jsonb, boolean)"
MIGRATION = next(p for p in MIGRATIONS.glob("548_a_tax_declaration_is_filed_in_one_transaction*.sql") if not p.name.endswith("_rollback.sql"))
ROLLBACK = next(MIGRATIONS.glob("548_a_tax_declaration_is_filed_in_one_transaction*_rollback.sql"))


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-1", "-f", str(path)], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


def _one(dsn: str, sql: str) -> str:
    return _rows(dsn, sql)[0][0]


def _text(dsn: str, sql: str) -> str:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.rstrip("\n")


def _j(x) -> str:
    return json.dumps(x).replace("'", "''")


def _decl(**over) -> dict:
    body = {"firm_id": FIRM, "client_id": CLIENT, "employee_id": EMPLOYEE, "fy": FY, "regime": "old",
            "rent_paid_declared_paise": 120000, "landlord_name": "L", "landlord_address": "A", "landlord_pan": "ABCDE1234F",
            "rent_is_metro": True, "lta_declared_paise": 5000, "home_loan_interest_declared_paise": 70000,
            "lender_name": "B", "lender_pan": "ABCDE1234G", "other_income_declared_paise": 100, "house_property_loss_declared_paise": 200}
    body.update(over)
    return body


def _items(*pairs) -> list[dict]:
    return [{"section": s, "label": f"{s} label", "amount_declared_paise": a, "proof_reference": f"ref-{s}",
             "proof_attachments": [{"name": f"{s}.pdf"}]} for s, a in pairs]


def _file(dsn: str, declaration: dict, items, refuse: bool = False, role: str = "service_role") -> tuple[bool, str]:
    sql = f"SET ROLE {role}; SELECT public.file_it_declaration('{_j(declaration)}'::jsonb, '{_j(items)}'::jsonb, {str(refuse).lower()});"
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql], capture_output=True, text=True)
    if r.returncode != 0:
        m = re.search(r"ERROR:\s+(.*)", r.stderr)
        return False, (m.group(1) if m else r.stderr).strip()
    out = [l for l in r.stdout.splitlines() if l.strip() and l.strip() != "SET"]
    return True, (out[-1].strip() if out else "")


def _header(dsn: str, employee: str = EMPLOYEE) -> dict:
    cols = ("id", "regime", "status", "rent_paid_declared_paise", "rent_paid_verified_paise", "lta_declared_paise", "lta_verified_paise",
            "home_loan_interest_declared_paise", "home_loan_interest_verified_paise", "landlord_pan", "proofs_verified",
            "coalesce(verified_at::text, '-')", "coalesce(verified_by::text, '-')", "other_income_declared_paise")
    rows = _rows(dsn, f"SELECT {', '.join(cols)} FROM payroll_it_declarations WHERE employee_id = '{employee}' AND fy = '{FY}'")
    assert len(rows) <= 1, rows
    if not rows:
        return {}
    names = ("id", "regime", "status", "rent", "rent_v", "lta", "lta_v", "loan", "loan_v", "landlord_pan", "verified", "verified_at",
             "verified_by", "other")
    return dict(zip(names, rows[0]))


def _lines(dsn: str, declaration_id: str) -> list[tuple]:
    return [tuple(r) for r in _rows(dsn, "SELECT section, amount_declared_paise, amount_verified_paise, status, label, proof_reference, "
                                         "proof_attachments::text FROM payroll_it_declaration_items "
                                         f"WHERE declaration_id = '{declaration_id}' ORDER BY section")]


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e548_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        seed = _psql(d, f"""
            INSERT INTO auth.users (id, email) VALUES ('54800000-1111-0000-0000-00000000000a', 'ca@t.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in'), ('{OTHER_FIRM}', 'G', 'g@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
                ('{CLIENT}', '{FIRM}', 'A', 'Proprietorship'), ('{OTHER_CLIENT}', '{FIRM}', 'B', 'Proprietorship'),
                ('54800000-0000-0000-0000-0000000000b1', '{OTHER_FIRM}', 'C', 'Proprietorship');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                VALUES ('{CA}', '{FIRM}', '54800000-1111-0000-0000-00000000000a', 'ca@t.in', 'ca', 'Partner', true);
            INSERT INTO payroll_employees (id, firm_id, client_id, name) VALUES
                ('{EMPLOYEE}', '{FIRM}', '{CLIENT}', 'E'), ('{OTHER_CLIENT_EMPLOYEE}', '{FIRM}', '{OTHER_CLIENT}', 'E3'),
                ('{OTHER_FIRM_EMPLOYEE}', '{OTHER_FIRM}', '54800000-0000-0000-0000-0000000000b1', 'E2');
        """)
        assert seed.returncode == 0, seed.stderr
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── a first filing and a re-filing ───────────────────────────────────────────────────────────────────────────────────
def test_a_first_filing_creates_the_header_and_its_lines_and_returns_the_id(dsn):
    ok, out = _file(dsn, _decl(), _items(("80C", 150000), ("80D", 25000)))
    assert ok, out
    h = _header(dsn)
    assert h["id"] == out and h["status"] == "submitted" and h["regime"] == "old" and h["verified"] == "f"
    assert (h["rent"], h["rent_v"], h["lta"], h["lta_v"], h["loan"], h["loan_v"], h["other"]) == ("120000", "0", "5000", "0", "70000", "0", "100")
    assert h["verified_at"] == "-" and h["verified_by"] == "-"
    assert _lines(dsn, out) == [("80C", "150000", "0", "declared", "80C label", "ref-80C", '[{"name": "80C.pdf"}]'),
                                ("80D", "25000", "0", "declared", "80D label", "ref-80D", '[{"name": "80D.pdf"}]')]


def test_a_refiling_replaces_the_lines_wholesale_and_keeps_the_declaration(dsn):
    ok, first = _file(dsn, _decl(), _items(("80C", 150000), ("80D", 25000)))
    assert ok, first
    ok, second = _file(dsn, _decl(regime="new", rent_paid_declared_paise=0, lta_declared_paise=0), _items(("80C", 90000), ("80CCD2", 5000)))
    assert ok and second == first, (first, second)
    h = _header(dsn)
    assert h["regime"] == "new" and h["rent"] == "0" and h["lta"] == "0"
    assert [(l[0], l[1]) for l in _lines(dsn, first)] == [("80C", "90000"), ("80CCD2", "5000")], "the withdrawn 80D line must be gone"
    assert _one(dsn, "SELECT count(*) FROM payroll_it_declaration_items") == "2"


def test_a_filing_with_no_lines_clears_them(dsn):
    ok, first = _file(dsn, _decl(), _items(("80C", 150000)))
    assert ok, first
    ok, again = _file(dsn, _decl(), [])
    assert ok and again == first
    assert _lines(dsn, first) == []


def test_a_refiling_resets_what_the_ca_had_verified(dsn):
    ok, first = _file(dsn, _decl(), _items(("80C", 150000)))
    assert ok, first
    assert _psql(dsn, f"""UPDATE payroll_it_declarations SET proofs_verified = true, status = 'verified', rent_paid_verified_paise = 100000,
                          lta_verified_paise = 1000, home_loan_interest_verified_paise = 5000, verified_at = now(), verified_by = '{CA}'
                          WHERE id = '{first}';
                          UPDATE payroll_it_declaration_items SET amount_verified_paise = 100000, status = 'verified' WHERE declaration_id = '{first}';""").returncode == 0
    ok, second = _file(dsn, _decl(), _items(("80C", 200000)), refuse=False)      # the staff door
    assert ok and second == first, second
    h = _header(dsn)
    assert (h["verified"], h["status"], h["rent_v"], h["lta_v"], h["loan_v"], h["verified_at"], h["verified_by"]) == ("f", "submitted", "0", "0", "0", "-", "-")
    assert _lines(dsn, first)[0][1:4] == ("200000", "0", "declared"), "the line's verdict is reset with the claim"


# ── the employee's door refuses a verified declaration ───────────────────────────────────────────────────────────────
def test_the_employees_door_refuses_a_verified_declaration_and_changes_nothing(dsn):
    ok, first = _file(dsn, _decl(), _items(("80C", 150000)), refuse=True)
    assert ok, first                                      # unverified: allowed, and the flag does nothing
    assert _psql(dsn, f"UPDATE payroll_it_declarations SET proofs_verified = true, status = 'verified', verified_at = now(), verified_by = '{CA}' WHERE id = '{first}'").returncode == 0
    before_header, before_lines = _header(dsn), _lines(dsn, first)
    ok, out = _file(dsn, _decl(regime="new"), _items(("80C", 1)), refuse=True)
    assert not ok and out.startswith("declaration_verified:"), out
    assert _header(dsn) == before_header and _lines(dsn, first) == before_lines


# ── a scope that is not the employee's writes nothing ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("label,declaration", [
    ("an employee of another firm", _decl(employee_id=OTHER_FIRM_EMPLOYEE)),
    ("an employee of another client of the firm", _decl(employee_id=OTHER_CLIENT_EMPLOYEE)),
    ("an employee nobody has", _decl(employee_id="54800000-0000-0000-0000-0000000000ee")),
    ("the firm of another employee", _decl(firm_id=OTHER_FIRM)),
])
def test_a_scope_that_is_not_the_employees_is_refused_and_writes_nothing(dsn, label, declaration):
    ok, out = _file(dsn, declaration, _items(("80C", 1)))
    assert not ok and "is not an employee of client" in out, (label, out)
    assert _one(dsn, "SELECT count(*) FROM payroll_it_declarations") == "0" and _one(dsn, "SELECT count(*) FROM payroll_it_declaration_items") == "0"


@pytest.mark.parametrize("missing", ["firm_id", "client_id", "employee_id", "fy"])
def test_a_declaration_that_names_no_firm_client_employee_or_year_is_refused(dsn, missing):
    d = _decl()
    d.pop(missing)
    ok, out = _file(dsn, d, [])
    assert not ok and "names its firm, client, employee and year" in out, out


def test_lines_that_are_not_an_array_are_refused(dsn):
    ok, out = _file(dsn, _decl(), {"section": "80C"})
    assert not ok and "must be a JSON array" in out, out


# ── one transaction ──────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("label,bad_line", [
    ("a null section", {"section": None, "amount_declared_paise": 1}),
    ("an amount that is not a number", {"section": "80C", "amount_declared_paise": "lots"}),
    ("a negative amount", {"section": "80C", "amount_declared_paise": -5}),
    ("too many attachments", {"section": "80C", "amount_declared_paise": 1, "proof_attachments": [{}] * 21}),
])
def test_a_line_the_database_refuses_rolls_the_whole_call_back(dsn, label, bad_line):
    ok, first = _file(dsn, _decl(), _items(("80C", 150000), ("80D", 25000)))
    assert ok, first
    before_header, before_lines = _header(dsn), _lines(dsn, first)
    ok, out = _file(dsn, _decl(regime="new", rent_paid_declared_paise=999), [{"section": "80G", "amount_declared_paise": 7}, bad_line])
    assert not ok, (label, out)
    assert _header(dsn) == before_header and _lines(dsn, first) == before_lines, label


def test_a_first_filing_whose_line_is_refused_leaves_no_declaration_behind(dsn):
    ok, out = _file(dsn, _decl(), [{"section": None, "amount_declared_paise": 1}])
    assert not ok, out
    assert _one(dsn, "SELECT count(*) FROM payroll_it_declarations") == "0"


# ── two filings at once ──────────────────────────────────────────────────────────────────────────────────────────────
def _session(dsn: str, declaration: dict, items, hold_seconds: float, refuse: bool = False) -> subprocess.Popen:
    sql = (f"BEGIN; SET LOCAL ROLE service_role; SELECT public.file_it_declaration('{_j(declaration)}'::jsonb, '{_j(items)}'::jsonb, {str(refuse).lower()}); "
           f"SELECT pg_sleep({hold_seconds}); COMMIT;")
    return subprocess.Popen(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_two_refilings_at_once_run_one_after_the_other_and_never_mix(dsn):
    ok, first = _file(dsn, _decl(), _items(("80C", 1)))
    assert ok, first
    a = _session(dsn, _decl(regime="old", rent_paid_declared_paise=111), _items(("80C", 111), ("80D", 111)), hold_seconds=1.5)
    time.sleep(0.4)
    started = time.time()
    b = _session(dsn, _decl(regime="new", rent_paid_declared_paise=222), _items(("80CCD2", 222)), hold_seconds=0)
    b_out, b_err = b.communicate(timeout=60)
    waited = time.time() - started
    a_out, a_err = a.communicate(timeout=60)
    assert a.returncode == 0 and b.returncode == 0, (a_err, b_err)
    assert waited >= 0.9, f"the second filing did not wait for the first's lock (waited {waited:.2f}s)"
    h = _header(dsn)
    assert (h["regime"], h["rent"]) == ("new", "222"), h
    assert [(l[0], l[1]) for l in _lines(dsn, first)] == [("80CCD2", "222")], "the lines are the second filing's alone"


def test_two_first_filings_at_once_make_one_declaration_with_the_second_ones_lines(dsn):
    a = _session(dsn, _decl(rent_paid_declared_paise=111), _items(("80C", 111)), hold_seconds=1.5)
    time.sleep(0.4)
    b = _session(dsn, _decl(rent_paid_declared_paise=222), _items(("80D", 222)), hold_seconds=0)
    b_out, b_err = b.communicate(timeout=60)
    a_out, a_err = a.communicate(timeout=60)
    assert a.returncode == 0 and b.returncode == 0, (a_err, b_err)
    assert _one(dsn, "SELECT count(*) FROM payroll_it_declarations") == "1"
    h = _header(dsn)
    assert h["rent"] == "222" and [(l[0], l[1]) for l in _lines(dsn, h["id"])] == [("80D", "222")], h


def test_a_filing_that_waits_for_a_verification_is_refused_by_it(dsn):
    """The CA's verification and the employee's filing at the same instant: whichever gets the lock first wins, and a filing that
    waits behind a verification sees `proofs_verified` and is refused instead of overwriting it."""
    ok, first = _file(dsn, _decl(), _items(("80C", 1)))
    assert ok, first
    verifier = subprocess.Popen(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c",
         f"BEGIN; SELECT 1 FROM payroll_it_declarations WHERE id = '{first}' FOR UPDATE; "
         f"UPDATE payroll_it_declarations SET proofs_verified = true, status = 'verified', verified_at = now(), verified_by = '{CA}' WHERE id = '{first}'; "
         "SELECT pg_sleep(1.5); COMMIT;"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(0.4)
    ok, out = _file(dsn, _decl(regime="new"), _items(("80C", 99)), refuse=True)
    verifier.communicate(timeout=60)
    assert not ok and out.startswith("declaration_verified:"), out
    assert _header(dsn)["verified"] == "t" and _header(dsn)["regime"] == "old"


# ── the shape ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _acl(dsn: str) -> dict[str, bool]:
    return {r: _one(dsn, f"SELECT has_function_privilege('{r}', '{FN}'::regprocedure, 'EXECUTE')") == "t" for r in ("anon", "authenticated", "service_role")}


def test_the_function_is_invoker_closed_to_the_signed_in_and_open_to_the_service_role(dsn):
    assert _one(dsn, f"SELECT prosecdef FROM pg_proc WHERE oid = '{FN}'::regprocedure") == "f"
    assert _acl(dsn) == {"anon": False, "authenticated": False, "service_role": True}
    for role in ("authenticated", "anon"):
        ok, msg = _file(dsn, _decl(), _items(("80C", 1)), role=role)
        assert not ok and "permission denied" in msg, (role, msg)
    assert _one(dsn, "SELECT count(*) FROM payroll_it_declarations") == "0"


def test_the_function_stays_closed_even_where_the_platform_grants_new_functions_to_the_signed_in(dsn):
    assert _psql(dsn, "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon, authenticated;").returncode == 0
    assert _psql(dsn, f"DROP FUNCTION {FN};").returncode == 0
    done = _psql_file(dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    assert _acl(dsn) == {"anon": False, "authenticated": False, "service_role": True}


def _closing_block() -> str:
    text = MIGRATION.read_text()
    return text[text.rindex("DO $$"):]


SPOILS = [
    ("executable by a signed-in user", f"GRANT EXECUTE ON FUNCTION {FN} TO authenticated;"),
    ("executable by anon", f"GRANT EXECUTE ON FUNCTION {FN} TO anon;"),
    ("closed to the service role", f"REVOKE EXECUTE ON FUNCTION {FN} FROM service_role;"),
    ("a definer", f"ALTER FUNCTION {FN} SECURITY DEFINER;"),
]


@pytest.mark.parametrize("label,spoil", SPOILS, ids=[s[0] for s in SPOILS])
def test_the_closing_check_fails_when_what_it_checks_is_spoiled(dsn, label, spoil):
    assert _psql(dsn, _closing_block()).returncode == 0, "the closing check should pass on the migrated database"
    assert _psql(dsn, spoil).returncode == 0, label
    r = _psql(dsn, _closing_block())
    assert r.returncode != 0 and "migration 548" in r.stderr, (label, r.stderr)


def test_the_rollback_drops_it_and_a_reapply_brings_it_back_and_applying_twice_changes_nothing(dsn):
    before = _text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{FN}'::regprocedure")
    assert _psql_file(dsn, ROLLBACK).returncode == 0
    assert _one(dsn, "SELECT count(*) FROM pg_proc WHERE proname = 'file_it_declaration'") == "0"
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert _text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{FN}'::regprocedure") == before
    ok, out = _file(dsn, _decl(), _items(("80C", 1)))
    assert ok, out


def test_the_function_writes_every_column_the_two_doors_wrote(dsn):
    """The header columns the doors' payloads named, so a column added to those payloads without the function is seen here."""
    src = _text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{FN}'::regprocedure")
    cols = [r[0] for r in _rows(dsn, "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' "
                                     "AND table_name = 'payroll_it_declarations' ORDER BY ordinal_position")]
    not_filed_by_the_function = {"id", "created_at", "rejected_reason"}
    for c in cols:
        if c in not_filed_by_the_function:
            continue
        assert re.search(rf"\b{c}\b", src), f"the function never writes payroll_it_declarations.{c}"
