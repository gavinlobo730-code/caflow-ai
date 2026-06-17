"""
ReportingService — single backend entry point for Trial Balance, P&L and
Balance Sheet on BOTH accrual and cash bases.

Accrual and cash are computed by identical builder code over the same scoped
ledger; only the line stream differs (cash runs the CashBasisProjector). This
removes the prior split-brain where accrual read live data and cash read a mock.

Compliance: IT Act §145 / §44AA (method of accounting), Companies Act §128
(accrual for statutory accounts). Cash basis is management reporting only and
never affects GST returns (CGST Act) or any filing calculation.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from . import builders
from .model import ProjectedLine
from .projector import CashBasisProjector
from .resolver import AccountResolver
from .sources import InMemoryLedgerSource, LedgerSource


def _fy_start(today: date | None = None) -> str:
    today = today or date.today()
    return date(today.year if today.month >= 4 else today.year - 1, 4, 1).isoformat()


class ReportingService:
    def __init__(self, source: LedgerSource):
        self.source = source

    def _lines(self, snapshot, basis: str) -> list[ProjectedLine]:
        if basis == "cash":
            resolver = AccountResolver(snapshot.accounts)
            return CashBasisProjector(snapshot, resolver).project()
        # Accrual: the posted ledger as-is.
        return [
            ProjectedLine(ln.account_id, ln.debit_paise, ln.credit_paise)
            for entry in snapshot.entries_in_range
            for ln in entry.lines
        ]

    def trial_balance(self, firm_id: str, client_id: Optional[str],
                      as_of_date: Optional[str], basis: str = "accrual") -> dict:
        as_of = as_of_date or date.today().isoformat()
        snap = self.source.snapshot(firm_id, client_id, None, as_of)
        return builders.trial_balance(self._lines(snap, basis), snap.accounts, as_of, basis)

    def profit_loss(self, firm_id: str, client_id: Optional[str],
                    start_date: Optional[str], end_date: Optional[str],
                    basis: str = "accrual") -> dict:
        start = start_date or _fy_start()
        end = end_date or date.today().isoformat()
        snap = self.source.snapshot(firm_id, client_id, start, end)
        return builders.profit_loss(self._lines(snap, basis), snap.accounts, start, end, basis)

    def balance_sheet(self, firm_id: str, client_id: Optional[str],
                      as_of_date: Optional[str], basis: str = "accrual") -> dict:
        as_of = as_of_date or date.today().isoformat()
        snap = self.source.snapshot(firm_id, client_id, None, as_of)
        return builders.balance_sheet(self._lines(snap, basis), snap.accounts, as_of, basis)


def mock_ledger_source() -> InMemoryLedgerSource:
    """
    Build a LedgerSource from the legacy in-memory seed (accounting_service)
    for dev/demo and no-DB environments. The seed has no sales/purchase
    documents, so cash basis equals accrual there (honest: with no allocation
    data, nothing can be reclassified) while still exercising the real engine.
    """
    from domain.accounting_service import MOCK_ACCOUNTS, MOCK_JOURNAL_ENTRIES
    from .model import Account, JournalEntry, JournalLine

    accounts = [
        Account(id=a["id"], code=a.get("account_code", ""), name=a.get("account_name", ""),
                type=a.get("account_type", ""), subtype=a.get("account_subtype"))
        for a in MOCK_ACCOUNTS
    ]
    entries = []
    for e in MOCK_JOURNAL_ENTRIES:
        if e.get("status") != "posted":
            continue
        lines = tuple(
            JournalLine(ln["account_id"], int(ln.get("debit_paise", 0)), int(ln.get("credit_paise", 0)))
            for ln in e["lines"]
        )
        entries.append(JournalEntry(
            id=e["id"], entry_date=e["entry_date"], client_id=e.get("client_id", ""),
            firm_id=e.get("firm_id", ""), entry_type=e.get("entry_type", ""), lines=lines,
        ))
    return InMemoryLedgerSource(accounts=accounts, entries=entries)
