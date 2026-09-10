"""
FA-05: the Fixed Assets note reported a charge the P&L need not carry.

WHAT WAS WRONG, IN THREE PARTS

  1. THE CHARGE WAS THEORETICAL. `dep_charge` was
     `sum(_annual_depreciation_for_period(a, fy_end_month))` — one full year's
     charge for every asset on the register, regardless of how many months had
     actually been posted, and with no pro-rata for an asset bought in December.
     A note is a disclosure OF THE BOOKS. A figure that need not match anything
     in the P&L is not one, and it is attached to a Balance Sheet.

  2. A SOLD ASSET VANISHED. The query filtered `is_disposed = False`, so an
     asset disposed of during the year disappeared from the gross block
     entirely instead of appearing as a deduction. Last year's closing then did
     not tie to this year's opening, and nothing in the note explained why.

  3. THERE WERE NO ADDITIONS OR DEDUCTIONS COLUMNS. Four closing figures and
     nothing to reconcile them with — which is not what Schedule III, Division I
     asks for. The note is a MOVEMENT: opening, additions, deductions, closing,
     the same four for accumulated depreciation, and net block at both ends.

WHAT IT IS NOW

The gross-block movement comes from the register, which holds every fact it
needs. The CHARGE comes from the ledger, through `account_period_balances` —
twelve pre-aggregated rows rather than every depreciation journal of the year
(CLAUDE.md's reporting rule). The per-class split comes from the register's own
record of what each asset was charged this year, and where that record does not
speak for the year in question the note says so instead of inventing a split.
Where the classes do not sum to the ledger's figure, the difference is STATED.
"""
import pytest

import routers.year_end_notes as yen
from tests.e2e_harness import FakeDB

FIRM, CLIENT = "F1", "C1"
FY_END = "2026-03-31"      # FY 2025-26
FY = "2025-26"


def _asset(db, **kw):
    row = {
        "firm_id": FIRM, "client_id": CLIENT, "is_disposed": False,
        "asset_category": "Plant & Machinery",
        "purchase_date": "2023-04-01", "purchase_cost_paise": 10_00_000_00,
        "accumulated_depreciation_paise": 0, "salvage_value_paise": 0,
        "depreciation_method": "WDV", "wdv_rate_percent": 18.10,
        "depreciation_fy": None, "depreciation_fy_start_accum_paise": None,
        "deleted_at": None,
    }
    row.update(kw)
    db.seed("fixed_assets", row)
    return row


def _note(db):
    return yen._compute_fixed_assets_note_data(db, FIRM, CLIENT, FY_END)


# ══════════════════════════════════════════════════════════════════════════════
# The movement
# ══════════════════════════════════════════════════════════════════════════════

def test_an_asset_bought_this_year_is_an_ADDITION_not_an_opening_balance():
    db = FakeDB()
    _asset(db, purchase_date="2025-09-01", purchase_cost_paise=5_00_000_00)
    got = _note(db)["classes"][0]
    assert got["opening_gross_paise"] == 0
    assert got["additions_paise"] == 5_00_000_00
    assert got["closing_gross_paise"] == 5_00_000_00


def test_an_asset_sold_this_year_is_a_DEDUCTION_not_an_absence():
    """The whole of (2). It used to be filtered out, so the gross block simply
    shrank with nothing to explain it."""
    db = FakeDB()
    _asset(db, purchase_date="2023-04-01", purchase_cost_paise=10_00_000_00,
           accumulated_depreciation_paise=4_00_000_00,
           is_disposed=True, disposal_date="2025-11-30")
    got = _note(db)["classes"][0]
    assert got["opening_gross_paise"] == 10_00_000_00, (
        "it was on the books at 1 April and must open the year")
    assert got["deductions_paise"] == 10_00_000_00
    assert got["closing_gross_paise"] == 0
    assert got["accum_on_deductions_paise"] == 4_00_000_00
    assert got["closing_accum_paise"] == 0


