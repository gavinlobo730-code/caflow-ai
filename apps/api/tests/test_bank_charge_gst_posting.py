"""
GST on bank charges, end to end (Tier 6.4) — the split reaching the ledger.

test_bank_charge_gst.py proves the arithmetic. This proves the WIRING: that a
₹590 charge posted at 18% produces a four-line draft journal with ₹500 on Bank
Charges and ₹45 on each of the two RIGHT tax heads, that the split is refused
everywhere it would be wrong, and that a matching rule can carry the treatment
so a CA states it once per bank instead of once per charge.

WHY THIS FILE HAS ITS OWN FAKE DB
    The fake in test_bank_posting.py treats `.ilike()` as a no-op passthrough,
    which is harmless there — every lookup it exercises resolves by
    system_account_key. It is NOT harmless here. The seeded chart carries three
    GST Input Credit accounts and migration 092 stamps system_account_key
    ='gst_input' on ALL THREE, so the tax head can only come from the NAME. With
    a no-op ilike, "does the CGST amount land on the CGST account" would pass
    against a fake that cannot tell the three apart — i.e. it would prove
    nothing. The fake below implements ilike and or_ for real.
"""
import re

import pytest
from fastapi import HTTPException

from domain.banking import match_rule
from models.banking import MatchingRuleIn, MatchingRuleUpdateIn, PostBankTxnIn
import services.bank_posting_service as bps
from services.bank_posting_service import bank_posting_service
from services.bank_matching_service import bank_matching_service
import services.bank_matching_service as bms


FIRM, CLIENT = "firm-1", "client-1"


# ══════════════════════════════════════════════════════════════════════════════
# A fake Supabase that honours ilike / or_
# ══════════════════════════════════════════════════════════════════════════════

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


class _Resp:
    def __init__(self, data, count=None): self.data, self.count = data, count


def _like_to_re(pattern: str) -> re.Pattern:
    """PostgREST ILIKE → a case-insensitive regex. % is the wildcard."""
    return re.compile("^" + ".*".join(re.escape(p) for p in pattern.split("%")) + "$",
                      re.IGNORECASE)


class _Q:
    def __init__(self, store, table):
        self.s, self.t = store, table
        self.op, self.payload = "select", None
        self.eqs, self.likes, self.ors = [], [], []
        self.preds = []
        self.single_ = False
        self.orders = []
        self.range_ = None
        self.count_ = None
        self.negate = False

    def insert(self, p): self.op, self.payload = "insert", p; return self
    def update(self, p): self.op, self.payload = "update", p; return self
    def select(self, *_a, count=None, **_k): self.op = "select"; self.count_ = count; return self
    def eq(self, k, v): return self._add(lambda r: r.get(k) == v)

    # `.not_` negates the NEXT predicate only, as PostgREST does — the queue's
    # view filter is SQL now and leans on it.
    @property
    def not_(self): self.negate = True; return self

    def _add(self, pred):
        neg, self.negate = self.negate, False
        self.preds.append((lambda r: not pred(r)) if neg else pred)
        return self

    def neq(self, k, v): return self._add(lambda r: r.get(k) != v)
    def range(self, a, b): self.range_ = (a, b); return self
    def ilike(self, col, pattern): self.likes.append((col, _like_to_re(pattern))); return self
    def limit(self, _n): return self
    def order(self, c, desc=False): self.orders.append((c, desc)); return self
    def single(self): self.single_ = True; return self
    def maybe_single(self): self.single_ = True; return self
    def is_(self, k, _v): return self._add(lambda r: r.get(k) is None)
    def in_(self, k, vals): vals = list(vals); return self._add(lambda r: r.get(k) in vals)

    def or_(self, expr):
        """Two shapes now, and it still refuses anything else rather than
        silently passing everything:

          "client_id.eq.<id>,client_id.is.null"   — own rows OR firm-wide
          "and(col.gte.LO,col.lte.HI),and(…)"     — the banded candidate fetch

        The second arrived when the per-row candidate queries were collapsed
        into one banded query for the whole page."""
        if "and(" in expr or "or(" in expr:
            return self._add(lambda r, e=expr: _or_match(r, e))
        parts = [p.strip() for p in expr.split(",")]
        col = parts[0].split(".")[0]
        allowed = set()
        for p in parts:
            c, opn, *rest = p.split(".")
            if c != col or opn not in ("eq", "is"):
                raise NotImplementedError(f"fake or_ does not understand {p!r}")
            allowed.add(None if opn == "is" else rest[0])
        self.ors.append(("__or__", col, allowed))
        return self

    def _match(self):
        out = []
        for r in self.s.setdefault(self.t, []):
            if any(r.get(k) != v for k, v in self.eqs):
                continue
            if any(not p(r) for p in self.preds):
                continue
            if any(not rx.match(str(r.get(c) or "")) for c, rx in self.likes):
                continue
            ok = True
            for kind, col, vals in self.ors:
                if kind == "__or__" and r.get(col) not in vals:
                    ok = False; break
                if kind == "__in__" and r.get(col) not in vals:
                    ok = False; break
            if ok:
                out.append(r)
        return out

    def execute(self):
        rows = self.s.setdefault(self.t, [])
        if self.op == "insert":
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            ins = []
            for p in items:
                rec = dict(p)
                rec.setdefault("id", f"{self.t}-{len(rows) + 1}")
                rows.append(rec)
                ins.append(rec)
            return _Resp(ins)
        m = self._match()
        if self.op == "update":
            for r in m:
                r.update(self.payload)
            return _Resp(m)
        for c, desc in reversed(self.orders):   # accumulates, as PostgREST does
            m = sorted(m, key=lambda r, c=c: str(r.get(c)), reverse=desc)
        total = len(m)
        if self.range_ is not None:
            m = m[self.range_[0]: self.range_[1] + 1]
        if self.single_:
            return _Resp(m[0] if m else None)
        return _Resp(m, count=(total if self.count_ else None))


