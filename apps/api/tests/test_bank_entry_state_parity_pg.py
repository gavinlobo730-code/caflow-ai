"""
Migration 322 — the entry_state trigger must equal the Python twin, exactly.

WHY THIS FILE EXISTS
    entry_state is computed by a BEFORE trigger on a real database and by
    domain/banking/entry.py::entry_state in mock mode. Two implementations of
    one rule drift; CLAUDE.md's answer is a parity test that runs every case
    through both. The cases are test_bank_entry.STATE_TABLE — declared once,
    asserted here against Postgres, so adding a branch to one twin without
    the other fails CI rather than showing a CA a different queue locally
    than in production.

WHAT ONLY POSTGRES CAN PROVE
    * The trigger fires on INSERT and on UPDATE, and the backfill in the
      migration ran (a row inserted before the trigger existed cannot be
      tested here; the migration's no-op UPDATE covers it).
    * draft_error is CLEARED when a human's answer changes the coding —
      UPDATE-time behaviour the Python twin has no OLD row to express.
    * has_splits follows bank_transaction_splits through its trigger.
    * The three CHECKs refuse what they must: a grade without a source, a
      state outside the six, and a trusted rule without a person or a ledger.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from domain.banking import entry as E
from tests.test_bank_entry import STATE_TABLE

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="SQL/Python parity proof requires HARNESS_PG + psql",
)

FIRM = "f3220000-0000-0000-0000-000000000001"
CLIENT = "c3220000-0000-0000-0000-000000000001"
USER = "a3220000-0000-0000-0000-000000000001"
ACCT = "ac220000-0000-0000-0000-000000000001"
STMT = "53220000-0000-0000-0000-000000000001"
RULE = "23220000-0000-0000-0000-000000000001"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _scalar(dsn: str, sql: str) -> str:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"e322_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
            VALUES ('{CLIENT}', '{FIRM}', 'C', 'Proprietorship');
            INSERT INTO users (id, firm_id, full_name, email, role)
            VALUES ('{USER}', '{FIRM}', 'U', 'u@t.in', 'Manager');
            INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type)
            VALUES ('{ACCT}', '{FIRM}', '{CLIENT}', '5001', 'Bank Charges', 'Expense');
            INSERT INTO bank_statements (id, firm_id, client_id, bank_name, statement_from, statement_to)
            VALUES ('{STMT}', '{FIRM}', '{CLIENT}', 'HDFC', '2026-04-01', '2026-04-30');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    return "'" + str(v).replace("'", "''") + "'"


# The Python table uses opaque strings for ids; Postgres wants uuids. Map
# any non-null id-ish value to a fixed uuid — the trigger tests NULL-ness only.
_ID_COLS = {"account_id": ACCT, "matched_entity_id": "e3220000-0000-0000-0000-000000000001",
            "transfer_pair_id": "e3220000-0000-0000-0000-000000000002"}


def _insert(dsn: str, row: dict) -> str:
    tid = str(uuid.uuid4())
    cols = {"id": tid, "statement_id": STMT, "firm_id": FIRM, "client_id": CLIENT,
            "transaction_date": "2026-04-15", "description": "x", "debit_paise": 100}
    for k, v in row.items():
        cols[k] = _ID_COLS[k] if (k in _ID_COLS and v) else v
    if "matched_entity_id" in cols and cols["matched_entity_id"]:
        cols.setdefault("matched_entity_type", "sales_invoice")
    if "draft_grade" in cols and cols["draft_grade"] and not cols.get("draft_source"):
        cols["draft_source"] = "rule"          # the pair CHECK; the twin reads grade only
    names = ", ".join(cols)
    values = ", ".join(_lit(v) for v in cols.values())
    r = _psql(dsn, f"INSERT INTO bank_transactions ({names}) VALUES ({values});")
    assert r.returncode == 0, r.stderr
    return tid


@pytest.mark.parametrize("row,expected", STATE_TABLE)
def test_the_trigger_and_the_twin_agree_on_insert(db, row, expected):
    tid = _insert(db, row)
    assert _scalar(db, f"SELECT entry_state FROM bank_transactions WHERE id='{tid}'") == expected
    assert E.entry_state(row) == expected


def test_the_trigger_recomputes_on_every_update(db):
    tid = _insert(db, {})
    s = lambda: _scalar(db, f"SELECT entry_state FROM bank_transactions WHERE id='{tid}'")  # noqa: E731
    assert s() == E.NEEDS_YOU
    _psql(db, f"UPDATE bank_transactions SET draft_source='history', draft_grade='proposed' WHERE id='{tid}'")
    assert s() == E.PROPOSED
    _psql(db, f"UPDATE bank_transactions SET draft_grade='ready' WHERE id='{tid}'")
    assert s() == E.READY
    _psql(db, f"UPDATE bank_transactions SET match_status='ignored' WHERE id='{tid}'")
    assert s() == E.SET_ASIDE
    _psql(db, f"UPDATE bank_transactions SET match_status='posted' WHERE id='{tid}'")
    assert s() == E.PASSED


def test_a_humans_answer_clears_the_machines_complaint(db):
    tid = _insert(db, {"draft_source": "rule", "draft_grade": "ready", "draft_error": "Period locked"})
    assert _scalar(db, f"SELECT entry_state FROM bank_transactions WHERE id='{tid}'") == E.NEEDS_YOU
    r = _psql(db, f"UPDATE bank_transactions SET account_id='{ACCT}', match_status='matched' WHERE id='{tid}'")
    assert r.returncode == 0, r.stderr
    got = _scalar(db, f"SELECT entry_state || '|' || coalesce(draft_error, '') FROM bank_transactions WHERE id='{tid}'")
    assert got == f"{E.READY}|"


def test_an_unrelated_update_keeps_the_complaint(db):
    tid = _insert(db, {"draft_source": "rule", "draft_grade": "ready", "draft_error": "Period locked"})
    _psql(db, f"UPDATE bank_transactions SET description='renamed' WHERE id='{tid}'")
    assert _scalar(db, f"SELECT draft_error FROM bank_transactions WHERE id='{tid}'") == "Period locked"


def test_has_splits_follows_the_splits_table(db):
    tid = _insert(db, {})
    r = _psql(db, f"""INSERT INTO bank_transaction_splits
        (firm_id, client_id, bank_transaction_id, account_id, amount_paise)
        VALUES ('{FIRM}', '{CLIENT}', '{tid}', '{ACCT}', 100);""")
    assert r.returncode == 0, r.stderr
    assert _scalar(db, f"SELECT has_splits::text || '|' || entry_state FROM bank_transactions WHERE id='{tid}'") \
        == f"true|{E.READY}"
    _psql(db, f"DELETE FROM bank_transaction_splits WHERE bank_transaction_id='{tid}'")
    assert _scalar(db, f"SELECT has_splits::text || '|' || entry_state FROM bank_transactions WHERE id='{tid}'") \
        == f"false|{E.NEEDS_YOU}"


def test_a_grade_without_a_source_is_refused(db):
    tid = _insert(db, {})
    r = _psql(db, f"UPDATE bank_transactions SET draft_grade='ready' WHERE id='{tid}'")
    assert r.returncode != 0 and "draft_pair_check" in r.stderr


def test_application_code_cannot_write_a_state_the_trigger_will_not(db):
    tid = _insert(db, {})
    # Whatever is written, the trigger overwrites it from the row — so a
    # nonsense value never reaches the CHECK, and the row still reads right.
    r = _psql(db, f"UPDATE bank_transactions SET entry_state='whatever' WHERE id='{tid}'")
    assert r.returncode == 0, r.stderr
    assert _scalar(db, f"SELECT entry_state FROM bank_transactions WHERE id='{tid}'") == E.NEEDS_YOU


def test_a_trusted_rule_needs_a_person_and_a_ledger(db):
    r = _psql(db, f"""INSERT INTO bank_matching_rules (id, firm_id, client_id, rule_name, suggested_account_id)
                      VALUES ('{RULE}', '{FIRM}', '{CLIENT}', 'Charges', '{ACCT}');""")
    assert r.returncode == 0, r.stderr
    r = _psql(db, f"UPDATE bank_matching_rules SET is_trusted=true WHERE id='{RULE}'")
    assert r.returncode != 0 and "trusted_check" in r.stderr
    r = _psql(db, f"UPDATE bank_matching_rules SET is_trusted=true, trusted_by='{USER}', trusted_at=now() WHERE id='{RULE}'")
    assert r.returncode == 0, r.stderr
    r = _psql(db, f"UPDATE bank_matching_rules SET suggested_account_id=NULL WHERE id='{RULE}'")
    assert r.returncode != 0 and "trusted_check" in r.stderr
    r = _psql(db, f"UPDATE bank_matching_rules SET is_trusted=false, trusted_by=NULL, trusted_at=NULL WHERE id='{RULE}'")
    assert r.returncode == 0, r.stderr
