"""
Banking B.2 — Matching & Categorization tests.

Pure engine (match ranking, rule categorization, category vocabulary) plus the
matching service (queue filters, manual match acceptance, duplicate prevention)
against an in-memory fake Supabase client.
"""
import pytest

from domain.banking import (
    Candidate, rank_suggestions, suggest_category, rule_matches,
    is_valid_category, CATEGORIES,
)
import services.bank_matching_service as bms
from services.bank_matching_service import bank_matching_service


# ── B.2.1 match ranking (pure) ────────────────────────────────────────────────

def _cand(**kw):
    base = dict(entity_type="sales_invoice", entity_id="i1", label="INV", amount_paise=118000,
                entity_date="2026-04-10", party_name=None, outstanding_paise=None)
    base.update(kw)
    return Candidate(**base)


def test_bank_line_larger_than_document_is_excluded():
    """A receipt BIGGER than the invoice is not settling that invoice. Short
    lines are ranked (see the TDS tests below); over-payments are not."""
    cands = [_cand(amount_paise=118000), _cand(entity_id="i2", amount_paise=100000)]
    out = rank_suggestions(118000, "2026-04-10", "NEFT", cands)
    assert [s.entity_id for s in out] == ["i1"]


def test_near_date_scores_below_same_day():
    same = rank_suggestions(118000, "2026-04-10", "x", [_cand(entity_date="2026-04-10")])[0]
    near = rank_suggestions(118000, "2026-04-10", "x", [_cand(entity_date="2026-04-13")])[0]
    far = rank_suggestions(118000, "2026-04-10", "x", [_cand(entity_date="2026-06-10")])[0]
    assert same.confidence > near.confidence > far.confidence


def test_multiple_candidates_ranked_by_confidence():
    cands = [
        _cand(entity_id="far", entity_date="2026-06-10"),
        _cand(entity_id="party", entity_date="2026-04-10", party_name="Acme", outstanding_paise=118000),
        _cand(entity_id="mid", entity_date="2026-04-12"),
    ]
    out = rank_suggestions(118000, "2026-04-10", "payment from ACME ltd", cands)
    assert out[0].entity_id == "party"          # same-day + party + outstanding → highest
    assert out[0].confidence_label == "high"
    assert [s.entity_id for s in out] == ["party", "mid", "far"]


def test_party_and_outstanding_boost_confidence():
    base = rank_suggestions(118000, "2026-04-10", "random", [_cand(entity_date="2026-04-10")])[0]
    boosted = rank_suggestions(118000, "2026-04-10", "from acme",
                               [_cand(entity_date="2026-04-10", party_name="Acme", outstanding_paise=118000)])[0]
    assert boosted.confidence > base.confidence


def test_invoice_outranks_journal_on_tie():
    cands = [
        Candidate("journal_entry", "j1", "JE", 5000, "2026-04-10"),
        Candidate("sales_invoice", "i1", "INV", 5000, "2026-04-10"),
    ]
    out = rank_suggestions(5000, "2026-04-10", "x", cands)
    assert out[0].entity_type == "sales_invoice"  # settlement doc ahead of journal


# ── B.2.3 rule engine (pure) ──────────────────────────────────────────────────

def test_rule_pattern_and_category():
    rules = [{"description_pattern": "RAZORPAY", "suggested_category": "Sales Receipt", "is_active": True}]
    assert suggest_category("NEFT RAZORPAY SOFTWARE", 50000, False, rules) == "Sales Receipt"
    assert suggest_category("ATM WITHDRAWAL", 50000, False, rules) is None


def test_rule_amount_and_txn_type():
    rule = {"description_pattern": "BANK CHARGES", "amount_max_paise": 10000,
            "txn_type": "debit", "suggested_category": "Expense", "is_active": True}
    assert rule_matches(rule, "MONTHLY BANK CHARGES", 5000, is_debit=True)
    assert not rule_matches(rule, "BANK CHARGES", 50000, is_debit=True)   # over max
    assert not rule_matches(rule, "BANK CHARGES", 5000, is_debit=False)  # wrong direction


def test_inactive_rule_skipped():
    rules = [{"description_pattern": "GST", "suggested_category": "GST Payment", "is_active": False}]
    assert suggest_category("GST PMT", 90000, True, rules) is None


