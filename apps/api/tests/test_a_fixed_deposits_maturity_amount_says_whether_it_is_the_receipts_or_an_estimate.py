"""A fixed deposit's maturity amount says whether it is the receipt's figure or an estimate (POST-A-134, second slice).

WHAT WAS WRONG
    The register screen computed `maturity_amount_paise` in the browser as annual compounding and inserted it as though it were the
    bank's. Banks usually compound a cumulative deposit quarterly and a payout deposit does not compound, so the stored figure
    could differ from the receipt, and both the register and the risk register ("FD Maturing Soon") showed it as the amount
    maturing with nothing to say it was an estimate.

WHAT IS HELD
    * the risk register names the basis of the amount: an estimate when the row says so or does not say (an older database, a test
      double), the receipt only when the row says it was typed from one;
    * the service that feeds it selects the flag;
    * migration 521 adds the column NOT NULL DEFAULT true, so a writer that does not know it can only ever produce an estimate;
    * the real-Postgres side is `tests/test_521_*_pg.py`; the browser side is `apps/web/lib/loans/fdMaturity.test.ts` and
      `apps/web/scripts/the-fd-register-says-whether-its-maturity-amount-is-an-estimate.test.ts`.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from domain.risk import register as rule

API = Path(__file__).resolve().parents[1]
AS_AT = date(2026, 9, 24)
MIGRATION = API / "migrations" / "521_a_fixed_deposit_says_whether_its_maturity_amount_is_the_receipts_or_an_estimate.sql"


def _fd(**over):
    row = {"id": "f", "client_id": "c", "bank_name": "SBI", "maturity_date": "2026-10-01", "maturity_amount_paise": 10_700_000}
    row.update(over)
    return row


def _row(**over):
    reg = rule.build(
        calendar=[], clients=[{"id": "c", "client_name": "X", "pan": "AABCU9603R"}], client_ids_with_recent_entries=set(),
        advance_tax_installments=[], advance_tax_tracked_client_ids=set(), advance_tax_filed_keys=set(), dsc_rows=[],
        loans=[], deposits=[_fd(**over)], as_at=AS_AT)
    [row] = [r for r in reg.rows if r.risk_type == "FD Maturing Soon"]
    return row


@pytest.mark.parametrize("flag", [True, None])
def test_an_estimate_or_a_row_that_does_not_say_is_called_an_estimate(flag):
    row = _row(maturity_amount_is_estimate=flag)
    assert "Estimated" in row.particulars["Maturity Amount"] and "receipt governs" in row.particulars["Maturity Amount"]


def test_a_row_without_the_key_at_all_is_an_estimate():
    assert "Estimated" in _row().particulars["Maturity Amount"]


def test_only_a_row_typed_from_a_receipt_is_called_the_receipts():
    assert _row(maturity_amount_is_estimate=False).particulars["Maturity Amount"] == "Per the deposit receipt"


def test_the_amount_itself_is_unchanged():
    assert _row(maturity_amount_is_estimate=False).amount_paise == 10_700_000 == _row().amount_paise


def test_the_service_selects_the_flag():
    source = (API / "services" / "risk_register_service.py").read_text(encoding="utf-8")
    assert re.search(r'\.table\("fixed_deposits"\)\s*\.select\("[^"]*maturity_amount_is_estimate', source), \
        "the risk register reads the flag with the amount, or it cannot say which it is"


def test_the_migration_adds_a_not_null_column_defaulting_to_true():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert re.search(r"ADD COLUMN IF NOT EXISTS maturity_amount_is_estimate BOOLEAN NOT NULL DEFAULT true", sql), \
        "a writer that does not know the column must only be able to produce an estimate"
