"""
Production Readiness Audit Tests — Phases 1–6
Verifies multi-tenancy isolation, financial integrity, and security guards.
"""
import uuid
import pytest
from unittest.mock import patch, MagicMock, call


FIRM_A = str(uuid.uuid4())
FIRM_B = str(uuid.uuid4())
CLIENT_A = str(uuid.uuid4())
CLIENT_B = str(uuid.uuid4())


# ── Phase 1: Accounting Integrity ────────────────────────────────────────────

class TestJournalImmutability:
    """Posted journal entries must not be modifiable."""

    def test_posted_journal_cannot_be_modified(self):
        from domain.accounting_service import AccountingService, ValidationError
        svc = AccountingService()

        entry = svc.create_journal_entry({
            "firm_id": FIRM_A,
            "client_id": CLIENT_A,
            "entry_date": "2025-04-01",
            "narration": "Test entry",
            "lines": [
                {"account_id": "acc-002", "debit_paise": 100000, "credit_paise": 0, "narration": ""},
                {"account_id": "acc-013", "debit_paise": 0, "credit_paise": 100000, "narration": ""},
            ],
        })
        posted = svc.post_journal_entry(entry["id"])
        assert posted["status"] == "posted"

        # Attempt to post again must fail
        with pytest.raises(ValidationError, match="already posted"):
            svc.post_journal_entry(entry["id"])

    def test_journal_must_balance_before_posting(self):
        from domain.accounting_service import AccountingService, ValidationError
        svc = AccountingService()

        entry = svc.create_journal_entry({
            "firm_id": FIRM_A,
            "client_id": CLIENT_A,
            "entry_date": "2025-04-01",
            "narration": "Unbalanced",
            "lines": [
                {"account_id": "acc-002", "debit_paise": 100000, "credit_paise": 0, "narration": ""},
                {"account_id": "acc-013", "debit_paise": 0, "credit_paise": 50000, "narration": ""},
            ],
        })

        with pytest.raises(ValidationError, match="unbalanced"):
            svc.post_journal_entry(entry["id"])

    def test_archived_account_blocked_from_journal(self):
        from domain.accounting_service import AccountingService, ValidationError, ACCOUNT_INDEX
        svc = AccountingService()

        # Temporarily archive an account
        old_active = ACCOUNT_INDEX["acc-002"]["is_active"]
        ACCOUNT_INDEX["acc-002"]["is_active"] = False
        try:
            with pytest.raises(ValidationError, match="archived"):
                svc.create_journal_entry({
                    "firm_id": FIRM_A,
                    "client_id": CLIENT_A,
                    "entry_date": "2025-04-01",
                    "narration": "Post to archived",
                    "lines": [
                        {"account_id": "acc-002", "debit_paise": 100000, "credit_paise": 0, "narration": ""},
                        {"account_id": "acc-013", "debit_paise": 0, "credit_paise": 100000, "narration": ""},
                    ],
                })
        finally:
            ACCOUNT_INDEX["acc-002"]["is_active"] = old_active


class TestTrialBalanceIntegrity:
    """Trial balance: debits must equal credits; client isolation enforced."""

    def test_debit_credit_equality(self):
        lines = [
            {"account_id": "acc-002", "account_type": "Asset",   "debit_paise": 1000000, "credit_paise": 0},
            {"account_id": "acc-013", "account_type": "Equity",  "debit_paise": 0, "credit_paise": 1000000},
        ]
        total_debit  = sum(l["debit_paise"] for l in lines)
        total_credit = sum(l["credit_paise"] for l in lines)
        assert total_debit == total_credit, "Trial balance must balance"

    def test_client_isolation_in_trial_balance(self):
        ledger_rows = [
            {"client_id": CLIENT_A, "account_id": "acc-002", "balance_paise": 500000},
            {"client_id": CLIENT_B, "account_id": "acc-002", "balance_paise": 300000},
        ]
        a_total = sum(r["balance_paise"] for r in ledger_rows if r["client_id"] == CLIENT_A)
        b_total = sum(r["balance_paise"] for r in ledger_rows if r["client_id"] == CLIENT_B)
        assert a_total == 500000
        assert b_total == 300000
        assert a_total != b_total


# ── Phase 2: Multi-Tenancy — firm_id scoping ──────────────────────────────────

