"""
Banking B.4 — Reconciliation Engine tests.

Covers the pure tie-out math and the full service: session lifecycle, manual
reconcile/unreconcile, the balance tie-out (perfect / unreconciled deposits /
unreconciled withdrawals / mismatch), completion + reopen prevention, the
report + CSV, posted-only enforcement, and firm isolation.
"""
import pytest
from fastapi import HTTPException

from domain.banking import reconciliation as recon
import services.bank_reconciliation_service as brs
from services.bank_reconciliation_service import bank_reconciliation_service as svc


# ── Pure tie-out math ─────────────────────────────────────────────────────────

def test_tie_out_perfect():
    r = recon.tie_out(opening_balance_paise=100000, closing_balance_paise=160000,
                      deposits_paise=80000, withdrawals_paise=20000)
    assert r["reconciled_book_balance_paise"] == 160000
    assert r["difference_paise"] == 0 and r["reconciles"] is True


def test_tie_out_mismatch_and_adjustments():
    r = recon.tie_out(opening_balance_paise=100000, closing_balance_paise=160000,
                      deposits_paise=80000, withdrawals_paise=25000)
    assert r["difference_paise"] == 5000 and r["reconciles"] is False
    # A documented +5000 adjustment closes the gap exactly.
    r2 = recon.tie_out(opening_balance_paise=100000, closing_balance_paise=160000,
                       deposits_paise=80000, withdrawals_paise=25000, adjustments_paise=5000)
    assert r2["reconciles"] is True


def test_split_amounts_integer_paise():
    deposits, withdrawals = recon.split_amounts([
        {"credit_paise": 50000, "debit_paise": 0},
        {"credit_paise": 30000, "debit_paise": 0},
        {"credit_paise": 0, "debit_paise": 20000},
    ])
    assert deposits == 80000 and withdrawals == 20000


# ── Fake Supabase (same shape as the B.3 suite) ───────────────────────────────

class _Resp:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, store, table):
        self.s, self.t = store, table
        self.op = "select"; self.payload = None; self.f = []
        self.single_ = False; self.order_ = None; self.desc = False

    def insert(self, p): self.op, self.payload = "insert", p; return self
    def update(self, p): self.op, self.payload = "update", p; return self
    def select(self, *a, **k): self.op = "select"; return self
    def eq(self, k, v): self.f.append((k, v)); return self
    def in_(self, k, vals): self.f.append((k, ("__in__", list(vals)))); return self
    def limit(self, _n): return self
    def order(self, c, desc=False): self.order_, self.desc = c, desc; return self
    def single(self): self.single_ = True; return self

    def _match(self):
        out = []
        for r in self.s.setdefault(self.t, []):
            ok = True
            for k, v in self.f:
                if isinstance(v, tuple) and v and v[0] == "__in__":
                    if r.get(k) not in v[1]: ok = False; break
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
                rows.append(rec); ins.append(rec)
            return _Resp(ins)
        m = self._match()
        if self.op == "update":
            for r in m: r.update(self.payload)
            return _Resp(m)
        if self.order_:
            m = sorted(m, key=lambda r: str(r.get(self.order_)), reverse=self.desc)
        if self.single_:
            return _Resp(m[0] if m else None)
        return _Resp(m)


class FakeDB:
    def __init__(self): self.store = {}
    def table(self, n): return _Q(self.store, n)


