"""Two database facts the marketing site states, pinned on real PostgreSQL
(market_and_trust-09).

  * "every change to a client, invoice, bill, receipt or ledger entry is written to an
    audit log" (products, support) — and the shorter "Audit logs" / "Audit log of
    changes" on the pricing and products pages;
  * "Every rupee in integer paise — never floating point" (homepage ecosystem panel,
    products, the document-reading walk-through).

THE AUDIT SENTENCE WAS "EACH RECORD" AND THE MEASUREMENT SAYS OTHERWISE. Migration 111
attaches `trg_audit_capture` with a ONE-SHOT `DO` loop over the tables that existed that
day — the shape CLAUDE.md records for migration 084's assignment-scope policy — and nothing
re-runs it. Measured on a freshly migrated database on 2026-10-01: of 288 firm-scoped
tables, 120 carry the trigger and 168 do not, among them `client_year_locks`,
`user_permissions`, `itr_filings`, `payroll_settlements`, `debit_notes`,
`purchase_credit_notes` and `einvoice_records`. So the sentences were reworded to the
records the trigger DOES cover, and this test names exactly those — it fails if one of
them ever loses the trigger, and it says nothing about the other 168, which is the
finding recorded beside the ledger rather than quietly passed.

THE TRIGGER FIRES FOR A SIGNED-IN USER, NOT FOR THE SERVICE ROLE: `audit_capture` returns
at once when `auth.uid()` is NULL, because a service-role write is meant to be audited
in-app by `audit_service.log_event`. In production that covers the API as well, since
`USE_USER_JWT` runs requests as `authenticated`; the behavioural test below acts as a
signed-in user for that reason.

Runs only when HARNESS_PG is set + psql is on PATH, like every *_pg test.
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

# The records the sentences name, as tables: a client, an invoice, a bill, a receipt, a
# ledger entry and the payroll records. If the site names another, it is added HERE and
# the sentence and this list change in one commit.
NAMED_RECORDS = (
    "clients",
    "client_sales_invoices",
    "purchase_bills",
    "receipts",
    "journal_entries",
    "payroll_runs",
    "payroll_employees",
)

FIRM = "52000000-0000-0000-0000-0000000000f1"
CLIENT = "52000000-0000-0000-0000-0000000000c1"
ACTOR_AUTH = "52000000-0000-0000-0000-00000000a001"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line for line in r.stdout.splitlines() if line.strip()]


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m09_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{ACTOR_AUTH}', 'p@t.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── the audit sentences ──────────────────────────────────────────────────────

def test_the_records_the_site_names_carry_the_audit_trigger(db):
    carrying = set(_rows(db, """
        SELECT c.relname FROM pg_trigger g JOIN pg_class c ON c.oid = g.tgrelid
        WHERE g.tgname = 'trg_audit_capture' AND NOT g.tgisinternal
    """))
    missing = [t for t in NAMED_RECORDS if t not in carrying]
    assert not missing, (
        f"{missing} no longer carry trg_audit_capture, and the site says every change to "
        "them is written to an audit log")


def test_a_signed_in_users_write_to_a_named_record_lands_in_the_audit_log(db):
    """The trigger exists; this is the behaviour the sentence promises — who, what, and the
    new row — acting as a signed-in user (`auth.uid()` present), which is what the API is in
    production."""
    r = _psql(db, f"""
        SET request.jwt.claims = '{{"sub": "{ACTOR_AUTH}"}}';
        INSERT INTO clients (id, firm_id, client_name, entity_type, pan)
          VALUES ('{CLIENT}', '{FIRM}', 'Audited Client', 'Private Limited', 'AAACA1234A');
        UPDATE clients SET client_name = 'Audited Client Pvt Ltd' WHERE id = '{CLIENT}';
    """)
    assert r.returncode == 0, r.stderr
    actions = _rows(db, f"""
        SELECT action FROM audit_log
        WHERE firm_id = '{FIRM}' AND entity_id = '{CLIENT}' AND actor_id = '{ACTOR_AUTH}'
        ORDER BY created_at, action
    """)
    assert sorted(actions) == ["create", "update"], (
        f"a signed-in write to a client was not audited as who-did-what: {actions}")
    new_name = _rows(db, f"""
        SELECT new_data->>'client_name' FROM audit_log
        WHERE entity_id = '{CLIENT}' AND action = 'update'
    """)
    assert new_name == ["Audited Client Pvt Ltd"], "the audit row must carry the changed value"


def test_the_trigger_is_not_attached_to_every_table_and_this_says_so(db):
    """NOT a ratchet and NOT a claim: it records the measurement that made the sentences
    name their records. If the loop of migration 111 is ever re-run for every firm table,
    this fails and the 'not_proved' note on the ledger's audit claim, the marketing
    sentences' qualifier and `found_not_touched` all become reducible in one go."""
    uncovered = _rows(db, """
        SELECT t.table_name FROM information_schema.tables t
        WHERE t.table_schema = 'public' AND t.table_type = 'BASE TABLE'
          AND EXISTS (SELECT 1 FROM information_schema.columns c
                      WHERE c.table_schema = 'public' AND c.table_name = t.table_name
                        AND c.column_name = 'firm_id')
          AND NOT EXISTS (SELECT 1 FROM pg_trigger g JOIN pg_class k ON k.oid = g.tgrelid
                          WHERE k.relname = t.table_name AND g.tgname = 'trg_audit_capture'
                            AND NOT g.tgisinternal)
    """)
    assert "client_year_locks" in uncovered and "user_permissions" in uncovered, (
        "a table the audit note names as uncovered now carries the trigger — good: update "
        "the ledger's not_proved note, and this test, in the same commit")


# ── "every rupee in integer paise — never floating point" ────────────────────

def test_every_paise_column_is_an_integer_and_no_money_is_floating_point(db):
    wrong = _rows(db, r"""
        SELECT c.table_name || '.' || c.column_name || ' ' || c.data_type
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name
        WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'
          AND c.column_name LIKE '%\_paise' AND c.data_type NOT IN ('bigint', 'integer')
        ORDER BY 1
    """)
    assert not wrong, "a *_paise column is not an integer type — money in a float or a numeric:\n" + "\n".join(wrong)

    floats = _rows(db, r"""
        SELECT c.table_name || '.' || c.column_name || ' ' || c.data_type
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name
        WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'
          AND c.data_type IN ('real', 'double precision')
          AND c.column_name ~* '(amount|price|total|balance|paise|tax|fee|salary|value|cost|debit|credit|gst|tds|cess)'
        ORDER BY 1
    """)
    assert not floats, "a money-named column is floating point:\n" + "\n".join(floats)


def test_the_paise_scan_finds_the_columns_it_is_about(db):
    """A scan that matched nothing would pass for ever: there are hundreds of them, and
    the big ones are bigint."""
    n = int(_rows(db, r"""
        SELECT count(*) FROM information_schema.columns
        WHERE table_schema = 'public' AND column_name LIKE '%\_paise' AND data_type = 'bigint'
    """)[0])
    assert n > 300, f"only {n} bigint *_paise columns found — the scan no longer sees the schema"
