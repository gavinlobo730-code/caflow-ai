"""
Undo a POSTED bank transaction.

WHAT WAS WRONG
    The queue has shown an "Undo" button on every posted row since it was
    built. It called bank_matching_service.unmatch, which begins:

        if txn.get("match_status") == "posted":
            raise HTTPException(409, "Cannot unmatch a posted transaction.")

    The button rendered on exactly the rows the endpoint refused, so every
    click was a 409. Nothing caught it because the /unmatch route had a
    mock-mode early return that answered `success` without touching anything —
    the suite exercised a no-op, which is the one thing a fake must never
    silently become.

WHAT UNDO HAS TO PUT BACK
    Posting did three things and all three are unwound here:
      1. a balanced journal        → REVERSED, never deleted (CLAUDE.md)
      2. paid_paise + status on the invoice or bill it settled
      3. a party credit, when it settled more than was owed (migration 284)

    Plus the row itself, which goes back to `matched` — not `unmatched` —
    when a document is still linked. Undoing the POSTING is not undoing the
    CA's identification of which invoice it was.
"""
import pytest
from fastapi import HTTPException

import services.bank_posting_service as bps
from services.bank_posting_service import bank_posting_service as svc
import services.journal_posting_service as jpsmod
from services.party_credit_service import party_credit_service

FIRM, CLIENT = "firm-1", "client-1"

ACCOUNTS = [
    ("acc-bank", "HDFC Bank", "bank"),
    ("acc-ar", "Trade Receivables", "ar"),
    ("acc-ap", "Trade Payables", "ap"),
    ("acc-rev", "Sales Revenue", "revenue"),
    ("acc-exp", "Office Rent", None),
]


class _Resp:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, store, table):
        self.s, self.t = store, table
        self.op, self.payload, self.f = "select", None, []
        self.single_ = False

    def insert(self, p): self.op, self.payload = "insert", p; return self
    def update(self, p): self.op, self.payload = "update", p; return self
    def select(self, *_a, **_k): self.op = "select"; return self
    def eq(self, k, v): self.f.append((k, v)); return self
    def is_(self, k, _v): self.f.append((k, ("__null__",))); return self
    def in_(self, k, vals): self.f.append((k, ("__in__", list(vals)))); return self
    def ilike(self, *_a, **_k): return self
    def or_(self, *_a, **_k): return self
    def limit(self, _n): return self
    def order(self, *_a, **_k): return self
    def single(self): self.single_ = True; return self
    def maybe_single(self): self.single_ = True; return self

    def _match(self):
        out = []
        for r in self.s.setdefault(self.t, []):
            ok = True
            for k, v in self.f:
                if isinstance(v, tuple) and v and v[0] == "__null__":
                    if r.get(k) is not None: ok = False; break
                elif isinstance(v, tuple) and v and v[0] == "__in__":
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
        if self.t == "journal_entries":
            for r in m:
                r["journal_lines"] = [dict(l) for l in self.s.get("journal_lines", [])
                                      if l.get("journal_entry_id") == r["id"]]
        if self.single_:
            return _Resp(m[0] if m else None)
        return _Resp(m)


class FakeDB:
    def __init__(self): self.store = {}
    def table(self, n): return _Q(self.store, n)


def _db():
    db = FakeDB()
    db.store["chart_of_accounts"] = [
        {"id": i, "firm_id": FIRM, "client_id": None, "account_name": n,
         "system_account_key": sk, "is_active": True} for (i, n, sk) in ACCOUNTS]
    return db


def _txn(db, *, credit=0, debit=0, category=None, matched_type=None, matched_id=None, **kw):
    row = dict(id="t1", firm_id=FIRM, client_id=CLIENT, transaction_date="2026-06-10",
               description="TEST", debit_paise=debit, credit_paise=credit,
               category=category, account_id=None,
               matched_entity_type=matched_type, matched_entity_id=matched_id,
               match_status="matched" if matched_id else "unmatched",
               posted_journal_id=None, posted_at=None)
    row.update(kw)
    db.store.setdefault("bank_transactions", []).append(row)
    return row


