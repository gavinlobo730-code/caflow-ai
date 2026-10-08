"""
accounting-18 — a migrated client's fixed-asset register arrives WITH the depreciation
each asset already carries.

WHAT WAS MISSING
    The register could take an asset one way: `POST /api/fixed-assets`, which
    starts accumulated depreciation at nil and posts a fresh acquisition journal.
    `accumulated_depreciation_paise` had no writable door at all, so a client
    arriving from Tally with a hundred part-depreciated assets could be given
    their position only by letting the runner charge every month since the
    purchase date on top of the balance the opening trial balance already
    carries — and the audit's premise, "assets carried over mid-life are already
    supported one by one", was wrong: only the first-posting-may-start-late rule
    (FA-04) existed, and it states no position.

WHAT THESE PIN
    * the register that arrives has the file's own totals — cost and accumulated
      depreciation — and every asset is stored as stated;
    * NOTHING is posted: no journal entry, no acquisition, no second write path;
    * the next depreciation run starts the month after the stated position, from
      the stated written-down value, and never charges the history again;
    * `GET /register-integrity` reports nothing new for such a register — an
      opening asset has no acquisition journal BY DESIGN — while an ordinary asset
      without one is still reported;
    * the position is a financial-year end and a mid-year one is refused with the
      way round; a date that has not happened is refused;
    * the row is judged by the SAME rules the single form applies (category,
      basis, the asset-code shape), and a bad row lists EVERY problem;
    * uploading the same file again records nothing twice, even after a
      depreciation run has moved the accumulated figure; the same code on
      anything else is refused and says what it clashes with;
    * a wrong import is removable: an untouched opening asset can be deleted (and
      is not asked about a closed period, since nothing moves), the first month
      after a position reverses back TO the position and not to "never
      depreciated", and a cost correction is refused rather than posting an
      acquisition for an asset the opening balances already carry.
"""
from __future__ import annotations

import ast
import re
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException

import routers.fixed_assets as fa
from domain.fixed_assets import asset_code as asset_code_rule
from domain.fixed_assets import integrity as fa_integrity
from domain.fixed_assets import opening_register as reg
from domain.fixed_assets import schedule_ii
from models.accounting import (DepreciationIn, DepreciationRunIn, FixedAssetIn,
                               FixedAssetUpdateIn)
from services import opening_register_service as svc
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e

API_ROOT = Path(__file__).resolve().parents[1]
FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth", "email": "ca@f.test",
          "role": "Partner"}
AS_AT = date(2026, 3, 31)
TODAY = date(2026, 10, 1)


def R(i=1, **over) -> reg.ImportRow:
    base = dict(row=i, asset_code=f"TAG-{i:03d}", asset_name=f"Machine {i}",
                asset_category="Plant & Machinery", purchase_date="12-06-2021",
                cost_paise=1_00_000_00, accumulated_depreciation_paise=40_000_00,
                salvage_value_paise=0, depreciation_method="WDV",
                useful_life_years="", wdv_rate_percent="", it_block_key="",
                location="", notes="", put_to_use_date="")
    base.update(over)
    return reg.ImportRow(**base)


def plan(rows, existing=None, as_at=AS_AT):
    return reg.plan(rows if isinstance(rows, list) else [rows], existing or {}, as_at=as_at)


def one(row, existing=None):
    [v] = plan([row], existing)
    return v


# ── the position date ────────────────────────────────────────────────────────

def test_a_position_is_a_financial_year_end():
    d, why = reg.position_problem("31-03-2026", TODAY)
    assert d == AS_AT and why is None
    assert reg.position_problem("2026-03-31", TODAY)[0] == AS_AT


@pytest.mark.parametrize("text", ["30-09-2026", "30-04-2026", "01-04-2026", "28-02-2026"])
def test_a_mid_year_position_is_refused_with_the_way_round(text):
    d, why = reg.position_problem(text, TODAY)
    assert d is None
    assert "31 March" in why and "runner" in why and "opening written-down value" in why


@pytest.mark.parametrize("text,fragment", [
    ("", "blank"), ("soon", "not a date"), ("31/3/26", "two-digit year"),
    ("31-02-2026", "February 2026 has 28 days"), ("31/13/2026", "there is no month 13"),
])
def test_a_position_that_is_not_a_date_is_refused(text, fragment):
    d, why = reg.position_problem(text, TODAY)
    assert d is None and fragment in why
    if fragment != "two-digit year":
        assert "two-digit year" not in why, why


def test_a_position_that_has_not_happened_is_refused():
    d, why = reg.position_problem("31-03-2099", TODAY)
    assert d is None and "future" in why


def test_the_next_run_starts_the_month_after_the_position():
    assert reg.next_depreciation_month(AS_AT) == "2026-04"
    assert reg.next_depreciation_month(date(2025, 12, 31)) == "2026-01"


