"""
Reading which accounts hold unbilled dues has to see a FIRM-LEVEL account
(client_id IS NULL), not only a row scoped to the one client being reported on
— the READ half of the fix `test_unbilled_dues_marking_reaches_firm_level_accounts.py`
made for the WRITE half.

CLAUDE.md: "A chart_of_accounts row with client_id IS NULL is a firm-level
account and is allowed on any of that firm's entries." Marking such an account
(services/ageing_schedule_service.classify(), target == "account") was fixed in
commit 862bf886 to `.or_(f"client_id.eq.{client_id},client_id.is.null")` — but
`_fetch_unbilled`, the function that reads the marking back for the Schedule
III ageing note's fallback path (mock mode / local dev, when the SQL aggregate
public.schedule_iii_ageing is unavailable), still filtered
`.eq("client_id", client_id)`, which a NULL column never satisfies in Postgres.
So a firm-level account, once correctly marked, was invisible to the very
disclosure the marking exists for: the note reported the client as having no
unbilled dues (or, worse, an unreviewed gap) however carefully the CA had
classified their shared chart of accounts.

The fake below models exactly the two predicates the fixed query issues (`eq`
on firm_id, `or_` for the client scope), the same minimal shape
test_unbilled_dues_marking_reaches_firm_level_accounts.py uses for the write
side and tests/test_bank_account_first_coding.py uses for the identical
PostgREST fallback-account pattern elsewhere in this codebase. It has no
`.gt`/`.order`/`.limit`, so `_paginate_all` takes its single-execute fallback
branch rather than its keyset-paging one — irrelevant to what this fix defends.
"""
from datetime import date

from services.ageing_schedule_service import _fetch_unbilled

FIRM = "firm-1"
CLIENT = "client-1"
OTHER_CLIENT = "client-2"


class _Resp:
    def __init__(self, data):
        self.data = data


class _AccountsQuery:
    """Enough PostgREST to run _fetch_unbilled's chart_of_accounts select for
    real: select, eq, or_, not_.is_, execute. `or_` handles only the one
    expression this path builds and raises on anything else — a double that
    quietly matched nothing would make a lost read indistinguishable from a
    correct one."""

    def __init__(self, rows):
        self._rows = rows
        self._pred = []

    def select(self, *_a, **_k):
        return self

    def eq(self, k, v):
        self._pred.append(lambda r, k=k, v=v: r.get(k) == v)
        return self

    def or_(self, expr):
        expect = f"client_id.eq.{CLIENT},client_id.is.null"
        if expr != expect:
            raise AssertionError(f"the fake does not model or_({expr!r})")
        self._pred.append(lambda r: r.get("client_id") in (None, CLIENT))
        return self

    @property
    def not_(self):
        outer = self

        class _Not:
            def is_(self, col, val):
                if val != "null":
                    raise AssertionError(f"the fake does not model not_.is_({col!r}, {val!r})")
                outer._pred.append(lambda r: r.get(col) is not None)
                return outer

        return _Not()

    def execute(self):
        return _Resp([r for r in self._rows if all(p(r) for p in self._pred)])


class _ReviewQuery:
    """The schedule_iii_unbilled_reviews lookup _fetch_unbilled also issues;
    answering "not reviewed" (empty) is fine for what these tests assert — the
    marked-account list, not the review gate."""

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return _Resp([])


class _LinesQuery:
    """The journal_entries!inner(journal_lines) fetch _fetch_unbilled issues
    once an account is marked. Every account in these tests has no posting, so
    this always answers empty — what these tests assert is which accounts get
    THIS FAR at all, not the balance arithmetic (that is
    domain/reporting/ageing.py's job and tests/test_schedule_iii_ageing_parity_pg.py's
    to pin)."""

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def is_(self, *_a, **_k):
        return self

    def lte(self, *_a, **_k):
        return self

    def in_(self, *_a, **_k):
        return self

    def execute(self):
        return _Resp([])


class FakeDB:
    def __init__(self, accounts):
        self._accounts = accounts

    def table(self, name):
        if name == "chart_of_accounts":
            return _AccountsQuery(self._accounts)
        if name == "schedule_iii_unbilled_reviews":
            return _ReviewQuery()
        if name == "journal_entries":
            return _LinesQuery()
        raise AssertionError(f"unexpected table: {name!r}")


def _account(id, *, client_id, side="receivable"):
    return dict(id=id, firm_id=FIRM, client_id=client_id,
                account_code="1801", account_name="Accrued Income",
                unbilled_dues_side=side)


def test_a_firm_level_account_is_seen():
    db = FakeDB([_account("acc-firm-wide", client_id=None)])

    marked, lines, reviewed_on = _fetch_unbilled(db, FIRM, CLIENT, date(2026, 3, 31))

    assert [a.account_id for a in marked] == ["acc-firm-wide"], (
        "a firm-level (client_id IS NULL) account must be visible to every "
        "one of the firm's clients — the old .eq('client_id', client_id) "
        "filter never matches a NULL column")


def test_a_client_scoped_account_is_still_seen():
    db = FakeDB([_account("acc-own", client_id=CLIENT)])

    marked, _lines, _reviewed_on = _fetch_unbilled(db, FIRM, CLIENT, date(2026, 3, 31))

    assert [a.account_id for a in marked] == ["acc-own"]


def test_another_clients_account_stays_out():
    """Tenancy is not loosened by this fix — only the firm-wide (NULL) case is
    added to what one client's note may see."""
    db = FakeDB([_account("acc-other-client", client_id=OTHER_CLIENT)])

    marked, _lines, _reviewed_on = _fetch_unbilled(db, FIRM, CLIENT, date(2026, 3, 31))

    assert marked == []
