"""
Transfer auto-detection (Tier 1.5) — pairing, and the double-count guard.

The guard is the part that matters. `build_transfer_lines` writes the COMPLETE
double entry, so a detected pair whose sides both post double-counts the cash —
the exact overstatement transfer detection exists to prevent, just arrived at
more tidily. Detection without that guard would be worse than nothing, because
it would look like the problem had been solved.
"""
import pytest
from fastapi import HTTPException

from domain.banking.transfers import detect, describe, DEFAULT_WINDOW_DAYS
import services.bank_posting_service as bps
from services.bank_posting_service import bank_posting_service
from services.bank_transfer_service import bank_transfer_service


FIRM, CLIENT = "firm-1", "client-1"
ACC_A, ACC_B = "ba-hdfc", "ba-icici"


def _t(id_, date, *, debit=0, credit=0, account=ACC_A, **kw):
    row = {"id": id_, "firm_id": FIRM, "client_id": CLIENT, "transaction_date": date,
           "description": f"TXN {id_}", "debit_paise": debit, "credit_paise": credit,
           "bank_account_id": account, "statement_id": f"st-{account}",
           "match_status": "unmatched", "category": None, "posted_journal_id": None,
           "posted_at": None, "matched_entity_id": None, "transfer_pair_id": None,
           "transfer_is_primary": None}
    row.update(kw)
    return row


# ══════════════════════════════════════════════════════════════════════════════
# Detection
# ══════════════════════════════════════════════════════════════════════════════

def test_an_obvious_transfer_is_found():
    pairs = detect([_t("out", "2026-04-01", debit=50000000, account=ACC_A),
                    _t("in", "2026-04-01", credit=50000000, account=ACC_B)])
    assert len(pairs) == 1
    p = pairs[0]
    assert p.primary_id == "out" and p.counterpart_id == "in"
    assert p.amount_paise == 50000000 and p.day_gap == 0
    assert p.is_unambiguous and p.confidence == "high"


def test_the_outflow_is_always_the_primary():
    """A transfer is naturally described from the account the money left, and
    the primary is the side that will carry the journal."""
    pairs = detect([_t("in", "2026-04-01", credit=100, account=ACC_B),
                    _t("out", "2026-04-01", debit=100, account=ACC_A)])
    assert pairs[0].primary_id == "out"


def test_a_settlement_delay_still_pairs():
    pairs = detect([_t("out", "2026-04-01", debit=100, account=ACC_A),
                    _t("in", "2026-04-03", credit=100, account=ACC_B)])
    assert len(pairs) == 1 and pairs[0].day_gap == 2
    assert pairs[0].confidence == "medium"      # unambiguous but not same-day


def test_beyond_the_window_is_a_coincidence_not_a_transfer():
    pairs = detect([_t("out", "2026-04-01", debit=100, account=ACC_A),
                    _t("in", "2026-04-20", credit=100, account=ACC_B)])
    assert pairs == []


def test_amounts_must_match_to_the_paise():
    """A transfer that arrives short is a transfer PLUS a bank charge — two
    facts. Pairing them as one would bury the charge."""
    assert detect([_t("out", "2026-04-01", debit=50000000, account=ACC_A),
                   _t("in", "2026-04-01", credit=49999999, account=ACC_B)]) == []


def test_two_outflows_are_not_a_transfer():
    assert detect([_t("a", "2026-04-01", debit=100, account=ACC_A),
                   _t("b", "2026-04-01", debit=100, account=ACC_B)]) == []


def test_the_same_account_on_both_sides_is_not_a_movement():
    assert detect([_t("out", "2026-04-01", debit=100, account=ACC_A),
                   _t("in", "2026-04-01", credit=100, account=ACC_A)]) == []


def test_a_line_with_no_known_account_cannot_pair():
    """Without knowing which account each side is on, 'different accounts'
    cannot be checked — so it must not pair rather than assume."""
    assert detect([_t("out", "2026-04-01", debit=100, account=None),
                   _t("in", "2026-04-01", credit=100, account=ACC_B)]) == []


