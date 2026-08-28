"""
Every document status the bank undo can write must be one the DATABASE accepts.

WHAT WAS WRONG
    bank_posting_service._unsettle set a settled document back to

        status = "unpaid" if new_paid <= 0 else ...

    and no table has ever had an "unpaid" state:

        client_sales_invoices   draft | issued   | partially_paid | paid | cancelled
        purchase_bills          draft | received | partially_paid | paid | cancelled

    So undoing a bank line that had FULLY paid off an invoice or bill violated
    the status CHECK and the request came back as a bare 500. Undo had never
    worked for a line that settled a document — the single-row button failed
    the same way; undoing five at once is only what made it visible.

    It was worse than a failed click. The journal reversal is written BEFORE the
    unsettle, so each failure left a balanced reversal on the books with the
    bank line still reading "posted" and the invoice still reading "paid": the
    GL said the customer owed the money again while the sub-ledger said they had
    paid. Five documents on a live firm ended up in that state.

WHY 7,000 MOCK-MODE TESTS PASSED OVER IT
    The FakeDB in test_bank_undo.py stores whatever dict it is handed. It has no
    CHECK constraints, no column types and no triggers, so "unpaid" was accepted
    happily. Two tests in that file went further and ASSERTED "unpaid" — they
    did not merely miss the bug, they pinned it in place.

    That is the whole reason this file exists and is a _pg test. It asks the
    REAL schema what the column allows, and drives the REAL function to see what
    it emits. A fake cannot answer either question.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

import pytest

import services.bank_posting_service as bps
from services.bank_posting_service import bank_posting_service as svc

_HARNESS_PG = os.environ.get("HARNESS_PG")
pytestmark = pytest.mark.skipif(
    not _HARNESS_PG or shutil.which("psql") is None,
    reason="status-vocabulary proof requires HARNESS_PG + psql",
)

FIRM, CLIENT = "firm-1", "client-1"


def _allowed_statuses(dsn: str, table: str) -> set[str]:
    """The values the real CHECK constraint permits, read out of the catalog."""
    sql = (
        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
        "JOIN pg_class r ON r.oid = c.conrelid "
        "JOIN pg_namespace n ON n.oid = r.relnamespace "
        f"WHERE n.nspname='public' AND r.relname='{table}' AND c.contype='c' "
        "AND pg_get_constraintdef(c.oid) ILIKE '%status%';"
    )
    out = subprocess.run(["psql", dsn, "-tA", "-X", "-q", "-c", sql],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    defs = out.stdout.strip()
    assert defs, f"no status CHECK found on {table} — this test would prove nothing"
    return set(re.findall(r"'([a-z_]+)'::text", defs))


# ── a fake that is ONLY a recorder; the schema is the authority here ─────────

class _Resp:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, store, table):
        self.s, self.t, self.op, self.payload, self.f = store, table, "select", None, []

    def select(self, *_a, **_k): self.op = "select"; return self
    def update(self, p): self.op, self.payload = "update", p; return self
    def eq(self, k, v): self.f.append((k, v)); return self
    def limit(self, _n): return self

    def execute(self):
        rows = self.s.setdefault(self.t, [])
        m = [r for r in rows if all(r.get(k) == v for k, v in self.f)]
        if self.op == "update":
            for r in m:
                r.update(self.payload)
        return _Resp(m)


class FakeDB:
    def __init__(self): self.store = {}
    def table(self, n): return _Q(self.store, n)


def _invoice(db, *, total, paid, status="paid"):
    db.store["client_sales_invoices"] = [{
        "id": "inv-1", "firm_id": FIRM, "client_id": CLIENT, "invoice_no": "INV-1",
        "total_paise": total, "paid_paise": paid, "credited_paise": 0,
        "debit_note_paise": 0, "status": status}]
    return db.store["client_sales_invoices"][0]


def _bill(db, *, total, paid, status="paid"):
    db.store["purchase_bills"] = [{
        "id": "bill-1", "firm_id": FIRM, "client_id": CLIENT, "bill_no": "B-1",
        "total_paise": total, "net_payable_paise": total, "paid_paise": paid,
        "credit_note_paise": 0, "debited_paise": 0, "status": status}]
    return db.store["purchase_bills"][0]


def _txn(*, credit=0, debit=0, category, mt, mid):
    return {"id": "t1", "firm_id": FIRM, "client_id": CLIENT,
            "transaction_date": "2026-06-10", "description": "TEST",
            "debit_paise": debit, "credit_paise": credit, "category": category,
            "matched_entity_type": mt, "matched_entity_id": mid}


@pytest.fixture()
def dsn(pg_template):
    return f"{_HARNESS_PG.strip()} dbname={pg_template.name}"


def test_the_schema_really_constrains_status(dsn):
    """Guard: if the CHECK did not exist, every assertion below would pass
    against an empty allowed-set comparison and prove nothing."""
    inv = _allowed_statuses(dsn, "client_sales_invoices")
    bill = _allowed_statuses(dsn, "purchase_bills")
    assert "paid" in inv and "issued" in inv, inv
    assert "paid" in bill and "received" in bill, bill
    assert "unpaid" not in inv and "unpaid" not in bill, (
        "the constraint now allows 'unpaid' — if that was deliberate this test "
        "should be revisited, but nothing in the codebase writes it")


@pytest.mark.parametrize("paid_off", [True, False])
def test_every_status_undo_writes_to_an_invoice_is_accepted(dsn, paid_off, monkeypatch):
    monkeypatch.setattr(bps, "_now", lambda: "2026-06-11T00:00:00Z")
    allowed = _allowed_statuses(dsn, "client_sales_invoices")
    db = FakeDB()
    total = 118000
    # Fully cleared by this line, or only partly — the two branches that decide
    # the status, exercised against what the column actually permits.
    paid = total if paid_off else total
    inv = _invoice(db, total=total, paid=paid)
    amount = total if paid_off else total // 2
    svc._unsettle(db, FIRM, _txn(credit=amount, category="Customer Payment",
                                 mt="sales_invoice", mid="inv-1"))
    assert inv["status"] in allowed, (
        f"undo wrote status {inv['status']!r} to client_sales_invoices, which "
        f"the column refuses — allowed: {sorted(allowed)}")
    # And it is the RIGHT one of the allowed values, not merely a legal one.
    assert inv["status"] == ("issued" if paid_off else "partially_paid")


@pytest.mark.parametrize("paid_off", [True, False])
def test_every_status_undo_writes_to_a_bill_is_accepted(dsn, paid_off, monkeypatch):
    monkeypatch.setattr(bps, "_now", lambda: "2026-06-11T00:00:00Z")
    allowed = _allowed_statuses(dsn, "purchase_bills")
    db = FakeDB()
    total = 90000
    bill = _bill(db, total=total, paid=total)
    amount = total if paid_off else total // 2
    svc._unsettle(db, FIRM, _txn(debit=amount, category="Vendor Payment",
                                 mt="purchase_bill", mid="bill-1"))
    assert bill["status"] in allowed, (
        f"undo wrote status {bill['status']!r} to purchase_bills, which the "
        f"column refuses — allowed: {sorted(allowed)}")
    # 'received' is the bill's own posted-but-unpaid state; 'issued' is the
    # invoice's. Using one for the other is legal SQL and wrong bookkeeping.
    assert bill["status"] == ("received" if paid_off else "partially_paid")


@pytest.mark.parametrize("frozen", ["draft", "cancelled"])
def test_a_draft_or_cancelled_document_is_not_resurrected(dsn, frozen, monkeypatch):
    """An undo takes back a payment. It does not decide that a cancelled
    invoice is now waiting to be paid."""
    monkeypatch.setattr(bps, "_now", lambda: "2026-06-11T00:00:00Z")
    allowed = _allowed_statuses(dsn, "client_sales_invoices")
    db = FakeDB()
    inv = _invoice(db, total=118000, paid=118000, status=frozen)
    svc._unsettle(db, FIRM, _txn(credit=118000, category="Customer Payment",
                                 mt="sales_invoice", mid="inv-1"))
    assert inv["status"] == frozen
    assert inv["status"] in allowed
    assert inv["paid_paise"] == 0, "the money still comes back off the document"
