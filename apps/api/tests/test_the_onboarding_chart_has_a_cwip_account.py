"""A firm onboarded through the product can post capital work-in-progress.

The chart every onboarded firm gets (STANDARD_COA) had no Capital
Work-in-Progress account, and migration 397's backfill collided with its 1504 =
Vehicles and was skipped — so `journal_for_cwip_addition` could never find its
account for those firms (migration 425 repairs the ones that exist).
"""
from __future__ import annotations

import fnmatch

from domain.reporting import schedule_iii
from services.coa_seed_service import STANDARD_COA


def _ilike(pattern: str, value: str) -> bool:
    return fnmatch.fnmatch(value.lower(), pattern.lower().replace("%", "*"))


def test_the_standard_chart_has_an_account_the_cwip_posting_finds():
    # phase2_journal_service.journal_for_cwip_addition falls back to exactly
    # this ILIKE when no account carries system key 'cwip'.
    hits = [row for row in STANDARD_COA if _ilike("%Capital Work-in-Progress%", row[1])]
    assert len(hits) == 1, hits
    code, _name, account_type, subtype = hits[0]
    assert account_type == "Asset"
    assert subtype == "Capital Work-in-Progress"   # load-bearing for Schedule III
    assert code == "1507"


def test_its_code_collides_with_nothing_else_on_the_chart():
    codes = [row[0] for row in STANDARD_COA]
    assert len(codes) == len(set(codes))
    assert dict((c, n) for c, n, _t, _s in STANDARD_COA)["1504"] == "Vehicles"


def test_schedule_iii_presents_it_as_capital_work_in_progress_not_as_ppe():
    caption, basis = schedule_iii.classify("Asset", "Capital Work-in-Progress")
    assert basis == "subtype"
    assert "work" in caption.lower() and "progress" in caption.lower(), caption
