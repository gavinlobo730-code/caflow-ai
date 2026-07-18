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
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from .model import (
    Account, Bill, CreditNote, Invoice, JournalEntry, JournalLine,
    LedgerSnapshot, Payment, Receipt, ReceiptAllocation,
)

_logger = logging.getLogger("caflow.reporting.source")

# Bounded worker pool for read-only Supabase fetches — used by _base() to run its
# independent top-level table fetches concurrently. (_fetch_all itself now pages
# sequentially by keyset; see its docstring for why.) httpx.Client (which
# supabase-py/postgrest-py wrap) is documented thread-safe for concurrent
# requests, so sharing one client instance across these workers is safe; each
# fetch here is a read with no shared mutable state beyond that.
_MAX_PARALLEL_FETCHES = 6


def _in_range(d: str, start: Optional[str], end: Optional[str]) -> bool:
    if start and d < start:
        return False
    if end and d > end:
        return False
    return True


def _is_missing_column_error(err: Exception, column: str) -> bool:
    """
    True when a PostgREST/Supabase error indicates `column` does not exist yet
    (i.e. migration 092 has not been applied). Requires the column name AND a
    not-found signal so unrelated failures (network, auth) are never swallowed.
    """
    s = str(err).lower()
    return column.lower() in s and any(
        marker in s for marker in
        ("does not exist", "could not find", "schema cache", "42703", "pgrst204")
    )


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

    # Base columns always present. system_account_key (migration 092) and
    # reversal_of (migration 055) are added later and probed for separately, so
    # reports run whether or not those migrations have been applied.
    _BASE_ACCOUNT_COLS = "id, account_code, account_name, account_type, account_subtype"
    _ENTRY_SCALAR_COLS = ("id, entry_date, client_id, firm_id, entry_type, "
                          "reference_no, narration, created_at")
    _BASE_LINE_COLS = "account_id, debit_paise, credit_paise"
    # Multi-Currency Phase 5: optional per-line FX memo (migration 147). Probed for
    # separately (like system_account_key / reversal_of) so reports run whether or
    # not the multi-currency migrations have been applied; base amounts above are
    # always authoritative.
    _LINE_CURRENCY_COLS = "txn_currency, txn_debit, txn_credit, exchange_rate"
    # Entries are PAGED (audit C6): PostgREST's ~1000-row cap on the top-level
    # journal_entries query silently truncated the ledger for any client with >1000
    # posted entries, corrupting TB/BS/P&L with no error. Lines stay embedded per
    # entry (a bounded handful each), so only the top-level fetch needs paging.
    _PAGE = 1000

    def __init__(self, db):
        self.db = db
        # None = not yet probed; True/False once the table has been read. Makes
        # reports work whether or not migrations 092 / 055 have run — deployment
        # order between those migrations and this code no longer matters.
        self._has_system_key: bool | None = None
        self._has_reversal_of: bool | None = None
        self._has_line_currency: bool | None = None   # journal_lines FX memo (migration 147)
        # Per-request memo of the (date-independent) base fetch, keyed by
        # (firm_id, client_id). A fresh source is created per request, so this only
        # dedupes repeated fetches WITHIN one request (e.g. cash_flow calls
        # snapshot() 3× with different date windows; a reports bundle calls it once
        # per report) — never across requests, so there is no staleness risk.
        self._base_cache: dict[tuple[str, Optional[str]], dict] = {}

    def _base(self, firm_id, client_id) -> dict:
        """Fetch (once per request) all tenant-scoped rows the reports need. Only the
        entry date-window differs between report calls, so everything here is cached
        and snapshot() just re-applies the date filter.

        The 7 top-level fetches below are independent reads (only _allocations
        depends on one of them — receipts — so it runs after). They used to run
        one after another; for a client with a large ledger that was N sequential
        HTTP round trips to Supabase before a single number could be computed.
        Running them concurrently turns that into ~1 round trip's worth of
        wall-clock time. A failure in any fetch still fails _base() the same way
        it always did — .result() re-raises."""
        key = (firm_id, client_id)
        cached = self._base_cache.get(key)
        if cached is not None:
            return cached

        with ThreadPoolExecutor(max_workers=_MAX_PARALLEL_FETCHES) as ex:
            f_accounts     = ex.submit(self._accounts, firm_id, client_id)
            f_entries      = ex.submit(self._entries, firm_id, client_id)
            f_invoices     = ex.submit(self._invoices, firm_id, client_id)
            f_receipts     = ex.submit(self._receipts, firm_id, client_id)
            f_credit_notes = ex.submit(self._credit_notes, firm_id, client_id)
            f_bills        = ex.submit(self._bills, firm_id, client_id)
            f_payments     = ex.submit(self._payments, firm_id, client_id)

            accounts     = f_accounts.result()
            entries_by_id = f_entries.result()
            invoices     = f_invoices.result()
            receipts     = f_receipts.result()
            credit_notes = f_credit_notes.result()
            bills        = f_bills.result()
            payments     = f_payments.result()

        data = {
            "accounts": accounts,
            "entries_by_id": entries_by_id,
            "invoices": invoices,
            "receipts": receipts,
            "allocations_by_receipt": self._allocations(list(receipts.keys())),
            "credit_notes": credit_notes,
            "bills": bills,
            "payments": payments,
        }
        self._base_cache[key] = data
        return data

    def snapshot(self, firm_id, client_id, start_date, end_date) -> LedgerSnapshot:
        b = self._base(firm_id, client_id)
        entries_by_id = b["entries_by_id"]
        in_range = [e for e in entries_by_id.values() if _in_range(e.entry_date, start_date, end_date)]
        in_range.sort(key=lambda e: e.entry_date)

        invoices = b["invoices"]
        receipts = b["receipts"]
        credit_notes = b["credit_notes"]
        bills = b["bills"]
        payments = b["payments"]

        return LedgerSnapshot(
            accounts=b["accounts"],
            entries_in_range=in_range,
            entries_by_id=entries_by_id,
            invoices=invoices,
            allocations_by_receipt=b["allocations_by_receipt"],
            credit_notes=credit_notes,
            bills=bills,
            receipt_by_journal={r.journal_entry_id: r for r in receipts.values() if r.journal_entry_id},
            payment_by_journal={p.journal_entry_id: p for p in payments if p.journal_entry_id},
            invoice_by_journal={i.journal_entry_id: i for i in invoices.values() if i.journal_entry_id},
            bill_by_journal={b2.journal_entry_id: b2 for b2 in bills.values() if b2.journal_entry_id},
            creditnote_by_journal={c.journal_entry_id: c for c in credit_notes if c.journal_entry_id},
        )

    # ── scoped fetches ────────────────────────────────────────────────────────

    def _accounts(self, firm_id, client_id) -> dict[str, Account]:
        def run(select_cols: str):
            q = self.db.table("chart_of_accounts").select(select_cols).eq("firm_id", firm_id)
            if client_id:
                q = q.or_(f"client_id.eq.{client_id},client_id.is.null")
            return q.execute().data or []

        rows = None
        # Use system_account_key when present; tolerate its absence pre-migration.
        if self._has_system_key is not False:
            try:
                rows = run(self._BASE_ACCOUNT_COLS + ", system_account_key")
                self._has_system_key = True
            except Exception as e:  # noqa: BLE001 — re-raised unless it's the missing column
                if not _is_missing_column_error(e, "system_account_key"):
                    raise
                self._has_system_key = False
                _logger.warning(
                    "chart_of_accounts.system_account_key not found — falling back to "
                    "name-based control-account resolution until migration 092 is applied."
                )
        if rows is None:
            rows = run(self._BASE_ACCOUNT_COLS)

        return {
            r["id"]: Account(
                id=r["id"], code=r.get("account_code", ""), name=r.get("account_name", ""),
                type=r.get("account_type", ""), subtype=r.get("account_subtype"),
                # .get() yields None when the column is absent → resolver name fallback.
                system_key=r.get("system_account_key"),
            )
            for r in rows
        }

    def _fetch_page(self, make_query, cursor, key: str, max_retries: int) -> list[dict]:
        """Fetch ONE keyset page — the next <=_PAGE rows whose `key` is strictly
        greater than `cursor` (None on the first page) — with retry-with-backoff
        on transient failure.

        Confirmed in production: for a client with 12k+ posted entries, one page
        hit a transient PostgREST 500 while every other page — including the SAME
        page moments later — succeeded. Before the retry, that single transient
        failure aborted the entire report, which the frontend then rendered as "no
        posted journal entries" (indistinguishable from a genuinely empty ledger)
        instead of a retryable error."""
        last_err: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                q = make_query()
                if cursor is not None:
                    q = q.gt(key, cursor)
                return q.limit(self._PAGE).execute().data or []
            except Exception as e:  # noqa: BLE001 — retry transient PostgREST/network failures
                last_err = e
                if attempt < max_retries - 1:
                    _logger.warning(
                        "Reporting fetch page failed (cursor=%s, attempt=%d/%d) — retrying: %s",
                        cursor, attempt + 1, max_retries, e,
                    )
                    time.sleep(0.3 * (attempt + 1))
        _logger.error(
            "Reporting fetch page failed permanently after %d attempts (cursor=%s): %s",
            max_retries, cursor, last_err,
        )
        raise last_err

    def _fetch_all(self, make_query, key: str = "id", max_retries: int = 3) -> list[dict]:
        """Fetch EVERY matching row via KEYSET (cursor) paging over a query ordered
        ascending by `key`, so results are never silently capped at PostgREST's
        ~1000-row limit (audit C6). `make_query` must return a fresh builder
        ordered ascending by `key`, and its select MUST include `key` so the next
        page's cursor can be read from the last row.

        KEYSET, not OFFSET — this is the fix for the report timeout (2026-07-18).
        With OFFSET, page k must re-scan (and, because journal_lines is embedded,
        RE-RUN the per-row line-aggregate for) all k*_PAGE preceding rows, so
        paging the whole ledger is O(entries^2): for a 12.8k-entry client the embed
        aggregate ran ~91k times instead of ~12.8k, and the deep pages tripped the
        database statement timeout (pg_stat_statements showed this exact query at
        mean 3.2s / max 8.0s). Keyset makes every page a bounded `WHERE key > :cursor
        ... LIMIT _PAGE` seek that touches only its own _PAGE rows regardless of
        depth, so total work is linear and no single page can time out. The partial
        index idx_journal_entries_firm_client_posted_id (migration 229) serves the
        (firm_id, client_id, id) seek directly.

        Paging is sequential (each cursor comes from the previous page's last row),
        which also cuts the concurrent DB load that the old 6-wide offset batch
        added to the contention. End-of-data is a short page (< _PAGE) — the
        genuine signal, NEVER an assumed PostgREST row count, which can be
        unreliable alongside an embedded relation and would silently truncate a
        financial report rather than just be slow."""
        out: list[dict] = []
        cursor = None
        while True:
            page = self._fetch_page(make_query, cursor, key, max_retries)
            out.extend(page)
            if len(page) < self._PAGE:
                break                                    # genuine end-of-data
            cursor = page[-1][key]                        # next page starts after this row
        return out

    def _entries(self, firm_id, client_id, date_from: Optional[str] = None,
                 date_to: Optional[str] = None) -> dict[str, JournalEntry]:
        """Posted, non-deleted entries for a tenant. date_from/date_to (inclusive
        entry_date bounds) are used by the passbook read path to pull only the one
        or two partial edge months it needs; unbounded (the default) is the full
        history the legacy report path and the backfill use."""
        def entry_cols(with_rev: bool, with_ccy: bool) -> str:
            line_cols = self._BASE_LINE_COLS + ((", " + self._LINE_CURRENCY_COLS) if with_ccy else "")
            cols = self._ENTRY_SCALAR_COLS + f", journal_lines({line_cols})"
            return cols + (", reversal_of" if with_rev else "")

        def make_q(with_rev: bool, with_ccy: bool):
            q = (self.db.table("journal_entries").select(entry_cols(with_rev, with_ccy))
                 .eq("firm_id", firm_id).eq("is_posted", True).is_("deleted_at", "null"))
            if client_id:
                q = q.eq("client_id", client_id)
            if date_from:
                q = q.gte("entry_date", date_from)
            if date_to:
                q = q.lte("entry_date", date_to)
            return q.order("id")   # stable key → correct offset paging

        # Probe reversal_of (migration 055) and the FX line memo (migration 147)
        # independently; on a missing column, disable that probe and retry. This
        # tolerates ANY subset of those additive migrations being applied, so the
        # ledger runs everywhere and only gains foreign visibility where the columns
        # exist (base amounts are always read).
        want_rev = self._has_reversal_of is not False
        want_ccy = self._has_line_currency is not False
        rows = None
        while rows is None:
            try:
                rows = self._fetch_all(lambda: make_q(want_rev, want_ccy))
                if want_rev:
                    self._has_reversal_of = True
                if want_ccy:
                    self._has_line_currency = True
            except Exception as e:  # noqa: BLE001 — re-raised unless it's a known missing column
                if want_ccy and any(_is_missing_column_error(e, c) for c in
                                    ("txn_currency", "txn_debit", "txn_credit", "exchange_rate")):
                    self._has_line_currency = False
                    want_ccy = False
                    _logger.warning(
                        "journal_lines FX columns not found — General Ledger shows base "
                        "(INR) only until multi-currency migration 147 is applied."
                    )
                elif want_rev and _is_missing_column_error(e, "reversal_of"):
                    self._has_reversal_of = False
                    want_rev = False
                    _logger.warning(
                        "journal_entries.reversal_of not found — treating all entries as "
                        "non-reversals until migration 055 is applied."
                    )
                else:
                    raise

        out: dict[str, JournalEntry] = {}
        for r in rows:
            lines = tuple(
                JournalLine(
                    l["account_id"], int(l.get("debit_paise", 0) or 0),
                    int(l.get("credit_paise", 0) or 0),
                    # Optional foreign memo — None for INR / un-migrated rows.
                    txn_currency=l.get("txn_currency"),
                    txn_debit=(int(l["txn_debit"]) if l.get("txn_debit") is not None else None),
                    txn_credit=(int(l["txn_credit"]) if l.get("txn_credit") is not None else None),
                    exchange_rate=(str(l["exchange_rate"]) if l.get("exchange_rate") is not None else None),
                )
                for l in (r.get("journal_lines") or [])
            )
            out[r["id"]] = JournalEntry(
                id=r["id"], entry_date=r["entry_date"], client_id=r.get("client_id", ""),
                firm_id=r.get("firm_id", ""), entry_type=r.get("entry_type", ""),
                # .get() yields None when the column is absent → entry treated as non-reversal.
                lines=lines, reversal_of=r.get("reversal_of"),
                reference_no=r.get("reference_no"), narration=r.get("narration"),
                created_at=r.get("created_at"),
            )
        return out

    # ── Passbook read path (reporting perf) ────────────────────────────────────
    def fetch_buckets(self, firm_id, client_id) -> dict[tuple[str, str], tuple[int, int]]:
        """Read a client's monthly buckets from account_period_balances — the
        small, time-bounded table that replaces replaying all history. Keys are
        ('account_id', 'YYYY-MM-01') to match balance_cache.build_buckets."""
        rows = self._fetch_all(lambda: (
            self.db.table("account_period_balances")
            .select("id, account_id, period_month, debit_paise, credit_paise")
            .eq("firm_id", firm_id).eq("client_id", client_id).order("id")
        ))
        return {
            (r["account_id"], str(r["period_month"])[:10]):
                (int(r.get("debit_paise", 0) or 0), int(r.get("credit_paise", 0) or 0))
            for r in rows
        }

    def fetch_edge_month_entries(self, firm_id, client_id, start, end) -> list[JournalEntry]:
        """Fetch the raw posted entries for ONLY the partial edge months of a
        window — the month of `start` when it isn't the 1st, and the month of
        `end` when it isn't the month's last day. These are the months the whole-
        month buckets can't represent exactly, so the passbook replays them from
        raw. At most two calendar months regardless of history depth; empty for a
        month-aligned window (a financial year, a calendar month, a quarter)."""
        from .balance_cache import _is_month_first, _is_month_last  # local: avoid cycle at import

        def _month_bounds(iso_date: str) -> tuple[str, str]:
            import calendar as _cal
            y, m = int(iso_date[:4]), int(iso_date[5:7])
            return f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{_cal.monthrange(y, m)[1]:02d}"

        ranges: list[tuple[str, str]] = []
        if start is not None and not _is_month_first(start):
            ranges.append(_month_bounds(start))
        if end is not None and not _is_month_last(end):
            eb = _month_bounds(end)
            if eb not in ranges:
                ranges.append(eb)
        out: list[JournalEntry] = []
        for mfrom, mto in ranges:
            out.extend(self._entries(firm_id, client_id, date_from=mfrom, date_to=mto).values())
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
