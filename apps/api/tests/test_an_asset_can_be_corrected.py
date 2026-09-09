"""FA-10 — an asset in the register can be corrected, and how depends on WHAT.

Until this, an asset was final the moment it was saved: routers/fixed_assets.py
had list / create / depreciate / dispose / schedule / categories /
register-integrity and no PATCH, no DELETE and no way to unwind a month. A CA
who typed ₹15,00,000 for ₹1,50,000 had three ways out and all three were wrong
— dispose at nil proceeds (a fabricated loss, and it first demands every
unposted month be depreciated), reverse the journal through the generic
accounting endpoint (the register then claims a cost the ledger no longer
carries), or a database console.

The three tiers are the point, and they are three MECHANISMS:

  A  name, location, notes         no GL — write it and log it
  B  cost, category, purchase date the acquisition JOURNAL is wrong too, so
                                   the correction is a reversal and a re-post
                                   through the one kernel
  C  life, rate, method, salvage   a revision of an ESTIMATE (Schedule II Part
                                   C Note 7, AS 10) — prospective, never a
                                   rewrite of a month already posted

Every test here fails against the previous code: there was no endpoint to call.
"""
import pytest
from fastapi import HTTPException

import routers.fixed_assets as fa
from models.accounting import FixedAssetIn, FixedAssetUpdateIn, DepreciationIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}
OTHER = {"firm_id": FIRM, "id": "u2", "auth_user_id": "auth2", "email": "x@f.test",
         "role": "Executive", "assigned_client_ids": ["CLI-OTHER"]}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [fa])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("firms", {"id": FIRM, "name": "Test & Co", "locked_financial_years": []})
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "financial_year_start": "2025-04-01"})
    seed_standard_coa(db, FIRM, "CLI")
    for name in ("Plant & Machinery", "Office Equipment", "Depreciation Expense",
                 "Accumulated Depreciation"):
        db.seed("chart_of_accounts", {
            "firm_id": FIRM, "client_id": "CLI", "account_name": name,
            "account_code": f"FA{abs(hash(name)) % 9000 + 1000}",
            "account_type": "Expense" if name == "Depreciation" else "Asset",
            "is_active": True})
    return db


def _create(cost=1_50_000_00, category="Plant & Machinery", date="2025-04-05", **kw):
    res = fa.create_asset(FixedAssetIn(
        client_id="CLI", asset_name="Lathe", asset_category=category,
        purchase_date=date, purchase_cost_paise=cost,
        useful_life_years=15, acquisition_mode="paid", **kw), CALLER)
    assert res["success"] is True, res
    return res["data"]


def _row(db, asset_id):
    return next(r for r in db.rows("fixed_assets") if r["id"] == asset_id)


def _patch(asset_id, caller=CALLER, **fields):
    return fa.correct_asset(asset_id, FixedAssetUpdateIn(**fields), caller)


# ───────────────────────────── tier A ─────────────────────────────

def test_a_name_is_corrected_without_touching_the_ledger(monkeypatch):
    db = _setup(monkeypatch)
    asset = _create()
    before = len(db.rows("journal_entries"))

    res = _patch(asset["id"], asset_name="Lathe — Bay 2", location="Bay 2")
    assert res["success"] is True
    assert res["data"]["acquisition_reposted"] is False
    assert len(db.rows("journal_entries")) == before

    row = _row(db, asset["id"])
    assert row["asset_name"] == "Lathe — Bay 2"
    assert row["location"] == "Bay 2"


def test_clearing_a_field_to_null_is_a_real_edit(monkeypatch):
    """exclude_unset, not exclude_none — PAY-12's mechanism was the other one."""
    db = _setup(monkeypatch)
    asset = _create(location="Bay 1")
    assert _patch(asset["id"], location=None)["success"] is True
    assert _row(db, asset["id"])["location"] is None


def test_sending_nothing_is_refused_rather_than_silently_doing_nothing(monkeypatch):
    _setup(monkeypatch)
    asset = _create()
    with pytest.raises(HTTPException) as exc:
        _patch(asset["id"])
    assert exc.value.status_code == 422


# ───────────────────────────── tier B ─────────────────────────────