def test_first_matching_rule_wins():
    rules = [
        {"description_pattern": "PMT", "suggested_category": "GST Payment", "is_active": True},
        {"description_pattern": "PMT", "suggested_category": "Other", "is_active": True},
    ]
    assert suggest_category("GST PMT", 1, True, rules) == "GST Payment"


# ── B.2.2 category vocabulary ─────────────────────────────────────────────────

def test_categories_are_controlled():
    assert is_valid_category("GST Payment")
    assert not is_valid_category("random text")
    assert len(CATEGORIES) == 11


# ── Fake Supabase for service tests ───────────────────────────────────────────

class _Resp:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count

# ── PostgREST or() ────────────────────────────────────────────────────────────
# The banded candidate fetch sends `or(and(col.gte.LO,col.lte.HI),and(…))` — the
# exact union of every row's amount band, in one query. A naive split on "," tears
# the groups apart and quietly matches nothing, which is indistinguishable from
# "no candidates", so this parses paren depth properly and REFUSES what it does
# not understand.
_OR_OPS = {"eq", "neq", "gt", "gte", "lt", "lte", "is"}


def _split_top(expr):
    out, depth, cur = [], 0, []
    for ch in expr:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur)); cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur))
    return [t.strip() for t in out if t.strip()]


def _coerce(v):
    if v == "null":
        return None
    return int(v) if v.lstrip("-").isdigit() else v


def _or_term(row, term):
    if term.startswith("and(") and term.endswith(")"):
        return all(_or_term(row, t) for t in _split_top(term[4:-1]))
    if term.startswith("or(") and term.endswith(")"):
        return any(_or_term(row, t) for t in _split_top(term[3:-1]))
    parts = term.split(".", 2)
    if len(parts) != 3:
        raise NotImplementedError(f"fake or() term not understood: {term!r}")
    c, op, v = parts
    if op not in _OR_OPS:
        raise NotImplementedError(f"fake or() operator not implemented: {op!r}")
    got, want = row.get(c), _coerce(v)
    if op == "is":
        return got is want
    if op == "eq":
        return got == want
    if op == "neq":
        return got != want
    if got is None:
        return False
    return {"gt": got > want, "gte": got >= want,
            "lt": got < want, "lte": got <= want}[op]


def _or_match(row, expr):
    return any(_or_term(row, t) for t in _split_top(expr))


