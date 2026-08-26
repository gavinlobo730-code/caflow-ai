"""
Bank posting map (Banking B.3) — category → journal mapping (pure, testable).

The DOUBLE-ENTRY itself is purely direction-driven:
  • money INTO bank  (credit) → Dr Bank        / Cr counter
  • money OUT of bank (debit) → Dr counter      / Cr Bank
  • Transfer                  → Dr/Cr between bank and the other bank/cash account
The CATEGORY only decides how the counter account is resolved (a deterministic
control account vs an explicitly-selected GL account) and whether a settlement
runs — that policy lives here as data; account resolution + settlement happen in
the service. Integer paise only; no GL account is ever guessed.
"""
from __future__ import annotations

from typing import Optional

# Categories whose counter is a deterministic CONTROL account (auto-resolved by
# system_account_key, name fallback). (system_account_key, name_pattern)
AUTO_COUNTER: dict[str, tuple[str, str]] = {
    "Customer Payment": ("ar", "%Trade Receivable%"),
    "Vendor Payment": ("ap", "%Trade Payable%"),
    "GST Payment": ("gst_output", "%GST Output%"),
}

# Categories that REQUIRE an explicitly-selected counter GL account (never guessed).
EXPLICIT_COUNTER = frozenset({
    "Expense", "Salary", "Loan", "Capital", "Interest", "Sales Receipt", "Other",
})

# Categories that settle a business document when matched.
SETTLES_SALES_INVOICE = frozenset({"Customer Payment", "Sales Receipt"})
SETTLES_PURCHASE_BILL = frozenset({"Vendor Payment"})

TRANSFER = "Transfer"


def entry_type_for(category: Optional[str], is_credit: bool) -> str:
    if category == TRANSFER:
        return "Contra"
    return "Receipt" if is_credit else "Payment"


def build_lines(amount_paise: int, is_credit: bool,
                bank_account_id: str, counter_account_id: str) -> list[dict]:
    """Balanced two-line entry for a non-transfer bank posting (direction-driven)."""
    if amount_paise <= 0:
        raise ValueError("Posting amount must be positive.")
    if not bank_account_id or not counter_account_id:
        raise ValueError("Both bank and counter accounts are required.")
    if is_credit:  # money into the bank
        return [
            {"account_id": bank_account_id, "debit_paise": amount_paise, "credit_paise": 0},
            {"account_id": counter_account_id, "debit_paise": 0, "credit_paise": amount_paise},
        ]
    return [  # money out of the bank
        {"account_id": counter_account_id, "debit_paise": amount_paise, "credit_paise": 0},
        {"account_id": bank_account_id, "debit_paise": 0, "credit_paise": amount_paise},
    ]


def build_transfer_lines(amount_paise: int, is_credit: bool,
                         bank_account_id: str, to_bank_account_id: str) -> list[dict]:
    """Balanced movement between two bank/cash accounts (Transfer)."""
    if amount_paise <= 0:
        raise ValueError("Transfer amount must be positive.")
    if not bank_account_id or not to_bank_account_id:
        raise ValueError("Transfer requires both bank accounts.")
    if bank_account_id == to_bank_account_id:
        raise ValueError("Transfer accounts must differ.")
    if is_credit:  # money arrived in this bank from the other account
        return [
            {"account_id": bank_account_id, "debit_paise": amount_paise, "credit_paise": 0},
            {"account_id": to_bank_account_id, "debit_paise": 0, "credit_paise": amount_paise},
        ]
    return [  # money left this bank for the other account
        {"account_id": to_bank_account_id, "debit_paise": amount_paise, "credit_paise": 0},
        {"account_id": bank_account_id, "debit_paise": 0, "credit_paise": amount_paise},
    ]


def counter_is_auto(category: Optional[str]) -> bool:
    return category in AUTO_COUNTER


def settles_document(category: Optional[str], matched_entity_type: Optional[str],
                     matched_entity_id: Optional[str]) -> bool:
    """True when posting this line will also settle an invoice or bill.

    Pure so that the posting engine and the review queue can ask the SAME
    question. A settling line is special twice over: its counter is the control
    account whatever the category says, and it cannot carry a GST rate.
    """
    if not matched_entity_id:
        return False
    return ((category in SETTLES_SALES_INVOICE and matched_entity_type == "sales_invoice")
            or (category in SETTLES_PURCHASE_BILL and matched_entity_type == "purchase_bill"))


def gst_split_allowed(category: Optional[str], *, settles_document: bool,
                      is_split: bool = False) -> bool:
    """Can this line carry a GST rate?

    DIRECTION IS NOT A CONDITION. Money out is an inward supply and its tax is
    input credit (CGST Act s.16); money in is an outward supply and its tax is
    output tax (s.9). Both are real, and the posting engine picks the accounts
    from the direction — see charge_gst.build_inclusive_lines.

    What IS refused:
      * a line that settles a document — the invoice or bill already carries
        its own GST, so taxing the bank line counts the same tax twice;
      * a control-account category (Customer Payment → Trade Receivables, and
        the rest of AUTO_COUNTER) — tax has no business on a control account;
      * a line already allocated across several ledgers, which would need a
        rate per leg.
      * a line with no ledger chosen yet: there is nowhere to book the ex-tax
        amount, and `category` is None until one is.

    One function so the guard that REFUSES and the flag the queue shows can
    never disagree — a screen offering a control the server rejects is the
    failure this exists to prevent.
    """
    if settles_document or is_split:
        return False
    return category in EXPLICIT_COUNTER
