"""A company credit card is a bank account, and it is a liability (BANK-21).

WHAT WAS WRONG
    `bank_accounts.account_type` admitted Current, Savings, Cash Credit and
    Overdraft and nothing else, so a company credit card could not be created
    at all: its statement could not be imported, its spend could not be coded
    through the bank workflow, and the monthly payment out of the current
    account posted to whatever ledger somebody picked, with the underlying
    expenses never recorded. A card is ordinary for any SME with travel or
    online spend.

WHAT IS PINNED HERE, AND THE FIRST ONE IS THE POINT
    THE DOUBLE ENTRY DOES NOT MOVE. `posting_map.build_lines` is
    direction-driven, so a LIABILITY ledger makes it already right both ways
    round — Dr Expense / Cr Card on a purchase, Dr Card / Cr Bank on a payment.
    Nothing in the posting map, the settlement or the reversal changes, and a
    test says so rather than leaving it to be re-discovered.

    What DOES differ is the sign of the BALANCE, and there is exactly one
    convention inside the product with two translations at the edge — the
    figure read off a statement and the figure shown back. Both are asserted,
    in both directions, and so is the fact that a MOVEMENT never flips.

    And the Transfer derivation, which could not recognise a card's ledger at
    all: it required account_type == 'Asset', which a card's and an
    overdraft's never are.
"""
from __future__ import annotations

import inspect
import re
from datetime import date
from pathlib import Path

import pytest

import routers.banking as bank
import services.bank_register_service as brs
from domain.banking import account_kind as ak
from domain.banking.account_category import category_for_account
from domain.banking.posting_map import build_lines, build_transfer_lines
from domain.reporting.schedule_iii import bs_bucket
from models.banking import BankAccountIn, BankAccountUpdateIn

_MIG = Path(__file__).resolve().parent.parent / "migrations"
_M386 = "386_a_credit_card_is_a_bank_account_that_is_a_liability.sql"
_M386_BACK = "386_a_credit_card_is_a_bank_account_that_is_a_liability_rollback.sql"

CARD, BANKACC, EXPENSE = "card-ledger", "bank-ledger", "expense-ledger"


# ══ the vocabulary ═══════════════════════════════════════════════════════════

def test_the_five_kinds_of_account():
    assert ak.ACCOUNT_TYPES == ("Current", "Savings", "Cash Credit",
                                "Overdraft", "Credit Card")


@pytest.mark.parametrize("account_type,shape", [
    ("Current", ("Asset", "Bank")),
    ("Savings", ("Asset", "Bank")),
    ("Cash Credit", ("Liability", "Bank Overdraft")),
    ("Overdraft", ("Liability", "Bank Overdraft")),
    ("Credit Card", ("Liability", "Credit Card")),
    (None, ("Asset", "Bank")),
    ("something else", ("Asset", "Bank")),
])
def test_each_kind_gets_the_right_ledger(account_type, shape):
    assert ak.ledger_shape_for(account_type) == shape
    # The router re-exports it, so the old import still resolves.
    assert bank.ledger_shape_for_bank(account_type) == shape


def test_the_card_subtype_presents_where_the_overdraft_one_does():
    """A company card outstanding is a loan repayable on demand from a bank.
    Without the classifier knowing the word it would fall to Other Current
    Liabilities BY ACCIDENT rather than by a decision. ⚠️ `[S]` — Schedule III
    could not be read here and the alternative is defensible; both are current
    liabilities, so no total moves, only which caption."""
    assert bs_bucket("Liability", "Credit Card") == "Short-term Borrowings"
    assert bs_bucket("Liability", "Bank Overdraft") == "Short-term Borrowings"
    # And nothing else moved.
    assert bs_bucket("Asset", "Bank") == "Cash & Cash Equivalents"
    assert bs_bucket("Liability", "Trade Payable") == "Trade Payables"


# ══ THE DOUBLE ENTRY DOES NOT MOVE ═══════════════════════════════════════════

