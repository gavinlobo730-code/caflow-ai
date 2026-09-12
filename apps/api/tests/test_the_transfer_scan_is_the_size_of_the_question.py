"""
BANK-15 — transfer detection reads the dates in question, not the ledger.

`bank_transfer_service.detect_pairs` used to read the client's newest 1,000
transactions on every call, and `bank_entry_service.redraft` calls it once per
chunk of 100 lines. Two things were wrong with that and only one of them is
speed.

THE WRONG ANSWER. `redraft` picks its chunks in `transaction_date` order,
OLDEST FIRST. So on a client past a thousand lines the index it consulted
covered the NEWEST thousand while the chunk it was drafting was the oldest:
every old line was told, with no caveat, that it had no transfer counterpart.
The cap was also silent — a thousand rows and a thousand-of-forty-thousand come
back looking identical, which is the truncation `core/db_paging` exists to end.

THE SPEED. One full-ledger scan per hundred-line chunk is quadratic in the
statement, and `jobs/bank_trusted_rules_job` drives that loop unattended.

The fix is one idea: the caller says which rows it wants an answer FOR, and
`transfers.scan_window` turns those dates into the range a scan has to cover —
one window for the counterpart, a second for whatever competes with it. Nothing
is hoisted above the chunk loop, which is the other way to stop the quadratic
and would have made one failed scan cost every remaining chunk.
"""
from __future__ import annotations

from datetime import date

import pytest

from domain.banking.transfers import DEFAULT_WINDOW_DAYS, SCAN_PADDING_WINDOWS, scan_window
import services.bank_transfer_service as bts
from services.bank_transfer_service import bank_transfer_service
from services.bank_entry_service import bank_entry_service
from tests.test_bank_matching import FakeDB, _Q, FIRM, CLIENT

ACC_A, ACC_B = "ba-hdfc", "ba-icici"


class _ScanQ(_Q):
    """`_Q` that records what a `bank_transactions` select actually asked for.

    The bounds matter as much as the row count: a scan that read everything and
    then filtered in Python would pass a count assertion and still make the
    cross-region round trip this finding is about.
    """

    def __init__(self, store, table, scans):
        super().__init__(store, table)
        self._scans, self._bounds = scans, []

    def gt(self, k, v):                       # core/db_paging's keyset cursor
        self._bounds.append(("gt", k, v))
        return self._add(lambda r, k=k, v=v: r.get(k) is not None and r[k] > v)

    def gte(self, k, v):
        self._bounds.append(("gte", k, v))
        return super().gte(k, v)

    def lte(self, k, v):
        self._bounds.append(("lte", k, v))
        return super().lte(k, v)

    def execute(self):
        res = super().execute()
        if self.table == "bank_transactions" and self._op == "select":
            self._scans.append({"bounds": list(self._bounds),
                                "returned": len(res.data or [])})
        return res


class ScanDB(FakeDB):
    def __init__(self):
        super().__init__()
        self.scans: list[dict] = []

    def table(self, name):
        return _ScanQ(self.store, name, self.scans)


def _statements(db):
    db.store["bank_statements"] = [
        {"id": f"st-{ACC_A}", "firm_id": FIRM, "client_id": CLIENT, "bank_account_id": ACC_A},
        {"id": f"st-{ACC_B}", "firm_id": FIRM, "client_id": CLIENT, "bank_account_id": ACC_B},
    ]


def _seed(db, id_, txn_date, *, debit=0, credit=0, account=ACC_A):
    row = {"id": id_, "firm_id": FIRM, "client_id": CLIENT, "transaction_date": txn_date,
           "description": f"TXN {id_}", "debit_paise": debit, "credit_paise": credit,
           "balance_paise": 0, "statement_id": f"st-{account}", "bank_account_id": account,
           "match_status": "unmatched", "category": None, "matched_entity_id": None,
           "posted_journal_id": None, "posted_at": None, "transfer_pair_id": None,
           "transfer_is_primary": None, "entry_state": "needs_you", "drafted_at": None,
           "account_id": None, "has_splits": False, "needs_review": False}
    db.store.setdefault("bank_transactions", []).append(row)
    return row


def _found(pairs):
    return [(p.primary_id, p.counterpart_id) for p in pairs]


# ── scan_window, the arithmetic on its own ────────────────────────────────────

