"""
Bank transaction splits (Tier 1.2) — service, posting integration, endpoints.

test_bank_splits.py proves the arithmetic. This proves the WIRING: that a split
transaction posts as an n-leg journal instead of silently collapsing to two legs,
that splits are refused where they would produce a wrong ledger, and that the
atomic replace path is the only way they get written.
"""
import pytest
from fastapi import HTTPException

from models.banking import BankSplitLineIn, BankSplitsIn
import services.bank_posting_service as bps
from services.bank_posting_service import bank_posting_service
from services.bank_split_service import bank_split_service


FIRM, CLIENT = "firm-1", "client-1"
BANK, A1, A2 = "acc-bank", "acc-rent", "acc-maint"


class _Resp:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, store, table):
        self.s, self.t = store, table
        self.op, self.payload = "select", None
        self.eqs, self.ins = [], []
        self.limit_ = None
        self.single_ = False

    def select(self, *_a, **_k): self.op = "select"; return self
    def insert(self, p): self.op, self.payload = "insert", p; return self
    def update(self, p): self.op, self.payload = "update", p; return self
    def delete(self): self.op = "delete"; return self
    def eq(self, k, v): self.eqs.append((k, v)); return self
    def in_(self, k, vals): self.ins.append((k, set(vals))); return self
    def or_(self, *_a, **_k): return self
    def ilike(self, *_a, **_k): return self
    def is_(self, k, _v): self.eqs.append((k, None)); return self
    def limit(self, n): self.limit_ = n; return self
    def order(self, *_a, **_k): return self
    def single(self): self.single_ = True; return self
    def maybe_single(self): self.single_ = True; return self

    def _match(self):
        out = []
        for r in self.s.setdefault(self.t, []):
            if any(r.get(k) != v for k, v in self.eqs):
                continue
            if any(r.get(k) not in vals for k, vals in self.ins):
                continue
            out.append(r)
        return out

    def execute(self):
        rows = self.s.setdefault(self.t, [])
        if self.op == "insert":
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            ins = []
            for p in items:
                rec = dict(p); rec.setdefault("id", f"{self.t}-{len(rows) + 1}")
                rows.append(rec); ins.append(rec)
            return _Resp(ins)
        m = self._match()
        if self.op == "update":
            for r in m:
                r.update(self.payload)
            return _Resp(m)
        if self.op == "delete":
            for r in m:
                rows.remove(r)
            return _Resp(m)
        if self.single_:
            # The real client returns the ROW here, not a one-element list.
            return _Resp(m[0] if m else None)
        return _Resp(m[:self.limit_] if self.limit_ else m)