def test_a_wrong_cost_is_corrected_by_reversing_and_reposting(monkeypatch):
    db = _setup(monkeypatch)
    asset = _create(cost=15_00_000_00)              # a zero too many

    res = _patch(asset["id"], purchase_cost_paise=1_50_000_00,
                 reason="Typed 15,00,000 for 1,50,000")
    assert res["success"] is True
    assert res["data"]["acquisition_reposted"] is True

    row = _row(db, asset["id"])
    assert row["purchase_cost_paise"] == 1_50_000_00
    assert row["corrections_count"] == 1

    # The original is reversed on the ledger, never rewritten, and the
    # correction carries a DIFFERENT reference so it cannot dedupe onto it.
    entries = {e["id"]: e for e in db.rows("journal_entries")}
    original = entries[asset["journal_entry_id"]]
    assert original["is_reversed"] is True
    corrected = entries[row["journal_entry_id"]]
    assert corrected["id"] != original["id"]
    assert corrected["reference_no"] != original["reference_no"]
    assert corrected["reference_no"].endswith("-R1")


def test_the_corrected_journal_carries_the_corrected_amount(monkeypatch):
    db = _setup(monkeypatch)
    asset = _create(cost=15_00_000_00)
    _patch(asset["id"], purchase_cost_paise=1_50_000_00)
    row = _row(db, asset["id"])
    lines = [l for l in db.rows("journal_lines")
             if l["journal_entry_id"] == row["journal_entry_id"]]
    assert max(int(l.get("debit_paise") or 0) for l in lines) == 1_50_000_00


def test_a_second_correction_gets_its_own_reference(monkeypatch):
    db = _setup(monkeypatch)
    asset = _create(cost=15_00_000_00)
    _patch(asset["id"], purchase_cost_paise=1_50_000_00)
    _patch(asset["id"], purchase_cost_paise=1_60_000_00)
    row = _row(db, asset["id"])
    assert row["corrections_count"] == 2
    entries = {e["id"]: e for e in db.rows("journal_entries")}
    assert entries[row["journal_entry_id"]]["reference_no"].endswith("-R2")


def test_correcting_the_cost_is_refused_once_depreciation_is_posted(monkeypatch):
    db = _setup(monkeypatch)
    asset = _create(cost=15_00_000_00)
    assert fa.post_depreciation(asset["id"], DepreciationIn(period="2025-04"), CALLER)["success"]

    with pytest.raises(HTTPException) as exc:
        _patch(asset["id"], purchase_cost_paise=1_50_000_00)
    assert exc.value.status_code == 422
    # It names the month and the way out, rather than refusing blankly.
    assert "2025-04" in exc.value.detail
    assert "everse" in exc.value.detail


def test_changing_the_tax_without_the_cost_is_refused(monkeypatch):
    """purchase_cost_paise is the CAPITALISED figure — §17(5) blocked tax is
    already inside it and the typed cost is stored nowhere, so re-capitalising
    the stored value would add that tax a second time, for the asset's life."""
    _setup(monkeypatch)
    asset = _create()
    with pytest.raises(HTTPException) as exc:
        _patch(asset["id"], igst_paise=27_000_00, itc_eligible=False)
    assert exc.value.status_code == 422
    assert "purchase_cost_paise" in exc.value.detail


def test_blocked_tax_is_capitalised_once_when_cost_and_tax_arrive_together(monkeypatch):
    db = _setup(monkeypatch)
    asset = _create(cost=1_00_000_00)
    _patch(asset["id"], purchase_cost_paise=1_00_000_00,
           igst_paise=18_000_00, itc_eligible=False)
    assert _row(db, asset["id"])["purchase_cost_paise"] == 1_18_000_00
    # ... and correcting something else afterwards does not add it again.
    _patch(asset["id"], asset_name="Lathe B")
    assert _row(db, asset["id"])["purchase_cost_paise"] == 1_18_000_00


# ───────────────────────────── tier C ─────────────────────────────

def test_a_wrong_rate_is_corrected_prospectively_before_anything_is_posted(monkeypatch):
    """FA-02's case: every asset created before the Schedule II rates were
    corrected carries an Income-tax Act block rate frozen for its life."""
    db = _setup(monkeypatch)
    asset = _create()
    assert _patch(asset["id"], wdv_rate_percent=18.1, useful_life_years=15)["success"]
    row = _row(db, asset["id"])
    assert float(row["wdv_rate_percent"]) == 18.1


