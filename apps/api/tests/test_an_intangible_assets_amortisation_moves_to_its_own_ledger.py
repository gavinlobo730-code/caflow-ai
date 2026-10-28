"""An intangible asset's accumulated amortisation moves from the shared Accumulated Depreciation ledger into the Accumulated Amortisation
ledger, by a Partner's posting, and every later journal of the asset follows it (POST-A-345, stage 3 of 3).

WHY IT EXISTS
    Schedule III presents tangible and intangible assets on separate lines, each net of its own accumulated depreciation or
    amortisation. The product credited every asset's depreciation to ONE ledger on the tangible line, so a company with a licence or
    software on the intangible line had the tangible line understated and the intangible line overstated by the same amount. Stages 1
    and 2 gave an asset a pointer to the ledger its figure is kept in and one function both journals ask. This stage writes it.

WHAT IS HELD, through the real services on a fake database holding the standard chart
    * a new intangible asset is BORN pointing at its own ledger, a tangible one is not, and a category change before anything is posted
      re-decides it (and is refused once the asset carries accumulated depreciation);
    * the preview writes nothing and says what would move; the post moves each asset by compare-and-set claim, then one journal per
      tranche, and afterwards the asset's depreciation credits, and its disposal debits, the new ledger and nothing else;
    * the figures TIE: the new ledger holds exactly what the register says, the shared ledger lost exactly that, the books balance;
    * the refusals: a shared ledger holding less than would leave it, an unexplained credit in the new ledger, a closed year, an asset
      that changed after it was previewed, a total that moved, an unreadable balance; and a failing journal leaves the asset where it was;
    * the undo, and when it is refused; the generic journal reversal refuses these entries; a depreciation month posted before the move
      cannot be reversed against the wrong ledger;
    * the register-integrity findings say it before the move and stop once it is done.
"""
from __future__ import annotations

import pathlib
import re

import pytest
from fastapi import HTTPException

import routers.accounting as acct
import routers.fixed_assets as fa
from domain.accounting.journal_source import AMORTISATION_RECLASS
from models.accounting import DepreciationIn, DisposalIn, FixedAssetIn, FixedAssetUpdateIn, JournalReversalIn
from services import amortisation_reclass_service as arcs
from services.coa_seed_service import STANDARD_COA
from tests.e2e_harness import FakeDB, wire_e2e

FIRM, CLIENT = "FIRM-AR", "CLI-AR"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}
SHARED, OWN, COST_LEDGER = "acct-1590", "acct-1591", "acct-1506"
AS_AT = "2025-09-30"


# ── the practice ────────────────────────────────────────────────────────────

def _firm(monkeypatch) -> FakeDB:
    db = FakeDB()
    wire_e2e(monkeypatch, db, [fa, acct])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("firms", {"id": FIRM, "name": "Amort & Co", "locked_financial_years": []})
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM, "financial_year_start": "2025-04-01"})
    for code, name, account_type, subtype in STANDARD_COA:
        db.seed("chart_of_accounts", {
            "id": f"acct-{code}", "firm_id": FIRM, "client_id": None, "account_code": code, "account_name": name,
            "account_type": account_type, "account_subtype": subtype, "is_active": True, "system_account_key": None})
    return db


def _create(db, name="Licence", category="Intangibles", cost=1_20_000_00, life=5, method="SL", date="2025-04-05"):
    res = fa.create_asset(FixedAssetIn(
        client_id=CLIENT, asset_name=name, asset_category=category, purchase_date=date, purchase_cost_paise=cost,
        depreciation_method=method, useful_life_years=life, acquisition_mode="paid"), CALLER)
    assert res["success"] is True, res
    return next(r for r in db.rows("fixed_assets") if r["id"] == res["data"]["id"])


def _legacy(db, months=("2025-04", "2025-05", "2025-06"), **kw):
    """An intangible asset as every one in production is today: no pointer, its depreciation in the shared ledger."""
    row = _create(db, **kw)
    row["accumulated_account_id"] = None
    for period in months:
        assert fa.post_depreciation(row["id"], DepreciationIn(period=period), CALLER)["success"]
    return row


def _sync_balances(db: FakeDB) -> None:
    """The pre-aggregated monthly rows the preview reads, rebuilt from the lines (what the database's triggers do)."""
    db._tables["account_period_balances"] = []
    entries = {e["id"]: e for e in db.rows("journal_entries")}
    sums: dict = {}
    for ln in db.rows("journal_lines"):
        e = entries.get(ln["journal_entry_id"])
        if not e:
            continue
        key = (e.get("client_id"), ln["account_id"], str(e["entry_date"])[:7] + "-01")
        d, c = sums.get(key, (0, 0))
        sums[key] = (d + int(ln.get("debit_paise") or 0), c + int(ln.get("credit_paise") or 0))
    for (client, account_id, month), (d, c) in sums.items():
        db.seed("account_period_balances", {"firm_id": FIRM, "client_id": client, "account_id": account_id, "period_month": month,
                                            "debit_paise": d, "credit_paise": c})


def _stamp(db: FakeDB) -> None:
    """`journal_entries.created_at` is `DEFAULT now()` in Postgres and the in-memory double does not supply it. The undo orders by it
    (a depreciation posted AFTER the reclassification), so give every entry without one the next instant, in insertion order."""
    n = sum(1 for e in db.rows("journal_entries") if e.get("created_at"))
    for e in db.rows("journal_entries"):
        if not e.get("created_at"):
            n += 1
            e["created_at"] = f"2026-10-27T05:00:{n // 60:02d}.{n % 60:06d}+00:00"


def _credit_as_at(db, account_id, day) -> int:
    """A ledger's credit balance AS AT a date, from its lines (what a balance sheet cut that day would show)."""
    entries = {e["id"]: e for e in db.rows("journal_entries")}
    return sum(int(l.get("credit_paise") or 0) - int(l.get("debit_paise") or 0) for l in db.rows("journal_lines")
               if l["account_id"] == account_id and entries[l["journal_entry_id"]].get("client_id") == CLIENT
               and str(entries[l["journal_entry_id"]]["entry_date"])[:10] <= day)


def _credit(db, account_id) -> int:
    entries = {e["id"]: e for e in db.rows("journal_entries")}
    return sum(int(l.get("credit_paise") or 0) - int(l.get("debit_paise") or 0) for l in db.rows("journal_lines")
               if l["account_id"] == account_id and entries[l["journal_entry_id"]].get("client_id") == CLIENT)


def _preview(db, as_at=AS_AT, carried=None):
    _sync_balances(db)
    return arcs.preview(db, FIRM, CLIENT, as_at, carried)


def _post(db, row_ids, total, as_at=AS_AT, carried=None):
    _sync_balances(db)
    return arcs.post(db, FIRM, CLIENT, as_at, row_ids, total, carried, CALLER)


def _live(db):
    """The live reclassification entries: not reversed, not themselves a reversal."""
    return [e for e in _entries(db) if not e.get("is_reversed") and not e.get("reversal_of")]


def _entries(db, source=AMORTISATION_RECLASS):
    return [e for e in db.rows("journal_entries") if e.get("source_type") == source]


# ── where an asset is born ──────────────────────────────────────────────────

def test_a_new_intangible_asset_is_born_pointing_at_its_own_ledger_and_a_tangible_one_is_not(monkeypatch):
    db = _firm(monkeypatch)
    assert _create(db)["accumulated_account_id"] == OWN
    plant = _create(db, name="Lathe", category="Plant & Machinery", life=15, method="WDV")
    assert not plant.get("accumulated_account_id")


def test_a_chart_with_no_amortisation_ledger_leaves_a_new_asset_where_every_asset_has_always_been(monkeypatch):
    db = _firm(monkeypatch)
    db._tables["chart_of_accounts"] = [r for r in db.rows("chart_of_accounts") if r["id"] != OWN]
    assert not _create(db).get("accumulated_account_id")


def test_a_cost_ledger_on_the_tangible_line_keeps_the_asset_in_the_shared_ledger(monkeypatch):
    """A chart whose Intangible Assets ledger is a Fixed Asset (migration 093's older chart) must not split cost from amortisation."""
    db = _firm(monkeypatch)
    next(r for r in db.rows("chart_of_accounts") if r["id"] == COST_LEDGER)["account_subtype"] = "Fixed Asset"
    assert not _create(db).get("accumulated_account_id")


def test_the_born_asset_depreciates_into_its_own_ledger_and_disposes_out_of_it(monkeypatch):
    db = _firm(monkeypatch)
    row = _create(db)
    for period in ("2025-04", "2025-05"):
        assert fa.post_depreciation(row["id"], DepreciationIn(period=period), CALLER)["success"]
    _sync_balances(db)
    assert _credit(db, OWN) == row["accumulated_depreciation_paise"] > 0 and _credit(db, SHARED) == 0
    fa.dispose_asset(row["id"], DisposalIn(disposal_date="2025-05-31", sale_proceeds_paise=50_000_00, disposal_type="Sale"), CALLER)
    assert _credit(db, OWN) == 0 and _credit(db, SHARED) == 0, "the disposal cleared the ledger the asset points at"


def test_a_category_change_before_anything_is_posted_re_decides_the_ledger_and_after_it_is_refused(monkeypatch):
    db = _firm(monkeypatch)
    row = _create(db, name="Lathe", category="Plant & Machinery", life=15, method="WDV")
    assert not row.get("accumulated_account_id")
    fa.correct_asset(row["id"], FixedAssetUpdateIn(asset_category="Intangibles"), CALLER)
    assert row["accumulated_account_id"] == OWN
    fa.correct_asset(row["id"], FixedAssetUpdateIn(asset_category="Plant & Machinery"), CALLER)
    assert not row.get("accumulated_account_id")
    row["accumulated_depreciation_paise"] = 5_00
    with pytest.raises(HTTPException) as exc:
        fa.correct_asset(row["id"], FixedAssetUpdateIn(asset_category="Intangibles"), CALLER)
    assert exc.value.status_code == 422 and "carries accumulated depreciation" in exc.value.detail
    assert not row.get("accumulated_account_id")


def _chart_for_cwip(db) -> None:
    """The standard chart is firm-level in `_firm`; a work-in-progress capitalisation reads the same chart."""
    assert any(r["id"] == OWN for r in db.rows("chart_of_accounts"))