def test_an_asset_sold_in_an_EARLIER_year_is_in_neither_column():
    db = FakeDB()
    _asset(db, purchase_date="2020-04-01", is_disposed=True, disposal_date="2024-06-30")
    got = _note(db)["classes"][0]
    assert got == {"asset_class": "Plant & Machinery",
                   **{k: 0 for k in yen._FA_MOVEMENT_KEYS}}


def test_the_movement_reconciles_opening_to_closing():
    """The property a reader checks first: opening + additions − deductions must
    be the closing figure, on every class."""
    db = FakeDB()
    _asset(db, purchase_date="2023-04-01", purchase_cost_paise=10_00_000_00)
    _asset(db, purchase_date="2025-06-01", purchase_cost_paise=3_00_000_00)
    _asset(db, purchase_date="2022-04-01", purchase_cost_paise=2_00_000_00,
           is_disposed=True, disposal_date="2025-12-31")
    got = _note(db)
    for c in got["classes"]:
        assert (c["opening_gross_paise"] + c["additions_paise"]
                - c["deductions_paise"]) == c["closing_gross_paise"]
        assert (c["opening_accum_paise"] + c["charge_paise"]
                - c["accum_on_deductions_paise"]) == c["closing_accum_paise"]
        assert c["closing_net_paise"] == c["closing_gross_paise"] - c["closing_accum_paise"]
    assert got["totals"]["closing_gross_paise"] == 13_00_000_00


def test_classes_are_separate_rows():
    db = FakeDB()
    _asset(db, asset_category="Plant & Machinery", purchase_cost_paise=10_00_000_00)
    _asset(db, asset_category="Computer & IT Equipment", purchase_cost_paise=1_00_000_00)
    classes = _note(db)["classes"]
    assert [c["asset_class"] for c in classes] == [
        "Computer & IT Equipment", "Plant & Machinery"]


# ══════════════════════════════════════════════════════════════════════════════
# The charge comes off the ledger
# ══════════════════════════════════════════════════════════════════════════════

def _with_ledger(db, paise_by_month: dict[str, int]):
    db.seed("chart_of_accounts", {"id": "coa-dep", "firm_id": FIRM, "client_id": CLIENT,
                                  "account_name": "Depreciation Expense",
                                  "account_type": "Expense", "account_code": "5200"})
    for month, paise in paise_by_month.items():
        db.seed("account_period_balances", {
            "firm_id": FIRM, "client_id": CLIENT, "account_id": "coa-dep",
            "period_month": month, "debit_paise": paise, "credit_paise": 0})


def test_the_charge_is_what_was_posted(monkeypatch):
    db = FakeDB()
    _asset(db, purchase_date="2023-04-01",
           accumulated_depreciation_paise=1_50_000_00,
           depreciation_fy=FY, depreciation_fy_start_accum_paise=1_00_000_00)
    _with_ledger(db, {"2025-04-01": 25_000_00, "2025-05-01": 25_000_00})
    monkeypatch.setattr(
        "services.phase2_journal_service.phase2_journal_service._find_account",
        lambda *a, **k: "coa-dep")

    got = _note(db)
    assert got["posted_depreciation_paise"] == 50_000_00
    assert got["depreciation_charge_paise"] == 50_000_00
    assert got["classes"][0]["charge_paise"] == 50_000_00
    assert "statutory_gaps" not in got, "nothing to flag when the two agree"


def test_a_disagreement_between_the_register_and_the_ledger_is_STATED(monkeypatch):
    """Not absorbed. The register says one thing and the ledger another, and a
    note that quietly picks one is how a difference stops being findable."""
    db = FakeDB()
    _asset(db, purchase_date="2023-04-01",
           accumulated_depreciation_paise=1_50_000_00,
           depreciation_fy=FY, depreciation_fy_start_accum_paise=1_00_000_00)
    _with_ledger(db, {"2025-04-01": 40_000_00})
    monkeypatch.setattr(
        "services.phase2_journal_service.phase2_journal_service._find_account",
        lambda *a, **k: "coa-dep")

    got = _note(db)
    assert got["depreciation_charge_paise"] == 40_000_00, "the LEDGER is the note"
    assert got["requires_ca_review"] is True
    gap = " ".join(got["statutory_gaps"])
    assert "not explained by this note" in gap
    assert "10,000.00" in gap


