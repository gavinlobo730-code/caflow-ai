"""apex-accounting-reports-04: two of sixteen Verify Books checks silently
never ran for Apex Trading Solutions, on every one of its 20 most recent
nightly runs.

check_missing_cogs_journals sent ~5,645 invoice ids in one
`.in_("id", list(by_invoice.keys()))` filter; PostgREST filters travel in the
URL, and httpx itself refused to build the request ("URL component 'query'
too long") before it ever reached the network.
check_missing_inventory_receipt_journals did the same with ~755 purchase
bill ids (~29,000 characters); there the GATEWAY refused it, with a 400
"JSON could not be generated". Both surfaced identically to the CA: a
"<check_name>.execution_error" critical finding, every night, forever —
because `run_reconciliation` catches each check's own exception and turns it
into a finding rather than aborting the whole run (see
test_run_reconciliation_survives_one_check_erroring in
test_reconciliation_service.py), which is exactly why nobody without this
brief would have noticed two specific checks going dark rather than the
whole sweep failing outright.

The fix routes both id lookups — and a third, structurally identical one in
check_bank_reconciliation_discrepancies, found while touching this file —
through core.db_paging.fetch_all_in, the helper added 28-09-2026 for the
identical failure in the §43B(h) MSME tracker
(services/msme_43bh_service.py; see
tests/test_an_id_list_is_never_longer_than_a_url_can_carry.py for its own
unit tests). fetch_all_in chunks an IN list to IN_CHUNK=150 ids per request.

This file proves the fix two ways per check:
  1. A query double that reproduces the production failure mode exactly —
     it raises once a single `.in_()` call is handed more ids than a URL can
     carry — so a check that still sends one unchunked list dies here the
     same way it died in production, and a correctly chunked one does not.
  2. A source-level assertion that the raw, unbounded `.in_()` calls this
     finding names are gone.

NEGATIVE CONTROL (confirmed by hand, not merely asserted): reverting
services/reconciliation_service.py's three fetch_all_in call sites back to
their pre-fix `_paginate_all(...in_("id"/"reconciliation_id", <whole
list>)...)` form and rerunning this file fails
test_missing_cogs_check_no_longer_dies_on_a_large_invoice_count,
test_missing_inventory_receipt_check_no_longer_dies_on_a_large_bill_count and
test_bank_reconciliation_discrepancy_check_no_longer_dies_on_many_sessions
with the simulated "URL component 'query' too long" exception propagating
out of the check function uncaught — i.e. exactly the crash this finding
reports, reproduced under test. The three fetch_all_in-source assertions
fail too, since the reverted source still contains the raw `.in_(` calls.
"""
from __future__ import annotations

import inspect

import services.reconciliation_service as rs
from core.db_paging import IN_CHUNK
from domain.reporting.model import JournalEntry, JournalLine

FIRM, CLIENT = "FIRM-A", "CLI-A"


class _URLTooLong(Exception):
    """Stands in for httpx's own refusal / the gateway's 400 once a single
    IN list is longer than a URL should be."""


class _Query:
    """Just enough of a PostgREST query builder to run these checks end to
    end against an in-memory table, while reproducing the one behaviour that
    matters here: `.in_()` raises once handed more values than a URL could
    actually carry.

    `_URL_LIMIT` sits strictly between IN_CHUNK (150, what a correctly
    chunked call sends) and every id count this file tests with — so a
    single unchunked `.in_()` call always trips it and a chunked one never
    does, whatever the true production threshold actually was.
    """

    _URL_LIMIT = 200

    def __init__(self, rows, in_log=None):
        self._rows = rows
        self._in_log = in_log
        self._cursor = None
        self._limit = None

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self

    def in_(self, col, vals):
        vals = list(vals)
        if self._in_log is not None:
            self._in_log.append(len(vals))
        if len(vals) > self._URL_LIMIT:
            raise _URLTooLong(f"URL component 'query' too long ({len(vals)} ids)")
        wanted = set(vals)
        self._rows = [r for r in self._rows if r.get(col) in wanted]
        return self

    def gt(self, col, val):
        self._cursor = (col, val)
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        rows = self._rows
        if self._cursor:
            col, val = self._cursor
            rows = [r for r in rows if r.get(col) > val]
        rows = sorted(rows, key=lambda r: r["id"])
        if self._limit is not None:
            rows = rows[: self._limit]

        class _R:
            data = rows

        return _R()


