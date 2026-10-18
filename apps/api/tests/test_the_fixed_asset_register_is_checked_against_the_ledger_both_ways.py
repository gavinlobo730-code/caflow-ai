"""The fixed-asset register is checked against the LEDGER in both directions (POST-A-110, the residue of FA-20).

WHAT WAS MISSING
    `integrity.register_findings` ran five checks, all of which read the register (or the bill behind an asset). Two asks of the
    ledger were absent: an asset the register shows as DISPOSED with no disposal entry (its cost and accumulated depreciation are
    still on the balance sheet and no gain or loss reached the profit and loss account), and an ACQUISITION entry in the ledger
    with no asset in the register (cost in Fixed Assets with nothing behind it).

WHAT IS HELD
    * the two pure rules, and that they are NOT asked when the caller passes no `LedgerLinks` (a caller that could not read the
      ledger must not be told "clean");
    * the fetch (`services/fixed_asset_ledger_links`) over an in-memory database: only live entries count (not deleted, not
      reversed, not themselves a reversal), only this client's and this source's, and a disposal is read for the disposed assets
      only;
    * both readers of the register hand the rule the same fetch (the endpoint and the nightly / Verify Books sweep), the sweep
      files both as critical, and both kinds have a label the Verify Books screen can show;
    * through the real endpoint and the real sweep on the in-memory database, a disposed asset with a live disposal entry and an
      asset with an acquisition entry are clean, and each broken shape is reported.
"""
from __future__ import annotations

import pytest

from domain.accounting import journal_source as JS
from domain.fixed_assets import integrity
from domain.fixed_assets.integrity import LedgerLinks
from services import fixed_asset_ledger_links as links
from services import reconciliation_service as rs
from tests.e2e_harness import FakeDB

FIRM, CLIENT, OTHER_CLIENT = "firm-1", "client-1", "client-2"


def _asset(asset_id="a1", **over):
    row = {"id": asset_id, "asset_code": f"FA-{asset_id}", "asset_name": "Lathe", "purchase_cost_paise": 100_000_00,
           "accumulated_depreciation_paise": 20_000_00, "salvage_value_paise": 0, "journal_entry_id": f"j-{asset_id}",
           "acquisition_mode": "direct", "purchase_bill_id": None, "is_disposed": False, "asset_category": "Land",
           "depreciation_method": "WDV", "wdv_rate_percent": None, "useful_life_years": None, "opening_position_date": None}
    row.update(over)
    return row


def _entry(entry_id, source_type, source_id, *, client=CLIENT, reversed_=False, reversal_of=None, deleted_at=None, ref=None):
    return {"id": entry_id, "firm_id": FIRM, "client_id": client, "source_type": source_type, "source_id": source_id,
            "reference_no": ref or f"FA-ACQ-{source_id}", "entry_date": "2026-04-01", "is_reversed": reversed_,
            "reversal_of": reversal_of, "deleted_at": deleted_at}


def _links(disposed=(), acquisitions=()):
    return LedgerLinks(frozenset(disposed), tuple(acquisitions))


# ── the two pure rules ──────────────────────────────────────────────────────────────────────────────

def test_a_disposed_asset_with_no_disposal_entry_is_reported_with_what_is_still_on_the_books():
    found = integrity.register_findings([_asset(is_disposed=True)], live_bill_ids=set(), ledger=_links())
    (finding,) = [f for f in found if f["kind"] == "disposed_asset_has_no_disposal_journal"]
    assert finding["asset_code"] == "FA-a1" and finding["amount_paise"] == 80_000_00
    assert "no gain or loss" in finding["what_it_means"]


def test_a_disposed_asset_with_a_disposal_entry_and_an_undisposed_asset_are_clean():
    assert integrity.register_findings([_asset(is_disposed=True)], set(), ledger=_links(disposed={"a1"})) == []
    assert integrity.register_findings([_asset()], set(), ledger=_links()) == []


def test_an_acquisition_entry_with_no_asset_is_reported_and_one_with_an_asset_is_not():
    journals = ({"id": "j9", "source_id": "gone", "reference_no": "FA-ACQ-FA-9", "entry_date": "2026-04-01"},
                {"id": "j1", "source_id": "a1", "reference_no": "FA-ACQ-FA-a1", "entry_date": "2026-04-01"})
    found = integrity.register_findings([_asset()], set(), ledger=_links(acquisitions=journals))
    (finding,) = found
    assert finding["kind"] == "acquisition_journal_has_no_asset" and finding["journal_entry_id"] == "j9"
    assert "FA-ACQ-FA-9" in finding["what_it_means"] and "nothing behind it" in finding["what_it_means"]


def test_without_ledger_links_neither_ledger_check_is_asked():
    """A caller that could not read the ledger passes none, and gets none of the two: not a false 'every disposed asset is missing
    its entry'."""
    assert integrity.register_findings([_asset(is_disposed=True)], live_bill_ids=set()) == []


def test_both_kinds_are_declared():
    assert {"disposed_asset_has_no_disposal_journal", "acquisition_journal_has_no_asset"} <= set(integrity.ALL_KINDS)


# ── the fetch ───────────────────────────────────────────────────────────────────────────────────────

