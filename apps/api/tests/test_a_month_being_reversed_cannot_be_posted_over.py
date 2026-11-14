"""A month of depreciation that is being reversed cannot be posted over (ledger POST-A-349, migration 587).

WHY IT EXISTS
    `reverse_depreciation` writes the register back a month first and reverses the month's journal second. A request posting the SAME
    month in between read a register without the month, was handed the still-live journal by the posting kernel's duplicate check,
    wrote the register up again, and was then reversed under: the register said posted, the ledger said reversed. A half-done reversal
    and a half-done post leave the same state, so a post cannot tell them apart on the state alone. The reversal now writes a marker
    (the month and the instant) in the same compare-and-set as its claim and takes it off when the journal is reversed or the claim is
    put back; a post refuses while the marker is within its lease, and its own register write is a compare-and-set on the marker it read.

WHAT IS HELD, through the real routes and the real posting kernel on a fake database holding the standard chart
    * the marker is on the asset while the journal is reversed, and off after; a failed reversal puts it back with the register;
    * a post of the month that lands between the claim and the journal is refused, and the ledger and the register agree afterwards;
    * a post whose register write lands after a reversal claimed the asset takes its own journal back;
    * a reversal that died: within the lease every post waits; past it a post adopts the live journal and takes the marker off (as a
      retry of a half-done post always has), and a repeated reversal of that month completes it, whether the journal was reversed
      before the death or not; another month is refused until it is completed; a completion that loses to a post is a 409;
    * the whole-year run posts past a dead marker without tripping on the marker it has just cleared;
    * a row read before the migration (no marker columns) is written exactly as before.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import routers.fixed_assets as fa
from models.accounting import DepreciationIn, DepreciationRunIn
from tests.test_an_intangible_assets_amortisation_moves_to_its_own_ledger import (
    CALLER, CLIENT, SHARED, _create, _credit, _firm, _sync_balances,
)

MONTHS = ("2025-04", "2025-05", "2025-06")
MARKER = ("depreciation_reversal_month", "depreciation_reversal_claimed_at")


class _Died(BaseException):
    """The process dying mid-request: no `except Exception` in the route can catch it, so nothing is put back or cleared."""


def _asset(db, months=MONTHS, *, migrated=True):
    row = _create(db, name="Lathe", category="Plant & Machinery", life=15, method="WDV")
    if migrated:
        row.update({k: None for k in MARKER})          # `select("*")` after migration 587: the columns are there, NULL
    for period in months:
        assert fa.post_depreciation(row["id"], DepreciationIn(period=period), CALLER)["success"]
    return row


def _reference(row, period):
    return f"FA-DEPN-{row.get('asset_code') or row['id'][:8]}-{period}"


def _live(db, row, period):
    return [e for e in db.rows("journal_entries")
            if e.get("reference_no") == _reference(row, period) and not e.get("is_reversed") and not e.get("deleted_at")]


def _ago(minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _ties(db, row):
    """The register and the ledger say the same thing: the shared ledger holds exactly the register's figure."""
    _sync_balances(db)
    return _credit(db, SHARED) == int(row["accumulated_depreciation_paise"])


def _dies_mid_reversal(monkeypatch, row, period="2025-06", *, after_journal=False, minutes=20):
    """Reverse `period` and die after the claim: before the journal is reversed, or after it and before the marker comes off."""
    real = fa._reverse_tolerating_already_reversed

    def dies(*a, **k):
        if after_journal:
            real(*a, **k)
        raise _Died()

    monkeypatch.setattr(fa, "_reverse_tolerating_already_reversed", dies)
    with pytest.raises(_Died):
        fa.reverse_depreciation(row["id"], period, CALLER)
    monkeypatch.setattr(fa, "_reverse_tolerating_already_reversed", real)
    assert row["depreciation_reversal_month"] == period, "the claim wrote the marker"
    if minutes:
        row["depreciation_reversal_claimed_at"] = _ago(minutes)


