"""
Account-first bank coding — the ledger IS the answer, the category follows.

WHAT THIS COVERS
    Coding a statement line used to need two answers in a fixed order: a
    Category, then — only for some categories, and only after the first answer
    revealed the second control — the GL account. domain/banking/account_category
    derives the first from the second so the screen asks once.

    The derivation is a label. What these tests actually defend is the one thing
    that is NOT a label:

        THE GUARANTEE — coding a line account-first posts the counter leg to
        EXACTLY the account that was picked.

    That is not free. Three categories (posting_map.AUTO_COUNTER) make
    bank_posting_service._resolve_counter re-resolve the account from a control
    key and ignore account_id entirely — and a key does not identify ONE
    account. Migration 092 stamps 'ar' on anything named "trade receivable" OR
    "accounts receivable" OR "sundry debtor", so a chart holding two of those
    names holds two accounts keyed 'ar', and _find_account picks between them
    with `.limit(1)` and no ORDER BY. Deriving "Customer Payment" from the
    account the CA picked would post to whichever one came back.

    So `_real_chart` below seeds that collision — Accounts Receivable AND Trade
    Receivables, both keyed 'ar' — and `test_every_account_posts_to_itself` runs
    every account in it through set_account and then through the real
    _resolve_counter, asserting the id comes back unchanged. It is written
    against the real resolver rather than a stub for exactly that reason:
    phase2_journal_service._find_account runs here, over a fake that models
    PostgREST's eq/or/ilike.

    The chart also carries the live mirror case — Trade Payables with a NULL key
    beside a keyed Accounts Payable — which is safe for a different reason: with
    no key there is no auto category to derive.

NEGATIVE CONTROLS RUN
    Each assertion below was checked against code without the thing it defends:
      * dropping the resolve-back check makes Trade Receivables derive "Customer
        Payment" and _resolve_counter returns the OTHER 'ar' account's id —
        test_every_account_posts_to_itself and
        test_trade_receivables_does_not_borrow_the_ar_key both fail (2 tests).
        The FIRST version of this fixture keyed only one of the pair, and the
        control passed: the derivation produced no auto category at all, so the
        check it was meant to defend was never reached. The collision is what
        makes the assertion bite.
      * defaulting derive_category to True makes
        test_account_alone_does_not_overwrite_a_deliberate_category fail.
      * removing the _scoped_account check makes the three scope tests pass a
        foreign/archived/other-client id straight into bank_transactions (3).
      * removing the draft-journal guard makes
        test_deriving_over_a_draft_journal_is_refused fail.
"""
import pytest

from fastapi import HTTPException

from domain.banking.account_category import category_for_account, DerivedCategory
from domain.banking.categories import CATEGORY_SET
from domain.banking.posting_map import AUTO_COUNTER, EXPLICIT_COUNTER, TRANSFER
from services.banking_service import banking_service
from services.bank_posting_service import bank_posting_service

FIRM, CLIENT = "firm-1", "client-1"


# ── a fake Supabase that models the predicates _find_account actually uses ────
class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    """Enough PostgREST to run phase2_journal_service._find_account for real.

    eq / or_ / ilike / limit / select / update. `or_` handles only the one
    expression this path builds (`client_id.eq.X,client_id.is.null`) and RAISES
    on anything else — a double that quietly matched nothing would make every
    resolution look like "no such account", which is indistinguishable from the
    mismatch these tests exist to detect.
    """

    def __init__(self, store, table):
        self.store, self.table = store, table
        self._pred, self._op, self._payload, self._limit = [], "select", None, None
        self._single = False

    def select(self, *_a, **_k):
        return self

    def update(self, payload):
        self._op, self._payload = "update", payload
        return self

    def insert(self, payload):
        self._op, self._payload = "insert", payload
        return self

    def eq(self, k, v):
        self._pred.append(lambda r, k=k, v=v: r.get(k) == v)
        return self

    def ilike(self, k, pattern):
        needle = pattern.replace("%", "").lower()
        self._pred.append(lambda r, k=k, n=needle: n in str(r.get(k) or "").lower())
        return self

    def or_(self, expr):
        if expr != f"client_id.eq.{CLIENT},client_id.is.null":
            raise AssertionError(f"the fake does not model or_({expr!r})")
        self._pred.append(lambda r: r.get("client_id") in (None, CLIENT))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def single(self):
        self._single = True
        return self

    def _matches(self):
        return [r for r in self.store.setdefault(self.table, [])
                if all(p(r) for p in self._pred)]

    def execute(self):
        rows = self._matches()
        if self._op == "update":
            for r in rows:
                r.update(self._payload)
            return _Resp(rows)
        if self._op == "insert":
            items = self._payload if isinstance(self._payload, list) else [self._payload]
            out = []
            for p in items:
                rec = dict(p)
                self.store.setdefault(self.table, []).append(rec)
                out.append(rec)
            return _Resp(out)
        if self._single:
            return _Resp(rows[0] if rows else None)
        return _Resp(rows[: self._limit] if self._limit is not None else rows)


