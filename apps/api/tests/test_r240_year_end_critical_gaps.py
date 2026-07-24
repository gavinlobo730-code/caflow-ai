"""
Task #240 — year-end critical gaps found in a fresh audit pass:

1. year_end_mappings.py's default account-type -> schedule_line map was keyed
   on invented lowercase categories ("bank", "receivable", "fixed_asset",
   "tax_asset", ...) that never matched chart_of_accounts.account_type's real
   CHECK-constrained enum ('Asset', 'Liability', 'Equity', 'Revenue',
   'Expense' — migration 003; the `accounts` view, migration 016, is a plain
   passthrough of chart_of_accounts). Only "equity"/"expense" happened to
   coincide after lowercasing; every Asset/Liability/Revenue account silently
   fell through to "other_current_assets", corrupting the auto-initialized
   Schedule III mapping that services.year_end_financial_service relies on.

2. year_end_notes.py's "auto-generated" Notes to Accounts (Fixed Assets,
   Share Capital, Loans, GST/TDS) were 100% hardcoded literal constants
   (e.g. gross_block_paise=80_000_00) regardless of the actual client/FY —
   numbers with no connection to the client's books that could end up in a
   filed Balance Sheet. Fixed Assets / Share Capital (paid-up) / Loans
   (aggregate) are now computed from real data; whatever genuinely can't be
   derived (authorised/issued/subscribed capital, secured/unsecured split,
   GST/TDS payable — no FY-level aggregation exists anywhere in the
   codebase) is now an honest requires_ca_review placeholder, never a
   fabricated number.

3. year_end_adjustments.py's post_adjustment was the only GL-posting action
   on this router with no locked-financial-year check, unlike every other
   posting endpoint in the codebase (fixed_assets.py, purchase_bills.py).

4. domain/income_tax/xbrl_service.py's validator never checked the Balance
   Sheet equation (Total Assets == Total Equity & Liabilities), and its
   paise->rupee conversion used floor division (silently truncating up to
   99 paise per line) instead of rounding to the nearest rupee.
"""
import re
import xml.etree.ElementTree as ET

import pytest
from fastapi import HTTPException

from tests.e2e_harness import FakeDB, wire_e2e

PARTNER_F1 = {"firm_id": "F1", "role": "Partner", "auth_user_id": "p1", "id": "u1", "email": "p1@f1.test"}


# =============================================================================
# 1. year_end_mappings.py — Schedule III default-mapping fix
# =============================================================================

def test_schedule_line_for_account_classifies_by_real_enum():
    import routers.year_end_mappings as m

    assert m._schedule_line_for_account("Asset", "Trade Receivables") == "trade_receivables"
    assert m._schedule_line_for_account("Asset", "Bank Account") == "cash_and_bank"
    assert m._schedule_line_for_account("Asset", "Plant & Machinery") == "tangible_assets"
    assert m._schedule_line_for_account("Liability", "Trade Payables") == "trade_payables"
    assert m._schedule_line_for_account("Liability", "Short Term Loan") == "short_term_borrowings"
    assert m._schedule_line_for_account("Equity", "Share Capital") == "share_capital"
    assert m._schedule_line_for_account("Revenue", "Sales") == "revenue_from_operations"
    assert m._schedule_line_for_account("Expense", "Salary") == "employee_benefit_expense"


def test_schedule_line_for_account_regression_not_defaulted_to_other_current_assets():
    """Old bug: Asset/Liability/Revenue accounts (i.e. most of a real Chart
    of Accounts) all fell through to "other_current_assets" because the map
    was keyed on categories ("bank", "receivable", "income", ...) that never
    matched the real ('Asset'/'Liability'/'Equity'/'Revenue'/'Expense') enum."""
    import routers.year_end_mappings as m

    assert m._schedule_line_for_account("Asset", "Trade Receivables") != "other_current_assets"
    assert m._schedule_line_for_account("Liability", "Trade Payables") != "other_current_assets"
    assert m._schedule_line_for_account("Revenue", "Sales") != "other_current_assets"


