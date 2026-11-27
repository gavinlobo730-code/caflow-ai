"""
Adding a bank account: its ledger is made for it, and a ledger a bank cannot sit on is refused (POST-A-492).

WHAT THE OWNER SAW (18-11-2026)
    "The ledger is not created automatically; we have to do it manually." The route already creates one named "<bank> — <last
    four digits>" when the request names none, but the form's box said "— Not linked —" with help text telling the person to link
    an account, so a person picked one by hand, and nothing stopped them picking "Cash in Hand" for a bank. And when the
    automatic ledger could not be created the account was saved UNLINKED without a word, so its postings had nowhere to go.

WHAT THIS PINS
    * no ledger named: one is created, linked, named for the bank and its last four digits, and it is a Bank ledger;
    * its creation failing refuses the save in a sentence and saves NOTHING;
    * a ledger named is refused when it is not this client's (or a firm-level one), is not an asset or a liability, or is a
      cash ledger (the cash book reads every Cash-subtype ledger), on create and when an edit changes the link;
    * an account already on such a ledger can still be edited when the link is not what changes.
This runs on the in-memory double; the same path on a real database is one for the owner's own first account.
"""
import pytest
from fastapi import HTTPException

import routers.banking as banking
from domain.banking import account_kind
from models.banking import BankAccountIn, BankAccountUpdateIn
from tests.test_bank_account_setup_does_not_rewrite_other_legs import _setup, _add_bank, CLIENT, FIRM, CALLER


def _own(db, name, typ, sub, client=CLIENT):
    return db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": client, "account_code": f"9{len(db.rows('chart_of_accounts')):03d}",
                                         "account_name": name, "account_type": typ, "account_subtype": sub, "is_active": True})


def test_no_ledger_named_creates_one_for_the_account_named_for_the_bank_and_its_last_four_digits(monkeypatch):
    db = _setup(monkeypatch)
    res = _add_bank(db, name="HDFC Bank", account_no="50100234567890")
    ledger = next(r for r in db.rows("chart_of_accounts") if r["id"] == res["data"]["coa_account_id"])
    assert ledger["account_name"] == "HDFC Bank — 7890"
    assert (ledger["account_type"], ledger["account_subtype"]) == ("Asset", "Bank")
    assert ledger["client_id"] == CLIENT


def test_a_ledger_that_could_not_be_created_refuses_the_save_and_saves_nothing(monkeypatch):
    db = _setup(monkeypatch)
    monkeypatch.setattr(banking, "_ensure_bank_ledger", lambda *a, **k: None)
    with pytest.raises(HTTPException) as e:
        _add_bank(db)
    assert e.value.status_code == 422
    assert "could not be created, so the account was not saved" in str(e.value.detail)
    assert db.rows("bank_accounts") == []                       # not saved unlinked


@pytest.mark.parametrize("name,typ,sub,why", [
    ("Cash in Hand", "Asset", "Cash", "cash ledger"),
    ("Petty Cash", "Asset", "cash", "cash ledger"),
    ("Cash - Branch", "Asset", "Cash Branch", "cash ledger"),          # the cash book's test is "contains cash", and so is this
    ("Office Rent", "Expense", "Operating", "asset or a liability"),
    ("Sales", "Revenue", "Operating", "asset or a liability"),
])
def test_a_ledger_a_bank_cannot_sit_on_is_refused_at_creation(monkeypatch, name, typ, sub, why):
    db = _setup(monkeypatch)
    ledger = _own(db, name, typ, sub)
    with pytest.raises(HTTPException) as e:
        _add_bank(db, coa=ledger["id"])
    assert e.value.status_code == 422 and why in str(e.value.detail)
    assert db.rows("bank_accounts") == []


def test_another_clients_ledger_is_refused_but_a_firm_level_one_and_the_clients_own_are_allowed(monkeypatch):
    db = _setup(monkeypatch)
    theirs = _own(db, "Their bank", "Asset", "Bank", client="OTHER-CLIENT")
    with pytest.raises(HTTPException) as e:
        _add_bank(db, coa=theirs["id"])
    assert e.value.status_code == 422 and "not found for this client" in str(e.value.detail)
    firm_level = db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": None, "account_code": "9801", "account_name": "Shared bank",
                                               "account_type": "Asset", "account_subtype": "Bank", "is_active": True})
    assert _add_bank(db, name="Axis Bank", account_no="000011112222", coa=firm_level["id"])["success"] is True
    mine = _own(db, "Current account (my own)", "Asset", "Current Assets")
    assert _add_bank(db, name="SBI", account_no="000033334444", coa=mine["id"])["success"] is True


def test_a_card_or_an_overdraft_may_sit_on_a_liability_ledger(monkeypatch):
    db = _setup(monkeypatch)
    od = _own(db, "HDFC overdraft", "Liability", "Bank Overdraft")
    assert _add_bank(db, coa=od["id"])["success"] is True