class FakeDB:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return _Q(self.store, name)


def _account(db, id, name, type_, *, key=None, subtype=None,
             client_id=CLIENT, is_active=True, code="0000"):
    row = dict(id=id, firm_id=FIRM, client_id=client_id, account_code=code,
               account_name=name, account_type=type_, account_subtype=subtype,
               system_account_key=key, is_active=is_active)
    db.store.setdefault("chart_of_accounts", []).append(row)
    return row


def _txn(db, **kw):
    row = dict(id="t1", firm_id=FIRM, client_id=CLIENT, transaction_date="2026-04-10",
               description="NEFT", debit_paise=0, credit_paise=118000,
               match_status="unmatched", category=None, account_id=None,
               matched_entity_type=None, matched_entity_id=None, posted_journal_id=None)
    row.update(kw)
    db.store.setdefault("bank_transactions", []).append(row)
    return row


def _real_chart(db):
    """A chart carrying BOTH ways a control key and a pick can disagree.

    Receivables: two accounts, both keyed 'ar' — which is simply what migration
    092's backfill produces on a chart naming both "Accounts Receivable" and
    "Trade Receivables". _find_account resolves that with `.limit(1)` and no
    ORDER BY, so which one it returns is arbitrary; the fake returns the first
    inserted, and relying on that order is precisely the mistake under test.

    Payables: the live shape — a keyed "Accounts Payable" with no postings
    beside the "Trade Payables" everything lands in, whose key is NULL (see
    reconciliation_service._find_account_id).
    """
    return {
        "ar_keyed": _account(db, "ar_keyed", "Accounts Receivable", "Asset", key="ar", code="1100"),
        "ar_real": _account(db, "ar_real", "Trade Receivables", "Asset", key="ar", code="1101"),
        "ap_keyed": _account(db, "ap_keyed", "Accounts Payable", "Liability", key="ap", code="2100"),
        "ap_real": _account(db, "ap_real", "Trade Payables", "Liability", code="2101"),
        "gst_out": _account(db, "gst_out", "GST Output Tax", "Liability", key="gst_output", code="2200"),
        "bank": _account(db, "bank", "HDFC Current A/c", "Asset", key="bank", code="1010"),
        "cash": _account(db, "cash", "Petty Cash", "Asset", subtype="Cash", code="1001"),
        "rent": _account(db, "rent", "Rent", "Expense", code="5010"),
        "salary": _account(db, "salary", "Salaries", "Expense", code="5020"),
        "sales": _account(db, "sales", "Sales", "Revenue", code="4000"),
        "capital": _account(db, "capital", "Partner Capital", "Equity", code="3000"),
        "loan": _account(db, "loan", "Bank Loan", "Liability", code="2500"),
    }


# ── the pure derivation ───────────────────────────────────────────────────────

@pytest.mark.parametrize("row, is_credit, expected", [
    ({"system_account_key": "ar", "account_type": "Asset"}, True, "Customer Payment"),
    ({"system_account_key": "ap", "account_type": "Liability"}, False, "Vendor Payment"),
    ({"system_account_key": "gst_output", "account_type": "Liability"}, False, "GST Payment"),
    ({"system_account_key": "bank", "account_type": "Asset"}, False, "Transfer"),
    ({"account_type": "Asset", "account_name": "Petty Cash"}, False, "Transfer"),
    ({"account_type": "Asset", "account_subtype": "Bank"}, False, "Transfer"),
    ({"account_type": "Expense", "account_name": "Salaries"}, False, "Expense"),
    ({"account_type": "Equity", "account_name": "Partner Capital"}, False, "Capital"),
    ({"account_type": "Revenue", "account_name": "Sales"}, True, "Sales Receipt"),
    ({"account_type": "Income", "account_name": "Sales"}, True, "Sales Receipt"),
    ({"account_type": "Asset", "account_name": "Trade Receivables"}, True, "Other"),
    ({"account_type": "Liability", "account_name": "Bank Loan"}, True, "Other"),
])
def test_derivation_table(row, is_credit, expected):
    assert category_for_account(row, is_credit=is_credit).category == expected


def test_money_leaving_against_revenue_is_not_a_sales_receipt():
    """A debit against Sales is a refund or a return. "Sales Receipt" is in
    SETTLES_SALES_INVOICE, so the word decides whether a matched invoice gets
    marked paid — it is not merely cosmetic."""
    out = category_for_account({"account_type": "Revenue", "account_name": "Sales"},
                               is_credit=False)
    assert out.category != "Sales Receipt"
    assert out.category in CATEGORY_SET