def test_schedule_line_for_account_falls_back_gracefully_without_subtype():
    import routers.year_end_mappings as m

    # No subtype at all -> coarse per-type default, but never a wrong-section one.
    assert m._schedule_line_for_account("Liability", None) == "other_current_liabilities"
    assert m._schedule_line_for_account("Revenue", None) == "revenue_from_operations"
    assert m._schedule_line_for_account("Expense", "") == "other_expenses"


def test_get_default_mappings_auto_init_classifies_by_real_enum(monkeypatch):
    import routers.year_end_mappings as m
    import core.supabase_client as sc

    monkeypatch.setattr(m, "_USE_MOCK", False)
    db = FakeDB()
    monkeypatch.setattr(sc, "get_supabase", lambda: db)

    db.seed("accounts", {"id": "a1", "firm_id": "F1", "account_type": "Asset",
                          "account_subtype": "Trade Receivables", "account_name": "Debtors"})
    db.seed("accounts", {"id": "a2", "firm_id": "F1", "account_type": "Liability",
                          "account_subtype": "Trade Payables", "account_name": "Creditors"})
    db.seed("accounts", {"id": "a3", "firm_id": "F1", "account_type": "Revenue",
                          "account_subtype": None, "account_name": "Sales"})
    db.seed("accounts", {"id": "a4", "firm_id": "F1", "account_type": "Equity",
                          "account_subtype": "Share Capital", "account_name": "Capital"})

    resp = m.get_default_mappings(PARTNER_F1)
    assert resp["success"] is True

    mappings = {r["account_id"]: r["schedule_line"] for r in db.rows("account_group_mappings")}
    assert mappings["a1"] == "trade_receivables"
    assert mappings["a2"] == "trade_payables"
    assert mappings["a3"] == "revenue_from_operations"
    assert mappings["a4"] == "share_capital"
    # None of these are the old broken catch-all.
    assert mappings["a1"] != "other_current_assets"
    assert mappings["a2"] != "other_current_assets"
    assert mappings["a3"] != "other_current_assets"


# =============================================================================
# 2. year_end_notes.py — real data, never fabricated
# =============================================================================

def test_compute_fixed_assets_note_data_uses_real_register():
    import routers.year_end_notes as m

    db = FakeDB()
    db.seed("fixed_assets", {
        "firm_id": "F1", "client_id": "C1", "is_disposed": False,
        "purchase_cost_paise": 10_00_000_00, "accumulated_depreciation_paise": 2_00_000_00,
        "depreciation_method": "SL", "salvage_value_paise": 0, "useful_life_years": 5,
        "purchase_date": "2023-04-01", "asset_category": "Plant & Machinery",
    })

    result = m._compute_fixed_assets_note_data(db, "F1", "C1", "2026-03-31")
    assert result["gross_block_paise"] == 10_00_000_00
    assert result["accumulated_dep_paise"] == 2_00_000_00
    assert result["net_block_paise"] == 8_00_000_00
    assert result["depreciation_charge_paise"] > 0
    # Not the old hardcoded literal.
    assert result["gross_block_paise"] != 80_000_00


def test_compute_fixed_assets_note_data_empty_register_is_zero_not_fabricated():
    import routers.year_end_notes as m

    db = FakeDB()
    result = m._compute_fixed_assets_note_data(db, "F1", "C1", "2026-03-31")
    assert result["gross_block_paise"] == 0
    assert result["net_block_paise"] == 0


def test_compute_fixed_assets_note_data_mock_mode_is_honest_placeholder():
    import routers.year_end_notes as m

    result = m._compute_fixed_assets_note_data(None, "F1", "C1", "2026-03-31")
    assert result["gross_block_paise"] == 0
    assert result["requires_ca_review"] is True


def test_compute_gl_schedule_balances_extracts_relevant_lines(monkeypatch):
    import routers.year_end_notes as m
    import services.year_end_financial_service as yefs

    def fake_generate(supabase, client_id, firm_id, fy_start, fy_end):
        return {"balance_sheet": {"equity_and_liabilities": {
            "share_capital": 5_00_000_00, "long_term_borrowings": 2_00_000_00,
            "short_term_borrowings": 1_00_000_00, "trade_payables": 50_000_00,
        }}}
    monkeypatch.setattr(yefs, "generate_financial_statements", fake_generate)

    result = m._compute_gl_schedule_balances(object(), "F1", "C1", "2025-04-01", "2026-03-31")
    assert result["share_capital"] == 5_00_000_00
    assert result["long_term_borrowings"] == 2_00_000_00
    assert result["short_term_borrowings"] == 1_00_000_00


