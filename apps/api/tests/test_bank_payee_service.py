"""
Payee (Tier 1.3) and learn-from-history (Tier 1.4) — service and queue wiring.

test_bank_history.py proves the tally. This proves the ASSEMBLY: that only
posted decisions teach, that a transaction is never its own evidence, that a
human's answer is never overwritten, and that the whole queue costs a bounded
number of queries rather than one per row.
"""
import pytest
from fastapi import HTTPException

from models.banking import BankPayeeIn
from services.bank_payee_service import bank_payee_service
from services.bank_matching_service import bank_matching_service
import services.bank_matching_service as bms


FIRM, CLIENT = "firm-1", "client-1"


class _Resp:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, store, table, counter):
        self.s, self.t, self.c = store, table, counter
        self.op, self.payload = "select", None
        self.eqs, self.ins = [], []
        self.limit_ = None

    def select(self, *_a, **_k): self.op = "select"; return self
    def update(self, p): self.op, self.payload = "update", p; return self
    def insert(self, p): self.op, self.payload = "insert", p; return self
    def eq(self, k, v): self.eqs.append((k, v)); return self
    def in_(self, k, vals): self.ins.append((k, set(vals))); return self
    def or_(self, *_a, **_k): return self
    def is_(self, k, _v): self.eqs.append((k, None)); return self
    def limit(self, n): self.limit_ = n; return self
    def order(self, *_a, **_k): return self
    def single(self): self.limit_ = 1; return self

    def execute(self):
        self.c[self.t] = self.c.get(self.t, 0) + 1
        rows = self.s.setdefault(self.t, [])
        if self.op == "insert":
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            for p in items:
                rows.append(dict(p))
            return _Resp(items)
        m = [r for r in rows
             if not any(r.get(k) != v for k, v in self.eqs)
             and not any(r.get(k) not in vals for k, vals in self.ins)]
        if self.op == "update":
            for r in m:
                r.update(self.payload)
            return _Resp(m)
        return _Resp(m[:self.limit_] if self.limit_ else m)


class FakeDB:
    def __init__(self):
        self.store = {}
        self.queries = {}          # table -> how many times it was queried
    def table(self, n): return _Q(self.store, n, self.queries)


def _db():
    db = FakeDB()
    db.store["bank_transactions"] = []
    db.store["customers"] = [
        {"id": "cust-1", "firm_id": FIRM, "client_id": CLIENT, "customer_name": "Acme Pvt Ltd"}]
    db.store["vendors"] = [
        {"id": "vend-1", "firm_id": FIRM, "client_id": CLIENT, "vendor_name": "Ramesh Kumar"}]
    db.store["bank_matching_rules"] = []
    return db


def _txn(db, id_="t1", *, description="NEFT", posted=False, account_id=None,
         category=None, payee_id=None, payee_name=None, date="2026-04-01", **kw):
    row = {"id": id_, "firm_id": FIRM, "client_id": CLIENT, "transaction_date": date,
           "description": description, "debit_paise": 100000, "credit_paise": 0,
           "account_id": account_id, "category": category, "payee_id": payee_id,
           "payee_name": payee_name, "payee_type": "vendor" if payee_id else None,
           "posted_journal_id": "je-1" if posted else None,
           "posted_at": date if posted else None,
           "match_status": "unmatched", "matched_entity_id": None, "needs_review": False}
    row.update(kw)
    db.store["bank_transactions"].append(row)
    return row