@pytest.mark.parametrize("field,value", [
    ("posted_journal_id", "je-1"), ("match_status", "posted"),
    ("match_status", "ignored"), ("transfer_pair_id", "other"),
    ("matched_entity_id", "inv-1"),
])
def test_a_line_that_is_already_spoken_for_does_not_pair(field, value):
    assert detect([_t("out", "2026-04-01", debit=100, account=ACC_A, **{field: value}),
                   _t("in", "2026-04-01", credit=100, account=ACC_B)]) == []


# ── each line in at most one pair ────────────────────────────────────────────

def test_a_line_is_never_used_in_two_pairs():
    """One outflow, two possible inflows. Using the outflow twice would invent
    a movement that never happened."""
    pairs = detect([_t("out", "2026-04-01", debit=100, account=ACC_A),
                    _t("in1", "2026-04-01", credit=100, account=ACC_B),
                    _t("in2", "2026-04-01", credit=100, account=ACC_B)])
    assert len(pairs) == 1
    used = {pairs[0].primary_id, pairs[0].counterpart_id}
    assert len(used) == 2


def test_ambiguity_is_reported_rather_than_hidden():
    """Two candidates for one side is a real ambiguity. Picking silently would
    be worse than picking none — the CA is told there was a choice."""
    pairs = detect([_t("out", "2026-04-01", debit=100, account=ACC_A),
                    _t("in1", "2026-04-01", credit=100, account=ACC_B),
                    _t("in2", "2026-04-01", credit=100, account=ACC_B)])
    p = pairs[0]
    assert p.counterpart_alternatives == 0      # the chosen inflow had one option
    assert p.primary_alternatives == 1          # the outflow had two
    assert p.is_unambiguous is False and p.confidence == "low"
    assert "check which two belong together" in describe(p)


def test_pairing_is_deterministic_regardless_of_input_order():
    """The same data must always produce the same pairing — otherwise two page
    loads disagree about which lines belong together."""
    rows = [_t("out1", "2026-04-01", debit=100, account=ACC_A),
            _t("out2", "2026-04-02", debit=100, account=ACC_A),
            _t("in1", "2026-04-01", credit=100, account=ACC_B),
            _t("in2", "2026-04-02", credit=100, account=ACC_B)]
    first = [(p.primary_id, p.counterpart_id) for p in detect(rows)]
    for order in ([3, 2, 1, 0], [1, 3, 0, 2], [2, 0, 3, 1]):
        shuffled = [rows[i] for i in order]
        assert [(p.primary_id, p.counterpart_id) for p in detect(shuffled)] == first


def test_the_closest_dates_pair_first():
    pairs = detect([_t("out", "2026-04-01", debit=100, account=ACC_A),
                    _t("far", "2026-04-04", credit=100, account=ACC_B),
                    _t("near", "2026-04-01", credit=100, account=ACC_B)])
    assert pairs[0].counterpart_id == "near"


def test_several_independent_transfers_all_pair():
    rows = []
    for i in range(1, 4):
        rows.append(_t(f"out{i}", f"2026-04-0{i}", debit=i * 1000, account=ACC_A))
        rows.append(_t(f"in{i}", f"2026-04-0{i}", credit=i * 1000, account=ACC_B))
    pairs = detect(rows)
    assert len(pairs) == 3
    assert {p.primary_id for p in pairs} == {"out1", "out2", "out3"}


def test_the_window_is_configurable():
    rows = [_t("out", "2026-04-01", debit=100, account=ACC_A),
            _t("in", "2026-04-08", credit=100, account=ACC_B)]
    assert detect(rows) == []
    assert len(detect(rows, window_days=10)) == 1


def test_the_default_window_is_a_few_days_not_weeks():
    assert 1 <= DEFAULT_WINDOW_DAYS <= 7


# ══════════════════════════════════════════════════════════════════════════════
# THE double-count guard
# ══════════════════════════════════════════════════════════════════════════════

