"""
Banking B.3 — Posting Engine tests: category→journal mapping, settlement,
duplicate/FY/account protection, and integrity (balanced, paise, audit).
"""
import pytest

from domain.banking import posting_map as pmap
import services.bank_posting_service as bps
from services.bank_posting_service import bank_posting_service
import services.journal_posting_service as jpsmod
from services.journal_posting_service import journal_posting_service
import services.phase2_journal_service as pjs


# ── Pure mapper (line direction / balance) ────────────────────────────────────

def _balanced(lines):
    return sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines)


def test_money_in_dr_bank_cr_counter():
    lines = pmap.build_lines(10000, True, "BANK", "AR")
    assert _balanced(lines)
    dr = next(l for l in lines if l["debit_paise"])
    cr = next(l for l in lines if l["credit_paise"])
    assert dr["account_id"] == "BANK" and cr["account_id"] == "AR"


def test_money_out_dr_counter_cr_bank():
    lines = pmap.build_lines(10000, False, "BANK", "AP")
    dr = next(l for l in lines if l["debit_paise"])
    cr = next(l for l in lines if l["credit_paise"])
    assert dr["account_id"] == "AP" and cr["account_id"] == "BANK" and _balanced(lines)


def test_transfer_direction_and_same_account_guard():
    out = pmap.build_transfer_lines(5000, False, "B1", "B2")     # money left B1 → Dr B2 / Cr B1
    assert next(l for l in out if l["debit_paise"])["account_id"] == "B2"
    inb = pmap.build_transfer_lines(5000, True, "B1", "B2")       # money into B1 → Dr B1 / Cr B2
    assert next(l for l in inb if l["debit_paise"])["account_id"] == "B1"
    with pytest.raises(ValueError):
        pmap.build_transfer_lines(5000, True, "B1", "B1")


def test_zero_amount_and_missing_account_raise():
    with pytest.raises(ValueError):
        pmap.build_lines(0, True, "BANK", "AR")
    with pytest.raises(ValueError):
        pmap.build_lines(100, True, "BANK", None)


def test_entry_type():
    assert pmap.entry_type_for("Customer Payment", True) == "Receipt"
    assert pmap.entry_type_for("Vendor Payment", False) == "Payment"
    assert pmap.entry_type_for("Transfer", False) == "Contra"


# ── Fake Supabase ─────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, store, table):
        self.s, self.t = store, table
        self.op = "select"; self.cols = ""; self.payload = None; self.f = []
        self.single_ = False; self.order_ = None; self.desc = False

    def insert(self, p): self.op, self.payload = "insert", p; return self
    def update(self, p): self.op, self.payload = "update", p; return self
    def select(self, *a, **k): self.op = "select"; self.cols = " ".join(str(x) for x in a); return self
    def eq(self, k, v): self.f.append((k, v)); return self
    def or_(self, *_a, **_k): return self
    def ilike(self, *_a, **_k): return self
    def in_(self, k, vals): self.f.append((k, ("__in__", list(vals)))); return self
    def is_(self, k, _v): self.f.append((k, ("__null__",))); return self
    def limit(self, _n): return self
    def order(self, c, desc=False): self.order_, self.desc = c, desc; return self
    def single(self): self.single_ = True; return self

    def _match(self):
        rows = self.s.setdefault(self.t, [])
        out = []
        for r in rows:
            ok = True
            for k, v in self.f:
                if isinstance(v, tuple) and v and v[0] == "__in__":
                    if r.get(k) not in v[1]: ok = False; break
                elif isinstance(v, tuple) and v and v[0] == "__null__":
                    if r.get(k) is not None: ok = False; break
                elif r.get(k) != v: ok = False; break
            if ok: out.append(r)
        return out

    def _embed(self, rows):
        if self.t == "journal_entries" and "journal_lines" in self.cols:
            for r in rows:
                r["journal_lines"] = [dict(l) for l in self.s.get("journal_lines", [])
                                      if l.get("journal_entry_id") == r["id"]]
        return rows

    def execute(self):
        rows = self.s.setdefault(self.t, [])
        if self.op == "insert":
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            ins = []
            for p in items:
                rec = dict(p); rec.setdefault("id", f"{self.t}-{len(rows)+1}")
                rows.append(rec); ins.append(rec)
            return _Resp(ins)
        m = self._match()
        if self.op == "update":
            for r in m: r.update(self.payload)
            return _Resp(m)
        m = self._embed(m)
        if self.order_:
            m = sorted(m, key=lambda r: str(r.get(self.order_)), reverse=self.desc)
        if self.single_:
            return _Resp(m[0] if m else None)
        return _Resp(m)


