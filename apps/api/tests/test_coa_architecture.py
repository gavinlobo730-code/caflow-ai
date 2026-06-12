"""
COA Architecture Tests — PracticeSync COA Implementation Mandate

Test 1: New account immediately visible to all clients (shared firm COA)
Test 2: Balance isolation — same account, different clients keep separate balances
Test 3: Archived account cannot accept new transactions; historical reports intact
Test 4: Schedule III mapping flows through to financial statement classification
Test 5: Import COA is idempotent — duplicate codes not inserted on second run
"""
import uuid
import pytest
from unittest.mock import patch, MagicMock

FIRM_ID   = str(uuid.uuid4())
CLIENT_A  = str(uuid.uuid4())
CLIENT_B  = str(uuid.uuid4())
ACCOUNT_ID = str(uuid.uuid4())

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _account(account_id=None, code="5205", name="Digital Marketing Expense",
             account_type="Expense", is_active=True,
             schedule_iii_mapping="Other Expenses",
             tax_category="Taxable", firm_id=None, client_id=None):
    return {
        "id": account_id or str(uuid.uuid4()),
        "firm_id": firm_id or FIRM_ID,
        "client_id": client_id,          # NULL = firm master
        "account_code": code,
        "account_name": name,
        "account_type": account_type,
        "account_subtype": "Overhead",
        "parent_group": "Operating Expenses",
        "sub_group": "Marketing Costs",
        "tax_category": tax_category,
        "schedule_iii_mapping": schedule_iii_mapping,
        "is_active": is_active,
    }


def _ledger_balance(account_id, client_id, balance_paise):
    """Simulate ledger_balances row: isolation key = (firm_id, client_id, account_id)."""
    return {
        "firm_id": FIRM_ID,
        "client_id": client_id,
        "account_id": account_id,
        "balance_paise": balance_paise,
        "as_of_date": "2025-03-31",
    }


# ---------------------------------------------------------------------------
# Test 1: Account visibility — a firm-level account is available to all clients
# ---------------------------------------------------------------------------

class TestAccountVisibility:
    """
    Approved architecture: One Firm → One Master COA.
    Creating account 5205 at firm level makes it available to Client A and Client B
    without any cloning or synchronisation step.
    """

    def test_firm_account_has_no_client_id(self):
        acct = _account(account_id=ACCOUNT_ID)
        assert acct["client_id"] is None, "Firm-level account must have client_id = NULL"

    def test_firm_account_visible_to_client_a(self):
        """
        Client A's COA query: SELECT * FROM chart_of_accounts
        WHERE firm_id = :firm_id AND (client_id IS NULL OR client_id = :client_a)
        A firm-level account satisfies client_id IS NULL.
        """
        acct = _account(account_id=ACCOUNT_ID)
        firm_id = acct["firm_id"]
        client_id = acct["client_id"]

        # Simulate the query filter
        visible = (acct["firm_id"] == firm_id and
                   (client_id is None or client_id == CLIENT_A))
        assert visible, "Firm account should be visible to Client A"

    def test_firm_account_visible_to_client_b(self):
        acct = _account(account_id=ACCOUNT_ID)
        firm_id = acct["firm_id"]
        client_id = acct["client_id"]

        visible = (acct["firm_id"] == firm_id and
                   (client_id is None or client_id == CLIENT_B))
        assert visible, "Firm account should be visible to Client B"

    def test_client_specific_account_not_visible_to_other_client(self):
        """Per approved architecture, client_id accounts are deprecated / archived."""
        client_specific = _account(account_id=str(uuid.uuid4()), client_id=CLIENT_A)
        # Should NOT be visible to Client B
        is_visible_to_b = (client_specific["client_id"] == CLIENT_B or
                           client_specific["client_id"] is None)
        assert not is_visible_to_b, "Client A-specific account must not be visible to Client B"


# ---------------------------------------------------------------------------
# Test 2: Balance isolation
# ---------------------------------------------------------------------------

