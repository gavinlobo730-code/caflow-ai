"""
A computation snapshot records the regime the assessee is actually taxed under.

WHAT WAS WRONG
    `tax_computation_snapshots.regime` was CHECKed to ('new', 'old') — the two
    answers to s.115BAC, an individual/HUF election. The engine answers
    'normal' / '115BAA' / '115BAB' for a domestic company and nothing for a
    firm or LLP, which the screen fills with 'firm' / 'llp'. So EVERY company,
    firm and LLP snapshot failed the CHECK; the router turned it into
    HTTPException(500, str(e)) with the constraint name in it, and the screen
    reported success over a snapshot that was never written.

WHAT IS ASSERTED
    * the request model's vocabulary is EXACTLY migration 427's CHECK — read
      out of the SQL, so the two cannot drift;
    * every one of the seven saves, through the real handler;
    * a value outside them is a 422-shaped ValidationError, never a 500;
    * a database refusal comes back as a sentence with a 4xx, and an unknown
      failure as a 500 that does not carry the exception's own text.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import domain.income_tax.computation_workspace as cw
from routers import itr_workspace as iw

MIGRATION = (Path(__file__).resolve().parents[1] / "migrations"
             / "427_a_snapshot_records_the_regime_an_entity_is_actually_taxed_under.sql")

CALLER = {"firm_id": "F-snap", "id": "u1", "auth_user_id": "a1",
          "email": "ca@f.test", "role": "Partner"}


def _req(**over):
    base = {"client_id": "C-snap", "financial_year": "2025-26",
            "assessment_year": "2026-27", "regime": "normal"}
    base.update(over)
    return iw.SnapshotRequest(**base)


class _PgError(Exception):
    """The shape supabase-py raises: one dict arg carrying code and message."""
    def __init__(self, code: str, message: str):
        super().__init__({"code": code, "message": message})


def test_the_request_speaks_exactly_the_migrations_vocabulary():
    sql = MIGRATION.read_text(encoding="utf-8")
    # The header quotes the OLD two-value CHECK in prose, so read the one the
    # statement actually adds.
    added = sql.split("ADD CONSTRAINT tax_computation_snapshots_regime_check", 1)[-1]
    check = re.search(r"CHECK\s*\(\s*regime\s+IN\s*\(([^)]*)\)\s*\)", added)
    assert check, "migration 427 no longer declares the regime CHECK"
    in_sql = {v.strip().strip("'") for v in check.group(1).split(",")}
    assert in_sql == set(get_args(iw.SnapshotRegime)) == {
        "new", "old", "normal", "115BAA", "115BAB", "firm", "llp"}


def test_the_migration_replaces_the_named_constraint_and_validates_it():
    """Named, so the guard fixture's in-flight exclusion recognises it and the
    old two-value CHECK cannot survive beside it under another name."""
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "DROP CONSTRAINT IF EXISTS tax_computation_snapshots_regime_check" in sql
    assert "ADD CONSTRAINT tax_computation_snapshots_regime_check" in sql
    assert "VALIDATE CONSTRAINT tax_computation_snapshots_regime_check" in sql


@pytest.mark.parametrize("regime", list(get_args(iw.SnapshotRegime)))
def test_every_regime_an_assessee_can_be_taxed_under_saves(regime):
    res = iw.create_snapshot(_req(regime=regime), CALLER)
    assert res["success"] is True
    assert res["data"]["regime"] == regime
    saved = cw.list_snapshots(CALLER["firm_id"], "C-snap", "2025-26")
    assert any(s["id"] == res["data"]["id"] and s["regime"] == regime for s in saved)


@pytest.mark.parametrize("bad", ["company", "", "NEW", "domestic_company"])
def test_a_regime_outside_the_seven_is_refused_by_the_model(bad):
    """Pydantic's refusal is FastAPI's 422, naming the field — not a 500 with
    a constraint name from the database."""
    with pytest.raises(ValidationError) as e:
        _req(regime=bad)
    assert "regime" in str(e.value)


def test_a_check_the_database_refuses_is_a_sentence_and_a_4xx(monkeypatch):
    def refuse(**_):
        raise _PgError("23514", 'new row for relation "tax_computation_snapshots" '
                                'violates check constraint "some_check"')
    monkeypatch.setattr(cw, "save_computation_snapshot", refuse)
    with pytest.raises(HTTPException) as e:
        iw.create_snapshot(_req(), CALLER)
    assert e.value.status_code == 400
    assert "not allowed" in e.value.detail
    assert "{'code'" not in e.value.detail, "the payload's dict repr reached the CA"


def test_two_saves_at_once_say_to_save_again(monkeypatch):
    def collide(**_):
        raise _PgError("23505", 'duplicate key value violates unique constraint '
                                '"tax_computation_snapshots_firm_id_client_id_financial_year__key"')
    monkeypatch.setattr(cw, "save_computation_snapshot", collide)
    with pytest.raises(HTTPException) as e:
        iw.create_snapshot(_req(), CALLER)
    assert e.value.status_code == 409
    assert "Save again" in e.value.detail
    assert "_key" not in e.value.detail, "the index name reached the CA"


def test_an_unknown_failure_does_not_hand_its_own_text_to_the_ca(monkeypatch):
    def explode(**_):
        raise RuntimeError("connection pool exhausted at 10.0.0.7:6543")
    monkeypatch.setattr(cw, "save_computation_snapshot", explode)
    with pytest.raises(HTTPException) as e:
        iw.create_snapshot(_req(), CALLER)
    assert e.value.status_code == 500
    assert "10.0.0.7" not in e.value.detail
    assert "computation snapshot" in e.value.detail