def test_a_purchase_on_the_card_credits_the_card_and_debits_the_expense():
    """Money OUT of the card account, in exactly the sense the posting map
    means — so the liability grows and the expense is recorded, with no change
    to build_lines at all."""
    lines = build_lines(50_000, is_credit=False,
                        bank_account_id=CARD, counter_account_id=EXPENSE)
    assert lines == [
        {"account_id": EXPENSE, "debit_paise": 50_000, "credit_paise": 0},
        {"account_id": CARD, "debit_paise": 0, "credit_paise": 50_000},
    ]


def test_paying_the_card_from_the_bank_debits_the_card_and_credits_the_bank():
    """The Contra. Money out of the CURRENT account reduces the liability."""
    lines = build_transfer_lines(50_000, is_credit=False,
                                 bank_account_id=BANKACC, to_bank_account_id=CARD)
    debits = {l["account_id"] for l in lines if l["debit_paise"]}
    credits = {l["account_id"] for l in lines if l["credit_paise"]}
    assert debits == {CARD} and credits == {BANKACC}


def test_the_posting_map_knows_nothing_about_a_card_and_must_not():
    """Direction-driven is what makes a card free. A branch on the account
    type here would be a second rule to keep in step with the first."""
    import domain.banking.posting_map as pm
    src = inspect.getsource(pm)
    assert "Credit Card" not in src
    assert "account_kind" not in src


# ══ the sign of the balance ══════════════════════════════════════════════════

@pytest.mark.parametrize("account_type", ["Current", "Savings", "Cash Credit", "Overdraft"])
def test_every_other_account_is_the_identity(account_type):
    for amount in (0, 1, -1, 5_00_000):
        assert ak.to_ledger_sign(account_type, amount) == amount
        assert ak.to_statement_sign(account_type, amount) == amount


def test_a_card_statement_states_the_amount_owed_and_the_ledger_holds_a_credit():
    assert ak.to_ledger_sign("Credit Card", 50_000_00) == -50_000_00
    assert ak.to_statement_sign("Credit Card", -50_000_00) == 50_000_00


def test_the_two_translations_are_inverses():
    for amount in (0, 1, -7, 12_345_67):
        assert ak.to_statement_sign("Credit Card",
                                    ak.to_ledger_sign("Credit Card", amount)) == amount


def test_the_label_says_which_way_the_column_reads():
    assert ak.balance_label("Credit Card") == "Amount owed"
    assert ak.balance_label("Current") == "Balance"
    assert ak.balance_label("Overdraft") == "Balance"


def test_an_overdraft_is_owed_to_the_bank_but_its_statement_is_not_mirrored():
    """An overdraft is drawn against a bank ACCOUNT and the bank prints that
    account's balance the ordinary way — overdrawn is negative. A card
    statement never prints a negative; it prints "total amount due"."""
    assert ak.is_owed_to_the_bank("Overdraft") is True
    assert ak.is_credit_card("Overdraft") is False
    assert ak.to_ledger_sign("Overdraft", -50_000_00) == -50_000_00


# ══ what the register hands back ═════════════════════════════════════════════

def _register_body():
    return {
        "account": {"account_type": "Credit Card", "opening_balance_paise": -10_000_00},
        "lines": [{"debit_paise": 5_000_00, "credit_paise": 0, "amount_paise": 5_000_00,
                   "balance_paise": -15_000_00, "statement_balance_paise": -15_000_00,
                   "balance_delta_paise": 0}],
        "summary": {"opening_balance_paise": -10_000_00, "closing_balance_paise": -15_000_00,
                    "deposits_paise": 0, "withdrawals_paise": 5_000_00, "line_count": 1},
        "divergence": None,
        "view_opening_balance_paise": -10_000_00,
    }


def test_the_register_hands_a_card_back_in_the_sign_the_ca_reads():
    out = brs.BankRegisterService._present(_register_body(), "Credit Card")
    assert out["account"]["opening_balance_paise"] == 10_000_00
    assert out["summary"]["closing_balance_paise"] == 15_000_00
    assert out["view_opening_balance_paise"] == 10_000_00
    assert out["lines"][0]["balance_paise"] == 15_000_00
    assert out["balance_label"] == "Amount owed"


