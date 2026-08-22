"""
Saving a bank account must not reconcile anybody else's opening balances — and a
bank account must not disappear when it is deactivated.

WHAT HAPPENED
    A CA added an HDFC account to a live client with 12,838 posted entries. The
    save fired opening_balance_service.post_opening_balances with no scope, which
    reconciles the WHOLE opening position against the master records. The vendor
    masters all carried zero while the GL carried 40.54 lakh of opening Trade
    Payables from a migration, so the delta engine did what it is built to do and
    posted Trade Payables Dr 40,54,000 — from the bank screen, with no warning and
    no confirmation, inside the same entry as the bank's own 50,000.

    Nothing about it was wrong arithmetically. It was wrong that a bank screen
    could do it at all.

THE OTHER HALF
    The same session created two bank accounts, both defaulting their Ledger
    Account to the one existing Bank row, so the balance sheet showed a single
    1,00,000 line that could not be attributed to either bank and neither account
    could be reconciled. Deactivating one then removed it from the list entirely —
    the API filtered is_active — while its opening balance stayed in the GL, as it
    correctly should. Money on the balance sheet, no account to explain it, and no
    way back to the account: the deactivation dialog's promise that "you can
    reactivate it later by editing it" was not something the app could keep.
"""
import pytest

import routers.banking as banking
import routers.customers as cust
import routers.vendors as ven
import services.opening_balance_service as obs
from models.banking import BankAccountIn, BankAccountUpdateIn
from models.parties import CustomerIn, VendorIn
from tests.e2e_harness import (
    FakeDB, wire_e2e, seed_standard_coa, coa_id, account_balance, trial_balance,
)

FIRM = "FIRM-BS"
CLIENT = "CLI-BS"
CALLER = {"firm_id": FIRM, "id": "u-int-1", "auth_user_id": "u1",
          "email": "ca@firm.test", "role": "Partner"}


def _setup(monkeypatch, mods=None):
    db = FakeDB()
    # routers/banking.py::_db reads SUPABASE_URL directly rather than a module
    # _USE_MOCK, so wire_e2e alone leaves it on the no-database path — where every
    # endpoint returns a canned success and nothing is asserted.
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    wire_e2e(monkeypatch, db, mods or [banking, cust, ven, obs])
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM,
                        "financial_year_start": "2026-04-01"})
    seed_standard_coa(db, FIRM, CLIENT)
    db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": CLIENT,
                                  "account_name": "Opening Balance Equity",
                                  "account_code": "3004", "is_active": True})
    return db


def _add_bank(db, *, name="HDFC Bank", account_no="50100234567890",
              opening=0, coa=None, date="2026-04-01"):
    return banking.create_bank_account(BankAccountIn(
        client_id=CLIENT, bank_name=name, account_no=account_no,
        opening_balance_paise=opening, opening_balance_date=date,
        coa_account_id=coa), CALLER)


# ══════════════════════════════════════════════════════════════════════════════
# The bank screen stays on its own leg
# ══════════════════════════════════════════════════════════════════════════════

def test_adding_a_bank_account_leaves_stale_payables_alone(monkeypatch):
    """The regression. A vendor opening balance is posted, then removed from the
    master — leaving the GL carrying a payable the masters no longer claim. Adding
    a bank account must not be what corrects it."""
    db = _setup(monkeypatch)
    ven.create_vendor(VendorIn(client_id=CLIENT, name="Supplier",
                               opening_balance_paise=4_054_000), CALLER)
    ap = coa_id(db, FIRM, "ap")
    assert account_balance(db, ap) == -4_054_000          # credit balance, a payable

    # The master goes to zero WITHOUT a re-sync (a deletion, a migration, a fix
    # applied straight to the table) — the GL is now drifted, and stays drifted.
    for row in db.rows("vendors"):
        row["opening_balance_paise"] = 0

    res = _add_bank(db, opening=50_000)
    assert res["success"] is True
    assert account_balance(db, ap) == -4_054_000, (
        "adding a bank account reconciled Trade Payables — the drift is real, but "
        "correcting it is the Opening Balances screen's job, not the bank form's")


def test_adding_a_bank_account_still_posts_its_own_opening(monkeypatch):
    """The other half: scoping must not stop the bank leg from working."""
    db = _setup(monkeypatch)
    res = _add_bank(db, opening=50_000)
    assert res["success"] is True
    ledger = res["data"]["coa_account_id"]
    assert account_balance(db, ledger) == 50_000
    tb = trial_balance(db, FIRM, CLIENT)
    assert tb["total_debit_paise"] == tb["total_credit_paise"], (
        "the scoped opening entry did not balance")