def test_a_revised_rate_is_refused_part_way_through_a_posted_year(monkeypatch):
    """Schedule II charges ONE annual figure ÷ 12. Changing the basis mid-year
    would give the remaining months a different charge from the posted ones."""
    db = _setup(monkeypatch)
    asset = _create()
    assert fa.post_depreciation(asset["id"], DepreciationIn(period="2025-04"), CALLER)["success"]

    with pytest.raises(HTTPException) as exc:
        _patch(asset["id"], wdv_rate_percent=9.5)
    assert exc.value.status_code == 422
    assert "2025-26" in exc.value.detail


def test_a_revised_rate_is_allowed_once_the_posted_year_is_behind(monkeypatch):
    db = _setup(monkeypatch)
    asset = _create()
    for period in ("2025-04",):
        assert fa.post_depreciation(asset["id"], DepreciationIn(period=period), CALLER)["success"]
    # Move the register to the last month of the year, so the next posting is a
    # new financial year and the revision has a clean boundary.
    db.table("fixed_assets").update({
        "depreciation_posted_through": "2026-03-31", "depreciation_fy": "2025-26",
    }).eq("id", asset["id"]).execute()

    assert _patch(asset["id"], wdv_rate_percent=9.5)["success"] is True


# ───────────────────── reversing a posted month ─────────────────────

def test_the_last_posted_month_can_be_reversed_and_the_register_moves_back(monkeypatch):
    db = _setup(monkeypatch)
    asset = _create()
    fa.post_depreciation(asset["id"], DepreciationIn(period="2025-04"), CALLER)
    fa.post_depreciation(asset["id"], DepreciationIn(period="2025-05"), CALLER)
    charged = _row(db, asset["id"])["accumulated_depreciation_paise"]

    res = fa.reverse_depreciation(asset["id"], "2025-05", CALLER)
    assert res["success"] is True
    row = _row(db, asset["id"])
    assert row["accumulated_depreciation_paise"] == charged - res["data"]["reversed_paise"]
    assert str(row["depreciation_posted_through"]).startswith("2025-04")
    assert row["current_wdv_paise"] == row["purchase_cost_paise"] - row["accumulated_depreciation_paise"]


def test_a_reversed_month_can_be_posted_again_and_lands_a_new_entry(monkeypatch):
    db = _setup(monkeypatch)
    asset = _create()
    fa.post_depreciation(asset["id"], DepreciationIn(period="2025-04"), CALLER)
    first = [e for e in db.rows("journal_entries") if str(e.get("reference_no", "")).endswith("2025-04")][0]

    fa.reverse_depreciation(asset["id"], "2025-04", CALLER)
    assert _row(db, asset["id"])["depreciation_posted_through"] is None
    assert _row(db, asset["id"])["accumulated_depreciation_paise"] == 0

    assert fa.post_depreciation(asset["id"], DepreciationIn(period="2025-04"), CALLER)["success"]
    live = [e for e in db.rows("journal_entries")
            if str(e.get("reference_no", "")).endswith("2025-04") and not e.get("is_reversed")]
    assert len(live) == 1
    assert live[0]["id"] != first["id"]


def test_a_month_that_is_not_the_last_one_is_refused(monkeypatch):
    """Months come off in the order they went on: post_depreciation refuses any
    month at or below the posted-through mark, so a hole would be permanent."""
    _setup(monkeypatch)
    asset = _create()
    fa.post_depreciation(asset["id"], DepreciationIn(period="2025-04"), CALLER)
    fa.post_depreciation(asset["id"], DepreciationIn(period="2025-05"), CALLER)

    with pytest.raises(HTTPException) as exc:
        fa.reverse_depreciation(asset["id"], "2025-04", CALLER)
    assert exc.value.status_code == 422
    assert "2025-05" in exc.value.detail


def test_reversing_the_only_month_of_a_year_clears_that_years_cached_charge(monkeypatch):
    db = _setup(monkeypatch)
    asset = _create()
    fa.post_depreciation(asset["id"], DepreciationIn(period="2025-04"), CALLER)
    assert _row(db, asset["id"])["depreciation_fy"] == "2025-26"

    fa.reverse_depreciation(asset["id"], "2025-04", CALLER)
    row = _row(db, asset["id"])
    assert row["depreciation_fy"] is None
    assert row["depreciation_fy_start_accum_paise"] is None