class FakeDB:
    def __init__(self): self.store = {}
    def table(self, n): return _Q(self.store, n)


FIRM, CLIENT = "firm-1", "client-1"

ACCOUNTS = [
    ("acc-bank", "HDFC Bank", "bank"), ("acc-bank2", "Cash in Hand", None),
    ("acc-ar", "Trade Receivables", "ar"), ("acc-ap", "Trade Payables", "ap"),
    ("acc-gst", "GST Output Tax Payable", "gst_output"),
    ("acc-exp", "Office Rent", None), ("acc-sal", "Salaries Expense", None),
    ("acc-loan", "Term Loan", None), ("acc-cap", "Capital Account", None),
    ("acc-draw", "Drawings Account", None), ("acc-int-inc", "Interest Income", None),
    ("acc-int-exp", "Interest on Loans", None), ("acc-rev", "Sales Revenue", None),
]


def _db_with_accounts():
    db = FakeDB()
    db.store["chart_of_accounts"] = [
        {"id": i, "firm_id": FIRM, "client_id": None, "account_name": n,
         "system_account_key": sk, "is_active": True} for (i, n, sk) in ACCOUNTS
    ]
    return db


def _seed_txn(db, *, credit=0, debit=0, category=None, matched_type=None, matched_id=None, **kw):
    row = dict(id="t1", firm_id=FIRM, client_id=CLIENT, transaction_date="2026-06-10",
               description="TEST", debit_paise=debit, credit_paise=credit,
               balance_paise=0, match_status="matched" if matched_id else "unmatched",
               category=category, matched_entity_type=matched_type, matched_entity_id=matched_id,
               posted_journal_id=None)
    row.update(kw)
    db.store.setdefault("bank_transactions", []).append(row)
    return row


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    # FY lock + timeline are external; default no-op (overridden per test).
    monkeypatch.setattr(bps.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(jpsmod.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(jpsmod.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    monkeypatch.setattr("services.audit_service.log_event", lambda *a, **k: None, raising=False)
    yield


def _lines_for(db, je_id):
    return [l for l in db.store.get("journal_lines", []) if l["journal_entry_id"] == je_id]


def _approve(db, draft_journal_id, actor="u1"):
    """Phase 3.5: approve+post a draft (fires deferred bank settlement)."""
    return journal_posting_service.post_draft(db, FIRM, draft_journal_id, actor_id=actor)


# ── B.3.3 every category posts a balanced, correctly-directed journal ─────────

CASES = [
    # name, category, credit, debit, account_id, expected_counter
    ("customer_payment", "Customer Payment", 100000, 0, None, "acc-ar"),
    ("vendor_payment",   "Vendor Payment",   0, 100000, None, "acc-ap"),
    ("expense",          "Expense",          0, 50000, "acc-exp", "acc-exp"),
    ("gst_payment",      "GST Payment",      0, 90000, None, "acc-gst"),
    ("salary",           "Salary",           0, 250000, "acc-sal", "acc-sal"),
    ("loan_received",    "Loan",             500000, 0, "acc-loan", "acc-loan"),
    ("loan_repayment",   "Loan",             0, 30000, "acc-loan", "acc-loan"),
    ("capital_introduced", "Capital",        700000, 0, "acc-cap", "acc-cap"),
    ("drawings",         "Capital",          0, 20000, "acc-draw", "acc-draw"),
    ("interest_earned",  "Interest",         1500, 0, "acc-int-inc", "acc-int-inc"),
    ("interest_paid",    "Interest",         0, 4000, "acc-int-exp", "acc-int-exp"),
]


@pytest.mark.parametrize("name,category,credit,debit,account_id,counter", CASES)
def test_post_each_category(name, category, credit, debit, account_id, counter):
    db = _db_with_accounts()
    _seed_txn(db, credit=credit, debit=debit, category=category)
    res = bank_posting_service.post(db, FIRM, "t1", bank_account_id="acc-bank",
                                    account_id=account_id, actor_id="u1")
    je = res["draft_journal_id"]
    assert je and res["status"] == "draft"        # Phase 3.5: creates a draft
    lines = _lines_for(db, je)
    assert _balanced(lines)                       # integrity: balanced
    is_credit = credit > 0
    dr = next(l for l in lines if l["debit_paise"])
    cr = next(l for l in lines if l["credit_paise"])
    if is_credit:                                  # money in → Dr Bank / Cr counter
        assert dr["account_id"] == "acc-bank" and cr["account_id"] == counter
    else:                                          # money out → Dr counter / Cr Bank
        assert dr["account_id"] == counter and cr["account_id"] == "acc-bank"
    assert db.store["bank_transactions"][0]["posted_journal_id"] == je


def test_transfer_posts_between_banks():
    db = _db_with_accounts()
    _seed_txn(db, debit=60000, category="Transfer")   # money out of acc-bank
    res = bank_posting_service.post(db, FIRM, "t1", bank_account_id="acc-bank",
                                    to_bank_account_id="acc-bank2", actor_id="u1")
    lines = _lines_for(db, res["draft_journal_id"])
    assert _balanced(lines)
    dr = next(l for l in lines if l["debit_paise"])
    assert dr["account_id"] == "acc-bank2"            # destination receives


# ── B.3.4 settlement ──────────────────────────────────────────────────────────

def _seed_invoice(db, total, paid=0, status="issued"):
    db.store.setdefault("client_sales_invoices", []).append(
        {"id": "inv-1", "firm_id": FIRM, "client_id": CLIENT, "invoice_no": "INV-1",
         "total_paise": total, "paid_paise": paid, "status": status})


def _seed_bill(db, total, paid=0, status="received"):
    db.store.setdefault("purchase_bills", []).append(
        {"id": "bill-1", "firm_id": FIRM, "client_id": CLIENT, "bill_no": "BILL-1",
         "total_paise": total, "paid_paise": paid, "status": status})


def test_full_invoice_settlement():
    db = _db_with_accounts(); _seed_invoice(db, 118000)
    _seed_txn(db, credit=118000, category="Customer Payment",
              matched_type="sales_invoice", matched_id="inv-1")
    res = bank_posting_service.post(db, FIRM, "t1", bank_account_id="acc-bank", actor_id="u1")
    assert db.store["client_sales_invoices"][0]["paid_paise"] == 0   # draft: not settled yet
    out = _approve(db, res["draft_journal_id"])                       # approve → settle
    inv = db.store["client_sales_invoices"][0]
    assert inv["paid_paise"] == 118000 and inv["status"] == "paid"
    assert out["settlement"]["allocated_paise"] == 118000


def test_partial_invoice_settlement():
    db = _db_with_accounts(); _seed_invoice(db, 118000, paid=18000, status="partially_paid")
    _seed_txn(db, credit=50000, category="Customer Payment",
              matched_type="sales_invoice", matched_id="inv-1")
    res = bank_posting_service.post(db, FIRM, "t1", bank_account_id="acc-bank", actor_id="u1")
    _approve(db, res["draft_journal_id"])
    inv = db.store["client_sales_invoices"][0]
    assert inv["paid_paise"] == 68000 and inv["status"] == "partially_paid"


def test_invoice_never_over_allocates():
    db = _db_with_accounts(); _seed_invoice(db, 100000, paid=90000, status="partially_paid")
    # bank credit larger than remaining (10000) — allocate only the remainder.
    _seed_txn(db, credit=50000, category="Customer Payment",
              matched_type="sales_invoice", matched_id="inv-1")
    res = bank_posting_service.post(db, FIRM, "t1", bank_account_id="acc-bank", actor_id="u1")
    out = _approve(db, res["draft_journal_id"])
    inv = db.store["client_sales_invoices"][0]
    assert inv["paid_paise"] == 100000 and inv["status"] == "paid"
    assert out["settlement"]["allocated_paise"] == 10000


def test_invoice_settlement_accounts_for_credit_and_debit_notes():
    # task #102: settlement used to allocate against (total_paise − paid_paise)
    # only, ignoring credit/debit notes — the SAME formula ar_aging already
    # uses (CGST Act §34). total 118000 + debit note 5000 − credited 20000
    # − paid 0 = outstanding 103000, not the old (118000 − 0) = 118000.
    db = _db_with_accounts()
    db.store.setdefault("client_sales_invoices", []).append(
        {"id": "inv-1", "firm_id": FIRM, "client_id": CLIENT, "invoice_no": "INV-1",
         "total_paise": 118000, "paid_paise": 0, "status": "issued",
         "debit_note_paise": 5000, "credited_paise": 20000})
    _seed_txn(db, credit=200000, category="Customer Payment",
              matched_type="sales_invoice", matched_id="inv-1")
    res = bank_posting_service.post(db, FIRM, "t1", bank_account_id="acc-bank", actor_id="u1")
    out = _approve(db, res["draft_journal_id"])
    inv = db.store["client_sales_invoices"][0]
    assert inv["paid_paise"] == 103000 and inv["status"] == "paid"
    assert out["settlement"]["allocated_paise"] == 103000   # NOT 118000 (old bug)


def test_bill_settlement_uses_tds_net_payable_not_gross_total():
    # task #102: for bills, the old formula used the GROSS total_paise instead
    # of the TDS-net net_payable_paise (IT Act §194C/194J — TDS withheld at
    # bill stage, so cash payable is net). Gross 100000, TDS-net payable
    # 90000, credit note 10000 → outstanding = 90000 + 10000 − 0 − 0 = 100000...
    # use a debited (debit note) too to prove the debited_paise term as well.
    db = _db_with_accounts()
    db.store.setdefault("purchase_bills", []).append(
        {"id": "bill-1", "firm_id": FIRM, "client_id": CLIENT, "bill_no": "BILL-1",
         "total_paise": 100000, "net_payable_paise": 90000, "paid_paise": 0,
         "status": "received", "credit_note_paise": 0, "debited_paise": 15000})
    # true outstanding = net_payable(90000) + credit_note(0) − paid(0) − debited(15000) = 75000
    _seed_txn(db, debit=200000, category="Vendor Payment",
              matched_type="purchase_bill", matched_id="bill-1")
    res = bank_posting_service.post(db, FIRM, "t1", bank_account_id="acc-bank", actor_id="u1")
    out = _approve(db, res["draft_journal_id"])
    bill = db.store["purchase_bills"][0]
    assert bill["paid_paise"] == 75000 and bill["status"] == "paid"
    assert out["settlement"]["allocated_paise"] == 75000   # NOT 100000 (old bug: gross total)


def test_settlement_excess_becomes_party_credit_not_lost():
    # task #102: a bank transaction matched for MORE than the invoice's true
    # outstanding used to just clamp the allocation and silently drop the
    # excess from tracking (the GL was already correct — the full amount was
    # posted to Trade Receivables — only the sub-ledger "whose money is this"
    # tracking was missing). The excess must now show up as a party credit.
    from services.party_credit_service import party_credit_service as PCS
    db = _db_with_accounts()
    db.store.setdefault("client_sales_invoices", []).append(
        {"id": "inv-1", "firm_id": FIRM, "client_id": CLIENT, "customer_id": "cust-1",
         "invoice_no": "INV-1", "total_paise": 100000, "paid_paise": 0, "status": "issued"})
    _seed_txn(db, credit=150000, category="Customer Payment",
              matched_type="sales_invoice", matched_id="inv-1")
    res = bank_posting_service.post(db, FIRM, "t1", bank_account_id="acc-bank", actor_id="u1")
    out = _approve(db, res["draft_journal_id"])
    inv = db.store["client_sales_invoices"][0]
    assert inv["paid_paise"] == 100000 and inv["status"] == "paid"
    assert out["settlement"]["allocated_paise"] == 100000
    assert out["settlement"]["credited_to_party_paise"] == 50000
    assert PCS.get_balance(db, FIRM, CLIENT, "customer", "cust-1") == 50000


def test_full_bill_settlement():
    db = _db_with_accounts(); _seed_bill(db, 59000)
    _seed_txn(db, debit=59000, category="Vendor Payment",
              matched_type="purchase_bill", matched_id="bill-1")
    res = bank_posting_service.post(db, FIRM, "t1", bank_account_id="acc-bank", actor_id="u1")
    _approve(db, res["draft_journal_id"])
    bill = db.store["purchase_bills"][0]
    assert bill["paid_paise"] == 59000 and bill["status"] == "paid"


def test_partial_bill_settlement():
    db = _db_with_accounts(); _seed_bill(db, 59000)
    _seed_txn(db, debit=20000, category="Vendor Payment",
              matched_type="purchase_bill", matched_id="bill-1")
    res = bank_posting_service.post(db, FIRM, "t1", bank_account_id="acc-bank", actor_id="u1")
    _approve(db, res["draft_journal_id"])
    bill = db.store["purchase_bills"][0]
    assert bill["paid_paise"] == 20000 and bill["status"] == "partially_paid"


# ── B.3.5 / protection ────────────────────────────────────────────────────────

def test_duplicate_post_rejected():
    db = _db_with_accounts(); _seed_txn(db, credit=100000, category="Customer Payment")
    bank_posting_service.post(db, FIRM, "t1", bank_account_id="acc-bank", actor_id="u1")
    with pytest.raises(Exception):
        bank_posting_service.post(db, FIRM, "t1", bank_account_id="acc-bank", actor_id="u1")


def test_fy_locked_blocks_post(monkeypatch):
    # Phase 3.5: the FY lock is enforced when the draft is APPROVED (books-hitting),
    # not when the draft is created.
    from fastapi import HTTPException
    db = _db_with_accounts(); _seed_txn(db, credit=100000, category="Customer Payment")
    res = bank_posting_service.post(db, FIRM, "t1", bank_account_id="acc-bank", actor_id="u1")
    def _locked(*a, **k):
        raise HTTPException(status_code=403, detail="FY locked")
    monkeypatch.setattr(jpsmod.period_validation_service, "validate_posting_date", _locked)
    with pytest.raises(HTTPException):
        _approve(db, res["draft_journal_id"])
    txn = db.store["bank_transactions"][0]
    assert txn.get("posted_at") is None and txn["match_status"] != "posted"  # never posted/settled


def test_missing_account_mapping_rejected():
    db = _db_with_accounts(); _seed_txn(db, debit=50000, category="Expense")  # needs account_id
    with pytest.raises(Exception):
        bank_posting_service.post(db, FIRM, "t1", bank_account_id="acc-bank", actor_id="u1")


def test_invalid_category_rejected():
    db = _db_with_accounts(); _seed_txn(db, credit=100000, category="Nonsense")
    with pytest.raises(Exception):
        bank_posting_service.post(db, FIRM, "t1", bank_account_id="acc-bank", actor_id="u1")


def test_deleted_transaction_404():
    db = _db_with_accounts()
    with pytest.raises(Exception):
        bank_posting_service.post(db, FIRM, "missing", bank_account_id="acc-bank", actor_id="u1")


# ── B.3 account resolution / tenant scoping (task #228 finding #3) ─────────────
# _resolve_bank's statement→bank_account lookup used to be unscoped by
# firm/client — a caller-supplied txn whose statement_id happened to match a
# statement belonging to a DIFFERENT client would silently resolve to that
# other client's GL bank account. Both lookups are now scoped to the
# transaction's own firm+client, mirroring _validate_account's scoping.

def test_resolve_bank_ignores_cross_client_statement_link():
    db = _db_with_accounts()
    _seed_txn(db, credit=100000, category="Customer Payment", statement_id="stmt-1")
    # A statement with the same id exists, but belongs to a different client —
    # must NOT be used to resolve the bank leg's GL account.
    db.store.setdefault("bank_statements", []).append(
        {"id": "stmt-1", "firm_id": FIRM, "client_id": "client-2", "bank_account_id": "ba-other"})
    db.store.setdefault("bank_accounts", []).append(
        {"id": "ba-other", "firm_id": FIRM, "client_id": "client-2", "coa_account_id": "acc-wrong"})
    res = bank_posting_service.post(db, FIRM, "t1", actor_id="u1")  # no bank_account_id passed
    lines = _lines_for(db, res["draft_journal_id"])
    dr = next(l for l in lines if l["debit_paise"])
    assert dr["account_id"] != "acc-wrong"
    assert dr["account_id"] == "acc-bank"   # falls back to the firm's master Bank account


def test_resolve_bank_uses_same_client_statement_link():
    db = _db_with_accounts()
    _seed_txn(db, credit=100000, category="Customer Payment", statement_id="stmt-1")
    db.store.setdefault("bank_statements", []).append(
        {"id": "stmt-1", "firm_id": FIRM, "client_id": CLIENT, "bank_account_id": "ba-1"})
    db.store.setdefault("bank_accounts", []).append(
        {"id": "ba-1", "firm_id": FIRM, "client_id": CLIENT, "coa_account_id": "acc-bank2"})
    res = bank_posting_service.post(db, FIRM, "t1", actor_id="u1")  # no bank_account_id passed
    lines = _lines_for(db, res["draft_journal_id"])
    dr = next(l for l in lines if l["debit_paise"])
    assert dr["account_id"] == "acc-bank2"  # resolved via own-client statement link


# ── Integrity ──────────────────────────────────────────────────────────────────

def test_audit_trail_created(monkeypatch):
    calls = []
    monkeypatch.setattr("services.audit_service.log_event",
                        lambda *a, **k: calls.append((a, k)))
    db = _db_with_accounts(); _seed_txn(db, credit=100000, category="Customer Payment")
    bank_posting_service.post(db, FIRM, "t1", bank_account_id="acc-bank", actor_id="u1")
    assert calls, "posting must write an audit event"
    args = calls[0][0]
    assert args[0] == FIRM and args[1] == "bank_transaction"


def test_paise_precision_preserved():
    db = _db_with_accounts(); _seed_txn(db, debit=12345, category="Expense")
    res = bank_posting_service.post(db, FIRM, "t1", bank_account_id="acc-bank",
                                    account_id="acc-exp", actor_id="u1")
    lines = _lines_for(db, res["draft_journal_id"])
    assert all(isinstance(l["debit_paise"], int) and isinstance(l["credit_paise"], int) for l in lines)
    assert sum(l["debit_paise"] for l in lines) == 12345
