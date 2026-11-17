"""A lot recorded on FORM GST ITC-04 can be retracted, and everything that reads lots leaves a retracted one out (POST-A-418).

The database half (migration 651: the columns, the function, the room, the cancel trigger) is `test_651_..._pg.py`; here, in mock mode over
the same functions' in-memory double: the door's refusals and its answers, the readers (the statement and its Table 5A, the room a line has
left, the day the challan came back, the cancel guard, the order), the route's permission pair and audit event, and the screen's sentence.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).parent))

import routers.sales_cycle as route
import services.itc_04_service as itc_service
import services.sales_cycle_service as svc
import test_itc_04_is_derived_from_the_challans_already_entered as itc
from tests.e2e_harness import FakeDB

TODAY = date(2026, 10, 9)


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(svc, "ist_today", lambda: TODAY)
    monkeypatch.setattr(itc_service, "ist_today", lambda: TODAY)


@pytest.fixture
def db():
    x = FakeDB()
    x.seed("clients", {"id": itc.CLIENT, "firm_id": itc.FIRM, "client_name": "Mfg Co"})
    x.seed("clients", {"id": itc.OTHER_CLIENT, "firm_id": itc.FIRM, "client_name": "Other Co"})
    return x


def _sent(db, no="JW/1", qty="10"):
    c = itc._challan(db, no, "2026-06-01")
    ln = itc._line(db, c, qty=qty)
    return c, ln


def _record(db, c, ln, back="4", lost="0", on="2026-08-20"):
    return itc_service.record_return(db, itc.FIRM, itc.CLIENT, c["id"], {
        "client_id": itc.CLIENT, "challan_line_id": ln["id"], "returned_on": on, "quantity_returned": back, "quantity_lost_or_wasted": lost,
        "job_worker_challan_no": "JW/22", "job_worker_challan_date": on, "nature_of_job_work": "Machining"}, None)


def _retract(db, c, lot, reason="recorded on the wrong challan", client=itc.CLIENT):
    return itc_service.retract_lot(db, itc.FIRM, client, c["id"], lot["id"], reason, "user-1")


def _status(db, c):
    return next(r for r in db.rows("delivery_challans") if r["id"] == c["id"])


def test_a_retraction_keeps_the_lot_with_its_reason_and_person_and_the_lot_stops_counting(db):
    c, ln = _sent(db)
    lot = _record(db, c, ln, back="4")
    assert svc._latest_returned_on(db, itc.FIRM, itc.CLIENT, c["id"]) == date(2026, 8, 20)
    out = _retract(db, c, lot)
    stored = next(r for r in db.rows("delivery_challan_returns") if r["id"] == lot["id"])
    assert stored["retracted_at"] and stored["retracted_by"] == "user-1" and stored["retraction_reason"] == "recorded on the wrong challan"
    assert out["challan_back_to_issued"] is False
    assert svc._latest_returned_on(db, itc.FIRM, itc.CLIENT, c["id"]) is None
    assert svc._latest_lot_recorded_on(db, itc.FIRM, itc.CLIENT, c["id"]) is None


def test_a_retracted_lot_gives_its_room_back_and_is_off_the_statement(db):
    c, ln = _sent(db, qty="10")
    lot = _record(db, c, ln, back="8")
    with pytest.raises(HTTPException) as caught:
        _record(db, c, ln, back="5", on="2026-08-21")
    assert caught.value.status_code == 409
    _retract(db, c, lot)
    _record(db, c, ln, back="10", on="2026-08-21")
    out = itc_service.statement(db, itc.FIRM, itc.CLIENT, "2026-27", as_at=TODAY)
    assert all(r.get("id") != lot["id"] for r in db.rows("delivery_challan_returns") if not r.get("retracted_at"))
    five = []
    for reading in out["readings"]:
        for w in reading["windows"]:
            five += itc_service.statement(db, itc.FIRM, itc.CLIENT, "2026-27", window=w["key"], as_at=TODAY)["table_5a"]["rows"]
    five = [r for r in five if not r["derived_from_whole_challan_return"]]
    assert five, "no window carried the lot"
    assert {r["quantity"] for r in five} == {"10.000"} and all(r["lot_id"] and r["lot_id"] != lot["id"] for r in five)


def test_a_challan_the_lots_marked_back_is_issued_again_when_a_lot_is_retracted(db):
    c, ln = _sent(db, qty="10")
    lot = _record(db, c, ln, back="10")
    assert _status(db, c)["status"] == "received_back"
    out = _retract(db, c, lot)
    assert out["challan_back_to_issued"] is True
    assert _status(db, c)["status"] == "issued" and _status(db, c)["received_back_on"] is None


def test_a_challan_the_ca_marked_back_after_a_part_lot_keeps_the_cas_day_when_that_lot_is_retracted(db):
    """4 of 10 came back in a lot; the CA then marked the whole challan back on 20 September through the whole-challan door. The lots never brought
    every line back, so they did not mark it back, and retracting the part lot leaves the CA's record and its day as they are."""
    c, ln = _sent(db, qty="10")
    lot = _record(db, c, ln, back="4")
    assert _status(db, c)["status"] == "issued"
    svc.update_challan(db, itc.FIRM, c["id"], {"status": "received_back", "received_back_on": "2026-09-20"})
    out = _retract(db, c, lot)
    assert out["challan_back_to_issued"] is False
    assert _status(db, c)["status"] == "received_back" and str(_status(db, c)["received_back_on"])[:10] == "2026-09-20"