# ── a good row ───────────────────────────────────────────────────────────────

def test_a_good_row_is_new_and_stored_exactly_as_stated():
    v = one(R(accumulated_depreciation_paise=41_234_56, it_block_key=" PM15 ", location="Bay 2"))
    assert v.status == reg.NEW and not v.problems
    p = v.planned
    assert (p.asset_code, p.purchase_date, p.purchase_cost_paise) == ("TAG-001", "2021-06-12", 1_00_000_00)
    assert p.accumulated_depreciation_paise == 41_234_56
    assert p.current_wdv_paise == 1_00_000_00 - 41_234_56
    row = p.as_row()
    # "posted through" the position is what makes the next run start after it.
    assert row["depreciation_posted_through"] == row["opening_position_date"] == "2026-03-31"
    assert row["it_block_key"] == "PM15" and row["location"] == "Bay 2"
    # NOT a column of an opening asset: there is no acquisition, and the asset
    # says so by what is absent.
    assert "journal_entry_id" not in row and "acquisition_mode" not in row


def test_the_basis_is_the_one_the_single_form_resolves():
    default = schedule_ii.default_class("Plant & Machinery")
    p = one(R()).planned
    assert p.wdv_rate_percent == float(default["wdv_rate_percent"])
    assert p.useful_life_years == default["useful_life_years"]
    sl = one(R(2, asset_category="Office Equipment", depreciation_method="SLM")).planned
    assert sl.depreciation_method == "SL" and sl.useful_life_years == 5


def test_land_needs_no_method_and_is_never_depreciated():
    v = one(R(asset_category="Land", depreciation_method="", accumulated_depreciation_paise=0))
    assert v.status == reg.NEW
    assert v.planned.wdv_rate_percent == 0.0
    bad = one(R(asset_category="Land", depreciation_method="", accumulated_depreciation_paise=5))
    assert bad.status == reg.REJECTED and "never depreciated" in bad.sentence


def test_a_category_with_no_prescribed_life_is_refused_in_the_single_forms_own_words():
    v = one(R(asset_category="Intangibles", depreciation_method="WDV"))
    assert v.status == reg.REJECTED
    assert schedule_ii.no_statutory_basis("Intangibles", "WDV") in v.problems
    assert fa._no_statutory_basis("Intangibles", "WDV") == schedule_ii.no_statutory_basis("Intangibles", "WDV")
    # Stating the figure is what the sentence asks for, and it then goes through.
    ok = one(R(asset_category="Intangibles", depreciation_method="SL", useful_life_years="5"))
    assert ok.status == reg.NEW and ok.planned.useful_life_years == 5


def test_a_rate_that_departs_from_schedule_ii_is_allowed_and_warned_in_the_integrity_checks_words():
    v = one(R(wdv_rate_percent="15%"))                      # the Income-tax Act's rate
    assert v.status == reg.NEW and v.planned.wdv_rate_percent == 15.0
    asked = fa_integrity.schedule_ii_departure(v.planned.register_row())
    assert asked and asked["what_it_means"] in v.warnings


def test_a_percentage_that_looks_like_an_excel_percent_cell_is_flagged():
    v = one(R(wdv_rate_percent="0.15"))
    assert v.status == reg.NEW
    assert any("0.15%" in w and "percentage cell" in w for w in v.warnings)


# ── what is refused ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("over,fragment", [
    (dict(accumulated_depreciation_paise=None), "accumulated depreciation is not an amount"),
    (dict(cost_paise=None), "cost is not an amount"),
    (dict(cost_paise=0), "cost is nil"),
    (dict(accumulated_depreciation_paise=-1), "cannot be negative"),
    (dict(accumulated_depreciation_paise=1_00_000_01), "more than the cost"),
    (dict(salvage_value_paise=None), "salvage value is not an amount"),
    (dict(salvage_value_paise=1_00_000_00), "not below the cost"),
    (dict(salvage_value_paise=10_000_00, accumulated_depreciation_paise=95_000_00),
     "takes the asset below its salvage value"),
])
def test_money_that_cannot_be_a_position_is_refused_by_row(over, fragment):
    v = one(R(**over))
    assert v.status == reg.REJECTED and fragment in v.sentence, v.sentence
    assert v.row == 1


def test_a_blank_accumulated_depreciation_is_not_read_as_nil():
    """The column header that did not match would otherwise arrive as a hundred
    assets that have never been depreciated, to be charged from scratch."""
    v = one(R(accumulated_depreciation_paise=None))
    assert v.status == reg.REJECTED
    nil = one(R(accumulated_depreciation_paise=0))
    assert nil.status == reg.NEW and nil.planned.accumulated_depreciation_paise == 0