class _Resp:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, store, table):
        self.s, self.t = store, table
        self.op, self.payload = "select", None
        self.eqs = []
        self.limit_, self.single_ = None, False

    def select(self, *_a, **_k): self.op = "select"; return self
    def update(self, p): self.op, self.payload = "update", p; return self
    def insert(self, p): self.op, self.payload = "insert", p; return self
    def eq(self, k, v): self.eqs.append((k, v)); return self
    def in_(self, *_a, **_k): return self
    def or_(self, *_a, **_k): return self
    def is_(self, k, _v): self.eqs.append((k, None)); return self
    def limit(self, n): self.limit_ = n; return self
    def order(self, *_a, **_k): return self
    def single(self): self.single_ = True; return self
    def maybe_single(self): self.single_ = True; return self

    def execute(self):
        rows = self.s.setdefault(self.t, [])
        if self.op == "insert":
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            for p in items:
                rows.append(dict(p))
            return _Resp(items)
        m = [r for r in rows if not any(r.get(k) != v for k, v in self.eqs)]
        if self.op == "update":
            for r in m:
                r.update(self.payload)
            return _Resp(m)
        if self.single_:
            return _Resp(m[0] if m else None)
        return _Resp(m[:self.limit_] if self.limit_ else m)


class _Rpc:
    def __init__(self, db, name, params): self.db, self.name, self.params = db, name, params

    def execute(self):
        import uuid
        if self.name == "post_journal_atomic":
            entry = dict(self.params["p_entry"])
            entry.setdefault("id", str(uuid.uuid4()))
            self.db.store.setdefault("journal_entries", []).append(entry)
            for l in self.params["p_lines"]:
                lr = dict(l); lr["journal_entry_id"] = entry["id"]
                self.db.store.setdefault("journal_lines", []).append(lr)
            return _Resp(entry["id"])
        if self.name == "pair_bank_transfer":
            p = self.params
            rows = self.db.store["bank_transactions"]
            a = next(r for r in rows if r["id"] == p["p_primary_id"])
            b = next(r for r in rows if r["id"] == p["p_counter_id"])
            a.update({"transfer_pair_id": b["id"], "transfer_is_primary": True,
                      "category": "Transfer"})
            b.update({"transfer_pair_id": a["id"], "transfer_is_primary": False,
                      "category": "Transfer"})
            return _Resp([a, b])
        raise RuntimeError(f"Unstubbed RPC: {self.name}")


class FakeDB:
    def __init__(self): self.store = {}
    def table(self, n): return _Q(self.store, n)
    def rpc(self, name, params): return _Rpc(self, name, params)


def _db():
    db = FakeDB()
    db.store["chart_of_accounts"] = [
        {"id": "coa-a", "firm_id": FIRM, "client_id": None, "account_name": "HDFC Bank",
         "system_account_key": "bank", "is_active": True},
        {"id": "coa-b", "firm_id": FIRM, "client_id": None, "account_name": "ICICI Bank",
         "system_account_key": None, "is_active": True},
    ]
    db.store["bank_statements"] = [
        {"id": "st-ba-hdfc", "firm_id": FIRM, "client_id": CLIENT, "bank_account_id": ACC_A},
        {"id": "st-ba-icici", "firm_id": FIRM, "client_id": CLIENT, "bank_account_id": ACC_B},
    ]
    db.store["bank_accounts"] = [
        {"id": ACC_A, "firm_id": FIRM, "client_id": CLIENT, "coa_account_id": "coa-a"},
        {"id": ACC_B, "firm_id": FIRM, "client_id": CLIENT, "coa_account_id": "coa-b"},
    ]
    db.store["bank_transactions"] = [
        _t("out", "2026-04-01", debit=50000000, account=ACC_A),
        _t("in", "2026-04-01", credit=50000000, account=ACC_B),
    ]
    return db