# ── the reversal marks the asset ─────────────────────────────────────────────

def test_the_reversal_marks_the_asset_while_it_reverses_the_journal_and_takes_the_mark_off_after(monkeypatch):
    db = _firm(monkeypatch)
    row = _asset(db)
    real, seen = fa._reverse_tolerating_already_reversed, {}

    def watching(*a, **k):
        seen.update({k_: row.get(k_) for k_ in (*MARKER, "depreciation_posted_through")})
        return real(*a, **k)

    monkeypatch.setattr(fa, "_reverse_tolerating_already_reversed", watching)
    assert fa.reverse_depreciation(row["id"], "2025-06", CALLER)["success"] is True
    assert seen["depreciation_reversal_month"] == "2025-06" and seen["depreciation_reversal_claimed_at"]
    assert str(seen["depreciation_posted_through"])[:7] == "2025-05", "the marker went on in the same write as the claim"
    assert all(row[k] is None for k in MARKER) and not _live(db, row, "2025-06") and _ties(db, row)


def test_a_failed_reversal_puts_the_marker_back_with_the_register(monkeypatch):
    db = _firm(monkeypatch)
    row = _asset(db)
    before = {k: row.get(k) for k in ("accumulated_depreciation_paise", "depreciation_posted_through", *MARKER)}
    monkeypatch.setattr(fa, "_reverse_tolerating_already_reversed", lambda *a, **k: (_ for _ in ()).throw(ValueError("outage")))
    with pytest.raises(ValueError):
        fa.reverse_depreciation(row["id"], "2025-06", CALLER)
    assert {k: row.get(k) for k in before} == before
    assert fa.post_depreciation(row["id"], DepreciationIn(period="2025-07"), CALLER)["success"], "nothing is left blocking a post"


# ── the two interleavings ────────────────────────────────────────────────────

def test_a_post_of_the_month_between_the_claim_and_the_journal_is_refused_and_the_ledger_and_register_agree(monkeypatch):
    """The ledger item's own interleaving. Before migration 587 the post adopted the live journal and wrote the month back."""
    db = _firm(monkeypatch)
    row = _asset(db)
    real, refused = fa._reverse_tolerating_already_reversed, []

    def a_post_lands_first(*a, **k):
        with pytest.raises(HTTPException) as exc:
            fa.post_depreciation(row["id"], DepreciationIn(period="2025-06"), CALLER)
        refused.append(exc.value)
        return real(*a, **k)

    monkeypatch.setattr(fa, "_reverse_tolerating_already_reversed", a_post_lands_first)
    assert fa.reverse_depreciation(row["id"], "2025-06", CALLER)["success"] is True
    assert refused and refused[0].status_code == 409 and "Nothing was posted. A reversal of 2025-06 started at" in refused[0].detail
    assert str(row["depreciation_posted_through"])[:7] == "2025-05" and not _live(db, row, "2025-06") and _ties(db, row)


def test_a_post_whose_register_write_lands_after_a_reversal_claimed_the_asset_takes_its_journal_back(monkeypatch):
    """The other order: the post read the row before the claim and writes after it."""
    db = _firm(monkeypatch)
    row = _asset(db)
    real_post = fa.Phase2JournalService.journal_for_depreciation

    def posts_then_a_reversal_claims(self, asset, *a, **k):
        entry = real_post(self, asset, *a, **k)
        row.update({"depreciation_reversal_month": "2025-06", "depreciation_reversal_claimed_at": _ago(0)})
        return entry

    monkeypatch.setattr(fa.Phase2JournalService, "journal_for_depreciation", posts_then_a_reversal_claims)
    with pytest.raises(HTTPException) as exc:
        fa.post_depreciation(row["id"], DepreciationIn(period="2025-07"), CALLER)
    assert exc.value.status_code == 409 and "a reversal claimed it" in exc.value.detail
    assert not _live(db, row, "2025-07") and str(row["depreciation_posted_through"])[:7] == "2025-06"


