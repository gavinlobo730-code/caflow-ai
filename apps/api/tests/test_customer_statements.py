"""
Phase 4.1 — Customer Statements tests.

Pure statement maths (opening carry-forward, running balance, closing, mixed
documents, empty customer), the service (firm/client scoping + draft/cancelled
exclusion), PDF generation, and email-delivery tracking. Read-only — no
accounting engine is touched.
"""
import pytest
from fastapi import HTTPException

from services.customer_statement_service import build_statement, customer_statement_service as SVC

FIRM, CLIENT, CUST = "firm-1", "client-1", "cust-1"
START, END = "2025-04-01", "2026-03-31"


def _cust(opening=0):
    return {"id": CUST, "name": "Acme Ltd", "email": "ap@acme.test", "gstin": "27AAAAA0000A1Z5",
            "opening_balance_paise": opening}


def inv(no, date, total): return {"invoice_no": no, "invoice_date": date, "total_paise": total}
def rcpt(no, date, amt): return {"receipt_no": no, "receipt_date": date, "amount_paise": amt}
def cn(no, date, total): return {"credit_note_no": no, "credit_note_date": date, "total_paise": total}


# ── Pure builder ──────────────────────────────────────────────────────────────

def test_opening_carries_seed_plus_prior_period():
    s = build_statement(
        _cust(opening=100000), START, END,
        invoices=[inv("PRIOR", "2025-03-20", 50000), inv("I1", "2025-04-10", 30000)],
        receipts=[rcpt("R1", "2025-04-20", 20000)], credit_notes=[])
    assert s["opening_balance_paise"] == 150000          # 100000 seed + 50000 prior invoice
    assert [t["reference"] for t in s["transactions"]] == ["I1", "R1"]
    assert [t["running_balance_paise"] for t in s["transactions"]] == [180000, 160000]
    assert s["closing_balance_paise"] == 160000


def test_no_transactions_returns_seed():
    s = build_statement(_cust(opening=75000), START, END, [], [], [])
    assert s["opening_balance_paise"] == 75000 and s["closing_balance_paise"] == 75000
    assert s["transactions"] == []


def test_mixed_invoices_receipts_credits():
    s = build_statement(
        _cust(opening=0), START, END,
        invoices=[inv("I1", "2025-04-05", 118000), inv("I2", "2025-05-05", 59000)],
        receipts=[rcpt("R1", "2025-04-20", 100000)],
        credit_notes=[cn("C1", "2025-05-10", 9000)])
    # 0 + 118000 - 100000 + 59000 - 9000 = 68000
    assert s["closing_balance_paise"] == 68000
    assert s["totals"] == {"invoiced_paise": 177000, "received_paise": 100000,
                           "credited_paise": 9000, "debited_paise": 0, "transaction_count": 4}
    # ordering: same-day invoices before credit notes before receipts; across days by date
    assert [t["reference"] for t in s["transactions"]] == ["I1", "R1", "I2", "C1"]


def test_credit_note_reduces_balance():
    s = build_statement(_cust(0), START, END,
                        invoices=[inv("I1", "2025-04-05", 50000)],
                        receipts=[], credit_notes=[cn("C1", "2025-04-06", 20000)])
    assert s["closing_balance_paise"] == 30000


def test_out_of_period_excluded_from_rows_but_prior_in_opening():
    s = build_statement(_cust(0), START, END,
                        invoices=[inv("FUTURE", "2026-05-01", 99999), inv("I1", "2025-04-10", 10000)],
                        receipts=[], credit_notes=[])
    refs = [t["reference"] for t in s["transactions"]]
    assert refs == ["I1"]                                # future invoice excluded
    assert s["closing_balance_paise"] == 10000


# ── PDF ───────────────────────────────────────────────────────────────────────

def test_statement_pdf_renders_bytes():
    from services.statement_pdf_service import build_statement_pdf
    s = build_statement(_cust(100000), START, END,
                        invoices=[inv("I1", "2025-04-10", 30000)],
                        receipts=[rcpt("R1", "2025-04-20", 20000)], credit_notes=[])
    pdf = build_statement_pdf(s, {"name": "Test & Co CA"}, s["customer"])
    assert isinstance(pdf, bytes) and pdf[:4] == b"%PDF" and len(pdf) > 800


# ── Service (FakeDB): scoping + draft/cancelled exclusion + deliveries ─────────

