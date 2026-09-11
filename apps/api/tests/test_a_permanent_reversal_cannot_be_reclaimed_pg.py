"""
Migration 362 — the register holds permanent reversals, and never releases one.

WHY THIS NEEDS A REAL DATABASE
    Two of the three things this migration does exist only in Postgres:

      * `reclaimable` is a GENERATED column. Whether credit can ever come back
        is a property of the GROUND — Rule 37 credit returns when the supplier
        is paid (Rule 37(4)), §17(5)(h) credit never returns — so it is derived
        from `reason_code` rather than set. A boolean anybody could set is a
        boolean that can disagree with the reason beside it, and the
        disagreement would show up as credit re-availed on a return where the
        Act forbids it. Only Postgres can prove it cannot be set.
      * the reclaim guard is a TRIGGER. `record_reclaim` refuses one too, but
        the register is written by a service that could grow a second caller,
        and a CHECK cannot express the rule because it needs the parent row.

    The widened `reason_code` CHECK is the third, and a double can only prove
    the service was called.
"""
from __future__ import annotations

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
    reason="register guard proof requires HARNESS_PG + psql",
)

FIRM = "f3620000-0000-0000-0000-000000000001"
CLIENT = "c3620000-0000-0000-0000-000000000001"
ACC = "a3620000-0000-0000-0000-000000000001"
JE = "e3620000-0000-0000-0000-000000000001"
JE2 = "e3620000-0000-0000-0000-000000000002"
JE3 = "e3620000-0000-0000-0000-000000000003"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _scalar(dsn: str, sql: str) -> str:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e362_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        seed = _psql(d, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f362@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
            VALUES ('{CLIENT}', '{FIRM}', 'C', 'Proprietorship');
            INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code,
                                           account_name, account_type)
            VALUES ('{ACC}', '{FIRM}', '{CLIENT}', '1710', 'GST Input Tax Credit', 'Asset');
            INSERT INTO journal_entries (id, firm_id, client_id, entry_date, reference_no,
                                         narration, entry_type, is_posted, status) VALUES
              ('{JE}',  '{FIRM}', '{CLIENT}', '2026-06-15', 'REV-1', 'n', 'Journal', true, 'posted'),
              ('{JE2}', '{FIRM}', '{CLIENT}', '2026-09-15', 'RCL-1', 'n', 'Journal', true, 'posted'),
              ('{JE3}', '{FIRM}', '{CLIENT}', '2026-06-20', 'REV-2', 'n', 'Journal', true, 'posted');
        """)
        assert seed.returncode == 0, seed.stderr
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _reversal(dsn_: str, reason: str, rid: str, journal: str = JE) -> subprocess.CompletedProcess:
    """`journal` is a parameter because one journal may be registered ONCE —
    a unique index says so, and the service says so, for the same reason:
    declaring one posting twice would double the reversal on the return."""
    return _psql(dsn_, f"""
        INSERT INTO itc_reversal_register
            (id, firm_id, client_id, journal_entry_id, kind, reason_code, period,
             cgst_paise, sgst_paise)
        VALUES ('{rid}', '{FIRM}', '{CLIENT}', '{journal}', 'reversal', '{reason}',
                '062026', 4500, 4500);
    """)


# ── the widened ground list ──────────────────────────────────────────────────

@pytest.mark.parametrize("reason", ["section_17_5_h", "section_17_5_other",
                                    "rule_38", "rule_42", "rule_43"])
def test_a_permanent_ground_is_now_accepted(dsn, reason):
    """Before 362 the CHECK listed only reclaimable grounds, so a §17(5)(h)
    stock write-off had nowhere to be declared and the prepared return claimed
    credit the books had already given back."""
    r = _reversal(dsn, reason, str(uuid.uuid4()))
    assert r.returncode == 0, r.stderr


def test_a_ground_that_is_not_statutory_is_still_refused(dsn):
    r = _reversal(dsn, "because_i_said_so", str(uuid.uuid4()))
    assert r.returncode != 0
    assert "reason_code" in r.stderr


# ── the generated column ─────────────────────────────────────────────────────

@pytest.mark.parametrize("reason,expected", [
    ("rule_37", "t"), ("rule_37a", "t"), ("section_16_2b", "t"),
    ("section_16_2c", "t"), ("other", "t"),
    ("section_17_5_h", "f"), ("rule_38", "f"), ("rule_42", "f"), ("rule_43", "f"),
])
def test_reclaimable_follows_the_ground(dsn, reason, expected):
    rid = str(uuid.uuid4())
    assert _reversal(dsn, reason, rid).returncode == 0
    assert _scalar(dsn, f"SELECT reclaimable FROM itc_reversal_register WHERE id='{rid}'") == expected


def test_reclaimable_cannot_be_set_by_hand(dsn):
    """The whole reason it is generated. A boolean somebody could set is a
    boolean that can disagree with the reason beside it, and that disagreement
    reads as credit re-availed where the Act forbids it."""
    rid = str(uuid.uuid4())
    r = _psql(dsn, f"""
        INSERT INTO itc_reversal_register
            (id, firm_id, client_id, journal_entry_id, kind, reason_code, period,
             cgst_paise, reclaimable)
        VALUES ('{rid}', '{FIRM}', '{CLIENT}', '{JE}', 'reversal',
                'section_17_5_h', '062026', 4500, true);
    """)
    assert r.returncode != 0
    assert "generated" in r.stderr.lower() or "cannot insert" in r.stderr.lower()


# ── the trigger ──────────────────────────────────────────────────────────────

def _reclaim(dsn_: str, reverses_id: str) -> subprocess.CompletedProcess:
    return _psql(dsn_, f"""
        INSERT INTO itc_reversal_register
            (firm_id, client_id, journal_entry_id, kind, reason_code, period,
             cgst_paise, sgst_paise, reverses_id)
        VALUES ('{FIRM}', '{CLIENT}', '{JE2}', 'reclaim', 'other', '092026',
                4500, 4500, '{reverses_id}');
    """)


def test_a_reclaimable_reversal_can_be_released(dsn):
    """Guard: the trigger must bite on the permanent case, not on everything.
    Rule 37(4) is exactly what 4(D)(1) exists for."""
    rid = str(uuid.uuid4())
    assert _reversal(dsn, "rule_37", rid).returncode == 0
    r = _reclaim(dsn, rid)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("reason", ["section_17_5_h", "rule_42", "rule_43"])
def test_a_permanent_reversal_cannot_be_released(dsn, reason):
    """Re-availing a §17(5) reversal claims credit the Act denies outright.
    Enforced on the TABLE, not only in the service, because the register is
    written by a service that could grow a second caller."""
    rid = str(uuid.uuid4())
    assert _reversal(dsn, reason, rid).returncode == 0

    r = _reclaim(dsn, rid)

    assert r.returncode != 0
    assert "permanent" in r.stderr
    assert reason in r.stderr


def test_the_guard_is_on_the_table_and_not_on_the_caller(dsn):
    """Run as `postgres`, which owns the schema and bypasses RLS. Still refused
    — the same argument migration 360 makes for journal lines."""
    rid = str(uuid.uuid4())
    assert _reversal(dsn, "section_17_5_h", rid).returncode == 0
    r = _psql(dsn, "SET LOCAL ROLE postgres; " + f"""
        INSERT INTO itc_reversal_register
            (firm_id, client_id, journal_entry_id, kind, reason_code, period,
             cgst_paise, reverses_id)
        VALUES ('{FIRM}', '{CLIENT}', '{JE2}', 'reclaim', 'other', '092026',
                4500, '{rid}');
    """)
    assert r.returncode != 0
    assert "permanent" in r.stderr


def test_an_update_cannot_repoint_a_reclaim_at_a_permanent_reversal(dsn):
    """The trigger is BEFORE INSERT OR UPDATE. Without the UPDATE arm the rule
    would be: point the reclaim at a Rule 37 reversal, then move it."""
    ok, bad = str(uuid.uuid4()), str(uuid.uuid4())
    assert _reversal(dsn, "rule_37", ok).returncode == 0
    assert _reversal(dsn, "section_17_5_h", bad, journal=JE3).returncode == 0
    assert _reclaim(dsn, ok).returncode == 0

    r = _psql(dsn, f"UPDATE itc_reversal_register SET reverses_id='{bad}' "
                   f"WHERE kind='reclaim';")

    assert r.returncode != 0
    assert "permanent" in r.stderr
