"""
The bank surface must read every row, not the first thousand.

WHAT THIS PINS
    PostgREST caps a response at ~1000 rows and reports nothing when it does.
    Five separate places in this codebase had already been bitten by that before
    the bank surface was checked; these are the bank ones.

    The worst is the register. Its own module docstring states the contract:

        "The running balance is computed over the WHOLE account, always, before
         any filter is applied."

    That is not a performance note, it is the reason the balance column ties to
    the bank statement. Read unpaged, the arithmetic ran over whatever the first
    thousand rows happened to be, and every balance shown was wrong — silently,
    with no error and nothing on screen to suggest it. About two years of an
    active current account is enough to cross the line.

    The queues fail differently but no better. ready_to_post, pending, posted
    and the categorisation queue each read the whole set and filter in Python,
    so truncation did not make them slow, it made them incomplete: work that was
    ready to post simply was not listed, and an empty-looking queue is
    indistinguishable from a finished one.

WHY 2,500 ROWS
    Past the 1000 cap, not a multiple of it, and spanning three pages — so the
    cursor has to advance correctly twice and the final short page has to
    terminate the walk.
"""
from __future__ import annotations

import pytest

from core.db_paging import PAGE, fetch_all


# ── A stub that truncates exactly like PostgREST ─────────────────────────────

class _Result:
    def __init__(self, data):
        self.data = data


