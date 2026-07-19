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

import logging
import os
from datetime import date
from typing import Optional

from core.ist_clock import ist_today

from . import balance_cache
from . import builders
from . import schedule_iii as schedule_iii_builder
from .model import ProjectedLine
from .projector import CashBasisProjector
from .resolver import AccountResolver
from .sources import InMemoryLedgerSource, LedgerSource, SupabaseLedgerSource

_logger = logging.getLogger("caflow.reporting.service")


def _passbook_mode() -> str:
    """Reporting passbook rollout switch (env REPORTING_PASSBOOK_MODE):
      off    — legacy full-history replay only.
      shadow — serve the legacy result, ALSO compute via the passbook and compare,
               logging any mismatch. Proves equivalence on real traffic with no
               user-facing risk before flipping.
      on     — serve the fast passbook result (falling back to legacy if the fast
               path errors, so a missing/stale cache degrades to slow, never wrong).
    Applies to ACCRUAL Trial Balance / P&L / Balance Sheet only; cash basis,
    Cash Flow and the ledger drill-down always use the legacy engine.

    DEFAULTS TO "on": the buckets are backfilled + trigger-maintained and were
    verified paise-identical to the raw ledger, and the legacy fall-back makes
    "on" safe. The default lives here (not only in render.yaml) because the host's
    blueprint does not auto-apply env-var changes — a code default deploys
    reliably, whereas the env var would sit unapplied. Tests force "off" via
    conftest (their fake DBs have no buckets); an explicit env var still wins."""
    m = os.environ.get("REPORTING_PASSBOOK_MODE", "on").strip().lower()
    return m if m in ("off", "shadow", "on") else "on"


def _log_shadow_mismatch(ctx: tuple, legacy_out: dict, fast_out: dict) -> None:
    diffs = {
        k: {"legacy": legacy_out.get(k), "fast": fast_out.get(k)}
        for k in (set(legacy_out) | set(fast_out))
        if isinstance(legacy_out.get(k), int) and legacy_out.get(k) != fast_out.get(k)
    }
    _logger.error("PASSBOOK SHADOW MISMATCH %s — top-level int diffs=%s "
                  "(also check line-level rows)", ctx, diffs or "none-at-top-level")


def _fy_start(today: date | None = None) -> str:
    today = today or ist_today()
    return date(today.year if today.month >= 4 else today.year - 1, 4, 1).isoformat()