class _Resp:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, store, table):
        self.s, self.t = store, table
        self.op = "select"; self.payload = None; self.f = []; self.order_ = None; self.desc = False

    def insert(self, p): self.op, self.payload = "insert", p; return self
    def update(self, p): self.op, self.payload = "update", p; return self
    def select(self, *a, **k): self.op = "select"; return self
    def eq(self, k, v): self.f.append((k, v)); return self
    def is_(self, k, _v): self.f.append((k, ("__null__",))); return self
    def limit(self, _n): return self
    def order(self, c, desc=False): self.order_, self.desc = c, desc; return self

    def _match(self):
        out = []
        for r in self.s.setdefault(self.t, []):
            ok = True
            for k, v in self.f:
                if isinstance(v, tuple) and v and v[0] == "__null__":
                    if r.get(k) is not None: ok = False; break
                elif r.get(k) != v: ok = False; break
            if ok: out.append(r)
        return out

    def execute(self):
        rows = self.s.setdefault(self.t, [])
        if self.op == "insert":
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            ins = []
            for p in items:
                rec = dict(p); rec.setdefault("id", f"{self.t}-{len(rows)+1}")
                rows.append(rec); ins.append(dict(rec))
            return _Resp(ins)
        m = self._match()
        if self.op == "update":
            for r in m: r.update(self.payload)
            return _Resp([dict(r) for r in m])
        if self.order_:
            m = sorted(m, key=lambda r: str(r.get(self.order_)), reverse=self.desc)
        return _Resp([dict(r) for r in m])


class FakeDB:
    def __init__(self): self.store = {}
    def table(self, n): return _Q(self.store, n)


def _seed_db():
    d = FakeDB()
    d.store["customers"] = [{"id": CUST, "firm_id": FIRM, "client_id": CLIENT, "name": "Acme",
                             "email": "ap@acme.test", "opening_balance_paise": 100000}]
    d.store["client_sales_invoices"] = [
        {"firm_id": FIRM, "client_id": CLIENT, "customer_id": CUST, "invoice_no": "I1",
         "invoice_date": "2025-04-10", "total_paise": 30000, "status": "issued", "deleted_at": None},
        {"firm_id": FIRM, "client_id": CLIENT, "customer_id": CUST, "invoice_no": "DRAFT",
         "invoice_date": "2025-04-12", "total_paise": 99999, "status": "draft", "deleted_at": None},
        {"firm_id": FIRM, "client_id": CLIENT, "customer_id": CUST, "invoice_no": "CANC",
         "invoice_date": "2025-04-13", "total_paise": 88888, "status": "cancelled", "deleted_at": None},
    ]
    d.store["receipts"] = [{"firm_id": FIRM, "client_id": CLIENT, "customer_id": CUST,
                            "receipt_no": "R1", "receipt_date": "2025-04-20", "amount_paise": 20000}]
    d.store["credit_notes"] = []
    d.store["customer_statement_deliveries"] = []
    return d


def test_service_generate_scopes_and_excludes_draft_cancelled():
    d = _seed_db()
    s = SVC.generate(d, FIRM, CLIENT, CUST, START, END)
    # only the issued invoice (30000) + receipt (20000) count; draft & cancelled excluded
    assert [t["reference"] for t in s["transactions"]] == ["I1", "R1"]
    assert s["opening_balance_paise"] == 100000
    assert s["closing_balance_paise"] == 110000          # 100000 + 30000 - 20000


def test_service_customer_not_found_for_wrong_firm():
    d = _seed_db()
    with pytest.raises(HTTPException) as e:
        SVC.generate(d, "other-firm", CLIENT, CUST, START, END)
    assert e.value.status_code == 404


def test_service_rejects_reversed_period():
    d = _seed_db()
    with pytest.raises(HTTPException) as e:
        SVC.generate(d, FIRM, CLIENT, CUST, END, START)
    assert e.value.status_code == 422


def test_delivery_tracking_records_send():
    d = _seed_db()
    did = SVC.record_delivery(d, FIRM, CLIENT, CUST, START, END, "ap@acme.test", "u1", "u@firm.test")
    row = d.store["customer_statement_deliveries"][0]
    assert row["status"] == "sending" and row["sent_to"] == "ap@acme.test"
    SVC.finish_delivery(d, did, True, provider_id="msg-1")
    assert row["status"] == "sent" and row["sent_at"] and row["provider_message_id"] == "msg-1"
    rows = SVC.deliveries(d, FIRM, CLIENT, CUST)
    assert len(rows) == 1 and rows[0]["status"] == "sent"
