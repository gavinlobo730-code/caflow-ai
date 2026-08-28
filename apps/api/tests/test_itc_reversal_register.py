"""A reclaimable ITC reversal, and the reclaim that later releases it.

WHAT WAS WRONG
    GSTR-3B Table 4(B)(2) declares credit reversed that may come back — Rule
    37/37A, CGST Act §16(2)(b) and (c) — and Table 4(D)(1) declares the reclaim
    when it does. Neither could ever be filled. Nothing recorded that a
    reclaimable reversal had happened, so there was never anything to reclaim
    against, and 4(D)(1) shipped as a hard-coded zero.

WHY THE REGISTER CLASSIFIES A JOURNAL INSTEAD OF POSTING ONE
    CLAUDE.md: one posting kernel, no alternative paths. Giving credit back
    credits GST Input, and that posting already has a home — the CA raises a
    manual journal like any other entry. What was missing was never a way to
    POST the reversal but a way to say WHAT IT WAS: a journal crediting GST
    Input could be Rule 37, a cancelled bill, or a correction, and the return
    has to tell them apart.

    So a register row points at an already-posted journal. It cannot drift from
    the ledger because it never writes to one.

THE INTEGRITY CHECK IS THE POINT
    A register row is a figure on a filed return. If it could claim more than
    its journal moved, the return would declare a reversal the ledger does not
    support — and because the same register feeds the books side of the
    reconciliation, the comparator would be checking a number against itself
    and agreeing. Most of this file is that check.
"""
import pytest

import services.itc_register_service as reg
from services.itc_register_service import ITCRegisterError

FIRM, CLIENT = "firm-1", "client-1"
JUNE, JULY = "062026", "072026"


class _Resp:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, store, table):
        self.s, self.t, self.op, self.payload = store, table, "select", None
        self.f, self.ors = [], None

    def select(self, *_a, **_k): self.op = "select"; return self
    def insert(self, p): self.op, self.payload = "insert", p; return self
    def eq(self, k, v): self.f.append((k, v)); return self
    def gt(self, k, v): self.f.append(("__gt__" + k, v)); return self
    def order(self, *_a, **_k): return self
    def limit(self, _n): return self

    def or_(self, expr):
        preds = []
        for clause in expr.split(","):
            col, op, val = clause.split(".", 2)
            if op == "eq":
                preds.append(lambda r, c=col, v=val: r.get(c) == v)
            elif op == "is" and val == "null":
                preds.append(lambda r, c=col: r.get(c) is None)
        self.ors = preds
        return self

    def execute(self):
        rows = self.s.setdefault(self.t, [])
        if self.op == "insert":
            row = dict(self.payload)
            row.setdefault("id", f"{self.t}-{len(rows) + 1}")
            rows.append(row)
            return _Resp([row])
        m = []
        for r in rows:
            ok = True
            for k, v in self.f:
                if k.startswith("__gt__"):
                    if not (str(r.get(k[6:]) or "") > str(v)):
                        ok = False
                elif r.get(k) != v:
                    ok = False
            if ok and self.ors and not any(p(r) for p in self.ors):
                ok = False
            if ok:
                m.append(r)
        return _Resp(m)


class FakeDB:
    def __init__(self): self.store = {}
    def table(self, n): return _Q(self.store, n)


GST_INPUT = "acc-gst-input"


@pytest.fixture
def db():
    d = FakeDB()
    d.store["chart_of_accounts"] = [
        {"id": GST_INPUT, "firm_id": FIRM, "client_id": None,
         "system_account_key": "gst_input", "account_name": "GST Input Tax Credit",
         "account_type": "Asset"},
        {"id": "acc-exp", "firm_id": FIRM, "client_id": None,
         "system_account_key": None, "account_name": "ITC Written Off",
         "account_type": "Expense"},
    ]
    d.store["journal_entries"] = []
    d.store["journal_lines"] = []
    d.store["itc_reversal_register"] = []
    return d