def test_a_scoped_sync_balances_through_opening_balance_equity(monkeypatch):
    db = _setup(monkeypatch)
    _add_bank(db, opening=50_000)
    obe = next(r["id"] for r in db.rows("chart_of_accounts")
               if r.get("account_name") == "Opening Balance Equity")
    assert account_balance(db, obe) == -50_000


def test_a_customer_save_leaves_the_bank_leg_alone(monkeypatch):
    """Scoping is not a bank special case — every master screen owns one leg."""
    db = _setup(monkeypatch)
    res = _add_bank(db, opening=50_000)
    ledger = res["data"]["coa_account_id"]
    for row in db.rows("bank_accounts"):
        row["opening_balance_paise"] = 0            # drift the bank leg

    cust.create_customer(CustomerIn(client_id=CLIENT, name="Buyer",
                                    opening_balance_paise=700_000), CALLER)
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 700_000
    assert account_balance(db, ledger) == 50_000, (
        "a customer save reconciled the bank leg")


def test_the_opening_balances_screen_still_reconciles_everything(monkeypatch):
    """Unscoped is unchanged — the screen whose job this IS still fixes all of it."""
    db = _setup(monkeypatch)
    ven.create_vendor(VendorIn(client_id=CLIENT, name="Supplier",
                               opening_balance_paise=4_054_000), CALLER)
    for row in db.rows("vendors"):
        row["opening_balance_paise"] = 0

    out = obs.post_opening_balances(FIRM, CLIENT, created_by="u-int-1")
    assert out["posted"] is True
    assert account_balance(db, coa_id(db, FIRM, "ap")) == 0
    tb = trial_balance(db, FIRM, CLIENT)
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


# ══════════════════════════════════════════════════════════════════════════════
# One book, one opening date
# ══════════════════════════════════════════════════════════════════════════════

def test_the_opening_date_follows_the_family_not_the_form(monkeypatch):
    """The books open on 2026-04-01. A bank account whose form said 2025-04-01
    must not open a second opening date in a prior financial year.

    financial_year_start is cleared deliberately: that is the state the live
    client was in, and with it set the date resolves correctly anyway, so a
    fixture that left it populated would not be testing anything."""
    db = _setup(monkeypatch)
    for row in db.rows("clients"):
        row["financial_year_start"] = None
    ven.create_vendor(VendorIn(client_id=CLIENT, name="Supplier",
                               opening_balance_paise=100_000,
                               opening_balance_date="2026-04-01"), CALLER)
    first = [e for e in db.rows("journal_entries")
             if e.get("source_type") == obs.OPENING_SOURCE]
    assert first and str(first[0]["entry_date"])[:10] == "2026-04-01"

    _add_bank(db, opening=50_000, date="2025-04-01")
    dates = {str(e["entry_date"])[:10] for e in db.rows("journal_entries")
             if e.get("source_type") == obs.OPENING_SOURCE}
    assert dates == {"2026-04-01"}, (
        f"the opening family is spread across {sorted(dates)} — every opening entry "
        f"for a client belongs on one date")


# ══════════════════════════════════════════════════════════════════════════════
# One ledger per bank
# ══════════════════════════════════════════════════════════════════════════════

def test_a_bank_account_gets_its_own_ledger(monkeypatch):
    db = _setup(monkeypatch)
    res = _add_bank(db)
    assert res["success"] is True
    ledger_id = res["data"]["coa_account_id"]
    assert ledger_id, "the bank account was saved with no ledger account"
    row = next(r for r in db.rows("chart_of_accounts") if r["id"] == ledger_id)
    assert row["account_type"] == "Asset" and row["account_subtype"] == "Bank"
    assert "7890" in row["account_name"] and "HDFC" in row["account_name"]
    assert row["account_code"] != coa_id(db, FIRM, "bank")


def test_two_banks_get_two_ledgers(monkeypatch):
    db = _setup(monkeypatch)
    a = _add_bank(db, name="HDFC Bank", account_no="50100234567890")
    b = _add_bank(db, name="Cosmos Bank", account_no="1234567899")
    assert a["data"]["coa_account_id"] != b["data"]["coa_account_id"]
    codes = {r["account_code"] for r in db.rows("chart_of_accounts")
             if r.get("account_code")}
    assert len(codes) == len([r for r in db.rows("chart_of_accounts")
                              if r.get("account_code")]), "duplicate account codes"


def test_sharing_a_ledger_with_another_bank_is_refused(monkeypatch):
    """What the two accounts in the report did: both picked 1101, so the balance
    sheet showed one 1,00,000 line and neither could be reconciled."""
    from fastapi import HTTPException
    db = _setup(monkeypatch)
    first = _add_bank(db, name="HDFC Bank", account_no="50100234567890")
    taken = first["data"]["coa_account_id"]

    with pytest.raises(HTTPException) as e:
        _add_bank(db, name="Cosmos Bank", account_no="1234567899", coa=taken)
    assert e.value.status_code == 422
    assert "already linked" in str(e.value.detail)