def _capitalise(db, category):
    from services import cwip_service
    db.seed("capital_work_in_progress", {"id": "p1", "firm_id": FIRM, "client_id": CLIENT, "project_code": "CWIP-1", "project_name": "Build",
                                         "asset_category": category, "status": "in_progress", "started_on": "2025-04-01",
                                         "approved_cost_paise": 1_00_000_00})
    db.seed("cwip_additions", {"id": "ad1", "firm_id": FIRM, "client_id": CLIENT, "cwip_id": "p1", "amount_paise": 1_00_000_00,
                               "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "itc_eligible": True, "incurred_on": "2025-05-01"})
    out = cwip_service.capitalise(db, firm_id=FIRM, client_id=CLIENT, cwip_id="p1", put_to_use_date="2025-06-01",
                                  useful_life_years=5, depreciation_method="SL")
    assert out["ok"] is True, out
    return db.rows("fixed_assets")[-1]


def test_work_in_progress_capitalised_into_the_intangible_line_is_born_in_its_own_ledger_and_a_tangible_one_is_not(monkeypatch):
    db = _firm(monkeypatch)
    _chart_for_cwip(db)
    assert _capitalise(db, "Intangibles")["accumulated_account_id"] == OWN
    db2 = _firm(monkeypatch)
    assert not _capitalise(db2, "Plant & Machinery").get("accumulated_account_id")


def test_a_disposal_that_loses_the_race_with_a_reclassification_misses_its_claim_and_clears_nothing(monkeypatch):
    """The copy of the asset the disposal read says the shared ledger; the row has since been moved. The claim names the pointer it read."""
    db = _firm(monkeypatch)
    row = _legacy(db, months=("2025-04", "2025-05", "2025-06"))
    stale = dict(row)                                           # what the disposal read before the reclassification committed
    row["accumulated_account_id"] = OWN
    monkeypatch.setattr(fa, "_live_asset", lambda db_, asset_id, firm_id: stale)
    entries_before = len(db.rows("journal_entries"))
    with pytest.raises(HTTPException) as exc:
        fa.dispose_asset(row["id"], DisposalIn(disposal_date="2025-06-30", sale_proceeds_paise=50_000_00, disposal_type="Sale"), CALLER)
    assert exc.value.status_code == 409 and "ledger changed" in exc.value.detail
    assert row["is_disposed"] is False and len(db.rows("journal_entries")) == entries_before


# ── the preview ─────────────────────────────────────────────────────────────

def test_the_preview_names_what_would_move_and_writes_nothing(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    entries_before, pointer_before = len(db.rows("journal_entries")), row.get("accumulated_account_id")
    out = _preview(db)
    assert out["ready"] is True and out["refusals"] == []
    assert [a["asset_id"] for a in out["assets"]] == [row["id"]]
    a = out["assets"][0]
    assert a["register_paise"] == row["accumulated_depreciation_paise"] > 0
    assert a["carried_over_paise"] == 0 and a["moves_later_paise"] == 0 and out["later_dates"] == []
    assert a["moves_as_at_paise"] == out["total_to_move_paise"] == row["accumulated_depreciation_paise"]
    assert out["own_ledger"]["id"] == OWN and out["shared_ledger"]["id"] == SHARED
    assert out["financial_years"][-1]["fixed"] is False, "an earlier balance sheet keeps its split, and the screen says so"
    assert "30 Sep 2025 and every later one" in out["financial_years"][0]["note"]
    assert not any(k.startswith("_") for k in out)
    assert len(db.rows("journal_entries")) == entries_before and row.get("accumulated_account_id") == pointer_before


def test_the_preview_tells_a_moved_asset_from_one_created_in_its_own_ledger_so_only_the_first_is_offered_an_undo(monkeypatch):
    db = _firm(monkeypatch)
    moved = _legacy(db, name="Old licence")
    born = _create(db, name="New licence")
    _post(db, [moved["id"]], moved["accumulated_depreciation_paise"])
    out = _preview(db)
    flags = {r["asset_id"]: r["moved_by_reclassification"] for r in out["reclassified"]}
    assert flags == {moved["id"]: True, born["id"]: False}


def test_a_tangible_asset_is_neither_moved_nor_listed(monkeypatch):
    db = _firm(monkeypatch)
    plant = _create(db, name="Lathe", category="Plant & Machinery", life=15, method="WDV")
    fa.post_depreciation(plant["id"], DepreciationIn(period="2025-04"), CALLER)
    legacy = _legacy(db)
    out = _preview(db)
    assert [a["asset_id"] for a in out["assets"]] == [legacy["id"]] and out["excluded"] == []


def test_a_date_in_the_future_or_a_malformed_one_is_refused_in_words(monkeypatch):
    db = _firm(monkeypatch)
    _legacy(db)
    for bad in ("2999-01-01", "31-03-2026", "", "2025-09-30T23:00:00Z"):
        with pytest.raises(HTTPException) as exc:
            _preview(db, as_at=bad)
        assert exc.value.status_code == 422 and "as at" in exc.value.detail


# ── the post ────────────────────────────────────────────────────────────────

def test_posting_moves_the_register_figure_between_the_ledgers_and_points_the_asset(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    register = row["accumulated_depreciation_paise"]
    _sync_balances(db)
    assert _credit(db, SHARED) == register and _credit(db, OWN) == 0
    out = _post(db, [row["id"]], register)
    assert out["failed"] == [] and out["skipped"] == [] and out["total_moved_paise"] == register
    _sync_balances(db)
    assert _credit(db, OWN) == register and _credit(db, SHARED) == 0
    assert row["accumulated_account_id"] == OWN
    entry = _entries(db)
    assert len(entry) == 1 and entry[0]["source_id"] == row["id"] and entry[0]["reference_no"] == "FA-AMORT-RECLASS-FA-0001"
    assert str(entry[0]["entry_date"])[:10] == AS_AT
    assert sum(int(l["debit_paise"]) for l in db.rows("journal_lines")) == sum(int(l["credit_paise"]) for l in db.rows("journal_lines"))


def test_after_the_move_depreciation_credits_and_a_disposal_debits_the_new_ledger_and_the_figures_still_tie(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db, months=("2025-04", "2025-05", "2025-06", "2025-07", "2025-08"))
    _post(db, [row["id"]], row["accumulated_depreciation_paise"], as_at="2025-08-31")
    assert fa.post_depreciation(row["id"], DepreciationIn(period="2025-09"), CALLER)["success"]
    _sync_balances(db)
    assert _credit(db, OWN) == row["accumulated_depreciation_paise"] and _credit(db, SHARED) == 0
    fa.dispose_asset(row["id"], DisposalIn(disposal_date="2025-09-30", sale_proceeds_paise=50_000_00, disposal_type="Sale"), CALLER)
    _sync_balances(db)
    assert _credit(db, OWN) == 0 and _credit(db, SHARED) == 0


def test_months_posted_after_the_stated_date_move_in_an_entry_dated_the_end_of_their_financial_year(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db, months=("2025-04", "2025-05", "2025-06", "2025-07", "2025-08"))
    register = row["accumulated_depreciation_paise"]
    out = _preview(db, as_at="2025-05-31")
    a = out["assets"][0]
    assert a["moves_as_at_paise"] > 0 and a["moves_later_paise"] > 0 and a["moves_as_at_paise"] + a["moves_later_paise"] == register
    assert out["later_dates"] == ["2026-03-31"], "June to August 2025 fall in FY 2025-26, whose year end is 31 March 2026"
    assert "31 Mar 2026" in out["financial_years"][0]["note"] and "another date between these" in out["financial_years"][1]["note"]
    _post(db, [row["id"]], register, as_at="2025-05-31")
    entries = sorted(_entries(db), key=lambda e: e["reference_no"])
    assert [(e["reference_no"], str(e["entry_date"])[:10]) for e in entries] == [
        ("FA-AMORT-RECLASS-FA-0001", "2025-05-31"), ("FA-AMORT-RECLASS-FA-0001-T2", "2026-03-31")]
    _sync_balances(db)
    assert _credit(db, OWN) == register and _credit(db, SHARED) == 0


def test_every_year_end_balance_sheet_from_the_stated_date_is_exact_and_a_date_between_is_said_to_be_partial(monkeypatch):
    """The defect a reviewer reproduced: with the second entry dated TODAY, the balance sheet at 31 March 2026 still showed the months
    posted after the stated date in the tangible ledger while the screen said it was fixed. Read as at a date, not all-time."""
    db = _firm(monkeypatch)
    monkeypatch.setattr(arcs, "ist_today", lambda: __import__("datetime").date(2026, 10, 27))
    row = _create(db, date="2024-04-05")
    row["accumulated_account_id"] = None
    months = [f"{y}-{m:02d}" for y, m in [(2024, m) for m in range(4, 13)] + [(2025, m) for m in range(1, 13)] + [(2026, m) for m in range(1, 7)]]
    for period in months:
        assert fa.post_depreciation(row["id"], DepreciationIn(period=period), CALLER)["success"]
    depreciation = [e for e in db.rows("journal_entries") if e.get("source_type") == "depreciation"]

    def amortised_to(day):
        ids = {e["id"] for e in depreciation if str(e["entry_date"])[:10] <= day}
        return sum(int(l["credit_paise"]) for l in db.rows("journal_lines") if l["journal_entry_id"] in ids and l["account_id"] == SHARED)

    out = _preview(db, as_at="2025-03-31")
    assert out["ready"] is True and out["later_dates"] == ["2026-03-31", "2026-10-27"]
    _post(db, [row["id"]], row["accumulated_depreciation_paise"], as_at="2025-03-31")
    assert [(e["reference_no"].split("FA-0001")[1], str(e["entry_date"])[:10]) for e in sorted(_entries(db), key=lambda e: str(e["entry_date"]))] == [
        ("", "2025-03-31"), ("-T2", "2026-03-31"), ("-T3", "2026-10-27")]
    for day in ("2025-03-31", "2026-03-31", "2026-10-27"):                 # the two year ends and today
        assert _credit_as_at(db, OWN, day) == amortised_to(day) > 0, day
        assert _credit_as_at(db, SHARED, day) == 0, f"the tangible contra still holds the licence at {day}"
    # between the stated date and the next year end, the months posted since are still in the old ledger: said, not hidden
    assert _credit_as_at(db, OWN, "2025-12-31") == amortised_to("2025-03-31")
    assert _credit_as_at(db, SHARED, "2025-12-31") == amortised_to("2025-12-31") - amortised_to("2025-03-31") > 0


def test_a_date_that_is_not_a_month_end_is_refused_in_words_before_anything_is_read(monkeypatch):
    db = _firm(monkeypatch)
    _legacy(db)
    with pytest.raises(HTTPException) as exc:
        _preview(db, as_at="2025-09-15")
    assert exc.value.status_code == 422 and "month end" in exc.value.detail


def test_depreciation_the_asset_brought_over_with_it_comes_from_the_ledger_the_partner_names(monkeypatch):
    """The register says more than the asset's own journals put in the shared ledger: the rest was carried over, and only the person
    posting can say where it sits. Left in the shared ledger it would be wrong; named, it moves from there."""
    db = _firm(monkeypatch)
    row = _legacy(db)
    own_journals = row["accumulated_depreciation_paise"]
    row["accumulated_depreciation_paise"] = own_journals + 10_000_00       # 10,000 carried over from the old books
    db.seed("chart_of_accounts", {"id": "acct-tb", "firm_id": FIRM, "client_id": CLIENT, "account_code": "1700",
                                  "account_name": "Accumulated Dep - Software (imported)", "account_type": "Asset",
                                  "account_subtype": "Fixed Asset", "is_active": True})
    # the imported trial balance put the carried-over credit there
    db.seed("journal_entries", {"id": "je-tb", "firm_id": FIRM, "client_id": CLIENT, "entry_date": "2025-04-01", "reference_no": "TB-1",
                                "is_reversed": False, "source_type": "TrialBalance"})
    db.seed("journal_lines", {"id": "jl-tb1", "journal_entry_id": "je-tb", "account_id": "acct-tb", "debit_paise": 0,
                              "credit_paise": 10_000_00})
    db.seed("journal_lines", {"id": "jl-tb2", "journal_entry_id": "je-tb", "account_id": "acct-1000", "debit_paise": 10_000_00,
                              "credit_paise": 0})
    # left in the shared ledger the batch is refused: that ledger holds only what the asset's own journals put there
    refused = _preview(db)
    assert refused["ready"] is False and any("shared Accumulated Depreciation ledger holds" in r for r in refused["refusals"])
    named = _preview(db, carried="acct-tb")
    assert named["ready"] is True and named["assets"][0]["carried_over_paise"] == 10_000_00
    assert named["carried_over_ledger"]["id"] == "acct-tb"
    out = _post(db, [row["id"]], own_journals + 10_000_00, carried="acct-tb")
    assert out["failed"] == [] and out["total_moved_paise"] == own_journals + 10_000_00
    _sync_balances(db)
    assert _credit(db, OWN) == own_journals + 10_000_00 and _credit(db, SHARED) == 0 and _credit(db, "acct-tb") == 0


def test_an_asset_with_nothing_depreciated_is_only_pointed(monkeypatch):
    db = _firm(monkeypatch)
    row = _create(db)
    row["accumulated_account_id"] = None
    out = _post(db, [row["id"]], 0)
    assert out["moved"][0]["moved_paise"] == 0 and row["accumulated_account_id"] == OWN
    assert _entries(db) == [], "nothing to move, so no journal"


# ── the refusals ────────────────────────────────────────────────────────────

def test_a_shared_ledger_holding_less_than_would_leave_it_refuses_and_posts_nothing(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    # an unrelated tangible asset's depreciation is in there too; take the ledger below what the licence needs
    db.seed("journal_entries", {"id": "je-x", "firm_id": FIRM, "client_id": CLIENT, "entry_date": "2025-06-30", "reference_no": "X",
                                "is_reversed": False, "source_type": "Journal"})
    db.seed("journal_lines", {"id": "jl-x", "journal_entry_id": "je-x", "account_id": SHARED, "debit_paise": 1_00, "credit_paise": 0})
    db.seed("journal_lines", {"id": "jl-y", "journal_entry_id": "je-x", "account_id": "acct-1000", "debit_paise": 0, "credit_paise": 1_00})
    entries_before = len(db.rows("journal_entries"))
    with pytest.raises(HTTPException) as exc:
        _post(db, [row["id"]], row["accumulated_depreciation_paise"])
    assert exc.value.status_code == 422 and "debit balance" in exc.value.detail
    assert len(db.rows("journal_entries")) == entries_before and not row.get("accumulated_account_id")


def test_a_credit_in_the_new_ledger_that_no_asset_explains_refuses(monkeypatch):
    db = _firm(monkeypatch)
    _legacy(db)
    db.seed("journal_entries", {"id": "je-tb", "firm_id": FIRM, "client_id": CLIENT, "entry_date": "2025-04-01", "reference_no": "TB-1",
                                "is_reversed": False, "source_type": "TrialBalance"})
    db.seed("journal_lines", {"id": "jl-1", "journal_entry_id": "je-tb", "account_id": OWN, "debit_paise": 0, "credit_paise": 7_00})
    db.seed("journal_lines", {"id": "jl-2", "journal_entry_id": "je-tb", "account_id": "acct-1000", "debit_paise": 7_00, "credit_paise": 0})
    out = _preview(db)
    assert out["ready"] is False and any("already carries" in r and "nothing is netted" in r for r in out["refusals"])


def test_a_closed_year_refuses_in_the_closures_own_words(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    next(f for f in db.rows("firms") if f["id"] == FIRM)["locked_financial_years"] = ["2025-26"]
    out = _preview(db)
    assert out["ready"] is False and out["refusals"], out
    with pytest.raises(HTTPException) as exc:
        _post(db, [row["id"]], row["accumulated_depreciation_paise"])
    assert exc.value.status_code == 422 and not row.get("accumulated_account_id")


def test_a_balance_that_cannot_be_read_refuses_rather_than_posting_blind(monkeypatch):
    db = _firm(monkeypatch)
    _legacy(db)
    _sync_balances(db)
    import services.fixed_asset_accumulated_ledger as fal
    monkeypatch.setattr(fal, "fetch_all", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")), raising=True)
    out = arcs.preview(db, FIRM, CLIENT, AS_AT, None)
    assert out["ready"] is False and any("could not be read" in r for r in out["refusals"])


def test_a_total_that_moved_since_the_preview_is_a_409_and_posts_nothing(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    entries_before = len(db.rows("journal_entries"))
    with pytest.raises(HTTPException) as exc:
        _post(db, [row["id"]], row["accumulated_depreciation_paise"] - 1)
    assert exc.value.status_code == 409 and "changed since you looked" in exc.value.detail
    assert len(db.rows("journal_entries")) == entries_before


def test_an_asset_not_in_the_preview_is_a_409(monkeypatch):
    db = _firm(monkeypatch)
    _legacy(db)
    with pytest.raises(HTTPException) as exc:
        _post(db, ["no-such-asset"], 0)
    assert exc.value.status_code == 409 and "no-such-asset" in exc.value.detail


def test_an_asset_that_changed_after_it_was_previewed_is_skipped_by_name_and_claims_nothing(monkeypatch):
    """Two Partners, or a depreciation posted between the preview and the claim: the compare-and-set finds the row moved."""
    db = _firm(monkeypatch)
    row = _legacy(db)
    real_claim = arcs._claim

    def claim_after_a_depreciation_landed(db_, firm, client, plan, own_id):
        row["accumulated_depreciation_paise"] += 1_00
        return real_claim(db_, firm, client, plan, own_id)

    monkeypatch.setattr(arcs, "_claim", claim_after_a_depreciation_landed)
    entries_before = len(db.rows("journal_entries"))
    out = _post(db, [row["id"]], row["accumulated_depreciation_paise"])
    assert out["moved"] == [] and [s["asset_code"] for s in out["skipped"]] == ["FA-0001"] and "changed since you looked" in out["skipped"][0]["reason"]
    assert not row.get("accumulated_account_id") and len(db.rows("journal_entries")) == entries_before


def test_two_posts_of_the_same_asset_claim_it_once(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    first = _post(db, [row["id"]], row["accumulated_depreciation_paise"])
    assert first["total_moved_paise"] > 0
    with pytest.raises(HTTPException) as exc:                      # the second finds nothing left to move: the asset is no longer in the plan
        _post(db, [row["id"]], row["accumulated_depreciation_paise"])
    assert exc.value.status_code == 409 and len(_entries(db)) == 1


def test_a_journal_that_fails_leaves_the_asset_where_it_was_and_the_others_still_move(monkeypatch):
    db = _firm(monkeypatch)
    bad = _legacy(db, name="Software")
    good = _create(db, name="Licence B")
    good["accumulated_account_id"] = None
    for period in ("2025-04", "2025-05"):
        fa.post_depreciation(good["id"], DepreciationIn(period=period), CALLER)
    from services.phase2_journal_service import phase2_journal_service as svc
    real = svc.journal_for_amortisation_reclass

    def failing_for_one_asset(asset, **kw):
        if asset["id"] == bad["id"]:
            raise ValueError("the ledger said no")
        return real(asset, **kw)

    monkeypatch.setattr(svc, "journal_for_amortisation_reclass", failing_for_one_asset)
    out = _post(db, [bad["id"], good["id"]], bad["accumulated_depreciation_paise"] + good["accumulated_depreciation_paise"])
    assert [f["asset_id"] for f in out["failed"]] == [bad["id"]] and "the ledger said no" in out["failed"][0]["reason"]
    assert [m["asset_id"] for m in out["moved"]] == [good["id"]]
    assert not bad.get("accumulated_account_id"), "the claim is undone so the asset can be tried again"
    assert good["accumulated_account_id"] == OWN


def test_a_second_tranche_that_fails_reverses_the_first_and_undoes_the_claim(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db, months=("2025-04", "2025-05", "2025-06", "2025-07"))
    from services.phase2_journal_service import phase2_journal_service as svc
    real = svc.journal_for_amortisation_reclass

    def second_tranche_fails(asset, **kw):
        if kw["tranche"] == 2:
            raise ValueError("closed")
        return real(asset, **kw)

    monkeypatch.setattr(svc, "journal_for_amortisation_reclass", second_tranche_fails)
    out = _post(db, [row["id"]], row["accumulated_depreciation_paise"], as_at="2025-05-31")
    assert len(out["failed"]) == 1 and out["moved"] == [] and not row.get("accumulated_account_id")
    _sync_balances(db)
    assert _credit(db, OWN) == 0 and _credit(db, SHARED) == row["accumulated_depreciation_paise"], "the first tranche was reversed"


# ── the undo ────────────────────────────────────────────────────────────────

def test_undo_puts_the_figures_and_the_pointer_back(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    _post(db, [row["id"]], row["accumulated_depreciation_paise"])
    _stamp(db)
    out = arcs.undo(db, FIRM, row["id"], CALLER)
    assert len(out["reversal_entry_ids"]) == 1 and not row.get("accumulated_account_id")
    _sync_balances(db)
    assert _credit(db, OWN) == 0 and _credit(db, SHARED) == row["accumulated_depreciation_paise"]


def test_undo_is_refused_once_depreciation_has_been_posted_on_the_new_ledger(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    _post(db, [row["id"]], row["accumulated_depreciation_paise"])
    _stamp(db)
    fa.post_depreciation(row["id"], DepreciationIn(period="2025-07"), CALLER)
    _stamp(db)
    with pytest.raises(HTTPException) as exc:
        arcs.undo(db, FIRM, row["id"], CALLER)
    assert exc.value.status_code == 409 and "since it was reclassified" in exc.value.detail
    assert row["accumulated_account_id"] == OWN


def test_undo_has_nothing_to_undo_for_an_asset_born_pointed_or_never_moved(monkeypatch):
    db = _firm(monkeypatch)
    born = _create(db)
    with pytest.raises(HTTPException) as exc:
        arcs.undo(db, FIRM, born["id"], CALLER)
    assert exc.value.status_code == 409 and "created pointing at its own ledger" in exc.value.detail
    legacy = _legacy(db, name="Old")
    with pytest.raises(HTTPException) as exc2:
        arcs.undo(db, FIRM, legacy["id"], CALLER)
    assert exc2.value.status_code == 409 and "nothing to undo" in exc2.value.detail


def test_the_generic_journal_reversal_refuses_these_entries_and_names_the_route_that_undoes_them(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    _post(db, [row["id"]], row["accumulated_depreciation_paise"])
    entry = _entries(db)[0]
    with pytest.raises(HTTPException) as exc:
        acct.reverse_journal_entry(entry["id"], JournalReversalIn(reversal_date="2025-10-01"), CALLER)
    assert exc.value.status_code == 422 and "Moved by a reclassification" in exc.value.detail
    assert "/api/" not in exc.value.detail, "a sentence for a chartered accountant names a screen, not a route"
    assert not entry.get("is_reversed") and row["accumulated_account_id"] == OWN


def test_a_month_posted_before_the_move_cannot_be_reversed_against_the_wrong_ledger(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db, months=("2025-04", "2025-05", "2025-06"))
    _post(db, [row["id"]], row["accumulated_depreciation_paise"])
    with pytest.raises(HTTPException) as exc:
        fa.reverse_depreciation(row["id"], "2025-06", CALLER)
    assert exc.value.status_code == 409 and "different ledger" in exc.value.detail
    fa.post_depreciation(row["id"], DepreciationIn(period="2025-07"), CALLER)
    assert fa.reverse_depreciation(row["id"], "2025-07", CALLER)["success"] is True, "a month posted after the move reverses normally"


def test_a_depreciation_that_loses_the_race_with_a_reclassification_undoes_itself(monkeypatch):
    """The pointer moved between the row being read and the register being updated: the month is not kept (409), its journal reversed."""
    db = _firm(monkeypatch)
    row = _legacy(db)
    real_post = fa.Phase2JournalService.journal_for_depreciation

    def posts_then_a_reclassification_commits(self, asset, *a, **k):
        entry = real_post(self, asset, *a, **k)
        row["accumulated_account_id"] = OWN                   # a Partner's claim lands while this month is being posted
        return entry

    monkeypatch.setattr(fa.Phase2JournalService, "journal_for_depreciation", posts_then_a_reclassification_commits)
    before = row["accumulated_depreciation_paise"]
    with pytest.raises(HTTPException) as exc:
        fa.post_depreciation(row["id"], DepreciationIn(period="2025-07"), CALLER)
    assert exc.value.status_code == 409 and "changed while" in exc.value.detail
    assert row["accumulated_depreciation_paise"] == before
    _sync_balances(db)
    assert _credit(db, SHARED) == before, "the month that raced was reversed, so the shared ledger is where it was"


# ── what a reviewer found: failure paths, races, and the edges of the rule ──────────────────────

def _two_entry_asset(db):
    """An asset whose move needs TWO entries (as at 31 May 2025, and the rest at 31 March 2026)."""
    return _legacy(db, months=("2025-04", "2025-05", "2025-06", "2025-07", "2025-08"))


def test_a_failed_second_entry_whose_reversal_also_fails_keeps_the_claim_and_reports_the_asset_as_partly_moved(monkeypatch):
    """The old code took the pointer back whatever happened to the reversal: a live entry, no pointer, and no route that could undo it."""
    db = _firm(monkeypatch)
    row = _two_entry_asset(db)
    register = row["accumulated_depreciation_paise"]
    from services.phase2_journal_service import phase2_journal_service as svc
    real_journal, real_reverse = svc.journal_for_amortisation_reclass, svc.reverse_entry

    def second_fails(asset, **kw):
        if kw["tranche"] == 2:
            raise ValueError("closed")
        return real_journal(asset, **kw)

    def reversal_fails(*a, **k):
        raise ValueError("the outage that stopped the second entry stops the reversal too")

    monkeypatch.setattr(svc, "journal_for_amortisation_reclass", second_fails)
    monkeypatch.setattr(svc, "reverse_entry", reversal_fails)
    out = _post(db, [row["id"]], register, as_at="2025-05-31")
    f = out["failed"][0]
    assert f["partly_moved"] is True and len(f["live_entry_ids"]) == 1 and "Undo" in f["reason"] and "closed" in f["reason"]
    assert row["accumulated_account_id"] == OWN, "the pointer stays: taking it back over a live entry is the half-in-each-ledger state"
    assert [e["id"] for e in _live(db)] == f["live_entry_ids"]
    # the undo, working from the ledger, finishes it
    monkeypatch.setattr(svc, "reverse_entry", real_reverse)
    done = arcs.undo(db, FIRM, row["id"], CALLER)
    assert len(done["reversal_entry_ids"]) == 1 and not row.get("accumulated_account_id") and _live(db) == []
    _sync_balances(db)
    assert _credit(db, OWN) == 0 and _credit(db, SHARED) == register


def test_a_journal_that_committed_but_whose_call_raised_is_found_in_the_ledger_and_reversed(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    from services.phase2_journal_service import phase2_journal_service as svc
    real = svc.journal_for_amortisation_reclass

    def commits_then_times_out(asset, **kw):
        real(asset, **kw)
        raise TimeoutError("read timed out after the commit")

    monkeypatch.setattr(svc, "journal_for_amortisation_reclass", commits_then_times_out)
    out = _post(db, [row["id"]], row["accumulated_depreciation_paise"])
    assert len(out["failed"]) == 1 and not out["failed"][0].get("partly_moved")
    assert out["failed"][0]["reason"] == "an unexpected error, which has been logged", "a raw exception is not shown to the browser"
    assert not row.get("accumulated_account_id") and _live(db) == [], "the entry the process never saw was found and reversed"
    _sync_balances(db)
    assert _credit(db, OWN) == 0 and _credit(db, SHARED) == row["accumulated_depreciation_paise"]


def test_undo_is_refused_when_a_disposal_lands_between_its_read_and_its_claim(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    _post(db, [row["id"]], row["accumulated_depreciation_paise"])
    real = arcs.live_entries

    def then_a_disposal_lands(*a, **k):
        out = real(*a, **k)
        row["is_disposed"] = True
        return out

    monkeypatch.setattr(arcs, "live_entries", then_a_disposal_lands)
    with pytest.raises(HTTPException) as exc:
        arcs.undo(db, FIRM, row["id"], CALLER)
    assert exc.value.status_code == 409 and "changed while this was being undone" in exc.value.detail
    assert row["accumulated_account_id"] == OWN and len(_live(db)) == 1, "nothing was changed"


def test_a_second_undo_cannot_put_the_pointer_back_over_a_ledger_the_first_emptied(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    register = row["accumulated_depreciation_paise"]
    _post(db, [row["id"]], register)
    arcs.undo(db, FIRM, row["id"], CALLER)
    with pytest.raises(HTTPException) as exc:
        arcs.undo(db, FIRM, row["id"], CALLER)
    assert exc.value.status_code == 409 and not row.get("accumulated_account_id"), "the pointer is not restored"
    _sync_balances(db)
    assert _credit(db, OWN) == 0 and _credit(db, SHARED) == register


def test_an_undo_whose_reversal_fails_leaves_the_pointer_gone_and_running_it_again_finishes(monkeypatch):
    db = _firm(monkeypatch)
    row = _two_entry_asset(db)
    register = row["accumulated_depreciation_paise"]
    _post(db, [row["id"]], register, as_at="2025-05-31")
    assert len(_live(db)) == 2
    from services.phase2_journal_service import phase2_journal_service as svc
    real, calls = svc.reverse_entry, {"n": 0}

    def second_reversal_fails(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("transient")
        return real(*a, **k)

    monkeypatch.setattr(svc, "reverse_entry", second_reversal_fails)
    with pytest.raises(HTTPException) as exc:
        arcs.undo(db, FIRM, row["id"], CALLER)
    assert exc.value.status_code == 502 and "run Undo again" in exc.value.detail
    assert not row.get("accumulated_account_id") and len(_live(db)) == 1, "the pointer is not put back over an entry still live"
    monkeypatch.setattr(svc, "reverse_entry", real)
    again = arcs.undo(db, FIRM, row["id"], CALLER)
    assert len(again["reversal_entry_ids"]) == 1 and _live(db) == []
    _sync_balances(db)
    assert _credit(db, OWN) == 0 and _credit(db, SHARED) == register


def test_an_asset_an_undo_took_back_but_could_not_empty_is_not_offered_for_a_second_move_and_still_has_its_undo(monkeypatch):
    """Pointer gone, one entry still live: the register says "shared ledger" and the ledger says "half moved". Offering it as a candidate
    would move it twice; hiding it would leave no button that finishes the undo."""
    db = _firm(monkeypatch)
    row = _two_entry_asset(db)
    _post(db, [row["id"]], row["accumulated_depreciation_paise"], as_at="2025-05-31")
    from services.phase2_journal_service import phase2_journal_service as svc
    real, calls = svc.reverse_entry, {"n": 0}

    def second_reversal_fails(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("transient")
        return real(*a, **k)

    monkeypatch.setattr(svc, "reverse_entry", second_reversal_fails)
    with pytest.raises(HTTPException):
        arcs.undo(db, FIRM, row["id"], CALLER)
    monkeypatch.setattr(svc, "reverse_entry", real)
    _stamp(db)
    p = _preview(db)
    assert p["assets"] == [] and p["ready"] is False
    assert [(r["asset_id"], r["unfinished"], r["moved_by_reclassification"]) for r in p["reclassified"]] == [(row["id"], True, True)]
    assert any("Run Undo on it to finish" in r and "move it twice" in r for r in p["refusals"])
    with pytest.raises(HTTPException) as exc:
        _post(db, [row["id"]], row["accumulated_depreciation_paise"])
    assert exc.value.status_code == 422
    s = arcs.summary(db, FIRM, CLIENT)
    assert (s["unmoved"], s["moved"], s["unfinished"]) == (0, 1, 1)
    assert arcs.undo(db, FIRM, row["id"], CALLER)["reversal_entry_ids"] and _live(db) == []
    assert arcs.summary(db, FIRM, CLIENT)["unfinished"] == 0 and arcs.summary(db, FIRM, CLIENT)["unmoved"] == 1


def test_undo_is_allowed_again_once_the_month_posted_since_has_been_reversed(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    _post(db, [row["id"]], row["accumulated_depreciation_paise"])
    fa.post_depreciation(row["id"], DepreciationIn(period="2025-07"), CALLER)
    with pytest.raises(HTTPException) as exc:
        arcs.undo(db, FIRM, row["id"], CALLER)
    assert exc.value.status_code == 409 and "Reverse those months first" in exc.value.detail
    _stamp(db)
    assert fa.reverse_depreciation(row["id"], "2025-07", CALLER)["success"] is True
    _stamp(db)
    assert arcs.undo(db, FIRM, row["id"], CALLER)["reversal_entry_ids"], "a month posted and reversed no longer blocks it"


def test_a_pointer_with_no_entry_behind_it_after_a_claim_that_posted_nothing_can_be_taken_back(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    row["accumulated_account_id"] = OWN              # claimed, then the process died before any journal
    assert arcs.undo(db, FIRM, row["id"], CALLER)["reversal_entry_ids"] == [] and not row.get("accumulated_account_id")


def test_the_month_reversal_claims_the_register_first_and_a_reclassification_that_lands_in_between_makes_it_a_409(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    stale = dict(row)                                                    # what the request read: pointer NULL, the register as it was
    _post(db, [row["id"]], row["accumulated_depreciation_paise"])        # ...and then the reclassification committed
    monkeypatch.setattr(fa, "_live_asset", lambda db_, asset_id, firm_id: stale)
    entries_before, register = len(db.rows("journal_entries")), row["accumulated_depreciation_paise"]
    with pytest.raises(HTTPException) as exc:
        fa.reverse_depreciation(row["id"], "2025-06", CALLER)
    assert exc.value.status_code == 409 and "changed while 2025-06 was being reversed" in exc.value.detail
    assert len(db.rows("journal_entries")) == entries_before and row["accumulated_depreciation_paise"] == register


def test_a_failed_month_reversal_puts_the_register_back(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    before = {k: row.get(k) for k in ("accumulated_depreciation_paise", "current_wdv_paise", "depreciation_posted_through")}
    monkeypatch.setattr(fa, "_reverse_tolerating_already_reversed", lambda *a, **k: (_ for _ in ()).throw(ValueError("outage")))
    with pytest.raises(ValueError):
        fa.reverse_depreciation(row["id"], "2025-06", CALLER)
    assert {k: row.get(k) for k in before} == before


def test_a_depreciation_whose_lost_race_reversal_fails_is_a_502_naming_the_journal_and_keeps_the_month_unposted(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    real_post = fa.Phase2JournalService.journal_for_depreciation

    def posts_then_a_claim_lands(self, asset, *a, **k):
        entry = real_post(self, asset, *a, **k)
        row["accumulated_account_id"] = OWN
        return entry

    monkeypatch.setattr(fa.Phase2JournalService, "journal_for_depreciation", posts_then_a_claim_lands)
    monkeypatch.setattr(fa, "_reverse_tolerating_already_reversed", lambda *a, **k: (_ for _ in ()).throw(ValueError("outage")))
    before = row["accumulated_depreciation_paise"]
    with pytest.raises(HTTPException) as exc:
        fa.post_depreciation(row["id"], DepreciationIn(period="2025-07"), CALLER)
    assert exc.value.status_code == 502 and "could not be reversed" in exc.value.detail and "Reverse that journal" in exc.value.detail
    assert row["accumulated_depreciation_paise"] == before


def test_a_correction_that_loses_the_race_with_the_first_month_does_not_write_the_new_pointer(monkeypatch):
    db = _firm(monkeypatch)
    row = _create(db, name="Lathe", category="Plant & Machinery", life=15, method="WDV")
    stale = dict(row)
    row["accumulated_depreciation_paise"] = 1_00                         # the first month landed after the request read the row
    with pytest.raises(HTTPException) as exc:
        fa._write_correction(db, FIRM, stale, row["id"], {"accumulated_account_id": OWN, "notes": "x"})
    assert exc.value.status_code == 409 and not row.get("accumulated_account_id")


def test_a_category_change_that_loses_the_race_with_the_first_month_touches_nothing(monkeypatch):
    """POST-A-349 (2). The compare-and-set used to be the correction's LAST write, after the old acquisition entry was reversed and the new
    one posted: a first month that landed in between left the acquisition replaced under the new category and the register on the old one.
    It is the first thing that changes now, so the refusal leaves the ledger and the register exactly as they were."""
    db = _firm(monkeypatch)
    row = _create(db, name="Lathe", category="Plant & Machinery", life=15, method="WDV")
    stale = dict(row)
    row["accumulated_depreciation_paise"] = 1_00                         # the first month landed after the request read the row
    monkeypatch.setattr(fa, "_live_asset", lambda db_, asset_id, firm_id: stale)
    entries_before = [(e["id"], e.get("is_reversed")) for e in db.rows("journal_entries")]
    before = {k: row.get(k) for k in ("asset_category", "accumulated_account_id", "journal_entry_id", "purchase_cost_paise", "corrections_count")}
    with pytest.raises(HTTPException) as exc:
        fa.correct_asset(row["id"], FixedAssetUpdateIn(asset_category="Intangibles"), CALLER)
    assert exc.value.status_code == 409 and "nothing was changed" in exc.value.detail
    assert [(e["id"], e.get("is_reversed")) for e in db.rows("journal_entries")] == entries_before, "no entry was reversed or posted"
    assert {k: row.get(k) for k in before} == before, "and the register is as it was"


def test_the_new_ledger_is_claimed_before_the_acquisition_entry_is_reversed(monkeypatch):
    """A first month of depreciation that starts after the claim is credited to the NEW ledger, which is the right one."""
    db = _firm(monkeypatch)
    row = _create(db, name="Lathe", category="Plant & Machinery", life=15, method="WDV")
    seen = {}
    real = fa._reverse_tolerating_already_reversed

    def reverse_and_look(*a, **k):
        seen["pointer"], seen["category"] = row.get("accumulated_account_id"), row.get("asset_category")
        return real(*a, **k)

    monkeypatch.setattr(fa, "_reverse_tolerating_already_reversed", reverse_and_look)
    fa.correct_asset(row["id"], FixedAssetUpdateIn(asset_category="Intangibles"), CALLER)
    assert seen == {"pointer": OWN, "category": "Intangibles"}, seen
    assert row["accumulated_account_id"] == OWN and row["asset_category"] == "Intangibles"


def test_a_month_posted_after_the_claim_is_refused_at_the_last_write_and_not_written_over(monkeypatch):
    """The reviewer's sequence: the claim passes, a first month (computed on the OLD cost, credited to the new ledger because the pointer is
    already the new one) lands while the acquisition entry is being replaced, and the last write would then set the new cost and a book value
    that ignores the month. It is a compare-and-set on the accumulated figure, so the register keeps the old cost and the answer says what to do."""
    db = _firm(monkeypatch)
    row = _create(db, name="Lathe", category="Plant & Machinery", life=15, method="WDV")
    cost_before = row["purchase_cost_paise"]
    real = fa._reverse_tolerating_already_reversed

    def reverse_then_a_month_lands(*a, **k):
        out = real(*a, **k)
        row["accumulated_depreciation_paise"] = 1_00                     # the first month, posted by another request
        return out

    monkeypatch.setattr(fa, "_reverse_tolerating_already_reversed", reverse_then_a_month_lands)
    logged = []
    monkeypatch.setattr(fa, "log_event", lambda *a, **k: logged.append(k.get("metadata") or {}))
    with pytest.raises(HTTPException) as exc:
        fa.correct_asset(row["id"], FixedAssetUpdateIn(asset_category="Intangibles", purchase_cost_paise=cost_before + 10_000_00), CALLER)
    assert exc.value.status_code == 409 and "Reverse that month" in exc.value.detail
    assert row["purchase_cost_paise"] == cost_before, "the cost was not written over a month computed on the old one"
    assert row["accumulated_depreciation_paise"] == 1_00
    assert any(m.get("action") == "correction_not_applied" for m in logged), "and the edit log says the correction did not happen"


def test_a_correction_that_fails_after_the_claim_is_completed_by_sending_it_again(monkeypatch):
    db = _firm(monkeypatch)
    row = _create(db, name="Lathe", category="Plant & Machinery", life=15, method="WDV")
    old_journal = row["journal_entry_id"]
    real = fa._reverse_tolerating_already_reversed
    monkeypatch.setattr(fa, "_reverse_tolerating_already_reversed", lambda *a, **k: (_ for _ in ()).throw(ValueError("outage")))
    with pytest.raises(ValueError):
        fa.correct_asset(row["id"], FixedAssetUpdateIn(asset_category="Intangibles"), CALLER)
    assert row["accumulated_account_id"] == OWN and row["journal_entry_id"] == old_journal, "claimed, the entry not yet replaced"
    monkeypatch.setattr(fa, "_reverse_tolerating_already_reversed", real)
    assert fa.correct_asset(row["id"], FixedAssetUpdateIn(asset_category="Intangibles"), CALLER)["success"] is True
    assert row["asset_category"] == "Intangibles" and row["accumulated_account_id"] == OWN
    assert row["journal_entry_id"] != old_journal and row["corrections_count"] == 1


def test_a_correction_whose_pointer_moved_after_it_was_read_does_not_overwrite_it_even_when_the_figure_did_not_move(monkeypatch):
    """A claim changes the pointer and not the figure, so the figure condition alone cannot see it."""
    db = _firm(monkeypatch)
    row = _create(db, name="Licence", category="Intangibles")             # born pointing at the new ledger, nothing depreciated
    stale = dict(row)
    stale["accumulated_account_id"] = None                                # the copy the request read, before the pointer was set
    with pytest.raises(HTTPException) as exc:
        fa._write_correction(db, FIRM, stale, row["id"], {"accumulated_account_id": None, "asset_name": "Renamed"})
    assert exc.value.status_code == 409 and row["accumulated_account_id"] == OWN and row["asset_name"] == "Licence"


def test_a_reclassified_asset_cannot_be_deleted_until_the_reclassification_is_undone(monkeypatch):
    db = _firm(monkeypatch)
    row = _create(db, date="2025-03-01")
    row.update(accumulated_account_id=None, opening_position_date="2025-03-31", depreciation_posted_through="2025-03-31",
               accumulated_depreciation_paise=50_000_00, current_wdv_paise=row["purchase_cost_paise"] - 50_000_00, journal_entry_id=None)
    db.seed("journal_entries", {"id": "je-tb", "firm_id": FIRM, "client_id": CLIENT, "entry_date": "2025-03-31", "reference_no": "TB-1",
                                "is_reversed": False, "source_type": "TrialBalance"})
    db.seed("journal_lines", {"id": "jl-tb1", "journal_entry_id": "je-tb", "account_id": SHARED, "debit_paise": 0, "credit_paise": 50_000_00})
    db.seed("journal_lines", {"id": "jl-tb2", "journal_entry_id": "je-tb", "account_id": "acct-1000", "debit_paise": 50_000_00, "credit_paise": 0})
    _post(db, [row["id"]], 50_000_00, as_at="2025-03-31", carried=SHARED)       # chosen on purpose: that is where the trial balance put it
    with pytest.raises(HTTPException) as exc:
        fa.delete_asset(row["id"], CALLER)
    assert exc.value.status_code == 422 and "Undo that first" in exc.value.detail and not row.get("deleted_at")
    arcs.undo(db, FIRM, row["id"], CALLER)
    assert fa.delete_asset(row["id"], CALLER)["success"] is True


def test_a_disposal_dated_before_the_move_is_refused_because_it_would_debit_the_new_ledger_before_it_was_credited(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db, months=("2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09"))
    _post(db, [row["id"]], row["accumulated_depreciation_paise"], as_at="2025-09-30")
    entries_before = len(db.rows("journal_entries"))
    with pytest.raises(HTTPException) as exc:
        fa.dispose_asset(row["id"], DisposalIn(disposal_date="2025-08-31", sale_proceeds_paise=50_000_00, disposal_type="Sale"), CALLER)
    assert exc.value.status_code == 422 and "2025-09-30" in exc.value.detail and row["is_disposed"] is False
    assert len(db.rows("journal_entries")) == entries_before
    assert fa.dispose_asset(row["id"], DisposalIn(disposal_date="2025-09-30", sale_proceeds_paise=50_000_00, disposal_type="Sale"),
                            CALLER)["success"] is True


# ── the named ledger, the date's lower bound, and what is offered ───────────────────────────────

def _brought_over(db, **kw):
    """An asset brought over with 10,000 of depreciation sitting in an imported ledger of its own."""
    row = _legacy(db, **kw)
    own_journals = row["accumulated_depreciation_paise"]
    row["accumulated_depreciation_paise"] = own_journals + 10_000_00
    db.seed("chart_of_accounts", {"id": "acct-tb", "firm_id": FIRM, "client_id": CLIENT, "account_code": "1700",
                                  "account_name": "Accumulated Dep - Software (imported)", "account_type": "Asset",
                                  "account_subtype": "Fixed Asset", "is_active": True})
    db.seed("journal_entries", {"id": "je-tb", "firm_id": FIRM, "client_id": CLIENT, "entry_date": "2025-04-01", "reference_no": "TB-1",
                                "is_reversed": False, "source_type": "TrialBalance"})
    db.seed("journal_lines", {"id": "jl-tb1", "journal_entry_id": "je-tb", "account_id": "acct-tb", "debit_paise": 0, "credit_paise": 10_000_00})
    db.seed("journal_lines", {"id": "jl-tb2", "journal_entry_id": "je-tb", "account_id": "acct-1000", "debit_paise": 10_000_00, "credit_paise": 0})
    return row


def test_the_brought_over_part_is_never_taken_from_the_shared_ledger_by_default(monkeypatch):
    """The reviewer's fixture: the shared ledger also holds a tangible asset's depreciation, so a balance check alone passes and the
    blank used to take the tangible asset's credit, leaving the tangible line too high. Now a blank is a refusal."""
    db = _firm(monkeypatch)
    plant = _create(db, name="Lathe", category="Plant & Machinery", life=15, method="WDV")
    fa.post_depreciation(plant["id"], DepreciationIn(period="2025-04"), CALLER)
    row = _brought_over(db)
    out = _preview(db)
    assert out["ready"] is False
    assert any("brought" in r and "Choose the ledger it sits in" in r and "Nothing is moved until you say" in r for r in out["refusals"])
    named = _preview(db, carried="acct-tb")
    assert named["ready"] is True and named["assets"][0]["carried_over_paise"] == 10_000_00
    explicit = _preview(db, carried=SHARED)
    assert not any("Choose the ledger it sits in" in r for r in explicit["refusals"]), "choosing the shared ledger is a choice, not a default"
    _sync_balances(db)
    shared_before = _credit(db, SHARED)
    _post(db, [row["id"]], row["accumulated_depreciation_paise"], carried="acct-tb")
    _sync_balances(db)
    assert _credit(db, SHARED) == shared_before - (row["accumulated_depreciation_paise"] - 10_000_00), "the plant's own credit is untouched"
    assert _credit(db, "acct-tb") == 0


def test_the_new_ledger_itself_cannot_be_named_for_the_carried_over_part(monkeypatch):
    db = _firm(monkeypatch)
    _brought_over(db)
    out = _preview(db, carried=OWN)
    assert out["ready"] is False and any("Accumulated Amortisation ledger itself" in r for r in out["refusals"])


def test_another_clients_ledger_cannot_be_named_and_its_name_is_not_shown(monkeypatch):
    db = _firm(monkeypatch)
    _brought_over(db)
    db.seed("chart_of_accounts", {"id": "acct-other", "firm_id": FIRM, "client_id": "CLI-SOMEONE-ELSE", "account_code": "1999",
                                  "account_name": "Other Client Secret Asset Ledger", "account_type": "Asset", "is_active": True})
    out = _preview(db, carried="acct-other")
    assert out["ready"] is False and out["carried_over_ledger"] is None
    assert "Secret" not in repr(out), "the other client's ledger name is not served"


def test_the_ledgers_offered_for_the_carried_over_part_are_asset_ledgers_that_hold_a_credit_and_never_cash(monkeypatch):
    db = _firm(monkeypatch)
    _brought_over(db)
    out = _preview(db)
    names = [c["name"] for c in out["carried_over_candidates"]]
    assert "Accumulated Dep - Software (imported)" in names
    assert not {"Cash in Hand", "Bank Account", "Trade Receivables", "Accumulated Depreciation", "Accumulated Amortisation"} & set(names)
    assert all(c["credit_paise"] > 0 for c in out["carried_over_candidates"])


def test_a_date_before_an_asset_with_brought_over_depreciation_existed_is_refused(monkeypatch):
    db = _firm(monkeypatch)
    row = _brought_over(db)
    row["opening_position_date"] = "2025-04-30"
    out = _preview(db, as_at="2025-03-31", carried="acct-tb")
    assert out["ready"] is False and any("is only on the books from 30 Apr 2025" in r for r in out["refusals"]), out["refusals"]


def test_a_closed_year_is_asked_only_of_the_dates_an_entry_will_be_dated(monkeypatch):
    """Nothing to move as at the stated date (every month is later): a closed year at that date is no reason to refuse."""
    db = _firm(monkeypatch)
    row = _create(db)
    row["accumulated_account_id"] = None
    fa.post_depreciation(row["id"], DepreciationIn(period="2025-04"), CALLER)
    next(f for f in db.rows("firms") if f["id"] == FIRM)["locked_financial_years"] = ["2024-25"]
    out = _preview(db, as_at="2025-03-31")
    assert out["ready"] is True, out["refusals"]


# ── a second client of the same firm, boundaries, and the other guards ─────────────────────────

CLIENT2 = "CLI-AR-2"


def _second_clients_legacy_asset(db):
    """The shared ledger is the FIRM's, so it holds every client's depreciation: a read that forgets the client sees all of it."""
    db.seed("clients", {"id": CLIENT2, "firm_id": FIRM, "financial_year_start": "2025-04-01"})
    res = fa.create_asset(FixedAssetIn(
        client_id=CLIENT2, asset_name="Other client's licence", asset_category="Intangibles", purchase_date="2025-04-05",
        purchase_cost_paise=6_00_000_00, depreciation_method="SL", useful_life_years=5, acquisition_mode="paid"), CALLER)
    row = next(r for r in db.rows("fixed_assets") if r["id"] == res["data"]["id"])
    row["accumulated_account_id"] = None
    for period in ("2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09"):
        fa.post_depreciation(row["id"], DepreciationIn(period=period), CALLER)
    return row


def test_one_clients_preview_balance_check_and_post_ignore_the_other_clients_of_the_firm(monkeypatch):
    db = _firm(monkeypatch)
    mine = _legacy(db)
    theirs = _second_clients_legacy_asset(db)
    out = _preview(db)
    assert [a["asset_id"] for a in out["assets"]] == [mine["id"]], "the other client's licence is not listed"
    assert out["total_to_move_paise"] == mine["accumulated_depreciation_paise"]
    # A shortfall in MY shared-ledger credit is a refusal even though the firm-wide ledger holds plenty (the other client's credit).
    db.seed("journal_entries", {"id": "je-x", "firm_id": FIRM, "client_id": CLIENT, "entry_date": "2025-06-30", "reference_no": "X",
                                "is_reversed": False, "source_type": "Journal"})
    db.seed("journal_lines", {"id": "jl-x", "journal_entry_id": "je-x", "account_id": SHARED, "debit_paise": 1_00, "credit_paise": 0})
    db.seed("journal_lines", {"id": "jl-y", "journal_entry_id": "je-x", "account_id": "acct-1000", "debit_paise": 0, "credit_paise": 1_00})
    refused = _preview(db)
    assert refused["ready"] is False and any("debit balance" in r for r in refused["refusals"])
    # ...and once it is whole, posting for me leaves the other client's asset and credit alone
    db._tables["journal_lines"] = [l for l in db.rows("journal_lines") if l["journal_entry_id"] != "je-x"]
    _sync_balances(db)
    their_credit_before = sum(int(l["credit_paise"]) - int(l["debit_paise"]) for l in db.rows("journal_lines")
                              if l["account_id"] == SHARED and next(e for e in db.rows("journal_entries") if e["id"] == l["journal_entry_id"])["client_id"] == CLIENT2)
    _post(db, [mine["id"]], mine["accumulated_depreciation_paise"])
    assert theirs.get("accumulated_account_id") is None
    their_credit_after = sum(int(l["credit_paise"]) - int(l["debit_paise"]) for l in db.rows("journal_lines")
                             if l["account_id"] == SHARED and next(e for e in db.rows("journal_entries") if e["id"] == l["journal_entry_id"])["client_id"] == CLIENT2)
    assert their_credit_after == their_credit_before > 0


def test_the_month_ending_on_the_stated_date_is_in_the_first_entry_and_the_next_month_in_the_later_one(monkeypatch):
    db = _firm(monkeypatch)
    _legacy(db, months=("2025-04", "2025-05", "2025-06"))

    def credited_in(month_end):
        entry = next(e for e in db.rows("journal_entries") if e.get("source_type") == "depreciation" and str(e["entry_date"])[:10] == month_end)
        return sum(int(l["credit_paise"]) for l in db.rows("journal_lines") if l["journal_entry_id"] == entry["id"] and l["account_id"] == SHARED)

    out = _preview(db, as_at="2025-05-31")
    a = out["assets"][0]
    assert a["moves_as_at_paise"] == credited_in("2025-04-30") + credited_in("2025-05-31"), "the month that ends ON the date is in the first entry"
    assert a["moves_later_paise"] == credited_in("2025-06-30")
    assert out["later_dates"] == ["2026-03-31"]


def test_a_date_equal_to_today_is_accepted_and_a_later_one_is_not(monkeypatch):
    db = _firm(monkeypatch)
    _legacy(db)
    monkeypatch.setattr(arcs, "ist_today", lambda: __import__("datetime").date(2025, 9, 30))
    assert _preview(db, as_at="2025-09-30")["ready"] is True
    with pytest.raises(HTTPException) as exc:
        _preview(db, as_at="2025-10-31")
    assert exc.value.status_code == 422 and "future" in exc.value.detail


def test_two_partners_posting_the_same_preview_claim_each_asset_once(monkeypatch):
    """The second claim finds the pointer already taken (the figure has not moved, so only the pointer condition can stop it)."""
    db = _firm(monkeypatch)
    row = _legacy(db)
    real = arcs._claim

    def another_partner_claims_first(db_, firm, client, plan, own_id):
        row["accumulated_account_id"] = OWN
        return real(db_, firm, client, plan, own_id)

    monkeypatch.setattr(arcs, "_claim", another_partner_claims_first)
    entries_before = len(db.rows("journal_entries"))
    out = _post(db, [row["id"]], row["accumulated_depreciation_paise"])
    assert out["moved"] == [] and len(out["skipped"]) == 1 and len(db.rows("journal_entries")) == entries_before


def test_undo_is_refused_for_a_disposed_asset_and_for_a_closed_year(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    _post(db, [row["id"]], row["accumulated_depreciation_paise"])
    next(f for f in db.rows("firms") if f["id"] == FIRM)["locked_financial_years"] = ["2025-26"]
    with pytest.raises(HTTPException) as closed:
        arcs.undo(db, FIRM, row["id"], CALLER)
    assert closed.value.status_code == 422 and "30 Sep 2025" in closed.value.detail and len(_live(db)) == 1 and row["accumulated_account_id"] == OWN
    next(f for f in db.rows("firms") if f["id"] == FIRM)["locked_financial_years"] = []
    row["is_disposed"] = True
    with pytest.raises(HTTPException) as disposed:
        arcs.undo(db, FIRM, row["id"], CALLER)
    assert disposed.value.status_code == 409 and "disposed" in disposed.value.detail and len(_live(db)) == 1


# ── the routes ──────────────────────────────────────────────────────────────

def test_the_post_and_undo_routes_ask_the_approve_permission_and_the_preview_only_read():
    """`rbac(resource, action)` returns a dependency; what each route asks is read off its source, as the rbac guards in this suite do."""
    import inspect
    asked = {}
    for fn in (fa.amortisation_reclassification_preview, fa.amortisation_reclassification_post, fa.amortisation_reclassification_undo):
        src = inspect.getsource(fn)
        asked[fn.__name__] = 'rbac("accounting", "approve")' in src, 'rbac("accounting", "read")' in src
    assert asked == {
        "amortisation_reclassification_preview": (False, True),
        "amortisation_reclassification_post": (True, False),
        "amortisation_reclassification_undo": (True, False),
    }


def test_the_routes_answer_through_the_service_and_the_post_leaves_a_timeline_line(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    _sync_balances(db)
    logged = []
    monkeypatch.setattr(fa.timeline_service, "log", lambda *a, **k: logged.append(a))
    out = fa.amortisation_reclassification_preview(CLIENT, AS_AT, None, CALLER)
    assert out["success"] is True and out["data"]["ready"] is True
    body = fa.AmortisationReclassIn(client_id=CLIENT, as_at=AS_AT, asset_ids=[row["id"]],
                                    expected_total_paise=row["accumulated_depreciation_paise"])
    res = fa.amortisation_reclassification_post(body, CALLER)
    assert res["success"] is True and res["data"]["total_moved_paise"] == row["accumulated_depreciation_paise"]
    assert any("Accumulated Amortisation Reclassified" in a for call in logged for a in call if isinstance(a, str))
    undone = fa.amortisation_reclassification_undo(row["id"], CALLER)
    assert undone["success"] is True and not row.get("accumulated_account_id")


# ── the register says it ────────────────────────────────────────────────────

def _kinds(db):
    return {f["kind"] for f in fa.register_integrity(CLIENT, CALLER)["data"]["findings"]}


def test_the_register_says_an_asset_is_in_the_wrong_ledger_until_it_is_moved(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    _sync_balances(db)
    assert "intangible_amortisation_in_the_shared_ledger" in _kinds(db)
    _post(db, [row["id"]], row["accumulated_depreciation_paise"])
    _sync_balances(db)
    assert not ({"intangible_amortisation_in_the_shared_ledger", "accumulated_amortisation_ledger_disagrees_with_register"} & _kinds(db))


def test_the_register_says_it_when_the_new_ledger_and_the_assets_pointed_at_it_disagree(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    _post(db, [row["id"]], row["accumulated_depreciation_paise"])
    db.seed("journal_entries", {"id": "je-h", "firm_id": FIRM, "client_id": CLIENT, "entry_date": "2025-09-30", "reference_no": "H1",
                                "is_reversed": False, "source_type": "Journal"})
    db.seed("journal_lines", {"id": "jl-h1", "journal_entry_id": "je-h", "account_id": OWN, "debit_paise": 3_00, "credit_paise": 0})
    db.seed("journal_lines", {"id": "jl-h2", "journal_entry_id": "je-h", "account_id": "acct-1000", "debit_paise": 0, "credit_paise": 3_00})
    _sync_balances(db)
    findings = fa.register_integrity(CLIENT, CALLER)["data"]["findings"]
    f = next(x for x in findings if x["kind"] == "accumulated_amortisation_ledger_disagrees_with_register")
    assert f["amount_paise"] == 3_00 and "less than the assets pointed at it" in f["what_it_means"]


def test_the_register_does_not_ask_when_the_chart_has_no_amortisation_ledger(monkeypatch):
    db = _firm(monkeypatch)
    _legacy(db)
    db._tables["chart_of_accounts"] = [r for r in db.rows("chart_of_accounts") if r["id"] != OWN]
    assert not ({"intangible_amortisation_in_the_shared_ledger", "accumulated_amortisation_ledger_disagrees_with_register"} & _kinds(db))


# ── the screen reads what the server serves ─────────────────────────────────────────────────────

# The screen's own types, apps/web/lib/fixedAssets/amortisationReclass.ts: read here so a renamed key fails on the side that renamed it.
WEB_TYPES = pathlib.Path(__file__).resolve().parents[2] / "web" / "lib" / "fixedAssets" / "amortisationReclass.ts"


def _ts_body(name: str) -> str:
    """The text of `export type <name> = ...` with comments and nested braces folded away, so only its own top-level fields are left."""
    text = re.sub(r"/\*.*?\*/", "", WEB_TYPES.read_text(), flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    start = text.index(f"export type {name} =")
    end = text.index(";\n", start) if "{" not in text[start:text.index("\n", start)] else None
    if end is None:                                   # a multi-line object type: up to its closing "};" at column 0
        end = text.index("\n};", start) + 2
    return text[start:end]


def _ts_fields(name: str) -> dict[str, bool]:
    """{field: required} of a type alias in the screen's module."""
    body = _ts_body(name)
    body = body[body.index("{"):]
    inner = body[1:]
    while re.search(r"\{[^{}]*\}", inner):                     # fold nested object types away; "_" has no braces, so this ends
        inner = re.sub(r"\{[^{}]*\}", "_", inner)
    body = "{" + inner
    return {m.group(1): m.group(2) != "?" for m in re.finditer(r"(?:^|[;{\n])\s*(\w+)(\??)\s*:", body[1:])}


def _ts_inline_fields(name: str, field: str) -> set[str]:
    """The keys of the object type written inline for a list field, e.g. `moved: { asset_id: string; ... }[]`."""
    m = re.search(rf"\b{field}\??:\s*\{{([^{{}}]*)\}}", _ts_body(name))
    assert m, f"{name}.{field} has no inline object type"
    return {k.group(1) for k in re.finditer(r"(?:^|;)\s*(\w+)\??\s*:", m.group(1))}


def _same_keys(ts_name: str, served: dict, *, unread: tuple = ()):
    fields = _ts_fields(ts_name)
    missing = [f for f, required in fields.items() if required and f not in served]
    assert not missing, f"{ts_name} reads {missing}, which the server does not serve: {sorted(served)}"
    extra = set(served) - set(fields) - set(unread)
    assert not extra, f"the server serves {sorted(extra)}, which {ts_name} does not describe"


def test_the_screens_types_name_exactly_the_keys_the_server_serves(monkeypatch):
    """A field renamed on one side reads `undefined` on the other, and `formatPaise(undefined)` is a blank where a figure should be.
    Every shape the screen reads is taken from a REAL preview, post, failed post and summary, not from a hand-written fixture."""
    db = _firm(monkeypatch)
    row = _brought_over(db, months=("2025-04", "2025-05", "2025-06", "2025-07", "2025-08"))
    p = _preview(db, as_at="2025-05-31", carried="acct-tb")
    assert p["ready"] is True and p["later_dates"] and p["carried_over_candidates"] and p["carried_over_ledger"]
    _same_keys("ReclassPreview", p, unread=("today",))
    _same_keys("ReclassAsset", p["assets"][0])
    assert set(p["carried_over_candidates"][0]) == set(_ts_fields("ReclassCandidate")) | set(_ts_fields("ReclassLedger")) - {"code", "name"} | {"code", "name"}
    assert set(p["carried_over_ledger"]) == set(_ts_fields("ReclassLedger"))
    assert set(p["financial_years"][0]) == _ts_inline_fields("ReclassPreview", "financial_years")

    unwanted = _preview(db)                                           # no ledger chosen: refused, and every figure is still served
    assert unwanted["ready"] is False
    _same_keys("ReclassPreview", unwanted, unread=("today",))

    out = _post(db, [row["id"]], p["total_to_move_paise"], as_at="2025-05-31", carried="acct-tb")
    _same_keys("ReclassPostResult", out)
    assert set(out["moved"][0]) == _ts_inline_fields("ReclassPostResult", "moved")
    s = arcs.summary(db, FIRM, CLIENT)
    _same_keys("ReclassSummary", s)
    assert set(s["moved_assets"][0]) == set(_ts_fields("ReclassedAsset")) and set(s["own_ledger"]) == {"id", "name"}
    again = _preview(db, as_at="2025-05-31", carried="acct-tb")
    assert set(again["reclassified"][0]) == set(_ts_fields("ReclassedAsset"))


def test_the_screens_failure_and_skipped_shapes_are_the_ones_the_server_serves(monkeypatch):
    db = _firm(monkeypatch)
    row = _two_entry_asset(db)
    register = row["accumulated_depreciation_paise"]
    from services.phase2_journal_service import phase2_journal_service as svc
    real_journal = svc.journal_for_amortisation_reclass

    def second_fails(asset, **kw):
        if kw["tranche"] == 2:
            raise ValueError("closed")
        return real_journal(asset, **kw)

    monkeypatch.setattr(svc, "journal_for_amortisation_reclass", second_fails)
    monkeypatch.setattr(svc, "reverse_entry", lambda *a, **k: (_ for _ in ()).throw(ValueError("down")))
    failed = _post(db, [row["id"]], register, as_at="2025-05-31")["failed"][0]
    assert set(failed) == set(_ts_fields("ReclassFailure"))
    assert set(_ts_fields("ReclassFailure")) >= {"asset_id", "asset_code", "reason", "partly_moved", "live_entry_ids"}
    fresh = _firm(monkeypatch)                                         # a second practice, for the skipped shape
    other = _legacy(fresh)
    monkeypatch.setattr(arcs, "_claim", lambda *a, **k: False)
    skipped = _post(fresh, [other["id"]], other["accumulated_depreciation_paise"])["skipped"]
    assert len(skipped) == 1 and set(skipped[0]) == _ts_inline_fields("ReclassPostResult", "skipped")


# ── what the final independent review found, each held ──────────────────────────────────────────

def _manual_journal(db, entry_date, debit_account, credit_account, amount, ref):
    """A plain journal on this client (what a manual entry or the disposal of a tangible asset leaves in a ledger)."""
    entry_id = f"je-{ref}"
    db.seed("journal_entries", {"id": entry_id, "firm_id": FIRM, "client_id": CLIENT, "entry_date": entry_date, "reference_no": ref,
                                "is_reversed": False, "source_type": "manual"})
    db.seed("journal_lines", {"id": f"{entry_id}-d", "journal_entry_id": entry_id, "account_id": debit_account,
                              "debit_paise": amount, "credit_paise": 0})
    db.seed("journal_lines", {"id": f"{entry_id}-c", "journal_entry_id": entry_id, "account_id": credit_account,
                              "debit_paise": 0, "credit_paise": amount})


def test_the_shared_ledger_is_judged_at_every_month_end_after_the_first_entry_and_not_only_on_the_days_an_entry_is_dated(monkeypatch):
    """Judged only on the entry's own date, a debit posted to the same ledger two months later (a tangible asset's disposal whose
    depreciation sits there) passed, and left the tangible line's contra in debit on every balance sheet from then on, today's too."""
    db = _firm(monkeypatch)
    row = _legacy(db)                                                     # April to June: its credit sits in the shared ledger
    assert _preview(db, as_at="2025-06-30")["ready"] is True, "without the later debit the move is fine"
    _manual_journal(db, "2025-08-31", SHARED, "acct-1000", 3_000_00, "DISPOSAL-OF-A-TANGIBLE-ASSET")
    out = _preview(db, as_at="2025-06-30")
    assert out["ready"] is False and any("31 Aug 2025" in r and "debit balance" in r for r in out["refusals"]), out["refusals"]
    with pytest.raises(HTTPException) as exc:
        _post(db, [row["id"]], row["accumulated_depreciation_paise"], as_at="2025-06-30")
    assert exc.value.status_code == 422 and not row.get("accumulated_account_id") and not _entries(db)


def test_a_month_dated_after_today_is_moved_in_an_entry_dated_at_that_month_and_not_before_its_credit_exists():
    """The current year's months move in an entry dated today, and this month's charge is dated its month end, which can be after
    today: an entry dated today would debit the ledger before the credit it moves exists in it."""
    merged = arcs._dated_at_the_latest_month({"2026-10-27": 600_00, "2026-03-31": 100_00}, {"2026-10-27": "2026-10-31", "2026-03-31": "2026-03-31"})
    assert merged == (("2026-03-31", 100_00), ("2026-10-31", 600_00))
    assert arcs._dated_at_the_latest_month({"2026-10-27": 600_00}, {"2026-10-27": "2026-09-30"}) == (("2026-10-27", 600_00),), \
        "months all dated on or before today stay in the entry dated today"


def _claim_without_posting(row):
    """What a reclassification that was killed after the claim and before its first journal leaves: the pointer set, nothing posted."""
    row["accumulated_account_id"] = OWN


def test_an_asset_claimed_and_never_posted_is_listed_with_an_undo_and_is_not_offered_a_second_move(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    _claim_without_posting(row)
    s = arcs.summary(db, FIRM, CLIENT)
    assert (s["unmoved"], s["unfinished"]) == (0, 1) and [a["asset_id"] for a in s["moved_assets"]] == [row["id"]]
    assert s["moved_assets"][0]["moved_by_reclassification"] is False and s["moved_assets"][0]["unfinished"] is True
    p = _preview(db)
    assert p["ready"] is False and any("did not finish" in r and "Undo" in r for r in p["refusals"])
    done = arcs.undo(db, FIRM, row["id"], CALLER)
    assert done["reversal_entry_ids"] == [] and not row.get("accumulated_account_id")
    assert arcs.summary(db, FIRM, CLIENT)["unfinished"] == 0


def test_a_claimed_asset_that_has_had_months_posted_since_says_what_to_reverse_and_not_that_it_was_born_pointed(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    _claim_without_posting(row)
    fa.post_depreciation(row["id"], DepreciationIn(period="2025-07"), CALLER)         # credits the new ledger: the pointer says so
    with pytest.raises(HTTPException) as exc:
        arcs.undo(db, FIRM, row["id"], CALLER)
    assert exc.value.status_code == 409 and "started and did not post" in exc.value.detail and "Reverse the months posted since" in exc.value.detail


def test_a_half_moved_asset_cannot_be_disposed_of_or_deleted_because_the_undo_refuses_a_disposed_asset(monkeypatch):
    """Disposing of it debited whichever ledger the pointer named for the whole register figure, left the other ledger with a credit
    nothing explains, and the undo then refused it for being disposed of: no way back."""
    db = _firm(monkeypatch)
    row = _two_entry_asset(db)
    from services.phase2_journal_service import phase2_journal_service as svc
    real_journal, real_reverse = svc.journal_for_amortisation_reclass, svc.reverse_entry

    def second_fails(asset, **kw):
        if kw["tranche"] == 2:
            raise ValueError("closed")
        return real_journal(asset, **kw)

    monkeypatch.setattr(svc, "journal_for_amortisation_reclass", second_fails)
    monkeypatch.setattr(svc, "reverse_entry", lambda *a, **k: (_ for _ in ()).throw(ValueError("down")))
    out = _post(db, [row["id"]], row["accumulated_depreciation_paise"], as_at="2025-05-31")
    assert out["failed"][0]["partly_moved"] is True and row["accumulated_account_id"] == OWN
    monkeypatch.setattr(svc, "journal_for_amortisation_reclass", real_journal)
    with pytest.raises(HTTPException) as exc:
        fa.dispose_asset(row["id"], DisposalIn(disposal_date="2025-08-31", sale_proceeds_paise=1_000_00), CALLER)
    assert exc.value.status_code == 422 and "did not finish" in exc.value.detail
    assert not row.get("is_disposed") and not row.get("deleted_at")
    # the other half-moved state: an Undo took the pointer back and could not empty the ledger
    monkeypatch.setattr(svc, "reverse_entry", real_reverse)
    _stamp(db)
    calls = {"n": 0}

    def second_reversal_fails(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("transient")
        return real_reverse(*a, **k)

    monkeypatch.setattr(svc, "reverse_entry", second_reversal_fails)
    _post_more = _live(db)
    assert _post_more, "one entry is still posted"
    with pytest.raises(HTTPException):
        arcs.undo(db, FIRM, row["id"], CALLER)
    monkeypatch.setattr(svc, "reverse_entry", real_reverse)
    if row.get("accumulated_account_id") is None and _live(db):
        with pytest.raises(HTTPException) as exc:
            fa.dispose_asset(row["id"], DisposalIn(disposal_date="2025-08-31", sale_proceeds_paise=1_000_00), CALLER)
        assert exc.value.status_code == 422 and "did not finish" in exc.value.detail
    arcs.undo(db, FIRM, row["id"], CALLER)                                # finishing the undo is what lifts the refusal
    assert _live(db) == []


def test_a_claimed_opening_asset_cannot_be_deleted_until_its_undo_finishes(monkeypatch):
    db = _firm(monkeypatch)
    row = _create(db, date="2025-03-01")
    row.update(accumulated_account_id=OWN, opening_position_date="2025-03-31", depreciation_posted_through="2025-03-31",
               accumulated_depreciation_paise=50_000_00, current_wdv_paise=row["purchase_cost_paise"] - 50_000_00, journal_entry_id=None)
    with pytest.raises(HTTPException) as exc:
        fa.delete_asset(row["id"], CALLER)
    assert exc.value.status_code == 422 and "did not finish" in exc.value.detail and not row.get("deleted_at")


def test_a_clean_reclassified_asset_is_still_disposed_of_normally(monkeypatch):
    """The half-moved guard must not be a wall in front of every asset: a complete move disposes as it did."""
    db = _firm(monkeypatch)
    row = _legacy(db, months=("2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09"))
    _post(db, [row["id"]], row["accumulated_depreciation_paise"])
    assert arcs.unfinished_move_reason(db, FIRM, CLIENT, row) is None
    out = fa.dispose_asset(row["id"], DisposalIn(disposal_date="2025-09-30", sale_proceeds_paise=1_000_00), CALLER)
    assert out["success"] is True


def test_a_failed_unclaim_after_a_failed_journal_is_reported_and_not_raised(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    from services.phase2_journal_service import phase2_journal_service as svc
    monkeypatch.setattr(svc, "journal_for_amortisation_reclass", lambda *a, **k: (_ for _ in ()).throw(ValueError("closed")))
    monkeypatch.setattr(arcs, "_unclaim", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("the database went away")))
    out = _post(db, [row["id"]], row["accumulated_depreciation_paise"])
    f = out["failed"][0]
    assert f["partly_moved"] is True and "Undo" in f["reason"] and "ConnectionError" not in f["reason"]
    assert row["accumulated_account_id"] == OWN and arcs.summary(db, FIRM, CLIENT)["moved_assets"], "and the Undo is there"


def test_the_ledgers_offered_are_read_through_a_key_that_is_unique(monkeypatch):
    """`period_month` repeats once per account in a month, and a keyset pager over a repeating key silently drops rows past a page."""
    db = _firm(monkeypatch)
    _brought_over(db)
    seen = []
    real = arcs.fetch_all

    def spy(make_query, key="id", **kw):
        seen.append((kw.get("label"), key))
        return real(make_query, key, **kw)

    monkeypatch.setattr(arcs, "fetch_all", spy)
    _preview(db)
    assert ("amortisation_reclass.balances", "id") in seen, seen


def test_a_chart_without_the_new_ledger_says_so_only_where_the_client_holds_an_intangible_asset_and_in_a_ccas_words(monkeypatch):
    db = _firm(monkeypatch)
    for r in list(db.rows("chart_of_accounts")):
        if r["id"] == OWN:
            db._tables["chart_of_accounts"].remove(r)
    _create(db, name="Lathe", category="Plant & Machinery", life=15, method="WDV")
    assert arcs.summary(db, FIRM, CLIENT)["refusal"] is None, "a tangible-only client is told nothing"
    _create(db, name="Licence", category="Intangibles")
    said = arcs.summary(db, FIRM, CLIENT)["refusal"]
    assert said and "Migration" not in said and "Accumulated Amortisation" in said


def test_an_unamortised_legacy_asset_is_not_said_to_have_been_amortised(monkeypatch):
    from domain.fixed_assets import integrity as fi
    facts = fi.AccumulatedLedgerFacts(own_ledger_id=OWN, own_ledger_credit_paise=0, belongs_asset_ids=frozenset({"a1"}))
    asset = {"id": "a1", "asset_code": "FA-1", "asset_name": "Licence", "accumulated_depreciation_paise": 0, "accumulated_account_id": None}
    zero = fi.amortisation_in_the_shared_ledger(asset, facts)["what_it_means"]
    assert "has not been amortised yet" in zero and "what it has been amortised is credited" not in zero
    asset["accumulated_depreciation_paise"] = 5_000_00
    assert "what it has been amortised is credited" in fi.amortisation_in_the_shared_ledger(asset, facts)["what_it_means"]


def test_the_integrity_reply_says_when_the_amortisation_checks_did_not_run_and_is_not_clean(monkeypatch):
    db = _firm(monkeypatch)
    _legacy(db)
    ok = fa.register_integrity(CLIENT, CALLER)["data"]
    assert ok["not_checked"] == []
    monkeypatch.setattr(fa, "fetch_accumulated_facts", lambda *a, **k: None)
    out = fa.register_integrity(CLIENT, CALLER)["data"]
    assert out["not_checked"] and "could not be run" in out["not_checked"][0] and out["clean"] is False
    from services.fixed_asset_accumulated_ledger import CHECKS_NOT_RUN_SENTENCE
    assert out["not_checked"] == [CHECKS_NOT_RUN_SENTENCE], "the screen and the nightly sweep say it in the same words"


def test_the_nightly_check_files_a_named_finding_when_the_amortisation_checks_could_not_run(monkeypatch):
    """POST-A-349 (3). The sweep used to skip the two checks without a word, so a failed read looked like a clean register."""
    from services import fixed_asset_accumulated_ledger as fal
    from services import reconciliation_service as rs
    db = _firm(monkeypatch)
    _legacy(db)
    name = "fixed_asset_register.accumulated_amortisation_checks_not_run"
    ran = rs.check_fixed_asset_register(db, FIRM, CLIENT, entries={})
    assert not [f for f in ran if f["check_name"] == name], "the checks could run, so there is nothing to say"
    monkeypatch.setattr(fal, "fetch_facts", lambda *a, **k: None)
    out = [f for f in rs.check_fixed_asset_register(db, FIRM, CLIENT, entries={}) if f["check_name"] == name]
    assert len(out) == 1 and out[0]["severity"] == "warning" and out[0]["summary"] == fal.CHECKS_NOT_RUN_SENTENCE
    assert name in rs.CHECK_CATALOGUE, "and the screen has words for it"


def test_only_a_failed_read_means_the_amortisation_checks_did_not_run():
    from domain.fixed_assets.integrity import AccumulatedLedgerFacts
    from services.fixed_asset_accumulated_ledger import checks_could_not_run
    assert checks_could_not_run(None) is True
    assert checks_could_not_run(AccumulatedLedgerFacts(own_ledger_id=OWN, own_ledger_credit_paise=None, belongs_asset_ids=frozenset())) is True
    assert checks_could_not_run(AccumulatedLedgerFacts(own_ledger_id=OWN, own_ledger_credit_paise=0, belongs_asset_ids=frozenset())) is False
    assert checks_could_not_run(AccumulatedLedgerFacts(own_ledger_id=None, own_ledger_credit_paise=None, belongs_asset_ids=frozenset())) is False, \
        "a chart with no Accumulated Amortisation ledger has nothing to check and nothing failed"


def test_the_edit_log_does_not_record_a_reversal_the_claim_refused(monkeypatch):
    db = _firm(monkeypatch)
    row = _legacy(db)
    logged = []
    monkeypatch.setattr(fa, "log_event", lambda *a, **k: logged.append(k.get("metadata") or {}))
    real = fa._reverse_month_claiming_the_register

    def refused(*a, **k):
        raise HTTPException(status_code=409, detail="This asset changed while 2025-06 was being reversed")

    monkeypatch.setattr(fa, "_reverse_month_claiming_the_register", refused)
    with pytest.raises(HTTPException):
        fa.reverse_depreciation(row["id"], "2025-06", CALLER)
    assert not any(m.get("action") == "depreciation_reversed" for m in logged), "the reversal did not happen"
    monkeypatch.setattr(fa, "_reverse_month_claiming_the_register", real)
    assert fa.reverse_depreciation(row["id"], "2025-06", CALLER)["success"] is True
    assert any(m.get("action") == "depreciation_reversed" for m in logged), "and when it does, it is logged"


def test_a_correction_the_register_refused_is_logged_as_not_applied(monkeypatch):
    db = _firm(monkeypatch)
    row = _create(db, name="Licence", category="Intangibles")
    logged = []
    monkeypatch.setattr(fa, "log_event", lambda *a, **k: logged.append(k.get("metadata") or {}))

    def refused(*a, **k):
        raise HTTPException(status_code=409, detail="The asset changed while its category was being corrected")

    monkeypatch.setattr(fa, "_write_correction", refused)
    from models.accounting import FixedAssetUpdateIn
    with pytest.raises(HTTPException):
        fa.correct_asset(row["id"], FixedAssetUpdateIn(asset_name="Renamed", reason="typo"), CALLER)
    assert any(m.get("action") == "correction_not_applied" for m in logged), logged


def test_a_database_refusal_is_never_shown_as_its_error_dict_when_a_lost_race_reversal_fails():
    class APIError(Exception):
        pass
    said = fa._why_a_reversal_failed(APIError({"message": "duplicate key value", "code": "23505", "details": "Key (id)=(x)"}))
    assert said and "{" not in said and "23505" not in said and "'code'" not in said, said
    assert fa._why_a_reversal_failed(HTTPException(status_code=409, detail="Already reversed.")) == "Already reversed."
