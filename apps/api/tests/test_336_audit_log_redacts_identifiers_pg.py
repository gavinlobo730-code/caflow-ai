"""
Migration 336 — the audit snapshot stops collecting a person's identifiers.

WHY THIS IS A REAL-POSTGRES TEST AND NOT A MOCK ONE

The whole mechanism is a database trigger writing into a table whose UPDATE and
DELETE are blocked by another trigger. There is no Python in the path at all, so
mock mode cannot see any of it: the redaction either happens in PostgreSQL or it
does not happen.

WHAT IS AT STAKE

audit_log is append-only by design (migration 082). Anything written there is
permanent — a DPDP erasure request cannot reach it, and neither can a fix. So a
redactor that silently fails is not a bug that gets noticed later; it is a
growing residue of identifiers nobody can remove. Measured before this
migration: 1,470 of 46,311 production rows already carried one.

THE SHAPE OF THE ASSERTIONS

Half of these are about what must NOT change. Over-redaction is the other
failure — an audit log with the identifying fields stripped out is a list of
timestamps — so the four deliberate near-misses (gstin, ifsc, bank_account_id,
esic_employer_code) are pinned as explicitly as the redactions are, and so is
the rule that the KEY survives while only the VALUE goes.
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
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="migration 336 proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000336"
CLIENT = "bbbbbbbb-0000-0000-0000-000000000336"
AUTH = "11111111-1111-1111-1111-111111111336"
REDACTED = "[redacted]"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _redact(dsn: str, payload: dict) -> dict:
    """Run one payload through public.audit_redact and read the result back."""
    literal = json.dumps(payload).replace("'", "''")
    r = _psql(dsn, f"SELECT public.audit_redact('{literal}'::jsonb);", tuples=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip())


@pytest.fixture()
def seeded(pg_template):
    admin = _ADMIN.strip()
    dbname = f"m336_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        assert "336_the_audit_log_stops_collecting_identifiers.sql" not in pg_template.failed
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{AUTH}','m336@test.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M336 Firm','m336@test.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
              VALUES ('{CLIENT}','{FIRM}','M336 Client','Private Limited');
            INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role)
              VALUES (gen_random_uuid(),'{FIRM}','{AUTH}','Staff','m336@test.in','Partner');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


# ── The redactor itself ──────────────────────────────────────────────────────

@pytest.mark.parametrize("key", [
    "pan", "deductee_pan", "deductor_pan", "landlord_pan", "lender_pan", "vendor_pan",
    "aadhaar_last4", "uan", "bank_account_no", "account_number",
    "date_of_birth", "deductee_tin", "tax_identification_number",
])
def test_every_listed_identifier_loses_its_value(seeded, key):
    got = _redact(seeded, {key: "SENSITIVE-VALUE", "id": "x"})
    assert got[key] == REDACTED, f"{key} kept its value"


@pytest.mark.parametrize("key", [
    "pan", "uan", "bank_account_no", "date_of_birth",
])
def test_the_key_survives_so_the_log_still_shows_which_field_changed(seeded, key):
    """Dropping the key would lose the fact that the field changed at all — the
    row would look identical to one where it did not. That is the whole reason
    this redacts the value rather than removing the entry."""
    got = _redact(seeded, {key: "SENSITIVE-VALUE"})
    assert key in got, f"{key} was dropped rather than redacted"


@pytest.mark.parametrize("key", [
    "gstin", "supplier_gstin",        # business registration, public, the CA's key
    "ifsc", "ifsc_code", "bank_ifsc", # a branch code identifies a branch, not a person
    "bank_account_id",                # a uuid FK, not an account number
    "esic_employer_code",             # the employer's registration, not an employee's
])
def test_the_deliberate_near_misses_are_left_alone(seeded, key):
    """Over-redaction turns an audit log into a list of timestamps. These four
    are argued in migration 336's header and are pinned here so a later widening
    of the list is a decision rather than a slip."""
    got = _redact(seeded, {key: "KEPT-VALUE"})
    assert got[key] == "KEPT-VALUE", f"{key} was redacted and should not be"


def test_names_and_contact_details_are_not_redacted(seeded):
    """A deliberate line, and the first one to revisit if the position must be
    stricter: they are personal data, but they are how a human reads an audit
    row at all."""
    got = _redact(seeded, {"name": "Asha Rao", "email": "a@b.in", "phone": "9000000000"})
    assert got == {"name": "Asha Rao", "email": "a@b.in", "phone": "9000000000"}


def test_a_null_stays_null_rather_than_becoming_a_marker(seeded):
    """"This field was empty" is information. A marker would assert something
    was there."""
    got = _redact(seeded, {"pan": None, "uan": "100000000001"})
    assert got["pan"] is None
    assert got["uan"] == REDACTED


def test_a_payload_with_no_identifiers_is_returned_unchanged(seeded):
    payload = {"id": "x", "firm_id": FIRM, "amount_paise": 12345, "note": "hello"}
    assert _redact(seeded, payload) == payload


def test_null_in_null_out(seeded):
    r = _psql(seeded, "SELECT public.audit_redact(NULL) IS NULL;", tuples=True)
    assert r.stdout.strip() == "t"


# ── The trigger path, end to end ─────────────────────────────────────────────

def _as(auth_user_id: str) -> str:
    return (f"SET request.jwt.claims = '{{\"sub\": \"{auth_user_id}\"}}'; "
            f"SET ROLE authenticated; ")


def test_a_browser_write_lands_in_audit_log_with_the_pan_redacted(seeded):
    """The end-to-end proof: the trigger fires on a real write and what reaches
    the append-only table carries no PAN."""
    cust = "cccccccc-0000-0000-0000-000000000336"
    r = _psql(seeded, _as(AUTH) + f"""
        INSERT INTO public.customers (id, firm_id, client_id, name, pan, gstin)
        VALUES ('{cust}','{FIRM}','{CLIENT}','Asha Rao','ABCDE1234F','27ABCDE1234F1Z5');
    """)
    assert r.returncode == 0, r.stderr

    got = _psql(seeded, f"""
        SELECT new_data->>'pan', new_data->>'gstin', new_data->>'name',
               new_data ? 'pan'
          FROM public.audit_log
         WHERE entity_id = '{cust}' AND action = 'create'
         LIMIT 1;
    """, tuples=True)
    assert got.returncode == 0, got.stderr
    assert got.stdout.strip(), "the audit trigger did not fire at all"
    pan, gstin, name, has_pan_key = got.stdout.strip().split("|")
    assert pan == REDACTED, "the PAN reached the append-only log"
    assert has_pan_key == "t", "the key was dropped instead of the value"
    assert gstin == "27ABCDE1234F1Z5", "the GSTIN was redacted and should not be"
    assert name == "Asha Rao", "the name was redacted and should not be"


def test_the_routing_columns_still_work_after_redaction(seeded):
    """firm_id and id are read OUT of the redacted payload. Neither is on the
    list — but if one ever were, every audited row would silently stop being
    written (a NULL firm_id returns early)."""
    cust = "cccccccc-0000-0000-0000-000000000337"
    assert _psql(seeded, _as(AUTH) + f"""
        INSERT INTO public.customers (id, firm_id, client_id, name, pan)
        VALUES ('{cust}','{FIRM}','{CLIENT}','Ravi Kumar','ABCDE1234F');
    """).returncode == 0

    got = _psql(seeded, f"""
        SELECT firm_id::text, entity_id, entity_type
          FROM public.audit_log WHERE entity_id = '{cust}' LIMIT 1;
    """, tuples=True)
    assert got.stdout.strip() == f"{FIRM}|{cust}|customer"


def test_an_update_redacts_both_sides(seeded):
    """old_data is where the PREVIOUS identifier would otherwise be preserved —
    the half that a naive fix forgets."""
    cust = "cccccccc-0000-0000-0000-000000000338"
    assert _psql(seeded, _as(AUTH) + f"""
        INSERT INTO public.customers (id, firm_id, client_id, name, pan)
        VALUES ('{cust}','{FIRM}','{CLIENT}','Meena Iyer','AAAAA1111A');
    """).returncode == 0
    assert _psql(seeded, _as(AUTH) + f"""
        UPDATE public.customers SET pan = 'BBBBB2222B' WHERE id = '{cust}';
    """).returncode == 0

    got = _psql(seeded, f"""
        SELECT old_data->>'pan', new_data->>'pan'
          FROM public.audit_log
         WHERE entity_id = '{cust}' AND action = 'update' LIMIT 1;
    """, tuples=True)
    assert got.stdout.strip() == f"{REDACTED}|{REDACTED}", (
        "an update leaked an identifier on one side")


def test_audit_log_is_still_append_only(seeded):
    """The property this migration depends on, re-proved: if UPDATE were
    allowed, redacting on write would be pointless because a later fix could
    have cleaned up instead."""
    cust = "cccccccc-0000-0000-0000-000000000339"
    assert _psql(seeded, _as(AUTH) + f"""
        INSERT INTO public.customers (id, firm_id, client_id, name, pan)
        VALUES ('{cust}','{FIRM}','{CLIENT}','Sunil Rao','AAAAA1111A');
    """).returncode == 0
    for op in ("UPDATE public.audit_log SET action = 'x'",
               "DELETE FROM public.audit_log"):
        r = _psql(seeded, f"{op} WHERE entity_id = '{cust}';")
        assert r.returncode != 0, f"{op} was permitted on audit_log"
        assert "append-only" in r.stderr