@pytest.fixture(autouse=True)
def _silence(monkeypatch):
    monkeypatch.setattr(bps.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(bps.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    monkeypatch.setattr("services.audit_service.log_event", lambda *a, **k: None, raising=False)
    yield


def _lines(db, je):
    return [l for l in db.store.get("journal_lines", []) if l["journal_entry_id"] == je]


def test_the_receiving_side_refuses_to_post():
    """THE guard. build_transfer_lines writes BOTH legs, so if the counterpart
    posted too the same ₹5,00,000 would appear twice — the overstatement this
    whole feature exists to prevent."""
    db = _db()
    bank_transfer_service.pair(db, FIRM, "out", "in")
    with pytest.raises(HTTPException) as ei:
        bank_posting_service.post(db, FIRM, "in", bank_account_id="coa-b", actor_id="u1")
    assert ei.value.status_code == 422
    assert "count the same money twice" in ei.value.detail
    assert db.store.get("journal_entries", []) == []


def test_the_paying_side_posts_one_balanced_contra():
    db = _db()
    bank_transfer_service.pair(db, FIRM, "out", "in")
    je = bank_posting_service.post(db, FIRM, "out", bank_account_id="coa-a",
                                   actor_id="u1")["posted_journal_id"]
    lines = _lines(db, je)
    assert len(lines) == 2
    assert sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines) == 50000000
    by_acc = {l["account_id"]: l for l in lines}
    assert by_acc["coa-b"]["debit_paise"] == 50000000     # money into the other account
    assert by_acc["coa-a"]["credit_paise"] == 50000000    # out of this one


def test_the_destination_is_resolved_from_the_pair():
    """The CA identified the destination by confirming the pair; making them
    pick it again invites a different answer."""
    db = _db()
    bank_transfer_service.pair(db, FIRM, "out", "in")
    je = bank_posting_service.post(db, FIRM, "out", bank_account_id="coa-a",
                                   actor_id="u1")["posted_journal_id"]
    assert any(l["account_id"] == "coa-b" for l in _lines(db, je))


def test_exactly_one_journal_exists_for_the_whole_transfer():
    db = _db()
    bank_transfer_service.pair(db, FIRM, "out", "in")
    bank_posting_service.post(db, FIRM, "out", bank_account_id="coa-a", actor_id="u1")
    with pytest.raises(HTTPException):
        bank_posting_service.post(db, FIRM, "in", bank_account_id="coa-b", actor_id="u1")
    assert len(db.store["journal_entries"]) == 1
    total = sum(l["debit_paise"] for l in db.store["journal_lines"])
    assert total == 50000000            # NOT 100000000


def test_the_counterpart_is_not_offered_in_the_ready_queue():
    """Refusing at post time is the backstop. Not offering it is the fix — a
    button that always errors is a defect of its own."""
    from domain.banking import entry as E
    db = _db()
    bank_transfer_service.pair(db, FIRM, "out", "in")
    rows = {t["id"]: t for t in db.store["bank_transactions"]}
    # The paying side is ready; the receiving side is COVERED by it and never
    # offered — the state the Entries screen filters on (09-bank-entries.md).
    assert E.entry_state(rows["out"]) == E.READY
    assert E.entry_state(rows["in"]) == E.COVERED


def test_an_unpaired_transfer_still_needs_a_destination():
    """Regression guard: the manual transfer path is unchanged."""
    db = _db()
    db.store["bank_transactions"][0]["category"] = "Transfer"
    with pytest.raises(HTTPException) as ei:
        bank_posting_service.post(db, FIRM, "out", bank_account_id="coa-a", actor_id="u1")
    assert ei.value.status_code == 422 and "destination" in ei.value.detail


# ══════════════════════════════════════════════════════════════════════════════
# The service
# ══════════════════════════════════════════════════════════════════════════════

def test_pairing_marks_both_sides_and_sets_the_category():
    db = _db()
    out = bank_transfer_service.pair(db, FIRM, "out", "in")
    assert out["is_paired"] is True and out["transfer_is_primary"] is True
    rows = {r["id"]: r for r in db.store["bank_transactions"]}
    assert rows["in"]["transfer_pair_id"] == "out"
    assert rows["in"]["transfer_is_primary"] is False
    assert rows["out"]["category"] == rows["in"]["category"] == "Transfer"


def test_detection_reads_the_account_from_each_statement():
    """Two lines on different statements of the SAME account are not a transfer,
    so the comparison has to be on accounts, not statements."""
    db = _db()
    db.store["bank_statements"].append(
        {"id": "st-second", "firm_id": FIRM, "client_id": CLIENT, "bank_account_id": ACC_A})
    db.store["bank_transactions"][1]["statement_id"] = "st-second"   # same account now
    assert bank_transfer_service.detect_pairs(db, FIRM, CLIENT) == []


def test_detection_finds_the_pair_through_the_statement_join():
    db = _db()
    pairs = bank_transfer_service.detect_pairs(db, FIRM, CLIENT)
    assert len(pairs) == 1 and pairs[0].primary_id == "out"
    assert bank_transfer_service.as_dict(pairs[0])["confidence"] == "high"