def test_a_fresh_marker_refuses_a_post_of_any_month_and_writes_nothing(monkeypatch):
    db = _firm(monkeypatch)
    row = _asset(db)
    row.update({"depreciation_reversal_month": "2025-06", "depreciation_reversal_claimed_at": _ago(1)})
    entries = len(db.rows("journal_entries"))
    with pytest.raises(HTTPException) as exc:
        fa.post_depreciation(row["id"], DepreciationIn(period="2025-07"), CALLER)
    assert exc.value.status_code == 409 and "Nothing was posted. A reversal of 2025-06 started at" in exc.value.detail
    assert "IST" in exc.value.detail and "Finish reversing 2025-06 is offered from" in exc.value.detail
    assert len(db.rows("journal_entries")) == entries


# ── a reversal that died ─────────────────────────────────────────────────────

def test_within_the_lease_a_reversal_that_died_still_holds_every_post_off(monkeypatch):
    db = _firm(monkeypatch)
    row = _asset(db)
    _dies_mid_reversal(monkeypatch, row, minutes=0)
    with pytest.raises(HTTPException) as exc:
        fa.post_depreciation(row["id"], DepreciationIn(period="2025-06"), CALLER)
    assert exc.value.status_code == 409 and _live(db, row, "2025-06"), "the live journal is left for the reversal to finish"


def test_past_the_lease_a_post_adopts_the_live_journal_and_takes_the_marker_off(monkeypatch):
    db = _firm(monkeypatch)
    row = _asset(db)
    _dies_mid_reversal(monkeypatch, row)
    entries = len(db.rows("journal_entries"))
    out = fa.post_depreciation(row["id"], DepreciationIn(period="2025-06"), CALLER)
    assert out["success"] is True and len(db.rows("journal_entries")) == entries, "the live journal was adopted, not posted twice"
    assert str(row["depreciation_posted_through"])[:7] == "2025-06" and all(row[k] is None for k in MARKER) and _ties(db, row)


def test_past_the_lease_a_repeated_reversal_of_the_month_completes_it(monkeypatch):
    db = _firm(monkeypatch)
    row = _asset(db)
    _dies_mid_reversal(monkeypatch, row)
    register = row["accumulated_depreciation_paise"]
    out = fa.reverse_depreciation(row["id"], "2025-06", CALLER)["data"]
    assert out["completed"] is True and out["journal_reversed_now"] is True
    assert not _live(db, row, "2025-06") and all(row[k] is None for k in MARKER)
    assert row["accumulated_depreciation_paise"] == register and _ties(db, row)


def test_a_reversal_that_died_after_its_journal_is_completed_by_taking_the_marker_off(monkeypatch):
    db = _firm(monkeypatch)
    row = _asset(db)
    _dies_mid_reversal(monkeypatch, row, after_journal=True)
    entries = len(db.rows("journal_entries"))
    out = fa.reverse_depreciation(row["id"], "2025-06", CALLER)["data"]
    assert out["completed"] is True and out["journal_reversed_now"] is False
    assert len(db.rows("journal_entries")) == entries and all(row[k] is None for k in MARKER) and _ties(db, row)


def test_another_month_is_refused_until_the_dead_reversal_is_completed(monkeypatch):
    db = _firm(monkeypatch)
    row = _asset(db)
    _dies_mid_reversal(monkeypatch, row)
    with pytest.raises(HTTPException) as exc:
        fa.reverse_depreciation(row["id"], "2025-05", CALLER)
    assert exc.value.status_code == 409 and "A reversal of 2025-06 on this asset did not finish. Finish reversing 2025-06 first" in exc.value.detail
    assert _live(db, row, "2025-05") and _live(db, row, "2025-06"), "nothing was reversed"