@pytest.mark.parametrize("text,fragment", [
    ("", "method is blank"), ("declining", "not a depreciation method"),
])
def test_the_method_is_stated_not_assumed(text, fragment):
    v = one(R(depreciation_method=text))
    assert v.status == reg.REJECTED and fragment in v.sentence


@pytest.mark.parametrize("text,want", [
    ("WDV", "WDV"), ("wdv", "WDV"), ("Written Down Value", "WDV"),
    ("SL", "SL"), ("SLM", "SL"), ("Straight Line", "SL"),
])
def test_the_spellings_a_tally_export_uses_are_read(text, want):
    v = one(R(asset_category="Office Equipment", depreciation_method=text))
    assert v.status == reg.NEW and v.planned.depreciation_method == want


@pytest.mark.parametrize("life,rate,fragment", [
    ("0", "", "useful life"), ("abc", "", "useful life"), ("101", "", "useful life"),
    ("", "150", "more than 100"), ("", "13.915", "WDV rate"), ("", "fifteen", "WDV rate"),
])
def test_a_life_or_rate_that_is_not_one_is_refused(life, rate, fragment):
    v = one(R(useful_life_years=life, wdv_rate_percent=rate))
    assert v.status == reg.REJECTED and fragment in v.sentence, v.sentence


def test_an_unknown_category_names_the_ones_this_register_holds():
    v = one(R(asset_category="Computers"))
    assert v.status == reg.REJECTED
    for c in schedule_ii.CATEGORIES:
        assert c in v.sentence
    assert one(R(asset_category="  plant & machinery ")).status == reg.NEW      # folded, not fuzzy
    assert one(R(asset_category="Plant and Machinery")).status == reg.REJECTED


def test_an_asset_bought_after_the_position_is_an_addition_not_an_opening_balance():
    v = one(R(purchase_date="02-04-2026"))
    assert v.status == reg.REJECTED
    assert "after the position date" in v.sentence and "Add Asset" in v.sentence
    assert one(R(purchase_date="31-03-2026")).status == reg.NEW


@pytest.mark.parametrize("text,reason", [
    ("", "is blank"), ("soon", "for example 15-03-2025"), ("4/1/26", "two-digit year"),
    ("31-02-2026", "February 2026 has 28 days"),
])
def test_a_purchase_date_that_cannot_be_read_with_certainty_is_refused(text, reason):
    v = one(R(purchase_date=text))
    assert v.status == reg.REJECTED and "purchase date" in v.sentence
    assert reason in v.sentence, v.sentence
    assert ("two-digit year" in v.sentence) == (reason == "two-digit year"), v.sentence


@pytest.mark.parametrize("text,reason", [
    ("soon", "for example 15-03-2025"), ("4/1/26", "two-digit year"),
    ("31-02-2021", "February 2021 has 28 days"),
])
def test_a_put_to_use_date_that_cannot_be_read_says_why(text, reason):
    v = one(R(put_to_use_date=text))
    assert v.status == reg.REJECTED and "put-to-use date" in v.sentence
    assert reason in v.sentence, v.sentence


def test_a_put_to_use_date_is_never_taken_from_the_purchase_date():
    assert one(R()).planned.put_to_use_date is None
    assert one(R(put_to_use_date="01-07-2021")).planned.put_to_use_date == "2021-07-01"
    early = one(R(put_to_use_date="01-01-2021"))
    assert early.status == reg.REJECTED and "before it was bought" in early.sentence


def test_a_bad_row_lists_every_problem_at_once():
    """A file corrected one error at a time is a file uploaded nineteen times."""
    v = one(R(asset_code="", asset_name="", asset_category="Computers", purchase_date="soon",
              cost_paise=None, accumulated_depreciation_paise=None, depreciation_method=""))
    assert v.status == reg.REJECTED
    for fragment in ("asset code is blank", "asset name is blank", "not an asset category",
                     "purchase date", "cost is not an amount", "accumulated depreciation is not an amount",
                     "method is blank"):
        assert fragment in v.sentence, (fragment, v.sentence)


# ── the code ─────────────────────────────────────────────────────────────────

def test_two_rows_of_one_file_cannot_share_a_code_and_case_is_not_a_difference():
    a, b, c = plan([R(1, asset_code="TAG-1"), R(2, asset_code="tag-1"), R(3, asset_code="TAG-2")])
    assert a.status == reg.NEW and c.status == reg.NEW
    assert b.status == reg.REJECTED and "row 1" in b.sentence


def test_the_generated_shape_is_refused_in_the_words_the_single_form_uses():
    v = one(R(asset_code="FA-0007"))
    assert v.status == reg.REJECTED
    assert asset_code_rule.problem_with("FA-0007") in v.problems
    # ONE rule, two doors: the single form's validator says exactly this.
    with pytest.raises(ValueError) as exc:
        FixedAssetIn(client_id="C", asset_name="x", purchase_date="2026-01-01",
                     purchase_cost_paise=1, asset_code="FA-0007")
    assert asset_code_rule.problem_with("FA-0007") in str(exc.value)
    assert FixedAssetIn(client_id="C", asset_name="x", purchase_date="2026-01-01",
                        purchase_cost_paise=1, asset_code="  ").asset_code is None