class FakeDB:
    def __init__(self): self.store = {}
    def table(self, n): return _Q(self.store, n)


# The names are the real seeded ones (migration 011), and all three carry
# system_account_key='gst_input' exactly as migration 092 leaves them — that
# collision is the reason _gst_input_account matches on the name.
ACCOUNTS = [
    ("acc-bank", "HDFC Bank", "bank"),
    ("acc-charges", "Bank Charges", None),
    ("acc-ar", "Trade Receivables", "ar"),
    ("acc-in-cgst", "GST Input Credit - CGST", "gst_input"),
    ("acc-in-sgst", "GST Input Credit - SGST", "gst_input"),
    ("acc-in-igst", "GST Input Credit - IGST", "gst_input"),
]


def _db(accounts=ACCOUNTS):
    db = FakeDB()
    db.store["chart_of_accounts"] = [
        {"id": i, "firm_id": FIRM, "client_id": None, "account_name": n,
         "system_account_key": sk, "is_active": True} for (i, n, sk) in accounts]
    return db


def _seed(db, *, debit=59000, credit=0, category="Expense", **kw):
    row = dict(id="t1", firm_id=FIRM, client_id=CLIENT, transaction_date="2026-06-10",
               description="BANK CHARGES GST", debit_paise=debit, credit_paise=credit,
               balance_paise=0, match_status="unmatched", category=category,
               matched_entity_type=None, matched_entity_id=None, posted_journal_id=None)
    row.update(kw)
    db.store.setdefault("bank_transactions", []).append(row)
    return row