class _Q:
    CAP = 1000

    def __init__(self, rows, store, table):
        self._rows, self._store, self._table = rows, store, table
        self._limit = None

    def select(self, *_a, **_k):
        return self

    def eq(self, c, v):
        self._rows = [r for r in self._rows if r.get(c) == v]
        return self

    def in_(self, c, vals):
        s = set(vals)
        self._rows = [r for r in self._rows if r.get(c) in s]
        return self

    def gt(self, c, v):
        self._rows = [r for r in self._rows if str(r.get(c)) > str(v)]
        return self

    def order(self, c, desc=False):
        self._rows = sorted(self._rows, key=lambda r: str(r.get(c)), reverse=desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        n = self._limit if self._limit is not None else self.CAP
        self._store.pages.append((self._table, len(self._rows[:n])))
        return _Result([dict(r) for r in self._rows[:n]])


class _DB:
    def __init__(self, data):
        self.data = data
        self.pages = []

    def table(self, name):
        return _Q(self.data.get(name, []), self, name)


FIRM, CLIENT, ACCT, STMT = "f1", "c1", "acc1", "st1"


def _txns(n, **over):
    """n statement lines, ids zero-padded so keyset order is stable."""
    rows = []
    for i in range(n):
        r = {
            "id": f"t{i:05d}", "firm_id": FIRM, "client_id": CLIENT,
            "statement_id": STMT, "transaction_date": f"2026-{(i % 12) + 1:02d}-01",
            "deposit_paise": 10_000, "withdrawal_paise": 0,
            "match_status": "unmatched", "category": None,
            "matched_entity_id": None, "needs_review": False,
            "posted_journal_id": None, "posted_at": None, "account_id": None,
            "description": f"NEFT {i}", "reconciliation_id": None,
        }
        r.update(over)
        rows.append(r)
    return rows


# ── The helper itself ────────────────────────────────────────────────────────

def test_the_stub_truncates_or_none_of_this_means_anything():
    db = _DB({"bank_transactions": _txns(2500)})
    got = db.table("bank_transactions").select("*").eq("firm_id", FIRM).execute()

    assert len(got.data) == 1000, "the fake must cap like db-max-rows"


def test_fetch_all_returns_every_row():
    db = _DB({"bank_transactions": _txns(2500)})
    got = fetch_all(lambda: db.table("bank_transactions").select("*").eq("firm_id", FIRM))

    assert len(got) == 2500
    assert len({r["id"] for r in got}) == 2500, "rows duplicated across pages"


def test_fetch_all_walks_three_pages_and_stops():
    db = _DB({"bank_transactions": _txns(2500)})
    stats: dict = {}
    fetch_all(lambda: db.table("bank_transactions").select("*").eq("firm_id", FIRM),
              stats=stats)

    assert [n for (_t, n) in db.pages] == [1000, 1000, 500]
    assert stats == {"pages": 3, "rows": 2500}


def test_fetch_all_gives_up_loudly_if_the_cursor_cannot_advance(caplog):
    """A make_query that ignores the cursor would loop forever. Bounded, and it
    says so — a hang in place of a wrong answer is not an improvement."""
    import logging
    from core import db_paging

    class _Stuck(_Q):
        def gt(self, c, v):     # cursor deliberately ignored
            return self

    db = _DB({"bank_transactions": _txns(2500)})
    db.table = lambda name: _Stuck(db.data.get(name, []), db, name)

    with caplog.at_level(logging.ERROR, logger="caflow.db.paging"):
        monkey = db_paging.MAX_PAGES
        db_paging.MAX_PAGES = 5
        try:
            fetch_all(lambda: db.table("bank_transactions").select("*"), label="stuck")
        finally:
            db_paging.MAX_PAGES = monkey

    assert any("page cap" in r.getMessage() for r in caplog.records), \
        "a stuck cursor must be reported, not silently truncated all over again"


def test_page_size_matches_the_cap_it_exists_to_defeat():
    assert PAGE == _Q.CAP


def test_every_page_asks_for_an_explicit_limit():
    """Caught by mutation testing, not by foresight: removing `.limit(PAGE)`
    broke none of the tests above, because the stub's default cap happens to
    equal PAGE — exactly as the real server's does today.

    It matters anyway. Without an explicit limit, a full page means "whatever
    the server chose to return", and the short-page stop signal then depends on
    a server setting no code here can see. Lower `db-max-rows` below PAGE and
    the first page comes back short, reads as end-of-data, and truncates in
    silence — this module's own bug, wearing its fix as a disguise.

    So the mechanism is pinned, not just the outcome."""
    limits: list[int | None] = []

    class _Recording(_Q):
        def limit(self, n):
            limits.append(n)
            return super().limit(n)

        def execute(self):
            if self._limit is None:
                limits.append(None)
            return super().execute()

    db = _DB({"bank_transactions": _txns(2500)})
    db.table = lambda name: _Recording(db.data.get(name, []), db, name)
    fetch_all(lambda: db.table("bank_transactions").select("*").eq("firm_id", FIRM))

    assert limits, "no page issued a query at all"
    assert all(n == PAGE for n in limits), (
        f"every page must request exactly PAGE rows; got {limits}")


# ── The register: the one that produces wrong money ──────────────────────────

def test_the_register_balance_covers_the_whole_account():
    """The module's stated contract. With 2,500 deposits of ₹100 each and a zero
    opening balance, the closing balance is ₹2,50,000 — 25,000,000 paise. Read
    unpaged it came to a tenth of that and looked entirely plausible."""
    from services.bank_register_service import bank_register_service as svc

    db = _DB({
        "bank_accounts": [{"id": ACCT, "firm_id": FIRM, "client_id": CLIENT,
                           "opening_balance_paise": 0, "currency": "INR",
                           "bank_name": "HDFC", "account_no": "1234"}],
        "bank_statements": [{"id": STMT, "firm_id": FIRM, "bank_account_id": ACCT}],
        "bank_transactions": _txns(2500),
        "bank_reconciliations": [],
    })
    rows = svc._txns(db, FIRM, ACCT)

    assert len(rows) == 2500, f"the register read {len(rows)} of 2500 lines"
    # Integer paise throughout — never float (CLAUDE.md).
    total = sum(int(r["deposit_paise"]) - int(r["withdrawal_paise"]) for r in rows)
    assert total == 25_000_000, f"closing balance would be {total} paise, not 25,000,000"
    assert isinstance(total, int)


# ── The queues: the ones that hide work ──────────────────────────────────────

def test_the_categorisation_queue_lists_every_unmatched_line():
    from services.bank_matching_service import bank_matching_service as svc

    db = _DB({"bank_transactions": _txns(2500), "bank_matching_rules": []})
    got = svc.queue(db, FIRM, CLIENT, "unmatched")

    assert len(got) == 2500, f"queue showed {len(got)} of 2500 — 1500 invisible"


def test_the_queue_is_still_in_date_order_after_paging():
    """Paging is keyset over id; display order is by date and must survive it."""
    from services.bank_matching_service import bank_matching_service as svc

    db = _DB({"bank_transactions": _txns(2500), "bank_matching_rules": []})
    dates = [t["transaction_date"] for t in svc.queue(db, FIRM, CLIENT, "unmatched")]

    assert dates == sorted(dates), "paging lost the date ordering"


@pytest.mark.parametrize("queue,over,expect", [
    ("ready_to_post", {"category": "Bank Charges"}, 2500),
    ("pending",       {"posted_journal_id": "j1"},  2500),
    ("posted",        {"posted_at": "2026-04-01T00:00:00Z"}, 2500),
])
def test_the_posting_queues_list_every_eligible_line(queue, over, expect):
    from services.bank_posting_service import bank_posting_service as svc

    db = _DB({"bank_transactions": _txns(2500, **over), "bank_matching_rules": []})
    got = getattr(svc, queue)(db, FIRM, CLIENT)

    assert len(got) == expect, f"{queue} listed {len(got)} of {expect}"


def test_posted_is_still_newest_first():
    """It was `.order(transaction_date, desc=True)`; keyset paging is ascending,
    so the reversal has to be reinstated or the newest work drops off the end of
    whatever the UI shows first."""
    from services.bank_posting_service import bank_posting_service as svc

    db = _DB({"bank_transactions": _txns(2500, posted_at="2026-04-01T00:00:00Z"),
              "bank_matching_rules": []})
    dates = [t["transaction_date"] for t in svc.posted(db, FIRM, CLIENT)]

    assert dates == sorted(dates, reverse=True), "posted is no longer newest-first"


# ── Reconciliation ───────────────────────────────────────────────────────────

def test_reconciliation_sees_every_posted_statement_line():
    """Truncated, it ties out against part of the statement and reports the rest
    as a difference — a reconciliation that cannot reconcile.

    It filters to POSTED on purpose (it ties out the BOOKS, unlike the register
    which shows the BANK), so every fixture row carries a journal id."""
    from services.bank_reconciliation_service import bank_reconciliation_service as svc

    db = _DB({
        "bank_statements": [{"id": STMT, "firm_id": FIRM, "bank_account_id": ACCT}],
        "bank_transactions": _txns(2500, posted_journal_id="j1"),
    })
    rows = svc._posted_account_txns(db, FIRM, ACCT)

    assert len(rows) == 2500, f"reconciliation read {len(rows)} of 2500"


def test_reconciliation_still_excludes_unposted_lines():
    """The paging change must not quietly widen what reconciliation counts."""
    from services.bank_reconciliation_service import bank_reconciliation_service as svc

    rows = _txns(1500, posted_journal_id="j1") + _txns(1200)
    for i, r in enumerate(rows):          # unique ids across the two batches
        r["id"] = f"t{i:05d}"
    db = _DB({
        "bank_statements": [{"id": STMT, "firm_id": FIRM, "bank_account_id": ACCT}],
        "bank_transactions": rows,
    })

    assert len(svc._posted_account_txns(db, FIRM, ACCT)) == 1500
