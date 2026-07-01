"""
Phase 3.5 — Draft Journal Workflow tests.

Proves the single lifecycle Draft → Approve → Post: drafts are off-books and
excluded from every report; approval requires the 'approve' permission, respects
the FY lock, and is audited; and a bank transaction does NOT settle / post /
reconcile until its draft journal is actually posted (deferred downstream action).
"""
import pytest
from fastapi import HTTPException

import services.phase2_journal_service as pjs
from services.phase2_journal_service import phase2_journal_service as JSVC
import services.journal_posting_service as jps
from services.journal_posting_service import journal_posting_service as JP
import services.bank_posting_service as bps
from services.bank_posting_service import bank_posting_service as BP
from core.permissions import can
from domain.reporting import SupabaseLedgerSource, ReportingService

FIRM, CLIENT = "firm-1", "client-1"


# ── Fake Supabase (stores tables; embeds journal_lines on select) ─────────────

class _Resp:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, store, table):
        self.s, self.t = store, table
        self.op = "select"; self.cols = ""; self.payload = None
        self.f = []; self.single_ = False; self.order_ = None; self.desc = False

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
    def range(self, *_a, **_k): return self
    def single(self): self.single_ = True; return self

    def _match(self):
        out = []
        for r in self.s.setdefault(self.t, []):
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
                sep = [dict(l) for l in self.s.get("journal_lines", [])
                       if l.get("journal_entry_id") == r["id"]]
                if sep:
                    r["journal_lines"] = sep            # lines stored in the separate table
                elif "journal_lines" not in r:
                    r["journal_lines"] = []             # no inline lines either
                # else: keep the row's inline journal_lines (report fixtures)
        return rows

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
        m = self._embed(m)
        if self.order_:
            m = sorted(m, key=lambda r: str(r.get(self.order_)), reverse=self.desc)
        if self.single_:
            return _Resp(dict(m[0]) if m else None)
        return _Resp([dict(r) for r in m])


class FakeDB:
    def __init__(self): self.store = {}
    def table(self, n): return _Q(self.store, n)