def test_compute_gl_schedule_balances_none_when_unavailable():
    import routers.year_end_notes as m

    assert m._compute_gl_schedule_balances(None, "F1", "C1", "2025-04-01", "2026-03-31") is None
    assert m._compute_gl_schedule_balances(object(), "F1", "C1", None, None) is None


def test_compute_gl_schedule_balances_falls_back_when_books_dont_balance(monkeypatch):
    import routers.year_end_notes as m
    import services.year_end_financial_service as yefs

    def fake_generate(*_a, **_k):
        raise ValueError("Balance Sheet does not balance")
    monkeypatch.setattr(yefs, "generate_financial_statements", fake_generate)

    assert m._compute_gl_schedule_balances(object(), "F1", "C1", "2025-04-01", "2026-03-31") is None


def test_generate_note_content_share_capital_no_fabrication_when_gl_unavailable():
    import routers.year_end_notes as m

    eng = {"financial_year": "2025-26"}
    computed = {"fixed_assets": {}, "gl_balances": None}
    nd = m._generate_note_content("share_capital", eng, computed)["note_data"]
    assert nd["paid_up_paise"] is None
    assert nd["authorised_paise"] is None
    assert nd["issued_paise"] is None
    assert nd["subscribed_paise"] is None
    assert nd["requires_ca_review"] is True


def test_generate_note_content_share_capital_uses_real_gl_balance_but_never_fabricates_moa_facts():
    import routers.year_end_notes as m

    eng = {"financial_year": "2025-26"}
    computed = {"fixed_assets": {}, "gl_balances": {"share_capital": 7_00_000_00}}
    nd = m._generate_note_content("share_capital", eng, computed)["note_data"]
    assert nd["paid_up_paise"] == 7_00_000_00
    assert nd["paid_up_paise"] != 100_000_00  # not the old hardcoded literal
    # Authorised/issued/subscribed are MOA facts, never derivable from the GL.
    assert nd["authorised_paise"] is None
    assert nd["issued_paise"] is None
    assert nd["subscribed_paise"] is None


def test_generate_note_content_loans_splits_real_totals_but_not_security_status():
    import routers.year_end_notes as m

    eng = {"financial_year": "2025-26"}
    computed = {"fixed_assets": {}, "gl_balances": {
        "long_term_borrowings": 3_00_000_00, "short_term_borrowings": 1_50_000_00,
    }}
    nd = m._generate_note_content("loans", eng, computed)["note_data"]
    assert nd["long_term_total_paise"] == 3_00_000_00
    assert nd["short_term_total_paise"] == 1_50_000_00
    assert nd["long_term_total_paise"] != 30_000_00  # not the old hardcoded literal
    assert nd["long_term_secured_paise"] is None
    assert nd["long_term_unsecured_paise"] is None
    assert nd["requires_ca_review"] is True


def test_generate_note_content_gst_tds_is_honest_placeholder_not_fabricated():
    import routers.year_end_notes as m

    eng = {"financial_year": "2025-26"}
    computed = {"fixed_assets": {}, "gl_balances": None}
    nd = m._generate_note_content("gst_tds", eng, computed)["note_data"]
    assert nd["gst_payable_paise"] is None
    assert nd["tds_payable_paise"] is None
    assert nd["input_itc_paise"] is None
    assert nd["requires_ca_review"] is True
    assert nd["is_auto_generated"] is False


def test_gst_tds_moved_out_of_auto_note_types():
    import routers.year_end_notes as m

    assert "gst_tds" in m._MANUAL_NOTE_TYPES
    assert "gst_tds" not in m._AUTO_NOTE_TYPES


