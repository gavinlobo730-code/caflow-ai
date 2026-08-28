"""
"Apply suggestions" must be able to say what it is about to do — and be right.

WHY THIS EXISTS
    The action coded N rows from rules and payee history and reported "20
    applied". A CA is answerable for every one of those lines and could not see,
    before pressing it, which lines had a suggestion, what each suggestion was,
    or whose authority it came from — nor afterwards which ledger had landed on
    which line. Reported by the CA in exactly those words.

    So the screen previews it. The danger in a preview is that it becomes a
    SECOND implementation: the browser guessing from suggested_account_id, or a
    parallel copy of the rule matching. Then the list the CA approves and the
    writes that follow can disagree, the CA has authorised one thing and the
    books carry another, and nothing reports it — the failure is silent by
    construction.

    accept(preview=True) is therefore the same function, the same loop and the
    same refusals, stopping short of the write. This file is what holds that:
    it runs both modes over one fixture and asserts they agree row for row.
"""
import pytest

import services.bank_batch_service as bbs
from services.bank_batch_service import bank_batch_service as svc

FIRM, CLIENT = "firm-1", "client-1"


class _Resp:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, store, table):
        self.s, self.t, self.op, self.payload, self.f = store, table, "select", None, []
        self.in_f = None

    def select(self, *_a, **_k): self.op = "select"; return self
    def update(self, p): self.op, self.payload = "update", p; return self
    def eq(self, k, v): self.f.append((k, v)); return self
    def in_(self, k, vals): self.in_f = (k, set(vals)); return self
    def order(self, *_a, **_k): return self
    def limit(self, _n): return self

    def execute(self):
        rows = self.s.setdefault(self.t, [])
        m = [r for r in rows if all(r.get(k) == v for k, v in self.f)]
        if self.in_f:
            k, vals = self.in_f
            m = [r for r in m if r.get(k) in vals]
        if self.op == "update":
            for r in m:
                r.update(self.payload)
        return _Resp(m)


class FakeDB:
    def __init__(self): self.store = {}
    def table(self, n): return _Q(self.store, n)


def _txn(tid, descr, **kw):
    row = {"id": tid, "firm_id": FIRM, "client_id": CLIENT, "description": descr,
           "debit_paise": 59000, "credit_paise": 0, "category": None,
           "account_id": None, "payee_name": None, "payee_id": None,
           "match_status": "unmatched", "posted_journal_id": None,
           "posted_at": None, "transaction_date": "2026-04-15"}
    row.update(kw)
    return row


def _db():
    """One line a RULE covers, one line HISTORY covers, one line nothing covers,
    one already coded, and one already posted — every branch of the loop."""
    db = FakeDB()
    db.store["bank_transactions"] = [
        _txn("t-rule", "NEFT CHARGES APR2026"),
        _txn("t-hist", "UPI/DR/999/RAMESH KUMAR/HDFC", payee_name="RAMESH KUMAR"),
        _txn("t-none", "SOMETHING NOBODY HAS SEEN"),
        _txn("t-coded", "NEFT CHARGES MAY2026", account_id="acc-charges",
             category="Expense"),
        _txn("t-posted", "NEFT CHARGES JUN2026", match_status="posted",
             posted_journal_id="je-9"),
        # The evidence history learns from: a POSTED row for the same payee.
        _txn("t-teacher", "UPI/DR/111/RAMESH KUMAR/HDFC", payee_name="RAMESH KUMAR",
             account_id="acc-rent", category="Expense", match_status="posted",
             posted_journal_id="je-1", posted_at="2026-03-01T00:00:00Z"),
    ]
    db.store["bank_matching_rules"] = [{
        "id": "r1", "firm_id": FIRM, "client_id": CLIENT, "is_active": True,
        "rule_name": "Bank charges", "description_pattern": "CHARGES",
        "amount_min_paise": None, "amount_max_paise": None, "txn_type": "any",
        "suggested_category": "Expense", "suggested_account_id": "acc-charges",
        "suggested_narration": None, "suggested_gst_rate_bps": None,
        "suggested_is_interstate": False, "created_at": "2026-01-01",
    }]
    return db


IDS = ["t-rule", "t-hist", "t-none", "t-coded", "t-posted"]


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(svc, "_log_batch", lambda *a, **k: None)
    yield