class _Q:
    def __init__(self, store, table):
        self.store, self.table = store, table
        self._op = "select"
        self._payload = None
        self._eq = []
        self._pred = []          # gte / lte / neq / is_ predicates
        self._single = False
        self._order = []
        self._limit = None
        self._range = None
        self._count = None
        self._negate = False

    def insert(self, p):
        self._op, self._payload = "insert", p
        return self

    def update(self, p):
        self._op, self._payload = "update", p
        return self

    def select(self, *_a, count=None, **_k):
        self._op = "select"
        self._count = count
        return self

    def eq(self, k, v):
        if self._negate:
            return self._add(lambda r, k=k, v=v: r.get(k) != v)
        self._eq.append((k, v))
        return self

    # `.not_.in_(...)` / `.not_.is_(...)`: PostgREST's negation applies to the
    # NEXT predicate only. The queue's view filter is SQL now, so the double
    # has to model that — without it "for_review" silently matched everything.
    @property
    def not_(self):
        self._negate = True
        return self

    def _add(self, pred):
        neg, self._negate = self._negate, False
        self._pred.append((lambda r: not pred(r)) if neg else pred)
        return self

    def in_(self, k, vals):
        vals = list(vals)
        return self._add(lambda r, k=k, vals=vals: r.get(k) in vals)

    def range(self, a, b):
        self._range = (a, b)
        return self

    def or_(self, expr):
        return self._add(lambda r, e=expr: _or_match(r, e))

    # Range + null predicates. Without these the candidate-fetch path raised
    # AttributeError, was swallowed by _candidates()'s best-effort except, and
    # every suggestion test silently exercised an empty candidate list.
    def gte(self, k, v):
        return self._add(lambda r, k=k, v=v: r.get(k) is not None and r[k] >= v)

    def lte(self, k, v):
        return self._add(lambda r, k=k, v=v: r.get(k) is not None and r[k] <= v)

    def neq(self, k, v):
        return self._add(lambda r, k=k, v=v: r.get(k) != v)

    def is_(self, k, _null):
        return self._add(lambda r, k=k: r.get(k) is None)

    def delete(self):
        self._op = "delete"
        return self

    def order(self, col, **_k):
        self._order.append(col)      # accumulates, as PostgREST does
        return self

    def limit(self, n):
        self._limit = n
        return self

    def single(self):
        self._single = True
        return self

    def _matches(self):
        rows = self.store.setdefault(self.table, [])
        return [r for r in rows
                if all(r.get(k) == v for k, v in self._eq)
                and all(p(r) for p in self._pred)]

    def execute(self):
        rows = self.store.setdefault(self.table, [])
        if self._op == "insert":
            items = self._payload if isinstance(self._payload, list) else [self._payload]
            ins = []
            for p in items:
                rec = dict(p)
                rec.setdefault("id", f"{self.table}-{len(rows)+1}")
                rows.append(rec); ins.append(rec)
            return _Resp(ins)
        matched = self._matches()
        if self._op == "update":
            for r in matched:
                r.update(self._payload)
            return _Resp(matched)
        if self._op == "delete":
            for r in matched:
                rows.remove(r)
            return _Resp(matched)
        for col in reversed(self._order):
            matched = sorted(matched, key=lambda r, c=col: str(r.get(c)))
        total = len(matched)
        if self._range is not None:
            matched = matched[self._range[0]: self._range[1] + 1]
        if self._limit is not None:
            matched = matched[: self._limit]
        if self._single:
            return _Resp(matched[0] if matched else None)
        return _Resp(matched, count=(total if self._count else None))


class FakeDB:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return _Q(self.store, name)


FIRM, CLIENT = "firm-1", "client-1"


@pytest.fixture(autouse=True)
def _silence(monkeypatch):
    monkeypatch.setattr(bms.timeline_service, "log", lambda *a, **k: None)
    yield


def _seed_txn(db, **kw):
    row = dict(id="t1", firm_id=FIRM, client_id=CLIENT, transaction_date="2026-04-10",
               description="NEFT", debit_paise=0, credit_paise=118000, balance_paise=118000,
               match_status="unmatched", category=None, matched_entity_id=None, needs_review=False)
    row.update(kw)
    db.store.setdefault("bank_transactions", []).append(row)
    return row


def _seed_entity(db, table, entity_id, **kw):
    """Seed a backing document (sales invoice / purchase bill / journal entry /
    etc.) so match()'s tenant-ownership check finds it owned by FIRM/CLIENT."""
    row = dict(id=entity_id, firm_id=FIRM, client_id=CLIENT)
    row.update(kw)
    db.store.setdefault(table, []).append(row)
    return row


# ── B.2.2 categorize ──────────────────────────────────────────────────────────

def test_categorize_sets_controlled_category():
    db = FakeDB(); _seed_txn(db)
    res = bank_matching_service.categorize(db, FIRM, "t1", "Sales Receipt")
    assert res["category"] == "Sales Receipt"
    assert db.store["bank_transactions"][0]["category"] == "Sales Receipt"


def test_categorize_rejects_freeform():
    db = FakeDB(); _seed_txn(db)
    with pytest.raises(Exception):
        bank_matching_service.categorize(db, FIRM, "t1", "made up category")


# ── B.2.5 manual match acceptance ─────────────────────────────────────────────

def test_manual_match_acceptance_links_entity():
    db = FakeDB(); _seed_txn(db)
    _seed_entity(db, "client_sales_invoices", "inv-9")
    res = bank_matching_service.match(db, FIRM, "t1", "sales_invoice", "inv-9",
                                      category="Sales Receipt", actor_id="u1")
    assert res["match_status"] == "matched"
    row = db.store["bank_transactions"][0]
    assert row["matched_entity_type"] == "sales_invoice"
    assert row["matched_entity_id"] == "inv-9"
    assert row["category"] == "Sales Receipt"
    assert row["matched_by"] == "u1" and row["matched_at"]


