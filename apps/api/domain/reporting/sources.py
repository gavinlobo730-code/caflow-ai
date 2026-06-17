"""
Ledger data sources.

A LedgerSource yields a tenant-scoped LedgerSnapshot. The projection/report
code is pure and DB-agnostic, so:
  - SupabaseLedgerSource queries the real production tables (prod path), and
  - InMemoryLedgerSource is fed fixtures (unit tests / no-DB environments).

SECURITY: reports run under the service-role key, which bypasses RLS. Every
Supabase query here MUST filter firm_id AND client_id explicitly.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

from .model import (
    Account, Bill, CreditNote, Invoice, JournalEntry, JournalLine,
    LedgerSnapshot, Payment, Receipt, ReceiptAllocation,
)

_logger = logging.getLogger("caflow.reporting.source")


def _in_range(d: str, start: Optional[str], end: Optional[str]) -> bool:
    if start and d < start:
        return False
    if end and d > end:
        return False
    return True


class LedgerSource(ABC):
    @abstractmethod
    def snapshot(self, firm_id: str, client_id: Optional[str],
                 start_date: Optional[str], end_date: Optional[str]) -> LedgerSnapshot:
        ...


class InMemoryLedgerSource(LedgerSource):
    """Builds a snapshot from in-memory fixtures (tests / mock)."""

    def __init__(self, *, accounts, entries, invoices=None, receipts=None,
                 allocations=None, credit_notes=None, bills=None, payments=None):
        self._accounts = {a.id: a for a in accounts}
        self._entries = list(entries)
        self._invoices = list(invoices or [])
        self._receipts = list(receipts or [])
        self._allocations = list(allocations or [])
        self._credit_notes = list(credit_notes or [])
        self._bills = list(bills or [])
        self._payments = list(payments or [])

    def snapshot(self, firm_id, client_id, start_date, end_date) -> LedgerSnapshot:
        def scoped(e: JournalEntry) -> bool:
            return e.firm_id == firm_id and (client_id is None or e.client_id == client_id)

        scoped_entries = [e for e in self._entries if scoped(e)]
        entries_by_id = {e.id: e for e in scoped_entries}
        in_range = [e for e in scoped_entries if _in_range(e.entry_date, start_date, end_date)]

        allocations_by_receipt: dict[str, list[ReceiptAllocation]] = {}
        for a in self._allocations:
            allocations_by_receipt.setdefault(a.receipt_id, []).append(a)

        invoices = {i.id: i for i in self._invoices}
        bills = {b.id: b for b in self._bills}

        return LedgerSnapshot(
            accounts=dict(self._accounts),
            entries_in_range=in_range,
            entries_by_id=entries_by_id,
            invoices=invoices,
            allocations_by_receipt=allocations_by_receipt,
            credit_notes=list(self._credit_notes),
            bills=bills,
            receipt_by_journal={r.journal_entry_id: r for r in self._receipts if r.journal_entry_id},
            payment_by_journal={p.journal_entry_id: p for p in self._payments if p.journal_entry_id},
            invoice_by_journal={i.journal_entry_id: i for i in self._invoices if i.journal_entry_id},
            bill_by_journal={b.journal_entry_id: b for b in self._bills if b.journal_entry_id},
            creditnote_by_journal={c.journal_entry_id: c for c in self._credit_notes if c.journal_entry_id},
        )


class SupabaseLedgerSource(LedgerSource):
    """Queries the production tables. Always firm_id + client_id scoped."""

    def __init__(self, db):
        self.db = db

    def snapshot(self, firm_id, client_id, start_date, end_date) -> LedgerSnapshot:
        accounts = self._accounts(firm_id, client_id)
        entries_by_id = self._entries(firm_id, client_id)
        in_range = [e for e in entries_by_id.values() if _in_range(e.entry_date, start_date, end_date)]
        in_range.sort(key=lambda e: e.entry_date)

        invoices = self._invoices(firm_id, client_id)
        receipts = self._receipts(firm_id, client_id)
        allocations_by_receipt = self._allocations(list(receipts.keys()))
        credit_notes = self._credit_notes(firm_id, client_id)
        bills = self._bills(firm_id, client_id)
        payments = self._payments(firm_id, client_id)

        return LedgerSnapshot(
            accounts=accounts,
            entries_in_range=in_range,
            entries_by_id=entries_by_id,
            invoices=invoices,
            allocations_by_receipt=allocations_by_receipt,
            credit_notes=credit_notes,
            bills=bills,
            receipt_by_journal={r.journal_entry_id: r for r in receipts.values() if r.journal_entry_id},
            payment_by_journal={p.journal_entry_id: p for p in payments if p.journal_entry_id},
            invoice_by_journal={i.journal_entry_id: i for i in invoices.values() if i.journal_entry_id},
            bill_by_journal={b.journal_entry_id: b for b in bills.values() if b.journal_entry_id},
            creditnote_by_journal={c.journal_entry_id: c for c in credit_notes if c.journal_entry_id},
        )

    # ── scoped fetches ────────────────────────────────────────────────────────

    def _accounts(self, firm_id, client_id) -> dict[str, Account]:
        q = self.db.table("chart_of_accounts").select(
            "id, account_code, account_name, account_type, account_subtype, system_account_key"
        ).eq("firm_id", firm_id)
        if client_id:
            q = q.or_(f"client_id.eq.{client_id},client_id.is.null")
        rows = q.execute().data or []
        return {
            r["id"]: Account(
                id=r["id"], code=r.get("account_code", ""), name=r.get("account_name", ""),
                type=r.get("account_type", ""), subtype=r.get("account_subtype"),
                system_key=r.get("system_account_key"),
            )
            for r in rows
        }

    def _entries(self, firm_id, client_id) -> dict[str, JournalEntry]:
        q = (self.db.table("journal_entries")
             .select("id, entry_date, client_id, firm_id, entry_type, reversal_of, "
                     "journal_lines(account_id, debit_paise, credit_paise)")
             .eq("firm_id", firm_id).eq("is_posted", True).is_("deleted_at", "null"))
        if client_id:
            q = q.eq("client_id", client_id)
        rows = q.execute().data or []
        out: dict[str, JournalEntry] = {}
        for r in rows:
            lines = tuple(
                JournalLine(l["account_id"], int(l.get("debit_paise", 0) or 0),
                            int(l.get("credit_paise", 0) or 0))
                for l in (r.get("journal_lines") or [])
            )
            out[r["id"]] = JournalEntry(
                id=r["id"], entry_date=r["entry_date"], client_id=r.get("client_id", ""),
                firm_id=r.get("firm_id", ""), entry_type=r.get("entry_type", ""),
                lines=lines, reversal_of=r.get("reversal_of"),
            )
        return out

    def _invoices(self, firm_id, client_id) -> dict[str, Invoice]:
        q = self.db.table("client_sales_invoices").select(
            "id, total_paise, journal_entry_id").eq("firm_id", firm_id)
        if client_id:
            q = q.eq("client_id", client_id)
        rows = q.execute().data or []
        return {r["id"]: Invoice(r["id"], int(r.get("total_paise", 0) or 0),
                                 r.get("journal_entry_id")) for r in rows}

    def _receipts(self, firm_id, client_id) -> dict[str, Receipt]:
        q = self.db.table("receipts").select(
            "id, amount_paise, tds_paise, journal_entry_id").eq("firm_id", firm_id)
        if client_id:
            q = q.eq("client_id", client_id)
        rows = q.execute().data or []
        return {r["id"]: Receipt(r["id"], r.get("journal_entry_id"),
                                 int(r.get("amount_paise", 0) or 0),
                                 int(r.get("tds_paise", 0) or 0)) for r in rows}

    def _allocations(self, receipt_ids) -> dict[str, list[ReceiptAllocation]]:
        out: dict[str, list[ReceiptAllocation]] = {}
        if not receipt_ids:
            return out
        rows = (self.db.table("receipt_allocations")
                .select("receipt_id, sales_invoice_id, allocated_paise")
                .in_("receipt_id", receipt_ids).execute().data or [])
        for r in rows:
            out.setdefault(r["receipt_id"], []).append(ReceiptAllocation(
                r["receipt_id"], r["sales_invoice_id"], int(r.get("allocated_paise", 0) or 0)))
        return out

    def _credit_notes(self, firm_id, client_id) -> list[CreditNote]:
        q = self.db.table("credit_notes").select(
            "id, sales_invoice_id, journal_entry_id").eq("firm_id", firm_id)
        if client_id:
            q = q.eq("client_id", client_id)
        rows = q.execute().data or []
        return [CreditNote(r["id"], r.get("sales_invoice_id"), r.get("journal_entry_id")) for r in rows]

    def _bills(self, firm_id, client_id) -> dict[str, Bill]:
        q = self.db.table("purchase_bills").select(
            "id, total_paise, journal_entry_id").eq("firm_id", firm_id)
        if client_id:
            q = q.eq("client_id", client_id)
        rows = q.execute().data or []
        return {r["id"]: Bill(r["id"], int(r.get("total_paise", 0) or 0),
                              r.get("journal_entry_id")) for r in rows}

    def _payments(self, firm_id, client_id) -> list[Payment]:
        q = self.db.table("purchase_payments").select(
            "id, purchase_bill_id, amount_paise, journal_entry_id").eq("firm_id", firm_id)
        if client_id:
            q = q.eq("client_id", client_id)
        rows = q.execute().data or []
        return [Payment(r["id"], r.get("purchase_bill_id"), r.get("journal_entry_id"),
                        int(r.get("amount_paise", 0) or 0)) for r in rows]