def test_editing_a_bank_onto_a_taken_ledger_is_refused(monkeypatch):
    from fastapi import HTTPException
    db = _setup(monkeypatch)
    first = _add_bank(db, name="HDFC Bank", account_no="50100234567890")
    second = _add_bank(db, name="Cosmos Bank", account_no="1234567899")

    with pytest.raises(HTTPException) as e:
        banking.update_bank_account(second["data"]["id"], BankAccountUpdateIn(
            coa_account_id=first["data"]["coa_account_id"]), CALLER)
    assert e.value.status_code == 422


def test_a_bank_may_keep_its_own_ledger_when_edited(monkeypatch):
    """The conflict check must not fire on an account's own ledger."""
    db = _setup(monkeypatch)
    acc = _add_bank(db, name="HDFC Bank", account_no="50100234567890")
    res = banking.update_bank_account(acc["data"]["id"], BankAccountUpdateIn(
        coa_account_id=acc["data"]["coa_account_id"], bank_name="HDFC Bank Ltd"), CALLER)
    assert res["success"] is True


# ══════════════════════════════════════════════════════════════════════════════
# A deactivated account stays reachable
# ══════════════════════════════════════════════════════════════════════════════

def test_a_deactivated_account_is_hidden_from_pickers_by_default(monkeypatch):
    db = _setup(monkeypatch)
    acc = _add_bank(db, name="Cosmos Bank", account_no="1234567899")
    banking.update_bank_account(acc["data"]["id"], BankAccountUpdateIn(is_active=False), CALLER)
    listed = banking.list_bank_accounts(client_id=CLIENT, current_user=CALLER)["data"]
    assert [a["bank_name"] for a in listed] == []


def test_a_deactivated_account_is_still_reachable_when_asked_for(monkeypatch):
    """Without this the account vanishes while its opening balance stays in the
    GL, and the deactivation dialog's promise of reactivation is unkeepable."""
    db = _setup(monkeypatch)
    acc = _add_bank(db, name="Cosmos Bank", account_no="1234567899", opening=50_000)
    banking.update_bank_account(acc["data"]["id"], BankAccountUpdateIn(is_active=False), CALLER)

    listed = banking.list_bank_accounts(client_id=CLIENT, include_inactive=True,
                                        current_user=CALLER)["data"]
    assert [a["bank_name"] for a in listed] == ["Cosmos Bank"]
    assert listed[0]["is_active"] is False
    # And the money it explains is still on the books, which is why it has to be
    # visible: deactivating an account is not a claim the money was never there.
    assert account_balance(db, acc["data"]["coa_account_id"]) == 50_000


def test_a_deactivated_account_can_be_reactivated(monkeypatch):
    db = _setup(monkeypatch)
    acc = _add_bank(db, name="Cosmos Bank", account_no="1234567899")
    banking.update_bank_account(acc["data"]["id"], BankAccountUpdateIn(is_active=False), CALLER)
    res = banking.update_bank_account(acc["data"]["id"], BankAccountUpdateIn(is_active=True), CALLER)
    assert res["success"] is True
    listed = banking.list_bank_accounts(client_id=CLIENT, current_user=CALLER)["data"]
    assert [a["bank_name"] for a in listed] == ["Cosmos Bank"]


def test_a_second_client_banking_at_the_same_branch_still_gets_a_ledger(monkeypatch):
    """chart_of_accounts is unique on (firm_id, account_name) firm-wide, so two
    clients of one CA both banking at HDFC with the same last four digits collide.
    The bank account must still get a ledger, not fall back to unlinked."""
    db = _setup(monkeypatch)
    db.seed("clients", {"id": "CLI-TWO", "firm_id": FIRM,
                        "financial_year_start": "2026-04-01"})
    seed_standard_coa(db, FIRM, "CLI-TWO")
    first = _add_bank(db, name="HDFC Bank", account_no="50100234567890")

    second = banking.create_bank_account(BankAccountIn(
        client_id="CLI-TWO", bank_name="HDFC Bank", account_no="99900234567890",
        opening_balance_paise=0), CALLER)
    assert second["success"] is True
    assert second["data"]["coa_account_id"], "the second client's bank was saved unlinked"
    assert second["data"]["coa_account_id"] != first["data"]["coa_account_id"]
    names = [r["account_name"] for r in db.rows("chart_of_accounts")
             if str(r.get("account_name", "")).startswith("HDFC Bank — 7890")]
    assert len(names) == len(set(names)), f"duplicate ledger names: {names}"