@pytest.fixture(autouse=True)
def _silence(monkeypatch):
    monkeypatch.setattr(bps.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(bps.period_validation_service, "validate_posting_date",
                        lambda *a, **k: None)
    monkeypatch.setattr(bms.timeline_service, "log", lambda *a, **k: None)
    yield


def _lines(db, je_id):
    return [l for l in db.store.get("journal_lines", []) if l["journal_entry_id"] == je_id]


def _post(db, **kw):
    return bank_posting_service.post(db, FIRM, "t1", bank_account_id="acc-bank",
                                     account_id="acc-charges", actor_id="u1", **kw)


# ══════════════════════════════════════════════════════════════════════════════
# The fake itself — a fake that lies makes every test below meaningless
# ══════════════════════════════════════════════════════════════════════════════

def test_the_fake_ilike_actually_discriminates():
    db = _db()
    q = (db.table("chart_of_accounts").select("id")
         .eq("firm_id", FIRM).ilike("account_name", "%GST Input%SGST%").execute())
    assert [r["id"] for r in q.data] == ["acc-in-sgst"]


def test_the_fake_or_scopes_client_rows_and_firm_wide_ones():
    db = _db()
    db.store["chart_of_accounts"].append(
        {"id": "other", "firm_id": FIRM, "client_id": "client-2",
         "account_name": "GST Input Credit - CGST", "system_account_key": "gst_input",
         "is_active": True})
    ids = [r["id"] for r in
           db.table("chart_of_accounts").select("id").eq("firm_id", FIRM)
           .or_(f"client_id.eq.{CLIENT},client_id.is.null")
           .ilike("account_name", "%GST Input%CGST%").execute().data]
    assert ids == ["acc-in-cgst"]          # another client's account is NOT visible


# ══════════════════════════════════════════════════════════════════════════════
# The split reaching the ledger
# ══════════════════════════════════════════════════════════════════════════════

def test_an_intrastate_charge_posts_four_lines_with_the_tax_split_out():
    """₹590 at 18%: ₹500 to Bank Charges, ₹45 to each input head, ₹590 off the bank.
    Before this feature the whole ₹590 hit Bank Charges and the credit was lost."""
    db = _db()
    _seed(db, debit=59000)
    je = _post(db, gst_rate_bps=1800)["posted_journal_id"]
    by_acc = {l["account_id"]: l for l in _lines(db, je)}
    assert len(by_acc) == 4
    assert by_acc["acc-charges"]["debit_paise"] == 50000
    assert by_acc["acc-in-cgst"]["debit_paise"] == 4500
    assert by_acc["acc-in-sgst"]["debit_paise"] == 4500
    assert by_acc["acc-bank"]["credit_paise"] == 59000


def test_the_cgst_amount_lands_on_the_cgst_account_not_the_sgst_one():
    """All three GST Input accounts share system_account_key='gst_input'
    (migration 092), so the head can only come from the name. Getting this
    backwards would still balance and still total the same ITC — and be wrong in
    GSTR-3B table 4, where the heads are reported separately."""
    db = _db()
    _seed(db, debit=59001)                 # odd tax → the halves differ by a paise
    je = _post(db, gst_rate_bps=1800)["posted_journal_id"]
    by_acc = {l["account_id"]: l["debit_paise"] for l in _lines(db, je)}
    assert by_acc["acc-in-sgst"] == by_acc["acc-in-cgst"] + 1   # odd paise to SGST


def test_an_interstate_charge_posts_igst_only():
    """IGST Act s.12(12) — place of supply for banking services is the
    recipient's location, so a bank registered elsewhere supplies inter-state."""
    db = _db()
    _seed(db, debit=59000)
    je = _post(db, gst_rate_bps=1800, is_interstate=True)["posted_journal_id"]
    by_acc = {l["account_id"]: l for l in _lines(db, je)}
    assert by_acc["acc-in-igst"]["debit_paise"] == 9000
    assert "acc-in-cgst" not in by_acc and "acc-in-sgst" not in by_acc


def test_a_zero_rate_books_the_whole_charge_but_says_so_deliberately():
    """0 is a positive statement — 'this debit carries no GST' — not a missing
    answer, so it posts the plain two-line entry without touching a tax head."""
    db = _db()
    _seed(db, debit=59000)
    je = _post(db, gst_rate_bps=0)["posted_journal_id"]
    by_acc = {l["account_id"]: l for l in _lines(db, je)}
    assert set(by_acc) == {"acc-charges", "acc-bank"}
    assert by_acc["acc-charges"]["debit_paise"] == 59000


def test_omitting_the_rate_posts_exactly_as_before():
    """Regression guard: every existing caller passes no rate and must keep
    getting the ordinary two-line entry."""
    db = _db()
    _seed(db, debit=59000)
    je = _post(db)["posted_journal_id"]
    lines = _lines(db, je)
    assert len(lines) == 2
    assert {l["account_id"] for l in lines} == {"acc-charges", "acc-bank"}


@pytest.mark.parametrize("gross", [1, 7, 99, 4999, 59001, 123457, 99999999])
@pytest.mark.parametrize("interstate", [False, True])
def test_the_posted_journal_balances_at_every_amount(gross, interstate):
    db = _db()
    _seed(db, debit=gross)
    je = _post(db, gst_rate_bps=1800, is_interstate=interstate)["posted_journal_id"]
    lines = _lines(db, je)
    assert sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines) == gross
    assert all(isinstance(l["debit_paise"], int) and isinstance(l["credit_paise"], int)
               for l in lines)


# ══════════════════════════════════════════════════════════════════════════════
# Where the split must be refused
# ══════════════════════════════════════════════════════════════════════════════

def test_a_credit_transaction_is_refused():
    """Money ARRIVING is not a bank charge. Splitting it would book negative
    input credit — a claim for tax nobody paid."""
    db = _db()
    _seed(db, debit=0, credit=59000)
    with pytest.raises(HTTPException) as ei:
        _post(db, gst_rate_bps=1800)
    assert ei.value.status_code == 422


