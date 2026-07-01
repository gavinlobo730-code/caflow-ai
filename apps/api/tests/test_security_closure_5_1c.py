"""
Phase 5.1C — security closure (OOS-1).

OOS-1: the purchase-bill status writer (_update_bill_payment_status) looked up
and mutated a bill by id with no firm/client scope. These tests prove the writer
is now scoped to (firm_id, client_id): a foreign firm or client cannot mutate a
bill's status; the correct firm+client can.

NOTE (reachability): PurchasePaymentIn now carries purchase_bill_id (Phase 5 H11),
so the writer IS reachable via the API — the firm/client scope on both the guard
read and the UPDATE keeps it safe. The writer now recomputes paid_paise + status
from ALL recorded payments (the payment row is inserted before it runs), so these
tests seed the payment rows the writer sums.
"""


class _Result:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, db, table):
        self.db, self.t = db, table
        self.f = []; self.op = "select"; self.payload = None; self._limit = None

    def select(self, *a, **k): self.op = "select"; return self
    def insert(self, p): self.op = "insert"; self.payload = p; return self
    def update(self, p): self.op = "update"; self.payload = p; return self
    def eq(self, c, v): self.f.append((c, v)); return self
    def limit(self, n): self._limit = n; return self

    def _match(self, row): return all(row.get(c) == v for c, v in self.f)

    def execute(self):
        rows = self.db.data.setdefault(self.t, [])
        if self.op == "select":
            out = [dict(r) for r in rows if self._match(r)]
            if self._limit is not None: out = out[:self._limit]
            return _Result(out)
        if self.op == "update":
            up = [r for r in rows if self._match(r)]
            for r in up: r.update(self.payload)
            return _Result([dict(r) for r in up])
        if self.op == "insert":
            payload = self.payload if isinstance(self.payload, list) else [self.payload]
            for p in payload: rows.append(dict(p))
            return _Result(list(payload))
        return _Result([])


class FakeDB:
    def __init__(self): self.data = {}
    def table(self, n): return _Q(self, n)
    def seed(self, t, row): self.data.setdefault(t, []).append(dict(row)); return row


def test_oos1_bill_status_writer_scoped_to_firm_and_client():
    from routers.purchase_payments import _update_bill_payment_status
    db = FakeDB()
    db.seed("purchase_bills", {"id": "BILL", "firm_id": "F", "client_id": "A",
                               "net_payable_paise": 100000, "status": "issued"})
    # The payment row is recorded before the writer runs (real create flow).
    db.seed("purchase_payments", {"id": "P1", "firm_id": "F", "client_id": "A",
                                  "purchase_bill_id": "BILL", "amount_paise": 100000})

    # Foreign firm → no mutation.
    _update_bill_payment_status(db, "OTHER", "A", "BILL", 100000)
    assert db.data["purchase_bills"][0]["status"] == "issued"

    # Right firm, wrong client → no mutation.
    _update_bill_payment_status(db, "F", "B", "BILL", 100000)
    assert db.data["purchase_bills"][0]["status"] == "issued"

    # Correct firm + client → status updates (full payment ⇒ paid) + paid_paise set.
    _update_bill_payment_status(db, "F", "A", "BILL", 100000)
    assert db.data["purchase_bills"][0]["status"] == "paid"
    assert db.data["purchase_bills"][0]["paid_paise"] == 100000


def test_oos1_partial_payment_marks_partially_paid():
    from routers.purchase_payments import _update_bill_payment_status
    db = FakeDB()
    db.seed("purchase_bills", {"id": "BILL", "firm_id": "F", "client_id": "A",
                               "net_payable_paise": 100000, "status": "issued"})
    db.seed("purchase_payments", {"id": "P1", "firm_id": "F", "client_id": "A",
                                  "purchase_bill_id": "BILL", "amount_paise": 40000})
    _update_bill_payment_status(db, "F", "A", "BILL", 40000)
    assert db.data["purchase_bills"][0]["status"] == "partially_paid"
    assert db.data["purchase_bills"][0]["paid_paise"] == 40000
