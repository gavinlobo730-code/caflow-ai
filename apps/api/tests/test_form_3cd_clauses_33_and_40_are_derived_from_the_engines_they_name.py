"""Form 3CD clauses 33 and 40 are derived from the modules the product already has, and a figure it cannot derive is a named gap
(POST-A-069).

* Clause 33 (Chapter VI-A / Chapter III deductions, section-wise) reads the CA's own entries on the computation workspace
  (`tax_deduction_claims`), grouped by the section each names. A year with no claim recorded answers nothing (it is not "none
  claimed"), and the answer says so.
* Clause 40 (turnover, gross-profit, net-profit and stock-in-trade ratios, this year and the preceding year) composes two Profit &
  Loss calls (the real `builders.profit_loss`, so the figures tie to it to the paisa) and the stock ledger's closing value. Material
  consumed and finished goods produced are named as a gap; no approximation is computed. A year with no ledger entry is named and
  never shown as nil.
"""
from __future__ import annotations

import pytest

from domain.income_tax import form_3cd as f3cd
from domain.reporting import builders
from domain.reporting.model import Account, ProjectedLine
from services import form_3cd_service as svc

FIRM, CLIENT = "firm-1", "client-1"
USER = {"firm_id": FIRM, "id": "u1", "role": "Partner"}


# ── clause 33 ────────────────────────────────────────────────────────────────

def _claims(monkeypatch, rows):
    import domain.income_tax.computation_workspace as ws
    monkeypatch.setattr(ws, "list_deduction_claims", lambda f, c, fy: rows)


def test_clause_33_groups_the_cas_own_claims_by_section_and_adds_up(monkeypatch):
    _claims(monkeypatch, [
        {"section": "80C", "claimed_amount_paise": 1_50_000_00, "allowed_amount_paise": 1_50_000_00, "status": "approved"},
        {"section": "80D", "claimed_amount_paise": 30_000_00, "allowed_amount_paise": 25_000_00, "status": "pending"},
        {"section": "80D", "claimed_amount_paise": 10_000_00, "allowed_amount_paise": 10_000_00, "status": "pending"},
        {"section": "10AA", "claimed_amount_paise": 5_00_000_00, "allowed_amount_paise": 5_00_000_00, "status": "approved"},
    ])
    value, note = svc._clause_33(None, FIRM, CLIENT, "2025-26")
    by = {r["section"]: r for r in value["by_section"]}
    assert by["80D"] == {"section": "80D", "claims": 2, "claimed_paise": 40_000_00, "allowed_paise": 35_000_00, "pending_claims": 2}
    assert by["10AA"]["claimed_paise"] == 5_00_000_00, "a Chapter III section appears under the name the CA typed"
    assert value["total_claimed_paise"] == 1_50_000_00 + 40_000_00 + 5_00_000_00
    assert value["total_allowed_paise"] == 1_50_000_00 + 35_000_00 + 5_00_000_00 and value["pending_claims"] == 2
    assert "tax_deduction_claims" in note


def test_clause_33_with_no_claim_recorded_answers_nothing_and_says_it_is_not_none_claimed(monkeypatch):
    _claims(monkeypatch, [])
    value, note = svc._clause_33(None, FIRM, CLIENT, "2025-26")
    assert value is None and "not the same as none claimed" in note


def test_clause_33_unreadable_claims_are_named_not_nil(monkeypatch):
    import domain.income_tax.computation_workspace as ws

    def boom(*a):
        raise RuntimeError("down")
    monkeypatch.setattr(ws, "list_deduction_claims", boom)
    value, note = svc._clause_33(None, FIRM, CLIENT, "2025-26")
    assert value is None and "could not be read" in note


# ── clause 40 ────────────────────────────────────────────────────────────────

ACCOUNTS = {
    "sales": Account("sales", "4000", "Sales", "Revenue", "Sales"),
    "interest": Account("interest", "4100", "Interest income", "Revenue", "Interest Income"),
    "cogs": Account("cogs", "5000", "Cost of goods sold", "Expense", "Cost of Goods Sold", system_key="cogs"),
    "rent": Account("rent", "6000", "Rent", "Expense", "Rent"),
}


def _pl(sales, interest, cogs, rent, start, end):
    lines = [ProjectedLine("sales", 0, sales), ProjectedLine("interest", 0, interest),
             ProjectedLine("cogs", cogs, 0), ProjectedLine("rent", rent, 0)]
    return builders.profit_loss([ln for ln in lines if ln.debit_paise or ln.credit_paise], ACCOUNTS, start, end, "accrual")


