"""Migration 578 — the bank queue's draft-source check admits the challan, and nothing else about the queue changes (POST-A-272).

WHAT THIS HOLDS (real Postgres)
    * A bank line can carry a draft whose source is `challan` (graded proposed), and the entry-state trigger, which reads the grade and not
      the source, calls it `proposed`: the Python twin is unchanged and still agrees.
    * All five sources the code proposes (`domain/banking/entry.SOURCES`) are admitted and a sixth is refused; a source without a grade is
      refused as before (the pair check).
    * The CLOSING CHECK catches a check that lost the new word, alone, after the spoiling it is there to catch.
    * THE ROLLBACK clears the drafts whose source is `challan` (they are proposals; nothing was posted by one), restores the four-word check
      and leaves every other draft alone; a re-apply admits the word again and is idempotent.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from domain.banking import entry as E

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the draft-source proof requires HARNESS_PG + psql",
)

FIRM = "57800000-0000-0000-0000-000000000001"
CLIENT = "57800000-0000-0000-0000-0000000000a1"
ACCT = "57800000-0000-0000-0000-0000000000a5"
STMT = "57800000-0000-0000-0000-0000000000c1"
CHALLAN = "57800000-0000-0000-0000-0000000000d1"
MIGRATION = next(p for p in MIGRATIONS.glob("578_the_bank_queue_may_propose_that_a_debit_is_the_payment_of_a_recorded_tds_challan*.sql")
                 if not p.name.endswith("_rollback.sql"))
ROLLBACK = next(MIGRATIONS.glob("578_the_bank_queue_may_propose_that_a_debit_is_the_payment_of_a_recorded_tds_challan*_rollback.sql"))


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-1", "-f", str(path)], capture_output=True, text=True)


def _scalar(dsn: str, sql: str) -> str:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"e578_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}', '{FIRM}', 'C', 'Proprietorship');
            INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type)
                VALUES ('{ACCT}', '{FIRM}', '{CLIENT}', '2310', 'TDS Payable', 'Liability');
            INSERT INTO bank_statements (id, firm_id, client_id, bank_name, statement_from, statement_to)
                VALUES ('{STMT}', '{FIRM}', '{CLIENT}', 'HDFC', '2026-04-01', '2026-04-30');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _line(dsn: str, source: str | None, grade: str | None = "proposed", **extra) -> tuple[bool, str, str]:
    tid = str(uuid.uuid4())
    cols = {"id": tid, "statement_id": STMT, "firm_id": FIRM, "client_id": CLIENT, "transaction_date": "2026-04-15",
            "description": "BY CLG TDS", "debit_paise": 500000, "draft_source": source, "draft_grade": grade, **extra}
    names = ", ".join(cols)
    values = ", ".join("NULL" if v is None else "'" + str(v).replace("'", "''") + "'" for v in cols.values())
    r = _psql(dsn, f"INSERT INTO bank_transactions ({names}) VALUES ({values});")
    return r.returncode == 0, tid, r.stderr


def _source(dsn: str, tid: str) -> str:
    return _scalar(dsn, f"SELECT coalesce(draft_source, '-') FROM bank_transactions WHERE id = '{tid}'")


def _check_def(dsn: str) -> str:
    return _scalar(dsn, "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'public.bank_transactions'::regclass "
                        "AND conname = 'bank_transactions_draft_source_check'")


def test_a_challan_draft_is_admitted_and_the_trigger_calls_it_proposed(db):
    ok, tid, err = _line(db, "challan", draft_account_id=ACCT, draft_entity_type="tds_challan", draft_entity_id=CHALLAN,
                         draft_label="TDS challan 0123", draft_reason="exactly the total of TDS challan 0123")
    assert ok, err
    assert _scalar(db, f"SELECT entry_state FROM bank_transactions WHERE id = '{tid}'") == "proposed"
    assert E.entry_state({"draft_grade": "proposed", "draft_source": "challan"}) == "proposed"


@pytest.mark.parametrize("source", list(E.SOURCES))
def test_every_source_the_code_proposes_is_admitted(db, source):
    ok, _tid, err = _line(db, source)
    assert ok, (source, err)


def test_a_sixth_source_and_a_source_without_a_grade_are_refused(db):
    ok, _t, err = _line(db, "bogus")
    assert not ok and "bank_transactions_draft_source_check" in err
    ok, _t, err = _line(db, "challan", grade=None)
    assert not ok and "bank_transactions_draft_pair_check" in err


def test_the_check_names_exactly_the_five_sources(db):
    d = _check_def(db)
    for word in E.SOURCES:
        assert f"'{word}'" in d, (word, d)


def test_the_closing_check_catches_a_check_that_lost_the_new_word(db):
    sql = MIGRATION.read_text(encoding="utf-8")
    closing = sql[sql.rindex("DO $$"):]
    assert _psql(db, closing).returncode == 0
    assert _psql(db, "ALTER TABLE bank_transactions DROP CONSTRAINT bank_transactions_draft_source_check; "
                     "ALTER TABLE bank_transactions ADD CONSTRAINT bank_transactions_draft_source_check "
                     "CHECK (draft_source IS NULL OR draft_source IN ('rule','document','history','transfer'));").returncode == 0
    r = _psql(db, closing)
    assert r.returncode != 0 and "migration 578" in r.stderr


def test_the_rollback_clears_challan_drafts_restores_the_four_word_check_and_leaves_other_drafts_alone(db):
    ok, challan_line, err = _line(db, "challan", draft_account_id=ACCT, draft_entity_type="tds_challan", draft_entity_id=CHALLAN,
                                  draft_label="x", draft_reason="y", drafted_at="2026-04-15T00:00:00Z")
    assert ok, err
    ok, rule_line, err = _line(db, "rule", draft_label="Bank charges", draft_reason="Rule")
    assert ok, err
    r = _psql_file(db, ROLLBACK)
    assert r.returncode == 0, r.stderr
    assert _source(db, challan_line) == "-"
    assert _scalar(db, f"SELECT concat_ws('|', draft_grade, draft_label, draft_account_id, draft_entity_type, draft_entity_id, drafted_at) "
                       f"FROM bank_transactions WHERE id = '{challan_line}'") == ""
    assert _source(db, rule_line) == "rule"
    assert "'challan'" not in _check_def(db)
    ok, _t, err = _line(db, "challan")
    assert not ok and "bank_transactions_draft_source_check" in err
    # the line cleared is back in the stale pile for a redraft, and its state follows the trigger
    assert _scalar(db, f"SELECT entry_state FROM bank_transactions WHERE id = '{challan_line}'") == "needs_you"


def test_a_reapply_admits_the_word_again_and_the_migration_is_idempotent(db):
    assert _psql_file(db, ROLLBACK).returncode == 0
    assert _psql_file(db, MIGRATION).returncode == 0
    ok, _t, err = _line(db, "challan")
    assert ok, err
    assert _psql_file(db, MIGRATION).returncode == 0, "applying it twice must not fail"
