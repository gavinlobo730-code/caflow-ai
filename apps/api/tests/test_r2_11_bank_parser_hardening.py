"""
R2.11 — bank statement parser hardening (surfaced by the R1.5 regression
review).

Covers three real, independent bugs in domain/banking/normalizer.py and
services/banking_service.py, all pure/DB-agnostic and unit-testable directly:

  1. _to_paise's Dr/Cr suffix handling was case/char-set sensitive
     (`.rstrip("DrCr")` strips individual characters 'D','r','C', not the
     substring) — only the exact mixed-case "Dr"/"Cr" suffix worked; "DR",
     "dr", "CR", "cr" all silently parsed to 0. It also discarded the Dr/Cr
     sign information entirely (an overdrawn "Dr" balance was stored the same
     as a positive "Cr" one).
  2. Single signed-Amount + Dr/Cr-indicator statement layouts (Date,
     Description, Amount, Dr/Cr, Balance — no separate Debit/Credit columns)
     were unsupported; every row misparsed as a debit.
  3. services/banking_service.py derived a statement's opening/closing
     balance from raw file position (new_rows[0] / new_rows[-1]), which
     inverts on a newest-first (descending) bank export.

Runs everywhere — pure parsing/derivation logic, no database.
"""
from __future__ import annotations

from domain.banking.normalizer import (
    _to_paise, detect_format, _validate_adapter, _rows_to_txns, parse_csv,
    StatementParseError,
)
from services.banking_service import _opening_closing_balance


# ─── 1. _to_paise: case-insensitive Dr/Cr suffix + correct sign ─────────────

class TestToPaiseDrCrSuffix:
    def test_mixed_case_dr_is_negative(self):
        assert _to_paise("150.00 Dr") == -15000

    def test_mixed_case_cr_is_positive(self):
        assert _to_paise("150.00 Cr") == 15000

    def test_all_caps_dr_previously_zeroed_now_negative(self):
        assert _to_paise("150.00 DR") == -15000

    def test_all_caps_cr_previously_zeroed_now_positive(self):
        assert _to_paise("150.00 CR") == 15000

    def test_all_lowercase_dr_previously_zeroed_now_negative(self):
        assert _to_paise("150.00 dr") == -15000

    def test_all_lowercase_cr_previously_zeroed_now_positive(self):
        assert _to_paise("150.00 cr") == 15000

    def test_no_space_before_suffix(self):
        assert _to_paise("150.00DR") == -15000
        assert _to_paise("150.00cr") == 15000

    def test_currency_symbol_and_commas_with_suffix(self):
        assert _to_paise("₹1,500.00 Dr") == -150000

    def test_parens_still_negative_without_suffix(self):
        assert _to_paise("(150.00)") == -15000

    def test_plain_number_no_suffix(self):
        assert _to_paise("150.00") == 15000

    def test_empty_and_dash_and_none(self):
        assert _to_paise("") == 0
        assert _to_paise("-") == 0
        assert _to_paise(None) == 0

    def test_int_and_float_inputs_unaffected(self):
        assert _to_paise(150) == 15000
        assert _to_paise(150.5) == 15050


# ─── 2. Single Amount + Dr/Cr indicator layout ──────────────────────────────