# ── a re-upload ──────────────────────────────────────────────────────────────

def _held(**over):
    base = {"id": "A1", "asset_code": "TAG-001", "asset_name": "Machine 1",
            "asset_category": "Plant & Machinery", "purchase_date": "2021-06-12",
            "purchase_cost_paise": 1_00_000_00, "opening_position_date": "2026-03-31",
            "deleted_at": None}
    base.update(over)
    return {"tag-001": base}


def test_the_same_asset_again_is_already_recorded_even_after_its_depreciation_moved():
    v = one(R(), _held())
    assert v.status == reg.ALREADY_RECORDED and v.existing_id == "A1" and not v.problems
    # The file says 40,000 and the register now holds more — accumulated depreciation
    # is NOT part of the identity, or a re-upload after a run would be refused.
    assert one(R(accumulated_depreciation_paise=12_345_00), _held()).status == reg.ALREADY_RECORDED


@pytest.mark.parametrize("held,fragment", [
    (dict(purchase_cost_paise=2_00_000_00), "its cost is"),
    (dict(asset_name="Lathe"), "named"),
    (dict(purchase_date="2020-01-01"), "bought on 2020-01-01"),
    (dict(asset_category="Vehicles"), "it is a Vehicles"),
    (dict(opening_position_date="2025-03-31"), "stated as at 2025-03-31"),
])
def test_the_same_code_on_something_else_is_refused_and_says_what_differs(held, fragment):
    v = one(R(), _held(**held))
    assert v.status == reg.REJECTED and fragment in v.sentence, v.sentence
    assert "Nothing is overwritten" in v.sentence


def test_a_code_held_by_an_ordinary_asset_is_never_overwritten():
    v = one(R(), _held(opening_position_date=None))
    assert v.status == reg.REJECTED and "Add Asset" in v.sentence


def test_a_code_held_by_a_deleted_asset_is_still_held():
    v = one(R(), _held(deleted_at="2026-05-01T00:00:00+00:00"))
    assert v.status == reg.REJECTED and "deleted" in v.sentence


# ── the register-integrity rules ─────────────────────────────────────────────

def test_an_opening_asset_is_not_reported_as_missing_its_acquisition_journal():
    """The negative half is the other test below: the SAME asset without the
    position date IS reported, so the exemption is the fact and not a blanket."""
    p = one(R()).planned
    assert fa_integrity.register_findings([p.register_row()], set()) == []


def test_an_ordinary_asset_with_no_journal_is_still_reported():
    row = one(R()).planned.register_row()
    row["opening_position_date"] = None
    kinds = [f["kind"] for f in fa_integrity.register_findings([row], set())]
    assert kinds == ["no_acquisition_journal"]


def test_both_integrity_fetchers_select_the_fact_the_exemption_reads():
    assert "opening_position_date" in fa_integrity.COLUMNS


# ── the summary ──────────────────────────────────────────────────────────────

def test_the_summary_adds_up_what_would_land_and_names_what_it_cannot_see():
    vs = plan([R(1), R(2, asset_category="Land", depreciation_method="", accumulated_depreciation_paise=0,
                      it_block_key="LAND"),
               R(3, asset_code="BAD", cost_paise=None), R(4, put_to_use_date="01-07-2021")], _held())
    s = reg.summarise(vs)
    # Row 1 is the asset the register already holds, row 3 is refused, rows 2 and 4
    # would land — and only those two are in the totals.
    assert (s.received, s.new, s.already_recorded, s.rejected) == (4, 2, 1, 1)
    assert s.cost_paise == 2 * 1_00_000_00
    assert s.accumulated_paise == 40_000_00
    # Land is never depreciated and row 4 states its date, so neither is "missing" one.
    assert not any("put-to-use" in g for g in s.gaps)
    cats = {b["asset_category"]: b for b in s.by_category}
    assert set(cats) == {"Land", "Plant & Machinery"}
    assert all(b["net_paise"] == b["cost_paise"] - b["accumulated_paise"] for b in cats.values())
    assert s.net_paise == s.cost_paise - s.accumulated_paise


def test_the_gaps_are_named_not_defaulted():
    vs = plan([R(1), R(2, it_block_key="PM15", put_to_use_date="01-07-2021")])
    gaps = reg.summarise(vs).gaps
    assert any("1 depreciable asset has no put-to-use date" in g for g in gaps)
    assert any("1 asset is in no Income-tax Act s.32 block" in g for g in gaps)


def test_every_answer_says_nothing_was_posted():
    assert "Nothing was posted to the ledger" in reg.NOTHING_IS_POSTED
    assert "count the same cost twice" in reg.NOTHING_IS_POSTED