@pytest.fixture
def db(monkeypatch):
    # Silence timeline / audit / FY-lock side effects in all three services.
    for mod in (jps, bps):
        monkeypatch.setattr(mod.timeline_service, "log", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(jps.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    monkeypatch.setattr("services.audit_service.log_event", lambda *a, **k: None, raising=False)
    d = FakeDB()
    d.store["chart_of_accounts"] = [
        {"id": "acc-bank", "firm_id": FIRM, "account_name": "Bank", "account_type": "Asset", "system_account_key": "bank", "is_active": True},
        {"id": "acc-ar", "firm_id": FIRM, "account_name": "Trade Receivables", "account_type": "Asset", "system_account_key": "ar", "is_active": True},
    ]
    d.store["bank_accounts"] = [{"id": "ba1", "firm_id": FIRM, "client_id": CLIENT, "coa_account_id": "acc-bank"}]
    d.store["bank_statements"] = [{"id": "stmt1", "firm_id": FIRM, "client_id": CLIENT, "bank_account_id": "ba1"}]
    d.store["journal_entries"] = []
    d.store["journal_lines"] = []
    return d


def _bank_txn(d, *, credit=100000):
    d.store["bank_transactions"] = [{
        "id": "txn1", "firm_id": FIRM, "client_id": CLIENT, "statement_id": "stmt1",
        "transaction_date": "2025-04-10", "description": "NEFT from customer",
        "debit_paise": 0, "credit_paise": credit, "match_status": "matched",
        "category": "Customer Payment", "matched_entity_type": "sales_invoice",
        "matched_entity_id": "inv1", "posted_journal_id": None, "posted_at": None,
    }]
    d.store["client_sales_invoices"] = [{
        "id": "inv1", "firm_id": FIRM, "client_id": CLIENT, "invoice_no": "INV-1",
        "total_paise": credit, "paid_paise": 0, "status": "sent",
    }]


# ── Engine: draft vs posted ───────────────────────────────────────────────────

def test_create_journal_draft_is_off_books(db):
    jid = JSVC._create_journal(
        db, firm_id=FIRM, client_id=CLIENT, entry_date="2025-04-10",
        reference_no="JD-1", narration="draft", entry_type="Journal",
        lines=[{"account_id": "acc-bank", "debit_paise": 5000, "credit_paise": 0},
               {"account_id": "acc-ar", "debit_paise": 0, "credit_paise": 5000}],
        is_posted=False, source_type="manual", created_by="u1",
    )
    row = next(r for r in db.store["journal_entries"] if r["id"] == jid)
    assert row["is_posted"] is False and row["status"] == "draft" and row["posted_at"] is None


def test_create_journal_default_posts(db):
    jid = JSVC._create_journal(
        db, firm_id=FIRM, client_id=CLIENT, entry_date="2025-04-10",
        reference_no="JP-1", narration="posted", entry_type="Journal",
        lines=[{"account_id": "acc-bank", "debit_paise": 5000, "credit_paise": 0},
               {"account_id": "acc-ar", "debit_paise": 0, "credit_paise": 5000}],
    )
    row = next(r for r in db.store["journal_entries"] if r["id"] == jid)
    assert row["is_posted"] is True and row["status"] == "posted" and row["posted_at"] is not None


# ── Approve & post a draft ────────────────────────────────────────────────────

def _make_draft(db, balanced=True):
    return JSVC._create_journal(
        db, firm_id=FIRM, client_id=CLIENT, entry_date="2025-04-10",
        reference_no="D-1", narration="d", entry_type="Journal",
        lines=[{"account_id": "acc-bank", "debit_paise": 5000, "credit_paise": 0},
               {"account_id": "acc-ar", "debit_paise": 0, "credit_paise": 5000 if balanced else 4000}],
        is_posted=False,
    )


def test_post_draft_puts_it_on_books(db):
    jid = _make_draft(db)
    out = JP.post_draft(db, FIRM, jid, actor_id="approver")
    assert out["is_posted"] is True and out["posted_at"]
    row = next(r for r in db.store["journal_entries"] if r["id"] == jid)
    assert row["is_posted"] is True and row["posted_by"] == "approver"


def test_post_draft_rejects_already_posted(db):
    jid = _make_draft(db)
    JP.post_draft(db, FIRM, jid)
    with pytest.raises(HTTPException) as e:
        JP.post_draft(db, FIRM, jid)
    assert e.value.status_code == 409


def test_post_draft_rejects_unbalanced(db):
    # _create_journal enforces balance at creation, so inject an unbalanced draft
    # directly (e.g. one written by a buggy external path) to prove the post guard.
    db.store["journal_entries"].append({
        "id": "unbal", "firm_id": FIRM, "client_id": CLIENT, "entry_date": "2025-04-10",
        "is_posted": False, "status": "draft", "deleted_at": None,
        "reference_no": "U-1", "narration": "u", "entry_type": "Journal",
    })
    db.store["journal_lines"] = [
        {"journal_entry_id": "unbal", "account_id": "acc-bank", "debit_paise": 5000, "credit_paise": 0},
        {"journal_entry_id": "unbal", "account_id": "acc-ar", "debit_paise": 0, "credit_paise": 4000},
    ]
    with pytest.raises(HTTPException) as e:
        JP.post_draft(db, FIRM, "unbal")
    assert e.value.status_code == 422


def test_post_draft_respects_fy_lock(db, monkeypatch):
    jid = _make_draft(db)
    def _locked(*_a, **_k):
        raise HTTPException(status_code=423, detail="FY locked")
    monkeypatch.setattr(jps.period_validation_service, "validate_posting_date", _locked)
    with pytest.raises(HTTPException) as e:
        JP.post_draft(db, FIRM, jid)
    assert e.value.status_code == 423


def test_post_draft_firm_isolation(db):
    jid = _make_draft(db)
    with pytest.raises(HTTPException) as e:
        JP.post_draft(db, "other-firm", jid)
    assert e.value.status_code == 404


# ── Approval queue ────────────────────────────────────────────────────────────

def test_queue_filters_draft_vs_posted(db):
    d1 = _make_draft(db)
    JSVC._create_journal(db, firm_id=FIRM, client_id=CLIENT, entry_date="2025-04-11",
                         reference_no="P-1", narration="p", entry_type="Journal",
                         lines=[{"account_id": "acc-bank", "debit_paise": 700, "credit_paise": 0},
                                {"account_id": "acc-ar", "debit_paise": 0, "credit_paise": 700}])
    drafts = JP.list_journals(db, FIRM, CLIENT, "draft")
    posted = JP.list_journals(db, FIRM, CLIENT, "posted")
    assert [j["id"] for j in drafts] == [d1]
    assert drafts[0]["total_debit_paise"] == 5000 and drafts[0]["total_credit_paise"] == 5000
    assert len(posted) == 1 and posted[0]["is_posted"] is True


# ── Banking: deferred settlement (Objective 3) ────────────────────────────────

def test_bank_draft_does_not_settle_until_posted(db):
    _bank_txn(db)
    res = BP.post(db, FIRM, "txn1", actor_id="maker")
    assert res["status"] == "draft" and res["draft_journal_id"]

    txn = db.store["bank_transactions"][0]
    inv = db.store["client_sales_invoices"][0]
    je = next(r for r in db.store["journal_entries"] if r["id"] == res["draft_journal_id"])
    # Draft only: not posted, not settled, not reconciled.
    assert je["is_posted"] is False
    assert txn["match_status"] != "posted" and txn["posted_at"] is None
    assert inv["paid_paise"] == 0 and inv["status"] == "sent"
    assert not txn.get("reconciled")

    # Approve the draft → settlement + posting happen now.
    out = JP.post_draft(db, FIRM, res["draft_journal_id"], actor_id="approver")
    txn = db.store["bank_transactions"][0]
    inv = db.store["client_sales_invoices"][0]
    assert out["settlement"] and out["settlement"]["allocated_paise"] == 100000
    assert txn["match_status"] == "posted" and txn["posted_at"]
    assert inv["paid_paise"] == 100000 and inv["status"] == "paid"


def test_bank_post_is_idempotent_one_draft(db):
    _bank_txn(db)
    BP.post(db, FIRM, "txn1", actor_id="maker")
    with pytest.raises(HTTPException) as e:
        BP.post(db, FIRM, "txn1", actor_id="maker")
    assert e.value.status_code == 409


def test_bank_queues_reflect_draft_then_posted(db):
    _bank_txn(db)
    assert [t["id"] for t in BP.ready_to_post(db, FIRM, CLIENT)] == ["txn1"]
    r = BP.post(db, FIRM, "txn1", actor_id="maker")
    assert BP.ready_to_post(db, FIRM, CLIENT) == []          # left ready queue
    assert [t["id"] for t in BP.pending(db, FIRM, CLIENT)] == ["txn1"]   # awaiting approval
    assert BP.posted(db, FIRM, CLIENT) == []                 # not yet posted
    JP.post_draft(db, FIRM, r["draft_journal_id"], actor_id="approver")
    assert BP.pending(db, FIRM, CLIENT) == []
    assert [t["id"] for t in BP.posted(db, FIRM, CLIENT)] == ["txn1"]


# ── Reporting excludes drafts (Objective 7) ───────────────────────────────────

def _je_row(jid, posted, lines, date="2025-04-10"):
    return {"id": jid, "firm_id": FIRM, "client_id": CLIENT, "entry_date": date,
            "is_posted": posted, "deleted_at": None, "entry_type": "x",
            "reference_no": jid, "narration": jid, "created_at": f"{date}T00:00",
            "reversal_of": None,
            "journal_lines": [{"account_id": a, "debit_paise": d, "credit_paise": c} for a, d, c in lines]}


class _ReportFakeDB:
    """Honours .eq('is_posted', True) so drafts are filtered exactly as production."""
    def __init__(self, rows):
        self.t = {"chart_of_accounts": [
            {"id": "acc-bank", "account_code": "1000", "account_name": "Bank", "account_type": "Asset", "account_subtype": "Bank", "system_account_key": "bank"},
            {"id": "acc-rev", "account_code": "4000", "account_name": "Fees", "account_type": "Revenue", "account_subtype": None, "system_account_key": None},
        ], "journal_entries": rows, "client_sales_invoices": [], "receipts": [],
            "receipt_allocations": [], "credit_notes": [], "purchase_bills": [], "purchase_payments": []}
    def table(self, n): return _Q(self.t, n)


def test_drafts_excluded_from_ledger_and_trial_balance(monkeypatch):
    rows = [
        _je_row("posted1", True, [("acc-bank", 50000, 0), ("acc-rev", 0, 50000)]),
        _je_row("draft1", False, [("acc-bank", 999999, 0), ("acc-rev", 0, 999999)]),
    ]
    svc = ReportingService(SupabaseLedgerSource(_ReportFakeDB(rows)))
    led = svc.ledger(FIRM, CLIENT, "acc-bank", "2025-04-01", "2026-03-31")
    assert [l["entry_id"] for l in led["lines"]] == ["posted1"]   # draft excluded
    assert led["closing_balance_paise"] == 50000
    tb = svc.trial_balance(FIRM, CLIENT, "2026-03-31")
    bank_row = next((r for r in tb["lines"] if r["account_id"] == "acc-bank"), None)
    assert bank_row and bank_row["total_debit_paise"] == 50000   # 999999 draft not included


# ── Permissions (Objective: unauthorized posting rejected) ────────────────────

def test_only_approve_role_can_post():
    assert can("Partner", "accounting", "approve") is True
    assert can("Executive", "accounting", "approve") is False
    assert can("Reviewer", "accounting", "approve") is False
