"""
Reporting domain model — shared dataclasses for accrual & cash-basis reporting.

All monetary values are integer paise (BIGINT). Never float — IT Act §145 /
CGST Act require exact rupee arithmetic; we apportion with the largest-remainder
method so every projected entry balances to the paise.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple, Optional


# Account types that represent income / expense in the production chart_of_accounts.
# Production seeds use "Revenue"; the legacy mock used "Income" — accept both.
INCOME_TYPES = frozenset({"Revenue", "Income"})
EXPENSE_TYPES = frozenset({"Expense"})


@dataclass(frozen=True)
class Account:
    id: str
    code: str
    name: str
    type: str                      # Asset | Liability | Equity | Revenue/Income | Expense
    subtype: Optional[str] = None
    system_key: Optional[str] = None   # ar | ap | bank | gst_output | gst_input | tds_* | advance_*

    @property
    def is_income(self) -> bool:
        return self.type in INCOME_TYPES

    @property
    def is_expense(self) -> bool:
        return self.type in EXPENSE_TYPES


class JournalLine(NamedTuple):
    account_id: str
    debit_paise: int
    credit_paise: int


@dataclass(frozen=True)
class JournalEntry:
    id: str
    entry_date: str                # ISO YYYY-MM-DD
    client_id: str
    firm_id: str
    entry_type: str
    lines: tuple[JournalLine, ...]
    reversal_of: Optional[str] = None
    # Display + ordering metadata (used by the ledger; ignored by aggregation
    # reports). created_at is the stable tiebreaker for same-day entries.
    reference_no: Optional[str] = None
    narration: Optional[str] = None
    created_at: Optional[str] = None


# ── Sales / purchase cycle documents (only the fields the projector needs) ──

@dataclass(frozen=True)
class Invoice:
    id: str
    total_paise: int
    journal_entry_id: Optional[str]


@dataclass(frozen=True)
class ReceiptAllocation:
    receipt_id: str
    sales_invoice_id: str
    allocated_paise: int


@dataclass(frozen=True)
class Receipt:
    id: str
    journal_entry_id: Optional[str]
    amount_paise: int = 0
    tds_paise: int = 0


@dataclass(frozen=True)
class CreditNote:
    id: str
    sales_invoice_id: Optional[str]
    journal_entry_id: Optional[str]


@dataclass(frozen=True)
class Bill:
    id: str
    total_paise: int
    journal_entry_id: Optional[str]


@dataclass(frozen=True)
class Payment:
    id: str
    purchase_bill_id: Optional[str]
    journal_entry_id: Optional[str]
    amount_paise: int = 0


@dataclass
class LedgerSnapshot:
    """
    A tenant-scoped, point-in-time view of the posted ledger plus the
    sales/purchase documents needed to project cash basis.

    `entries_in_range` are the posted entries inside the report window.
    `entries_by_id` is the full scoped set of posted entries (supersets the
    in-range list) so linked invoices/bills/originals dated outside the window
    can still be resolved for revenue/expense distribution and reversals.
    """
    accounts: dict[str, Account]
    entries_in_range: list[JournalEntry]
    entries_by_id: dict[str, JournalEntry]
    invoices: dict[str, Invoice] = field(default_factory=dict)
    allocations_by_receipt: dict[str, list[ReceiptAllocation]] = field(default_factory=dict)
    credit_notes: list[CreditNote] = field(default_factory=list)
    bills: dict[str, Bill] = field(default_factory=dict)
    # Reverse maps: journal_entry_id -> owning document
    receipt_by_journal: dict[str, Receipt] = field(default_factory=dict)
    payment_by_journal: dict[str, Payment] = field(default_factory=dict)
    invoice_by_journal: dict[str, Invoice] = field(default_factory=dict)
    bill_by_journal: dict[str, Bill] = field(default_factory=dict)
    creditnote_by_journal: dict[str, CreditNote] = field(default_factory=dict)


class ProjectedLine(NamedTuple):
    """A single posting line in a (possibly transformed) report stream."""
    account_id: str
    debit_paise: int
    credit_paise: int


def apportion(total: int, weights: list[int]) -> list[int]:
    """
    Split `total` paise across `weights` using the largest-remainder method.

    Guarantees sum(result) == total exactly when total >= 0 and sum(weights) > 0,
    so a transformed journal entry balances to the paise (no rounding drift).
    Pure integer arithmetic — never float.
    """
    n = len(weights)
    if n == 0:
        return []
    w_sum = sum(weights)
    if w_sum <= 0 or total <= 0:
        return [0] * n
    base = [(total * w) // w_sum for w in weights]
    remainders = [(total * w) % w_sum for w in weights]
    leftover = total - sum(base)            # in 0 .. n-1 for non-negative inputs
    # Hand out the leftover paise to the largest fractional remainders first;
    # ties resolve by lower index for determinism.
    order = sorted(range(n), key=lambda i: (-remainders[i], i))
    for k in range(leftover):
        base[order[k]] += 1
    return base