def test_a_second_reversal_within_the_lease_is_refused(monkeypatch):
    db = _firm(monkeypatch)
    row = _asset(db)
    _dies_mid_reversal(monkeypatch, row, minutes=0)
    with pytest.raises(HTTPException) as exc:
        fa.reverse_depreciation(row["id"], "2025-06", CALLER)
    assert exc.value.status_code == 409 and "Nothing was reversed. A reversal of 2025-06 started at" in exc.value.detail and _live(db, row, "2025-06")


def test_a_completion_that_loses_to_a_post_that_adopted_the_asset_reverses_nothing(monkeypatch):
    db = _firm(monkeypatch)
    row = _asset(db)
    _dies_mid_reversal(monkeypatch, row)
    stale = dict(row)                                                            # what the completion read: the dead marker
    assert fa.post_depreciation(row["id"], DepreciationIn(period="2025-06"), CALLER)["success"]   # ...then a post adopted it
    monkeypatch.setattr(fa, "_live_asset", lambda db_, asset_id, firm_id: dict(stale))
    with pytest.raises(HTTPException) as exc:
        fa.reverse_depreciation(row["id"], "2025-06", CALLER)
    assert exc.value.status_code == 409 and "was being finished" in exc.value.detail
    assert _live(db, row, "2025-06") and str(row["depreciation_posted_through"])[:7] == "2025-06" and _ties(db, row)


def test_the_year_run_posts_past_a_dead_marker_without_tripping_on_the_one_it_cleared(monkeypatch):
    db = _firm(monkeypatch)
    row = _asset(db)
    _dies_mid_reversal(monkeypatch, row)
    monkeypatch.setattr(fa, "assert_client_access", lambda *a, **k: None)
    got = fa.run_depreciation(DepreciationRunIn(client_id=CLIENT, from_period="2025-06", to_period="2025-08"), CALLER)["data"]
    mine = next(a for a in got["assets"] if a["asset_id"] == row["id"])
    assert [m["period"] for m in mine["months"]] == ["2025-06", "2025-07", "2025-08"] and mine["stopped_at"] is None, mine
    assert str(row["depreciation_posted_through"])[:7] == "2025-08" and all(row[k] is None for k in MARKER) and _ties(db, row)


# ── the edges ────────────────────────────────────────────────────────────────

def test_a_row_read_before_the_migration_is_written_as_before():
    """No marker column on the row: the claim and the post write what they always wrote, so the API can run ahead of migration 587."""
    calls = []

    class Q:
        def __getattr__(self, name):
            return lambda *a, **k: calls.append((name, a)) or self

    q = Q()
    assert fa._with_marker_as_read(q, {"id": "a"}) is q and calls == []
    assert fa._adopting_a_dead_marker({"x": 1}, {"id": "a"}) == {"x": 1}
    assert fa._reversal_in_flight({"id": "a"}) is None


def test_a_row_read_before_the_migration_reverses_and_posts_without_naming_a_marker(monkeypatch):
    db = _firm(monkeypatch)
    row = _asset(db, migrated=False)
    assert fa.reverse_depreciation(row["id"], "2025-06", CALLER)["success"] is True
    assert fa.post_depreciation(row["id"], DepreciationIn(period="2025-06"), CALLER)["success"] is True
    assert not any(k in row for k in MARKER), "a column the database may not have yet was written"