def test_a_control_account_category_is_refused():
    """Customer Payment resolves to Trade Receivables. A GST split there would
    put input tax against a balance-sheet control account."""
    db = _db()
    _seed(db, debit=59000, category="Customer Payment")
    with pytest.raises(HTTPException) as ei:
        bank_posting_service.post(db, FIRM, "t1", bank_account_id="acc-bank",
                                  actor_id="u1", gst_rate_bps=1800)
    assert ei.value.status_code == 422


def test_a_transfer_is_refused():
    """Moving money between the client's own accounts is not a supply at all."""
    db = _db()
    _seed(db, debit=59000, category="Transfer")
    with pytest.raises(HTTPException) as ei:
        bank_posting_service.post(db, FIRM, "t1", bank_account_id="acc-bank",
                                  to_bank_account_id="acc-charges", actor_id="u1",
                                  gst_rate_bps=1800)
    assert ei.value.status_code == 422


def test_a_refused_split_writes_nothing():
    """A 422 must leave no half-made journal and no posted_journal_id behind."""
    db = _db()
    _seed(db, debit=0, credit=59000)
    with pytest.raises(HTTPException):
        _post(db, gst_rate_bps=1800)
    assert db.store.get("journal_entries", []) == []
    assert db.store["bank_transactions"][0]["posted_journal_id"] is None


def test_a_missing_gst_input_account_is_refused_not_silently_dropped():
    """Dropping the tax line would silently book the gross to Bank Charges —
    exactly the bug this feature exists to fix — so it refuses instead."""
    db = _db([a for a in ACCOUNTS if a[0] != "acc-in-sgst"])
    _seed(db, debit=59000)
    with pytest.raises(HTTPException) as ei:
        _post(db, gst_rate_bps=1800)
    assert ei.value.status_code == 422
    assert "SGST" in ei.value.detail


def test_an_inactive_gst_input_account_does_not_count():
    db = _db()
    next(a for a in db.store["chart_of_accounts"] if a["id"] == "acc-in-cgst")["is_active"] = False
    _seed(db, debit=59000)
    with pytest.raises(HTTPException) as ei:
        _post(db, gst_rate_bps=1800)
    assert ei.value.status_code == 422


def test_another_firms_gst_account_is_not_reachable():
    db = _db()
    for a in db.store["chart_of_accounts"]:
        if a["id"] == "acc-in-igst":
            a["firm_id"] = "other-firm"
    _seed(db, debit=59000)
    with pytest.raises(HTTPException) as ei:
        _post(db, gst_rate_bps=1800, is_interstate=True)
    assert ei.value.status_code == 422


def test_an_unsupported_rate_is_refused_at_the_service_too():
    """The Pydantic model closes the vocabulary for HTTP callers; the service is
    also reachable directly (multi-allocation, future jobs), so it re-checks."""
    db = _db()
    _seed(db, debit=59000)
    with pytest.raises(HTTPException) as ei:
        _post(db, gst_rate_bps=1500)
    assert ei.value.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# preview — the CA has to be able to check the arithmetic
# ══════════════════════════════════════════════════════════════════════════════

def test_preview_shows_the_split_arithmetic():
    db = _db()
    _seed(db, debit=59000)
    out = bank_posting_service.preview(db, FIRM, "t1", bank_account_id="acc-bank",
                                       account_id="acc-charges", gst_rate_bps=1800)
    assert out["gst"] == {
        "rate_bps": 1800, "is_interstate": False, "gross_paise": 59000,
        "taxable_paise": 50000, "cgst_paise": 4500, "sgst_paise": 4500,
        "igst_paise": 0, "tax_paise": 9000,
    }
    assert out["total_debit_paise"] == out["total_credit_paise"] == 59000


def test_preview_omits_the_gst_block_when_no_rate_is_asked_for():
    db = _db()
    _seed(db, debit=59000)
    out = bank_posting_service.preview(db, FIRM, "t1", bank_account_id="acc-bank",
                                       account_id="acc-charges")
    assert "gst" not in out


def test_preview_names_the_tax_accounts_it_would_use():
    db = _db()
    _seed(db, debit=59000)
    out = bank_posting_service.preview(db, FIRM, "t1", bank_account_id="acc-bank",
                                       account_id="acc-charges", gst_rate_bps=1800)
    names = {l["account_name"] for l in out["lines"]}
    assert "GST Input Credit - CGST" in names and "GST Input Credit - SGST" in names


