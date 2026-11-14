"""Migration 587 on a real database: a month of depreciation that is being reversed cannot be posted over (ledger POST-A-349).

WHAT ONLY POSTGRES CAN PROVE
    The mock-mode file (`test_a_month_being_reversed_cannot_be_posted_over.py`) holds the rule on a fake database that compares
    timestamps as text. Here the two interleavings run through the real routes, the real posting kernel and the real ledger doors as the
    roles production uses, so what is proved is that:
    * the post's register write, a compare-and-set on the marker it read, really misses once a reversal has claimed the row;
    * the clear after the journal (a compare-and-set on the claim's own stamp, sent as text and compared as timestamptz) really matches,
      so the marker comes off and does not sit there for the lease;
    * the stamp read back from the database is read as an instant, so a fresh marker refuses and an aged one is adopted or completed;
    * the two CHECKs refuse half a marker and a month that is not one;
    and, after each interleaving, the ledger's Accumulated Depreciation equals the register's figure to the paisa.

HOW. The `world` of the POST-A-345 real-database file is reused (one chart, one firm, one Partner, the service-role and signed-in
clients the routes are handed in production).

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from tests.test_an_intangible_assets_amortisation_ties_to_its_own_balance_sheet_line_pg import (  # noqa: F401 — `world` is a fixture
    PARTNER, _ADMIN, _balances, _create, _depreciate, _psql, _rows, pytestmark, world,
)

MONTHS = ("2025-04", "2025-05", "2025-06")
_NULL = "<null>"


class _Died(BaseException):
    """The process dying mid-request: no `except Exception` in the route can catch it."""


def _lathe(w):
    asset = _create(w, "Lathe", "Plant & Machinery", 2_40_000_00, 15, "WDV")
    _depreciate(w, asset["id"], MONTHS)
    return asset["id"]


def _row(w, asset_id) -> dict:
    cols = ("accumulated_depreciation_paise", "depreciation_posted_through", "depreciation_reversal_month",
            "depreciation_reversal_claimed_at")
    got = _rows(w.dsn, f"SELECT {', '.join(f'COALESCE({c}::text, {_NULL!r})' for c in cols)} FROM fixed_assets WHERE id = '{asset_id}'")[0]
    return {c: (None if v == _NULL else v) for c, v in zip(cols, got, strict=True)}


def _live_months(w, asset_id) -> list[str]:
    code = _rows(w.dsn, f"SELECT asset_code FROM fixed_assets WHERE id = '{asset_id}'")[0][0]
    return [r[0][-7:] for r in _rows(w.dsn, (
        f"SELECT reference_no FROM journal_entries WHERE reference_no LIKE 'FA-DEPN-{code}-%' AND NOT is_reversed AND deleted_at IS NULL "
        "ORDER BY reference_no"))]


def _ties(w, asset_id) -> bool:
    """The ledger's Accumulated Depreciation (a credit) equals the register's figure: the only asset of the client is this one."""
    return -_balances(w).get("1590", 0) == int(_row(w, asset_id)["accumulated_depreciation_paise"])


def test_a_post_of_the_month_between_the_claim_and_the_journal_is_refused_and_the_ledger_ties(world, monkeypatch):  # noqa: F811 — `world` is the imported fixture
    import routers.fixed_assets as fa
    from models.accounting import DepreciationIn
    w = world
    asset_id = _lathe(w)
    real, refused = fa._reverse_tolerating_already_reversed, []

    def a_post_lands_first(*a, **k):
        assert _row(w, asset_id)["depreciation_reversal_month"] == "2025-06", "the marker is on the row in the database"
        with pytest.raises(HTTPException) as exc:
            fa.post_depreciation(asset_id, DepreciationIn(period="2025-06"), PARTNER)
        refused.append(exc.value)
        return real(*a, **k)

    monkeypatch.setattr(fa, "_reverse_tolerating_already_reversed", a_post_lands_first)
    assert fa.reverse_depreciation(asset_id, "2025-06", PARTNER)["success"] is True
    assert refused and refused[0].status_code == 409 and "Nothing was posted. A reversal of 2025-06 started at" in refused[0].detail
    after = _row(w, asset_id)
    assert after["depreciation_posted_through"].startswith("2025-05") and after["depreciation_reversal_month"] is None
    assert after["depreciation_reversal_claimed_at"] is None, "the clear's compare-and-set on its own stamp matched in the database"
    assert _live_months(w, asset_id) == ["2025-04", "2025-05"] and _ties(w, asset_id)


def test_a_post_whose_write_lands_after_a_reversal_claimed_the_row_takes_its_journal_back_and_the_reversal_is_then_completed(
        world, monkeypatch):  # noqa: F811 — `world` is the imported fixture
    import routers.fixed_assets as fa
    from models.accounting import DepreciationIn
    w = world
    asset_id = _lathe(w)
    real_post, real_reverse = fa.Phase2JournalService.journal_for_depreciation, fa._reverse_tolerating_already_reversed

    def dies(*a, **k):
        raise _Died()

    def posts_then_a_reversal_claims(self, asset, *a, **k):
        entry = real_post(self, asset, *a, **k)
        monkeypatch.setattr(fa, "_reverse_tolerating_already_reversed", dies)
        with pytest.raises(_Died):
            fa.reverse_depreciation(asset_id, "2025-06", PARTNER)     # claims the row in the database, then dies
        monkeypatch.setattr(fa, "_reverse_tolerating_already_reversed", real_reverse)
        return entry

    monkeypatch.setattr(fa.Phase2JournalService, "journal_for_depreciation", posts_then_a_reversal_claims)
    with pytest.raises(HTTPException) as exc:
        fa.post_depreciation(asset_id, DepreciationIn(period="2025-07"), PARTNER)
    monkeypatch.setattr(fa.Phase2JournalService, "journal_for_depreciation", real_post)
    assert exc.value.status_code == 409 and "a reversal claimed it" in exc.value.detail
    assert _live_months(w, asset_id) == ["2025-04", "2025-05", "2025-06"], "the post's own journal for July was taken back"
    assert _row(w, asset_id)["depreciation_reversal_month"] == "2025-06"

    # Within the lease the dead claim holds every post off, read back from the database as an instant.
    with pytest.raises(HTTPException) as held:
        fa.post_depreciation(asset_id, DepreciationIn(period="2025-06"), PARTNER)
    assert held.value.status_code == 409 and "Nothing was posted. A reversal of 2025-06 started at" in held.value.detail

    # Past it, the reversal of the same month is completed: June's journal reversed, the marker off, the ledger tied.
    assert _psql(w.dsn, f"UPDATE fixed_assets SET depreciation_reversal_claimed_at = now() - interval '20 minutes' "
                        f"WHERE id = '{asset_id}';").returncode == 0
    out = fa.reverse_depreciation(asset_id, "2025-06", PARTNER)["data"]
    assert out["completed"] is True and out["journal_reversed_now"] is True
    after = _row(w, asset_id)
    assert after["depreciation_reversal_month"] is None and after["depreciation_reversal_claimed_at"] is None
    assert _live_months(w, asset_id) == ["2025-04", "2025-05"] and _ties(w, asset_id)


def test_past_the_lease_a_post_adopts_the_live_journal_in_the_database(world, monkeypatch):  # noqa: F811 — `world` is the imported fixture
    import routers.fixed_assets as fa
    from models.accounting import DepreciationIn
    w = world
    asset_id = _lathe(w)
    real = fa._reverse_tolerating_already_reversed
    monkeypatch.setattr(fa, "_reverse_tolerating_already_reversed", lambda *a, **k: (_ for _ in ()).throw(_Died()))
    with pytest.raises(_Died):
        fa.reverse_depreciation(asset_id, "2025-06", PARTNER)
    monkeypatch.setattr(fa, "_reverse_tolerating_already_reversed", real)
    assert _psql(w.dsn, f"UPDATE fixed_assets SET depreciation_reversal_claimed_at = now() - interval '20 minutes' "
                        f"WHERE id = '{asset_id}';").returncode == 0
    entries = int(_rows(w.dsn, "SELECT count(*) FROM journal_entries")[0][0])
    assert fa.post_depreciation(asset_id, DepreciationIn(period="2025-06"), PARTNER)["success"] is True
    assert int(_rows(w.dsn, "SELECT count(*) FROM journal_entries")[0][0]) == entries, "the live journal was adopted, not posted twice"
    after = _row(w, asset_id)
    assert after["depreciation_posted_through"].startswith("2025-06") and after["depreciation_reversal_month"] is None
    assert _ties(w, asset_id)


@pytest.mark.parametrize("assignment,constraint", [
    ("depreciation_reversal_month = '2025-06'", "fixed_assets_reversal_marker_is_whole"),
    ("depreciation_reversal_claimed_at = now()", "fixed_assets_reversal_marker_is_whole"),
    ("depreciation_reversal_month = '2025-13', depreciation_reversal_claimed_at = now()", "fixed_assets_reversal_marker_is_a_month"),
    ("depreciation_reversal_month = 'June', depreciation_reversal_claimed_at = now()", "fixed_assets_reversal_marker_is_a_month"),
])
def test_half_a_marker_or_a_month_that_is_not_one_is_refused_by_the_database(world, assignment, constraint):  # noqa: F811 — `world` is the imported fixture
    w = world
    asset_id = _lathe(w)
    r = _psql(w.dsn, f"UPDATE fixed_assets SET {assignment} WHERE id = '{asset_id}';")
    assert r.returncode != 0 and constraint in r.stderr, r.stderr
    assert _psql(w.dsn, f"UPDATE fixed_assets SET depreciation_reversal_month = '2025-06', depreciation_reversal_claimed_at = now() "
                        f"WHERE id = '{asset_id}';").returncode == 0, "a whole marker is accepted"


def test_two_posts_of_the_month_past_a_dead_reversal_keep_the_one_journal_the_register_counts(world, monkeypatch):  # noqa: F811
    """Found by the independent read: both posts are handed one journal; the second's compare-and-set misses on the marker the first
    took off, and it must not reverse the journal the register now counts. Proved on the database, through the real re-read."""
    import routers.fixed_assets as fa
    from models.accounting import DepreciationIn
    w = world
    asset_id = _lathe(w)
    real = fa._reverse_tolerating_already_reversed
    monkeypatch.setattr(fa, "_reverse_tolerating_already_reversed", lambda *a, **k: (_ for _ in ()).throw(_Died()))
    with pytest.raises(_Died):
        fa.reverse_depreciation(asset_id, "2025-06", PARTNER)
    monkeypatch.setattr(fa, "_reverse_tolerating_already_reversed", real)
    assert _psql(w.dsn, f"UPDATE fixed_assets SET depreciation_reversal_claimed_at = now() - interval '20 minutes' "
                        f"WHERE id = '{asset_id}';").returncode == 0
    real_read = fa._live_asset
    stale = real_read(w.service_db, asset_id, PARTNER["firm_id"])                 # what the second post read
    assert fa.post_depreciation(asset_id, DepreciationIn(period="2025-06"), PARTNER)["success"] is True   # the first post
    reads = {"n": 0}

    def second_post_reads_the_old_row_first(db_, aid, firm_id):
        reads["n"] += 1
        return dict(stale) if reads["n"] == 1 else real_read(db_, aid, firm_id)

    monkeypatch.setattr(fa, "_live_asset", second_post_reads_the_old_row_first)
    with pytest.raises(HTTPException) as exc:
        fa.post_depreciation(asset_id, DepreciationIn(period="2025-06"), PARTNER)
    assert exc.value.status_code == 409 and "by another request at the same moment" in exc.value.detail
    assert _live_months(w, asset_id) == ["2025-04", "2025-05", "2025-06"] and _ties(w, asset_id)