def test_an_edit_that_changes_the_link_to_a_cash_ledger_is_refused_and_one_that_leaves_it_alone_is_not(monkeypatch):
    db = _setup(monkeypatch)
    acc = _add_bank(db)["data"]
    cash = _own(db, "Cash in Hand", "Asset", "Cash")
    with pytest.raises(HTTPException) as e:
        banking.update_bank_account(acc["id"], BankAccountUpdateIn(coa_account_id=cash["id"]), CALLER)
    assert e.value.status_code == 422 and "cash ledger" in str(e.value.detail)
    # an account that is ALREADY on such a ledger (made before this rule) is still editable when the link is not what changes
    for row in db.rows("bank_accounts"):
        row["coa_account_id"] = cash["id"]
    out = banking.update_bank_account(acc["id"], BankAccountUpdateIn(bank_name="HDFC Bank Ltd"), CALLER)
    assert out["success"] is True and out["data"]["bank_name"] == "HDFC Bank Ltd"
    # and re-sending the link it already has is not a change
    out = banking.update_bank_account(acc["id"], BankAccountUpdateIn(coa_account_id=cash["id"]), CALLER)
    assert out["success"] is True


def test_the_rule_in_words_names_what_to_do():
    assert account_kind.ledger_problem_for_a_bank("Asset", "Bank") is None
    assert account_kind.ledger_problem_for_a_bank("Liability", "Credit Card") is None
    assert account_kind.ledger_problem_for_a_bank("Asset", "Cash").startswith("That is a cash ledger")
    assert "asset or a liability" in account_kind.ledger_problem_for_a_bank("Expense", None)
    assert "asset or a liability" in account_kind.ledger_problem_for_a_bank(None, None)


# ── the form is served the ledgers a bank can use, and the name a new one would get ───────────────────────────────────

def _choices(**kw):
    return banking.bank_ledger_choices(**{"client_id": CLIENT, "account_id": None, "bank_name": "", "account_no": "",
                                          "current_user": CALLER, **kw})["data"]


def test_the_choices_leave_out_cash_ledgers_expense_ledgers_and_other_banks_ledgers(monkeypatch):
    db = _setup(monkeypatch)
    cash = _own(db, "Cash in Hand", "Asset", "Cash")
    exp = _own(db, "Office Rent", "Expense", "Operating")
    mine = _own(db, "Current account (my own)", "Asset", "Current Assets")
    first = _add_bank(db, name="HDFC Bank", account_no="50100234567890")["data"]
    ids = {c["id"] for c in _choices()["ledgers"]}
    assert mine["id"] in ids
    assert cash["id"] not in ids and exp["id"] not in ids
    assert first["coa_account_id"] not in ids                    # one ledger per bank


def test_an_account_being_edited_keeps_its_own_current_ledger_on_the_list_whatever_it_is(monkeypatch):
    db = _setup(monkeypatch)
    cash = _own(db, "Cash in Hand", "Asset", "Cash")
    acc = _add_bank(db)["data"]
    for row in db.rows("bank_accounts"):
        row["coa_account_id"] = cash["id"]                       # made before the rule
    assert cash["id"] in {c["id"] for c in _choices(account_id=acc["id"])["ledgers"]}
    assert cash["id"] not in {c["id"] for c in _choices()["ledgers"]}


def test_the_name_a_new_ledger_would_get_is_the_one_the_account_is_given(monkeypatch):
    db = _setup(monkeypatch)
    said = _choices(bank_name="HDFC Bank", account_no="50100234567890")["new_ledger_name"]
    made = _add_bank(db, name="HDFC Bank", account_no="50100234567890")["data"]
    ledger = next(r for r in db.rows("chart_of_accounts") if r["id"] == made["coa_account_id"])
    assert said == ledger["account_name"] == "HDFC Bank — 7890"
    assert _choices(bank_name="Axis Bank")["new_ledger_name"] == "Axis Bank"        # no digits yet: the bank's name alone
    assert _choices()["new_ledger_name"] is None                                     # nothing typed: nothing promised


def test_an_inactive_ledger_is_refused(monkeypatch):
    db = _setup(monkeypatch)
    off = db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": CLIENT, "account_code": "9701", "account_name": "Old bank",
                                        "account_type": "Asset", "account_subtype": "Bank", "is_active": False})
    with pytest.raises(HTTPException) as e:
        _add_bank(db, coa=off["id"])
    assert e.value.status_code == 422 and "not active" in str(e.value.detail)


def test_an_executive_who_names_no_ledger_is_told_a_manager_must_add_it_and_nothing_is_saved(monkeypatch):
    # The ledger is inserted as the caller and the chart's own gate is Manager or above, so for an Executive the old code saved the
    # account unlinked without a word; the new one said "try again", which never works. It now says who can.
    db = _setup(monkeypatch)
    executive = {**CALLER, "role": "Executive"}
    with pytest.raises(HTTPException) as e:
        banking.create_bank_account(BankAccountIn(client_id=CLIENT, bank_name="HDFC Bank", account_no="50100234567890",
                                                  opening_balance_paise=0, opening_balance_date="2026-04-01"), executive)
    assert e.value.status_code == 422 and "needs someone with write access to Accounting" in str(e.value.detail)
    assert db.rows("bank_accounts") == []
    mine = _own(db, "Current account (my own)", "Asset", "Current Assets")       # naming a ledger needs no chart write
    out = banking.create_bank_account(BankAccountIn(client_id=CLIENT, bank_name="HDFC Bank", account_no="50100234567890",
                                                    opening_balance_paise=0, opening_balance_date="2026-04-01",
                                                    coa_account_id=mine["id"]), executive)
    assert out["success"] is True