class _Rpc:
    """Stands in for replace_bank_transaction_splits.

    It re-implements the SAME refusals as the SQL function — that is the point:
    the service is supposed to have caught them already, so if this fake ever
    raises, a guard upstream is missing. Migration 256's own behaviour was
    verified separately against a real Postgres 16.
    """
    def __init__(self, db, name, params):
        self.db, self.name, self.params = db, name, params

    def execute(self):
        if self.name == "post_journal_atomic":
            return self._post_journal_atomic()
        if self.name != "replace_bank_transaction_splits":
            raise RuntimeError(f"Unstubbed RPC in this test's fake: {self.name}")
        return self._replace_splits()

    def _post_journal_atomic(self):
        """Mirrors migration 152 (and tests/e2e_harness) closely enough for the
        posting path: header + lines, with reference_no idempotency."""
        import uuid
        entry = dict(self.params["p_entry"])
        entries = self.db.store.setdefault("journal_entries", [])
        ref = entry.get("reference_no")
        if ref is not None:
            for r in entries:
                if (r.get("firm_id") == entry.get("firm_id")
                        and r.get("reference_no") == ref
                        and r.get("entry_date") == entry.get("entry_date")
                        and not r.get("deleted_at") and not r.get("is_reversed")):
                    return _Resp(r["id"])
        entry.setdefault("id", str(uuid.uuid4()))
        entries.append(entry)
        lines = self.db.store.setdefault("journal_lines", [])
        for l in self.params["p_lines"]:
            lr = dict(l); lr["journal_entry_id"] = entry["id"]
            lr.setdefault("id", str(uuid.uuid4()))
            lines.append(lr)
        return _Resp(entry["id"])

    def _replace_splits(self):
        p = self.params
        store = self.db.store
        txn = next((t for t in store.get("bank_transactions", [])
                    if t["id"] == p["p_txn_id"] and t["firm_id"] == p["p_firm_id"]), None)
        if not txn:
            raise RuntimeError("Bank transaction not found for this firm.")
        if txn.get("posted_journal_id"):
            raise RuntimeError("This transaction already has a journal.")
        amount = max(int(txn.get("debit_paise") or 0), int(txn.get("credit_paise") or 0))
        rows = store.setdefault("bank_transaction_splits", [])
        kept = [r for r in rows if r["bank_transaction_id"] != p["p_txn_id"]]
        new = p["p_splits"] or []
        if new:
            if any(int(s["amount_paise"]) <= 0 for s in new):
                raise RuntimeError("Every split must be a positive amount.")
            if len(new) < 2:
                raise RuntimeError("A split needs at least two lines.")
            if sum(int(s["amount_paise"]) for s in new) != amount:
                raise RuntimeError("The splits do not sum to the transaction amount.")
        store["bank_transaction_splits"] = kept + [{
            "id": f"sp-{i}", "firm_id": p["p_firm_id"], "client_id": txn["client_id"],
            "bank_transaction_id": p["p_txn_id"], "account_id": s["account_id"],
            "amount_paise": int(s["amount_paise"]), "narration": s.get("narration"),
            "sequence_no": i,
        } for i, s in enumerate(new)]
        return _Resp(store["bank_transaction_splits"])


class FakeDB:
    def __init__(self): self.store = {}
    def table(self, n): return _Q(self.store, n)
    def rpc(self, name, params): return _Rpc(self, name, params)


ACCOUNTS = [(BANK, "HDFC Bank", "bank"), (A1, "Rent", None), (A2, "Maintenance", None),
            ("acc-ar", "Trade Receivables", "ar"), ("acc-ap", "Trade Payables", "ap")]


def _db():
    db = FakeDB()
    db.store["chart_of_accounts"] = [
        {"id": i, "firm_id": FIRM, "client_id": None, "account_name": n,
         "system_account_key": k, "is_active": True} for (i, n, k) in ACCOUNTS]
    db.store["bank_transactions"] = []
    db.store["bank_transaction_splits"] = []
    return db


def _txn(db, *, debit=4720000, credit=0, category="Expense", **kw):
    row = {"id": "t1", "firm_id": FIRM, "client_id": CLIENT,
           "transaction_date": "2026-04-01", "description": "LANDLORD",
           "debit_paise": debit, "credit_paise": credit, "category": category,
           "match_status": "unmatched", "matched_entity_type": None,
           "matched_entity_id": None, "posted_journal_id": None, "statement_id": None}
    row.update(kw)
    db.store["bank_transactions"].append(row)
    return row


def _split(account, amount, narration=None):
    return {"account_id": account, "amount_paise": amount, "narration": narration}


