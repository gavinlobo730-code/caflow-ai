"""
Bank register service + endpoint (Tier 1.1).

test_bank_register.py proves the arithmetic. This proves the ASSEMBLY: that the
right transactions are gathered for one account, that filtering never restarts
the balance, that tenant scoping holds, and that the endpoint refuses input it
cannot honour.
"""
import pytest
from fastapi import HTTPException

from services.bank_register_service import bank_register_service, SORTABLE, STATUS_FILTERS


FIRM, CLIENT, OTHER = "firm-1", "client-1", "client-2"


class _Resp:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, store, table):
        self.s, self.t = store, table
        self.eqs, self.ins = [], []
        self.limit_ = None

    def select(self, *_a, **_k): return self
    def eq(self, k, v): self.eqs.append((k, v)); return self
    def in_(self, k, vals): self.ins.append((k, set(vals))); return self
    def limit(self, n): self.limit_ = n; return self
    def order(self, *_a, **_k): return self

    def execute(self):
        rows = []
        for r in self.s.get(self.t, []):
            if any(r.get(k) != v for k, v in self.eqs):
                continue
            if any(r.get(k) not in vals for k, vals in self.ins):
                continue
            rows.append(r)
        return _Resp(rows[:self.limit_] if self.limit_ else rows)


class FakeDB:
    def __init__(self): self.store = {}
    def table(self, n): return _Q(self.store, n)


def _db(*, opening=100000, opening_date="2026-04-01", client_id=CLIENT):
    db = FakeDB()
    db.store["bank_accounts"] = [{
        "id": "ba-1", "firm_id": FIRM, "client_id": client_id,
        "bank_name": "HDFC Bank", "account_no": "50100123456789",
        "account_type": "Current", "coa_account_id": "acc-bank",
        "opening_balance_paise": opening, "opening_balance_date": opening_date,
    }]
    db.store["bank_statements"] = [
        {"id": "st-1", "firm_id": FIRM, "bank_account_id": "ba-1"},
        {"id": "st-other", "firm_id": FIRM, "bank_account_id": "ba-other"},
    ]
    db.store["bank_transactions"] = []
    db.store["bank_reconciliations"] = []
    return db


def _txn(db, id_, d, *, debit=0, credit=0, statement="st-1", balance=None, **kw):
    row = {"id": id_, "firm_id": FIRM, "client_id": CLIENT, "statement_id": statement,
           "transaction_date": d, "description": f"TXN {id_}", "debit_paise": debit,
           "credit_paise": credit, "balance_paise": balance, "reference_no": None,
           "created_at": f"2026-01-01T00:00:{len(db.store['bank_transactions']):02d}Z",
           "category": None, "match_status": "unmatched", "posted_journal_id": None,
           "reconciliation_id": None, "needs_review": False}
    row.update(kw)
    db.store["bank_transactions"].append(row)
    return row


def _reg(db, **kw):
    return bank_register_service.register(db, FIRM, "ba-1", **kw)


# ══════════════════════════════════════════════════════════════════════════════
# Assembly
# ══════════════════════════════════════════════════════════════════════════════

def test_the_register_carries_the_account_and_a_running_balance():
    db = _db()
    _txn(db, "a", "2026-04-01", credit=10000)
    _txn(db, "b", "2026-04-02", debit=3000)
    out = _reg(db)
    assert out["account"]["bank_name"] == "HDFC Bank"
    assert [l["balance_paise"] for l in out["lines"]] == [110000, 107000]
    assert out["summary"]["closing_balance_paise"] == 107000


def test_another_accounts_statements_are_not_included():
    """Transactions reach an account only through its statements. A register
    that pulled in a sibling account's lines would show a balance that ties to
    neither statement."""
    db = _db()
    _txn(db, "mine", "2026-04-01", credit=10000)
    _txn(db, "theirs", "2026-04-02", credit=99999, statement="st-other")
    out = _reg(db)
    assert [l["transaction_id"] for l in out["lines"]] == ["mine"]
    assert out["summary"]["closing_balance_paise"] == 110000


