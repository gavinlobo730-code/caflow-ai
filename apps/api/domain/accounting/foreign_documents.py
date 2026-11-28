"""A document billed in a foreign currency is settled, credited or debited in that currency, or not at all (ledger POST-A-579).

WHAT WAS WRONG
    An invoice or a bill billed in a foreign currency carries two amounts that must move together: the rupees (`paid_paise`,
    `credited_paise`, ...) and the foreign amount (`paid_txn`). A foreign receipt or payment moves both, and the receipt function and
    the payment function refuse a rupee one in words (POST-A-576). Six other doors moved the rupees alone and never the foreign
    amount: a bank line matched one-to-one to the document, a party's credit applied to it, and a credit or debit note issued against
    it, on the sales side and on the purchase side. The document then read settled in rupees with its foreign amount outstanding, and
    the next foreign receipt refused it in words that blamed a rupee shortfall nobody could see.

WHAT THIS DOES, AND WHAT IT DOES NOT
    One question and the sentences a person reads when the answer is yes. A door asks `billed_in(document)` before it writes
    anything and refuses with the sentence for its own kind of door. It is a REFUSAL and not a carry: carrying both amounts through a
    note or a credit needs a foreign amount on the note (a credit note on a foreign invoice is itself in that currency) and a rule for
    the exchange difference, which is accounting that this product does not hold yet, so the honest answer today is that the
    document is settled in its own currency. The refusal says so, names the way that works (record the receipt or the payment in the
    document's currency) and says nothing was written.

    `billed_in` reads `txn_currency`, the column that holds a document's own currency. An absent or blank value is rupees, which is
    what every document written before the multi-currency columns is.
"""
from __future__ import annotations

RUPEES = "INR"


def billed_in(document: dict) -> str:
    """The currency a sales invoice or a purchase bill was billed in: its `txn_currency`, in capitals, and rupees where there is none."""
    return (str((document or {}).get("txn_currency") or "").strip() or RUPEES).upper()


def is_foreign(document: dict) -> bool:
    return billed_in(document) != RUPEES


def _noun(is_bill: bool) -> str:
    return "Bill" if is_bill else "Invoice"


def refusal_for_a_bank_line(number: str, currency: str, *, is_bill: bool) -> str:
    """A bank line in rupees matched one-to-one to a document billed in a foreign currency."""
    act, party = ("payment", "supplier") if is_bill else ("receipt", "customer")
    return (f"{_noun(is_bill)} {number} is billed in {currency}, and a bank line is in rupees. Matching the line to it here would "
            f"settle its rupee amount and leave its {currency} amount outstanding. Record the {act} in {currency}, with the rate the "
            f"money moved at, from the {party}'s page. Nothing was posted.")


def refusal_for_a_party_credit(number: str, currency: str, *, is_bill: bool) -> str:
    """A party's credit, which is held in rupees, applied to a document billed in a foreign currency."""
    act = "payment" if is_bill else "receipt"
    return (f"{_noun(is_bill)} {number} is billed in {currency}, and a party's credit is held in rupees. Applying it here would "
            f"settle the rupee amount and leave the {currency} amount outstanding. Record a {act} in {currency} instead. "
            "Nothing was applied.")


def refusal_for_a_note(number: str, currency: str, *, is_bill: bool, note: str) -> str:
    """A credit or debit note (`note` says which) issued against a document billed in a foreign currency."""
    return (f"{_noun(is_bill)} {number} is billed in {currency}. A {note} here changes its rupee amount only and would leave its "
            f"{currency} amount as it was, so the {_noun(is_bill).lower()} would disagree with itself. A {note} against a document "
            "billed in a foreign currency is not issued here. Nothing was issued.")