def _stamp(kind):
    """Worked out when the test RUNS: a stamp fixed at collection ages by however long a parallel run takes to reach the test."""
    if isinstance(kind, int):
        return _ago(kind)
    if kind == "naive":
        return (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(tzinfo=None).isoformat()
    return kind


@pytest.mark.parametrize("kind,live", [
    (None, True),                                       # unreadable: refuse rather than write over a reversal
    ("not a time", True),
    (1, True),
    (14, True),
    (16, False),
    ("naive", True),                                    # a stamp with no zone is read as UTC
], ids=["no-stamp", "unreadable", "1-minute", "14-minutes", "16-minutes", "naive-1-minute"])
def test_a_marker_is_live_within_the_lease_and_when_its_stamp_cannot_be_read(kind, live):
    got = fa._reversal_in_flight({"depreciation_reversal_month": "2025-06", "depreciation_reversal_claimed_at": _stamp(kind)})
    assert got == ("2025-06" if live else None)
    assert fa._reversal_in_flight({"depreciation_reversal_month": None, "depreciation_reversal_claimed_at": None}) is None


# ── what the independent read found ──────────────────────────────────────────

def test_two_posts_of_the_month_past_a_dead_marker_do_not_reverse_the_journal_the_first_one_kept(monkeypatch):
    """Both are handed ONE journal by the kernel. The first writes the register and takes the marker off; the second's
    compare-and-set misses on the marker it read, and reversing then would take off the journal the register counts."""
    db = _firm(monkeypatch)
    row = _asset(db)
    _dies_mid_reversal(monkeypatch, row)
    stale = dict(row)                                                            # what the second post read
    assert fa.post_depreciation(row["id"], DepreciationIn(period="2025-06"), CALLER)["success"]   # the first post
    real_read, reads = fa._live_asset, {"n": 0}

    def second_post_reads_the_old_row_first(db_, asset_id, firm_id):
        reads["n"] += 1
        return dict(stale) if reads["n"] == 1 else real_read(db_, asset_id, firm_id)

    monkeypatch.setattr(fa, "_live_asset", second_post_reads_the_old_row_first)
    with pytest.raises(HTTPException) as exc:
        fa.post_depreciation(row["id"], DepreciationIn(period="2025-06"), CALLER)
    assert exc.value.status_code == 409 and "posted on this asset by another request at the same moment" in exc.value.detail
    assert _live(db, row, "2025-06") and str(row["depreciation_posted_through"])[:7] == "2025-06" and _ties(db, row)


def test_a_stalled_reversal_whose_journal_fails_after_another_request_finished_it_does_not_put_the_register_back(monkeypatch):
    """R claims and its journal call stalls past the lease; Finish reversing re-stamps the marker, reverses the journal and clears it;
    then R's call raises. R's restore matched on the figure alone and wrote June back over a reversed journal."""
    db = _firm(monkeypatch)
    row = _asset(db)
    real, calls = fa._reverse_tolerating_already_reversed, {"n": 0}

    def stalls_then_another_request_finishes_it(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:                                                      # R's own journal call
            row["depreciation_reversal_claimed_at"] = _ago(20)                   # ...stalled past the lease
            assert fa.reverse_depreciation(row["id"], "2025-06", CALLER)["data"]["completed"] is True
            raise ValueError("timed out")
        return real(*a, **k)                                                     # the completion's journal call

    monkeypatch.setattr(fa, "_reverse_tolerating_already_reversed", stalls_then_another_request_finishes_it)
    with pytest.raises(ValueError):
        fa.reverse_depreciation(row["id"], "2025-06", CALLER)
    assert str(row["depreciation_posted_through"])[:7] == "2025-05", "the register was put back over a reversed journal"
    assert not _live(db, row, "2025-06") and all(row[k] is None for k in MARKER) and _ties(db, row)


def test_an_asset_whose_reversal_did_not_finish_cannot_be_deleted_until_it_is_finished(monkeypatch):
    db = _firm(monkeypatch)
    row = _asset(db, months=("2025-04",))
    _dies_mid_reversal(monkeypatch, row, period="2025-04")
    assert row.get("depreciation_posted_through") in (None, "") or str(row["depreciation_posted_through"])[:7] < "2025-04"
    with pytest.raises(HTTPException) as exc:
        fa.delete_asset(row["id"], CALLER)
    assert exc.value.status_code == 422 and "Finish reversing 2025-04 (Depreciation tab), then delete" in exc.value.detail
    assert _live(db, row, "2025-04") and not row.get("deleted_at")
    assert fa.reverse_depreciation(row["id"], "2025-04", CALLER)["data"]["completed"] is True
    assert fa.delete_asset(row["id"], CALLER)["success"] is True and not _live(db, row, "2025-04")


def test_the_depreciation_table_serves_an_unfinished_reversal_in_words_with_its_times_in_india(monkeypatch):
    db = _firm(monkeypatch)
    row = _asset(db)
    monkeypatch.setattr(fa, "assert_client_access", lambda *a, **k: None)

    def mine():
        return next(r for r in fa.depreciation_schedule(CLIENT, CALLER)["data"] if r["asset_id"] == row["id"])

    assert mine()["unfinished_reversal"] is None
    _dies_mid_reversal(monkeypatch, row, minutes=0)
    held = mine()["unfinished_reversal"]
    assert held["month"] == "2025-06" and held["can_finish_now"] is False and "IST" in held["sentence"]
    assert "Finish reversing 2025-06 is offered from" in held["sentence"]
    row["depreciation_reversal_claimed_at"] = _ago(20)
    free = mine()["unfinished_reversal"]
    assert free["can_finish_now"] is True and "did not finish" in free["sentence"] and "post 2025-06 again" in free["sentence"]


def test_a_stamp_that_cannot_be_read_holds_posts_off_and_can_still_be_finished(monkeypatch):
    db = _firm(monkeypatch)
    row = _asset(db)
    _dies_mid_reversal(monkeypatch, row, minutes=0)
    row["depreciation_reversal_claimed_at"] = "not a time"
    with pytest.raises(HTTPException) as exc:
        fa.post_depreciation(row["id"], DepreciationIn(period="2025-06"), CALLER)
    assert exc.value.status_code == 409 and "start time could not be read" in exc.value.detail
    assert fa.reverse_depreciation(row["id"], "2025-06", CALLER)["data"]["completed"] is True and _ties(db, row)


def test_finishing_a_reversal_in_a_closed_year_is_refused_and_leaves_the_marker(monkeypatch):
    db = _firm(monkeypatch)
    row = _asset(db)
    _dies_mid_reversal(monkeypatch, row)
    next(f for f in db.rows("firms") if f["id"] == row["firm_id"])["locked_financial_years"] = ["2025-26"]
    stamp = row["depreciation_reversal_claimed_at"]
    with pytest.raises(HTTPException) as exc:
        fa.reverse_depreciation(row["id"], "2025-06", CALLER)
    assert exc.value.status_code in (409, 422) and _live(db, row, "2025-06")
    assert row["depreciation_reversal_month"] == "2025-06" and row["depreciation_reversal_claimed_at"] == stamp


def test_a_failure_while_finishing_keeps_the_marker_so_it_can_be_finished_again(monkeypatch):
    db = _firm(monkeypatch)
    row = _asset(db)
    _dies_mid_reversal(monkeypatch, row)
    real = fa._reverse_tolerating_already_reversed
    monkeypatch.setattr(fa, "_reverse_tolerating_already_reversed", lambda *a, **k: (_ for _ in ()).throw(ValueError("outage")))
    with pytest.raises(ValueError):
        fa.reverse_depreciation(row["id"], "2025-06", CALLER)
    assert row["depreciation_reversal_month"] == "2025-06" and _live(db, row, "2025-06")
    with pytest.raises(HTTPException) as held:                                    # the renewed stamp holds a post off
        fa.post_depreciation(row["id"], DepreciationIn(period="2025-06"), CALLER)
    assert held.value.status_code == 409
    monkeypatch.setattr(fa, "_reverse_tolerating_already_reversed", real)
    row["depreciation_reversal_claimed_at"] = _ago(20)
    assert fa.reverse_depreciation(row["id"], "2025-06", CALLER)["data"]["completed"] is True and _ties(db, row)
