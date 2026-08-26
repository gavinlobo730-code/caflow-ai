"""
GST on a bank line, in BOTH directions.

WHAT WAS MISSING
    The inclusive-GST split was built for bank charges only, and the service
    refused a rate on any money coming IN. The refusal's stated reason was that
    "splitting a receipt would book negative input credit" — true, but only
    because _charge_lines resolved GST Input accounts and nothing else. The
    ARITHMETIC is direction-blind; the ACCOUNTS are not.

    So a cash sale banked directly — ₹1,18,000 in, of which ₹18,000 is tax the
    client now owes the government — could not be recorded at all.

WHAT THESE TESTS PIN
    * money out  → tax DEBITS GST Input (an asset). CGST Act s.16, input credit.
    * money in   → tax CREDITS GST Output (a liability). CGST Act s.9, output tax.
    * the two never share an account. Crediting the input asset on a sale would
      claim ITC on the client's own outward supply — the single worst thing this
      feature could do, so it is asserted by account KEY, not by name.
    * gst_return_service reads output tax as the net credit on gst_cgst /
      gst_sgst / gst_igst. A receipt banked here and the same receipt raised as
      an invoice must therefore reach the SAME three accounts, or GSTR-3B
      reports two different worlds. Asserted by key for that reason.
    * a rate is refused where it would double-count (a row settling an invoice
      or bill, which already carries its own GST) or land on a control account.
"""
import pytest
from fastapi import HTTPException

import services.bank_posting_service as bps
from services.bank_posting_service import bank_posting_service as svc
import services.journal_posting_service as jpsmod
from domain.banking.charge_gst import split_inclusive_charge, build_inclusive_lines

FIRM, CLIENT = "firm-1", "client-1"


# ── A chart with the real keys ───────────────────────────────────────────────
#
# migration 098 keys the OUTPUT heads individually — gst_cgst / gst_sgst /
# gst_igst — and only on Liability accounts. migration 092 keys ALL THREE input
# accounts 'gst_input', so the input side has to tell them apart by name. Both
# shapes are seeded here because the resolution code differs between them, and a
# fixture that flattened the difference would test something we do not ship.
ACCOUNTS = [
    ("acc-bank", "HDFC Bank", "bank", "Asset"),
    ("acc-rev", "Sales Revenue", "revenue", "Revenue"),
    ("acc-exp", "Bank Charges", None, "Expense"),
    ("acc-ar", "Trade Receivables", "ar", "Asset"),
    ("acc-ap", "Trade Payables", "ap", "Liability"),
    ("out-cgst", "GST Output - CGST", "gst_cgst", "Liability"),
    ("out-sgst", "GST Output - SGST", "gst_sgst", "Liability"),
    ("out-igst", "GST Output - IGST", "gst_igst", "Liability"),
    ("in-cgst", "GST Input Credit - CGST", "gst_input", "Asset"),
    ("in-sgst", "GST Input Credit - SGST", "gst_input", "Asset"),
    ("in-igst", "GST Input Credit - IGST", "gst_input", "Asset"),
]


class _Resp:
    def __init__(self, data): self.data = data


class _Q:
    """Enough PostgREST to let the REAL resolvers run.

    `ilike` is modelled FAITHFULLY rather than stubbed to a no-op. A no-op
    ilike makes every name lookup match the first row in the chart, which would
    let "resolve the IGST account" pass while returning the bank — the exact
    class of false pass these tests exist to catch.
    """
    def __init__(self, store, table):
        self.s, self.t = store, table
        self.op, self.payload, self.f, self.pats = "select", None, [], []
        self.single_ = False

    def insert(self, p): self.op, self.payload = "insert", p; return self
    def update(self, p): self.op, self.payload = "update", p; return self
    def select(self, *a, **k): self.op = "select"; return self
    def eq(self, k, v): self.f.append((k, v)); return self
    def is_(self, k, _v): self.f.append((k, ("__null__",))); return self
    def in_(self, k, vals): self.f.append((k, ("__in__", list(vals)))); return self
    def limit(self, _n): return self
    def order(self, *_a, **_k): return self
    def single(self): self.single_ = True; return self

    def or_(self, expr, *_a, **_k):
        # Only the client_id-or-null scope is modelled; anything else would be
        # silently ignored, so refuse it rather than quietly widening a filter.
        if "client_id" not in expr:
            raise AssertionError(f"unmodelled or_(): {expr}")
        return self

    def ilike(self, col, pattern):
        self.pats.append((col, pattern.strip("%").lower()))
        return self

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
            if ok:
                for col, frag in self.pats:
                    # "%GST Input%CGST%" → every fragment present, in order.
                    hay, pos = str(r.get(col) or "").lower(), 0
                    for part in [p for p in frag.split("%") if p]:
                        i = hay.find(part, pos)
                        if i < 0: ok = False; break
                        pos = i + len(part)
                    if not ok: break
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
        if self.single_:
            return _Resp(m[0] if m else None)
        return _Resp(m)


