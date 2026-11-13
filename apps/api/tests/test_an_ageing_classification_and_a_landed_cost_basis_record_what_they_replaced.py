"""The two doors that set a user-chosen classification on a document or a supplier record what the column held before (POST-A-430).

WHAT WAS WRONG
    `POST /api/accounting/schedule-iii/ageing/classify` writes `is_disputed` and `considered_doubtful` on a receivable, `is_disputed` on a payable, a supplier's MSME
    classification, registration number and agreement period, and an account's unbilled-dues side; `PUT /api/purchase-bills/landed-cost-basis` writes the client's landed-cost
    basis (an accounting policy, AS 2) or one bill's override. Both logged only the value written. POST-A-424 gave the six document edit routes an old value; these two doors
    still left only the new one, so "this invoice was un-disputed, what was it?" and "this supplier was taken out of the MSME classification, what had it been?" (the answers s.43B(h)
    and the Schedule III ageing note turn on) could not be answered from the log.

WHAT IS HELD
    The row is read FIRST under the same firm and client scope the write uses, and what each column about to be written held is returned and put in the edit log as `old_data` beside
    `new_data`. A row that is not this client's is the same 404 as before, and nothing is written (the landed-cost write used to match nothing and report success). A read that fails is
    not swallowed: a classification that cannot be recorded with what it replaced is not made. The response a caller gets does not change shape.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.accounting as ac
import routers.purchase_bills as pb
from domain.inventory import landed_cost as landed
from routers.accounting import AgeingClassifyIn
from services import ageing_schedule_service as svc
from services import landed_cost_service as lc
from tests.e2e_harness import FakeDB

FIRM, CLIENT, OTHER = "F1", "C1", "C2"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "a1", "email": "p@f.in", "role": "Partner"}


@pytest.fixture
def db(monkeypatch):
    x = FakeDB()
    monkeypatch.setattr(ac, "_prod_db", lambda: x)
    monkeypatch.setattr(ac, "assert_client_access", lambda *a, **k: None)
    return x


@pytest.fixture
def events(monkeypatch):
    seen: list[dict] = []
    monkeypatch.setattr(ac, "log_event", lambda *a, **k: seen.append({"args": a, **k}))
    return seen


# (target, table, the row as it stands, what is sent, what each column written held before)
CASES = [
    ("invoice", "client_sales_invoices", {"is_disputed": False, "considered_doubtful": True},
     {"is_disputed": True, "considered_doubtful": False}, {"is_disputed": False, "considered_doubtful": True}),
    ("invoice", "client_sales_invoices", {"is_disputed": True, "considered_doubtful": True},
     {"is_disputed": False}, {"is_disputed": True}),
    ("bill", "purchase_bills", {"is_disputed": True}, {"is_disputed": False}, {"is_disputed": True}),
    ("vendor", "vendors", {"msme_status": "small", "msme_registration_no": "UDYAM-1", "msmed_agreement_days": 45},
     {"msme_status": None}, {"msme_status": "small"}),
    ("vendor", "vendors", {"msme_status": None, "msme_registration_no": None, "msmed_agreement_days": None},
     {"msme_status": "micro", "msme_registration_no": "UDYAM-2", "msmed_agreement_days": 30},
     {"msme_status": None, "msme_registration_no": None, "msmed_agreement_days": None}),
    ("account", "chart_of_accounts", {"unbilled_dues_side": "payable", "client_id": None},
     {"unbilled_dues_side": None}, {"unbilled_dues_side": "payable"}),
]


@pytest.mark.parametrize("target,table,row,sent,was", CASES)
def test_the_route_logs_what_each_column_held_before_and_what_it_holds_now(db, events, target, table, row, sent, was):
    base = {"id": "r1", "firm_id": FIRM, "client_id": CLIENT}
    db.seed(table, {**base, **row})
    out = ac.classify_for_ageing_schedule(AgeingClassifyIn(client_id=CLIENT, target=target, target_id="r1", **sent), USER)
    assert len(events) == 1
    assert events[0]["old_data"] == was, "the log does not say what the column held before"
    assert events[0]["new_data"] == out["data"]["set"] == sent
    assert "was" not in out["data"], "the response changed shape"
    stored = next(r for r in db.rows(table) if r["id"] == "r1")
    assert all(stored[k] == events[0]["new_data"][k] for k in events[0]["new_data"]), "the write did not land"


def test_a_row_of_another_client_is_a_404_and_nothing_is_written(db, events):
    db.seed("client_sales_invoices", {"id": "i1", "firm_id": FIRM, "client_id": OTHER, "is_disputed": False, "considered_doubtful": False})
    with pytest.raises(HTTPException) as caught:
        ac.classify_for_ageing_schedule(AgeingClassifyIn(client_id=CLIENT, target="invoice", target_id="i1", is_disputed=True), USER)
    assert caught.value.status_code == 404
    assert db.rows("client_sales_invoices")[0]["is_disputed"] is False
    assert events == []


def test_a_row_of_another_firm_is_a_404_too(db, events):
    db.seed("purchase_bills", {"id": "b1", "firm_id": "F2", "client_id": CLIENT, "is_disputed": False})
    with pytest.raises(HTTPException) as caught:
        ac.classify_for_ageing_schedule(AgeingClassifyIn(client_id=CLIENT, target="bill", target_id="b1", is_disputed=True), USER)
    assert caught.value.status_code == 404 and db.rows("purchase_bills")[0]["is_disputed"] is False


def test_a_read_that_fails_is_not_swallowed_and_nothing_is_written():
    class _Broken:
        wrote = False

        def table(self, name):
            return self

        def select(self, *a, **k):
            raise RuntimeError("database unreachable")

        def update(self, *a, **k):
            _Broken.wrote = True
            return self

    with pytest.raises(RuntimeError, match="database unreachable"):
        svc.classify(_Broken(), FIRM, CLIENT, "invoice", "i1", {"is_disputed": True})
    assert _Broken.wrote is False


def test_the_service_returns_what_was_held_only_for_the_columns_it_wrote():
    x = FakeDB()
    x.seed("vendors", {"id": "v1", "firm_id": FIRM, "client_id": CLIENT, "msme_status": "small", "msme_registration_no": "UDYAM-1", "msmed_agreement_days": 45})
    out = svc.classify(x, FIRM, CLIENT, "vendor", "v1", {"msme_status": "medium"})
    assert out["was"] == {"msme_status": "small"}, "a column that was not written was reported as changed"


# ── the landed-cost basis ─────────────────────────────────────────────────────

BASIS, OTHER_BASIS = sorted(landed.BASES)[0], sorted(landed.BASES)[1]


def test_a_client_basis_change_returns_the_basis_it_replaced():
    x = FakeDB()
    x.seed("clients", {"id": CLIENT, "firm_id": FIRM, "landed_cost_basis": BASIS})
    out = lc.set_basis(x, firm_id=FIRM, client_id=CLIENT, basis=OTHER_BASIS)
    assert out["ok"] and out["was"] == BASIS and out["basis"] == OTHER_BASIS
    assert x.rows("clients")[0]["landed_cost_basis"] == OTHER_BASIS


def test_a_bill_override_returns_the_override_it_replaced_including_none():
    x = FakeDB()
    x.seed("purchase_bills", {"id": "b1", "firm_id": FIRM, "client_id": CLIENT, "landed_cost_basis": None})
    first = lc.set_basis(x, firm_id=FIRM, client_id=CLIENT, basis=BASIS, bill_id="b1")
    assert first["ok"] and first["was"] is None
    second = lc.set_basis(x, firm_id=FIRM, client_id=CLIENT, basis=None, bill_id="b1")
    assert second["ok"] and second["was"] == BASIS and x.rows("purchase_bills")[0]["landed_cost_basis"] is None


def test_a_bill_or_client_that_is_not_this_ones_is_refused_in_words_and_nothing_is_written():
    x = FakeDB()
    x.seed("purchase_bills", {"id": "b1", "firm_id": FIRM, "client_id": OTHER, "landed_cost_basis": None})
    x.seed("clients", {"id": "C9", "firm_id": "F2", "landed_cost_basis": BASIS})
    bill = lc.set_basis(x, firm_id=FIRM, client_id=CLIENT, basis=BASIS, bill_id="b1")
    assert bill["ok"] is False and "not on this client's books" in bill["refusal"]
    assert x.rows("purchase_bills")[0]["landed_cost_basis"] is None
    client = lc.set_basis(x, firm_id=FIRM, client_id="C9", basis=OTHER_BASIS)
    assert client["ok"] is False and "not on this firm's books" in client["refusal"]
    assert x.rows("clients")[0]["landed_cost_basis"] == BASIS


def test_the_route_logs_the_basis_it_replaced(monkeypatch):
    x = FakeDB()
    x.seed("clients", {"id": CLIENT, "firm_id": FIRM, "landed_cost_basis": BASIS})
    seen: list[dict] = []
    monkeypatch.setattr(pb, "_USE_MOCK", False)
    monkeypatch.setattr(pb, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(pb, "log_event", lambda *a, **k: seen.append({"args": a, **k}))
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_supabase", lambda: x)
    out = pb.put_landed_cost_basis(pb.LandedCostBasisIn(client_id=CLIENT, basis=OTHER_BASIS), USER)
    assert out["success"] and "was" not in out["data"]
    assert seen[0]["old_data"] == {"basis": BASIS, "bill_id": None}
    assert seen[0]["new_data"] == {"basis": OTHER_BASIS, "bill_id": None}


# ── the read before the write is scoped as the write is ───────────────────────────────────────────────

class _Chain:
    """Records every call of one query chain; `execute()` answers the next prepared read, or a successful write."""

    def __init__(self, owner, table):
        self.owner, self.calls = owner, [("table", table)]
        owner.chains.append(self.calls)

    def __getattr__(self, name):
        def call(*args, **_kw):
            self.calls.append((name, *args))
            return self
        return call

    def execute(self):
        is_read = any(c[0] == "select" for c in self.calls)
        data = self.owner.reads.pop(0) if is_read else [{"id": "r1"}]
        return type("R", (), {"data": data})()


class _RecordingDB:
    def __init__(self, reads):
        self.chains, self.reads = [], list(reads)

    def table(self, name):
        return _Chain(self, name)


def _reads_and_writes(db):
    return ([c for c in db.chains if any(x[0] == "select" for x in c)], [c for c in db.chains if any(x[0] == "update" for x in c)])


@pytest.mark.parametrize("target,fields,table", [
    ("invoice", {"is_disputed": True}, "client_sales_invoices"),
    ("bill", {"is_disputed": True}, "purchase_bills"),
    ("vendor", {"msme_status": "small"}, "vendors"),
])
def test_the_read_before_the_write_names_the_firm_and_the_client(target, fields, table):
    db = _RecordingDB([[{"is_disputed": False, "msme_status": None}]])
    svc.classify(db, FIRM, CLIENT, target, "r1", dict(fields))
    reads, writes = _reads_and_writes(db)
    assert len(reads) == 1 and len(writes) == 1 and db.chains.index(reads[0]) < db.chains.index(writes[0]), "the row is not read first"
    assert reads[0][0] == ("table", table)
    assert ("eq", "firm_id", FIRM) in reads[0] and ("eq", "client_id", CLIENT) in reads[0] and ("eq", "id", "r1") in reads[0]


def test_an_account_is_read_as_the_clients_own_and_then_as_the_firms_shared_one():
    db = _RecordingDB([[], [{"unbilled_dues_side": "payable"}]])
    out = svc.classify(db, FIRM, CLIENT, "account", "a1", {"unbilled_dues_side": None})
    reads, _ = _reads_and_writes(db)
    assert len(reads) == 2
    assert ("eq", "client_id", CLIENT) in reads[0] and ("is_", "client_id", "null") in reads[1]
    assert all(("eq", "firm_id", FIRM) in r and ("eq", "id", "a1") in r for r in reads), "a read of an account is not scoped to the firm"
    assert out["was"] == {"unbilled_dues_side": "payable"}
    # and a client's own account is found at the first read, so the shared one is not asked for
    own = _RecordingDB([[{"unbilled_dues_side": "receivable"}]])
    svc.classify(own, FIRM, CLIENT, "account", "a1", {"unbilled_dues_side": None})
    assert len(_reads_and_writes(own)[0]) == 1