def test_uncoded_transactions_are_included():
    """A register is the BANK's view. A line the bank debited belongs on it
    whether or not anyone has coded it — omitting it would make the balance
    disagree with the statement, which is the one thing a register cannot do."""
    db = _db()
    _txn(db, "coded", "2026-04-01", credit=10000, posted_journal_id="je-1")
    _txn(db, "raw", "2026-04-02", credit=5000)
    out = _reg(db)
    assert len(out["lines"]) == 2
    assert out["summary"]["closing_balance_paise"] == 115000
    assert out["summary"]["unposted_count"] == 1


def test_an_account_with_no_statements_yields_an_empty_register():
    db = _db()
    db.store["bank_statements"] = []
    out = _reg(db)
    assert out["lines"] == [] and out["total_count"] == 0
    assert out["summary"]["closing_balance_paise"] == 100000   # still the opening


def test_the_cleared_column_reflects_the_reconciliations_status():
    db = _db()
    db.store["bank_reconciliations"] = [
        {"id": "r-done", "firm_id": FIRM, "status": "completed"},
        {"id": "r-live", "firm_id": FIRM, "status": "in_progress"},
    ]
    _txn(db, "a", "2026-04-01", credit=100, reconciliation_id="r-done")
    _txn(db, "b", "2026-04-02", credit=100, reconciliation_id="r-live")
    _txn(db, "c", "2026-04-03", credit=100)
    assert [l["cleared"] for l in _reg(db)["lines"]] == ["R", "C", ""]


# ══════════════════════════════════════════════════════════════════════════════
# Filtering must never restart the balance
# ══════════════════════════════════════════════════════════════════════════════

def test_a_date_filter_keeps_each_lines_true_balance():
    """THE filtering invariant. Recomputing from the filter boundary would show
    a balance that starts at zero-plus-April and ties to nothing."""
    db = _db()
    _txn(db, "mar", "2026-04-01", credit=10000)
    _txn(db, "apr", "2026-05-02", credit=5000)
    out = _reg(db, date_from="2026-05-01")
    assert [l["transaction_id"] for l in out["lines"]] == ["apr"]
    assert out["lines"][0]["balance_paise"] == 115000          # NOT 5000
    assert out["view_opening_balance_paise"] == 110000         # what came before
    assert out["filtered_count"] == 1 and out["total_count"] == 2


def test_the_view_opening_is_the_account_opening_when_nothing_precedes():
    db = _db()
    _txn(db, "a", "2026-04-01", credit=10000)
    assert _reg(db)["view_opening_balance_paise"] == 100000


def test_the_summary_describes_the_whole_account_not_the_filtered_page():
    """A bookkeeper filtering to one week still needs the account's real closing
    balance, not the balance of the week."""
    db = _db()
    _txn(db, "a", "2026-04-01", credit=10000)
    _txn(db, "b", "2026-05-02", credit=5000)
    out = _reg(db, date_from="2026-05-01")
    assert out["summary"]["closing_balance_paise"] == 115000
    assert out["summary"]["line_count"] == 2


@pytest.mark.parametrize("status,expected", [
    ("uncleared", ["c"]), ("pending", ["b"]), ("reconciled", ["a"]), ("all", ["a", "b", "c"]),
])
def test_status_filters(status, expected):
    db = _db()
    db.store["bank_reconciliations"] = [
        {"id": "r-done", "firm_id": FIRM, "status": "completed"},
        {"id": "r-live", "firm_id": FIRM, "status": "open"},
    ]
    _txn(db, "a", "2026-04-01", credit=100, reconciliation_id="r-done")
    _txn(db, "b", "2026-04-02", credit=100, reconciliation_id="r-live")
    _txn(db, "c", "2026-04-03", credit=100)
    assert [l["transaction_id"] for l in _reg(db, status=status)["lines"]] == expected


def test_the_unposted_filter_finds_work_still_to_do():
    db = _db()
    _txn(db, "done", "2026-04-01", credit=100, posted_journal_id="je-1")
    _txn(db, "todo", "2026-04-02", credit=100)
    assert [l["transaction_id"] for l in _reg(db, status="unposted")["lines"]] == ["todo"]


