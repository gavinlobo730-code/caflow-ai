"""
Cash-basis projector — IT Act §145 (cash method of accounting).

Transforms the posted accrual ledger into a cash-basis line stream by
recognising revenue only when collected and expense only when paid, with the
collected/paid linkage read from the document allocation tables — NEVER by
matching rupee amounts. Every transformed entry balances to the paise.

Management reporting only. GST returns remain invoice-based per the CGST Act
and are entirely unaffected by this view.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from .model import JournalEntry, LedgerSnapshot, ProjectedLine, apportion
from .resolver import AccountResolver

_logger = logging.getLogger("caflow.reporting.cash")

# Synthetic accounts used when the chart has no advance control account.
ADVANCE_CUSTOMER = ("__advance_customers__", "Advance from Customers", "Liability")
ADVANCE_VENDOR = ("__advance_to_vendors__", "Advance to Vendors", "Asset")


class CashBasisProjector:
    """
    Projects a LedgerSnapshot into cash-basis ProjectedLines.

    Per posted entry in the report window:
      INVOICE / BILL / CREDIT_NOTE -> dropped (accrual recognition only)
      RECEIPT  -> keep cash legs; recognise revenue from allocated invoices
      PAYMENT  -> keep cash leg; recognise expense from the linked bill
      REVERSAL -> re-project the original entry and negate it
      DIRECT   -> pass through, but any leg touching A/R or A/P (a manual entry
                  that bypassed the document flow) is rerouted to the same
                  Advance from Customers / Advance to Vendors accounts used for
                  unallocated cash (Decision C), so it can never resurrect an
                  accrual receivable/payable on the cash-basis Balance Sheet.
    """

    def __init__(self, snapshot: LedgerSnapshot, resolver: AccountResolver):
        self.s = snapshot
        self.r = resolver
        # Per-invoice net revenue/GST distribution cache.
        self._dist_cache: dict[str, list[tuple[str, int]]] = {}

    # ── public ──────────────────────────────────────────────────────────────

    def project(self) -> list[ProjectedLine]:
        out: list[ProjectedLine] = []
        for entry in self.s.entries_in_range:
            out.extend(self._project_entry(entry, sign=1))
        return out

    # ── per-entry dispatch ────────────────────────────────────────────────────

    def _project_entry(self, entry: JournalEntry, sign: int) -> list[ProjectedLine]:
        if entry.reversal_of:
            original = self.s.entries_by_id.get(entry.reversal_of)
            if original is not None:
                # Reverse the economic effect of the original by negating its projection.
                return self._project_entry(original, sign=-sign)
            # Unknown original — fall through to pass-through so the books still balance.
            return self._passthrough(entry, sign)

        eid = entry.id
        receipt = self.s.receipt_by_journal.get(eid)
        if receipt is not None:
            return self._project_receipt(entry, sign)
        if eid in self.s.payment_by_journal:
            return self._project_payment(entry, sign)
        if (eid in self.s.invoice_by_journal
                or eid in self.s.bill_by_journal
                or eid in self.s.creditnote_by_journal):
            return []  # accrual recognition document — no cash effect on its own
        return self._passthrough(entry, sign)

    # ── projections ───────────────────────────────────────────────────────────

    def _passthrough(self, entry: JournalEntry, sign: int) -> list[ProjectedLine]:
        """Pass DIRECT (undocumented) entries through as-is, except any leg on the
        A/R or A/P control account — those never happen via the normal document
        flow (invoices/bills always route through _project_receipt/_project_payment),
        so a manual journal that touches them is netted off and rerouted to the
        advance control accounts instead of leaking an accrual balance into the
        cash-basis books."""
        ar_net = 0
        ap_net = 0
        out: list[ProjectedLine] = []
        for ln in entry.lines:
            if self.r.is_ar(ln.account_id):
                ar_net += ln.credit_paise - ln.debit_paise
                continue
            if self.r.is_ap(ln.account_id):
                ap_net += ln.debit_paise - ln.credit_paise
                continue
            out.append(self._signed(ln.account_id, ln.debit_paise, ln.credit_paise, sign))

        if ar_net != 0:
            _logger.warning(
                "cash-basis: DIRECT entry %s touches A/R outside the document flow "
                "(net %d paise) -- routed to Advance from Customers", entry.id, ar_net)
            aid = self.r.advance_customer_id or self._ensure_synthetic(*ADVANCE_CUSTOMER)
            if ar_net > 0:
                out.append(self._signed(aid, 0, ar_net, sign))
            else:
                out.append(self._signed(aid, -ar_net, 0, sign))

        if ap_net != 0:
            _logger.warning(
                "cash-basis: DIRECT entry %s touches A/P outside the document flow "
                "(net %d paise) -- routed to Advance to Vendors", entry.id, ap_net)
            aid = self.r.advance_vendor_id or self._ensure_synthetic(*ADVANCE_VENDOR)
            if ap_net > 0:
                out.append(self._signed(aid, ap_net, 0, sign))
            else:
                out.append(self._signed(aid, 0, -ap_net, sign))

        return out

    def _project_receipt(self, entry: JournalEntry, sign: int) -> list[ProjectedLine]:
        """Dr Bank (+ Dr TDS Receivable) kept; Cr A/R replaced by recognised revenue."""
        out: list[ProjectedLine] = []
        ar_cleared = 0
        for ln in entry.lines:
            if self.r.is_ar(ln.account_id):
                ar_cleared += ln.credit_paise - ln.debit_paise  # net A/R credit cleared
                continue
            out.append(self._signed(ln.account_id, ln.debit_paise, ln.credit_paise, sign))

        if ar_cleared <= 0:
            return out  # nothing collected against receivables (defensive)

        receipt = self.s.receipt_by_journal[entry.id]
        recognised = 0
        for alloc in self.s.allocations_by_receipt.get(receipt.id, []):
            if recognised >= ar_cleared:
                break
            amount = min(alloc.allocated_paise, ar_cleared - recognised)
            legs = self._invoice_distribution(alloc.sales_invoice_id)
            weights = [w for _, w in legs]
            if legs and sum(weights) > 0:
                parts = apportion(amount, weights)
                for (aid, _), p in zip(legs, parts):
                    if p:
                        out.append(self._signed(aid, 0, p, sign))  # Cr revenue/GST
                recognised += amount
            # else: invoice not resolvable / fully credited -> falls into remainder below

        remaining = ar_cleared - recognised
        if remaining > 0:
            # Decision C: unallocated / unattributable cash -> Advance from Customers (liability).
            aid = self.r.advance_customer_id or self._ensure_synthetic(*ADVANCE_CUSTOMER)
            out.append(self._signed(aid, 0, remaining, sign))
        return out

    def _project_payment(self, entry: JournalEntry, sign: int) -> list[ProjectedLine]:
        """Cr Bank kept; Dr A/P replaced by recognised expense from the linked bill."""
        out: list[ProjectedLine] = []
        ap_cleared = 0
        for ln in entry.lines:
            if self.r.is_ap(ln.account_id):
                ap_cleared += ln.debit_paise - ln.credit_paise  # net A/P debit cleared
                continue
            out.append(self._signed(ln.account_id, ln.debit_paise, ln.credit_paise, sign))

        if ap_cleared <= 0:
            return out

        payment = self.s.payment_by_journal[entry.id]
        recognised = 0
        if payment.purchase_bill_id:
            legs = self._bill_distribution(payment.purchase_bill_id)
            weights = [w for _, w in legs]
            if legs and sum(weights) > 0:
                parts = apportion(ap_cleared, weights)
                for (aid, _), p in zip(legs, parts):
                    if p:
                        out.append(self._signed(aid, p, 0, sign))  # Dr expense / GST input
                recognised = ap_cleared

        remaining = ap_cleared - recognised
        if remaining > 0:
            # Decision C mirror: advance / unattributable payment -> Advance to Vendors (asset).
            aid = self.r.advance_vendor_id or self._ensure_synthetic(*ADVANCE_VENDOR)
            out.append(self._signed(aid, remaining, 0, sign))
        return out

    # ── distribution helpers (revenue/expense account split per document) ──────

    def _invoice_distribution(self, invoice_id: str) -> list[tuple[str, int]]:
        """
        Revenue + GST credit legs of an invoice's journal entry, net of any
        applied credit notes. Returns [(account_id, weight_paise), ...].
        Netting changes only which accounts receive the cash, never the total.
        """
        if invoice_id in self._dist_cache:
            return self._dist_cache[invoice_id]

        legs: list[tuple[str, int]] = []
        inv = self.s.invoices.get(invoice_id)
        if inv and inv.journal_entry_id:
            je = self.s.entries_by_id.get(inv.journal_entry_id)
            if je:
                net: dict[str, int] = defaultdict(int)
                for ln in je.lines:
                    if not self.r.is_ar(ln.account_id) and ln.credit_paise > 0:
                        net[ln.account_id] += ln.credit_paise
                # Subtract credit-note debits to the same accounts (CGST Act §34).
                for cn in self.s.credit_notes:
                    if cn.sales_invoice_id != invoice_id or not cn.journal_entry_id:
                        continue
                    cje = self.s.entries_by_id.get(cn.journal_entry_id)
                    if not cje:
                        continue
                    for ln in cje.lines:
                        if not self.r.is_ar(ln.account_id) and ln.debit_paise > 0:
                            net[ln.account_id] -= ln.debit_paise
                legs = [(aid, w) for aid, w in net.items() if w > 0]

        self._dist_cache[invoice_id] = legs
        return legs

    def _bill_distribution(self, bill_id: str) -> list[tuple[str, int]]:
        """Expense + GST-input debit legs of a bill's journal entry."""
        cache_key = f"bill:{bill_id}"
        if cache_key in self._dist_cache:
            return self._dist_cache[cache_key]
        legs: list[tuple[str, int]] = []
        bill = self.s.bills.get(bill_id)
        if bill and bill.journal_entry_id:
            je = self.s.entries_by_id.get(bill.journal_entry_id)
            if je:
                net: dict[str, int] = defaultdict(int)
                for ln in je.lines:
                    if not self.r.is_ap(ln.account_id) and ln.debit_paise > 0:
                        net[ln.account_id] += ln.debit_paise
                legs = [(aid, w) for aid, w in net.items() if w > 0]
        self._dist_cache[cache_key] = legs
        return legs

    # ── utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _signed(account_id: str, debit: int, credit: int, sign: int) -> ProjectedLine:
        if sign >= 0:
            return ProjectedLine(account_id, debit, credit)
        # Negate by swapping debit/credit so the entry still balances.
        return ProjectedLine(account_id, credit, debit)

    def _ensure_synthetic(self, acc_id: str, name: str, acc_type: str) -> str:
        """Register a synthetic advance control account if the chart lacks one."""
        if acc_id not in self.s.accounts:
            from .model import Account
            self.s.accounts[acc_id] = Account(
                id=acc_id, code="", name=name, type=acc_type, system_key=None,
            )
        return acc_id
