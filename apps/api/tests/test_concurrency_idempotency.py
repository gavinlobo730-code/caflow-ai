"""
Production Readiness Phase 3 — idempotent posting + lost-update prevention
(audit H2, M8, H1). Logic-level tests through the real posting kernel / receipt
engine; the true concurrent races are proven against the live DB (rolled back)
in the phase deliverable.
"""
import pytest
from fastapi import HTTPException

import routers.sales_invoices as si
import services.receipt_service as rsvc
import services.phase2_journal_service as pjs
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, coa_id, account_balance

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, rsvc])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "financial_year_start": "2025-04-01"})
    db.seed("customers", {"id": "CUST1", "firm_id": FIRM, "client_id": "CLI", "name": "Acme",
                          "is_active": True, "opening_balance_paise": 0})
    seed_standard_coa(db, FIRM, "CLI")
    return db


def _balanced_lines(db):
    return [
        {"account_id": coa_id(db, FIRM, "ar"), "debit_paise": 1000, "credit_paise": 0},
        {"account_id": coa_id(db, FIRM, "revenue"), "debit_paise": 0, "credit_paise": 1000},
    ]


# ── H2: idempotent posting ────────────────────────────────────────────────────
def test_duplicate_journal_reference_is_idempotent(monkeypatch):
    db = _setup(monkeypatch)
    k = pjs.phase2_journal_service
    a = k._create_journal(db, firm_id=FIRM, client_id="CLI", entry_date="2025-06-01",
                          reference_no="DUP-1", narration="x", entry_type="Journal",
                          lines=_balanced_lines(db))
    b = k._create_journal(db, firm_id=FIRM, client_id="CLI", entry_date="2025-06-01",
                          reference_no="DUP-1", narration="x", entry_type="Journal",
                          lines=_balanced_lines(db))
    assert a == b                                                    # same entry returned
    dups = [e for e in db.rows("journal_entries") if e.get("reference_no") == "DUP-1"]
    assert len(dups) == 1                                           # only one posted


def test_reversed_entry_does_not_block_repost(monkeypatch):
    """A reversed original is dead — re-posting the same document (same firm+
    client+reference_no+entry_date) must create a fresh entry, not dedupe onto
    the reversed one (task #102 finding)."""
    db = _setup(monkeypatch)
    k = pjs.phase2_journal_service
    a = k._create_journal(db, firm_id=FIRM, client_id="CLI", entry_date="2025-06-01",
                          reference_no="REPOST-1", narration="x", entry_type="Journal",
                          lines=_balanced_lines(db))
    k.reverse_entry(db, firm_id=FIRM, entry_id=a, reversal_date="2025-06-02", created_by="u")
    b = k._create_journal(db, firm_id=FIRM, client_id="CLI", entry_date="2025-06-01",
                          reference_no="REPOST-1", narration="x", entry_type="Journal",
                          lines=_balanced_lines(db))
    assert a != b
    live = [e for e in db.rows("journal_entries")
            if e.get("reference_no") == "REPOST-1" and not e.get("is_reversed")]
    assert len(live) == 1
    assert live[0]["id"] == b


def test_same_ref_different_date_is_distinct(monkeypatch):
    db = _setup(monkeypatch)
    k = pjs.phase2_journal_service
    a = k._create_journal(db, firm_id=FIRM, client_id="CLI", entry_date="2025-06-01",
                          reference_no="R", narration="x", entry_type="Journal", lines=_balanced_lines(db))
    b = k._create_journal(db, firm_id=FIRM, client_id="CLI", entry_date="2025-06-02",
                          reference_no="R", narration="x", entry_type="Journal", lines=_balanced_lines(db))
    assert a != b and len(db.rows("journal_entries")) == 2


# ── M8: zero-value journal rejected ───────────────────────────────────────────
def test_zero_value_journal_rejected(monkeypatch):
    db = _setup(monkeypatch)
    with pytest.raises(ValueError, match="zero-value"):
        pjs.phase2_journal_service._create_journal(
            db, firm_id=FIRM, client_id="CLI", entry_date="2025-06-01",
            reference_no="Z", narration="x", entry_type="Journal",
            lines=[{"account_id": coa_id(db, FIRM, "ar"), "debit_paise": 0, "credit_paise": 0},
                   {"account_id": coa_id(db, FIRM, "revenue"), "debit_paise": 0, "credit_paise": 0}],
        )
    assert not db.rows("journal_entries")