class FakeDB:
    def __init__(self): self.store = {}
    def table(self, n): return _Q(self.store, n)


def _db(*, drop_keys=()):
    db = FakeDB()
    db.store["chart_of_accounts"] = [
        {"id": i, "firm_id": FIRM, "client_id": None, "account_name": n,
         "system_account_key": sk, "account_type": at, "is_active": True}
        for (i, n, sk, at) in ACCOUNTS if sk not in drop_keys
    ]
    return db


def _txn(db, *, credit=0, debit=0, category=None, account_id=None,
         matched_type=None, matched_id=None, **kw):
    row = dict(id="t1", firm_id=FIRM, client_id=CLIENT, transaction_date="2026-06-10",
               description="TEST", debit_paise=debit, credit_paise=credit,
               category=category, account_id=account_id,
               matched_entity_type=matched_type, matched_entity_id=matched_id,
               match_status="matched" if matched_id else "unmatched",
               posted_journal_id=None)
    row.update(kw)
    db.store.setdefault("bank_transactions", []).append(row)
    return row


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(bps.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(jpsmod.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr("services.audit_service.log_event", lambda *a, **k: None, raising=False)
    yield


def _key_of(db, account_id):
    return next(a["system_account_key"] for a in db.store["chart_of_accounts"]
                if a["id"] == account_id)


def _plan(db, txn, **kw):
    return svc._plan(db, FIRM, txn, None, txn.get("account_id"), None, **kw)


# ── the arithmetic is the same both ways; the accounts are not ───────────────

def test_the_split_itself_does_not_care_which_way_the_money_went():
    # ₹1,18,000 inclusive at 18% is ₹1,00,000 + ₹18,000 whether it arrived or left.
    s = split_inclusive_charge(11_800_000, 1800)
    assert (s.taxable_paise, s.cgst_paise, s.sgst_paise) == (10_000_000, 900_000, 900_000)


def test_money_in_debits_the_bank_and_credits_everything_else():
    s = split_inclusive_charge(11_800_000, 1800)
    lines = build_inclusive_lines(s, bank_account_id="BANK", counter_account_id="REV",
                                  is_credit=True, cgst_account_id="OC", sgst_account_id="OS")
    assert sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines)
    dr = [l for l in lines if l["debit_paise"]]
    assert len(dr) == 1 and dr[0]["account_id"] == "BANK" and dr[0]["debit_paise"] == 11_800_000
    by = {l["account_id"]: l["credit_paise"] for l in lines if l["credit_paise"]}
    assert by == {"REV": 10_000_000, "OC": 900_000, "OS": 900_000}


def test_money_out_keeps_the_old_shape():
    s = split_inclusive_charge(59_000, 1800)
    lines = build_inclusive_lines(s, bank_account_id="BANK", counter_account_id="EXP",
                                  is_credit=False, cgst_account_id="IC", sgst_account_id="IS")
    cr = [l for l in lines if l["credit_paise"]]
    assert len(cr) == 1 and cr[0]["account_id"] == "BANK" and cr[0]["credit_paise"] == 59_000
    by = {l["account_id"]: l["debit_paise"] for l in lines if l["debit_paise"]}
    assert by == {"EXP": 50_000, "IC": 4_500, "IS": 4_500}


def test_the_narration_cites_the_section_that_applies_to_that_direction():
    # CLAUDE.md: GST logic carries its section. s.9 levies output tax on an
    # outward supply; s.16 grants the credit on an inward one. A line that cited
    # the wrong one would describe the opposite transaction.
    s = split_inclusive_charge(11_800_000, 1800)
    out = " ".join(l["narration"] for l in build_inclusive_lines(
        s, bank_account_id="B", counter_account_id="R", is_credit=True,
        cgst_account_id="OC", sgst_account_id="OS"))
    inn = " ".join(l["narration"] for l in build_inclusive_lines(
        s, bank_account_id="B", counter_account_id="E", is_credit=False,
        cgst_account_id="IC", sgst_account_id="IS"))
    assert "Output CGST (CGST Act s.9)" in out and "s.16" not in out
    assert "Input CGST (CGST Act s.16)" in inn and "s.9" not in inn


# ── through the service: the tax must land on the right SIDE of the sheet ────

def test_a_banked_cash_sale_credits_gst_output_not_gst_input():
    db = _db()
    txn = _txn(db, credit=11_800_000, category="Sales Receipt", account_id="acc-rev")
    _etype, lines, _bank = _plan(db, txn, gst_rate_bps=1800, is_interstate=False)
    tax = {_key_of(db, l["account_id"]): l["credit_paise"]
           for l in lines if l["credit_paise"] and l["account_id"] != "acc-rev"}
    # By KEY, not by name: gst_return_service sums output tax over exactly these.
    assert tax == {"gst_cgst": 900_000, "gst_sgst": 900_000}
    assert all(_key_of(db, l["account_id"]) != "gst_input" for l in lines), \
        "claimed input credit on the client's own outward supply"


def test_an_inter_state_receipt_uses_the_igst_output_head():
    db = _db()
    txn = _txn(db, credit=11_800_000, category="Sales Receipt", account_id="acc-rev")
    _e, lines, _b = _plan(db, txn, gst_rate_bps=1800, is_interstate=True)
    tax = {_key_of(db, l["account_id"]): l["credit_paise"]
           for l in lines if l["credit_paise"] and l["account_id"] != "acc-rev"}
    assert tax == {"gst_igst": 1_800_000}


def test_a_charge_going_out_still_debits_the_input_heads():
    db = _db()
    txn = _txn(db, debit=59_000, category="Expense", account_id="acc-exp")
    _e, lines, _b = _plan(db, txn, gst_rate_bps=1800, is_interstate=False)
    tax = {l["account_id"]: l["debit_paise"]
           for l in lines if l["debit_paise"] and l["account_id"] != "acc-exp"}
    assert tax == {"in-cgst": 4_500, "in-sgst": 4_500}


def test_zero_rate_is_a_real_answer_and_posts_two_lines():
    db = _db()
    txn = _txn(db, credit=11_800_000, category="Sales Receipt", account_id="acc-rev")
    _e, lines, _b = _plan(db, txn, gst_rate_bps=0, is_interstate=False)
    assert len(lines) == 2
    assert {l["account_id"] for l in lines} == {"acc-bank", "acc-rev"}


def test_a_single_account_chart_collapses_the_heads_exactly_as_an_invoice_would():
    """Plenty of small charts carry ONE "GST Output Tax Payable" rather than
    three heads. phase2_journal_service resolves output tax by key first and
    falls back to %GST Output% precisely so those charts work, and this path
    calls the same helper — so a receipt banked here lands where an invoice for
    the same supply would. Diverging (a head-specific pattern) would make the
    bank route fail on a chart the sales route accepts, which is the drift the
    shared helper exists to prevent.
    """
    db = _db(drop_keys=("gst_cgst", "gst_sgst", "gst_igst"))
    db.store["chart_of_accounts"].append(
        {"id": "acc-gst", "firm_id": FIRM, "client_id": None,
         "account_name": "GST Output Tax Payable", "system_account_key": "gst_output",
         "account_type": "Liability", "is_active": True})
    txn = _txn(db, credit=11_800_000, category="Sales Receipt", account_id="acc-rev")
    _e, lines, _b = _plan(db, txn, gst_rate_bps=1800, is_interstate=False)
    combined = sum(l["credit_paise"] for l in lines if l["account_id"] == "acc-gst")
    assert combined == 1_800_000, "both heads belong on the one output account"


def test_no_output_account_at_all_says_so_rather_than_posting_somewhere_else():
    db = _db(drop_keys=("gst_cgst", "gst_sgst", "gst_igst"))
    txn = _txn(db, credit=11_800_000, category="Sales Receipt", account_id="acc-rev")
    with pytest.raises(HTTPException) as e:
        _plan(db, txn, gst_rate_bps=1800, is_interstate=False)
    assert e.value.status_code == 422 and "GST Output" in e.value.detail


# ── where a rate must be refused ─────────────────────────────────────────────

def test_a_row_that_settles_an_invoice_refuses_a_rate():
    # The invoice already booked its own CGST/SGST. Taxing the bank line too
    # would credit the same output tax twice for one supply.
    db = _db()
    db.store["sales_invoices"] = [{"id": "inv-1", "firm_id": FIRM, "client_id": CLIENT,
                                   "total_paise": 11_800_000, "amount_paid_paise": 0}]
    txn = _txn(db, credit=11_800_000, category="Customer Payment",
               matched_type="sales_invoice", matched_id="inv-1")
    with pytest.raises(HTTPException) as e:
        _plan(db, txn, gst_rate_bps=1800, is_interstate=False)
    assert e.value.status_code == 422 and "twice" in e.value.detail


def test_a_control_account_category_refuses_a_rate():
    db = _db()
    txn = _txn(db, credit=11_800_000, category="Customer Payment")
    with pytest.raises(HTTPException) as e:
        _plan(db, txn, gst_rate_bps=1800, is_interstate=False)
    assert e.value.status_code == 422 and "control account" in e.value.detail


def test_a_transfer_refuses_a_rate():
    db = _db()
    txn = _txn(db, debit=1_000_000, category="Transfer", account_id="acc-bank")
    with pytest.raises(HTTPException) as e:
        _plan(db, txn, gst_rate_bps=1800, is_interstate=False)
    assert e.value.status_code == 422 and "not a supply" in e.value.detail


# ── the guard that lets the category stop being a question ───────────────────

def test_a_matched_invoice_posts_to_receivables_whatever_the_category_says():
    """Sales Receipt is an EXPLICIT_COUNTER category AND settles a sales invoice.

    If it took the picked ledger, a matched receipt would credit Sales — which
    the invoice already credited — while still marking the invoice paid:
    revenue twice, Trade Receivables never cleared. _resolve_counter's
    matched-invoice branch is what stops that, and it is the reason the category
    can be derived rather than asked for. Pinned here because nothing else
    tests the EXPLICIT_COUNTER-plus-settles combination.
    """
    db = _db()
    db.store["sales_invoices"] = [{"id": "inv-1", "firm_id": FIRM, "client_id": CLIENT,
                                   "total_paise": 11_800_000, "amount_paid_paise": 0}]
    txn = _txn(db, credit=11_800_000, category="Sales Receipt",
               matched_type="sales_invoice", matched_id="inv-1", account_id="acc-rev")
    assert svc._settles_a_document(txn) is True
    assert svc._resolve_counter(db, FIRM, txn, None) == "acc-ar"


# ── the queue tells the screen what the engine would accept ──────────────────

@pytest.mark.parametrize("category,settles,is_split,expected", [
    ("Expense",          False, False, True),   # money out, explicit ledger
    ("Sales Receipt",    False, False, True),   # money in, explicit ledger
    ("Other",            False, False, True),
    ("Customer Payment", False, False, False),  # control account
    ("Vendor Payment",   False, False, False),
    ("GST Payment",      False, False, False),
    ("Transfer",         False, False, False),  # not a supply
    ("Sales Receipt",    True,  False, False),  # the document carries the tax
    ("Expense",          False, True,  False),  # a rate per leg is a bigger design
    (None,               False, False, False),  # no ledger chosen yet
])
def test_the_flag_matches_what_the_engine_would_accept(category, settles, is_split, expected):
    """One rule, two readers. If these ever disagree the screen offers a control
    the post then rejects — which reads to a CA as the software being broken,
    not as a rule being enforced."""
    from domain.banking import posting_map as pmap
    assert pmap.gst_split_allowed(
        category, settles_document=settles, is_split=is_split) is expected


@pytest.mark.parametrize("category,mtype,expected", [
    ("Customer Payment", "sales_invoice",  True),
    ("Sales Receipt",    "sales_invoice",  True),
    ("Vendor Payment",   "purchase_bill",  True),
    # A match is NOT a settlement on its own. The entity has to be the kind the
    # category settles, or _settle would mark a document paid that this line has
    # nothing to do with — and the GST guard would refuse a rate for no reason.
    ("Expense",          "sales_invoice",  False),
    ("Expense",          "purchase_bill",  False),
    ("Customer Payment", "purchase_bill",  False),
    ("Vendor Payment",   "sales_invoice",  False),
    ("Customer Payment", "receipt",        False),
])
def test_settling_needs_the_right_kind_of_document_not_merely_a_match(category, mtype, expected):
    from domain.banking import posting_map as pmap
    assert pmap.settles_document(category, mtype, "ent-1") is expected
    assert pmap.settles_document(category, mtype, None) is False, \
        "nothing settles without a document to settle"


def test_the_queue_stamps_the_flag_on_every_row():
    from services.bank_matching_service import bank_matching_service as q
    rows = [
        {"id": "a", "category": "Expense", "debit_paise": 59_000, "credit_paise": 0},
        {"id": "b", "category": "Customer Payment", "debit_paise": 0, "credit_paise": 100},
        {"id": "c", "category": "Sales Receipt", "credit_paise": 100, "is_split": True},
        {"id": "d", "category": "Customer Payment", "credit_paise": 100,
         "matched_entity_type": "sales_invoice", "matched_entity_id": "inv-1"},
    ]
    q._mark_gst_eligibility(rows)
    assert [r["gst_allowed"] for r in rows] == [True, False, False, False]
    assert all("gst_allowed" in r for r in rows), "a row with no flag renders no control at all"