def test_the_window_reaches_two_windows_either_side():
    lo, hi = scan_window([{"transaction_date": "2026-06-10"}])
    reach = DEFAULT_WINDOW_DAYS * SCAN_PADDING_WINDOWS
    assert reach == 8
    assert (lo, hi) == (date(2026, 6, 2), date(2026, 6, 18))


def test_the_window_spans_every_row_it_is_given():
    lo, hi = scan_window([{"transaction_date": "2026-06-10"},
                          {"transaction_date": "2026-06-01"},
                          {"transaction_date": "2026-06-20"}])
    assert (lo, hi) == (date(2026, 5, 24), date(2026, 6, 28))


def test_rows_with_no_readable_date_give_no_window():
    assert scan_window([]) == (None, None)
    assert scan_window([{"transaction_date": None}, {}]) == (None, None)


# ── the wrong answer ──────────────────────────────────────────────────────────

def test_a_transfer_older_than_a_thousand_lines_is_still_found():
    """The defect in its own shape. Under the newest-1,000 scan these two lines
    were outside the index every chunk consulted, so the oldest lines on a busy
    client were told they had no counterpart."""
    db = ScanDB()
    _statements(db)
    for i in range(1050):
        _seed(db, f"n{i:04d}", f"2026-{(i % 12) + 1:02d}-15", debit=1_000 + i)
    out = _seed(db, "old-out", "2025-04-10", debit=5_00_000_00, account=ACC_A)
    _seed(db, "old-in", "2025-04-10", credit=5_00_000_00, account=ACC_B)

    assert _found(bank_transfer_service.detect_pairs(db, FIRM, CLIENT, around=[out])) \
        == [("old-out", "old-in")]


def test_with_no_rows_named_the_scan_is_the_whole_client_and_is_paged():
    """No `around` means the whole client, and the whole client means ALL of
    it: `core/db_paging.fetch_all`, not a cap that says "no transfer" about
    lines it never looked at."""
    db = ScanDB()
    _statements(db)
    for i in range(1200):
        _seed(db, f"n{i:04d}", "2026-01-15", debit=1_000 + i)
    _seed(db, "out", "2026-01-15", debit=7_00_000_00, account=ACC_A)
    _seed(db, "in", "2026-01-15", credit=7_00_000_00, account=ACC_B)

    assert _found(bank_transfer_service.detect_pairs(db, FIRM, CLIENT)) == [("out", "in")]
    assert len(db.scans) > 1, "1,202 rows cannot come back in one page of 1,000"


# ── the speed ─────────────────────────────────────────────────────────────────

def test_the_scan_asks_the_database_for_the_window_and_not_for_everything():
    db = ScanDB()
    _statements(db)
    for i in range(200):
        _seed(db, f"n{i:04d}", "2026-01-15", debit=1_000 + i)
    row = _seed(db, "q", "2026-06-10", debit=999)
    db.scans.clear()

    bank_transfer_service.detect_pairs(db, FIRM, CLIENT, around=[row])

    bounds = [b for s in db.scans for b in s["bounds"]]
    assert ("gte", "transaction_date", "2026-06-02") in bounds
    assert ("lte", "transaction_date", "2026-06-18") in bounds
    # One row is in the window; the two hundred in January are not, and they
    # must not have crossed the wire to be discarded in Python.
    assert sum(s["returned"] for s in db.scans) == 1


def test_the_redraft_scopes_the_scan_to_the_chunk_it_is_drafting(monkeypatch):
    """The seam. `_pairs_by_txn` is rebuilt per chunk — deliberately, since a
    windowed scan is already proportional to the chunk — so what makes it cheap
    is that it is told which rows the chunk holds."""
    seen: dict = {}

    def _record(db, firm_id, client_id, *a, around=None, **k):
        seen["around"] = around
        return []

    monkeypatch.setattr(bts.bank_transfer_service, "detect_pairs", _record)
    db = ScanDB()
    _statements(db)
    a = _seed(db, "a", "2026-06-10", debit=100)
    b = _seed(db, "b", "2026-06-11", credit=100, account=ACC_B)

    bank_entry_service.redraft(db, FIRM, CLIENT, limit=100)

    assert [r["id"] for r in (seen.get("around") or [])] == [a["id"], b["id"]]