FIRM, CLIENT, BA = "firm-1", "client-1", "ba-1"
START, END = "2025-04-01", "2025-04-30"


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(brs.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr("services.audit_service.log_event", lambda *a, **k: None, raising=False)
    d = FakeDB()
    d.store["bank_accounts"] = [
        {"id": BA, "firm_id": FIRM, "client_id": CLIENT, "bank_name": "HDFC",
         "account_no": "0001", "coa_account_id": "coa-bank"},
    ]
    d.store["bank_statements"] = [
        {"id": "stmt-1", "firm_id": FIRM, "client_id": CLIENT, "bank_account_id": BA,
         "statement_from": START, "statement_to": END},
    ]
    # Three posted txns in-period; one un-posted (not eligible).
    d.store["bank_transactions"] = [
        _txn("t1", credit=50000), _txn("t2", debit=20000), _txn("t3", credit=30000),
        _txn("t4", credit=99999, posted=False),
    ]
    d.store["bank_reconciliations"] = []
    return d


def _txn(tid, *, debit=0, credit=0, date="2025-04-10", posted=True):
    return {
        "id": tid, "firm_id": FIRM, "client_id": CLIENT, "statement_id": "stmt-1",
        "transaction_date": date, "description": f"txn {tid}", "reference_no": tid.upper(),
        "debit_paise": debit, "credit_paise": credit, "match_status": "posted" if posted else "matched",
        "posted_journal_id": f"je-{tid}" if posted else None, "reconciliation_id": None,
        "reconciled": False,
    }


def _open(db, opening=100000, closing=160000):
    return svc.create_session(db, FIRM, CLIENT, BA, START, END,
                              opening_balance_paise=opening, closing_balance_paise=closing,
                              actor_id="user-1")["id"]


# ── Session lifecycle ─────────────────────────────────────────────────────────

def test_create_session_opens(db):
    s = svc.create_session(db, FIRM, CLIENT, BA, START, END, 100000, 160000)
    assert s["status"] == "open"
    assert s["statement_start_date"] == START and s["statement_end_date"] == END
    assert s["opening_balance_paise"] == 100000


def test_manual_reconcile_advances_to_in_progress_and_sets_flag(db):
    rid = _open(db)
    out = svc.reconcile(db, FIRM, rid, ["t1"], actor_id="user-1")
    assert out["status"] == "in_progress"
    t1 = next(t for t in db.store["bank_transactions"] if t["id"] == "t1")
    assert t1["reconciled"] is True and t1["reconciliation_id"] == rid
    assert t1["reconciled_journal_id"] == "je-t1"
    assert out["counts"]["reconciled"] == 1 and out["counts"]["unreconciled"] == 2


def test_manual_unreconcile_clears_flag(db):
    rid = _open(db)
    svc.reconcile(db, FIRM, rid, ["t1"])
    svc.unreconcile(db, FIRM, rid, ["t1"])
    t1 = next(t for t in db.store["bank_transactions"] if t["id"] == "t1")
    assert t1["reconciled"] is False and t1["reconciliation_id"] is None


# ── Balance tie-out ───────────────────────────────────────────────────────────

def test_perfect_reconciliation_ties_out_and_completes(db):
    rid = _open(db, 100000, 160000)
    out = svc.reconcile(db, FIRM, rid, ["t1", "t2", "t3"])
    assert out["summary"]["reconciles"] is True
    done = svc.complete(db, FIRM, rid, actor_id="user-1")
    assert done["status"] == "completed" and done["completed_at"] is not None


def test_unreconciled_deposit_blocks_completion(db):
    rid = _open(db, 100000, 160000)
    svc.reconcile(db, FIRM, rid, ["t2", "t3"])      # leave deposit t1 (50000) unreconciled
    rep = svc.report(db, FIRM, rid)
    assert rep["ties_out"] is False
    assert rep["summary"]["difference_paise"] == 50000
    with pytest.raises(HTTPException) as e:
        svc.complete(db, FIRM, rid)
    assert e.value.status_code == 422


def test_unreconciled_withdrawal_blocks_completion(db):
    rid = _open(db, 100000, 160000)
    svc.reconcile(db, FIRM, rid, ["t1", "t3"])      # leave withdrawal t2 (20000) unreconciled
    rep = svc.report(db, FIRM, rid)
    assert rep["ties_out"] is False
    assert rep["summary"]["difference_paise"] == -20000
    with pytest.raises(HTTPException):
        svc.complete(db, FIRM, rid)


def test_balance_mismatch_blocks_completion(db):
    rid = _open(db, 100000, 999999)                 # wrong closing balance
    svc.reconcile(db, FIRM, rid, ["t1", "t2", "t3"])
    rep = svc.report(db, FIRM, rid)
    assert rep["ties_out"] is False
    with pytest.raises(HTTPException) as e:
        svc.complete(db, FIRM, rid)
    assert e.value.status_code == 422


def test_adjustment_makes_it_tie_out(db):
    rid = _open(db, 100000, 165000)                 # 5000 more than txns imply
    svc.reconcile(db, FIRM, rid, ["t1", "t2", "t3"])
    svc.update_session(db, FIRM, rid, {"adjustments_paise": 5000})
    assert svc.report(db, FIRM, rid)["ties_out"] is True
    assert svc.complete(db, FIRM, rid)["status"] == "completed"


# ── Reopen prevention (immutable after completion) ────────────────────────────

def test_completed_session_is_immutable(db):
    rid = _open(db, 100000, 160000)
    svc.reconcile(db, FIRM, rid, ["t1", "t2", "t3"])
    svc.complete(db, FIRM, rid)
    for call in (
        lambda: svc.reconcile(db, FIRM, rid, ["t1"]),
        lambda: svc.unreconcile(db, FIRM, rid, ["t1"]),
        lambda: svc.update_session(db, FIRM, rid, {"closing_balance_paise": 1}),
        lambda: svc.complete(db, FIRM, rid),
    ):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 409


# ── Posted-only + protection ──────────────────────────────────────────────────

def test_cannot_reconcile_unposted_transaction(db):
    rid = _open(db)
    with pytest.raises(HTTPException) as e:
        svc.reconcile(db, FIRM, rid, ["t4"])        # t4 has no posted_journal_id
    assert e.value.status_code == 422


def test_cannot_reconcile_out_of_period(db):
    db.store["bank_transactions"].append(_txn("t5", credit=1000, date="2025-05-15"))
    rid = _open(db)
    with pytest.raises(HTTPException) as e:
        svc.reconcile(db, FIRM, rid, ["t5"])
    assert e.value.status_code == 422


# ── Report + CSV ──────────────────────────────────────────────────────────────

def test_report_structure_and_csv(db):
    rid = _open(db, 100000, 160000)
    svc.reconcile(db, FIRM, rid, ["t1", "t2"])      # t3 left unreconciled
    rep = svc.report(db, FIRM, rid)
    assert {"reconciliation", "summary", "ties_out", "reconciled", "unreconciled", "exceptions"} <= rep.keys()
    assert rep["counts"]["reconciled"] == 2 and rep["counts"]["unreconciled"] == 1

    csv_text = svc.report_csv(db, FIRM, rid)
    assert "Bank Reconciliation Report" in csv_text
    assert "Reconciled book balance" in csv_text
    assert "reconciled" in csv_text and "unreconciled" in csv_text
    # one data row per transaction (3 posted txns appear across the sections)
    assert csv_text.count("txn t1") == 1


# ── Firm isolation ────────────────────────────────────────────────────────────

def test_firm_isolation(db):
    rid = _open(db)
    with pytest.raises(HTTPException) as e:
        svc.get_session(db, "other-firm", rid)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException):
        svc.reconcile(db, "other-firm", rid, ["t1"])
