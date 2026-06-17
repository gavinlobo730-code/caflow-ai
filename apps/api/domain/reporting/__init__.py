"""
Cash-basis & accrual reporting engine.

Pure, DB-agnostic projection of the posted ledger into Trial Balance, P&L and
Balance Sheet. Cash basis is derived from document allocation tables
(receipt_allocations, purchase_payments.purchase_bill_id, credit_notes) — never
by amount matching — and every transformed entry balances to the paise.
"""
from .model import (
    Account, Bill, CreditNote, Invoice, JournalEntry, JournalLine,
    Payment, ProjectedLine, Receipt, ReceiptAllocation, apportion,
)
from .resolver import AccountResolver
from .projector import CashBasisProjector
from .sources import InMemoryLedgerSource, LedgerSource, SupabaseLedgerSource
from .service import ReportingService, mock_ledger_source

__all__ = [
    "Account", "JournalEntry", "JournalLine", "Invoice", "Receipt",
    "ReceiptAllocation", "CreditNote", "Bill", "Payment", "ProjectedLine",
    "apportion", "AccountResolver", "CashBasisProjector",
    "LedgerSource", "InMemoryLedgerSource", "SupabaseLedgerSource",
    "ReportingService", "mock_ledger_source",
]