def _invoice(db, *, total, paid=0, status="issued", iid="inv-1"):
    row = {"id": iid, "firm_id": FIRM, "client_id": CLIENT, "invoice_no": "INV-1",
           "total_paise": total, "paid_paise": paid, "credited_paise": 0,
           "debit_note_paise": 0, "status": status, "customer_id": "cust-1"}
    db.store.setdefault("client_sales_invoices", []).append(row)
    return row


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(bps.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(jpsmod.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(jpsmod.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    monkeypatch.setattr(bps.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    monkeypatch.setattr("services.audit_service.log_event", lambda *a, **k: None, raising=False)
    yield


def _lines(db, je_id):
    return [l for l in db.store.get("journal_lines", []) if l["journal_entry_id"] == je_id]


# ── the button pointed at an endpoint that refuses it ────────────────────────

def test_unmatch_still_refuses_a_posted_row_which_is_why_undo_exists():
    """Not a regression test for a fix — a record of the ORIGINAL bug. unmatch
    clears a MATCH; it was never the way to unwind a posting, and it says so."""
    from services.bank_matching_service import bank_matching_service as m
    db = _db()
    _txn(db, debit=50000, category="Expense", account_id="acc-exp",
         match_status="posted", posted_journal_id="je-1")
    with pytest.raises(HTTPException) as e:
        m.unmatch(db, FIRM, "t1")
    assert e.value.status_code == 409


# ── the journal comes back, by reversal ──────────────────────────────────────

def test_undo_reverses_the_journal_rather_than_deleting_it():
    db = _db()
    _txn(db, debit=50000, category="Expense", account_id="acc-exp")
    res = svc.post(db, FIRM, "t1", actor_id="u1")
    je = res["posted_journal_id"]
    original = _lines(db, je)
    assert len(original) == 2

    out = svc.undo(db, FIRM, "t1", actor_id="u1")
    rev = out["reversal_journal_id"]
    assert rev and rev != je

    # The original entry and its lines are untouched — CLAUDE.md: a posted
    # entry can never be hard-DELETEd or rewritten in place.
    assert _lines(db, je) == original
    assert any(e["id"] == je for e in db.store["journal_entries"])

    # And the reversal is equal and opposite, so the two net to nothing.
    net: dict = {}
    for l in original + _lines(db, rev):
        net[l["account_id"]] = (net.get(l["account_id"], 0)
                                + int(l["debit_paise"]) - int(l["credit_paise"]))
    assert all(v == 0 for v in net.values()), net


def test_the_row_goes_back_in_the_queue():
    db = _db()
    _txn(db, debit=50000, category="Expense", account_id="acc-exp")
    svc.post(db, FIRM, "t1", actor_id="u1")
    svc.undo(db, FIRM, "t1", actor_id="u1")
    row = db.store["bank_transactions"][0]
    assert row["match_status"] == "unmatched"
    assert row["posted_journal_id"] is None and row["posted_at"] is None


def test_a_matched_row_goes_back_to_matched_not_unmatched():
    """Undoing the POSTING is not undoing the CA's identification of which
    invoice this was. Sending it back to unmatched makes them find it again."""
    db = _db()
    _invoice(db, total=118000)
    _txn(db, credit=118000, category="Customer Payment",
         matched_type="sales_invoice", matched_id="inv-1")
    svc.post(db, FIRM, "t1", actor_id="u1")
    svc.undo(db, FIRM, "t1", actor_id="u1")
    row = db.store["bank_transactions"][0]
    assert row["match_status"] == "matched"
    assert row["matched_entity_id"] == "inv-1", "the match itself must survive"


def test_undoing_twice_is_refused_rather_than_reversing_twice():
    db = _db()
    _txn(db, debit=50000, category="Expense", account_id="acc-exp")
    svc.post(db, FIRM, "t1", actor_id="u1")
    svc.undo(db, FIRM, "t1", actor_id="u1")
    with pytest.raises(HTTPException) as e:
        svc.undo(db, FIRM, "t1", actor_id="u1")
    assert e.value.status_code == 409 and "not posted" in e.value.detail


def test_undo_on_a_row_that_was_never_posted_is_refused():
    db = _db()
    _txn(db, debit=50000, category="Expense", account_id="acc-exp")
    with pytest.raises(HTTPException) as e:
        svc.undo(db, FIRM, "t1", actor_id="u1")
    assert e.value.status_code == 409


# ── the document gets its money back ─────────────────────────────────────────

def test_a_settled_invoice_is_unsettled():
    db = _db()
    _invoice(db, total=118000)
    _txn(db, credit=118000, category="Customer Payment",
         matched_type="sales_invoice", matched_id="inv-1")
    svc.post(db, FIRM, "t1", actor_id="u1")
    inv = db.store["client_sales_invoices"][0]
    assert (inv["paid_paise"], inv["status"]) == (118000, "paid")

    out = svc.undo(db, FIRM, "t1", actor_id="u1")
    # "issued", NOT "unpaid". This test asserted "unpaid" and passed for
    # months, because the FakeDB below has no CHECK constraints and stores any
    # string it is handed. The real column does not:
    #     client_sales_invoices.status  draft|issued|partially_paid|paid|cancelled
    # so in production this UPDATE raised and the undo came back as a 500 —
    # every time a bank line that settled a document was undone. The test was
    # not merely silent about the bug; it encoded it.
    assert (inv["paid_paise"], inv["status"]) == (0, "issued")
    assert out["unsettled"]["reversed_paise"] == 118000


def test_a_part_paid_invoice_goes_back_to_partially_paid_not_unpaid():
    """The invoice was ALREADY half paid before this line topped it up. Undo
    must return it to that state, not to 'nobody has paid anything'."""
    db = _db()
    _invoice(db, total=118000, paid=50000, status="partially_paid")
    _txn(db, credit=68000, category="Customer Payment",
         matched_type="sales_invoice", matched_id="inv-1")
    svc.post(db, FIRM, "t1", actor_id="u1")
    inv = db.store["client_sales_invoices"][0]
    assert (inv["paid_paise"], inv["status"]) == (118000, "paid")

    svc.undo(db, FIRM, "t1", actor_id="u1")
    assert inv["paid_paise"] == 50000
    assert inv["status"] == "partially_paid", "the earlier payment is not this line's to erase"


def test_unsettling_never_drives_paid_negative():
    """If something else already reduced paid_paise, subtracting this line's
    full amount would make the document look overdue for money nobody owes."""
    db = _db()
    _invoice(db, total=118000)
    _txn(db, credit=118000, category="Customer Payment",
         matched_type="sales_invoice", matched_id="inv-1")
    svc.post(db, FIRM, "t1", actor_id="u1")
    db.store["client_sales_invoices"][0]["paid_paise"] = 20000   # a correction landed
    svc.undo(db, FIRM, "t1", actor_id="u1")
    inv = db.store["client_sales_invoices"][0]
    assert inv["paid_paise"] == 0 and inv["status"] == "issued"


def test_an_unmatched_posting_touches_no_document():
    db = _db()
    _invoice(db, total=118000, paid=118000, status="paid")
    _txn(db, debit=50000, category="Expense", account_id="acc-exp")
    svc.post(db, FIRM, "t1", actor_id="u1")
    out = svc.undo(db, FIRM, "t1", actor_id="u1")
    assert out["unsettled"] is None
    assert db.store["client_sales_invoices"][0]["paid_paise"] == 118000


# ── the overpayment credit ───────────────────────────────────────────────────

def test_an_overpayment_credit_is_taken_back():
    db = _db()
    _invoice(db, total=100000)
    _txn(db, credit=118000, category="Customer Payment",
         matched_type="sales_invoice", matched_id="inv-1")
    svc.post(db, FIRM, "t1", actor_id="u1")
    assert party_credit_service.get_balance(db, FIRM, CLIENT, "customer", "cust-1") == 18000

    out = svc.undo(db, FIRM, "t1", actor_id="u1")
    assert party_credit_service.get_balance(db, FIRM, CLIENT, "customer", "cust-1") == 0
    assert out["credit_revoked"]["paise"] == 18000
    # Append-only: the grant is still there, with a revocation beside it.
    kinds = [r["kind"] for r in db.store["party_credit_ledger"]]
    assert kinds == ["grant", "revocation"]


def test_a_credit_already_spent_blocks_the_undo_instead_of_going_negative():
    """Once the credit has been applied to another invoice, that invoice's
    paid_paise went up on the strength of it. Clawing it back here would leave
    the sub-ledger claiming the customer owes money the GL says they paid."""
    db = _db()
    _invoice(db, total=100000)
    _txn(db, credit=118000, category="Customer Payment",
         matched_type="sales_invoice", matched_id="inv-1")
    svc.post(db, FIRM, "t1", actor_id="u1")
    # Spend it, without going through apply_credit's document machinery.
    bal = db.store["party_credit_balances"][0]
    bal["balance_paise"] = 0

    with pytest.raises(HTTPException) as e:
        svc.undo(db, FIRM, "t1", actor_id="u1")
    assert e.value.status_code == 409 and "already been used" in e.value.detail


def test_post_undo_post_undo_revokes_only_the_second_grant():
    """The ordinary correction loop: post it, spot the mistake, undo, fix, post
    again, undo again. Each posting grants its OWN credit and each undo must
    take back that one.

    This is what makes granted_for_source exclude revocations. Counting them
    would hand _revoke_overpayment_credit a NEGATIVE amount from the first
    round's revocation row, and revoke_credit refuses a non-positive amount —
    so the second undo would fail with a confusing 422 about an amount the CA
    never entered.
    """
    db = _db()
    _invoice(db, total=100000)
    _txn(db, credit=118000, category="Customer Payment",
         matched_type="sales_invoice", matched_id="inv-1")
    bal = lambda: party_credit_service.get_balance(db, FIRM, CLIENT, "customer", "cust-1")

    svc.post(db, FIRM, "t1", actor_id="u1")
    assert bal() == 18000
    svc.undo(db, FIRM, "t1", actor_id="u1")
    assert bal() == 0

    svc.post(db, FIRM, "t1", actor_id="u1")
    assert bal() == 18000, "the second posting grants its own credit"
    out = svc.undo(db, FIRM, "t1", actor_id="u1")
    assert bal() == 0
    assert out["credit_revoked"]["paise"] == 18000, \
        "only the live grant is revocable — the first round's is already undone"
    kinds = [r["kind"] for r in db.store["party_credit_ledger"]]
    assert kinds == ["grant", "revocation", "grant", "revocation"]


# ── outstanding_for_source on its own ────────────────────────────────────────

def test_outstanding_for_source_reports_only_what_is_still_live():
    """Directly, because the bank flow cannot reach every case: a fully-undone
    source nets to zero, and a function called "outstanding" must return
    nothing for it rather than a zero row. revoke_credit refuses a non-positive
    amount, so a zero row would surface as a 422 about an amount nobody typed.
    """
    db = _db()
    db.store["party_credit_ledger"] = [
        # fully given back — nothing outstanding
        {"firm_id": FIRM, "client_id": CLIENT, "party_type": "customer", "party_id": "c1",
         "amount_paise": 18000, "kind": "grant", "source_type": "bank_overpayment", "source_id": "t1"},
        {"firm_id": FIRM, "client_id": CLIENT, "party_type": "customer", "party_id": "c1",
         "amount_paise": -18000, "kind": "revocation", "source_type": "bank_overpayment", "source_id": "t1"},
        # partly consumed by an application — the rest is still revocable
        {"firm_id": FIRM, "client_id": CLIENT, "party_type": "vendor", "party_id": "v1",
         "amount_paise": 50000, "kind": "grant", "source_type": "bank_overpayment", "source_id": "t1"},
        {"firm_id": FIRM, "client_id": CLIENT, "party_type": "vendor", "party_id": "v1",
         "amount_paise": -20000, "kind": "application", "source_type": "bank_overpayment", "source_id": "t1"},
    ]
    out = party_credit_service.outstanding_for_source(db, FIRM, CLIENT, "bank_overpayment", "t1")
    assert out == [{"party_type": "vendor", "party_id": "v1", "amount_paise": 30000}]


# ── through the ROUTE, past the mock-mode early return ───────────────────────

def test_the_undo_ROUTE_runs_end_to_end_with_a_database(monkeypatch):
    """routers.banking has 57 `if not db: return ...` early returns, and in mock
    mode each one IS the whole endpoint — everything after it is unexercised by
    the entire suite. That is how #308's ledger_order shipped raising NameError
    on every real request with CI green.

    /undo is the other route added recently, and it is a WRITE. Patching _db
    gets past the early return so the route's own wiring — the actor keys it
    reads off current_user, the scope assertion, the shape it returns — is run
    at least once.
    """
    import core.authz as authz
    import routers.banking as banking_router
    db = _db()
    _txn(db, debit=50000, category="Expense", account_id="acc-exp")
    svc.post(db, FIRM, "t1", actor_id="u1")
    monkeypatch.setattr(banking_router, "_db", lambda: db)
    monkeypatch.setattr(authz, "_USE_MOCK", True)
    monkeypatch.setattr(banking_router, "_assert_txn_scope", lambda *a, **k: None)

    res = banking_router.undo_transaction(
        "t1", current_user={"firm_id": FIRM, "role": "Partner",
                            "auth_user_id": "p1", "id": "u1"})
    assert res["success"] is True
    assert res["data"]["match_status"] == "unmatched"
    rev_id = res["data"]["reversal_journal_id"]
    assert rev_id
    assert db.store["bank_transactions"][0]["posted_journal_id"] is None
    # The actor has to survive the route, not just the service: who reversed a
    # posted journal is the whole point of the audit trail, and the route is
    # the only place current_user is unpacked.
    rev = next(e for e in db.store["journal_entries"] if e["id"] == rev_id)
    assert rev.get("created_by") == "u1", "the reversal must name who made it"


# ── what it refuses to half-undo ─────────────────────────────────────────────

def test_a_receipt_backed_settlement_is_refused_not_half_undone():
    db = _db()
    _txn(db, credit=118000, category="Customer Payment",
         match_status="posted", posted_journal_id="je-r")
    db.store["journal_entries"] = [{"id": "je-r", "firm_id": FIRM, "client_id": CLIENT,
                                    "source_type": "receipt", "entry_date": "2026-06-10",
                                    "is_posted": True}]
    with pytest.raises(HTTPException) as e:
        svc.undo(db, FIRM, "t1", actor_id="u1")
    assert e.value.status_code == 422 and "receipt" in e.value.detail


# ── a half-finished undo is resumable, not double-reversing ──────────────────

def test_a_second_undo_reuses_the_reversal_the_first_one_already_wrote():
    """THE STATE A FAILED UNDO LEAVES BEHIND.

    Undo is several writes and is not atomic: the reversal lands first, and
    anything failing after it — as _unsettle did for months, writing a status
    no table accepts — leaves a balanced reversal on the books with the bank
    line still reading "posted". Five documents on a live firm sat like that.

    Pressing Undo again is how a CA gets out of it, so that press must FINISH
    the job, not start it over. Reversing the same journal twice would swing the
    ledger the wrong way by the full amount, and the (client, reference_no,
    entry_date) dedupe in _create_journal cannot stop it because a reversal's
    reference_no is REV-<random>.
    """
    db = _db()
    inv = _invoice(db, total=118000, paid=0)
    _txn(db, credit=118000, category="Customer Payment",
         matched_type="sales_invoice", matched_id=inv["id"])
    je = svc.post(db, FIRM, "t1", actor_id="u1")["posted_journal_id"]

    # Simulate the interrupted undo: the reversal is written, everything after
    # it never ran — the row is still posted and the invoice still shows paid.
    first = svc._reverse_for_test if hasattr(svc, "_reverse_for_test") else None
    import services.phase2_journal_service as p2
    orphan = p2.phase2_journal_service.reverse_entry(
        db, FIRM, je, "2026-06-10", narration="interrupted undo", created_by="u1")
    reversals_before = [e for e in db.store["journal_entries"] if e.get("reversal_of") == je]
    assert len(reversals_before) == 1 and orphan == reversals_before[0]["id"]

    out = svc.undo(db, FIRM, "t1", actor_id="u1")

    # NO second reversal — the existing one is adopted.
    reversals_after = [e for e in db.store["journal_entries"] if e.get("reversal_of") == je]
    assert len(reversals_after) == 1, (
        f"undo wrote a second reversal of the same journal ({len(reversals_after)} "
        "now exist) — the ledger has moved twice for one correction")
    assert out["reversal_journal_id"] == orphan

    # And the rest of the undo still completed: the document gave the money
    # back and the line is out of the posted state.
    assert (inv["paid_paise"], inv["status"]) == (0, "issued")
    txn = db.store["bank_transactions"][0]
    assert txn["match_status"] == "matched" and txn["posted_journal_id"] is None


def test_a_fresh_posting_is_still_reversed_normally():
    """The guard must not swallow a legitimate reversal. A re-POST creates a
    NEW journal, so the second undo has nothing of its own to adopt."""
    db = _db()
    _txn(db, debit=50000, category="Expense", account_id="acc-exp")
    je1 = svc.post(db, FIRM, "t1", actor_id="u1")["posted_journal_id"]
    svc.undo(db, FIRM, "t1", actor_id="u1")

    db.store["bank_transactions"][0].update({"category": "Expense", "account_id": "acc-exp"})
    je2 = svc.post(db, FIRM, "t1", actor_id="u1")["posted_journal_id"]
    assert je2 != je1, "the re-post must create its own journal"
    out = svc.undo(db, FIRM, "t1", actor_id="u1")

    assert out["reversal_journal_id"] not in (None, "")
    revs2 = [e for e in db.store["journal_entries"] if e.get("reversal_of") == je2]
    assert len(revs2) == 1, "the second posting must get a reversal of its own"
    assert out["reversal_journal_id"] == revs2[0]["id"]