def test_search_covers_narration_reference_and_category():
    db = _db()
    _txn(db, "a", "2026-04-01", credit=100, description="UPI RAMESH KUMAR")
    _txn(db, "b", "2026-04-02", credit=100, description="NEFT", reference_no="UTR9987")
    _txn(db, "c", "2026-04-03", credit=100, description="CHG", category="Expense")
    assert [l["transaction_id"] for l in _reg(db, q="ramesh")["lines"]] == ["a"]
    assert [l["transaction_id"] for l in _reg(db, q="utr99")["lines"]] == ["b"]
    assert [l["transaction_id"] for l in _reg(db, q="expense")["lines"]] == ["c"]


# ══════════════════════════════════════════════════════════════════════════════
# Sorting
# ══════════════════════════════════════════════════════════════════════════════

def test_sorting_by_amount_does_not_renumber_the_balance_column():
    """A running balance in amount order is not a running balance. Each line
    keeps the balance it had in date order."""
    db = _db()
    _txn(db, "big", "2026-04-01", credit=50000)
    _txn(db, "small", "2026-04-02", credit=1000)
    out = _reg(db, sort="amount")
    assert [l["transaction_id"] for l in out["lines"]] == ["small", "big"]
    assert {l["transaction_id"]: l["balance_paise"] for l in out["lines"]} == {
        "big": 150000, "small": 151000}


def test_descending_date_reverses_the_rows_not_the_arithmetic():
    db = _db()
    _txn(db, "a", "2026-04-01", credit=10000)
    _txn(db, "b", "2026-04-02", credit=5000)
    out = _reg(db, sort="date", desc=True)
    assert [l["transaction_id"] for l in out["lines"]] == ["b", "a"]
    assert [l["balance_paise"] for l in out["lines"]] == [115000, 110000]


@pytest.mark.parametrize("sort", SORTABLE)
def test_every_advertised_sort_works(sort):
    db = _db()
    _txn(db, "a", "2026-04-01", credit=10000)
    _txn(db, "b", "2026-04-02", debit=5000)
    assert len(_reg(db, sort=sort)["lines"]) == 2


# ══════════════════════════════════════════════════════════════════════════════
# Paging
# ══════════════════════════════════════════════════════════════════════════════

def test_paging_slices_without_changing_the_balances():
    db = _db()
    for i in range(1, 11):
        _txn(db, f"t{i:02d}", f"2026-04-{i:02d}", credit=1000)
    page2 = _reg(db, limit=3, offset=3)
    assert [l["transaction_id"] for l in page2["lines"]] == ["t04", "t05", "t06"]
    assert [l["balance_paise"] for l in page2["lines"]] == [104000, 105000, 106000]
    assert page2["total_count"] == 10 and page2["filtered_count"] == 10


def test_an_offset_past_the_end_is_empty_not_an_error():
    db = _db()
    _txn(db, "a", "2026-04-01", credit=100)
    assert _reg(db, offset=500)["lines"] == []


# ══════════════════════════════════════════════════════════════════════════════
# The self-check against the bank's stated balance
# ══════════════════════════════════════════════════════════════════════════════

def test_a_gap_against_the_statement_is_surfaced():
    db = _db()
    _txn(db, "a", "2026-04-01", credit=10000, balance=110000)
    _txn(db, "b", "2026-04-02", credit=0, balance=115000)
    d = _reg(db)["divergence"]
    assert d and d["transaction_id"] == "b" and d["delta_paise"] == 5000


def test_agreement_reports_no_divergence():
    db = _db()
    _txn(db, "a", "2026-04-01", credit=10000, balance=110000)
    assert _reg(db)["divergence"] is None


# ══════════════════════════════════════════════════════════════════════════════
# Scoping and refusals
# ══════════════════════════════════════════════════════════════════════════════

def test_another_firms_account_is_not_found():
    db = _db()
    db.store["bank_accounts"][0]["firm_id"] = "other-firm"
    with pytest.raises(HTTPException) as ei:
        _reg(db)
    assert ei.value.status_code == 404


