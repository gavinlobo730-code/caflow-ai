"""
Phase 5.1C — security closure (OOS-1).

OOS-1: the purchase-bill status writer (_update_bill_payment_status) looked up
and mutated a bill by id with no firm/client scope. These tests prove the writer
is now scoped to (firm_id, client_id): a foreign firm or client cannot mutate a
bill's status; the correct firm+client can.

NOTE (reachability): create_purchase_payment cannot currently feed an
attacker-controlled bill id — PurchasePaymentIn has no purchase_bill_id field, so
Pydantic drops it and the writer is never invoked via the API. OOS-1 is therefore
THEORETICAL; this fix hardens the writer + adds a pre-create guard so the path is
safe if the field is ever wired in. The test exercises the writer directly.
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

    # Foreign firm → no mutation.
    _update_bill_payment_status(db, "OTHER", "A", "BILL", 100000)
    assert db.data["purchase_bills"][0]["status"] == "issued"

    # Right firm, wrong client → no mutation.
    _update_bill_payment_status(db, "F", "B", "BILL", 100000)
    assert db.data["purchase_bills"][0]["status"] == "issued"

    # Correct firm + client → status updates (full payment ⇒ paid).
    _update_bill_payment_status(db, "F", "A", "BILL", 100000)
    assert db.data["purchase_bills"][0]["status"] == "paid"


def test_oos1_partial_payment_marks_partially_paid():
    from routers.purchase_payments import _update_bill_payment_status
    db = FakeDB()
    db.seed("purchase_bills", {"id": "BILL", "firm_id": "F", "client_id": "A",
                               "net_payable_paise": 100000, "status": "issued"})
    _update_bill_payment_status(db, "F", "A", "BILL", 40000)
    assert db.data["purchase_bills"][0]["status"] == "partially_paid"
