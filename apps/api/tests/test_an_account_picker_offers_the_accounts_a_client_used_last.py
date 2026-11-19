"""The account picker on a journal line and on a bill line puts the accounts the client used last at the top (POST-A-155)."""
from __future__ import annotations

import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from domain import account_recent
from domain.account_recent import read_recent_accounts, recent_account_ids

pytestmark = pytest.mark.usefixtures("dev_header_auth")
ROOT = pathlib.Path(__file__).resolve().parents[3]


class _Query:
    """A PostgREST chain over in-memory rows, applied the way the database applies it: every filter, then the order,
    then the limit. It has no `gt`, so the shared pager reads it once, as it reads every such double."""

    def __init__(self, db, name, rows):
        self.db, self.name, self.rows, self.filters, self.orders, self.cap = db, name, rows, [], [], None

    def select(self, cols):
        self.db.log.append((self.name, "select", cols))
        return self

    def eq(self, col, val):
        self.db.log.append((self.name, "eq", col, val))
        self.filters.append(lambda r: r.get(col) == val)
        return self

    def is_(self, col, val):
        self.db.log.append((self.name, "is_", col, val))
        self.filters.append(lambda r: r.get(col) is None)
        return self

    def in_(self, col, vals):
        vals = {str(v) for v in vals}
        self.db.log.append((self.name, "in_", col, tuple(sorted(vals))))
        self.filters.append(lambda r: str(r.get(col)) in vals)
        return self

    def order(self, col, desc=False):
        self.db.log.append((self.name, "order", col, desc))
        self.orders.append((col, desc))
        return self

    def limit(self, n):
        self.db.log.append((self.name, "limit", n))
        self.cap = n
        return self

    def execute(self):
        rows = [r for r in self.rows if all(f(r) for f in self.filters)]
        for col, desc in reversed(self.orders):
            rows.sort(key=lambda r: r[col], reverse=desc)
        if self.cap is not None:
            rows = rows[: self.cap]
        return type("R", (), {"data": rows})()


class _DB:
    def __init__(self, **tables):
        self.log, self.tables = [], tables

    def table(self, name):
        return _Query(self, name, self.tables.get(name, []))


def _entry(i, *, source="manual", client="cl-1", firm="firm-1", deleted=False):
    return {"id": f"e{i:04d}", "client_id": client, "firm_id": firm, "source_type": source,
            "deleted_at": "2026-11-01" if deleted else None, "created_at": f"2026-01-01T00:00:00.{i:06d}+00:00"}


def _jl(entry, account, order):
    return {"id": f"l-{entry}-{order}", "journal_entry_id": entry, "account_id": account, "line_order": order}


def test_each_account_once_newest_document_first_then_its_lines_in_order():
    lines = [_jl("e2", "acc-b", 2), _jl("e2", "acc-a", 1), _jl("e1", "acc-c", 1), _jl("e1", "acc-a", 2),
             _jl("e9", "acc-not-ours", 1), {"id": "x", "journal_entry_id": "e1", "account_id": None, "line_order": 3}]
    assert recent_account_ids(["e2", "e1"], lines, "journal_entry_id", "account_id", "line_order") == ["acc-a", "acc-b", "acc-c"]
    assert recent_account_ids(["e2", "e1"], lines, "journal_entry_id", "account_id", "line_order", limit=1) == ["acc-a"]
    assert recent_account_ids([], lines, "journal_entry_id", "account_id", "line_order") == []


def test_a_journal_line_reads_the_clients_own_manual_journals_newest_first_and_bounded():
    entries = [_entry(1), _entry(2), _entry(3, source="sales_invoice"), _entry(4, deleted=True),
               _entry(5, client="cl-2"), _entry(6, firm="firm-2")]
    lines = [_jl("e0001", "acc-old", 1), _jl("e0002", "acc-new", 1), _jl("e0003", "acc-receivables", 1),
             _jl("e0004", "acc-deleted", 1), _jl("e0005", "acc-other-client", 1), _jl("e0006", "acc-other-firm", 1)]
    db = _DB(journal_entries=entries, journal_lines=lines)
    out = read_recent_accounts(db, "journal", "firm-1", "cl-1")
    assert out == {"ids": ["acc-new", "acc-old"], "documents_read": 2, "window": account_recent.WINDOW}
    for call in (("journal_entries", "eq", "firm_id", "firm-1"), ("journal_entries", "eq", "client_id", "cl-1"),
                 ("journal_entries", "eq", "source_type", "manual"), ("journal_entries", "is_", "deleted_at", "null"),
                 ("journal_entries", "order", "created_at", True), ("journal_entries", "order", "id", True),
                 ("journal_entries", "limit", account_recent.WINDOW)):
        assert call in db.log, call
    # The lines are asked for by the ids the scoped read returned, and by nothing wider.
    assert ("journal_lines", "in_", "journal_entry_id", ("e0001", "e0002")) in db.log