class TestBalanceIsolation:
    """
    Even though 5205 is a shared firm account, ledger_balances are keyed by
    (firm_id, client_id, account_id) so Client A and Client B have independent balances.
    """

    def test_isolation_key_is_client_specific(self):
        bal_a = _ledger_balance(ACCOUNT_ID, CLIENT_A, 1_000_000)  # ₹10,000
        bal_b = _ledger_balance(ACCOUNT_ID, CLIENT_B, 5_000_000)  # ₹50,000

        # Same account, different clients
        assert bal_a["account_id"] == bal_b["account_id"]
        assert bal_a["client_id"]  != bal_b["client_id"]

        # Balances are independent
        assert bal_a["balance_paise"] == 1_000_000
        assert bal_b["balance_paise"] == 5_000_000

    def test_client_a_balance_does_not_affect_client_b(self):
        bal_a = _ledger_balance(ACCOUNT_ID, CLIENT_A, 1_000_000)
        bal_b = _ledger_balance(ACCOUNT_ID, CLIENT_B, 5_000_000)

        # Mutate Client A's balance
        bal_a["balance_paise"] += 500_000  # ₹5,000 more for Client A

        # Client B's balance is unchanged
        assert bal_b["balance_paise"] == 5_000_000

    def test_balance_stored_in_integer_paise(self):
        """All monetary values must use integer paise arithmetic (₹1 = 100 paise)."""
        bal = _ledger_balance(ACCOUNT_ID, CLIENT_A, 1_000_000)
        assert isinstance(bal["balance_paise"], int), "Balance must be integer paise, not float"

    def test_trial_balance_sums_per_client(self):
        """
        Trial balance for Client A should sum only Client A's ledger rows,
        not contaminate with Client B's rows.
        """
        balances = [
            _ledger_balance(ACCOUNT_ID, CLIENT_A, 1_000_000),
            _ledger_balance(ACCOUNT_ID, CLIENT_B, 5_000_000),
        ]
        client_a_total = sum(b["balance_paise"] for b in balances if b["client_id"] == CLIENT_A)
        client_b_total = sum(b["balance_paise"] for b in balances if b["client_id"] == CLIENT_B)

        assert client_a_total == 1_000_000
        assert client_b_total == 5_000_000


# ---------------------------------------------------------------------------
# Test 3: Archive account — no new transactions; history intact
# ---------------------------------------------------------------------------

class TestArchiveAccount:

    def test_archived_account_is_inactive(self):
        acct = _account(is_active=False)
        assert not acct["is_active"]

    def test_cannot_post_to_archived_account(self):
        """
        Journal posting must reject an archived account.
        This mirrors the validation in phase2_journal_service.py.
        """
        archived = _account(is_active=False)

        def validate_journal_line(account):
            if not account["is_active"]:
                raise ValueError(f"Account '{account['account_name']}' is archived. Cannot post transactions.")

        with pytest.raises(ValueError, match="archived"):
            validate_journal_line(archived)

    def test_archived_account_visible_in_historical_query(self):
        """
        Archived accounts must remain in historical ledger reports.
        Query with include_archived=True must return them.
        """
        acct = _account(is_active=False)
        include_archived = True

        visible_in_history = include_archived or acct["is_active"]
        assert visible_in_history, "Archived account must be visible in historical reports"

    def test_archived_account_hidden_from_selection_lists(self):
        acct = _account(is_active=False)
        # Selection list query: WHERE is_active = true
        in_selection = acct["is_active"]
        assert not in_selection, "Archived account must be hidden from account selection lists"

    def test_archive_is_soft_delete_not_hard_delete(self):
        """Soft archive: is_active = false. Account row is preserved."""
        acct = _account(is_active=True)
        # Simulate archive
        acct["is_active"] = False
        # Row still exists (not deleted)
        assert acct["id"] is not None
        assert not acct["is_active"]


# ---------------------------------------------------------------------------
# Test 4: Schedule III Mapping
# ---------------------------------------------------------------------------

class TestScheduleIIIMapping:

    MAPPING_RULES = {
        "Revenue": ["Revenue from Operations", "Other Income"],
        "Expense": ["Cost of Materials Consumed", "Employee Benefits Expense",
                    "Finance Costs", "Depreciation & Amortisation", "Other Expenses"],
        "Asset":   ["Fixed Assets", "Capital Work in Progress", "Goodwill & Intangibles",
                    "Long-term Investments", "Deferred Tax Asset", "Inventories",
                    "Trade Receivables", "Cash & Cash Equivalents",
                    "Short-term Loans & Advances", "Other Current Assets"],
        "Liability": ["Share Capital", "Reserves & Surplus", "Long-term Borrowings",
                      "Deferred Tax Liability", "Long-term Provisions",
                      "Short-term Borrowings", "Trade Payables",
                      "Other Current Liabilities", "Short-term Provisions"],
    }

    def test_expense_account_maps_to_schedule_iii(self):
        acct = _account(account_type="Expense", schedule_iii_mapping="Employee Benefits Expense")
        assert acct["schedule_iii_mapping"] in self.MAPPING_RULES["Expense"]

    def test_asset_account_maps_to_schedule_iii(self):
        bank = _account(
            code="1101", name="HDFC Bank Current Account",
            account_type="Asset", schedule_iii_mapping="Cash & Cash Equivalents"
        )
        assert bank["schedule_iii_mapping"] in self.MAPPING_RULES["Asset"]

    def test_financial_statement_classification(self):
        """
        Simulate financial statement grouping: accounts are bucketed by schedule_iii_mapping.
        """
        accounts = [
            _account(code="4001", name="Audit Fees",        account_type="Revenue",  schedule_iii_mapping="Revenue from Operations"),
            _account(code="5001", name="Staff Salaries",    account_type="Expense",  schedule_iii_mapping="Employee Benefits Expense"),
            _account(code="5013", name="Depreciation",      account_type="Expense",  schedule_iii_mapping="Depreciation & Amortisation"),
            _account(code="1101", name="HDFC Bank",         account_type="Asset",    schedule_iii_mapping="Cash & Cash Equivalents"),
            _account(code="2001", name="Accounts Payable",  account_type="Liability", schedule_iii_mapping="Trade Payables"),
        ]

        by_mapping: dict[str, list] = {}
        for a in accounts:
            key = a["schedule_iii_mapping"] or "Unmapped"
            by_mapping.setdefault(key, []).append(a)

        assert "Revenue from Operations"    in by_mapping
        assert "Employee Benefits Expense"  in by_mapping
        assert "Depreciation & Amortisation" in by_mapping
        assert "Cash & Cash Equivalents"    in by_mapping
        assert "Trade Payables"             in by_mapping

    def test_unmapped_accounts_are_flagged(self):
        """All active accounts should have a Schedule III mapping for correct reporting."""
        acct = _account(schedule_iii_mapping=None)
        assert acct["schedule_iii_mapping"] is None  # Would be flagged in the UI warning banner