def _journal(db, jid, *, credit_gst_input=0, debit_gst_input=0, posted=True,
             client_id=CLIENT, firm_id=FIRM):
    db.store["journal_entries"].append({
        "id": jid, "firm_id": firm_id, "client_id": client_id,
        "is_posted": posted, "entry_date": "2026-06-10", "reference_no": jid})
    db.store["journal_lines"].append({
        "journal_entry_id": jid, "account_id": GST_INPUT,
        "debit_paise": debit_gst_input, "credit_paise": credit_gst_input})
    db.store["journal_lines"].append({
        "journal_entry_id": jid, "account_id": "acc-exp",
        "debit_paise": credit_gst_input, "credit_paise": debit_gst_input})
    return jid


def _rev(db, jid, **kw):
    kw.setdefault("period", JUNE)
    kw.setdefault("reason_code", "rule_37")
    kw.setdefault("amounts", {"cgst_paise": 4500, "sgst_paise": 4500})
    return reg.record_reversal(db, FIRM, CLIENT, journal_entry_id=jid, **kw)


# ── the happy path ───────────────────────────────────────────────────────────

def test_a_posted_reversal_journal_can_be_registered(db):
    _journal(db, "je-1", credit_gst_input=9000)
    row = _rev(db, "je-1")
    assert row["kind"] == "reversal"
    assert row["cgst_paise"] == 4500 and row["sgst_paise"] == 4500
    assert row["reverses_id"] is None


def test_the_period_report_splits_reversals_from_reclaims(db):
    _journal(db, "je-1", credit_gst_input=9000)
    rev = _rev(db, "je-1")
    _journal(db, "je-2", debit_gst_input=9000)
    reg.record_reclaim(db, FIRM, CLIENT, journal_entry_id="je-2", period=JULY,
                       reverses_id=rev["id"],
                       amounts={"cgst_paise": 4500, "sgst_paise": 4500})

    june = reg.for_period(db, FIRM, CLIENT, JUNE)
    july = reg.for_period(db, FIRM, CLIENT, JULY)
    assert len(june["reversals"]) == 1 and june["reclaims"] == []
    assert july["reversals"] == [] and len(july["reclaims"]) == 1
    assert june["reversal_totals"]["cgst_paise"] == 4500
    assert july["reclaim_totals"]["cgst_paise"] == 4500


# ── the integrity check ──────────────────────────────────────────────────────

def test_a_row_cannot_declare_more_than_its_journal_moved(db):
    """THE check. Without it the register could put a figure on a return that
    the ledger does not support, and the reconciliation would agree with it
    because the register feeds both sides."""
    _journal(db, "je-1", credit_gst_input=9000)
    with pytest.raises(ITCRegisterError, match="does not support|declares"):
        _rev(db, "je-1", amounts={"cgst_paise": 50000, "sgst_paise": 0})


def test_declaring_exactly_what_moved_is_allowed(db):
    """Guard: the check must bite on excess, not on everything."""
    _journal(db, "je-1", credit_gst_input=9000)
    assert _rev(db, "je-1", amounts={"cgst_paise": 9000})["cgst_paise"] == 9000


def test_a_journal_that_takes_credit_cannot_be_a_reversal(db):
    """A DEBIT to GST Input takes credit. It gives nothing back."""
    _journal(db, "je-1", debit_gst_input=9000)
    with pytest.raises(ITCRegisterError):
        _rev(db, "je-1")


def test_a_draft_journal_cannot_support_a_return_figure(db):
    _journal(db, "je-1", credit_gst_input=9000, posted=False)
    with pytest.raises(ITCRegisterError, match="draft"):
        _rev(db, "je-1")


def test_the_same_journal_cannot_be_registered_twice(db):
    _journal(db, "je-1", credit_gst_input=90000)
    _rev(db, "je-1")
    with pytest.raises(ITCRegisterError, match="already registered"):
        _rev(db, "je-1")


def test_another_clients_journal_is_refused(db):
    _journal(db, "je-1", credit_gst_input=9000, client_id="client-2")
    with pytest.raises(ITCRegisterError, match="different client"):
        _rev(db, "je-1")