def test_a_liability_named_bank_loan_is_not_a_transfer():
    """Migration 092 orders its bank/cash backfill last for exactly this reason.
    A Transfer builds a DIFFERENT journal shape (contra between two of the
    client's own accounts), so a false positive here is not a wrong label — it
    is a wrong entry."""
    assert category_for_account({"account_type": "Liability", "account_name": "Bank Loan"},
                                is_credit=True).category != TRANSFER
    assert category_for_account({"account_type": "Expense", "account_name": "Bank Charges"},
                                is_credit=False).category != TRANSFER


def test_every_derived_category_is_in_the_controlled_vocabulary():
    """The column has a CHECK mirroring domain.banking.categories. A derivation
    that invented a word would be refused by the database, one row at a time,
    with no way for the CA to tell why."""
    db = FakeDB()
    for acc in _real_chart(db).values():
        for is_credit in (True, False):
            d = category_for_account(acc, is_credit=is_credit)
            assert d.category in CATEGORY_SET, f"{acc['account_name']} → {d.category}"
            assert d.fallback in CATEGORY_SET


def test_the_fallback_is_always_a_category_that_honours_the_pick():
    """`fallback` exists to be safe when the control key disagrees, so it must
    never itself be a category that re-resolves the account."""
    db = FakeDB()
    for acc in _real_chart(db).values():
        for is_credit in (True, False):
            fb = category_for_account(acc, is_credit=is_credit).fallback
            assert fb in EXPLICIT_COUNTER or fb == TRANSFER, fb


def test_the_key_table_is_exactly_the_inverse_of_auto_counter():
    """Drift guard. If a fourth AUTO_COUNTER category is added and this module
    is not taught about it, picking its control account would derive a plain
    label instead — silently losing the settlement."""
    from domain.banking import account_category as ac
    assert ac._KEY_TO_AUTO_CATEGORY == {k: c for c, (k, _p) in AUTO_COUNTER.items()}


# ── THE GUARANTEE ─────────────────────────────────────────────────────────────

def test_every_account_posts_to_itself():
    """Pick any ledger in a real-shaped chart; the counter leg lands there.

    Runs the whole path: set_account derives and stores a category, then the
    REAL bank_posting_service._resolve_counter (which is what actually decides
    where the money goes) is asked where that row will post. Transfer is
    excluded because it resolves through to_bank_account_id instead, and has its
    own test below.
    """
    for name, acc in _real_chart(FakeDB()).items():
        db = FakeDB()
        chart = _real_chart(db)
        txn = _txn(db, credit_paise=118000, debit_paise=0)
        res = banking_service.set_account(db, FIRM, "t1", chart[name]["id"],
                                          derive_category=True)
        if res["category"] == TRANSFER:
            continue
        landed = bank_posting_service._resolve_counter(
            db, FIRM, db.store["bank_transactions"][0], chart[name]["id"])
        assert landed == chart[name]["id"], (
            f"picking {acc['account_name']} derived {res['category']!r}, which posts "
            f"to {landed!r} instead")


def test_trade_receivables_does_not_borrow_the_ar_key():
    """The specific defect. Trade Receivables has no system_account_key, so
    nothing may derive Customer Payment from it — that category would send the
    posting to the empty "Accounts Receivable" twin."""
    db = FakeDB()
    chart = _real_chart(db)
    _txn(db)
    res = banking_service.set_account(db, FIRM, "t1", chart["ar_real"]["id"],
                                      derive_category=True)
    assert res["category"] not in AUTO_COUNTER
    assert bank_posting_service._resolve_counter(
        db, FIRM, db.store["bank_transactions"][0], chart["ar_real"]["id"]) == "ar_real"


def test_the_keyed_control_account_does_derive_its_auto_category():
    """The other half: when the key DOES resolve back to the account picked,
    the settlement-bearing category is used. Without this the check would be
    trivially satisfiable by never deriving one at all."""
    db = FakeDB()
    chart = _real_chart(db)
    _txn(db, credit_paise=118000, debit_paise=0)
    res = banking_service.set_account(db, FIRM, "t1", chart["ar_keyed"]["id"],
                                      derive_category=True)
    assert res["category"] == "Customer Payment"
    assert bank_posting_service._resolve_counter(
        db, FIRM, db.store["bank_transactions"][0], chart["ar_keyed"]["id"]) == "ar_keyed"


def test_a_missing_control_account_falls_back_instead_of_refusing():
    """A chart with no keyed AR at all: _find_account raises, and the CA must
    still be able to code the line to the account they chose."""
    db = FakeDB()
    _account(db, "ar_real", "Trade Receivables", "Asset", code="1101")
    _txn(db)
    res = banking_service.set_account(db, FIRM, "t1", "ar_real", derive_category=True)
    assert res["category"] in CATEGORY_SET
    assert res["category"] not in AUTO_COUNTER


