"""
Task #221 — AR/AP aging at scale.

customer_statement_service.ar_aging() / vendor_statement_service.ap_aging()
read a client's ENTIRE invoice/bill history unfiltered by date, aggregated
across every customer/vendor — the audit's highest-severity remaining finding
after the reporting engine itself (domain/reporting/sources.py, fixed in
test_scale_ledger_pagination.py). A DB double that reproduces PostgREST's
~1000-row hard cap on un-ranged selects proves both now return EVERY open
invoice/bill (so the aging total a CA sees is correct) for a client with far
more than 1000 open documents, where the old un-paged fetch silently
truncated to 1000.
"""
from services.customer_statement_service import customer_statement_service
from services.vendor_statement_service import vendor_statement_service

FIRM = "FIRM-A"
CLIENT = "CLI"
CAP = 1000


class _Res:
    def __init__(self, data): self.data = data


class _CapQuery:
    """Simulates PostgREST: an un-ranged/un-limited select is hard-capped at
    CAP rows; a .limit()/.range() select returns exactly that slice. Supports
    keyset paging (.gt + .limit over an ascending .order). Mirrors
    test_scale_ledger_pagination.py's double."""
    def __init__(self, store, table):
        self.store, self.t = store, table
        self.f = []; self._range = None; self._cols = ""
        self._order = None; self._limit = None
    def select(self, cols="*", **k): self._cols = cols; return self
    def eq(self, k, v): self.f.append((k, v)); return self
    def is_(self, k, _v): self.f.append((k, "__null__")); return self
    def in_(self, k, vals): self.f.append((k, ("__in__", set(vals)))); return self
    def gt(self, k, v): self.f.append((k, ("__gt__", v))); return self
    def order(self, col=None, *_a, **_k): self._order = col; return self
    def range(self, a, b): self._range = (a, b); return self
    def limit(self, n): self._limit = n; return self

    def _match(self, r):
        for k, v in self.f:
            if v == "__null__":
                if r.get(k) is not None: return False
            elif isinstance(v, tuple) and v[0] == "__in__":
                if r.get(k) not in v[1]: return False
            elif isinstance(v, tuple) and v[0] == "__gt__":
                if not (r.get(k) is not None and str(r.get(k)) > str(v[1])): return False
            elif r.get(k) != v:
                return False
        return True

    def execute(self):
        rows = [dict(r) for r in self.store.get(self.t, []) if self._match(r)]
        if self._order is not None:
            rows.sort(key=lambda r: str(r.get(self._order)))
        if self._range is not None:
            a, b = self._range
            return _Res(rows[a:b + 1])
        if self._limit is not None:
            return _Res(rows[:self._limit])
        return _Res(rows[:CAP])          # the silent cap (un-limited select)


class _CapDB:
    def __init__(self, store): self.store = store
    def table(self, n): return _CapQuery(self.store, n)


def _invoice_row(i: int) -> dict:
    return {
        "id": f"inv{i:06d}", "customer_id": f"cust{i % 50:04d}", "invoice_no": f"INV-{i:06d}",
        "invoice_date": "2025-06-01", "due_date": "2025-06-15",
        "total_paise": 10_000, "paid_paise": 0, "credited_paise": 0, "debit_note_paise": 0,
        "status": "issued", "txn_currency": "INR", "exchange_rate": "1", "txn_total": 10_000,
        "paid_txn": 0, "firm_id": FIRM, "client_id": CLIENT, "deleted_at": None,
    }


def _bill_row(i: int) -> dict:
    return {
        "id": f"bill{i:06d}", "vendor_id": f"vend{i % 50:04d}", "bill_no": f"BILL-{i:06d}",
        "bill_date": "2025-06-01", "due_date": "2025-06-15",
        "net_payable_paise": 10_000, "paid_paise": 0, "debited_paise": 0, "credit_note_paise": 0,
        "status": "received", "txn_currency": "INR", "exchange_rate": "1", "txn_net_payable": 10_000,
        "paid_txn": 0, "firm_id": FIRM, "client_id": CLIENT, "deleted_at": None,
    }


def test_ar_aging_returns_all_open_invoices_beyond_cap():
    n = 2500
    store = {
        "client_sales_invoices": [_invoice_row(i) for i in range(n)],
        "customers": [{"id": f"cust{i:04d}", "name": f"Customer {i}", "firm_id": FIRM, "client_id": CLIENT}
                     for i in range(50)],
    }
    db = _CapDB(store)
    result = customer_statement_service.ar_aging(db, FIRM, CLIENT, as_of="2026-01-01")
    assert len(result["invoices"]) == n              # not silently capped at 1000
    assert result["total_outstanding_paise"] == n * 10_000


def test_ap_aging_returns_all_open_bills_beyond_cap():
    n = 2500
    store = {
        "purchase_bills": [_bill_row(i) for i in range(n)],
        "vendors": [{"id": f"vend{i:04d}", "name": f"Vendor {i}", "firm_id": FIRM, "client_id": CLIENT}
                   for i in range(50)],
    }
    db = _CapDB(store)
    result = vendor_statement_service.ap_aging(db, FIRM, CLIENT, as_of="2026-01-01")
    assert len(result["bills"]) == n                 # not silently capped at 1000
    assert result["total_outstanding_paise"] == n * 10_000