def _book():
    db = FakeDB()
    for e in (
        _entry("d-live", JS.ASSET_DISPOSAL, "a1", ref="FA-DISP-FA-a1"),
        _entry("d-reversed", JS.ASSET_DISPOSAL, "a2", reversed_=True, ref="FA-DISP-FA-a2"),
        _entry("d-reversal", JS.ASSET_DISPOSAL, "a3", reversal_of="d-x", ref="REV-FA-DISP-FA-a3"),
        _entry("d-deleted", JS.ASSET_DISPOSAL, "a4", deleted_at="2026-05-01T00:00:00Z", ref="FA-DISP-FA-a4"),
        _entry("d-other-client", JS.ASSET_DISPOSAL, "a5", client=OTHER_CLIENT, ref="FA-DISP-FA-a5"),
        _entry("q-live", JS.FIXED_ASSET, "a1"),
        _entry("q-orphan", JS.FIXED_ASSET, "ghost"),
        _entry("q-reversed", JS.FIXED_ASSET, "old", reversed_=True),
        _entry("q-reversal", JS.FIXED_ASSET, "old", reversal_of="q-reversed", ref="REV-FA-ACQ-old"),
        _entry("q-other-client", JS.FIXED_ASSET, "elsewhere", client=OTHER_CLIENT),
        _entry("dep", JS.DEPRECIATION, "a1", ref="FA-DEP-FA-a1-2026-04"),
    ):
        db.seed("journal_entries", e)
    return db


def test_only_live_entries_of_this_client_and_this_source_count():
    assets = [_asset("a1", is_disposed=True), _asset("a2", is_disposed=True), _asset("a3", is_disposed=True),
              _asset("a4", is_disposed=True), _asset("a5", is_disposed=True), _asset("a6")]
    got = links.fetch_ledger_links(_book(), FIRM, CLIENT, assets)
    assert got.disposal_journalled_asset_ids == frozenset({"a1"})
    assert sorted(j["id"] for j in got.acquisition_journals) == ["q-live", "q-orphan"]


def test_a_disposal_is_read_for_the_disposed_assets_only():
    db = _book()
    queried = []
    real = db.table

    def spy(name):
        query = real(name)
        original = query.in_

        def in_(col, vals):
            queried.append((name, col, sorted(vals)))
            return original(col, vals)
        query.in_ = in_
        return query
    db.table = spy
    links.fetch_ledger_links(db, FIRM, CLIENT, [_asset("a1", is_disposed=True), _asset("a6")])
    assert queried == [("journal_entries", "source_id", ["a1"])]
    queried.clear()
    got = links.fetch_ledger_links(db, FIRM, CLIENT, [_asset("a6")])
    assert queried == [] and got.disposal_journalled_asset_ids == frozenset()


# ── the two readers hand the rule the same fetch ───────────────────────────────────────────────────

def _register(db):
    for row in (_asset("a1", is_disposed=True),                       # disposed WITH a live disposal entry
                _asset("a2", is_disposed=True),                       # disposed, its disposal was reversed
                _asset("a6")):
        db.seed("fixed_assets", {**row, "firm_id": FIRM, "client_id": CLIENT, "deleted_at": None})


def test_the_sweep_files_both_as_critical_and_reports_each_broken_shape():
    db = _book()
    _register(db)
    out = rs.check_fixed_asset_register(db, FIRM, CLIENT, entries={})
    by_kind = {f["check_name"].split(".", 1)[1]: f for f in out if f["check_name"].startswith("fixed_asset_register.")}
    assert set(by_kind) == {"disposed_asset_has_no_disposal_journal", "acquisition_journal_has_no_asset"}, sorted(by_kind)
    assert {f["severity"] for f in by_kind.values()} == {"critical"}
    assert "FA-a2" in by_kind["disposed_asset_has_no_disposal_journal"]["summary"]
    assert "FA-ACQ-ghost" in by_kind["acquisition_journal_has_no_asset"]["summary"]


def test_the_endpoint_reports_the_same_two():
    import routers.fixed_assets as fa
    db = _book()
    _register(db)
    rows = fa._register_rows(db, FIRM, CLIENT)
    found = integrity.register_findings(rows, fa._live_bill_ids(db, FIRM, rows),
                                        ledger=links.fetch_ledger_links(db, FIRM, CLIENT, rows))
    assert sorted(f["kind"] for f in found) == ["acquisition_journal_has_no_asset", "disposed_asset_has_no_disposal_journal"]


def test_both_readers_call_the_one_fetch_and_hand_it_to_the_rule():
    import inspect

    import routers.fixed_assets as fa
    for fn in (fa.register_integrity, rs.check_fixed_asset_register):
        source = inspect.getsource(fn)
        assert "fetch_ledger_links(" in source and "ledger=" in source, fn.__name__


@pytest.mark.parametrize("kind", ["disposed_asset_has_no_disposal_journal", "acquisition_journal_has_no_asset"])
def test_each_kind_has_a_label_on_the_verify_books_screen(kind):
    entry = rs.CHECK_CATALOGUE[f"fixed_asset_register.{kind}"]
    assert entry["label"] and entry["looks_for"]