def test_a_credit_to_the_account_reduces_the_year(monkeypatch):
    """A reversed month is a credit on an expense account. Summing debits alone
    would report a charge the client no longer carries."""
    db = FakeDB()
    _asset(db, purchase_date="2023-04-01")
    db.seed("chart_of_accounts", {"id": "coa-dep", "firm_id": FIRM, "client_id": CLIENT,
                                  "account_name": "Depreciation Expense",
                                  "account_type": "Expense", "account_code": "5200"})
    db.seed("account_period_balances", {
        "firm_id": FIRM, "client_id": CLIENT, "account_id": "coa-dep",
        "period_month": "2025-04-01", "debit_paise": 30_000_00, "credit_paise": 5_000_00})
    monkeypatch.setattr(
        "services.phase2_journal_service.phase2_journal_service._find_account",
        lambda *a, **k: "coa-dep")
    assert _note(db)["posted_depreciation_paise"] == 25_000_00


def test_an_unreachable_ledger_is_a_named_gap_not_a_zero():
    db = FakeDB()
    _asset(db, purchase_date="2023-04-01", accumulated_depreciation_paise=2_00_000_00)
    got = _note(db)
    assert got["posted_depreciation_paise"] is None
    assert got["requires_ca_review"] is True
    assert any("could not be read from the ledger" in g for g in got["statutory_gaps"])


def test_a_charge_from_another_year_is_not_attributed_to_this_one(monkeypatch):
    """`depreciation_fy_start_accum_paise` speaks for the asset's CURRENT
    depreciation year only. Using it for a different year would put last year's
    charge in this year's class."""
    db = FakeDB()
    _asset(db, purchase_date="2023-04-01", accumulated_depreciation_paise=3_00_000_00,
           depreciation_fy="2024-25", depreciation_fy_start_accum_paise=2_00_000_00)
    _with_ledger(db, {"2025-04-01": 0})
    monkeypatch.setattr(
        "services.phase2_journal_service.phase2_journal_service._find_account",
        lambda *a, **k: "coa-dep")
    got = _note(db)
    assert got["classes"][0]["charge_paise"] == 0
    assert any("different financial year" in g for g in got["statutory_gaps"])


# ══════════════════════════════════════════════════════════════════════════════
# The shape the rest of the app still reads
# ══════════════════════════════════════════════════════════════════════════════

def test_the_four_original_figures_are_still_there():
    """Downstream reads gross/accumulated/net/charge. Adding the movement must
    not take them away."""
    db = FakeDB()
    _asset(db, purchase_date="2023-04-01", purchase_cost_paise=10_00_000_00,
           accumulated_depreciation_paise=2_00_000_00)
    got = _note(db)
    assert got["gross_block_paise"] == 10_00_000_00
    assert got["accumulated_dep_paise"] == 2_00_000_00
    assert got["net_block_paise"] == 8_00_000_00
    assert "depreciation_charge_paise" in got
    assert got["note_type"] == "fixed_assets" and got["is_auto_generated"] is True


def test_no_financial_year_reports_the_register_and_says_so():
    db = FakeDB()
    _asset(db, purchase_date="2023-04-01", purchase_cost_paise=10_00_000_00,
           accumulated_depreciation_paise=2_00_000_00)
    got = yen._compute_fixed_assets_note_data(db, FIRM, CLIENT, None)
    assert got["gross_block_paise"] == 10_00_000_00
    assert any("shows the register as it stands" in g for g in got["statutory_gaps"])


def test_a_deleted_asset_is_in_nothing():
    """Migration 351's soft delete is for a row created by mistake — it was
    never in the register, so it is in no column of the note."""
    db = FakeDB()
    _asset(db, purchase_date="2023-04-01", deleted_at="2025-06-01T00:00:00Z")
    assert _note(db)["classes"] == []