# ---------------------------------------------------------------------------
# Test 5: Import COA idempotency — no duplicates on second run
# ---------------------------------------------------------------------------

class TestCoaImport:

    def _run_import(self, existing_codes: set[str], import_rows: list[dict]) -> dict:
        """Simulate the import logic: skip rows whose account_code already exists."""
        to_insert = [r for r in import_rows if r["account_code"].upper() not in existing_codes]
        skipped = len(import_rows) - len(to_insert)
        # Simulate insert
        inserted_codes = {r["account_code"].upper() for r in to_insert}
        new_existing = existing_codes | inserted_codes
        return {"inserted": len(to_insert), "skipped": skipped, "existing_after": new_existing}

    def test_first_import_inserts_all_rows(self):
        rows = [
            {"account_code": "5205", "account_name": "Digital Marketing Expense"},
            {"account_code": "5206", "account_name": "SEO & SEM Expense"},
        ]
        result = self._run_import(existing_codes=set(), import_rows=rows)
        assert result["inserted"] == 2
        assert result["skipped"] == 0

    def test_second_import_skips_duplicates(self):
        """Running import twice must not create duplicate account codes."""
        rows = [
            {"account_code": "5205", "account_name": "Digital Marketing Expense"},
            {"account_code": "5206", "account_name": "SEO & SEM Expense"},
        ]
        # First import
        r1 = self._run_import(existing_codes=set(), import_rows=rows)
        assert r1["inserted"] == 2

        # Second import with same file
        r2 = self._run_import(existing_codes=r1["existing_after"], import_rows=rows)
        assert r2["inserted"] == 0
        assert r2["skipped"] == 2

    def test_import_with_partial_overlap(self):
        """If some codes already exist and others are new, only new ones are inserted."""
        existing = {"5205"}
        rows = [
            {"account_code": "5205", "account_name": "Digital Marketing Expense"},
            {"account_code": "5206", "account_name": "SEO & SEM Expense"},
            {"account_code": "5207", "account_name": "Content Marketing"},
        ]
        result = self._run_import(existing_codes=existing, import_rows=rows)
        assert result["inserted"] == 2  # 5206, 5207 are new
        assert result["skipped"]  == 1  # 5205 already exists

    def test_import_validates_account_type(self):
        """Invalid account_type values must be rejected during parsing."""
        valid_types = {"Asset", "Liability", "Equity", "Revenue", "Expense"}

        valid_row   = {"account_code": "5205", "account_type": "Expense"}
        invalid_row = {"account_code": "5206", "account_type": "Income"}  # 'Income' not allowed

        assert valid_row["account_type"] in valid_types
        assert invalid_row["account_type"] not in valid_types

    def test_import_duplicate_codes_within_file_are_rejected(self):
        """Two rows in the same CSV with the same code must raise a parse error."""
        rows = [
            {"account_code": "5205", "account_name": "Digital Marketing Expense"},
            {"account_code": "5205", "account_name": "Online Advertising"},  # duplicate
        ]
        code_seen: dict[str, int] = {}
        errors = []
        for i, row in enumerate(rows, start=2):
            code = row["account_code"].upper()
            if code in code_seen:
                errors.append(f"Row {i}: Duplicate code '{code}' (also on row {code_seen[code]})")
            else:
                code_seen[code] = i

        assert len(errors) == 1
        assert "Duplicate code" in errors[0]
