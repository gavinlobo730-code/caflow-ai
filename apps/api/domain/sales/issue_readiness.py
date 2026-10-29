"""What stands between a draft sales invoice and its issue, as a list a screen can show BEFORE the click (POST-A-125).

Issuing a draft posts a dated journal and turns the draft into a tax invoice (CGST Act §31, Rule 46), so the route refuses in a
fixed order for eight reasons: the status, the firm's locked year, a filed return covering the date, a number Rule 46(b) does not
allow, a placeholder number, a place of supply Rule 46(n) needs, a draft that does not add up to its own lines, and a chart of
accounts that lacks an account the posting needs. Each was an English sentence, and the editor showed whichever the server sent
after the CA had already clicked, with no way for the screen to tell "go and fix the state" from "ask a Partner to reopen the year".

This module is the vocabulary and the pure parts:

    * `Blocker` carries a stable `code`, the sentence the server already said (the same words, one speaker), and an `action`
      the screen can offer: `fix_in_editor` (with the field), `seed_chart_of_accounts`, or nothing where only a Partner or the
      calendar can help. The action names what the SCREEN does and never an address, so the server does not guess a URL.
    * `required_accounts` is which ledger accounts the sales journal looks up for an invoice. It is the one definition the
      pre-flight asks, and `tests/test_the_issue_preflight_asks_for_the_accounts_the_posting_looks_up.py` records the posting's
      own lookups and holds the two identical, so the pre-flight cannot say "ready" for an invoice the posting then refuses.
    * `place_of_supply_problem` and the two number problems are the sentences the issue route used to carry inline.

It touches no database and raises nothing: `services/issue_readiness_service` asks the checks that need one and builds the list.
It is a READING, not a gate: the issue route still refuses, from the same list, and a pre-flight that says "ready" promises
nothing about a lock that changes between the two requests.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from domain.gst.validator import VALID_STATE_CODES

# Codes: stable words a screen may branch on. Adding one is a change to this tuple, the service and the screen together.
NOT_A_DRAFT = "NOT_A_DRAFT"
PERIOD_LOCKED_YEAR = "PERIOD_LOCKED_YEAR"
PERIOD_LOCKED_RETURN = "PERIOD_LOCKED_RETURN"
INVOICE_NO_NOT_ALLOWED = "INVOICE_NO_NOT_ALLOWED"
INVOICE_NO_PLACEHOLDER = "INVOICE_NO_PLACEHOLDER"
PLACE_OF_SUPPLY_MISSING = "PLACE_OF_SUPPLY_MISSING"
PLACE_OF_SUPPLY_INVALID = "PLACE_OF_SUPPLY_INVALID"
DRAFT_DOES_NOT_ADD_UP = "DRAFT_DOES_NOT_ADD_UP"
COA_MISSING = "COA_MISSING"

CODES: tuple[str, ...] = (
    NOT_A_DRAFT, PERIOD_LOCKED_YEAR, PERIOD_LOCKED_RETURN, INVOICE_NO_NOT_ALLOWED, INVOICE_NO_PLACEHOLDER,
    PLACE_OF_SUPPLY_MISSING, PLACE_OF_SUPPLY_INVALID, DRAFT_DOES_NOT_ADD_UP, COA_MISSING,
)

# What the SCREEN can do about a blocker. `fix_in_editor` carries the field; the screen maps the field to its own control.
ACTION_FIX_IN_EDITOR = "fix_in_editor"
ACTION_SEED_CHART_OF_ACCOUNTS = "seed_chart_of_accounts"
ACTION_KINDS: tuple[str, ...] = (ACTION_FIX_IN_EDITOR, ACTION_SEED_CHART_OF_ACCOUNTS)
EDITOR_FIELDS: tuple[str, ...] = ("invoice_no", "supply_state", "lines")


@dataclass(frozen=True)
class Blocker:
    code: str
    message: str
    action: Optional[dict] = None

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "action": self.action}


def fix_in_editor(field: str, label: str) -> dict:
    assert field in EDITOR_FIELDS, field
    return {"kind": ACTION_FIX_IN_EDITOR, "field": field, "label": label}


def seed_chart_of_accounts() -> dict:
    return {"kind": ACTION_SEED_CHART_OF_ACCOUNTS, "label": "Set up the chart of accounts"}


# Which action each code offers. A locked year or a filed return offers none: what unlocks them is a Partner reopening the year or
# a later period's amendment, and the sentence the server already says names it.
ACTION_FOR: dict[str, Optional[dict]] = {
    NOT_A_DRAFT: None,
    PERIOD_LOCKED_YEAR: None,
    PERIOD_LOCKED_RETURN: None,
    INVOICE_NO_NOT_ALLOWED: fix_in_editor("invoice_no", "Change the invoice number"),
    INVOICE_NO_PLACEHOLDER: fix_in_editor("invoice_no", "Enter the invoice number"),
    PLACE_OF_SUPPLY_MISSING: fix_in_editor("supply_state", "Set the supply state"),
    PLACE_OF_SUPPLY_INVALID: fix_in_editor("supply_state", "Set the supply state"),
    DRAFT_DOES_NOT_ADD_UP: fix_in_editor("lines", "Re-save the draft's lines"),
    COA_MISSING: seed_chart_of_accounts(),
}


def blocker(code: str, message: str) -> Blocker:
    """A blocker with the action its code offers."""
    assert code in CODES, code
    return Blocker(code=code, message=message, action=ACTION_FOR[code])


def place_of_supply_problem(supply_state_code: Optional[str]) -> Optional[tuple[str, str]]:
    """(code, sentence) for a place of supply Rule 46(n) cannot accept on a tax invoice, or None.

    The place of supply is checked at ISSUE and not at draft: a draft may be incomplete, and issuing is the moment the document
    becomes a tax invoice. GSTR-1 is rejected without a valid two-digit state code (`domain/gst/validator`), so a wrong one
    found on the 10th of the following month is a §34 credit note and not an edit (SALES-29)."""
    pos = (supply_state_code or "").strip()
    if pos in VALID_STATE_CODES:
        return None
    code = PLACE_OF_SUPPLY_MISSING if not pos else PLACE_OF_SUPPLY_INVALID
    return code, (
        f"Cannot issue — place of supply is {'missing' if not pos else f'invalid ({pos})'}. CGST Rule 46(n) "
        f"requires it on a tax invoice, and GSTR-1 is rejected without a "
        f"valid 2-digit state code. Set the Supply State on the invoice, "
        f"or record the customer's state or GSTIN and re-open the draft."
    )


@dataclass(frozen=True)
class RequiredAccount:
    """One ledger account the sales journal looks up: the name pattern, the system key it is found by first, and a label a person
    reads ("Trade Receivables") when it is missing."""
    label: str
    pattern: str
    system_key: str


def required_accounts(invoice: dict) -> tuple[RequiredAccount, ...]:
    """The accounts `phase2_journal_service.journal_for_sales_invoice` resolves for this invoice, in its order.

    Receivables and sales always; a GST head only when the invoice carries that head's tax (CGST Act §8: an intra-state supply
    posts CGST and SGST, an inter-state one IGST); the compensation cess ledger only when the invoice carries cess (its own
    liability ledger, GST (Compensation to States) Act s.11(2) proviso); Round Off only when the total was rounded."""
    out = [
        RequiredAccount("Trade Receivables", "%Trade Receivable%", "ar"),
        RequiredAccount("Sales", "%Sales%", "revenue"),
    ]
    if int(invoice.get("cgst_paise") or 0) > 0:
        out.append(RequiredAccount("GST Output (CGST)", "%GST Output%", "gst_cgst"))
    if int(invoice.get("sgst_paise") or 0) > 0:
        out.append(RequiredAccount("GST Output (SGST)", "%GST Output%", "gst_sgst"))
    if int(invoice.get("igst_paise") or 0) > 0:
        out.append(RequiredAccount("GST Output (IGST)", "%GST Output%", "gst_igst"))
    if int(invoice.get("cess_paise") or 0) > 0:
        out.append(RequiredAccount("Compensation Cess Payable", "%Compensation Cess Payable%", "gst_cess_output"))
    if int(invoice.get("round_off_paise") or 0) != 0:
        out.append(RequiredAccount("Round Off", "%Round Off%", "round_off"))
    return tuple(out)


def missing_accounts_sentence(labels: list[str]) -> str:
    """The sentence for a chart that lacks accounts the posting needs. Written for the person who has to fix it, so it names the
    accounts and the way out."""
    names = ", ".join(labels)
    return (
        f"Cannot issue — the chart of accounts has no account for: {names}. The invoice remains a draft; set up the chart of "
        "accounts and issue it again."
    )
