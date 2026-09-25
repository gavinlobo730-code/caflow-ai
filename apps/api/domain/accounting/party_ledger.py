"""Who a control account's balance is owed BY, or owed TO (ACC-13's other half).

WHAT WAS MISSING

    Drilling into Trade Receivables showed one pooled control account. The
    per-customer view existed only on the separate Customer Statement screen,
    which is built from DOCUMENTS (`customer_statement_service` reads
    client_sales_invoices, receipts, credit_notes and sales_debit_notes and
    reconstructs the balance). So the two never met: a CA looking at the
    ledger could not see which parties made up the figure, and when the
    control account and the statements disagreed there was nothing that said
    WHICH entries were the difference.

    That last part is the point of this module rather than a side effect.
    ACC-22's drill-through exists, in its own words, because "when the GL and
    a sub-ledger disagree, the link is how you find WHICH document drifted".
    This applies the same idea to the aggregate.

NO COLUMN ON `journal_lines`, AND THAT IS THE DECISION

    The party is ALREADY on the document. `journal_entries.source_type` /
    `source_id` have named that document on all twenty-six posting paths since
    ACC-22, and all nine document tables carry `customer_id` or `vendor_id`
    NOT NULL — so the party derives, and a line can never be half-attributed.

    Migration 418 DID take a column for a cost centre one commit ago, and the
    two are not inconsistent: a cost centre is a fact no document holds and
    somebody must type, a party is a fact every document already holds. The
    `line_order` lesson decides it — "a field every caller must set is a field
    some caller will not" — so a derivable fact is derived.

THE UNATTRIBUTED SET IS THE ANSWER, NOT A GAP IN IT

    Five source kinds name no party, each for its own reason, and together
    they are exactly the difference between this control account and the sum
    of the party sub-ledgers:

      manual              a CA typed a journal against the control account.
                          There is no party anywhere in the entry. This is the
                          real one, and the one a reconciliation is looking for.
      Opening             `opening_balance_service._plan_opening` computes
                          three AGGREGATE targets, so the AR leg is the sum of
                          every customer's opening balance and names none of
                          them. ACC-14's opening DOCUMENTS post no journal at
                          all, so the party genuinely is not in the entry.
      TrialBalance        an imported trial balance is a control-account total
                          by construction.
      year_end_adjustment not a party document.
      bank_transaction    `bank_posting_service.post` may code a statement line
                          straight to a control account with no settlement.

    So `Σ(party rows) + Σ(unattributed rows)` equals the control account's own
    closing balance BY CONSTRUCTION, and a test asserts it against
    `builders.ledger`. They are therefore LISTED, one row per source kind so
    "manual" and "Opening" are told apart, and never folded into an "Others"
    party — which would be a party that does not exist, on a screen whose
    whole value is that every row names somebody to ask.

A BILL OF ENTRY IS NOT A PARTY ROW

    `bills_of_entry` carries a supplier, and the journal it posts touches NO
    accounts payable: PUR-18's rule is that IGST on imported goods is paid to
    CUSTOMS under Customs Tariff Act s.3(7), not to the supplier. So it can
    only reach a control account by some other leg, and attributing it to the
    vendor would say the vendor is owed money they are not. It is named here
    rather than mapped, so the next reader does not "fix" the omission.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Optional

CUSTOMER = "customer"
VENDOR = "vendor"

#: source_type -> (table holding the document, its party column, which kind).
#: Every one of these columns is NOT NULL (verified against the migrations,
#: 25-09-2026), so a mapped source either resolves or its document is missing.
PARTY_SOURCES: dict[str, tuple[str, str, str]] = {
    "sales_invoice":        ("client_sales_invoices", "customer_id", CUSTOMER),
    "credit_note":          ("credit_notes",          "customer_id", CUSTOMER),
    "sales_debit_note":     ("sales_debit_notes",     "customer_id", CUSTOMER),
    "receipt":              ("receipts",              "customer_id", CUSTOMER),
    "purchase_bill":        ("purchase_bills",        "vendor_id",   VENDOR),
    "debit_note":           ("debit_notes",           "vendor_id",   VENDOR),
    "purchase_credit_note": ("purchase_credit_notes", "vendor_id",   VENDOR),
    "purchase_payment":     ("purchase_payments",     "vendor_id",   VENDOR),
}

#: A source that names no party, and WHY — rendered on the row, because the
#: five reasons are not interchangeable and what the CA does next differs.
NO_PARTY_REASON: dict[str, str] = {
    "manual": (
        "A manual journal posted against this account. Nothing in the entry "
        "names a party, so this is the figure a control-account reconciliation "
        "is usually looking for."
    ),
    "Opening": (
        "The opening balance, which is posted as one aggregate figure for the "
        "whole account rather than per party."
    ),
    "TrialBalance": (
        "An imported trial balance, which carries control-account totals and "
        "no party detail."
    ),
    "year_end_adjustment": (
        "A year-end adjustment, which is not raised against a party."
    ),
    "bank_transaction": (
        "A bank statement line coded straight to this account, without being "
        "settled against a document."
    ),
    "bank_overpayment": (
        "A bank receipt or payment in excess of what any document was open "
        "for, held on this account until it is allocated."
    ),
}

#: Recorded so the absence reads as a decision. See the module docstring.
BILL_OF_ENTRY_IS_NOT_A_PARTY = (
    "A bill of entry records tax assessed and collected by customs, not a sum "
    "owed to the supplier (PUR-18), so it is never attributed to one."
)

#: What a row means when the source is not in either map.
UNKNOWN_SOURCE_REASON = (
    "Posted by a path this report does not know how to attribute to a party."
)

#: Shown wherever the breakdown is. Not a caveat — the invariant IS the point.
THE_PARTS_SUM_TO_THE_ACCOUNT = (
    "The party rows and the unattributed rows together equal this account's "
    "own balance. What cannot be attributed is shown rather than dropped, "
    "because it is the difference between this control account and the "
    "per-party statements."
)


@dataclass(frozen=True)
class PartyRow:
    """One party, or one kind of unattributed entry. Never both."""
    party_id: Optional[str]
    party_name: str
    party_kind: Optional[str]
    unattributed_source: Optional[str]
    unattributed_reason: Optional[str]
    debit_paise: int
    credit_paise: int

    @property
    def balance_paise(self) -> int:
        return self.debit_paise - self.credit_paise

    @property
    def is_attributed(self) -> bool:
        return self.party_id is not None


@dataclass(frozen=True)
class Breakdown:
    rows: list[PartyRow]
    attributed_paise: int
    unattributed_paise: int
    notes: list[str] = field(default_factory=list)

    @property
    def total_paise(self) -> int:
        """What the whole breakdown comes to — and what the account's own
        closing balance must equal. A test asserts that against
        `builders.ledger` rather than trusting this to be self-consistent."""
        return self.attributed_paise + self.unattributed_paise


def _as_int(v) -> int:
    """PostgREST hands a bigint back as a string. Never float — a rupee figure
    that has been through a float is a rupee figure nobody can reconcile."""
    if v is None:
        return 0
    if isinstance(v, bool):
        return int(v)
    return int(Decimal(str(v)))


def reason_for(source_type: Optional[str]) -> str:
    """Why a line could not be attributed. Every branch says something
    different, because a screen that renders one sentence for five causes
    tells the CA nothing about which to go and look at."""
    if not source_type:
        return "This entry records no source document."
    if source_type == "bill_of_entry":
        return BILL_OF_ENTRY_IS_NOT_A_PARTY
    return NO_PARTY_REASON.get(source_type, UNKNOWN_SOURCE_REASON)


def breakdown(lines: Iterable[dict]) -> Breakdown:
    """Group already-fetched, already-resolved lines by party.

    Each line carries `debit_paise`, `credit_paise`, its `source_type`, and —
    where the service could resolve one — `party_id`, `party_name` and
    `party_kind`. Resolution happens in the service because it is a database
    read; which sources CAN resolve is `PARTY_SOURCES`, above.

    This is the mock-mode twin of `public.party_ledger_as_at`. Both are run
    over every scenario by tests/test_party_ledger_parity_pg.py.

    A line whose party the service could NOT resolve — a document row that has
    since been deleted, say — falls to the unattributed side under its own
    source rather than being dropped, because the invariant is that the parts
    sum to the account and a dropped line breaks it silently.
    """
    parties: dict[str, dict] = {}
    unattributed: dict[str, dict] = {}

    for ln in lines:
        debit, credit = _as_int(ln.get("debit_paise")), _as_int(ln.get("credit_paise"))
        pid = ln.get("party_id")
        if pid:
            slot = parties.setdefault(str(pid), {
                "name": ln.get("party_name") or "(unnamed)",
                "kind": ln.get("party_kind"),
                "debit": 0, "credit": 0,
            })
        else:
            key = ln.get("source_type") or ""
            slot = unattributed.setdefault(key, {"debit": 0, "credit": 0})
        slot["debit"] += debit
        slot["credit"] += credit

    rows = [
        PartyRow(party_id=pid, party_name=v["name"], party_kind=v["kind"],
                 unattributed_source=None, unattributed_reason=None,
                 debit_paise=v["debit"], credit_paise=v["credit"])
        for pid, v in parties.items()
    ]
    # Largest balance first, then by name, so the order is TOTAL and the same
    # account renders the same way on every read — `line_order`'s property.
    rows.sort(key=lambda r: (-abs(r.balance_paise), r.party_name, r.party_id or ""))

    unrows = [
        PartyRow(party_id=None, party_name="", party_kind=None,
                 unattributed_source=src or None, unattributed_reason=reason_for(src),
                 debit_paise=v["debit"], credit_paise=v["credit"])
        for src, v in unattributed.items()
    ]
    unrows.sort(key=lambda r: (-abs(r.balance_paise), r.unattributed_source or ""))

    notes = [THE_PARTS_SUM_TO_THE_ACCOUNT]
    if any(r.unattributed_source == "bill_of_entry" for r in unrows):
        notes.append(BILL_OF_ENTRY_IS_NOT_A_PARTY)

    return Breakdown(
        rows=rows + unrows,
        attributed_paise=sum(r.balance_paise for r in rows),
        unattributed_paise=sum(r.balance_paise for r in unrows),
        notes=notes,
    )