class _FakeDB:
    """`db.table(name)` -> a fresh `_Query` over that table's full row set,
    every time — matching real PostgREST client semantics (a query builder
    is stateful; `fetch_all`/`fetch_all_in` rely on getting a NEW one per
    call, never a reused, already-filtered one)."""

    def __init__(self, tables, in_log=None):
        self._tables = tables
        self._in_log = in_log

    def table(self, name):
        return _Query(list(self._tables.get(name, [])), self._in_log)


# ── check_missing_cogs_journals ──────────────────────────────────────────────

def _invoice_fixture(n: int) -> dict:
    ledger = [
        {"id": f"L{i:04d}", "firm_id": FIRM, "client_id": CLIENT,
         "source_type": "sales_invoice", "movement_type": "sale",
         "source_id": f"INV-{i:04d}", "value_delta_paise": -1000}
        for i in range(n)
    ]
    invoices = [
        {"id": f"INV-{i:04d}", "firm_id": FIRM, "client_id": CLIENT,
         "invoice_no": f"BULK-{i:04d}"}
        for i in range(n)
    ]
    return {"inventory_stock_ledger": ledger, "client_sales_invoices": invoices}


def test_missing_cogs_check_no_longer_dies_on_a_large_invoice_count():
    n = 2 * IN_CHUNK + 10  # past one url-sized request; needs >= 3 chunks
    db = _FakeDB(_invoice_fixture(n))
    findings = rs.check_missing_cogs_journals(db, FIRM, CLIENT, {})
    # no COGS journal was posted for any of them — every one is a finding
    assert len(findings) == n
    assert {f["details"]["invoice_no"] for f in findings} == {
        f"BULK-{i:04d}" for i in range(n)
    }


def test_missing_cogs_check_matches_a_posted_journal_past_the_first_chunk():
    n = 2 * IN_CHUNK + 10
    db = _FakeDB(_invoice_fixture(n))
    # The invoice that lands in the SECOND chunk has its COGS journal posted
    # — proves the id-to-invoice_no lookup still resolves correctly past a
    # chunk boundary, not merely that the read no longer raises.
    posted_index = IN_CHUNK + 5
    entries = {
        "j1": JournalEntry(
            id="j1", entry_date="2026-04-05", client_id=CLIENT, firm_id=FIRM,
            entry_type="Journal",
            lines=(JournalLine("cogs", 1000, 0),
                   JournalLine("inv", 0, 1000)),
            reference_no=f"BULK-{posted_index:04d}-COGS",
        )
    }
    findings = rs.check_missing_cogs_journals(db, FIRM, CLIENT, entries)
    assert len(findings) == n - 1
    flagged = {f["details"]["invoice_no"] for f in findings}
    assert f"BULK-{posted_index:04d}" not in flagged


def test_missing_cogs_check_never_sends_a_single_in_list_the_gateway_would_refuse():
    n = 2 * IN_CHUNK + 10
    in_log: list = []
    db = _FakeDB(_invoice_fixture(n), in_log=in_log)
    rs.check_missing_cogs_journals(db, FIRM, CLIENT, {})
    assert in_log, "the invoice lookup never filtered by id at all"
    assert max(in_log) <= IN_CHUNK


# ── check_missing_inventory_receipt_journals ─────────────────────────────────

def _bill_fixture(n: int) -> dict:
    ledger = [
        {"id": f"L{i:04d}", "firm_id": FIRM, "client_id": CLIENT,
         "source_type": "purchase_bill", "movement_type": "purchase",
         "source_id": f"BILL-{i:04d}", "value_delta_paise": 2000}
        for i in range(n)
    ]
    bills = [
        {"id": f"BILL-{i:04d}", "firm_id": FIRM, "client_id": CLIENT,
         "bill_no": f"VEND-{i:04d}"}
        for i in range(n)
    ]
    return {"inventory_stock_ledger": ledger, "purchase_bills": bills}


def test_missing_inventory_receipt_check_no_longer_dies_on_a_large_bill_count(monkeypatch):
    monkeypatch.setattr(
        "services.phase2_journal_service.purchase_bill_journal_ref",
        lambda bill_id: f"PB-{bill_id}",
    )
    n = 2 * IN_CHUNK + 10
    db = _FakeDB(_bill_fixture(n))
    findings = rs.check_missing_inventory_receipt_journals(db, FIRM, CLIENT, {})
    assert len(findings) == n
    assert {f["details"]["bill_no"] for f in findings} == {
        f"VEND-{i:04d}" for i in range(n)
    }