def test_generate_notes_mock_mode_produces_no_fabricated_figures():
    import routers.year_end_notes as m
    import routers.year_end as ye

    ye._MOCK_ENGAGEMENTS["eng-r240-1"] = {
        "id": "eng-r240-1", "firm_id": "F1", "client_id": "C1",
        "financial_year": "2025-26", "status": "draft",
    }

    resp = m.generate_notes("eng-r240-1", PARTNER_F1)
    assert resp["success"] is True
    notes = {n["note_type"]: n for n in resp["data"]}

    assert notes["fixed_assets"]["note_data"]["gross_block_paise"] == 0
    assert notes["fixed_assets"]["note_data"]["gross_block_paise"] != 80_000_00
    assert notes["share_capital"]["note_data"]["paid_up_paise"] is None
    assert notes["loans"]["note_data"]["long_term_total_paise"] is None
    assert notes["gst_tds"]["note_data"]["gst_payable_paise"] is None
    assert notes["gst_tds"]["is_auto_generated"] is False


# =============================================================================
# 3. year_end_adjustments.py — post_adjustment period-lock check
# =============================================================================

def test_post_adjustment_calls_period_validation_with_the_posting_date(monkeypatch):
    import routers.year_end_adjustments as m

    db = FakeDB()
    wire_e2e(monkeypatch, db, [m])

    calls = []
    monkeypatch.setattr(m.period_validation_service, "validate_posting_date",
                         lambda firm_id, date_str: calls.append((firm_id, date_str)))

    eng = db.seed("year_end_engagements", {"firm_id": "F1", "client_id": "C1", "status": "draft"})
    adj = db.seed("year_end_adjustments", {
        "engagement_id": eng["id"], "firm_id": "F1", "status": "approved",
        "adjustment_date": "2025-07-15", "amount_paise": 1000,
        "debit_account_id": "A1", "credit_account_id": "A2", "description": "test",
    })

    m.post_adjustment(eng["id"], adj["id"], PARTNER_F1)
    assert calls == [("F1", "2025-07-15")]


def test_post_adjustment_blocks_when_period_locked(monkeypatch):
    import routers.year_end_adjustments as m

    db = FakeDB()
    wire_e2e(monkeypatch, db, [m])

    def _blocked(firm_id, date_str):
        raise HTTPException(status_code=422, detail="Financial year is locked")
    monkeypatch.setattr(m.period_validation_service, "validate_posting_date", _blocked)

    eng = db.seed("year_end_engagements", {"firm_id": "F1", "client_id": "C1", "status": "draft"})
    adj = db.seed("year_end_adjustments", {
        "engagement_id": eng["id"], "firm_id": "F1", "status": "approved",
        "adjustment_date": "2024-05-01", "amount_paise": 1000,
        "debit_account_id": "A1", "credit_account_id": "A2", "description": "test",
    })

    with pytest.raises(HTTPException) as ei:
        m.post_adjustment(eng["id"], adj["id"], PARTNER_F1)
    assert ei.value.status_code == 422
    # No journal entry was posted, and the adjustment's status was untouched.
    assert db.rows("journal_entries") == []
    assert db.rows("year_end_adjustments")[0]["status"] == "approved"


def test_post_adjustment_succeeds_when_period_open(monkeypatch):
    import routers.year_end_adjustments as m

    db = FakeDB()
    wire_e2e(monkeypatch, db, [m])  # validate_posting_date no-op'd -> period open

    eng = db.seed("year_end_engagements", {"firm_id": "F1", "client_id": "C1", "status": "draft"})
    adj = db.seed("year_end_adjustments", {
        "engagement_id": eng["id"], "firm_id": "F1", "status": "approved",
        "adjustment_date": "2025-07-15", "amount_paise": 1000,
        "debit_account_id": "A1", "credit_account_id": "A2", "description": "test",
    })

    resp = m.post_adjustment(eng["id"], adj["id"], PARTNER_F1)
    assert resp["success"] is True
    assert resp["data"]["status"] == "posted"
    assert len(db.rows("journal_entries")) == 1


def test_post_adjustment_mock_mode_calls_period_validation(monkeypatch):
    import routers.year_end_adjustments as m

    monkeypatch.setattr(m, "_USE_MOCK", True)
    calls = []
    monkeypatch.setattr(m.period_validation_service, "validate_posting_date",
                         lambda firm_id, date_str: calls.append((firm_id, date_str)))

    eng_id, adj_id = "eng-mock-post-1", "adj-mock-post-1"
    m._MOCK_ADJUSTMENTS[eng_id] = [{
        "id": adj_id, "engagement_id": eng_id, "firm_id": "F1", "status": "approved",
        "adjustment_date": "2025-08-01", "amount_paise": 500,
        "debit_account_id": "A1", "credit_account_id": "A2", "description": "test",
    }]

    m.post_adjustment(eng_id, adj_id, PARTNER_F1)
    assert calls == [("F1", "2025-08-01")]