class _Reporting:
    def __init__(self, by_start):
        self.by_start = by_start

    def profit_loss(self, firm, client, start, end, basis="accrual"):
        return self.by_start[start]


@pytest.fixture
def books(monkeypatch):
    import routers.accounting as acc
    from services import stock_position_service
    state = {
        "2025-04-01": _pl(10_00_000_00, 50_000_00, 6_00_000_00, 1_00_000_00, "2025-04-01", "2026-03-31"),
        "2024-04-01": _pl(8_00_000_00, 0, 5_00_000_00, 80_000_00, "2024-04-01", "2025-03-31"),
    }
    monkeypatch.setattr(acc, "_reporting_service", lambda user: _Reporting(state))
    monkeypatch.setattr(stock_position_service, "position",
                        lambda db, f, c, as_of, item_id=None: {"total_value_paise": 2_00_000_00 if as_of == "2026-03-31" else 1_00_000_00})
    return state


def test_clause_40_ties_to_the_profit_and_loss_to_the_paisa_for_both_years(books):
    value, note = svc._clause_40(None, FIRM, CLIENT, "2025-26", USER)
    this, prior = value["this_year"], value["preceding_year"]
    assert this["financial_year"] == "2025-26" and prior["financial_year"] == "2024-25"
    # Turnover is 'Revenue from Operations' only (the interest is other income); gross profit is turnover less cost of sales.
    assert this["turnover_paise"] == 10_00_000_00 and this["gross_profit_paise"] == 4_00_000_00
    assert this["net_profit_paise"] == books["2025-04-01"]["net_profit_paise"] == 10_50_000_00 - 6_00_000_00 - 1_00_000_00
    assert this["closing_stock_paise"] == 2_00_000_00
    assert this["gross_profit_to_turnover_bps"] == 4000 and this["net_profit_to_turnover_bps"] == 3500
    assert this["stock_to_turnover_bps"] == 2000
    assert prior["turnover_paise"] == 8_00_000_00 and prior["gross_profit_to_turnover_bps"] == 3750
    assert prior["net_profit_to_turnover_bps"] == (8_00_000_00 - 5_00_000_00 - 80_000_00) * 10_000 // 8_00_000_00
    assert "Revenue from Operations" in note


def test_clause_40_names_material_consumed_and_goods_produced_as_a_gap_and_computes_no_figure(books):
    value, _ = svc._clause_40(None, FIRM, CLIENT, "2025-26", USER)
    assert any("Material consumed and finished goods produced are not derivable" in g for g in value["gaps"])
    assert "material_consumed_paise" not in value["this_year"] and "finished_goods_produced_paise" not in value["this_year"]


def test_clause_40_a_year_with_no_ledger_entry_is_named_and_not_shown_as_nil(books):
    del books["2024-04-01"]
    books["2024-04-01"] = builders.profit_loss([], ACCOUNTS, "2024-04-01", "2025-03-31", "accrual")
    value, _ = svc._clause_40(None, FIRM, CLIENT, "2025-26", USER)
    assert value["preceding_year"] is None
    assert any("2024-25" in g and "no income or expense entry" in g for g in value["gaps"])


def test_clause_40_for_a_year_with_no_entry_answers_nothing(books):
    books["2025-04-01"] = builders.profit_loss([], ACCOUNTS, "2025-04-01", "2026-03-31", "accrual")
    value, note = svc._clause_40(None, FIRM, CLIENT, "2025-26", USER)
    assert value is None and "no income or expense entry" in note


def test_clause_40_with_no_turnover_has_no_ratio_not_a_zero_ratio(books):
    books["2025-04-01"] = _pl(0, 50_000_00, 0, 1_00_000_00, "2025-04-01", "2026-03-31")
    value, _ = svc._clause_40(None, FIRM, CLIENT, "2025-26", USER)
    this = value["this_year"]
    assert this["turnover_paise"] == 0 and this["gross_profit_to_turnover_bps"] is None and this["stock_to_turnover_bps"] is None
    assert any("no ratio to turnover" in g for g in this["gaps"])


def test_clause_40_without_the_callers_scope_is_not_read():
    value, note = svc._clause_40(None, FIRM, CLIENT, "2025-26", None)
    assert value is None and "scope" in note


def test_the_register_counts_33_and_40_as_derivable():
    assert {"33", "40"} <= set(f3cd.DERIVABLE_CODES)