@pytest.fixture(autouse=True)
def _silence(monkeypatch):
    monkeypatch.setattr(bps.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(bps.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    monkeypatch.setattr("services.audit_service.log_event", lambda *a, **k: None, raising=False)
    yield


def _lines(db, je_id):
    return [l for l in db.store.get("journal_lines", []) if l["journal_entry_id"] == je_id]


# ══════════════════════════════════════════════════════════════════════════════
# Replace
# ══════════════════════════════════════════════════════════════════════════════

def test_splits_that_tie_are_saved():
    db = _db(); _txn(db)
    out = bank_split_service.replace(db, FIRM, "t1",
                                     [_split(A1, 4000000, "April rent"), _split(A2, 720000)])
    assert out["is_split"] is True
    assert out["unallocated_paise"] == 0
    assert [s["amount_paise"] for s in out["splits"]] == [4000000, 720000]


def test_splits_that_do_not_tie_are_refused_with_the_shortfall():
    db = _db(); _txn(db)
    with pytest.raises(HTTPException) as ei:
        bank_split_service.replace(db, FIRM, "t1", [_split(A1, 4000000), _split(A2, 500000)])
    assert ei.value.status_code == 422
    assert "₹2,200.00" in ei.value.detail          # the gap, named


def test_a_refused_split_writes_nothing():
    db = _db(); _txn(db)
    with pytest.raises(HTTPException):
        bank_split_service.replace(db, FIRM, "t1", [_split(A1, 1), _split(A2, 2)])
    assert db.store["bank_transaction_splits"] == []


def test_replacing_a_split_does_not_leave_the_old_rows_behind():
    db = _db(); _txn(db)
    bank_split_service.replace(db, FIRM, "t1", [_split(A1, 4000000), _split(A2, 720000)])
    bank_split_service.replace(db, FIRM, "t1", [_split(A1, 4720000 - 1), _split(A2, 1)])
    rows = db.store["bank_transaction_splits"]
    assert len(rows) == 2 and sum(r["amount_paise"] for r in rows) == 4720000


def test_an_empty_list_clears_the_split():
    """Legitimate: it returns the transaction to an ordinary single-account post."""
    db = _db(); _txn(db)
    bank_split_service.replace(db, FIRM, "t1", [_split(A1, 4000000), _split(A2, 720000)])
    out = bank_split_service.replace(db, FIRM, "t1", [])
    assert out["is_split"] is False and db.store["bank_transaction_splits"] == []


def test_splitting_after_posting_is_refused():
    """The journal is immutable (migration 251), so editing the splits under it
    would leave the ledger and its explanation disagreeing."""
    db = _db(); _txn(db, posted_journal_id="je-1")
    with pytest.raises(HTTPException) as ei:
        bank_split_service.replace(db, FIRM, "t1", [_split(A1, 4000000), _split(A2, 720000)])
    assert ei.value.status_code == 409
    assert "Reverse it" in ei.value.detail


def test_a_matched_settling_transaction_cannot_be_split():
    """It settles the invoice in full. Crediting split accounts instead of Trade
    Receivables while still marking the invoice paid leaves the control account
    and the sub-ledger describing different worlds."""
    db = _db()
    _txn(db, debit=0, credit=4720000, category="Customer Payment",
         matched_entity_type="sales_invoice", matched_entity_id="inv-1")
    with pytest.raises(HTTPException) as ei:
        bank_split_service.replace(db, FIRM, "t1", [_split(A1, 4000000), _split(A2, 720000)])
    assert ei.value.status_code == 422 and "Unmatch" in ei.value.detail


def test_an_unmatched_customer_payment_can_still_be_split():
    """The guard is about SETTLEMENT, not the category."""
    db = _db(); _txn(db, debit=0, credit=4720000, category="Customer Payment")
    out = bank_split_service.replace(db, FIRM, "t1", [_split(A1, 4000000), _split(A2, 720000)])
    assert out["is_split"] is True


def test_another_firms_account_cannot_be_split_to():
    db = _db(); _txn(db)
    db.store["chart_of_accounts"].append(
        {"id": "foreign", "firm_id": "other-firm", "client_id": None,
         "account_name": "Theirs", "is_active": True})
    with pytest.raises(HTTPException) as ei:
        bank_split_service.replace(db, FIRM, "t1", [_split(A1, 4000000), _split("foreign", 720000)])
    assert ei.value.status_code == 422


def test_an_archived_account_cannot_be_split_to():
    db = _db(); _txn(db)
    next(a for a in db.store["chart_of_accounts"] if a["id"] == A2)["is_active"] = False
    with pytest.raises(HTTPException) as ei:
        bank_split_service.replace(db, FIRM, "t1", [_split(A1, 4000000), _split(A2, 720000)])
    assert ei.value.status_code == 422


def test_another_clients_account_cannot_be_split_to():
    db = _db(); _txn(db)
    next(a for a in db.store["chart_of_accounts"] if a["id"] == A2)["client_id"] = "client-2"
    with pytest.raises(HTTPException) as ei:
        bank_split_service.replace(db, FIRM, "t1", [_split(A1, 4000000), _split(A2, 720000)])
    assert ei.value.status_code == 422


def test_another_firms_transaction_is_not_found():
    db = _db(); _txn(db, firm_id="other-firm")
    with pytest.raises(HTTPException) as ei:
        bank_split_service.replace(db, FIRM, "t1", [_split(A1, 4000000), _split(A2, 720000)])
    assert ei.value.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Posting a split transaction
# ══════════════════════════════════════════════════════════════════════════════

def test_a_split_transaction_posts_an_n_leg_journal():
    """THE integration. Before this, the whole ₹47,200 landed on one account."""
    db = _db(); _txn(db)
    bank_split_service.replace(db, FIRM, "t1",
                               [_split(A1, 4000000, "April rent"), _split(A2, 720000, "Lift AMC")])
    je = bank_posting_service.post(db, FIRM, "t1", bank_account_id=BANK,
                                   actor_id="u1")["posted_journal_id"]
    lines = _lines(db, je)
    assert len(lines) == 3
    by_acc = {l["account_id"]: l for l in lines}
    assert by_acc[A1]["debit_paise"] == 4000000
    assert by_acc[A2]["debit_paise"] == 720000
    assert by_acc[BANK]["credit_paise"] == 4720000
    assert sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines)


def test_a_split_receipt_credits_each_account_and_debits_the_bank_once():
    db = _db(); _txn(db, debit=0, credit=4720000, category="Other")
    bank_split_service.replace(db, FIRM, "t1", [_split(A1, 4000000), _split(A2, 720000)])
    je = bank_posting_service.post(db, FIRM, "t1", bank_account_id=BANK,
                                   actor_id="u1")["posted_journal_id"]
    lines = _lines(db, je)
    bank_lines = [l for l in lines if l["account_id"] == BANK]
    assert len(bank_lines) == 1 and bank_lines[0]["debit_paise"] == 4720000


def test_a_split_needs_no_counter_account_to_post():
    """The splits ARE the counter accounts, so the ordinary 'select a GL account'
    requirement for an Expense must not still apply."""
    db = _db(); _txn(db, category="Expense")
    bank_split_service.replace(db, FIRM, "t1", [_split(A1, 4000000), _split(A2, 720000)])
    res = bank_posting_service.post(db, FIRM, "t1", bank_account_id=BANK, actor_id="u1")
    assert res["posted_journal_id"]


def test_an_unsplit_transaction_still_posts_two_legs():
    """Regression guard: everything that worked before must be untouched."""
    db = _db(); _txn(db)
    je = bank_posting_service.post(db, FIRM, "t1", bank_account_id=BANK,
                                   account_id=A1, actor_id="u1")["posted_journal_id"]
    assert len(_lines(db, je)) == 2


def test_the_preview_shows_the_split_legs():
    db = _db(); _txn(db)
    bank_split_service.replace(db, FIRM, "t1", [_split(A1, 4000000), _split(A2, 720000)])
    out = bank_posting_service.preview(db, FIRM, "t1", bank_account_id=BANK)
    assert len(out["lines"]) == 3
    assert out["total_debit_paise"] == out["total_credit_paise"] == 4720000


def test_a_split_transfer_is_refused():
    db = _db(); _txn(db, category="Transfer")
    bank_split_service.replace(db, FIRM, "t1", [_split(A1, 4000000), _split(A2, 720000)])
    with pytest.raises(HTTPException) as ei:
        bank_posting_service.post(db, FIRM, "t1", bank_account_id=BANK,
                                  to_bank_account_id=A1, actor_id="u1")
    assert ei.value.status_code == 422 and "cannot be split" in ei.value.detail


def test_combining_a_split_with_a_gst_rate_is_refused():
    """Both decide the non-bank legs. Doing them together needs a rate PER split
    — refuse rather than silently applying one and dropping the other."""
    db = _db(); _txn(db)
    bank_split_service.replace(db, FIRM, "t1", [_split(A1, 4000000), _split(A2, 720000)])
    with pytest.raises(HTTPException) as ei:
        bank_posting_service.post(db, FIRM, "t1", bank_account_id=BANK,
                                  actor_id="u1", gst_rate_bps=1800)
    assert ei.value.status_code == 422 and "cannot be combined" in ei.value.detail


def test_splitting_first_and_matching_afterwards_still_refuses_to_post():
    """The ORDERING the replace-time guard cannot see: split a transaction while
    it is unmatched, then match it to an invoice, then post. Without the guard in
    _plan the journal would credit the split accounts while settle_on_post marks
    the invoice paid — the control account and the sub-ledger describing
    different worlds. This is why the check exists in BOTH places."""
    db = _db()
    _txn(db, debit=0, credit=4720000, category="Customer Payment")
    bank_split_service.replace(db, FIRM, "t1", [_split(A1, 4000000), _split(A2, 720000)])
    # ... matched afterwards, by a different code path than the split editor.
    db.store["bank_transactions"][0].update(
        {"matched_entity_type": "sales_invoice", "matched_entity_id": "inv-1"})
    with pytest.raises(HTTPException) as ei:
        bank_posting_service.post(db, FIRM, "t1", bank_account_id=BANK, actor_id="u1")
    assert ei.value.status_code == 422 and "Unmatch" in ei.value.detail
    assert db.store.get("journal_entries", []) == []


def test_a_stored_split_that_stops_tying_refuses_to_post():
    """Nothing edits a bank amount today, but posting a journal from splits that
    no longer tie must fail loudly rather than balance by luck."""
    db = _db(); _txn(db)
    bank_split_service.replace(db, FIRM, "t1", [_split(A1, 4000000), _split(A2, 720000)])
    db.store["bank_transactions"][0]["debit_paise"] = 5000000     # amount moved underneath
    with pytest.raises(HTTPException) as ei:
        bank_posting_service.post(db, FIRM, "t1", bank_account_id=BANK, actor_id="u1")
    assert ei.value.status_code == 422 and "no longer matches" in ei.value.detail


def test_a_posted_split_transaction_keeps_its_splits_readable():
    db = _db(); _txn(db)
    bank_split_service.replace(db, FIRM, "t1", [_split(A1, 4000000), _split(A2, 720000)])
    bank_posting_service.post(db, FIRM, "t1", bank_account_id=BANK, actor_id="u1")
    out = bank_split_service.get(db, FIRM, "t1")
    assert out["is_split"] is True and out["editable"] is False


# ══════════════════════════════════════════════════════════════════════════════
# Request validation
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("bad", [0, -1, -4720000])
def test_the_model_refuses_a_non_positive_split(bad):
    with pytest.raises(ValueError):
        BankSplitLineIn(account_id=A1, amount_paise=bad)


def test_the_model_refuses_a_split_with_no_account():
    with pytest.raises(ValueError):
        BankSplitLineIn(account_id="   ", amount_paise=100)


def test_the_model_allows_an_empty_list_so_a_split_can_be_cleared():
    assert BankSplitsIn(splits=[]).splits == []


# ══════════════════════════════════════════════════════════════════════════════
# The endpoints
# ══════════════════════════════════════════════════════════════════════════════

PARTNER = {"firm_id": FIRM, "role": "Partner", "auth_user_id": "p1", "id": "u1"}


@pytest.fixture
def routed(monkeypatch):
    import core.authz as authz
    import routers.banking as br
    db = _db(); _txn(db)
    monkeypatch.setattr(br, "_db", lambda: db)
    monkeypatch.setattr(authz, "_USE_MOCK", True)
    return db, br


def test_the_put_endpoint_saves_and_the_get_reads_back(routed):
    db, br = routed
    res = br.replace_transaction_splits("t1", BankSplitsIn(splits=[
        BankSplitLineIn(account_id=A1, amount_paise=4000000),
        BankSplitLineIn(account_id=A2, amount_paise=720000),
    ]), current_user=PARTNER)
    assert res["success"] is True and res["data"]["unallocated_paise"] == 0
    got = br.get_transaction_splits("t1", current_user=PARTNER)
    assert len(got["data"]["splits"]) == 2 and got["data"]["editable"] is True


def test_the_put_endpoint_surfaces_a_shortfall_as_422(routed):
    _, br = routed
    with pytest.raises(HTTPException) as ei:
        br.replace_transaction_splits("t1", BankSplitsIn(splits=[
            BankSplitLineIn(account_id=A1, amount_paise=4000000),
            BankSplitLineIn(account_id=A2, amount_paise=500000),
        ]), current_user=PARTNER)
    assert ei.value.status_code == 422