# =============================================================================
# 4. xbrl_service.py — balance-equation validator + rounding
# =============================================================================

def test_check_balance_equation_flags_mismatch():
    import domain.income_tax.xbrl_service as xs

    data = {
        "BalanceSheet.CurrentAssets.CashAndCashEquivalents": 100_000_00,
        "BalanceSheet.Equity.ShareCapital": 40_000_00,
        "BalanceSheet.CurrentLiabilities.TradePayables": 30_000_00,
    }
    errors = xs._check_balance_equation(data)
    assert len(errors) == 1
    assert "does not balance" in errors[0]


def test_check_balance_equation_passes_when_balanced():
    import domain.income_tax.xbrl_service as xs

    data = {
        "BalanceSheet.CurrentAssets.CashAndCashEquivalents": 70_000_00,
        "BalanceSheet.Equity.ShareCapital": 40_000_00,
        "BalanceSheet.CurrentLiabilities.TradePayables": 30_000_00,
    }
    assert xs._check_balance_equation(data) == []


def test_check_balance_equation_ignores_non_balance_sheet_lines():
    import domain.income_tax.xbrl_service as xs

    data = {
        "BalanceSheet.CurrentAssets.CashAndCashEquivalents": 50_000_00,
        "BalanceSheet.Equity.ShareCapital": 50_000_00,
        "ProfitAndLoss.Revenue.RevenueFromOperations": 999_00_00,  # must not affect the BS check
    }
    assert xs._check_balance_equation(data) == []


def test_run_validation_surfaces_balance_error_alongside_missing_tags():
    import domain.income_tax.xbrl_service as xs

    data = {
        "BalanceSheet.CurrentAssets.CashAndCashEquivalents": 100_000_00,
        "BalanceSheet.Equity.ShareCapital": 40_000_00,
    }
    errors, missing = xs._run_validation(data, "MCA_2023")
    assert any("does not balance" in e for e in errors)
    assert missing  # other mandatory tags are still reported missing


def test_run_validation_clean_balanced_package_has_no_balance_error():
    import domain.income_tax.xbrl_service as xs

    data = {sl: 0 for sl, _tag, _label, mandatory in xs.DEFAULT_MAPPINGS if mandatory}
    errors, missing = xs._run_validation(data, "MCA_2023")
    assert missing == []
    assert not any("does not balance" in e for e in errors)


def test_generate_xbrl_xml_rounds_paise_to_nearest_rupee_not_floor():
    import domain.income_tax.xbrl_service as xs

    pkg = xs.create_xbrl_package("F1", "C1", "2025-26", "u1")
    xs.update_xbrl_data(
        "F1", pkg["id"],
        balance_sheet_json={
            "BalanceSheet.CurrentAssets.CashAndCashEquivalents": 12350,  # Rs 123.50 -> 124 (half-up)
            "BalanceSheet.CurrentAssets.TradeReceivables": 12349,        # Rs 123.49 -> 123
        },
    )
    xs._MOCK_PACKAGES[pkg["id"]]["status"] = "validated"

    xml_str = xs.generate_xbrl_xml("F1", pkg["id"], "Test Co Pvt Ltd", "U01234MH2020PTC000001")

    cash = re.search(
        r"<in-bse-fin:CashAndCashEquivalents[^>]*>(-?\d+)</in-bse-fin:CashAndCashEquivalents>", xml_str)
    receivables = re.search(
        r"<in-bse-fin:TradeReceivables[^>]*>(-?\d+)</in-bse-fin:TradeReceivables>", xml_str)
    assert cash and cash.group(1) == "124"          # NOT 123 (old floor-division bug)
    assert receivables and receivables.group(1) == "123"

    # The generated XML must still be well-formed.
    ET.fromstring(xml_str)