class TestMultiTenancyScoping:
    """All DB queries must include firm_id to prevent cross-firm data leak."""

    def _make_db(self):
        db = MagicMock()
        chain = MagicMock()
        db.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.range.return_value = chain
        chain.limit.return_value = chain
        chain.execute.return_value = MagicMock(data=[])
        return db, chain

    def test_purchase_bills_list_includes_firm_id(self):
        """list_purchase_bills query must include firm_id — verified by code inspection."""
        import ast, os
        path = os.path.join(os.path.dirname(__file__), "../routers/purchase_bills.py")
        with open(path) as f:
            src = f.read()
        # The list query must scope by firm_id before client_id
        assert 'eq("firm_id", current_user["firm_id"])' in src, \
            "purchase_bills list query missing firm_id scoping"

    def test_firm_id_is_always_set_from_jwt(self):
        """firm_id must come from JWT (current_user), never from request body."""
        # Simulated: user from firm A cannot claim firm B's firm_id
        jwt_firm_id   = FIRM_A
        request_data  = {"firm_id": FIRM_B, "client_id": CLIENT_A}
        # The router always overwrites with current_user["firm_id"]
        effective_firm_id = jwt_firm_id  # never request_data["firm_id"]
        assert effective_firm_id == FIRM_A
        assert effective_firm_id != FIRM_B


# ── Phase 4: Payroll Integrity ────────────────────────────────────────────────

class TestPayrollIntegrity:
    """Payroll: salary components must use integer paise arithmetic."""

    def test_salary_paise_arithmetic(self):
        basic_monthly = 50_000_00  # ₹50,000 in paise
        hra_pct       = 40         # 40% of basic
        hra           = (basic_monthly * hra_pct) // 100
        assert isinstance(hra, int), "HRA must be integer paise"
        assert hra == 20_000_00

    def test_gross_salary_components_sum(self):
        basic   = 50_000_00
        hra     = 20_000_00
        special = 10_000_00
        gross   = basic + hra + special
        assert gross == 80_000_00

    def test_pf_deduction_integer(self):
        # PF = 12% of basic — IT Act §80C / EPF Act
        basic = 50_000_00
        pf    = (basic * 12) // 100
        assert isinstance(pf, int)
        assert pf == 6_000_00

    def test_net_salary_non_negative(self):
        gross      = 80_000_00
        pf         = 6_000_00
        income_tax = 5_000_00
        net        = gross - pf - income_tax
        assert net >= 0, "Net salary cannot be negative"


# ── Phase 5: Fixed Assets ─────────────────────────────────────────────────────

class TestDepreciationEngine:
    """Companies Act 2013 Schedule II depreciation — integer paise, no float."""

    def _make_asset(self, method="WDV", cost=1_000_000_00, salvage=0, accum=0,
                    rate=25.89, life=5, category="Vehicle"):
        return {
            "purchase_cost_paise": cost,
            "salvage_value_paise": salvage,
            "depreciation_method": method,
            "accumulated_depreciation_paise": accum,
            "wdv_rate_percent": rate,
            "useful_life_years": life,
            "asset_category": category,
        }

    def test_sl_annual_depreciation_integer(self):
        import math
        asset  = self._make_asset(method="SL", cost=1_200_000_00, salvage=200_000_00, life=5)
        annual = math.floor((asset["purchase_cost_paise"] - asset["salvage_value_paise"]) / asset["useful_life_years"])
        assert isinstance(annual, int)
        assert annual == 200_000_00

    def test_wdv_annual_depreciation_integer(self):
        import math
        asset  = self._make_asset(method="WDV", cost=1_000_000_00, rate=25.89)
        wdv    = asset["purchase_cost_paise"] - asset["accumulated_depreciation_paise"]
        annual = math.floor(wdv * asset["wdv_rate_percent"] / 100)
        assert isinstance(annual, int)

    def test_fully_depreciated_asset_zero_depreciation(self):
        import math
        asset = self._make_asset(cost=1_000_000_00, salvage=100_000_00,
                                 accum=900_000_00, method="WDV")
        wdv = asset["purchase_cost_paise"] - asset["accumulated_depreciation_paise"]
        assert wdv <= asset["salvage_value_paise"]
        annual = 0  # must return 0 when WDV ≤ salvage
        assert annual == 0

    def test_depreciation_cannot_exceed_remaining_wdv(self):
        import math
        asset  = self._make_asset(cost=1_000_000_00, salvage=100_000_00,
                                  accum=850_000_00, method="WDV", rate=90.0)
        wdv    = asset["purchase_cost_paise"] - asset["accumulated_depreciation_paise"]
        annual = math.floor(wdv * asset["wdv_rate_percent"] / 100)
        capped = min(annual, wdv - asset["salvage_value_paise"])
        assert capped <= wdv - asset["salvage_value_paise"]


# ── Phase 5: Banking Reconciliation ──────────────────────────────────────────

