"""Migration 651 on a real database: a lot recorded on FORM GST ITC-04 can be retracted (ledger POST-A-418).

HELD HERE: the retraction keeps the row, the day, the person and a reason (a blank reason is refused by the function and by a CHECK);
a retracted lot no longer counts against the room a line has left, so the goods can be recorded again; a challan that the lots had
marked received back goes back to issued with no back day when the live lots no longer bring every line back (a challan marked back by
the whole-challan door, with no lot, is left as it is); a challan whose every lot is retracted can be cancelled and one with a live lot
still cannot; a retraction is final (written once, the row not changed after); a lot of another challan or client, or one already
retracted, is not found; the function is closed to anon/authenticated; two retractions at once act once; the migration is idempotent
and its rollback refuses while a lot is retracted, then restores 585's functions. Negative control: after the rollback the retraction
function is gone and a challan with a lot cannot be cancelled, as before.

Runs only when HARNESS_PG is set + psql on PATH.
"""
from __future__ import annotations

import pathlib
import subprocess
import uuid

import pytest

from tests.test_585_a_delivery_challan_is_written_in_one_transaction_and_says_when_it_was_issued_pg import (  # noqa: F401
    CLIENT, FIRM, LOT, OTHER_CLIENT, _ADMIN, _answer, _call, _challan, _lot, _lot_call, _psql, _rows, _run_file, db,
)

pytestmark = pytest.mark.skipif(not _ADMIN, reason="needs HARNESS_PG")

_M = pathlib.Path(__file__).resolve().parent.parent / "migrations"
_UP = next(_M.glob("651_a_lot_recorded_on_itc_04_can_be_retracted.sql"))
_DOWN = next(_M.glob("651_a_lot_recorded_on_itc_04_can_be_retracted_rollback.sql"))
RETRACT = "public.retract_challan_lot_atomic"
USER = str(uuid.uuid4())


def _retract(dsn, cid, lot_id, reason="recorded on the wrong challan", client=CLIENT):
    return _call(dsn, f"SELECT {RETRACT}('{FIRM}', '{client}', '{cid}', '{lot_id}', '{reason}', '{USER}');")


def _record(dsn, cid, lid, **kw) -> str:
    done = _lot_call(dsn, cid, _lot(lid, **kw))
    out = _answer(done)
    return out["lot"]["id"]


def _status(dsn, cid):
    return _rows(dsn, f"SELECT status || '|' || coalesce(received_back_on::text, '') FROM delivery_challans WHERE id = '{cid}';")[0]


def test_a_retraction_keeps_the_row_the_day_the_person_and_the_reason(db):
    cid, (lid,) = _challan(db)
    lot = _record(db, cid, lid, back="4")
    done = _retract(db, cid, lot)
    assert done.returncode == 0, done.stderr
    row = _rows(db, f"SELECT retracted_at IS NOT NULL, retracted_by = '{USER}', retraction_reason, quantity_returned FROM delivery_challan_returns WHERE id = '{lot}';")
    assert row == ["t|t|recorded on the wrong challan|4.000"]


def test_a_blank_reason_is_refused_by_the_function_and_the_table(db):
    cid, (lid,) = _challan(db)
    lot = _record(db, cid, lid)
    assert "retraction_needs_reason" in _retract(db, cid, lot, reason="   ").stderr
    bad = _psql(db, f"UPDATE delivery_challan_returns SET retracted_at = now(), retraction_reason = ' ' WHERE id = '{lot}';")
    assert bad.returncode != 0 and "retraction_says_why" in bad.stderr


def test_a_retracted_lot_gives_its_room_back(db):
    cid, (lid,) = _challan(db, quantity=10)
    lot = _record(db, cid, lid, back="8")
    assert "lot_exceeds_line" in _lot_call(db, cid, _lot(lid, back="5")).stderr
    assert _retract(db, cid, lot).returncode == 0
    assert _lot_call(db, cid, _lot(lid, back="10")).returncode == 0


