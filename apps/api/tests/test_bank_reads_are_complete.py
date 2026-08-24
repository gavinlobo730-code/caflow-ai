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

import re

import pytest

from core.db_paging import PAGE, fetch_all


# ── A stub that truncates exactly like PostgREST ─────────────────────────────
# ── PostgREST or() ────────────────────────────────────────────────────────────
# The banded candidate fetch sends `or(and(col.gte.LO,col.lte.HI),and(…))` — the
# exact union of every row's amount band, in one query. A naive split on "," tears
# the groups apart and quietly matches nothing, which is indistinguishable from
# "no candidates", so this parses paren depth properly and REFUSES what it does
# not understand.
_OR_OPS = {"eq", "neq", "gt", "gte", "lt", "lte", "is", "ilike", "like"}


def _pg_ilike(value, pattern) -> bool:
    """PostgREST's or()-expression LIKE: `*` is the wildcard (not `%`), and a
    backslash escapes a literal `%`, `_` or `*`.

    Written out rather than reusing the plain ilike matcher, which translates
    `%` and would re.escape a `*` into a literal — so `*foo*` matched nothing
    and every search test would have passed by finding no rows."""
    if value is None:
        return False
    out, i = [], 0
    p = str(pattern)
    while i < len(p):
        ch = p[i]
        if ch == "\\" and i + 1 < len(p):
            out.append(re.escape(p[i + 1])); i += 2; continue
        if ch == "*":
            out.append(".*")
        elif ch == "%":
            out.append(".*")
        elif ch == "_":
            out.append(".")
        else:
            out.append(re.escape(ch))
        i += 1
    return re.match("^" + "".join(out) + "$", str(value), re.IGNORECASE) is not None


def _split_top(expr):
    out, depth, cur = [], 0, []
    for ch in expr:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur)); cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur))
    return [t.strip() for t in out if t.strip()]


def _coerce(v):
    if v == "null":
        return None
    return int(v) if v.lstrip("-").isdigit() else v


def _or_term(row, term):
    if term.startswith("and(") and term.endswith(")"):
        return all(_or_term(row, t) for t in _split_top(term[4:-1]))
    if term.startswith("or(") and term.endswith(")"):
        return any(_or_term(row, t) for t in _split_top(term[3:-1]))
    parts = term.split(".", 2)
    if len(parts) != 3:
        raise NotImplementedError(f"fake or() term not understood: {term!r}")
    c, op, v = parts
    if op not in _OR_OPS:
        raise NotImplementedError(f"fake or() operator not implemented: {op!r}")
    got, want = row.get(c), _coerce(v)
    if op in ("ilike", "like"):
        return _pg_ilike(got, want)
    if op == "is":
        return got is want
    if op == "eq":
        return got == want
    if op == "neq":
        return got != want
    if got is None:
        return False
    return {"gt": got > want, "gte": got >= want,
            "lt": got < want, "lte": got <= want}[op]


def _or_match(row, expr):
    return any(_or_term(row, t) for t in _split_top(expr))


class _Result:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _Q:
    CAP = 1000

    def __init__(self, rows, store, table):
        self._rows, self._store, self._table = rows, store, table
        self._limit = None
        self._range = None
        self._count = None
        self._order = []
        self._negate = False

    def select(self, *_a, count=None, **_k):
        self._count = count
        return self

    # `.not_` negates the NEXT predicate only, as PostgREST does.
    @property
    def not_(self):
        self._negate = True
        return self

    def _keep(self, pred):
        neg, self._negate = self._negate, False
        keep = (lambda r: not pred(r)) if neg else pred
        self._rows = [r for r in self._rows if keep(r)]
        return self

    def eq(self, c, v):
        return self._keep(lambda r: r.get(c) == v)

    def neq(self, c, v):
        return self._keep(lambda r: r.get(c) != v)

    def is_(self, c, _null):
        return self._keep(lambda r: r.get(c) is None)

    def in_(self, c, vals):
        s = set(vals)
        return self._keep(lambda r: r.get(c) in s)

    def gt(self, c, v):
        return self._keep(lambda r: str(r.get(c)) > str(v))

    def order(self, c, desc=False):
        # Deferred and ACCUMULATED. Sorting eagerly made `.order(a).order(b)`
        # mean "sorted by b", which is the opposite of ORDER BY a, b — and the
        # tiebreak is what makes a paged queue stable.
        self._order.append((c, desc))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, a, b):
        self._range = (a, b)
        return self

    def or_(self, expr):
        return self._keep(lambda r: _or_match(r, expr))

    def execute(self):
        rows = self._rows
        for c, desc in reversed(self._order):
            rows = sorted(rows, key=lambda r, c=c: str(r.get(c)), reverse=desc)
        total = len(rows)
        if self._range is not None:
            rows = rows[self._range[0]: self._range[1] + 1]
        n = self._limit if self._limit is not None else self.CAP
        rows = rows[:n]
        self._store.pages.append((self._table, len(rows)))
        return _Result([dict(r) for r in rows], count=(total if self._count else None))


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