@pytest.fixture(autouse=True)
def _silence(monkeypatch):
    monkeypatch.setattr(bms.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr("services.audit_service.log_event", lambda *a, **k: None, raising=False)
    yield


# ══════════════════════════════════════════════════════════════════════════════
# 1.3 — setting a payee
# ══════════════════════════════════════════════════════════════════════════════

def test_a_plain_payee_needs_no_link():
    """The landlord and the electricity board are neither customers nor vendors,
    and inventing records for them would be worse than the problem."""
    db = _db(); _txn(db)
    out = bank_payee_service.set_payee(db, FIRM, "t1", payee_name="City Power Ltd")
    assert out["payee_name"] == "City Power Ltd"
    assert out["payee_type"] == "other" and out["payee_id"] is None


def test_a_linked_vendor_is_stored_with_its_type():
    db = _db(); _txn(db)
    out = bank_payee_service.set_payee(db, FIRM, "t1", payee_name="Ramesh Kumar",
                                       payee_type="vendor", payee_id="vend-1")
    assert out["payee_type"] == "vendor" and out["payee_id"] == "vend-1"


def test_clearing_the_name_clears_the_link_too():
    """A wrong association must not survive as a dangling id with no name."""
    db = _db(); _txn(db)
    bank_payee_service.set_payee(db, FIRM, "t1", payee_name="Ramesh Kumar",
                                 payee_type="vendor", payee_id="vend-1")
    out = bank_payee_service.set_payee(db, FIRM, "t1", payee_name="")
    assert out["payee_name"] is None and out["payee_id"] is None and out["payee_type"] is None


def test_a_link_with_type_other_is_refused():
    db = _db(); _txn(db)
    with pytest.raises(HTTPException) as ei:
        bank_payee_service.set_payee(db, FIRM, "t1", payee_name="X",
                                     payee_type="other", payee_id="vend-1")
    assert ei.value.status_code == 422


def test_a_customer_type_with_no_id_is_refused():
    db = _db(); _txn(db)
    with pytest.raises(HTTPException) as ei:
        bank_payee_service.set_payee(db, FIRM, "t1", payee_name="X", payee_type="customer")
    assert ei.value.status_code == 422


def test_another_firms_party_cannot_be_linked():
    """payee_id carries no foreign key (the reference is polymorphic), so this
    check is the only thing between a typo and a cross-tenant pointer."""
    db = _db(); _txn(db)
    db.store["vendors"][0]["firm_id"] = "other-firm"
    with pytest.raises(HTTPException) as ei:
        bank_payee_service.set_payee(db, FIRM, "t1", payee_name="R",
                                     payee_type="vendor", payee_id="vend-1")
    assert ei.value.status_code == 422


def test_another_clients_party_cannot_be_linked():
    db = _db(); _txn(db)
    db.store["vendors"][0]["client_id"] = "client-2"
    with pytest.raises(HTTPException) as ei:
        bank_payee_service.set_payee(db, FIRM, "t1", payee_name="R",
                                     payee_type="vendor", payee_id="vend-1")
    assert ei.value.status_code == 422


def test_an_unknown_payee_type_is_refused():
    db = _db(); _txn(db)
    with pytest.raises(HTTPException):
        bank_payee_service.set_payee(db, FIRM, "t1", payee_name="X", payee_type="supplier")


def test_another_firms_transaction_is_not_found():
    db = _db(); _txn(db, firm_id="other-firm")
    with pytest.raises(HTTPException) as ei:
        bank_payee_service.set_payee(db, FIRM, "t1", payee_name="X")
    assert ei.value.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 1.3 — auto-fill
# ══════════════════════════════════════════════════════════════════════════════

def test_a_known_vendor_in_the_narration_is_offered_as_a_link():
    db = _db()
    t = _txn(db, description="UPI/412345678901/RAMESH KUMAR/HDFC")
    s = bank_payee_service.suggest_payee(db, FIRM, CLIENT, t)
    assert s["payee_id"] == "vend-1" and s["payee_type"] == "vendor"
    assert s["source"] == "matched_party"


def test_an_unknown_counterparty_is_still_offered_as_a_name():
    """A name is more useful than nothing, even without a party to link."""
    db = _db()
    t = _txn(db, description="UPI/999/CITY POWER LTD/SBIN")
    s = bank_payee_service.suggest_payee(db, FIRM, CLIENT, t)
    assert s["payee_type"] == "other" and s["payee_id"] is None
    assert "CITY POWER" in s["payee_name"]


def test_a_payee_a_human_already_named_is_not_second_guessed():
    db = _db()
    t = _txn(db, description="UPI/412345/RAMESH KUMAR", payee_name="Someone Else")
    assert bank_payee_service.suggest_payee(db, FIRM, CLIENT, t) is None


def test_an_unparseable_narration_yields_no_suggestion():
    db = _db()
    t = _txn(db, description="NEFT DR")
    assert bank_payee_service.suggest_payee(db, FIRM, CLIENT, t) is None


# ══════════════════════════════════════════════════════════════════════════════
# 1.4 — what history teaches
# ══════════════════════════════════════════════════════════════════════════════

def test_only_posted_decisions_teach():
    """A draft is a proposal. Learning from unposted rows would let one mistaken
    suggestion, accepted once, become the evidence for suggesting itself."""
    db = _db()
    _txn(db, "old1", description="UPI/1/ACME LTD", posted=True, account_id="acc-rent", category="Expense")
    _txn(db, "old2", description="UPI/2/ACME LTD", posted=False, account_id="acc-wrong", category="Expense")
    idx = bank_payee_service.history_index(db, FIRM, CLIENT)
    new = {"description": "UPI/3/ACME LTD", "payee_id": None, "payee_name": None}
    s = bank_payee_service.suggest_for(new, idx)
    assert s.account_id == "acc-rent" and s.total_seen == 1


def test_a_transaction_is_never_its_own_evidence():
    """Without the exclusion, a posted row in the queue would suggest itself
    back at 100% and look like corroboration."""
    db = _db()
    t = _txn(db, "t1", description="UPI/1/ACME LTD", posted=True,
             account_id="acc-rent", category="Expense")
    idx = bank_payee_service.history_index(db, FIRM, CLIENT)
    assert bank_payee_service.suggest_for(t, idx) is None


def test_the_majority_coding_is_suggested_with_its_evidence():
    db = _db()
    for i, acc in enumerate(["acc-rent", "acc-rent", "acc-repairs"]):
        _txn(db, f"old{i}", description=f"UPI/{i}/ACME LTD", posted=True,
             account_id=acc, category="Expense", date=f"2026-0{i + 1}-01")
    idx = bank_payee_service.history_index(db, FIRM, CLIENT)
    out = bank_payee_service.as_dict(bank_payee_service.suggest_for(
        {"description": "UPI/9/ACME LTD", "payee_id": None, "payee_name": None}, idx))
    assert out["account_id"] == "acc-rent"
    assert out["times_seen"] == 2 and out["total_seen"] == 3
    assert out["summary"] == "Coded this way 2 of the last 3 times"
    assert out["alternatives"][0]["account_id"] == "acc-repairs"
    assert out["is_unanimous"] is False


def test_a_linked_party_matches_history_across_different_narrations():
    """THE reason payee_id is the strongest key: the narration text can be
    completely different and it still learns."""
    db = _db()
    _txn(db, "old", description="NEFT/AAA/SOMETHING", posted=True, payee_id="vend-1",
         account_id="acc-rent", category="Expense")
    idx = bank_payee_service.history_index(db, FIRM, CLIENT)
    s = bank_payee_service.suggest_for(
        {"description": "IMPS/ZZZ/TOTALLY DIFFERENT", "payee_id": "vend-1"}, idx)
    assert s is not None and s.account_id == "acc-rent"
    assert bank_payee_service.as_dict(s)["matched_on"] == "linked party"


def test_no_history_yields_no_suggestion():
    db = _db()
    idx = bank_payee_service.history_index(db, FIRM, CLIENT)
    assert bank_payee_service.suggest_for(
        {"description": "UPI/1/BRAND NEW PAYEE"}, idx) is None


def test_another_clients_history_does_not_leak():
    db = _db()
    _txn(db, "theirs", description="UPI/1/ACME LTD", posted=True,
         account_id="acc-theirs", category="Expense", client_id="client-2")
    idx = bank_payee_service.history_index(db, FIRM, CLIENT)
    assert bank_payee_service.suggest_for({"description": "UPI/9/ACME LTD"}, idx) is None


# ══════════════════════════════════════════════════════════════════════════════
# The queue
# ══════════════════════════════════════════════════════════════════════════════

def test_the_queue_carries_the_payee_and_the_history():
    db = _db()
    _txn(db, "old", description="UPI/1/ACME LTD", posted=True,
         account_id="acc-rent", category="Expense")
    _txn(db, "new", description="UPI/2/ACME LTD")
    row = next(r for r in bank_matching_service.queue(db, FIRM, CLIENT, "all")
               if r["id"] == "new")
    assert row["history"]["account_id"] == "acc-rent"
    assert row["history"]["summary"] == "Coded this way once before"
    assert row["suggested_payee"]["payee_name"]


def test_the_queue_costs_a_bounded_number_of_queries():
    """One history read and one party read for the whole client — not one per
    row. A hundred transactions must not mean a hundred round trips."""
    db = _db()
    for i in range(25):
        _txn(db, f"n{i}", description=f"UPI/{i}/ACME LTD")
    db.queries.clear()
    bank_matching_service.queue(db, FIRM, CLIENT, "all")
    assert db.queries.get("bank_transactions", 0) <= 3
    assert db.queries.get("customers", 0) <= 2
    assert db.queries.get("vendors", 0) <= 2


def test_the_queue_still_works_with_no_history_at_all():
    db = _db(); _txn(db, "new", description="UPI/1/NOBODY")
    row = bank_matching_service.queue(db, FIRM, CLIENT, "all")[0]
    assert row["history"] is None


# ══════════════════════════════════════════════════════════════════════════════
# Request validation and the endpoint
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("bad", ["supplier", "Customer ", "party"])
def test_the_model_closes_the_payee_type_vocabulary(bad):
    if bad.strip().lower() in ("customer", "vendor", "other"):
        assert BankPayeeIn(payee_type=bad).payee_type == bad.strip().lower()
    else:
        with pytest.raises(ValueError):
            BankPayeeIn(payee_type=bad)


def test_the_model_treats_a_blank_type_as_absent():
    assert BankPayeeIn(payee_type="   ").payee_type is None


PARTNER = {"firm_id": FIRM, "role": "Partner", "auth_user_id": "p1", "id": "u1"}


def test_the_endpoint_sets_a_payee(monkeypatch):
    import core.authz as authz
    import routers.banking as br
    db = _db(); _txn(db)
    monkeypatch.setattr(br, "_db", lambda: db)
    monkeypatch.setattr(authz, "_USE_MOCK", True)
    res = br.set_transaction_payee("t1", BankPayeeIn(
        payee_name="Ramesh Kumar", payee_type="vendor", payee_id="vend-1"),
        current_user=PARTNER)
    assert res["success"] is True
    assert db.store["bank_transactions"][0]["payee_id"] == "vend-1"