def test_a_challan_with_every_lot_retracted_can_be_cancelled_and_the_refusal_says_retract_first(db):
    c, ln = _sent(db)
    lot = _record(db, c, ln, back="3")
    with pytest.raises(HTTPException) as caught:
        svc.update_challan(db, itc.FIRM, c["id"], {"status": "cancelled"})
    assert "retract the lot first" in str(caught.value.detail)
    _retract(db, c, lot)
    assert svc.update_challan(db, itc.FIRM, c["id"], {"status": "cancelled"})["status"] == "cancelled"


def test_a_lot_that_is_not_there_or_not_this_clients_or_already_retracted_is_the_same_404(db):
    c, ln = _sent(db)
    lot = _record(db, c, ln)
    other, oln = _sent(db, "JW/2")
    for call in (lambda: itc_service.retract_lot(db, itc.FIRM, itc.CLIENT, other["id"], lot["id"], "x", None),
                 lambda: _retract(db, c, lot, client=itc.OTHER_CLIENT),
                 lambda: itc_service.retract_lot(db, itc.FIRM, itc.CLIENT, c["id"], "no-such-lot", "x", None)):
        with pytest.raises(HTTPException) as caught:
            call()
        assert caught.value.status_code == 404
    _retract(db, c, lot)
    with pytest.raises(HTTPException) as caught:
        _retract(db, c, lot)
    assert caught.value.status_code == 404


def test_a_blank_reason_is_refused_and_writes_nothing(db):
    c, ln = _sent(db)
    lot = _record(db, c, ln)
    with pytest.raises(HTTPException) as caught:
        _retract(db, c, lot, reason="   ")
    assert caught.value.status_code == 422
    assert not any(r.get("retracted_at") for r in db.rows("delivery_challan_returns"))


class _Before651(FakeDB):
    """The database in the minutes between the API's deploy and the migration job applying 651: a read that names `retracted_at` fails as
    PostgREST answers it (42703), and the retraction function is not there (PGRST202)."""

    def table(self, name):
        q = super().table(name)
        real = q.execute

        def execute():
            if any(col == "retracted_at" for _kind, col, _val in q._filters):
                err = Exception(str({"code": "42703", "message": "column delivery_challan_returns.retracted_at does not exist", "details": None, "hint": None}))
                err.code = "42703"
                raise err
            return real()
        q.execute = execute
        return q

    def rpc(self, fn, params=None):
        if fn == "retract_challan_lot_atomic":
            raise Exception(str({"code": "PGRST202", "message": "Could not find the function public.retract_challan_lot_atomic in the schema cache"}))
        return super().rpc(fn, params)


def test_before_migration_651_is_applied_every_reader_of_lots_reads_them_all_and_a_retraction_says_to_wait():
    """The API is live some minutes before 651 is applied (one squash carries both): the statement, the record door's room, the challan's back
    day and the cancel guard read every lot (none can be retracted yet, so that is the same answer), and the retraction is a 503 in words."""
    db = _Before651()
    db.seed("clients", {"id": itc.CLIENT, "firm_id": itc.FIRM, "client_name": "Mfg Co"})
    c, ln = _sent(db, qty="10")
    lot = _record(db, c, ln, back="8")
    with pytest.raises(HTTPException) as caught:
        _record(db, c, ln, back="5", on="2026-08-21")
    assert caught.value.status_code == 409                       # the room check read the lot of 8
    assert svc._latest_returned_on(db, itc.FIRM, itc.CLIENT, c["id"]) == date(2026, 8, 20)
    assert svc._latest_lot_recorded_on(db, itc.FIRM, itc.CLIENT, c["id"]) == date(2026, 8, 20)
    out = itc_service.statement(db, itc.FIRM, itc.CLIENT, "2026-27", as_at=TODAY)
    five = [r for reading in out["readings"] for w in reading["windows"]
            for r in itc_service.statement(db, itc.FIRM, itc.CLIENT, "2026-27", window=w["key"], as_at=TODAY)["table_5a"]["rows"]]
    assert any(r.get("lot_id") == lot["id"] for r in five), "the statement did not read the lot"
    with pytest.raises(HTTPException) as caught:
        _retract(db, c, lot)
    assert caught.value.status_code == 503 and "nothing was retracted" in caught.value.detail
    # Any other failure of a read is raised as it came, not read again without the filter.
    with pytest.raises(Exception, match="boom"):
        from services import delivery_challan_writes as writes
        writes.read_live_lots(lambda live: (_ for _ in ()).throw(Exception("boom")))


def test_the_route_asks_the_invoice_write_pair_and_the_client_and_writes_an_audit_event(monkeypatch):
    import inspect
    src = inspect.getsource(route.retract_challan_return)
    assert 'rbac("invoice", "write")' in inspect.getsource(route).split("def retract_challan_return")[0].rsplit("@router", 1)[1] + src
    assert "assert_client_access(current_user, payload.client_id)" in src and "log_event(" in src
