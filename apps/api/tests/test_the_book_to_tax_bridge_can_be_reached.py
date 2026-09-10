"""
The second half of IT-09 ≡ FA-06: two engines that could not be reached.

WHAT WAS WRONG

`domain/income_tax/book_to_tax_bridge.py` was imported by NO ROUTER. Its own
docstring said the §32 depreciation line was usually the largest single
adjustment in the bridge and that nothing in this codebase computed it, and both
halves were true — so the one document a CA hands every business client, and an
assessing officer asks for, could not be produced at all.

WHAT THIS FILE PINS

The assembly, not the arithmetic. `tests/test_section_32_block_of_assets.py`
holds the engine to §32; this holds the service to WHERE EACH FACT COMES FROM:

  * additions and deletions DERIVED from the fixed-asset register, deletions at
    the MONEYS PAYABLE and not at cost (§43(6)(c)(i)(B));
  * the block, the rate, the opening written-down value, whether any asset
    remains, and the put-to-use date all STORED, because none is derivable;
  * an asset in no block NAMED rather than placed — there is no safe default,
    since the wrong block charges the wrong rate for the life of the asset and
    no block silently drops its cost;
  * and the bridge withholding the §32 line while any of that is outstanding,
    because assuming the two depreciation figures equal would make the bridge
    foot perfectly while understating the difference to nil.
"""
import pytest

import routers.income_tax as it
from services.section_32_service import fy_window, section_32_service
from tests.e2e_harness import FakeDB