def test_a_movement_never_flips():
    """A Rs 5,000 purchase is Rs 5,000 on either kind of account. Flipping a
    magnitude would make every debit negative."""
    out = brs.BankRegisterService._present(_register_body(), "Credit Card")
    line = out["lines"][0]
    assert line["debit_paise"] == 5_000_00
    assert line["amount_paise"] == 5_000_00
    assert out["summary"]["withdrawals_paise"] == 5_000_00
    assert out["summary"]["line_count"] == 1


def test_the_register_of_a_bank_account_is_untouched():
    body = _register_body()
    assert brs.BankRegisterService._present(body, "Current") is body


def test_the_divergence_flips_with_the_balances_it_names():
    body = _register_body()
    body["divergence"] = {"index": 0, "computed_balance_paise": -15_000_00,
                          "statement_balance_paise": -14_000_00, "delta_paise": 1_000_00}
    out = brs.BankRegisterService._present(body, "Credit Card")
    assert out["divergence"]["computed_balance_paise"] == 15_000_00
    assert out["divergence"]["statement_balance_paise"] == 14_000_00
    assert out["divergence"]["delta_paise"] == -1_000_00


def test_both_register_paths_come_through_the_one_presenter():
    """There are two — the SQL function and its Python twin, held identical by
    a parity test. Converting inside either would make them disagree and would
    give the other one a chance to forget."""
    src = inspect.getsource(brs.BankRegisterService.register)
    assert src.count("self._present(") == 2


# ══ the Transfer derivation ══════════════════════════════════════════════════

def _card_ledger():
    return {"id": CARD, "account_type": "Liability", "account_subtype": "Credit Card",
            "account_name": "HDFC Card — 4321", "system_account_key": None}


def test_a_card_ledger_picked_on_a_bank_line_is_a_transfer():
    """Paying the company card out of the current account. Before this it was
    coded "Other" and posted as an EXPENSE against a liability ledger."""
    got = category_for_account(_card_ledger(), is_credit=False, is_bank_ledger=True)
    assert got.category == "Transfer"


def test_the_name_test_could_never_have_answered_for_a_liability_ledger():
    """`_looks_like_bank_or_cash` requires account_type == 'Asset', which a
    card's and an overdraft's ledger never is — so the FACT is the only thing
    that can settle it."""
    got = category_for_account(_card_ledger(), is_credit=False, is_bank_ledger=None)
    assert got.category != "Transfer"


def test_the_fact_is_not_required_and_nothing_else_changes():
    """None means "not established" and the name test answers as it always
    did — every existing chart behaves byte for byte as before."""
    asset_bank = {"id": BANKACC, "account_type": "Asset", "account_subtype": "Bank",
                  "account_name": "HDFC Bank — 7890", "system_account_key": None}
    assert category_for_account(asset_bank, is_credit=True).category == "Transfer"
    expense = {"id": EXPENSE, "account_type": "Expense", "account_subtype": "Operating",
               "account_name": "Travel", "system_account_key": None}
    assert category_for_account(expense, is_credit=False).category == "Expense"


def test_the_service_supplies_the_fact_from_the_bank_accounts_table():
    import services.banking_service as bs
    src = inspect.getsource(bs.BankingService._confirmed_category)
    assert "is_bank_ledger=self._is_bank_ledger(" in src
    resolver = inspect.getsource(bs.BankingService._is_bank_ledger)
    assert 'table("bank_accounts")' in resolver
    assert 'eq("coa_account_id", coa_account_id)' in resolver
    assert "return None" in resolver, (
        "a failed read must not assert the account is NOT a bank ledger")


# ══ the model ════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("value", ["Credit Card", "Current", "Overdraft"])
def test_a_known_account_type_is_accepted(value):
    assert BankAccountIn(client_id="C1", bank_name="HDFC", account_no="1",
                         account_type=value).account_type == value


