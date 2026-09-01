"""
The two ageing-schedule endpoints are actually CALLED at least once.

Deliberately shallow, for the reason tests/test_new_payroll_endpoints_are_callable
records: four endpoints once shipped calling a two-argument guard with one
argument, and every one of them would have raised TypeError on its first real
request. Domain tests cannot see a wiring mistake. The statutory arithmetic is
tested in tests/test_schedule_iii_ageing.py; this executes the handlers.
"""
import pytest
from fastapi import HTTPException

import routers.accounting as ac
from routers.accounting import AgeingClassifyIn

CLIENT = "11111111-1111-1111-1111-111111111111"
USER = {"id": "u1", "firm_id": "f1", "auth_user_id": "a1", "email": "p@f.in", "role": "Partner"}


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    monkeypatch.setattr(ac, "_prod_db", lambda: None)
    monkeypatch.setattr(ac, "assert_client_access", lambda *a, **k: None)


def test_ageing_schedule_is_callable():
    out = ac.get_schedule_iii_ageing(client_id=CLIENT, as_of=None, current_user=USER)
    assert out["success"]
    assert out["data"]["division"] == "I"
    assert [r["key"] for r in out["data"]["payables"]["rows"]] == [
        "msme", "others", "disputed_msme", "disputed_others"]


def test_ageing_schedule_accepts_a_reporting_date():
    out = ac.get_schedule_iii_ageing(client_id=CLIENT, as_of="2026-03-31", current_user=USER)
    assert out["data"]["as_of"] == "2026-03-31"


def test_a_malformed_reporting_date_is_422_not_an_empty_schedule():
    with pytest.raises(HTTPException) as e:
        ac.get_schedule_iii_ageing(client_id=CLIENT, as_of="31-03-2026", current_user=USER)
    assert e.value.status_code == 422


def test_classify_refuses_an_unknown_target():
    body = AgeingClassifyIn(client_id=CLIENT, target="ledger", target_id="x",
                            is_disputed=True)
    with pytest.raises(HTTPException) as e:
        ac.classify_for_ageing_schedule(body, USER)
    assert e.value.status_code == 422
    assert "target must be one of" in str(e.value.detail)


def test_classify_refuses_a_field_that_does_not_belong_to_the_target():
    """A bill has no `considered_doubtful` — that row exists only in the
    receivables table. Accepting it would write a column purchase_bills does not
    have, or silently drop it."""
    body = AgeingClassifyIn(client_id=CLIENT, target="bill", target_id="b1",
                            considered_doubtful=True)
    with pytest.raises(HTTPException) as e:
        ac.classify_for_ageing_schedule(body, USER)
    assert e.value.status_code == 422
    assert "accepts only" in str(e.value.detail)


def test_classify_refuses_an_msmed_status_that_is_not_one():
    body = AgeingClassifyIn(client_id=CLIENT, target="vendor", target_id="v1",
                            msme_status="large")
    with pytest.raises(HTTPException) as e:
        ac.classify_for_ageing_schedule(body, USER)
    assert e.value.status_code == 422
    assert "msme_status must be null or one of" in str(e.value.detail)


def test_classify_refuses_an_empty_body():
    body = AgeingClassifyIn(client_id=CLIENT, target="invoice", target_id="i1")
    with pytest.raises(HTTPException) as e:
        ac.classify_for_ageing_schedule(body, USER)
    assert e.value.status_code == 422
    assert "nothing to set" in str(e.value.detail)


def test_clearing_a_vendors_classification_is_allowed():
    """A CA who classified a vendor by mistake must be able to put them back
    into the gap. s.43B(h) makes a standing guess worse than a stated unknown —
    so `msme_status: null` has to be distinguishable from "field not sent", and
    reach validation rather than being dropped."""
    body = AgeingClassifyIn(client_id=CLIENT, target="vendor", target_id="v1",
                            msme_status=None)
    with pytest.raises(HTTPException) as e:
        ac.classify_for_ageing_schedule(body, USER)
    # 503 (no database in mock mode), NOT 422 — the value passed validation.
    assert e.value.status_code == 503, e.value.detail


def test_a_registration_number_cannot_be_recorded_without_a_classification():
    """A Udyam number is the EVIDENCE for a classification, not a classification.
    Storing one beside a NULL msme_status would look like the vendor had been
    classified while leaving them in the gap."""
    body = AgeingClassifyIn(client_id=CLIENT, target="vendor", target_id="v1",
                            msme_registration_no="UDYAM-MH-01-0000001")
    with pytest.raises(HTTPException) as e:
        ac.classify_for_ageing_schedule(body, USER)
    assert e.value.status_code == 422
    assert "cannot be recorded without msme_status" in str(e.value.detail)


# ── What each write actually sends ───────────────────────────────────────────
# The service writes through six literal branches so the column checker can read
# every column name (see _write's docstring). Verbose code with branches needs a
# test that each branch sends what it claims, and only that.

class _FakeQuery:
    def __init__(self, sink): self.sink = sink
    def update(self, payload): self.sink["payload"] = payload; return self
    def eq(self, col, val): self.sink.setdefault("eq", []).append((col, val)); return self
    def execute(self):
        return type("R", (), {"data": [{"id": self.sink.get("id")}]})()


class _FakeDB:
    def __init__(self): self.calls = []
    def table(self, name):
        sink = {"table": name}
        self.calls.append(sink)
        return _FakeQuery(sink)