def test_match_invalid_entity_type_rejected():
    db = FakeDB(); _seed_txn(db)
    with pytest.raises(Exception):
        bank_matching_service.match(db, FIRM, "t1", "not_a_type", "x")


def test_match_derives_category_when_none_given():
    """Accepting a suggestion without a category must NOT leave the txn
    uncategorized: a receivable match implies Customer Payment, a payable match
    Vendor Payment (both AUTO-counter, settle the matched document downstream)."""
    db = FakeDB(); _seed_txn(db)
    _seed_entity(db, "client_sales_invoices", "inv-9")
    res = bank_matching_service.match(db, FIRM, "t1", "sales_invoice", "inv-9")
    assert res["category"] == "Customer Payment"
    assert db.store["bank_transactions"][0]["category"] == "Customer Payment"

    db2 = FakeDB(); _seed_txn(db2, debit_paise=50000, credit_paise=0)
    _seed_entity(db2, "purchase_bills", "bill-3")
    res2 = bank_matching_service.match(db2, FIRM, "t1", "purchase_bill", "bill-3")
    assert res2["category"] == "Vendor Payment"


def test_match_explicit_category_overrides_derived_default():
    db = FakeDB(); _seed_txn(db)
    _seed_entity(db, "client_sales_invoices", "inv-9")
    res = bank_matching_service.match(db, FIRM, "t1", "sales_invoice", "inv-9",
                                     category="Sales Receipt")
    assert res["category"] == "Sales Receipt"


def test_match_journal_entry_leaves_category_null():
    """journal_entry / manual have no unambiguous category — stay NULL for the CA
    to classify explicitly, rather than guessing one."""
    db = FakeDB(); _seed_txn(db)
    _seed_entity(db, "journal_entries", "je-1")
    res = bank_matching_service.match(db, FIRM, "t1", "journal_entry", "je-1")
    assert res["category"] is None
    assert db.store["bank_transactions"][0].get("category") is None


# ── tenant-ownership check (task #225 finding #3) ─────────────────────────────

def test_match_rejects_entity_from_another_firm():
    """matched_entity_id is caller-supplied — must be verified to actually
    belong to this transaction's firm, not merely well-formed."""
    db = FakeDB(); _seed_txn(db)
    _seed_entity(db, "client_sales_invoices", "inv-9", firm_id="firm-OTHER")
    with pytest.raises(Exception):
        bank_matching_service.match(db, FIRM, "t1", "sales_invoice", "inv-9")
    assert db.store["bank_transactions"][0]["match_status"] == "unmatched"


def test_match_rejects_entity_from_another_client_same_firm():
    db = FakeDB(); _seed_txn(db)
    _seed_entity(db, "purchase_bills", "bill-3", client_id="client-OTHER")
    with pytest.raises(Exception):
        bank_matching_service.match(db, FIRM, "t1", "purchase_bill", "bill-3")
    assert db.store["bank_transactions"][0]["match_status"] == "unmatched"


def test_match_rejects_nonexistent_entity():
    db = FakeDB(); _seed_txn(db)
    with pytest.raises(Exception):
        bank_matching_service.match(db, FIRM, "t1", "sales_invoice", "inv-does-not-exist")


def test_manual_match_type_has_no_ownership_check():
    """'manual' has no backing document table — matching it must not attempt
    a lookup (and must therefore succeed with any caller-supplied id)."""
    db = FakeDB(); _seed_txn(db)
    res = bank_matching_service.match(db, FIRM, "t1", "manual", "free-text-ref")
    assert res["match_status"] == "matched"


# ── Duplicate prevention: cannot re-match a posted transaction ────────────────

def test_cannot_match_posted_transaction():
    db = FakeDB(); _seed_txn(db, match_status="posted")
    with pytest.raises(Exception):
        bank_matching_service.match(db, FIRM, "t1", "sales_invoice", "inv-9")


def test_unmatch_clears_linkage():
    db = FakeDB()
    _seed_txn(db, match_status="matched", matched_entity_type="sales_invoice", matched_entity_id="inv-9")
    res = bank_matching_service.unmatch(db, FIRM, "t1")
    assert res["match_status"] == "unmatched"
    assert db.store["bank_transactions"][0]["matched_entity_id"] is None