def test_preview_writes_nothing():
    db = _db()
    _seed(db, debit=59000)
    bank_posting_service.preview(db, FIRM, "t1", bank_account_id="acc-bank",
                                 account_id="acc-charges", gst_rate_bps=1800)
    assert db.store.get("journal_entries", []) == []


# ══════════════════════════════════════════════════════════════════════════════
# The audit trail
# ══════════════════════════════════════════════════════════════════════════════

def test_the_tax_decision_is_written_to_the_audit_log(monkeypatch):
    """An input credit claimed under s.16 has to be defensible years later: who
    said this ₹590 carried 18% IGST, and when."""
    seen = {}
    monkeypatch.setattr("services.audit_service.log_event",
                        lambda *a, **k: seen.update(k), raising=False)
    db = _db()
    _seed(db, debit=59000)
    _post(db, gst_rate_bps=1800, is_interstate=True)
    assert seen["new_data"]["gst_rate_bps"] == 1800
    assert seen["new_data"]["gst_is_interstate"] is True


def test_an_ordinary_post_carries_no_gst_keys(monkeypatch):
    seen = {}
    monkeypatch.setattr("services.audit_service.log_event",
                        lambda *a, **k: seen.update(k), raising=False)
    db = _db()
    _seed(db, debit=59000)
    _post(db)
    assert "gst_rate_bps" not in seen["new_data"]


# ══════════════════════════════════════════════════════════════════════════════
# A rule carries the treatment (migration 254)
# ══════════════════════════════════════════════════════════════════════════════

def _rule(**kw):
    base = dict(id="r1", firm_id=FIRM, client_id=CLIENT, rule_name="HDFC charges",
                is_active=True, description_pattern="BANK CHARGES",
                suggested_category="Expense", suggested_account_id="acc-charges")
    base.update(kw)
    return base


def test_a_rule_carries_the_rate_and_the_place_of_supply():
    hit = match_rule("BANK CHARGES GST", 59000, True,
                     [_rule(suggested_gst_rate_bps=1800, suggested_is_interstate=True)])
    assert hit.gst_rate_bps == 1800 and hit.is_interstate is True


def test_a_rules_zero_rate_survives_as_zero():
    """`or None` would turn 'this bank's charges carry no GST' back into 'the
    rule says nothing', which is a different answer and would silently reinstate
    gross posting."""
    hit = match_rule("BANK CHARGES", 59000, True, [_rule(suggested_gst_rate_bps=0)])
    assert hit.gst_rate_bps == 0


def test_a_rule_with_no_gst_columns_reads_as_no_opinion():
    """Rules created before migration 254 have neither column."""
    hit = match_rule("BANK CHARGES", 59000, True, [_rule()])
    assert hit.gst_rate_bps is None and hit.is_interstate is False


def test_a_rate_alone_does_not_make_a_rule_fire():
    """A rate with no account has nothing to code the ex-tax amount to; letting
    it fire would only mask a later rule that actually proposes something."""
    hit = match_rule("BANK CHARGES", 59000, True, [
        _rule(suggested_category=None, suggested_account_id=None,
              suggested_narration=None, suggested_gst_rate_bps=1800),
        _rule(id="r2", rule_name="useful", suggested_category="Expense"),
    ])
    assert hit.rule_name == "useful"


def test_the_queue_offers_the_rate_on_a_debit():
    db = _db()
    _seed(db, debit=59000, category=None)
    db.store["bank_matching_rules"] = [
        _rule(suggested_gst_rate_bps=1800, suggested_is_interstate=False,
              created_at="2026-01-01")]
    row = bank_matching_service.queue(db, FIRM, CLIENT, "unmatched")[0]
    assert row["suggested_gst_rate_bps"] == 1800
    assert row["suggested_is_interstate"] is False


def test_the_queue_withholds_the_rate_on_a_credit():
    """A rule set to 'any' can fire on a receipt too. Offering 18% there would
    prefill the drawer with a split the posting engine then refuses."""
    db = _db()
    _seed(db, debit=0, credit=59000, category=None)
    db.store["bank_matching_rules"] = [
        _rule(txn_type="any", suggested_gst_rate_bps=1800, created_at="2026-01-01")]
    assert bank_matching_service.queue(db, FIRM, CLIENT, "unmatched")[0][
        "suggested_gst_rate_bps"] is None


# ══════════════════════════════════════════════════════════════════════════════
# Request validation
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("rate", [1, 100, 1500, 1801, 5000, -1800])
def test_the_post_model_closes_the_rate_vocabulary(rate):
    with pytest.raises(ValueError):
        PostBankTxnIn(gst_rate_bps=rate)