class TestAmountDrCrIndicatorLayout:
    HEADERS = ["Date", "Description", "Amount", "Dr/Cr", "Balance"]

    def test_detected_as_generic_amount_drcr(self):
        assert detect_format(self.HEADERS) == "generic_amount_drcr"

    def test_validator_accepts_matching_header(self):
        _validate_adapter("generic_amount_drcr", self.HEADERS)  # must not raise

    def test_debit_row_classified_correctly(self):
        rows = [self.HEADERS, ["05/04/2026", "ATM Withdrawal", "500.00", "Dr", "9500.00"]]
        txns = _rows_to_txns(rows, 0)
        assert len(txns) == 1
        assert txns[0].debit_paise == 50000
        assert txns[0].credit_paise == 0
        assert txns[0].balance_paise == 950000

    def test_credit_row_classified_correctly(self):
        rows = [self.HEADERS, ["05/04/2026", "Salary Credit", "20000.00", "Cr", "30000.00"]]
        txns = _rows_to_txns(rows, 0)
        assert len(txns) == 1
        assert txns[0].debit_paise == 0
        assert txns[0].credit_paise == 2000000

    def test_single_letter_indicator_variants(self):
        rows = [
            self.HEADERS,
            ["05/04/2026", "Row D", "100.00", "D", "100.00"],
            ["06/04/2026", "Row C", "200.00", "C", "300.00"],
        ]
        txns = _rows_to_txns(rows, 0)
        assert txns[0].debit_paise == 10000 and txns[0].credit_paise == 0
        assert txns[1].debit_paise == 0 and txns[1].credit_paise == 20000

    def test_unrecognized_indicator_skips_row_rather_than_guessing(self):
        rows = [
            self.HEADERS,
            ["05/04/2026", "Ambiguous row", "500.00", "??", "9500.00"],
            ["06/04/2026", "Good row", "100.00", "Cr", "9600.00"],
        ]
        txns = _rows_to_txns(rows, 0)
        assert len(txns) == 1
        assert txns[0].description == "Good row"

    def test_full_csv_parse_end_to_end(self):
        csv_text = (
            "Date,Description,Amount,Dr/Cr,Balance\n"
            "01/04/2026,Opening,1000.00,Cr,1000.00\n"
            "05/04/2026,ATM,500.00,Dr,500.00\n"
            "10/04/2026,Salary,20000.00,Cr,20500.00\n"
        )
        txns = parse_csv(csv_text)
        assert len(txns) == 3
        assert txns[1].debit_paise == 50000 and txns[1].credit_paise == 0
        assert txns[2].debit_paise == 0 and txns[2].credit_paise == 2000000

    def test_mismatched_header_still_raises(self):
        bad_headers = ["Date", "Description", "Amount", "Dr/Cr"]  # too few columns for 'balance' at index 4
        import pytest
        with pytest.raises(StatementParseError):
            _validate_adapter("generic_amount_drcr", bad_headers)


# ─── 3. services/banking_service._opening_closing_balance: date order ───────

class TestOpeningClosingBalanceDateOrder:
    def test_ascending_file_unaffected(self):
        rows = [
            {"transaction_date": "2026-04-01", "balance_paise": 100000},
            {"transaction_date": "2026-04-05", "balance_paise": 50000},
            {"transaction_date": "2026-04-10", "balance_paise": 2050000},
        ]
        opening, closing = _opening_closing_balance(rows)
        assert opening == 100000
        assert closing == 2050000

    def test_descending_newest_first_file_is_corrected(self):
        """The R2.11 bug: a newest-first export's raw first/last row balances
        are the CLOSING/OPENING balances respectively — inverted from what
        file-position derivation assumed."""
        rows = [
            {"transaction_date": "2026-04-10", "balance_paise": 2050000},
            {"transaction_date": "2026-04-05", "balance_paise": 50000},
            {"transaction_date": "2026-04-01", "balance_paise": 100000},
        ]
        opening, closing = _opening_closing_balance(rows)
        assert opening == 100000, "opening must be the EARLIEST date's balance, not row[0]'s"
        assert closing == 2050000, "closing must be the LATEST date's balance, not row[-1]'s"

    def test_single_day_statement_uses_file_order(self):
        rows = [
            {"transaction_date": "2026-04-05", "balance_paise": 100000},
            {"transaction_date": "2026-04-05", "balance_paise": 90000},
        ]
        opening, closing = _opening_closing_balance(rows)
        assert (opening, closing) == (100000, 90000)

    def test_empty_rows(self):
        assert _opening_closing_balance([]) == (0, 0)