def test_another_firms_journal_is_not_even_found(db):
    _journal(db, "je-1", credit_gst_input=9000, firm_id="firm-2")
    with pytest.raises(ITCRegisterError, match="not found"):
        _rev(db, "je-1")


# ── only reclaimable grounds belong here ─────────────────────────────────────

@pytest.mark.parametrize("reason", ["rule_37", "rule_37a", "section_16_2b",
                                    "section_16_2c", "other"])
def test_every_reclaimable_ground_is_accepted(db, reason):
    _journal(db, f"je-{reason}", credit_gst_input=9000)
    assert _rev(db, f"je-{reason}", reason_code=reason)["reason_code"] == reason


@pytest.mark.parametrize("reason", ["rule_42", "section_17_5", "rule_38"])
def test_a_permanent_ground_is_refused(db, reason):
    """Rules 38/42/43 and §17(5) are Table 4(B)(1), derived from the documents.
    Registering one would declare the same reversal twice."""
    _journal(db, "je-1", credit_gst_input=9000)
    with pytest.raises(ITCRegisterError, match="permanent|4\\(B\\)\\(1\\)"):
        _rev(db, "je-1", reason_code=reason)


# ── a reclaim can only take back what was reversed ───────────────────────────

def test_a_reclaim_cannot_exceed_its_reversal(db):
    _journal(db, "je-1", credit_gst_input=9000)
    rev = _rev(db, "je-1")
    _journal(db, "je-2", debit_gst_input=50000)
    with pytest.raises(ITCRegisterError, match="only come back once"):
        reg.record_reclaim(db, FIRM, CLIENT, journal_entry_id="je-2",
                           period=JULY, reverses_id=rev["id"],
                           amounts={"cgst_paise": 5000})


def test_a_reversal_can_be_reclaimed_in_parts(db):
    _journal(db, "je-1", credit_gst_input=9000)
    rev = _rev(db, "je-1")
    _journal(db, "je-2", debit_gst_input=3000)
    reg.record_reclaim(db, FIRM, CLIENT, journal_entry_id="je-2", period=JULY,
                       reverses_id=rev["id"], amounts={"cgst_paise": 3000})
    assert reg.outstanding_for(db, FIRM, rev["id"])["cgst_paise"] == 1500

    _journal(db, "je-3", debit_gst_input=1500)
    reg.record_reclaim(db, FIRM, CLIENT, journal_entry_id="je-3", period=JULY,
                       reverses_id=rev["id"], amounts={"cgst_paise": 1500})
    assert reg.outstanding_for(db, FIRM, rev["id"])["cgst_paise"] == 0

    _journal(db, "je-4", debit_gst_input=100)
    with pytest.raises(ITCRegisterError, match="only come back once"):
        reg.record_reclaim(db, FIRM, CLIENT, journal_entry_id="je-4",
                           period=JULY, reverses_id=rev["id"],
                           amounts={"cgst_paise": 100})


def test_a_reclaim_is_checked_head_by_head(db):
    """CGST reversed cannot be reclaimed as SGST. They are different taxes."""
    _journal(db, "je-1", credit_gst_input=9000)
    rev = _rev(db, "je-1", amounts={"cgst_paise": 9000})
    _journal(db, "je-2", debit_gst_input=9000)
    with pytest.raises(ITCRegisterError, match="sgst"):
        reg.record_reclaim(db, FIRM, CLIENT, journal_entry_id="je-2",
                           period=JULY, reverses_id=rev["id"],
                           amounts={"sgst_paise": 9000})


def test_a_zero_row_is_not_a_declaration(db):
    _journal(db, "je-1", credit_gst_input=9000)
    with pytest.raises(ITCRegisterError, match="nothing"):
        _rev(db, "je-1", amounts={})


# ── the routes ───────────────────────────────────────────────────────────────

def test_the_routes_are_registered():
    from main import app
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    for p in ("/api/gst-workspace/itc/register",
              "/api/gst-workspace/itc/register/reversal",
              "/api/gst-workspace/itc/register/reclaim"):
        assert p in paths, p