@pytest.mark.parametrize("fields,table,expected", [
    ({"is_disputed": True}, "client_sales_invoices", {"is_disputed": True}),
    ({"considered_doubtful": True}, "client_sales_invoices", {"considered_doubtful": True}),
    ({"is_disputed": False, "considered_doubtful": True}, "client_sales_invoices",
     {"is_disputed": False, "considered_doubtful": True}),
])
def test_invoice_branches_write_exactly_what_was_sent(fields, table, expected):
    from services import ageing_schedule_service as svc
    db = _FakeDB()
    svc.classify(db, "f1", CLIENT, "invoice", "i1", dict(fields))
    assert db.calls[0]["table"] == table
    assert db.calls[0]["payload"] == expected
    assert ("firm_id", "f1") in db.calls[0]["eq"]
    assert ("client_id", CLIENT) in db.calls[0]["eq"]


def test_a_bill_is_written_to_purchase_bills():
    from services import ageing_schedule_service as svc
    db = _FakeDB()
    svc.classify(db, "f1", CLIENT, "bill", "b1", {"is_disputed": True})
    assert db.calls[0]["table"] == "purchase_bills"
    assert db.calls[0]["payload"] == {"is_disputed": True}


def test_a_vendor_classification_does_not_touch_a_registration_it_was_not_given():
    """The partial-update branch exists for this: classifying a vendor from the
    unclassified list must not wipe a Udyam number recorded earlier."""
    from services import ageing_schedule_service as svc
    db = _FakeDB()
    svc.classify(db, "f1", CLIENT, "vendor", "v1", {"msme_status": "small"})
    assert db.calls[0]["payload"] == {"msme_status": "small"}


def test_a_vendor_classification_with_evidence_writes_both():
    from services import ageing_schedule_service as svc
    db = _FakeDB()
    svc.classify(db, "f1", CLIENT, "vendor", "v1",
                 {"msme_status": "micro", "msme_registration_no": " UDYAM-MH-01-1 "})
    assert db.calls[0]["payload"] == {"msme_status": "micro",
                                      "msme_registration_no": "UDYAM-MH-01-1"}


# ── The SQL function is what production runs ─────────────────────────────────

class _RpcDB:
    """A database that answers the RPC. If the service ever stops asking for the
    function first, the ageing schedule silently reverts to reading rows — which
    still gives the right answer, so nothing else would notice."""

    def __init__(self, payload=None, blow_up=False):
        self.payload, self.blow_up, self.calls, self.tables = payload, blow_up, [], []

    def rpc(self, fn, params):
        self.calls.append((fn, params))
        db = self

        class _R:
            def execute(self):
                if db.blow_up:
                    raise RuntimeError("function does not exist")
                return type("Res", (), {"data": db.payload})()
        return _R()

    def table(self, name):
        self.tables.append(name)
        rows: list = []

        class _Q:
            def select(self, *a, **k): return self
            def eq(self, *a, **k): return self
            def gt(self, *a, **k): return self
            def is_(self, *a, **k): return self
            def order(self, *a, **k): return self
            def limit(self, *a, **k): return self
            @property
            def not_(self): return self
            def in_(self, *a, **k): return self
            def execute(self): return type("Res", (), {"data": rows})()
        return _Q()


def test_the_sql_function_is_asked_first():
    from services import ageing_schedule_service as svc
    doc = {"receivables": {"total_paise": 1}, "payables": {"total_paise": 2}}
    db = _RpcDB(payload=doc)
    out = svc.schedule(db, "f1", CLIENT, "2026-03-31")
    assert [c[0] for c in db.calls] == ["schedule_iii_ageing"]
    assert db.calls[0][1] == {"p_firm": "f1", "p_client": CLIENT, "p_as_of": "2026-03-31"}
    assert out is doc, "the function's answer was recomputed instead of returned"
    assert db.tables == [], "it read rows as well as calling the function"


def test_a_broken_function_falls_back_rather_than_500ing():
    """A CA must still get the note if the migration has not reached this
    database yet. The fallback reads OPEN documents only (the filters are in the
    query, migration 278), so it is bounded by what is owed."""
    from services import ageing_schedule_service as svc
    db = _RpcDB(blow_up=True)
    out = svc.schedule(db, "f1", CLIENT, "2026-03-31")
    assert [c[0] for c in db.calls] == ["schedule_iii_ageing"], "it did try the function first"
    assert set(db.tables) == {"client_sales_invoices", "purchase_bills", "vendors"}
    assert out["division"] == "I"
    assert out["receivables"]["total_paise"] == 0


def test_a_half_answer_from_the_function_is_a_failure_not_a_report():
    """Anything but a whole schedule is a bug to fall back from, never a thin
    document to render — a note missing its payables table would be signed."""
    from services import ageing_schedule_service as svc
    db = _RpcDB(payload={"receivables": {}})
    out = svc.schedule(db, "f1", CLIENT, "2026-03-31")
    assert "payables" in out and "gaps" in out
    assert db.tables, "it rendered the half answer instead of falling back"


def test_the_two_per_document_ageing_endpoints_answer_the_same_way_with_no_database():
    """They are each other's mirror. ap-aging had no mock branch while ar-aging
    did, so with no database one returned an empty schedule and the other a
    generic failure — which is how the Payables tab of a report shows an error
    beside a working Receivables tab."""
    import routers.customers as cu
    import routers.vendors as ve

    ar = cu.ar_aging(client_id=CLIENT, as_of=None, current_user=USER)
    ap = ve.ap_aging(client_id=CLIENT, as_of=None, current_user=USER)
    assert ar["success"] is ap["success"] is True
    assert ar["data"]["total_outstanding_paise"] == ap["data"]["total_outstanding_paise"] == 0
    assert ar["data"]["invoices"] == [] and ap["data"]["bills"] == []