# ── H1: settlement accumulates without lost update / overshoot ─────────────────
def _issue_invoice(db, total=100000):
    inv = db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST1", "invoice_no": "INV-1",
        "invoice_date": "2025-06-01", "status": "draft", "total_paise": total,
        "taxable_amount_paise": total, "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 0,
        "paid_paise": 0, "credited_paise": 0, "is_interstate": False,
    })
    assert si.issue_invoice(inv["id"], CALLER)["success"] is True
    return inv["id"]


def _receipt(db, inv_id, amount):
    return rsvc.create_receipt_core(FIRM, {
        "client_id": "CLI", "customer_id": "CUST1", "receipt_date": "2025-06-10",
        "amount_paise": amount, "allocations": [{"sales_invoice_id": inv_id, "allocated_paise": amount}],
    }, CALLER, db)


def test_settlement_accumulates_with_cas(monkeypatch):
    db = _setup(monkeypatch)
    inv_id = _issue_invoice(db, total=100000)
    _receipt(db, inv_id, 40000)
    _receipt(db, inv_id, 60000)
    inv = next(i for i in db.rows("client_sales_invoices") if i["id"] == inv_id)
    assert inv["paid_paise"] == 100000 and inv["status"] == "paid"   # no lost update


def test_over_allocation_blocked(monkeypatch):
    db = _setup(monkeypatch)
    inv_id = _issue_invoice(db, total=100000)
    _receipt(db, inv_id, 100000)
    with pytest.raises(HTTPException) as ex:
        _receipt(db, inv_id, 1)          # would exceed the invoice total
    assert ex.value.status_code == 422
    inv = next(i for i in db.rows("client_sales_invoices") if i["id"] == inv_id)
    assert inv["paid_paise"] == 100000    # unchanged by the rejected allocation


def test_cas_guard_retries_on_stale_paid(monkeypatch):
    # Simulate a concurrent writer: the FIRST invoice-status UPDATE the receipt
    # engine issues is intercepted to also bump paid_paise underneath it, so the
    # compare-and-set (WHERE paid_paise = <stale>) matches 0 rows and the engine
    # must re-read and retry — ending at the correct accumulated total.
    #
    # R2.12: create_receipt_core now prefers db.rpc when available — the atomic
    # settle_receipt_atomic path, whose concurrency safety comes from a real
    # Postgres row lock (SELECT ... FOR UPDATE) rather than an app-level
    # optimistic CAS retry, and isn't meaningfully simulable by a
    # single-threaded fake reacting to its own synchronous .update() call (see
    # test_r2_12_atomic_receipt_settlement_pg.py for the real-Postgres proof
    # of concurrent-settlement safety). This test targets the legacy
    # CAS-retry loop specifically, which the code still preserves as a
    # fallback for test doubles without rpc support — so the receipt call
    # here goes through a db stand-in that hides .rpc.
    db = _setup(monkeypatch)
    inv_id = _issue_invoice(db, total=100000)

    real_table = db.table
    state = {"tripped": False}

    class _Wrap:
        def __init__(self, q): self._q = q
        def __getattr__(self, n): return getattr(self._q, n)
        def update(self, payload):
            # On the first settlement update, mutate the row first (concurrent writer).
            if not state["tripped"] and "paid_paise" in payload:
                state["tripped"] = True
                for r in db.rows("client_sales_invoices"):
                    if r["id"] == inv_id:
                        r["paid_paise"] = 5000      # someone else paid ₹50 first
                        r["status"] = "partially_paid"
            return self._q.update(payload)

    def wrapped_table(name):
        q = real_table(name)
        return _Wrap(q) if name == "client_sales_invoices" else q

    class _NoRpcDB:
        """Exposes only .table (delegated), deliberately no .rpc attribute, to
        force create_receipt_core down its legacy CAS-retry fallback path."""
        def __init__(self, table_fn): self._table_fn = table_fn
        def table(self, name): return self._table_fn(name)

    _receipt(_NoRpcDB(wrapped_table), inv_id, 40000)

    inv = next(i for i in db.rows("client_sales_invoices") if i["id"] == inv_id)
    # The concurrent ₹50 + this ₹400 both land — nothing lost.
    assert inv["paid_paise"] == 5000 + 40000