# ── the world: the real router, service and depreciation engine ──────────────

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
            "account_type": "Asset", "is_active": True})
    return db


def _body(rows, as_at="31-03-2026", dry_run=False):
    return fa.OpeningRegisterIn(
        client_id="CLI", as_at=as_at, dry_run=dry_run,
        rows=[fa.OpeningAssetRowIn(**{k: (v if k.endswith("_paise") or k == "row"
                                           else (v or None)) for k, v in r.__dict__.items()})
              for r in rows])


def _import(rows, **kw):
    res = fa.import_opening_register(_body(rows, **kw), CALLER)
    assert res["success"] is True, res
    return res["data"]


def _file(n=100):
    """n assets over five classes, every figure distinct so a total can be wrong."""
    rows = []
    for i in range(1, n + 1):
        kind = i % 5
        common = dict(row=i, asset_code=f"TAG-{i:03d}", asset_name=f"Asset {i}",
                      purchase_date="12-06-2021")
        cost = 1_00_000_00 + i * 1_000_00
        if kind == 0:
            rows.append(R(**common, asset_category="Plant & Machinery", depreciation_method="WDV",
                          cost_paise=cost, accumulated_depreciation_paise=cost // 3 + i))
        elif kind == 1:
            rows.append(R(**common, asset_category="Office Equipment", depreciation_method="SL",
                          cost_paise=cost, accumulated_depreciation_paise=cost // 2 + i))
        elif kind == 2:
            rows.append(R(**common, asset_category="Vehicles", depreciation_method="WDV",
                          cost_paise=cost, accumulated_depreciation_paise=cost // 4 + i))
        elif kind == 3:
            rows.append(R(**common, asset_category="Land", depreciation_method="",
                          cost_paise=cost, accumulated_depreciation_paise=0))
        else:
            rows.append(R(**common, asset_category="Intangibles", depreciation_method="SL",
                          useful_life_years="5", cost_paise=cost,
                          accumulated_depreciation_paise=cost // 5 + i))
    return rows


def test_a_100_asset_register_arrives_with_the_files_own_totals(monkeypatch):
    db = _setup(monkeypatch)
    rows = _file(100)
    out = _import(rows)
    assert out["received"] == 100 and out["created"] == 100 and out["rejected"] == 0
    stored = db.rows("fixed_assets")
    assert len(stored) == 100
    # The register's totals ARE the file's totals, to the paise.
    assert sum(a["purchase_cost_paise"] for a in stored) == sum(r.cost_paise for r in rows)
    assert (sum(a["accumulated_depreciation_paise"] for a in stored)
            == sum(r.accumulated_depreciation_paise for r in rows))
    assert out["cost_paise"] == sum(r.cost_paise for r in rows)
    assert out["accumulated_paise"] == sum(r.accumulated_depreciation_paise for r in rows)
    assert out["net_paise"] == out["cost_paise"] - out["accumulated_paise"]
    # Each asset carries ITS OWN figure, not an average.
    by_code = {a["asset_code"]: a for a in stored}
    for r in rows:
        assert by_code[r.asset_code]["accumulated_depreciation_paise"] == r.accumulated_depreciation_paise
        assert by_code[r.asset_code]["current_wdv_paise"] == r.cost_paise - r.accumulated_depreciation_paise
        assert str(by_code[r.asset_code]["depreciation_posted_through"]) == "2026-03-31"
        assert str(by_code[r.asset_code]["opening_position_date"]) == "2026-03-31"
    assert out["next_depreciation_month"] == "2026-04"
    assert "Nothing was posted to the ledger" in out["ledger_note"]
    assert sum(b["assets"] for b in out["by_category"]) == 100


def test_nothing_is_posted_to_the_ledger(monkeypatch):
    db = _setup(monkeypatch)
    before = (len(db.rows("journal_entries")), len(db.rows("journal_lines")))
    _import(_file(20))
    assert (len(db.rows("journal_entries")), len(db.rows("journal_lines"))) == before
    assert all(not a.get("journal_entry_id") for a in db.rows("fixed_assets"))
    assert all(a.get("acquisition_mode") is None for a in db.rows("fixed_assets"))


def test_register_integrity_reports_nothing_new_for_that_register(monkeypatch):
    db = _setup(monkeypatch)
    _import(_file(100))
    res = fa.register_integrity("CLI", CALLER)["data"]
    assert res["checked"] == 100
    assert res["findings"] == [] and res["clean"] is True


def test_the_next_depreciation_run_starts_from_the_stated_position(monkeypatch):
    db = _setup(monkeypatch)
    out = _import([R(1, cost_paise=1_00_000_00, accumulated_depreciation_paise=40_000_00,
                     wdv_rate_percent="15")])
    asset_id = out["rows"][0]["id"]

    res = fa.post_depreciation(asset_id, DepreciationIn(period="2026-04"), CALLER)["data"]
    # 15% of the STATED written-down value (₹60,000), a twelfth of it — not of cost,
    # and not of a value rebuilt from five years of charges nobody posted.
    assert res["depreciation_paise"] == (60_000_00 * 15 // 100) // 12
    assert res["new_accumulated"] == 40_000_00 + res["depreciation_paise"]
    assert res["foreclosed_months"] == [] and res["foreclosure_notice"] == ""
    assert len(db.rows("journal_entries")) == 1, "the one depreciation entry — no acquisition, no history"

    # And it cannot be started anywhere else: the month after is the only one open.
    other = _import([R(2, asset_code="TAG-002", cost_paise=1_00_000_00,
                       accumulated_depreciation_paise=40_000_00, wdv_rate_percent="15")])
    with pytest.raises(HTTPException) as exc:
        fa.post_depreciation(other["rows"][0]["id"], DepreciationIn(period="2026-06"), CALLER)
    assert exc.value.status_code == 422 and "2026-04" in exc.value.detail


def test_the_range_runner_charges_only_the_months_since_the_position(monkeypatch):
    db = _setup(monkeypatch)
    _import([R(1, purchase_date="12-06-2019", wdv_rate_percent="15")])
    # A range that reaches back to the purchase must not charge the history: every
    # month up to the position is already posted, by statement.
    res = fa.run_depreciation(DepreciationRunIn(
        client_id="CLI", from_period="2019-06", to_period="2026-06"), CALLER)["data"]
    assert res["months_posted"] == 3
    refs = sorted(e["reference_no"] for e in db.rows("journal_entries"))
    assert len(refs) == 3 and refs[0].endswith("2026-04") and refs[-1].endswith("2026-06")


def test_reversing_the_first_month_rolls_back_to_the_position_not_to_never(monkeypatch):
    db = _setup(monkeypatch)
    out = _import([R(1, wdv_rate_percent="15")])
    asset_id = out["rows"][0]["id"]
    fa.post_depreciation(asset_id, DepreciationIn(period="2026-04"), CALLER)

    fa.reverse_depreciation(asset_id, "2026-04", CALLER)
    row = next(a for a in db.rows("fixed_assets") if a["id"] == asset_id)
    assert str(row["depreciation_posted_through"]) == "2026-03-31", (
        "the mark must return TO the position — cleared, the next run starts at the "
        "purchase month and charges the history again")
    assert row["accumulated_depreciation_paise"] == 40_000_00
    assert row["depreciation_fy"] is None

    again = fa.post_depreciation(asset_id, DepreciationIn(period="2026-04"), CALLER)["data"]
    assert again["depreciation_paise"] > 0 and again["foreclosed_months"] == []
    assert again["new_accumulated"] == 40_000_00 + again["depreciation_paise"]


def test_a_re_upload_posts_nothing_twice_even_after_a_run_moved_the_figure(monkeypatch):
    db = _setup(monkeypatch)
    rows = _file(30)
    first = _import(rows)
    fa.run_depreciation(DepreciationRunIn(client_id="CLI", from_period="2026-04",
                                          to_period="2026-04"), CALLER)
    again = _import(rows)
    assert first["created"] == 30
    assert again["created"] == 0 and again["already_recorded"] == 30 and again["rejected"] == 0
    assert len(db.rows("fixed_assets")) == 30


def test_a_dry_run_writes_nothing_and_reports_what_would_land(monkeypatch):
    db = _setup(monkeypatch)
    out = _import(_file(10), dry_run=True)
    assert db.rows("fixed_assets") == []
    assert out["created"] == 0 and out["would_create"] == 10
    assert out["cost_paise"] > 0
    assert {r["status"] for r in out["rows"]} == {"would_create"}


def test_the_good_rows_land_and_the_bad_ones_are_named(monkeypatch):
    db = _setup(monkeypatch)
    rows = _file(10)
    rows[3] = R(4, asset_code="TAG-004", asset_category="Computers")
    out = _import(rows)
    assert out["created"] == 9 and out["rejected"] == 1
    bad = [r for r in out["rows"] if r["status"] == "rejected"]
    assert [b["row"] for b in bad] == [4] and "not an asset category" in " ".join(bad[0]["problems"])
    assert len(db.rows("fixed_assets")) == 9


def test_a_chunk_the_database_refuses_is_retried_one_asset_at_a_time(monkeypatch):
    db = _setup(monkeypatch)
    real = svc._write

    def flaky(db_, firm, client, planned):
        if any(p.asset_code == "TAG-007" for p in planned):
            raise RuntimeError('duplicate key value violates unique constraint "fixed_assets_code"')
        return real(db_, firm, client, planned)

    monkeypatch.setattr(svc, "_write", flaky)
    out = _import(_file(12))
    assert out["created"] == 11 and out["rejected"] == 1
    bad = next(r for r in out["rows"] if r["status"] == "rejected")
    assert bad["asset_code"] == "TAG-007" and bad["row"] == 7
    assert out["cost_paise"] == sum(a["purchase_cost_paise"] for a in db.rows("fixed_assets"))


def test_a_mid_year_position_is_refused_before_anything_is_judged(monkeypatch):
    db = _setup(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        fa.import_opening_register(_body(_file(3), as_at="30-09-2026"), CALLER)
    assert exc.value.status_code == 422 and "31 March" in exc.value.detail
    assert db.rows("fixed_assets") == []


def test_the_insert_writes_exactly_the_columns_the_plan_defines(monkeypatch):
    db = _setup(monkeypatch)
    out = _import([R(1, it_block_key="PM15", location="Bay 2", notes="n", put_to_use_date="01-07-2021")])
    stored = next(a for a in db.rows("fixed_assets") if a["id"] == out["rows"][0]["id"])
    planned = one(R(1, it_block_key="PM15", location="Bay 2", notes="n",
                    put_to_use_date="01-07-2021")).planned.as_row()
    written = set(stored) - {"id", "is_disposed", "corrections_count"}
    assert written == set(planned) | {"firm_id", "client_id"}, (
        written ^ (set(planned) | {"firm_id", "client_id"}))
    for k, v in planned.items():
        assert stored[k] == v, k


# ── removing and correcting an opening asset ─────────────────────────────────

def _opening(monkeypatch, **over):
    db = _setup(monkeypatch)
    out = _import([R(1, wdv_rate_percent="15", purchase_date="12-06-2019", **over)])
    return db, out["rows"][0]["id"]


def test_an_untouched_opening_asset_can_be_deleted_and_its_code_stays_held(monkeypatch):
    db, asset_id = _opening(monkeypatch)
    res = fa.delete_asset(asset_id, CALLER)
    assert res["success"] is True and res["data"]["acquisition_reversed"] is False
    row = next(a for a in db.rows("fixed_assets") if a["id"] == asset_id)
    assert row["deleted_at"] is not None and row["asset_code"] == "TAG-001"
    assert db.rows("journal_entries") == [], "nothing was posted for it, so nothing is reversed"
    # The code is still owned, so the corrected file cannot reuse it and is told so.
    again = _import([R(1)])
    assert again["rejected"] == 1 and "deleted" in " ".join(again["rows"][0]["problems"])


def test_deleting_an_untouched_opening_asset_is_not_asked_about_a_closed_period(monkeypatch):
    """Its purchase date is years inside closed years and nothing moves in the
    ledger — a wrong import must never be made permanent by that."""
    db, asset_id = _opening(monkeypatch)

    def closed(*a, **k):
        raise HTTPException(status_code=423, detail="the year is closed")

    monkeypatch.setattr(fa.period_lock_service, "assert_open", closed)
    assert fa.delete_asset(asset_id, CALLER)["success"] is True


def test_an_opening_asset_depreciated_since_must_be_reversed_before_it_is_deleted(monkeypatch):
    db, asset_id = _opening(monkeypatch)
    fa.post_depreciation(asset_id, DepreciationIn(period="2026-04"), CALLER)
    with pytest.raises(HTTPException) as exc:
        fa.delete_asset(asset_id, CALLER)
    assert exc.value.status_code == 422 and "2026-04" in exc.value.detail
    fa.reverse_depreciation(asset_id, "2026-04", CALLER)
    assert fa.delete_asset(asset_id, CALLER)["success"] is True


def test_a_cost_correction_is_refused_and_posts_no_acquisition(monkeypatch):
    db, asset_id = _opening(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        fa.correct_asset(asset_id, FixedAssetUpdateIn(purchase_cost_paise=2_00_000_00), CALLER)
    assert exc.value.status_code == 422
    assert "opening balance" in exc.value.detail and "delete it" in exc.value.detail
    assert db.rows("journal_entries") == [], "an acquisition here would count the cost twice"
    row = next(a for a in db.rows("fixed_assets") if a["id"] == asset_id)
    assert row["purchase_cost_paise"] == 1_00_000_00


def test_a_name_and_a_location_can_still_be_corrected_on_an_opening_asset(monkeypatch):
    db, asset_id = _opening(monkeypatch)
    res = fa.correct_asset(asset_id, FixedAssetUpdateIn(asset_name="Lathe", location="Bay 9"), CALLER)
    assert res["success"] is True and res["data"]["acquisition_reposted"] is False
    row = next(a for a in db.rows("fixed_assets") if a["id"] == asset_id)
    assert row["asset_name"] == "Lathe" and row["location"] == "Bay 9"


# ── the door ─────────────────────────────────────────────────────────────────

def _http(role="Partner"):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.auth import get_current_user
    app = FastAPI()
    app.include_router(fa.router)
    user = dict(CALLER, role=role)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


def _json(rows, **over):
    body = {"client_id": "CLI", "as_at": "31-03-2026", "rows": [
        {"row": r.row, "asset_code": r.asset_code, "asset_name": r.asset_name,
         "asset_category": r.asset_category, "purchase_date": r.purchase_date,
         "cost_paise": r.cost_paise,
         "accumulated_depreciation_paise": r.accumulated_depreciation_paise,
         "depreciation_method": r.depreciation_method,
         "useful_life_years": r.useful_life_years,
         "wdv_rate_percent": r.wdv_rate_percent} for r in rows]}
    body.update(over)
    return body


def test_the_position_date_is_required_by_the_door_so_none_is_assumed():
    http = _http()
    body = _json([R()])
    del body["as_at"]
    assert http.post("/api/fixed-assets/opening-register", json=body).status_code == 422


def test_a_role_that_cannot_write_accounting_cannot_import():
    assert _http("Reviewer").post("/api/fixed-assets/opening-register",
                                  json=_json([R()])).status_code == 403


def test_the_door_audits_the_import_once_and_a_re_upload_audits_nothing(monkeypatch):
    db = _setup(monkeypatch)
    events = []
    monkeypatch.setattr(fa, "log_event", lambda *a, **k: events.append((a, k)))
    http = _http()
    res = http.post("/api/fixed-assets/opening-register", json=_json(_file(5)))
    assert res.status_code == 200, res.text
    assert res.json()["data"]["created"] == 5 and len(events) == 1
    args, kwargs = events[0]
    assert args[3] == "opening_register_import" and kwargs["actor_id"] == "auth"
    assert len(kwargs["new_data"]["asset_codes"]) == 5
    again = http.post("/api/fixed-assets/opening-register", json=_json(_file(5))).json()["data"]
    assert again["created"] == 0 and again["already_recorded"] == 5 and len(events) == 1


def test_a_failed_audit_write_is_not_a_failed_import(monkeypatch):
    db = _setup(monkeypatch)
    monkeypatch.setattr(fa, "log_event", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("audit down")))
    res = _http().post("/api/fixed-assets/opening-register", json=_json(_file(3)))
    assert res.status_code == 200 and res.json()["data"]["created"] == 3
    assert len(db.rows("fixed_assets")) == 3


# ── structure ────────────────────────────────────────────────────────────────

def _names(path: str) -> set[str]:
    tree = ast.parse((API_ROOT / path).read_text(encoding="utf-8"))
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            names.add(n.id)
        elif isinstance(n, ast.Attribute):
            names.add(n.attr)
        elif isinstance(n, ast.alias):
            names.add(n.name.split(".")[-1])
    return names


def test_the_import_reaches_no_posting_path():
    """One posting kernel, and this is not it: the register is the breakup of
    balances the opening balances carry."""
    forbidden = {"_create_journal", "journal_for_asset_acquisition", "journal_for_depreciation",
                 "manual_journal_service", "post_journal_atomic", "phase2_journal_service"}
    for path in ("services/opening_register_service.py",
                 "domain/fixed_assets/opening_register.py"):
        assert not (_names(path) & forbidden), path
    router_fn = next(n for n in ast.walk(ast.parse((API_ROOT / "routers/fixed_assets.py").read_text("utf-8")))
                     if isinstance(n, ast.FunctionDef) and n.name == "import_opening_register")
    called = {n.attr for n in ast.walk(router_fn) if isinstance(n, ast.Attribute)}
    assert not (called & forbidden)


def test_the_domain_module_holds_no_database_handle_and_no_clock():
    names = _names("domain/fixed_assets/opening_register.py")
    # `today` is a PARAMETER (the caller's clock), so the test is for the clocks
    # themselves and for anything that could reach a database.
    assert not ({"ist_today", "ist_now", "utcnow", "get_supabase", "get_service_supabase",
                 "fetch_all"} & names)
    src = (API_ROOT / "domain/fixed_assets/opening_register.py").read_text("utf-8")
    assert "date.today" not in src and "datetime.now" not in src and ".table(" not in src


def test_the_migration_adds_one_nullable_column_and_nothing_else():
    sql = next((API_ROOT / "migrations").glob("456_*.sql")).read_text("utf-8")
    code = re.sub(r"--[^\n]*", "", sql)
    code = re.sub(r"COMMENT ON COLUMN[^;]*;", "", code, flags=re.S)
    assert re.search(r"ADD COLUMN IF NOT EXISTS opening_position_date DATE\s*;", code)
    for word in ("DROP", "DELETE", "UPDATE", "NOT NULL", "DEFAULT", "CONSTRAINT", "INDEX", "GRANT"):
        assert word not in code.upper(), word