# ─────────────────────────── deletion ───────────────────────────

def test_an_asset_created_by_mistake_is_soft_deleted_and_its_journal_reversed(monkeypatch):
    db = _setup(monkeypatch)
    asset = _create()

    res = fa.delete_asset(asset["id"], CALLER)
    assert res["success"] is True

    row = _row(db, asset["id"])                     # the ROW is still there
    assert row["deleted_at"] is not None
    assert row["deleted_by"] == "u1"
    entries = {e["id"]: e for e in db.rows("journal_entries")}
    assert entries[asset["journal_entry_id"]]["is_reversed"] is True


def test_a_deleted_asset_is_gone_from_the_register(monkeypatch):
    db = _setup(monkeypatch)
    asset = _create()
    fa.delete_asset(asset["id"], CALLER)
    listed = fa.list_assets("CLI", True, CALLER)["data"]
    assert [a["id"] for a in listed] == []


def test_a_deleted_asset_keeps_its_code_so_the_next_one_cannot_take_it(monkeypatch):
    """FA-ACQ-{code} is the acquisition journal's reference and the kernel
    dedupes on (client_id, reference_no, entry_date). Hand the code on and the
    next asset's acquisition lands on the deleted one's entry."""
    db = _setup(monkeypatch)
    first = _create()
    assert first["asset_code"] == "FA-0001"
    fa.delete_asset(first["id"], CALLER)

    second = _create()
    assert second["asset_code"] == "FA-0002"
    assert second["journal_entry_id"] != first["journal_entry_id"]


def test_a_deleted_asset_cannot_be_reached_again(monkeypatch):
    _setup(monkeypatch)
    asset = _create()
    fa.delete_asset(asset["id"], CALLER)
    for call in (lambda: _patch(asset["id"], asset_name="x"),
                 lambda: fa.delete_asset(asset["id"], CALLER),
                 lambda: fa.reverse_depreciation(asset["id"], "2025-04", CALLER)):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 404


def test_deleting_a_depreciated_asset_is_refused_and_names_the_way_out(monkeypatch):
    _setup(monkeypatch)
    asset = _create()
    fa.post_depreciation(asset["id"], DepreciationIn(period="2025-04"), CALLER)
    with pytest.raises(HTTPException) as exc:
        fa.delete_asset(asset["id"], CALLER)
    assert exc.value.status_code == 422
    assert "2025-04" in exc.value.detail


# ───────────────────── the guards every write here keeps ─────────────────────

def test_an_unassigned_caller_cannot_correct_or_delete_another_book(monkeypatch):
    _setup(monkeypatch)
    asset = _create()
    # core.authz reads its own _USE_MOCK at import and short-circuits to True;
    # what is under test here is that the ENDPOINT consults the check and
    # answers 404 either way, not authz's own resolution.
    monkeypatch.setattr(fa, "can_access_client",
                        lambda user, cid: cid in (user.get("assigned_client_ids") or ["CLI"]))
    for call in (lambda: _patch(asset["id"], caller=OTHER, asset_name="x"),
                 lambda: fa.delete_asset(asset["id"], OTHER),
                 lambda: fa.reverse_depreciation(asset["id"], "2025-04", OTHER)):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 404
        assert exc.value.detail == "Asset not found"


def test_a_locked_year_refuses_the_correction_with_its_own_sentence(monkeypatch):
    db = _setup(monkeypatch)
    asset = _create()
    db.table("firms").update({"locked_financial_years": ["2025-26"]}).eq("id", FIRM).execute()

    with pytest.raises(HTTPException) as exc:
        _patch(asset["id"], purchase_cost_paise=1_00_000_00)
    assert exc.value.status_code == 422
    assert "2025-26" in exc.value.detail


def test_a_filed_return_covering_the_date_refuses_the_deletion(monkeypatch):
    db = _setup(monkeypatch)
    asset = _create()
    db.seed("filings", {"firm_id": FIRM, "client_id": "CLI", "filing_type": "GSTR-3B",
                        "period_start": "2025-04-01", "period_end": "2025-04-30",
                        "filed_date": "2025-05-18"})
    with pytest.raises(HTTPException) as exc:
        fa.delete_asset(asset["id"], CALLER)
    assert exc.value.status_code == 422
    assert "GSTR-3B" in exc.value.detail