def test_a_bill_line_reads_the_expense_accounts_of_the_clients_live_bills_that_were_not_carried_over():
    bills = [
        {"id": "b1", "firm_id": "firm-1", "client_id": "cl-1", "is_opening": False, "deleted_at": None, "created_at": "2026-04-01"},
        {"id": "b2", "firm_id": "firm-1", "client_id": "cl-1", "is_opening": False, "deleted_at": None, "created_at": "2026-04-02"},
        {"id": "b3", "firm_id": "firm-1", "client_id": "cl-1", "is_opening": True, "deleted_at": None, "created_at": "2026-04-03"},
        {"id": "b4", "firm_id": "firm-1", "client_id": "cl-1", "is_opening": False, "deleted_at": "x", "created_at": "2026-04-04"},
    ]
    lines = [{"id": "l1", "bill_id": "b1", "expense_account_id": "rent", "sort_order": 0},
             {"id": "l2", "bill_id": "b2", "expense_account_id": "power", "sort_order": 1},
             {"id": "l3", "bill_id": "b2", "expense_account_id": "rent", "sort_order": 0},
             {"id": "l4", "bill_id": "b3", "expense_account_id": "opening", "sort_order": 0},
             {"id": "l5", "bill_id": "b4", "expense_account_id": "deleted", "sort_order": 0}]
    db = _DB(purchase_bills=bills, purchase_bill_lines=lines)
    out = read_recent_accounts(db, "bill", "firm-1", "cl-1")
    assert out["ids"] == ["rent", "power"]
    assert ("purchase_bills", "eq", "is_opening", False) in db.log
    with pytest.raises(ValueError):
        read_recent_accounts(db, "invoice", "firm-1", "cl-1")


def test_a_client_with_no_documents_reads_no_lines():
    db = _DB(journal_entries=[], journal_lines=[_jl("e1", "a", 1)])
    assert read_recent_accounts(db, "journal", "firm-1", "cl-1")["ids"] == []
    assert not any(c[0] == "journal_lines" for c in db.log)


def test_the_route_answers_ids_asks_the_clients_scope_and_names_which_picker():
    from main import app
    c = TestClient(app)
    h = {"X-User-Email": "p@test.com", "X-User-Role": "partner", "X-Firm-ID": "firm-1"}
    for used_on in ("journal", "bill"):
        r = c.get("/api/accounting/accounts/recent", params={"client_id": "client-123", "used_on": used_on}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True and r.json()["data"]["ids"] == []
    assert c.get("/api/accounting/accounts/recent", params={"client_id": "client-123"}, headers=h).status_code == 422
    assert c.get("/api/accounting/accounts/recent", params={"used_on": "bill"}, headers=h).status_code == 422
    assert c.get("/api/accounting/accounts/recent",
                 params={"client_id": "client-123", "used_on": "invoice"}, headers=h).status_code == 422


def test_the_route_asks_accounting_read():
    from routers import accounting
    import inspect
    dep = inspect.signature(accounting.recent_accounts).parameters["current_user"].default
    assert getattr(dep.dependency, "__name__", "") == "rbac_accounting_read"


def test_the_journal_and_bill_line_pickers_take_the_recent_accounts():
    web = ROOT / "apps/web"
    for rel, read in (("components/journal/JournalEditor.tsx", "recentJournalAccounts"),
                      ("components/purchases/PurchaseBillEditor.tsx", "recentBillAccounts")):
        src = (web / rel).read_text(encoding="utf-8")
        pickers = [src[m.start(): src.index("/>", m.end()) + 2] for m in re.finditer(r"<AccountLookup\b", src)]
        assert pickers, f"{rel}: no account picker found, the scan has gone blind"
        assert all("recent={" in p for p in pickers), f"{rel}: an account picker without recent="
        assert f"api.accounting.{read}" in src, f"{rel} does not read the recent accounts of its own kind"
