"""
Opening-balance journalisation (multi-year hardening #1).

Master-record opening balances (customers/vendors/bank_accounts.opening_balance_paise)
are posted as ONE balanced opening journal contra'd to Opening Balance Equity, so the
Trial Balance / Balance Sheet reconcile with customer & vendor balances. Verifies:
  * a balanced opening journal is posted with AR (Dr), AP (Cr), Bank (Dr) + OBE contra
  * the trial balance stays balanced (debit == credit)
  * GL control accounts reconcile to the master opening figures
  * re-posting is idempotent (no duplicate journal, no doubled balances)
  * re-posting reflects a changed opening figure (single source of truth)
  * a bank account's mapped CoA account is used when set
  * nothing is posted when there are no opening balances
"""
from services import opening_balance_service as obs
from tests.e2e_harness import (
    FakeDB, wire_e2e, seed_standard_coa, trial_balance, coa_id, account_balance,
)

FIRM = "FIRM-A"


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [obs])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "financial_year_start": "2025-04-01"})
    seed_standard_coa(db, FIRM, "CLI")
    # Opening Balance Equity is not in the harness standard COA — add it (firm CoA).
    db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": "CLI",
                                  "account_name": "Opening Balance Equity", "is_active": True})
    return db


def _cust(db, paise):
    db.seed("customers", {"firm_id": FIRM, "client_id": "CLI", "is_active": True,
                          "opening_balance_paise": paise})


def _vendor(db, paise):
    db.seed("vendors", {"firm_id": FIRM, "client_id": "CLI", "is_active": True,
                        "opening_balance_paise": paise})


def test_posts_balanced_opening_journal(monkeypatch):
    db = _setup(monkeypatch)
    _cust(db, 500_000)
    _cust(db, 300_000)
    _vendor(db, 200_000)

    res = obs.post_opening_balances(FIRM, "CLI")
    assert res["posted"] is True
    assert res["ar_paise"] == 800_000
    assert res["ap_paise"] == 200_000
    assert res["opening_date"] == "2025-04-01"          # from client's FY start

    # Trial balance must be balanced (double-entry intact).
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]

    # GL controls reconcile to the master opening figures (no invoices yet).
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 800_000      # debit asset
    assert account_balance(db, coa_id(db, FIRM, "ap")) == -200_000     # credit liability
    # Net brought in = 800k − 200k = 600k credited to Opening Balance Equity.
    assert res["opening_equity_paise"] == 600_000


def test_idempotent_repost_does_not_duplicate(monkeypatch):
    db = _setup(monkeypatch)
    _cust(db, 500_000)

    obs.post_opening_balances(FIRM, "CLI")
    obs.post_opening_balances(FIRM, "CLI")        # run again

    opening = [e for e in db.rows("journal_entries") if e.get("entry_type") == "opening_balance"]
    assert len(opening) == 1                       # not duplicated
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 500_000   # not doubled


def test_repost_reflects_changed_opening_balance(monkeypatch):
    db = _setup(monkeypatch)
    db.seed("customers", {"id": "C1", "firm_id": FIRM, "client_id": "CLI",
                          "is_active": True, "opening_balance_paise": 500_000})
    obs.post_opening_balances(FIRM, "CLI")

    # CA corrects the opening balance; re-post must reflect it exactly.
    for c in db.rows("customers"):
        if c["id"] == "C1":
            c["opening_balance_paise"] = 700_000
    obs.post_opening_balances(FIRM, "CLI")

    assert account_balance(db, coa_id(db, FIRM, "ar")) == 700_000
    opening = [e for e in db.rows("journal_entries") if e.get("entry_type") == "opening_balance"]
    assert len(opening) == 1


def test_bank_opening_uses_mapped_coa_account(monkeypatch):
    db = _setup(monkeypatch)
    bank_coa = db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": "CLI",
                                             "account_name": "HDFC Current A/c", "is_active": True})
    db.seed("bank_accounts", {"firm_id": FIRM, "client_id": "CLI", "is_active": True,
                              "opening_balance_paise": 1_000_000, "coa_account_id": bank_coa["id"]})

    res = obs.post_opening_balances(FIRM, "CLI")
    assert res["posted"] is True and res["bank_paise"] == 1_000_000
    assert account_balance(db, bank_coa["id"]) == 1_000_000
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


def test_no_openings_posts_nothing(monkeypatch):
    db = _setup(monkeypatch)
    _cust(db, 0)
    res = obs.post_opening_balances(FIRM, "CLI")
    assert res["posted"] is False
    assert not any(e.get("entry_type") == "opening_balance" for e in db.rows("journal_entries"))


def test_reconciles_with_customer_balances(monkeypatch):
    # Trial-balance AR control == sum of customer opening balances.
    db = _setup(monkeypatch)
    _cust(db, 125_000)
    _cust(db, 375_000)
    obs.post_opening_balances(FIRM, "CLI")
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 500_000