def test_missing_inventory_receipt_check_matches_a_posted_journal_past_the_first_chunk(monkeypatch):
    monkeypatch.setattr(
        "services.phase2_journal_service.purchase_bill_journal_ref",
        lambda bill_id: f"PB-{bill_id}",
    )
    n = 2 * IN_CHUNK + 10
    db = _FakeDB(_bill_fixture(n))
    posted_index = IN_CHUNK + 5
    entries = {
        "j1": JournalEntry(
            id="j1", entry_date="2026-04-05", client_id=CLIENT, firm_id=FIRM,
            entry_type="Journal",
            lines=(JournalLine("inv", 2000, 0),
                   JournalLine("purch", 0, 2000)),
            reference_no=f"VEND-{posted_index:04d}-INV",
        )
    }
    findings = rs.check_missing_inventory_receipt_journals(db, FIRM, CLIENT, entries)
    assert len(findings) == n - 1
    flagged = {f["details"]["bill_no"] for f in findings}
    assert f"VEND-{posted_index:04d}" not in flagged


def test_missing_inventory_receipt_check_never_sends_a_single_in_list_the_gateway_would_refuse(monkeypatch):
    monkeypatch.setattr(
        "services.phase2_journal_service.purchase_bill_journal_ref",
        lambda bill_id: f"PB-{bill_id}",
    )
    n = 2 * IN_CHUNK + 10
    in_log: list = []
    db = _FakeDB(_bill_fixture(n), in_log=in_log)
    rs.check_missing_inventory_receipt_journals(db, FIRM, CLIENT, {})
    assert in_log, "the bill lookup never filtered by id at all"
    assert max(in_log) <= IN_CHUNK


# ── check_bank_reconciliation_discrepancies ──────────────────────────────────
# Not one of the two named in the finding, but the same defect class in the
# same file (an unbounded `.in_("reconciliation_id", session_ids)`, one
# session per bank account per month for as long as the client has been
# reconciled) — fixed alongside the other two per the brief's own scope note.

def _bank_reconciliation_fixture(n: int) -> dict:
    sessions = [
        {"id": f"REC-{i:04d}", "firm_id": FIRM, "client_id": CLIENT,
         "status": "completed", "account_no": "001",
         "period_start": "2026-01-01", "period_end": "2026-01-31",
         "completed_at": "2026-02-01T00:00:00Z", "snapshot": {"reconciled": []}}
        for i in range(n)
    ]
    return {"bank_reconciliations": sessions, "bank_transactions": []}


def test_bank_reconciliation_discrepancy_check_no_longer_dies_on_many_sessions():
    n = 2 * IN_CHUNK + 10
    db = _FakeDB(_bank_reconciliation_fixture(n))
    assert rs.check_bank_reconciliation_discrepancies(db, FIRM, CLIENT, {}) == []


def test_bank_reconciliation_discrepancy_check_never_sends_an_unbounded_in_list():
    n = 2 * IN_CHUNK + 10
    in_log: list = []
    db = _FakeDB(_bank_reconciliation_fixture(n), in_log=in_log)
    rs.check_bank_reconciliation_discrepancies(db, FIRM, CLIENT, {})
    assert in_log, "the transaction lookup never filtered by reconciliation_id"
    assert max(in_log) <= IN_CHUNK


# ── source-level guard: no raw, unbounded `.in_()` survives ──────────────────

def test_none_of_the_three_checks_hand_in_an_unbounded_id_list():
    src_cogs = inspect.getsource(rs.check_missing_cogs_journals)
    src_bills = inspect.getsource(rs.check_missing_inventory_receipt_journals)
    src_bank = inspect.getsource(rs.check_bank_reconciliation_discrepancies)

    assert "fetch_all_in(" in src_cogs
    assert "fetch_all_in(" in src_bills
    assert "fetch_all_in(" in src_bank

    assert '.in_("id", list(by_invoice' not in src_cogs
    assert '.in_("id", list(by_bill' not in src_bills
    assert '.in_("reconciliation_id", session_ids)' not in src_bank