def test_the_post_model_keeps_none_and_zero_distinct():
    assert PostBankTxnIn().gst_rate_bps is None
    assert PostBankTxnIn(gst_rate_bps=0).gst_rate_bps == 0


def test_a_rule_needs_an_account_to_carry_a_rate():
    with pytest.raises(ValueError):
        MatchingRuleIn(client_id=CLIENT, rule_name="R", description_pattern="CHG",
                       suggested_category="Expense", suggested_gst_rate_bps=1800)


def test_a_credit_only_rule_cannot_carry_a_rate():
    with pytest.raises(ValueError):
        MatchingRuleIn(client_id=CLIENT, rule_name="R", description_pattern="CHG",
                       txn_type="credit", suggested_account_id="acc-charges",
                       suggested_gst_rate_bps=1800)


def test_a_debit_rule_with_an_account_is_accepted():
    r = MatchingRuleIn(client_id=CLIENT, rule_name="R", description_pattern="CHG",
                       txn_type="debit", suggested_account_id="acc-charges",
                       suggested_gst_rate_bps=1800, suggested_is_interstate=True)
    assert r.suggested_gst_rate_bps == 1800 and r.suggested_is_interstate is True


@pytest.mark.parametrize("rate", [1, 1500, 5000])
def test_the_rule_update_model_closes_the_vocabulary_too(rate):
    with pytest.raises(ValueError):
        MatchingRuleUpdateIn(suggested_gst_rate_bps=rate)


# ── router: the merged rule is what gets judged ──────────────────────────────

PARTNER = {"firm_id": FIRM, "role": "Partner", "auth_user_id": "p1", "id": "u1"}


@pytest.fixture
def rules_db(monkeypatch):
    import core.authz as authz
    import routers.banking as banking_router
    db = _db()
    monkeypatch.setattr(banking_router, "_db", lambda: db)
    monkeypatch.setattr(authz, "_USE_MOCK", True)
    db.store["bank_matching_rules"] = [_rule(created_at="2026-01-01")]
    return db, banking_router


def test_patching_a_rate_onto_a_rule_that_already_has_an_account_is_allowed(rules_db):
    """The model sees the patch alone, where 'rate, no account' looks invalid.
    Only the merged rule can answer — and here it is fine."""
    db, router = rules_db
    router.update_rule("r1", MatchingRuleUpdateIn(suggested_gst_rate_bps=1800),
                       current_user=PARTNER)
    assert db.store["bank_matching_rules"][0]["suggested_gst_rate_bps"] == 1800


def test_patching_a_rate_onto_a_rule_with_no_account_is_refused(rules_db):
    db, router = rules_db
    db.store["bank_matching_rules"][0]["suggested_account_id"] = None
    with pytest.raises(HTTPException) as ei:
        router.update_rule("r1", MatchingRuleUpdateIn(suggested_gst_rate_bps=1800),
                           current_user=PARTNER)
    assert ei.value.status_code == 422


def test_patching_a_rule_to_credit_only_is_refused_while_it_carries_a_rate(rules_db):
    db, router = rules_db
    db.store["bank_matching_rules"][0]["suggested_gst_rate_bps"] = 1800
    with pytest.raises(HTTPException) as ei:
        router.update_rule("r1", MatchingRuleUpdateIn(txn_type="credit"),
                           current_user=PARTNER)
    assert ei.value.status_code == 422


def test_an_explicit_null_clears_a_wrongly_stamped_rate(rules_db):
    """exclude_none normally makes every field unclearable on this endpoint. A
    rule stamped 18% by mistake would otherwise keep proposing an input credit
    forever, and 0 is not the escape hatch — it means something else."""
    db, router = rules_db
    db.store["bank_matching_rules"][0]["suggested_gst_rate_bps"] = 1800
    router.update_rule("r1", MatchingRuleUpdateIn(suggested_gst_rate_bps=None),
                       current_user=PARTNER)
    assert db.store["bank_matching_rules"][0]["suggested_gst_rate_bps"] is None


def test_omitting_the_rate_leaves_it_alone(rules_db):
    db, router = rules_db
    db.store["bank_matching_rules"][0]["suggested_gst_rate_bps"] = 1800
    router.update_rule("r1", MatchingRuleUpdateIn(rule_name="Renamed"),
                       current_user=PARTNER)
    assert db.store["bank_matching_rules"][0]["suggested_gst_rate_bps"] == 1800
