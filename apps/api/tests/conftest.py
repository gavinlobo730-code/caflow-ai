"""
Shared pytest fixtures.

Production now defaults REPORTING_PASSBOOK_MODE to "on" — the reporting passbook
(account_period_balances) is backfilled, trigger-maintained, and verified
paise-identical to the raw ledger, so accrual reports serve from it by default
(with automatic fall-back to the legacy engine on any error).

Tests, however, run against in-memory / fake-DB doubles that have no
account_period_balances rows, so they must exercise the LEGACY engine unless a
test opts into the passbook explicitly. This autouse fixture forces the mode to
"off" for every test; the passbook tests (test_passbook_read_path) call
monkeypatch.setenv(...) inside the test body, which runs after this fixture and
therefore overrides it.
"""
import pytest


@pytest.fixture(autouse=True)
def _passbook_off_by_default(monkeypatch):
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "off")