@pytest.mark.parametrize("value", ["credit card", "Card", "Loan", ""])
def test_an_unknown_account_type_is_refused_rather_than_500ing(value):
    """The DB CHECK was the only enforcement, so a value outside it came back
    as a 500-shaped database error rather than a refusal naming the field —
    and it also decides the LEDGER, so an unrecognised value would silently
    take the asset branch."""
    with pytest.raises(Exception):
        BankAccountIn(client_id="C1", bank_name="HDFC", account_no="1",
                      account_type=value)


def test_the_patch_door_validates_too():
    """A validator only at the create door is one PATCH from being none."""
    with pytest.raises(Exception):
        BankAccountUpdateIn(account_type="Card")
    assert BankAccountUpdateIn(account_type=None).account_type is None
    assert BankAccountUpdateIn(account_type="Credit Card").account_type == "Credit Card"


# ══ the router's two boundaries ══════════════════════════════════════════════

def test_the_opening_balance_is_stored_in_ledger_sign():
    src = inspect.getsource(bank.create_bank_account)
    assert 'account_kind.to_ledger_sign(' in src
    assert 'account_kind.to_statement_sign(' in src


def test_a_patch_reads_the_type_the_request_leaves_the_account_in():
    """A PATCH may carry a new opening balance, a new account_type, or both;
    reading the STORED type while the request changes it would store the
    figure under the old convention."""
    src = inspect.getsource(bank.update_bank_account)
    assert 'effective_type = update.get("account_type", prior.get("account_type"))' in src
    assert "account_kind.to_ledger_sign(\n            effective_type" in src


def test_changing_the_type_re_signs_the_balance_already_stored():
    src = inspect.getsource(bank.update_bank_account)
    assert '-int(prior.get("opening_balance_paise") or 0)' in src


def test_the_account_list_hands_back_the_statements_sign():
    src = inspect.getsource(bank._annotate_accounts)
    assert 'r["opening_balance_paise"] = account_kind.to_statement_sign(' in src
    assert 'r["balance_label"]' in src


def _statement_rows():
    """A card statement: Rs 500 owed, then a Rs 5,000 purchase, then a
    Rs 3,000 payment. The BALANCE column states the amount due."""
    from domain.banking.normalizer import NormalizedTxn
    def _t(debit, credit, balance):
        return NormalizedTxn(transaction_date="2026-06-10", description="x",
                             reference_no=None, debit_paise=debit,
                             credit_paise=credit, balance_paise=balance)
    return [_t(0, 0, 500_00), _t(5_000_00, 0, 5_500_00), _t(0, 3_000_00, 2_500_00)]


def test_a_card_statements_balances_are_mirrored_and_its_columns_are_not():
    rows, opening, closing = ak.mirror_imported_statement(
        "Credit Card", _statement_rows(), 500_00, 2_500_00)
    assert [r.balance_paise for r in rows] == [-500_00, -5_500_00, -2_500_00]
    assert (opening, closing) == (-500_00, -2_500_00)
    # The columns are the movement and never flip.
    assert [r.debit_paise for r in rows] == [0, 5_000_00, 0]
    assert [r.credit_paise for r in rows] == [0, 0, 3_000_00]


def test_the_mirrored_statement_is_the_one_the_import_accepts():
    """`statement_check` REFUSES an import when `opening + credits - debits !=
    closing`. On a card statement in its OWN sign that is never true — 500
    owed, a 5,000 purchase, a 3,000 payment and 2,500 owed gives -1,500
    against a stated 2,500 — so a file that adds up perfectly would be
    refused."""
    from domain.banking.tie_out import statement_check
    raw = _statement_rows()
    unmirrored = statement_check(raw, opening_paise=500_00, closing_paise=2_500_00,
                                 printed=None)
    assert unmirrored["refusal"], "a card statement is refused in its own sign"

    rows, opening, closing = ak.mirror_imported_statement(
        "Credit Card", raw, 500_00, 2_500_00)
    mirrored = statement_check(rows, opening_paise=opening, closing_paise=closing,
                               printed=None)
    assert not mirrored["refusal"], mirrored
    assert mirrored["verified"] is True