def _by_id(res):
    return {r["transaction_id"]: r for r in res["results"]}


# ── the fixture has to actually produce suggestions ──────────────────────────

def test_the_fixture_produces_both_kinds_of_suggestion():
    """Guard: if neither source fired, the parity assertions below would be
    comparing two empty answers and would hold for any implementation."""
    out = svc.accept(_db(), FIRM, IDS, preview=True)
    got = _by_id(out)
    assert got["t-rule"]["status"] == "would_apply", got["t-rule"]
    assert "rule" in got["t-rule"]["source"], got["t-rule"]["source"]
    assert got["t-hist"]["status"] == "would_apply", got["t-hist"]
    assert "before" in got["t-hist"]["source"], got["t-hist"]["source"]


# ── a preview writes nothing ─────────────────────────────────────────────────

def test_a_preview_changes_no_row():
    db = _db()
    before = [dict(r) for r in db.store["bank_transactions"]]
    svc.accept(db, FIRM, IDS, preview=True)
    assert db.store["bank_transactions"] == before, (
        "the preview wrote to the queue — a CA who pressed Cancel would have "
        "been coded anyway")


def test_a_preview_reports_nothing_as_applied():
    out = svc.accept(_db(), FIRM, IDS, preview=True)
    assert out["applied"] == 0, "nothing was written, so nothing may be counted as applied"
    assert out["would_apply"] == 2, out


def test_a_preview_leaves_no_audit_trail(monkeypatch):
    """A CA who previews and cancels must not appear to have accepted a batch."""
    seen = []
    monkeypatch.setattr(svc, "_log_batch", lambda *a, **k: seen.append(a))
    svc.accept(_db(), FIRM, IDS, preview=True)
    assert seen == [], "the preview logged a batch action it did not take"
    svc.accept(_db(), FIRM, IDS, preview=False)
    assert len(seen) == 1, "the real action must still be logged"


# ── and it tells the truth about what the real one does ──────────────────────

def test_the_preview_promises_exactly_what_the_apply_writes():
    """THE GUARANTEE. Row for row: same verdict, same ledger, same source."""
    promised = _by_id(svc.accept(_db(), FIRM, IDS, preview=True))

    db = _db()
    done = _by_id(svc.accept(db, FIRM, IDS, preview=False))

    assert set(promised) == set(done)
    for tid in promised:
        p, d = promised[tid], done[tid]
        # "would_apply" is the preview's word for "applied"; every other verdict
        # must match exactly, including the refusals.
        p_status = "applied" if p["status"] == "would_apply" else p["status"]
        assert p_status == d["status"], f"{tid}: previewed {p['status']}, got {d['status']}"
        assert p.get("account_id") == d.get("account_id"), f"{tid}: different ledger"
        assert p.get("category") == d.get("category"), f"{tid}: different category"
        assert p.get("source") == d.get("source"), f"{tid}: different authority"

    # And what the apply actually WROTE is what was promised — not merely what
    # it reported. A result dict can say anything; the row is the fact.
    rows = {r["id"]: r for r in db.store["bank_transactions"]}
    for tid, p in promised.items():
        if p["status"] == "would_apply":
            assert rows[tid]["account_id"] == p["account_id"], (
                f"{tid}: the preview promised {p['account_id']} and the row got "
                f"{rows[tid]['account_id']}")


def test_the_refusals_are_previewed_too():
    """A CA needs to know what will be LEFT ALONE, not only what changes."""
    got = _by_id(svc.accept(_db(), FIRM, IDS, preview=True))
    assert got["t-none"]["status"] == "skipped"
    assert "no rule matches" in got["t-none"]["reason"]
    assert got["t-coded"]["status"] == "skipped"
    assert "Already coded" in got["t-coded"]["reason"]
    assert got["t-posted"]["status"] == "skipped"
    assert "Already posted" in got["t-posted"]["reason"]


def test_the_preview_names_the_line_it_is_talking_about():
    """The modal lists lines, so each result has to carry enough to name one."""
    got = _by_id(svc.accept(_db(), FIRM, IDS, preview=True))
    assert got["t-rule"]["description"] == "NEFT CHARGES APR2026"
    assert got["t-rule"]["account_id"] == "acc-charges"