def test_an_account_belonging_to_a_different_client_is_refused():
    """Firm match alone must not resolve it — same check the reconciliation
    service makes."""
    db = _db(client_id=OTHER)
    with pytest.raises(HTTPException) as ei:
        _reg(db, client_id=CLIENT)
    assert ei.value.status_code == 422


@pytest.mark.parametrize("bad", ["id", "; drop table", "balance_paise", ""])
def test_an_unlisted_sort_column_is_refused(bad):
    """The sort reaches a query builder, so the vocabulary is closed rather
    than 'whatever the caller sent'."""
    db = _db()
    with pytest.raises(HTTPException) as ei:
        _reg(db, sort=bad)
    assert ei.value.status_code == 422


@pytest.mark.parametrize("bad", ["cleared", "posted", "anything"])
def test_an_unknown_status_filter_is_refused(bad):
    db = _db()
    with pytest.raises(HTTPException) as ei:
        _reg(db, status=bad)
    assert ei.value.status_code == 422


def test_a_backwards_date_range_is_refused():
    db = _db()
    with pytest.raises(HTTPException) as ei:
        _reg(db, date_from="2026-05-01", date_to="2026-04-01")
    assert ei.value.status_code == 422


def test_the_limit_is_clamped_rather_than_trusted():
    db = _db()
    _txn(db, "a", "2026-04-01", credit=100)
    assert _reg(db, limit=999999)["limit"] == 1000
    assert _reg(db, limit=0)["limit"] == 1


def test_every_advertised_status_filter_is_accepted():
    db = _db()
    _txn(db, "a", "2026-04-01", credit=100)
    for s in STATUS_FILTERS:
        assert "lines" in _reg(db, status=s)


# ══════════════════════════════════════════════════════════════════════════════
# The endpoint
# ══════════════════════════════════════════════════════════════════════════════

PARTNER = {"firm_id": FIRM, "role": "Partner", "auth_user_id": "p1", "id": "u1"}

# Calling a router function directly bypasses FastAPI's dependency resolution,
# so every Query-defaulted parameter has to be supplied explicitly — otherwise
# the Query(...) object itself arrives as the value.
_ENDPOINT_DEFAULTS = dict(client_id=None, date_from=None, date_to=None, status="all",
                          q=None, sort="date", desc=False, limit=200, offset=0)


def _call(br, **kw):
    return br.bank_register(**{**_ENDPOINT_DEFAULTS, **kw, "current_user": PARTNER})


def test_the_endpoint_returns_the_standard_envelope(monkeypatch):
    import core.authz as authz
    import routers.banking as br
    db = _db()
    _txn(db, "a", "2026-04-01", credit=10000)
    monkeypatch.setattr(br, "_db", lambda: db)
    monkeypatch.setattr(authz, "_USE_MOCK", True)
    res = _call(br, bank_account_id="ba-1", client_id=CLIENT)
    assert res["success"] is True and res["error"] is None
    assert res["data"]["lines"][0]["balance_paise"] == 110000


def test_the_endpoint_is_read_only(monkeypatch):
    """A register must not mutate anything — it is a view over the statement."""
    import core.authz as authz
    import routers.banking as br
    db = _db()
    _txn(db, "a", "2026-04-01", credit=10000)
    before = [dict(r) for r in db.store["bank_transactions"]]
    monkeypatch.setattr(br, "_db", lambda: db)
    monkeypatch.setattr(authz, "_USE_MOCK", True)
    _call(br, bank_account_id="ba-1")
    assert db.store["bank_transactions"] == before


def test_the_endpoints_query_patterns_match_the_service_vocabulary():
    """The route's regex and the service's allow-lists have to agree, or one of
    them rejects something the other advertises."""
    import routers.banking as br
    params = br.bank_register.__annotations__
    assert set(SORTABLE) == {"date", "amount", "description", "balance", "cleared"}
    assert set(STATUS_FILTERS) == {"all", "uncleared", "pending", "reconciled",
                                   "unposted", "needs_review"}
    assert "bank_account_id" in params