def test_a_challan_the_lots_marked_back_goes_back_to_issued_and_one_marked_by_hand_does_not(db):
    cid, (lid,) = _challan(db, quantity=10)
    lot = _record(db, cid, lid, back="10")
    assert _status(db, cid).startswith("received_back|2026-08-20")
    assert _retract(db, cid, lot).returncode == 0
    assert _status(db, cid) == "issued|"
    hand, _ = _challan(db, no="JW/2", status="received_back")
    _psql(db, f"UPDATE delivery_challans SET received_back_on = DATE '2026-09-01' WHERE id = '{hand}';")
    other, (ol,) = _challan(db, no="JW/3", quantity=5)
    spare = _record(db, other, ol, back="2")
    assert _retract(db, hand, spare).returncode != 0          # a lot of another challan is not found
    assert _status(db, hand).startswith("received_back|2026-09-01")


def test_a_challan_with_every_lot_retracted_can_be_cancelled_and_one_with_a_live_lot_cannot(db):
    cid, (lid,) = _challan(db)
    first, second = _record(db, cid, lid, back="2"), _record(db, cid, lid, back="3")
    assert "challan_has_lots" in _psql(db, f"UPDATE delivery_challans SET status = 'cancelled' WHERE id = '{cid}';").stderr
    assert _retract(db, cid, first).returncode == 0
    assert "challan_has_lots" in _psql(db, f"UPDATE delivery_challans SET status = 'cancelled' WHERE id = '{cid}';").stderr
    assert _retract(db, cid, second).returncode == 0
    assert _psql(db, f"UPDATE delivery_challans SET status = 'cancelled' WHERE id = '{cid}';").returncode == 0


def test_a_retraction_is_final_and_not_repeated_and_names_only_its_own_challans_lot(db):
    cid, (lid,) = _challan(db)
    lot = _record(db, cid, lid)
    assert _retract(db, cid, lot).returncode == 0
    again = _retract(db, cid, lot)
    assert again.returncode != 0 and "lot_not_found" in again.stderr
    edit = _psql(db, f"UPDATE delivery_challan_returns SET notes = 'x' WHERE id = '{lot}';")
    assert edit.returncode != 0 and "retracted lot is not changed" in edit.stderr
    other, (ol,) = _challan(db, no="JW/9")
    assert "lot_not_found" in _retract(db, other, _record(db, cid, lid, back="1"), reason="x").stderr
    assert "challan_not_found" in _retract(db, cid, lot, client=OTHER_CLIENT).stderr


def test_the_record_function_cannot_write_the_retraction_columns_through_a_lot(db):
    cid, (lid,) = _challan(db)
    done = _lot_call(db, cid, _lot(lid, retracted_at="2026-08-21", retraction_reason="x"))
    assert done.returncode == 0, done.stderr
    assert _rows(db, f"SELECT count(*) FROM delivery_challan_returns WHERE challan_id = '{cid}' AND retracted_at IS NULL;") == ["1"]


def test_the_function_is_closed_to_signed_in_roles(db):
    fn = f"{RETRACT}(uuid, uuid, uuid, uuid, text, uuid)"
    for role in ("anon", "authenticated", "public"):
        assert _rows(db, f"SELECT has_function_privilege('{role}', '{fn}', 'EXECUTE');") == ["f"]
    assert _rows(db, f"SELECT has_function_privilege('service_role', '{fn}', 'EXECUTE');") == ["t"]


def test_the_migration_is_idempotent_and_its_rollback_is_refused_while_a_lot_is_retracted_then_restores_585(db):
    assert _run_file(db, _UP).returncode == 0
    cid, (lid,) = _challan(db)
    lot = _record(db, cid, lid)
    assert _retract(db, cid, lot).returncode == 0
    refused = _run_file(db, _DOWN)
    assert refused.returncode != 0 and "retracted lots exist" in refused.stderr
    _psql(db, "ALTER TABLE delivery_challan_returns DISABLE TRIGGER trg_delivery_challan_returns_retraction_is_final;")
    _psql(db, f"DELETE FROM delivery_challan_returns WHERE id = '{lot}';")
    assert _run_file(db, _DOWN).returncode == 0
    assert _run_file(db, _DOWN).returncode == 0
    assert _rows(db, "SELECT count(*) FROM pg_proc WHERE proname = 'retract_challan_lot_atomic';") == ["0"]
    # NEGATIVE CONTROL / 585 restored: the lot function works again without the columns, and a challan with a lot is not cancelled.
    other, (ol,) = _challan(db, no="JW/5")
    assert _lot_call(db, other, _lot(ol, back="1")).returncode == 0
    assert "challan_has_lots" in _psql(db, f"UPDATE delivery_challans SET status = 'cancelled' WHERE id = '{other}';").stderr