def test_picking_a_bank_ledger_is_a_transfer():
    db = FakeDB()
    chart = _real_chart(db)
    _txn(db, credit_paise=0, debit_paise=500000)
    res = banking_service.set_account(db, FIRM, "t1", chart["bank"]["id"],
                                      derive_category=True)
    assert res["category"] == TRANSFER
    assert db.store["bank_transactions"][0]["account_id"] == "bank"


# ── the flag is opt-in ────────────────────────────────────────────────────────

def test_account_alone_does_not_overwrite_a_deliberate_category():
    """A rule proposes a category AND an account; the screen applies both. If
    setting the account re-derived the category, the rule's finer word (Salary,
    Interest, Loan) would be thrown away every time it fired."""
    db = FakeDB()
    chart = _real_chart(db)
    _txn(db, category="Salary")
    res = banking_service.set_account(db, FIRM, "t1", chart["salary"]["id"])
    assert res["category"] == "Salary"
    assert db.store["bank_transactions"][0]["category"] == "Salary"


def test_deriving_replaces_an_earlier_derived_category():
    """Changing your mind has to change the answer. Picking Rent then Trade
    Receivables must not leave the row coded as an Expense — the category
    decides settlement, so a stale one is a wrong entry, not a stale label."""
    db = FakeDB()
    chart = _real_chart(db)
    _txn(db)
    banking_service.set_account(db, FIRM, "t1", chart["rent"]["id"], derive_category=True)
    assert db.store["bank_transactions"][0]["category"] == "Expense"
    banking_service.set_account(db, FIRM, "t1", chart["ar_keyed"]["id"], derive_category=True)
    assert db.store["bank_transactions"][0]["category"] == "Customer Payment"


# ── scope and state guards ────────────────────────────────────────────────────

def test_an_account_from_another_firm_is_refused():
    db = FakeDB()
    _real_chart(db)
    db.store["chart_of_accounts"].append(
        dict(id="theirs", firm_id="firm-2", client_id="client-9", account_code="9999",
             account_name="Their Expense", account_type="Expense", account_subtype=None,
             system_account_key=None, is_active=True))
    _txn(db)
    with pytest.raises(HTTPException) as e:
        banking_service.set_account(db, FIRM, "t1", "theirs")
    assert e.value.status_code == 422
    assert db.store["bank_transactions"][0]["account_id"] is None


def test_an_archived_account_is_refused():
    db = FakeDB()
    _account(db, "old", "Closed Expense", "Expense", is_active=False)
    _txn(db)
    with pytest.raises(HTTPException) as e:
        banking_service.set_account(db, FIRM, "t1", "old")
    assert e.value.status_code == 422


def test_another_clients_account_is_refused():
    db = FakeDB()
    _account(db, "other", "Their Rent", "Expense", client_id="client-2")
    _txn(db)
    with pytest.raises(HTTPException) as e:
        banking_service.set_account(db, FIRM, "t1", "other")
    assert e.value.status_code == 422


def test_a_firm_level_template_account_is_allowed():
    """client_id NULL is the firm-wide chart every client inherits — refusing it
    would make the picker offer accounts it then rejects."""
    db = FakeDB()
    _account(db, "shared", "Bank Charges", "Expense", client_id=None)
    _txn(db)
    res = banking_service.set_account(db, FIRM, "t1", "shared", derive_category=True)
    assert res["account_id"] == "shared"
    assert res["category"] == "Expense"


def test_a_posted_transaction_cannot_be_recoded():
    db = FakeDB()
    _real_chart(db)
    _txn(db, match_status="posted")
    with pytest.raises(HTTPException) as e:
        banking_service.set_account(db, FIRM, "t1", "rent", derive_category=True)
    assert e.value.status_code == 409


def test_deriving_over_a_draft_journal_is_refused():
    """The same guard categorize()/match()/unmatch() carry: a draft journal was
    built from the category as it stood, and settle_on_post re-reads it at
    approval time."""
    db = FakeDB()
    _real_chart(db)
    _txn(db, posted_journal_id="je-1", category="Expense")
    with pytest.raises(HTTPException) as e:
        banking_service.set_account(db, FIRM, "t1", "rent", derive_category=True)
    assert e.value.status_code == 409
    assert db.store["bank_transactions"][0]["category"] == "Expense"


def test_the_response_reports_the_category_it_stored():
    """The screen shows what came back. Reporting a category the row does not
    carry is how "Recorded · Expense" appears over a Customer Payment."""
    db = FakeDB()
    chart = _real_chart(db)
    _txn(db)
    res = banking_service.set_account(db, FIRM, "t1", chart["rent"]["id"],
                                      derive_category=True)
    assert res["category"] == db.store["bank_transactions"][0]["category"]