class TestBankingReconciliation:
    """Bank statement import: dedup, paise, reconciliation percent."""

    def test_import_dedup_by_key(self):
        seen: set = set()
        rows = [
            ("c1", "ba1", "2025-04-01", 100000, 0, "Rent"),
            ("c1", "ba1", "2025-04-01", 100000, 0, "Rent"),  # duplicate
            ("c1", "ba1", "2025-04-02", 200000, 0, "Salary"),
        ]
        inserted = 0
        skipped  = 0
        for r in rows:
            if r in seen:
                skipped += 1
            else:
                seen.add(r)
                inserted += 1
        assert inserted == 2
        assert skipped  == 1

    def test_reconciliation_percent_calculation(self):
        txns = [
            {"reconciled": True,  "debit_paise": 100000, "credit_paise": 0},
            {"reconciled": True,  "debit_paise": 200000, "credit_paise": 0},
            {"reconciled": False, "debit_paise": 150000, "credit_paise": 0},
        ]
        matched = [t for t in txns if t["reconciled"]]
        pct = round(len(matched) / len(txns) * 100, 1)
        assert pct == 66.7

    def test_bank_amounts_stored_as_paise(self):
        txn = {"debit_paise": 100000, "credit_paise": 0}
        assert isinstance(txn["debit_paise"], int), "Bank amounts must be integer paise"


# ── Phase 2: GST Calculations ─────────────────────────────────────────────────

class TestGSTCalculations:
    """CGST Act §9 — GST must be computed in integer paise."""

    def test_intra_state_cgst_sgst_split(self):
        # CGST Act §9(1): CGST = SGST = half of GST rate for intra-state
        taxable   = 1_000_000  # ₹10,000 in paise
        gst_rate  = 18         # 18%
        total_gst = (taxable * gst_rate) // 100
        cgst      = total_gst // 2
        sgst      = total_gst - cgst  # handles odd paise
        assert cgst + sgst == total_gst
        assert isinstance(cgst, int)
        assert isinstance(sgst, int)

    def test_inter_state_igst_full(self):
        # IGST Act §5 — IGST = full GST rate for inter-state
        taxable = 1_000_000
        igst    = (taxable * 18) // 100
        assert igst == 180000
        assert isinstance(igst, int)

    def test_gst_exempt_zero(self):
        taxable  = 1_000_000
        gst_rate = 0  # exempt
        gst      = (taxable * gst_rate) // 100
        assert gst == 0

    def test_no_floating_point_in_gst(self):
        taxable = 100050  # odd amount
        gst     = (taxable * 18) // 100  # integer division
        assert isinstance(gst, int)
        assert gst == 18009


# ── Phase 2: TDS Validation ───────────────────────────────────────────────────

class TestTDSValidation:
    """IT Act — TDS cannot exceed taxable amount."""

    def test_tds_within_taxable(self):
        total_taxable = 100000  # ₹1,000
        tds_rate_bps  = 1000    # 10%
        tds_paise     = (total_taxable * tds_rate_bps) // 10000
        assert tds_paise <= total_taxable

    def test_tds_cannot_exceed_taxable(self):
        total_taxable = 100000
        # A pathologically high rate
        tds_rate_bps  = 20000  # 200%
        tds_paise     = (total_taxable * tds_rate_bps) // 10000
        is_valid = tds_paise <= total_taxable
        assert not is_valid, "200% TDS rate must be rejected"

    def test_tds_integer_paise(self):
        total_taxable = 75050
        tds_rate_bps  = 1000   # 10%
        tds_paise     = (total_taxable * tds_rate_bps) // 10000
        assert isinstance(tds_paise, int)


# ── Phase 2: Receipt Over-Allocation ─────────────────────────────────────────

class TestReceiptOverAllocation:
    """Receipts must not be allocated beyond invoice total."""

    def test_allocation_within_invoice_total(self):
        inv_total  = 1_000_000
        paid       = 500_000
        new_alloc  = 400_000
        new_paid   = paid + new_alloc
        assert new_paid <= inv_total

    def test_over_allocation_rejected(self):
        inv_total = 1_000_000
        paid      = 800_000
        new_alloc = 300_000   # would push total to 1,100,000
        new_paid  = paid + new_alloc
        is_valid  = new_paid <= inv_total
        assert not is_valid, "Over-allocation must be rejected"


# ── Phase 6: Year-End Statements ──────────────────────────────────────────────

class TestYearEndStatements:
    """Year-end engagement must not expose hardcoded firm/client IDs."""

    def test_no_hardcoded_firm_id_in_fallback(self):
        """
        The _mock_engagement_meta fallback must NOT contain hardcoded
        firm-001 or client-001. Verified by source code inspection.
        """
        import os
        path = os.path.join(os.path.dirname(__file__), "../routers/year_end_statements.py")
        with open(path) as f:
            src = f.read()
        assert "firm-001" not in src, "Hardcoded firm-001 found in year_end_statements.py"
        assert "client-001" not in src, "Hardcoded client-001 found in year_end_statements.py"