def test_the_per_row_balance_check_agrees_once_it_is_mirrored():
    """`normalizer.balance_agreement` and the register's `first_divergence`
    compare each row's own balance the same way and need the same sign."""
    from domain.banking.normalizer import balance_agreement
    raw = _statement_rows()
    assert balance_agreement(raw).get("agrees") is not True
    rows, _, _ = ak.mirror_imported_statement("Credit Card", raw, None, None)
    assert balance_agreement(rows)["agrees"] is True


def test_a_bank_statement_is_handed_back_untouched():
    raw = _statement_rows()
    rows, opening, closing = ak.mirror_imported_statement("Current", raw, 500_00, 2_500_00)
    assert [r.balance_paise for r in rows] == [r.balance_paise for r in raw]
    assert (opening, closing) == (500_00, 2_500_00)


def test_the_mirror_runs_before_the_check_in_the_router():
    src = inspect.getsource(bank.upload_statement)
    mirror = src.index("account_kind.mirror_imported_statement(")
    check = src.index("check = statement_check(")
    assert mirror < check, "the mirror must happen BEFORE the check"


def test_an_unreadable_account_takes_the_ordinary_path():
    """The safe direction: a card whose type could not be read imports
    un-mirrored and its own balance check then says so loudly, where a bank
    account wrongly treated as a card would silently invert every figure on a
    statement that was right."""
    assert bank._bank_account_type(None, "F1", "acct") is None
    assert bank._bank_account_type(object(), "F1", None) is None
    assert ak.is_credit_card(None) is False
    raw = _statement_rows()
    rows, _, _ = ak.mirror_imported_statement(None, raw, None, None)
    assert [r.balance_paise for r in rows] == [r.balance_paise for r in raw]


def test_the_account_types_are_served_from_the_engine():
    body = bank.list_bank_account_types(current_user={"firm_id": "F1", "role": "Partner"})
    values = [t["value"] for t in body["data"]["account_types"]]
    assert values == list(ak.ACCOUNT_TYPES)
    card = next(t for t in body["data"]["account_types"] if t["value"] == "Credit Card")
    assert card["ledger_account_type"] == "Liability"
    assert card["balance_label"] == "Amount owed"
    assert card["owed_to_the_bank"] is True


# ══ the migration ════════════════════════════════════════════════════════════

def _mig(name: str) -> str:
    return (_MIG / name).read_text(encoding="utf-8")


def _sql(name: str) -> str:
    return "\n".join(l for l in _mig(name).splitlines() if not l.lstrip().startswith("--"))


def test_the_check_accepts_exactly_what_the_engine_knows():
    sql = _sql(_M386)
    body = sql[sql.index("ADD CONSTRAINT bank_accounts_account_type_check"):]
    accepted = set(re.findall(r"'([^']*)'", body[:body.index(";")]))
    assert accepted == set(ak.ACCOUNT_TYPES), accepted


def test_the_constraint_is_dropped_by_name_first():
    """Postgres has no ALTER ... MODIFY CHECK, so widening means dropping and
    recreating — and the drop has to be IF EXISTS for a database built either
    from 093's inline CHECK or from an earlier run of this."""
    sql = _sql(_M386)
    drop = sql.index("DROP CONSTRAINT IF EXISTS bank_accounts_account_type_check")
    add = sql.index("ADD CONSTRAINT bank_accounts_account_type_check")
    assert drop < add


def test_the_rollback_refuses_rather_than_deleting_a_clients_card():
    """Narrowing the CHECK under existing rows would leave rows the constraint
    forbids; deleting them would take a statement, its coding and its
    reconciliation with it, which is an owner decision."""
    back = _sql(_M386_BACK)
    assert "RAISE EXCEPTION" in back
    assert "'Credit Card'" in back
    assert "DELETE FROM public.bank_accounts" not in back
    restored = back[back.index("ADD CONSTRAINT bank_accounts_account_type_check"):]
    accepted = set(re.findall(r"'([^']*)'", restored[:restored.index(";")]))
    assert accepted == {"Current", "Savings", "Cash Credit", "Overdraft"}