FIRM, CLIENT = "firm-32", "client-32"
FY = "2025-26"
L = 1_00_000_00
CALLER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "auth-1", "role": "Partner"}


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    monkeypatch.setattr(it, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(it, "_db", lambda: d)
    return d


def _block(db, **kw):
    row = {"firm_id": FIRM, "client_id": CLIENT, "financial_year": FY,
           "block_key": "P&M 15%", "rate_percent": 15,
           "opening_wdv_paise": 10 * L, "assets_remain": True}
    row.update(kw)
    db.seed("income_tax_asset_blocks", row)
    return row


def _asset(db, **kw):
    row = {"id": kw.pop("id", f"a{len(db.rows('fixed_assets')) + 1}"),
           "firm_id": FIRM, "client_id": CLIENT, "deleted_at": None,
           "asset_code": "FA-001", "asset_name": "Lathe",
           "asset_category": "Plant & Machinery",
           "purchase_date": "2025-06-01", "purchase_cost_paise": 2 * L,
           "put_to_use_date": "2025-06-01", "it_block_key": "P&M 15%",
           "is_disposed": False, "disposal_date": None, "disposal_value_paise": 0}
    row.update(kw)
    db.seed("fixed_assets", row)
    return row


def _run(db):
    return section_32_service.assemble(db, FIRM, CLIENT, FY)


# ══════════════════════════════════════════════════════════════════════════════
# What is derived
# ══════════════════════════════════════════════════════════════════════════════

def test_the_financial_year_runs_april_to_march():
    assert fy_window("2025-26") == (__import__("datetime").date(2025, 4, 1),
                                    __import__("datetime").date(2026, 3, 31))


def test_a_purchase_in_the_year_is_an_addition(db):
    _block(db)
    _asset(db, purchase_date="2025-06-01", put_to_use_date="2025-06-01")
    got = _run(db)["blocks"][0]
    assert got["additions_full_rate_paise"] == 2 * L
    assert got["depreciation_paise"] == int(0.15 * 12 * L)


def test_a_purchase_in_an_earlier_year_is_already_in_the_opening_wdv(db):
    """It is not an addition of THIS year. Counting it again would depreciate
    the same cost twice."""
    _block(db)
    _asset(db, purchase_date="2022-06-01", put_to_use_date="2022-06-01")
    got = _run(db)["blocks"][0]
    assert got["additions_full_rate_paise"] == 0
    assert got["depreciation_paise"] == int(0.15 * 10 * L)


def test_a_disposal_reduces_the_block_by_the_MONEYS_PAYABLE(db):
    """§43(6)(c)(i)(B) — the sale consideration, not the asset's cost and not
    its book value."""
    _block(db)
    _asset(db, purchase_date="2022-06-01", purchase_cost_paise=8 * L,
           is_disposed=True, disposal_date="2025-09-01", disposal_value_paise=3 * L)
    got = _run(db)["blocks"][0]
    assert got["deletions_paise"] == 3 * L
    assert got["wdv_before_depreciation_paise"] == 7 * L


def test_a_disposal_in_an_earlier_year_is_not_this_years_deletion(db):
    _block(db)
    _asset(db, purchase_date="2020-06-01", is_disposed=True,
           disposal_date="2024-09-01", disposal_value_paise=3 * L)
    assert _run(db)["blocks"][0]["deletions_paise"] == 0


def test_the_put_to_use_date_is_read_and_never_the_purchase_date(db):
    """Bought in June, put to use in December: half the rate. Substituting the
    purchase date would allow the full rate on an asset the second proviso
    halves."""
    _block(db, opening_wdv_paise=0)
    _asset(db, purchase_date="2025-06-01", put_to_use_date="2025-12-01",
           purchase_cost_paise=10 * L)
    got = _run(db)["blocks"][0]
    assert got["additions_half_rate_paise"] == 10 * L
    assert got["depreciation_paise"] == int(0.075 * 10 * L)


def test_an_addition_with_no_put_to_use_date_is_a_gap_not_a_guess(db):
    _block(db, opening_wdv_paise=0)
    _asset(db, put_to_use_date=None, purchase_cost_paise=10 * L)
    got = _run(db)
    assert got["blocks"][0]["depreciation_paise"] == 0
    assert got["is_complete"] is False
    assert any("no put-to-use date" in g for g in got["statutory_gaps"])


# ══════════════════════════════════════════════════════════════════════════════
# What is refused
# ══════════════════════════════════════════════════════════════════════════════

def test_an_unclassified_asset_is_NAMED_not_placed(db):
    """There is no safe default. The wrong block charges the wrong rate on the
    wrong base for the life of the asset; no block silently drops its cost."""
    _block(db)
    _asset(db, id="a9", asset_code="FA-009", it_block_key=None,
           purchase_cost_paise=5 * L)
    got = _run(db)
    assert [u["asset_code"] for u in got["unclassified_assets"]] == ["FA-009"]
    assert got["blocks"][0]["additions_full_rate_paise"] == 0
    assert got["is_complete"] is False
    assert any("not assigned to a §32 block" in g for g in got["statutory_gaps"])


def test_an_unclassified_asset_from_an_EARLIER_year_is_not_this_years_problem(db):
    """It is already inside whatever opening written-down value somebody
    entered. Naming it here would be a gap the CA cannot close in this year."""
    _block(db)
    _asset(db, id="a9", it_block_key=None, purchase_date="2019-06-01",
           put_to_use_date="2019-06-01")
    got = _run(db)
    assert got["unclassified_assets"] == []
    assert got["is_complete"] is True


def test_a_block_with_assets_but_no_opening_wdv_is_omitted_and_named(db):
    """A zero is not the answer: it would allow no depreciation at all on a
    block that may have been running for a decade."""
    _asset(db, it_block_key="Computers 40%")
    got = _run(db)
    assert got["blocks"] == []
    assert got["blocks_without_opening_wdv"] == ["Computers 40%"]
    assert any("comes off last year's return" in g for g in got["statutory_gaps"])


def test_not_knowing_whether_assets_remain_is_carried_through(db):
    _block(db, assets_remain=None)
    got = _run(db)
    assert got["is_complete"] is False
    assert any("§50" in g for g in got["statutory_gaps"])


def test_additional_depreciation_is_never_inferred_from_the_register(db):
    """§32(1)(iia) needs three facts this product does not hold: new plant, a
    manufacturing assessee, and no §115BAA/§115BAB election. A new lathe on the
    register asserts none of them."""
    _block(db, opening_wdv_paise=0)
    _asset(db, purchase_cost_paise=10 * L)
    assert _run(db)["additional_depreciation_paise"] == 0


def test_a_soft_deleted_asset_is_in_nothing(db):
    _block(db, opening_wdv_paise=0)
    _asset(db, deleted_at="2025-07-01T00:00:00Z", purchase_cost_paise=10 * L)
    got = _run(db)
    assert got["blocks"][0]["additions_full_rate_paise"] == 0
    assert got["unclassified_assets"] == []


# ══════════════════════════════════════════════════════════════════════════════
# The capital gain is not netted
# ══════════════════════════════════════════════════════════════════════════════

def test_a_short_term_capital_gain_stays_out_of_the_allowance(db):
    _block(db, opening_wdv_paise=1 * L)
    _asset(db, purchase_date="2020-06-01", is_disposed=True,
           disposal_date="2025-09-01", disposal_value_paise=4 * L)
    got = _run(db)
    assert got["short_term_capital_gain_paise"] == 3 * L
    assert got["allowance_paise"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# The endpoints
# ══════════════════════════════════════════════════════════════════════════════

def test_the_section_32_endpoint_answers(db):
    _block(db)
    _asset(db)
    got = it.section_32_depreciation(client_id=CLIENT, fy=FY, current_user=CALLER)["data"]
    assert got["financial_year"] == FY
    assert got["period_start"] == "2025-04-01" and got["period_end"] == "2026-03-31"
    assert got["allowance_paise"] > 0


def test_a_block_is_upserted_not_duplicated(db):
    it.upsert_section_32_block(
        it.Section32BlockIn(client_id=CLIENT, financial_year=FY, block_key="P&M 15%",
                            rate_percent=15, opening_wdv_paise=10 * L,
                            assets_remain=True),
        CALLER)
    it.upsert_section_32_block(
        it.Section32BlockIn(client_id=CLIENT, financial_year=FY, block_key="P&M 15%",
                            rate_percent=15, opening_wdv_paise=12 * L,
                            assets_remain=True),
        CALLER)
    rows = db.rows("income_tax_asset_blocks")
    assert len(rows) == 1, "a second row would silently double the opening WDV"
    assert rows[0]["opening_wdv_paise"] == 12 * L
    assert rows[0]["created_by"] == "u-1", "public.users.id, not the auth id"


def test_the_bridge_now_has_a_router_and_gets_its_own_section_32_figure(db):
    _block(db, opening_wdv_paise=10 * L)
    _asset(db, purchase_date="2020-06-01", put_to_use_date="2020-06-01")
    got = it.book_to_tax_bridge(
        it.BookToTaxBridgeRequest(client_id=CLIENT, fy=FY,
                                  book_profit_paise=50 * L,
                                  depreciation_per_books_paise=3 * L),
        CALLER)["data"]
    assert got["is_complete"] is True
    assert got["foots"] is True
    # Two lines, not one: the book charge added back and the §32 allowance
    # deducted. Netting them would hide the adjustment the bridge exists to show.
    labels = [l["label"] for l in got["lines"]]
    assert "Depreciation charged in the accounts" in labels
    assert "Depreciation allowable" in labels
    assert any("32" in l["reference"] for l in got["lines"]), got["lines"]
    assert got["section_32"]["allowance_paise"] == int(0.15 * 10 * L)


def test_the_bridge_REFUSES_the_line_while_the_blocks_are_incomplete(db):
    """The bridge's own argument, now reachable: assuming the two depreciation
    figures equal would make it foot perfectly while understating the difference
    to nil, and a bridge that reconciles and lies is worse than one that refuses
    to reconcile."""
    _block(db)
    _asset(db, id="a9", it_block_key=None)          # unclassified → incomplete
    got = it.book_to_tax_bridge(
        it.BookToTaxBridgeRequest(client_id=CLIENT, fy=FY,
                                  book_profit_paise=50 * L,
                                  depreciation_per_books_paise=3 * L),
        CALLER)["data"]
    assert got["is_complete"] is False
    assert any("§32" in m for m in got["missing"])
    assert got["taxable_income_paise"] == 50 * L, (
        "neither depreciation line is drawn, so book profit passes through")
    assert got["section_32"]["is_complete"] is False, (
        "and the reason travels with it, so a CA needs no second request")