# ── task #228 audit finding: a DRAFT journal (posted_journal_id set) must
# block categorize/match/unmatch too, not just an already-POSTED transaction.
# bank_posting_service.post() creates the draft and deliberately leaves
# match_status alone until a human approves it (settle_on_post re-reads
# category/matched_entity_* from the LIVE row at approval time) — without
# this guard, the linkage the pending draft will settle against can be
# silently changed or erased out from under it. ────────────────────────────

def test_categorize_rejects_when_draft_journal_pending():
    db = FakeDB()
    _seed_txn(db, posted_journal_id="je-draft-1")
    with pytest.raises(Exception):
        bank_matching_service.categorize(db, FIRM, "t1", "Sales Receipt")
    assert db.store["bank_transactions"][0]["category"] is None


def test_match_rejects_when_draft_journal_pending():
    db = FakeDB()
    _seed_txn(db, posted_journal_id="je-draft-1")
    _seed_entity(db, "client_sales_invoices", "inv-9")
    with pytest.raises(Exception):
        bank_matching_service.match(db, FIRM, "t1", "sales_invoice", "inv-9")
    assert db.store["bank_transactions"][0]["matched_entity_id"] is None


def test_unmatch_rejects_when_draft_journal_pending():
    db = FakeDB()
    _seed_txn(db, match_status="matched", matched_entity_type="sales_invoice",
             matched_entity_id="inv-9", posted_journal_id="je-draft-1")
    with pytest.raises(Exception):
        bank_matching_service.unmatch(db, FIRM, "t1")
    # The pending draft's linkage must survive untouched.
    assert db.store["bank_transactions"][0]["matched_entity_id"] == "inv-9"


# ── B.2.4 queue filters ───────────────────────────────────────────────────────

def test_queue_filters_partition_transactions():
    db = FakeDB()
    _seed_txn(db, id="u1", match_status="unmatched")
    _seed_txn(db, id="c1", category="Expense")
    _seed_txn(db, id="m1", match_status="matched", matched_entity_id="inv-1")
    _seed_txn(db, id="r1", needs_review=True)

    ids = lambda st: {t["id"] for t in bank_matching_service.queue(db, FIRM, CLIENT, st)}
    assert "u1" in ids("unmatched") and "m1" not in ids("unmatched")
    assert ids("categorized") == {"c1"}
    assert ids("matched") == {"m1"}
    assert ids("needs_review") == {"r1"}
    assert len(ids("all")) == 4


def test_queue_applies_rule_suggested_category():
    db = FakeDB()
    _seed_txn(db, id="u1", description="UPI RAZORPAY PAYOUT")
    # A matching rule always belongs to a client (MatchingRuleIn.client_id is
    # required) -- queue() only applies a client's own rules to its own
    # transactions (task #235 fix), so this must carry the same client_id.
    db.store.setdefault("bank_matching_rules", []).append({
        "id": "rule-1", "firm_id": FIRM, "client_id": CLIENT, "is_active": True,
        "description_pattern": "RAZORPAY", "suggested_category": "Sales Receipt",
    })
    q = bank_matching_service.queue(db, FIRM, CLIENT, "unmatched")
    assert q[0]["suggested_category"] == "Sales Receipt"


def test_queue_does_not_apply_another_clients_rule():
    """Task #235 fix: matching rules are per-client. A rule configured for
    Client B must never surface as a suggested category on Client A's
    transactions, even though both clients are in the same firm."""
    db = FakeDB()
    other_client = "client-2"
    _seed_txn(db, id="u1", client_id=CLIENT, description="UPI RAZORPAY PAYOUT")
    db.store.setdefault("bank_matching_rules", []).append({
        "id": "rule-1", "firm_id": FIRM, "client_id": other_client, "is_active": True,
        "description_pattern": "RAZORPAY", "suggested_category": "Sales Receipt",
    })
    q = bank_matching_service.queue(db, FIRM, CLIENT, "unmatched")
    assert q[0]["suggested_category"] is None

    # Firm-wide view (client_id=None) must also isolate rules per transaction.
    q_all = bank_matching_service.queue(db, FIRM, None, "unmatched")
    assert q_all[0]["suggested_category"] is None
