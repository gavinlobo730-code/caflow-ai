"""Migration 635 on a real database: a depreciation post that read the asset before a WHOLE reversal ran cannot write over it
(ledger POST-A-434).

WHAT ONLY POSTGRES CAN PROVE
    The version is added to by a trigger, so only a real database shows that:
    * every change to the register's columns adds one and an edit of a name does not;
    * a post of the next month that read the row, and whose write lands after a reversal of the month before it has claimed the row,
      reversed the journal AND cleared its marker (the row then reads as it did before the claim, which 587's marker cannot see),
      misses, takes its own journal back and answers 409, so the register and the ledger agree to the paisa;
    * two posts of one month, the second's write landing after the first's, keep the ONE journal the register counts.
Reuses the `world` of the POST-A-349 real-database file. Runs only when HARNESS_PG is set; skips in the mock-mode job.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from tests.test_587_a_month_being_reversed_cannot_be_posted_over_pg import _lathe, _live_months, _row, _ties
from tests.test_an_intangible_assets_amortisation_ties_to_its_own_balance_sheet_line_pg import (  # noqa: F401 — `world` is a fixture
    PARTNER, _psql, _rows, pytestmark, world,
)


def _version(w, asset_id) -> int:
    return int(_rows(w.dsn, f"SELECT register_version FROM fixed_assets WHERE id = '{asset_id}'")[0][0])


def test_the_version_moves_with_the_register_and_not_with_a_name(world):  # noqa: F811 — `world` is the imported fixture
    w = world
    asset_id = _lathe(w)
    before = _version(w, asset_id)
    assert before >= 3, "three months were posted"
    assert _psql(w.dsn, f"UPDATE fixed_assets SET asset_name = 'Renamed lathe' WHERE id = '{asset_id}';").returncode == 0
    assert _version(w, asset_id) == before
    assert _psql(w.dsn, f"UPDATE fixed_assets SET depreciation_reversal_month = '2025-06', "
                        f"depreciation_reversal_claimed_at = now() WHERE id = '{asset_id}';").returncode == 0
    assert _version(w, asset_id) == before + 1


def test_a_post_that_read_the_row_before_a_whole_reversal_takes_its_journal_back(world, monkeypatch):  # noqa: F811
    import routers.fixed_assets as fa
    from models.accounting import DepreciationIn
    w = world
    asset_id = _lathe(w)                                              # Apr, May, Jun posted
    real_post = fa.Phase2JournalService.journal_for_depreciation

    def posts_then_a_whole_reversal_runs(self, asset, *a, **k):
        entry = real_post(self, asset, *a, **k)                       # July's journal, written from the row read before
        monkeypatch.setattr(fa.Phase2JournalService, "journal_for_depreciation", real_post)
        assert fa.reverse_depreciation(asset_id, "2025-06", PARTNER)["success"]    # claims, reverses and CLEARS the marker
        assert _row(w, asset_id)["depreciation_reversal_month"] is None
        return entry

    monkeypatch.setattr(fa.Phase2JournalService, "journal_for_depreciation", posts_then_a_whole_reversal_runs)
    with pytest.raises(HTTPException) as exc:
        fa.post_depreciation(asset_id, DepreciationIn(period="2025-07"), PARTNER)
    assert exc.value.status_code == 409
    assert _live_months(w, asset_id) == ["2025-04", "2025-05"], "July's journal was taken back and June's was reversed"
    assert _row(w, asset_id)["depreciation_posted_through"].startswith("2025-05")
    assert _ties(w, asset_id), "the ledger and the register agree to the paisa"
    # The way out is the ordinary one: the months post again.
    for period in ("2025-06", "2025-07"):
        assert fa.post_depreciation(asset_id, DepreciationIn(period=period), PARTNER)["success"]
    assert _live_months(w, asset_id) == ["2025-04", "2025-05", "2025-06", "2025-07"] and _ties(w, asset_id)


def test_two_posts_of_one_month_keep_the_one_journal_the_register_counts(world, monkeypatch):  # noqa: F811
    import routers.fixed_assets as fa
    from models.accounting import DepreciationIn
    w = world
    asset_id = _lathe(w)
    real_post = fa.Phase2JournalService.journal_for_depreciation

    def the_other_post_finishes_first(self, asset, *a, **k):
        monkeypatch.setattr(fa.Phase2JournalService, "journal_for_depreciation", real_post)
        assert fa.post_depreciation(asset_id, DepreciationIn(period="2025-07"), PARTNER)["success"]
        return real_post(self, asset, *a, **k)                         # the kernel hands this one the same entry

    monkeypatch.setattr(fa.Phase2JournalService, "journal_for_depreciation", the_other_post_finishes_first)
    with pytest.raises(HTTPException) as exc:
        fa.post_depreciation(asset_id, DepreciationIn(period="2025-07"), PARTNER)
    assert exc.value.status_code == 409 and "by another request" in exc.value.detail
    assert _live_months(w, asset_id) == ["2025-04", "2025-05", "2025-06", "2025-07"] and _ties(w, asset_id)