def _day_before(iso: str) -> str:
    from datetime import timedelta
    return (date.fromisoformat(iso[:10]) - timedelta(days=1)).isoformat()


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

    # ── Passbook (fast accrual) plumbing ───────────────────────────────────────
    def _passbook_applicable(self, basis: str) -> bool:
        return (basis == "accrual" and _passbook_mode() != "off"
                and isinstance(self.source, SupabaseLedgerSource))

    def _passbook_accrual_lines(self, firm_id, client_id, start, end):
        """Accrual accounts + ProjectedLines for [start, end] read from the
        passbook (small buckets + at most two edge months) instead of the full
        posted history."""
        accounts = self.source._accounts(firm_id, client_id)
        buckets = self.source.fetch_buckets(firm_id, client_id)
        edge = self.source.fetch_edge_month_entries(firm_id, client_id, start, end)
        lines = balance_cache.project_lines(buckets, start, end, edge)
        return accounts, lines

    def _serve(self, ctx: tuple, fast, legacy):
        """Route a report through the passbook according to the rollout mode.
        `on` serves fast (legacy fallback on error); `shadow` serves legacy but
        computes fast and compares."""
        mode = _passbook_mode()
        if mode == "on":
            try:
                return fast()
            except Exception as e:  # a missing/stale cache must degrade to slow, never wrong
                _logger.error("passbook fast path failed %s — falling back to legacy: %s", ctx, e)
                return legacy()
        legacy_out = legacy()          # shadow: the trusted result is what we serve
        try:
            fast_out = fast()
            if fast_out != legacy_out:
                _log_shadow_mismatch(ctx, legacy_out, fast_out)
        except Exception as e:  # shadow compute must never affect the served result
            _logger.error("passbook shadow compute failed %s: %s", ctx, e)
        return legacy_out

    def trial_balance(self, firm_id: str, client_id: Optional[str],
                      as_of_date: Optional[str], basis: str = "accrual") -> dict:
        as_of = as_of_date or ist_today().isoformat()

        def legacy():
            snap = self.source.snapshot(firm_id, client_id, None, as_of)
            return builders.trial_balance(self._lines(snap, basis), snap.accounts, as_of, basis)

        if not self._passbook_applicable(basis):
            return legacy()

        def fast():
            accounts, lines = self._passbook_accrual_lines(firm_id, client_id, None, as_of)
            return builders.trial_balance(lines, accounts, as_of, "accrual")

        return self._serve(("trial_balance", firm_id, client_id, as_of), fast, legacy)

    def ledger(self, firm_id: str, client_id: Optional[str], account_id: str,
               start_date: Optional[str] = None, end_date: Optional[str] = None) -> dict:
        """Per-account general ledger (accrual, posted-only) from the same engine
        and scoped source as every other report. Opening balance carries forward
        from before `start`; the snapshot's full posted history supplies it."""
        start = start_date or _fy_start()
        end = end_date or ist_today().isoformat()
        snap = self.source.snapshot(firm_id, client_id, start, end)
        return builders.ledger(snap.entries_by_id, snap.accounts, account_id, start, end)

    def profit_loss(self, firm_id: str, client_id: Optional[str],
                    start_date: Optional[str], end_date: Optional[str],
                    basis: str = "accrual") -> dict:
        start = start_date or _fy_start()
        end = end_date or ist_today().isoformat()

        def legacy():
            snap = self.source.snapshot(firm_id, client_id, start, end)
            return builders.profit_loss(self._lines(snap, basis), snap.accounts, start, end, basis)

        if not self._passbook_applicable(basis):
            return legacy()

        def fast():
            accounts, lines = self._passbook_accrual_lines(firm_id, client_id, start, end)
            return builders.profit_loss(lines, accounts, start, end, "accrual")

        return self._serve(("profit_loss", firm_id, client_id, start, end), fast, legacy)

    def balance_sheet(self, firm_id: str, client_id: Optional[str],
                      as_of_date: Optional[str], basis: str = "accrual") -> dict:
        as_of = as_of_date or ist_today().isoformat()

        def legacy():
            snap = self.source.snapshot(firm_id, client_id, None, as_of)
            return builders.balance_sheet(self._lines(snap, basis), snap.accounts, as_of, basis)

        if not self._passbook_applicable(basis):
            return legacy()

        def fast():
            accounts, lines = self._passbook_accrual_lines(firm_id, client_id, None, as_of)
            return builders.balance_sheet(lines, accounts, as_of, "accrual")

        return self._serve(("balance_sheet", firm_id, client_id, as_of), fast, legacy)

    def schedule_iii(self, firm_id: str, client_id: Optional[str],
                     fy_start: Optional[str], fy_end: Optional[str]) -> dict:
        """Companies Act 2013 Schedule III (Division I) presentation of the P&L
        (for the year) and Balance Sheet (as at year-end). Statutory statements
        must use accrual (Companies Act §128), so basis is fixed to accrual — the
        cash-basis management view is intentionally not offered here. The P&L and
        BS amounts come from the same reporting engine as every other report;
        schedule_iii only groups them into the statutory captions."""
        start = fy_start or _fy_start()
        end = fy_end or ist_today().isoformat()
        pl = self.profit_loss(firm_id, client_id, start, end, basis="accrual")
        bs = self.balance_sheet(firm_id, client_id, end, basis="accrual")
        return schedule_iii_builder.build_schedule_iii(pl, bs, start, end)

    def cash_flow_statement(self, firm_id: str, client_id: Optional[str],
                            start_date: Optional[str], end_date: Optional[str],
                            basis: str = "accrual") -> dict:
        """
        AS-3 Cash Flow Statement (indirect), Companies Act 2013 Schedule III.

        Investing & financing follow the ACTUAL cash legs of posted entries that
        touch fixed-asset / loan / equity accounts; operating is the residual,
        presented as the indirect reconciliation (net profit + depreciation
        add-back − non-operating items ± working capital). Non-cash entries
        (depreciation, year-end closing) are excluded — they have no cash leg.

        A cash flow statement is intrinsically actual-cash, so investing/financing
        and the cash totals are basis-invariant; the operating reconciliation uses
        the accrual P&L. `basis` is accepted for API symmetry and echoed only.
        Opening and closing cash are computed INDEPENDENTLY from the ledger, so the
        reconciliation is a real check, not a tautology.
        """
        start = start_date or _fy_start()
        end = end_date or ist_today().isoformat()
        period_snap = self.source.snapshot(firm_id, client_id, start, end)
        bank_ids = AccountResolver(period_snap.accounts).bank_ids
        entries = period_snap.entries_in_range
        opening_cash = self._cash_balance(firm_id, client_id, _day_before(start), "accrual")
        closing_cash = self._cash_balance(firm_id, client_id, end, "accrual")
        return builders.cash_flow(
            entries, period_snap.accounts, bank_ids,
            start, end, opening_cash, closing_cash, basis,
        )

    def _cash_balance(self, firm_id: str, client_id: Optional[str],
                      as_of: str, basis: str) -> int:
        """Cumulative cash/bank balance (integer paise) as of a date, same basis
        stream as the report. Cash legs are basis-invariant, so accrual and cash
        agree; computing on the requested basis keeps the tie-out exact."""
        snap = self.source.snapshot(firm_id, client_id, None, as_of)
        bank_ids = AccountResolver(snap.accounts).bank_ids
        total = 0
        for ln in self._lines(snap, basis):
            if ln.account_id in bank_ids:
                total += ln.debit_paise - ln.credit_paise
        return total


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
