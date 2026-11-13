"""A delivery challan is issued by one door, and a job-work challan is then a row of FORM GST ITC-04 (POST-A-398).

WHAT WAS WRONG
    `create_challan` wrote `status: "draft"` and nothing in the product ever set `issued`: no route, no database function, no trigger, no button (a test read the whole API tree, the
    migrations and the front end for one). Three things hung from that. FORM GST ITC-04 lists a job-work challan only when it is `issued` or `received_back` (`itc_04.SENT_STATUSES`), so a
    job-work challan made in the product was not listed as sent until its goods were marked back; the ITC-04 lot door refuses a draft ("goods can only come back on a challan that has been
    issued"), so the lots of goods could not be recorded against it at all; and the whole-challan "Record goods back" was offered for a draft and took `received_back` on it, which
    was the one way left to end the s.143 clock of a challan made here. A draft also drew a clock, an overdue banner and a gap about the kind of goods, as if goods were out on it.

WHAT THIS HOLDS
    * `issue_challan` is the ONE door that makes a challan issued. It turns a draft into an issued challan and changes nothing else, and every refusal is a sentence that leaves the row as
      it was: not a draft (issued, received back or cancelled), no lines, a date that has not come, a Rule 55(1) particular the challan does not hold (the consigner is the CLIENT), a job-work
      challan that does not say what is sent. The write is a compare-and-set on the status.
    * a job-work challan is on FORM GST ITC-04 once it is issued and not before, and the lot door that refused a draft takes it;
    * the amendment door cannot issue a challan, cannot send one back to a draft, cannot give goods back to a draft, cannot cancel one whose goods are already recorded as returned, and
      leaves a received-back or a cancelled challan at its end (`delivery_challan.status_change_problem`, pure);
    * a draft and a cancelled challan draw no clock (`deemed_supply_clock(status=…)`), on the list and in the Rule 55 view, and an issued one draws what it always did;
    * the route ties the challan to the client named, and writes the audit event.
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
from domain.gst import delivery_challan as dc
from tests.e2e_harness import FakeDB, wire_e2e

TODAY = date(2026, 10, 9)
CONSIGNER = {"legal_name": "Mfg Co Pvt Ltd", "gstin": None, "address": "1 Mill Road, Pune"}


@pytest.fixture(autouse=True)
def _india_today_is_fixed(monkeypatch):
    monkeypatch.setattr(svc, "ist_today", lambda: TODAY)
    monkeypatch.setattr(itc_service, "ist_today", lambda: TODAY)


@pytest.fixture
def db():
    x = FakeDB()
    x.seed("clients", {"id": itc.CLIENT, "firm_id": itc.FIRM, "client_name": "Mfg Co", "legal_name": "Mfg Co Pvt Ltd", "address_line1": "1 Mill Road", "city": "Pune"})
    x.seed("clients", {"id": itc.OTHER_CLIENT, "firm_id": itc.FIRM, "client_name": "Other Co"})
    return x


def _draft(db, no="JW/1", sent_on="2026-06-01", with_line=True, **over):
    challan = itc._challan(db, no, sent_on, status="draft", **over)
    if with_line:
        itc._line(db, challan)
    return challan


def _issue(db, challan, consigner=CONSIGNER):
    return svc.issue_challan(db, itc.FIRM, challan["id"], client_id=itc.CLIENT, consigner=consigner)


def _stored(db, challan):
    return next(r for r in db.rows("delivery_challans") if r["id"] == challan["id"])


def _refused(db, challan, code, consigner=CONSIGNER):
    before = dict(_stored(db, challan))
    with pytest.raises(HTTPException) as caught:
        _issue(db, challan, consigner)
    assert caught.value.status_code == code, (caught.value.status_code, caught.value.detail)
    assert _stored(db, challan) == before, "a refused issue wrote something"
    return str(caught.value.detail)


# ── the issue door ────────────────────────────────────────────────────────────────────────────────────
def test_a_draft_is_issued_and_nothing_else_about_it_changes(db):
    c = _draft(db)
    before = dict(_stored(db, c))
    out = _issue(db, c)
    after = _stored(db, c)
    assert out["status"] == after["status"] == "issued"
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    assert changed == {"status", "updated_at"}, f"issuing changed {sorted(changed)}"


@pytest.mark.parametrize("status", ["issued", "received_back", "cancelled"])
def test_only_a_draft_is_issued(db, status):
    c = _draft(db)
    _stored(db, c)["status"] = status
    assert _refused(db, c, 409) == dc.only_a_draft_is_issued_sentence("JW/1", status)


def test_a_challan_with_no_goods_on_it_is_not_issued(db):
    c = _draft(db, with_line=False)
    assert _refused(db, c, 422) == dc.an_empty_challan_is_not_issued_sentence("JW/1")


def test_a_challan_dated_after_today_is_not_issued_and_one_dated_today_is(db):
    tomorrow = _draft(db, "JW/2", "2026-10-10")
    detail = _refused(db, tomorrow, 422)
    assert "2026-10-10" in detail and "has not come" in detail
    today = _draft(db, "JW/3", "2026-10-09")
    assert _issue(db, today)["status"] == "issued"


def test_a_challan_that_lacks_a_rule_55_particular_is_not_issued_and_the_sentence_names_the_clause(db):
    no_consigner = _draft(db, "JW/4")
    detail = _refused(db, no_consigner, 422, consigner=None)
    assert detail == dc.issue_needs_the_particulars_sentence("JW/4", ["55(1)(ii) Name, address and GSTIN of the consigner, if registered"])
    no_consignee = _draft(db, "JW/5", consignee_name=None, consignee_gstin=None, consignee_address=None)
    assert "55(1)(iii)" in _refused(db, no_consignee, 422)
    no_hsn = _draft(db, "JW/6", with_line=False)
    itc._line(db, no_hsn, hsn_sac="")
    assert "55(1)(iv)" in _refused(db, no_hsn, 422)


def test_an_inter_state_challan_needs_its_place_of_supply(db):
    c = _draft(db, "JW/7", is_inter_state=True, place_of_supply=None)
    assert "55(1)(viii)" in _refused(db, c, 422)


def test_a_job_work_challan_is_not_issued_without_saying_what_is_sent_but_another_reason_is(db):
    job = _draft(db, "JW/8", goods_kind=None)
    assert _refused(db, job, 422) == dc.issue_needs_the_kind_of_goods_sentence("JW/8")
    approval = _draft(db, "SA/1", reason=dc.REASON_ON_APPROVAL, goods_kind=None)
    assert _issue(db, approval)["status"] == "issued", "the kind of goods is a job-work question"


def test_two_requests_cannot_both_issue_and_an_issue_loses_to_a_cancel_that_came_between(db, monkeypatch):
    c = _draft(db, "JW/9")
    real = svc.challan_lines

    def lines_then_a_cancel_lands(*a, **k):
        out = real(*a, **k)
        _stored(db, c)["status"] = "cancelled"                      # another request got in between the read and the write
        return out

    monkeypatch.setattr(svc, "challan_lines", lines_then_a_cancel_lands)
    with pytest.raises(HTTPException) as caught:
        _issue(db, c)
    assert caught.value.status_code == 409 and "changed while it was being issued" in str(caught.value.detail)
    assert _stored(db, c)["status"] == "cancelled", "the issue overwrote the cancel"


def test_another_firms_challan_is_not_found(db):
    c = _draft(db, "JW/10")
    with pytest.raises(HTTPException) as caught:
        svc.issue_challan(db, "ANOTHER-FIRM", c["id"], client_id=itc.CLIENT, consigner=CONSIGNER)
    assert caught.value.status_code == 404
    assert _stored(db, c)["status"] == "draft"


def test_the_door_itself_does_not_issue_a_challan_of_another_client_of_the_firm(db):
    """The route asks whose the challan is before it calls the door, and the door asks again: a caller that is not the route gets the words a missing challan gets, and nothing is written."""
    c = _draft(db, "JW/12")
    with pytest.raises(HTTPException) as other:
        svc.issue_challan(db, itc.FIRM, c["id"], client_id=itc.OTHER_CLIENT, consigner=CONSIGNER)
    with pytest.raises(HTTPException) as missing:
        svc.issue_challan(db, itc.FIRM, "no-such-challan", client_id=itc.OTHER_CLIENT, consigner=CONSIGNER)
    assert (other.value.status_code, other.value.detail) == (missing.value.status_code, missing.value.detail) == (404, "That delivery challan was not found.")
    assert _stored(db, c)["status"] == "draft"


def test_the_update_names_the_client_as_well_as_the_firm_and_the_id(db, monkeypatch):
    """Were the read's question let through (a helper that answered for a row it should not), the write itself would still match nothing for another client's challan:
    the update carries `client_id` (POST-A-337's rule, held over the whole tree by `test_a_route_that_asserts_a_client_does_not_write_a_row_by_the_firm_alone.py`)."""
    c = _draft(db, "JW/13")
    monkeypatch.setattr(svc, "row_of_client", lambda _db, _table, _firm, _row_id, _client, _what: _stored(db, c))
    with pytest.raises(HTTPException) as caught:
        svc.issue_challan(db, itc.FIRM, c["id"], client_id=itc.OTHER_CLIENT, consigner=CONSIGNER)
    assert caught.value.status_code == 409 and "changed while it was being issued" in str(caught.value.detail)
    assert _stored(db, c)["status"] == "draft", "the issue wrote a challan of another client"


# ── FORM GST ITC-04 ──────────────────────────────────────────────────────────────────────────────────
def _on_the_statement(db):
    out = itc_service.statement(db, itc.FIRM, itc.CLIENT, "2026-27", as_at=TODAY)
    return [r["challan_no"] for r in out["outstanding"]], out


def test_a_job_work_challan_is_on_itc_04_when_it_is_issued_and_not_before(db):
    c = _draft(db, "JW/11")
    listed, out = _on_the_statement(db)
    assert listed == [], "a draft is on FORM GST ITC-04"
    before = itc_service.statement(db, itc.FIRM, itc.CLIENT, "2026-27", window="2026-27:Q1", as_at=TODAY)
    assert not (before["table_4"] or {}).get("rows"), "a draft is a row of Table 4"
    _issue(db, c)
    listed, out = _on_the_statement(db)
    assert listed == ["JW/11"], "an issued job-work challan is not on FORM GST ITC-04"
    window = out["readings"][0]["windows"][0]["key"]                  # a window the statement lists: its Table 4 carries the challan when it was sent inside it
    assert window == "2026-27:Q1", window
    in_the_window = itc_service.statement(db, itc.FIRM, itc.CLIENT, "2026-27", window=window, as_at=TODAY)
    assert [r["challan_no"] for r in in_the_window["table_4"]["rows"]] == ["JW/11"] and in_the_window["table_4"]["count"] == 1, "Table 4 does not carry the issued challan"


def test_the_lot_door_refuses_a_draft_and_takes_the_challan_once_it_is_issued(db):
    c = _draft(db, "JW/12")
    line = next(r for r in db.rows("delivery_challan_lines") if r["challan_id"] == c["id"])
    payload = {"client_id": itc.CLIENT, "challan_line_id": line["id"], "returned_on": "2026-08-20", "quantity_returned": 4.0, "quantity_lost_or_wasted": 0.0,
               "job_worker_challan_no": "JW/22", "job_worker_challan_date": "2026-08-19", "nature_of_job_work": "Machining"}
    with pytest.raises(HTTPException) as caught:
        itc_service.record_return(db, itc.FIRM, itc.CLIENT, c["id"], dict(payload), None)
    assert dc.not_issued_sentence("JW/12", "draft") in str(caught.value.detail)
    _issue(db, c)
    itc_service.record_return(db, itc.FIRM, itc.CLIENT, c["id"], dict(payload), None)
    assert len(db.rows("delivery_challan_returns")) == 1


# ── the amendment door ───────────────────────────────────────────────────────────────────────────────
def _amend(db, challan, patch):
    return svc.update_challan(db, itc.FIRM, challan["id"], patch)


def test_an_amendment_cannot_give_goods_back_to_a_draft(db):
    c = _draft(db, "JW/13")
    for patch in ({"received_back_on": "2026-08-20"}, {"status": "received_back", "received_back_on": "2026-08-20"}):
        with pytest.raises(HTTPException) as caught:
            _amend(db, c, patch)
        assert caught.value.status_code == 409 and str(caught.value.detail) == dc.not_issued_sentence("JW/13", "draft"), patch
    assert _stored(db, c)["status"] == "draft" and not _stored(db, c).get("received_back_on")


def test_an_amendment_cannot_issue_a_challan_or_make_one_a_draft_again(db):
    draft = _draft(db, "JW/14")
    with pytest.raises(HTTPException) as caught:
        _amend(db, draft, {"status": "issued"})
    assert caught.value.status_code == 409 and "Issue challan" in str(caught.value.detail)
    issued = _draft(db, "JW/15")
    _issue(db, issued)
    with pytest.raises(HTTPException) as caught:
        _amend(db, issued, {"status": "draft"})
    assert caught.value.status_code == 409 and "not made a draft again" in str(caught.value.detail)
    assert _stored(db, draft)["status"] == "draft" and _stored(db, issued)["status"] == "issued"


def test_a_draft_can_be_cancelled_and_a_cancelled_challan_is_at_its_end(db):
    c = _draft(db, "JW/16")
    assert _amend(db, c, {"status": "cancelled"})["status"] == "cancelled"
    assert _refused(db, c, 409) == dc.only_a_draft_is_issued_sentence("JW/16", "cancelled")
    with pytest.raises(HTTPException) as caught:
        _amend(db, c, {"status": "issued"})
    assert "is cancelled: it cannot become issued" in str(caught.value.detail)


def test_an_issued_challan_with_goods_recorded_as_returned_is_not_cancelled_but_one_without_is(db):
    with_lot = _draft(db, "JW/17")
    _issue(db, with_lot)
    line = next(r for r in db.rows("delivery_challan_lines") if r["challan_id"] == with_lot["id"])
    itc._came_back(db, with_lot, line, "4", "2026-08-20")
    with pytest.raises(HTTPException) as caught:
        _amend(db, with_lot, {"status": "cancelled"})
    assert caught.value.status_code == 409 and str(caught.value.detail) == dc.cancel_after_goods_came_back_sentence("JW/17", "2026-08-20")
    assert _stored(db, with_lot)["status"] == "issued"
    clean = _draft(db, "JW/18")
    _issue(db, clean)
    assert _amend(db, clean, {"status": "cancelled"})["status"] == "cancelled"


def test_an_issued_challan_takes_the_whole_challan_back_day_as_before(db):
    c = _draft(db, "JW/19")
    _issue(db, c)
    out = _amend(db, c, {"received_back_on": "2026-08-20"})
    assert out["status"] == "received_back" and _stored(db, c)["received_back_on"] == "2026-08-20"


@pytest.mark.parametrize("current,wanted,expected", [
    ("draft", "draft", None), ("draft", "cancelled", None), ("issued", "received_back", None), ("issued", "cancelled", None), ("issued", "issued", None),
    ("draft", "issued", "Issue challan"), ("draft", "received_back", "goods can only come back on a challan that has been issued"),
    ("issued", "draft", "not made a draft again"),
    ("received_back", "issued", "its goods are back"), ("received_back", "cancelled", "its goods are back"), ("received_back", "draft", "its goods are back"),
    ("cancelled", "issued", "is cancelled"), ("cancelled", "received_back", "is cancelled"), ("cancelled", "draft", "is cancelled"),
])
def test_the_pure_rule_of_which_status_an_amendment_may_give(current, wanted, expected):
    problem = dc.status_change_problem("X/1", current, wanted)
    if expected is None:
        assert problem is None
    else:
        assert problem and expected in problem, problem


def test_every_status_a_patch_may_make_is_a_status_the_vocabulary_knows():
    from domain.sales import order_cycle as oc
    assert set(dc.AMENDMENT_MAY_MAKE) == set(oc.CHALLAN_STATUSES)
    for made in dc.AMENDMENT_MAY_MAKE.values():
        assert set(made) <= set(oc.CHALLAN_STATUSES) - {"draft", "issued"}, "an amendment can make a challan a draft or issue it"


# ── the clock ────────────────────────────────────────────────────────────────────────────────────────
def _clock(status, reason=dc.REASON_JOB_WORK, goods_kind=dc.GOODS_KIND_INPUTS, sent="2025-04-10", back=None, as_at="2026-10-09"):
    return dc.deemed_supply_clock(reason=reason, challan_date=sent, as_at=as_at, goods_kind=goods_kind, status=status, received_back_on=back)


def test_a_draft_and_a_cancelled_challan_draw_no_clock_and_no_gap():
    for status, words in (("draft", "not recorded as issued"), ("cancelled", "cancelled")):
        clock = _clock(status, goods_kind=None)               # no kind of goods: an issued one would name the gap, a draft has no period to run
        assert clock.applies is False and clock.overdue is None and clock.due_back_by is None and clock.gaps == [], status
        assert words in clock.consequence


def test_a_draft_says_what_issuing_it_would_mean_and_does_not_say_the_goods_have_not_left():
    """The product cannot know that the goods on a draft have not left, and issuing does not move the day a period counts from (the challan's date): a draft dated long ago is one press from a
    period that is over, and the sentence says so before the press (the reviewer's point: a forgotten challan costs tax)."""
    old = _clock("draft")                                          # job work, inputs, dated 2025-04-10, looked at on 2026-10-09
    assert old.applies is False and old.overdue is None and old.days_remaining is None and old.gaps == []
    assert "no period is running on it here" in old.consequence
    assert "If the goods left on the challan's date, 2025-04-10, the period under CGST Act s.143 with Rule 45 would end on 2026-04-10, which is already past." in old.consequence
    assert "not left" not in old.consequence and "yet" not in old.consequence, "a draft is not said to be a challan whose goods have not left"
    recent = _clock("draft", sent="2026-10-01")
    assert "would end on 2027-10-01." in recent.consequence and "already past" not in recent.consequence
    approval = _clock("draft", reason=dc.REASON_ON_APPROVAL, goods_kind=None, sent="2026-04-01")
    assert "CGST Act s.31(7)" in approval.consequence and "would end on 2026-10-01, which is already past." in approval.consequence


def test_a_draft_names_no_period_where_none_is_run_or_it_cannot_be_timed():
    base = dc.DRAFT_RUNS_NO_PERIOD
    assert _clock("draft", goods_kind=None).consequence == base, "the kind of goods is not recorded: the period is not timed and the issue door asks for the answer"
    assert _clock("draft", goods_kind=dc.GOODS_KIND_EXCLUDED).consequence == base, "moulds, dies, jigs, fixtures and tools have no period to end"
    assert _clock("draft", reason=dc.REASON_NOT_A_SUPPLY).consequence == "", "a reason with no period says nothing of one"


def test_a_cancelled_challan_says_nothing_of_the_goods():
    consequence = _clock("cancelled").consequence
    assert consequence == "This challan is cancelled, so no period is run on it here." and "goods" not in consequence


def test_an_issued_or_received_back_challan_draws_the_clock_it_always_did():
    for reason, kind in ((dc.REASON_JOB_WORK, dc.GOODS_KIND_INPUTS), (dc.REASON_ON_APPROVAL, None)):
        for back in (None, "2026-03-01", "2026-09-30"):
            without = dc.deemed_supply_clock(reason=reason, challan_date="2025-04-10", as_at="2026-10-09", goods_kind=kind, received_back_on=back)
            assert _clock("issued", reason=reason, goods_kind=kind, back=back).as_dict() == without.as_dict(), (reason, "issued", back)
            if back:                                               # a received-back challan with the day it came back is the same clock too
                assert _clock("received_back", reason=reason, goods_kind=kind, back=back).as_dict() == without.as_dict(), (reason, "received_back", back)
    assert _clock("issued").overdue is True and _clock("issued").applies is True


def test_a_challan_recorded_as_received_back_with_no_day_is_neither_overdue_nor_clear():
    """A row from before POST-A-383 (a status with no day). The goods are said to be back and when is unknown, so whether it was within the period is unknown: the clock still applies, it is not
    overdue and not on time, and the gap names what to record (the box "Mark a whole challan back at once" lists it for that)."""
    clock = _clock("received_back")
    assert clock.applies is True and clock.overdue is None and clock.days_remaining is None and clock.due_back_by == "2026-04-10"
    assert clock.gaps == [dc.RECEIVED_BACK_WITHOUT_A_DAY] and "Record the day they came back" in clock.gaps[0]
    assert _clock("issued").gaps == [] and _clock("received_back", back="2026-03-01").gaps == []


def test_the_list_says_a_status_only_row_cannot_be_timed(db):
    c = _draft(db, "JW/22", "2025-04-10", goods_kind=dc.GOODS_KIND_INPUTS)
    _stored(db, c)["status"] = "received_back"                     # written before POST-A-383 refused a status with no day
    row = next(r for r in svc.list_challans(db, itc.FIRM, itc.CLIENT) if r["document_no"] == "JW/22")
    assert row["clock"]["applies"] is True and row["clock"]["overdue"] is None and row["clock"]["gaps"] == [dc.RECEIVED_BACK_WITHOUT_A_DAY]


def test_a_reason_with_no_clock_is_unchanged_by_the_status():
    plain = dc.deemed_supply_clock(reason=dc.REASON_NOT_A_SUPPLY, challan_date="2025-04-10", as_at="2026-10-09")
    assert _clock("draft", reason=dc.REASON_NOT_A_SUPPLY).as_dict() == plain.as_dict()


def test_the_list_and_the_rule_55_view_draw_the_clock_of_the_status(db):
    draft = _draft(db, "JW/20", "2025-04-10")
    issued = _draft(db, "JW/21", "2025-04-10")
    _issue(db, issued)
    rows = {r["document_no"]: r for r in svc.list_challans(db, itc.FIRM, itc.CLIENT)}
    assert rows["JW/20"]["clock"]["applies"] is False and rows["JW/20"]["clock"]["overdue"] is None
    assert rows["JW/21"]["clock"]["applies"] is True and rows["JW/21"]["clock"]["overdue"] is True
    assert svc.challan_particulars(db, itc.FIRM, draft["id"], consigner=CONSIGNER)["clock"]["applies"] is False
    assert svc.challan_particulars(db, itc.FIRM, issued["id"], consigner=CONSIGNER)["clock"]["applies"] is True


# ── the route ────────────────────────────────────────────────────────────────────────────────────────
USER = {"id": "u1", "firm_id": itc.FIRM, "auth_user_id": "au1", "role": "Partner", "email": "p@example.test"}


@pytest.fixture
def served(db, monkeypatch):
    wire_e2e(monkeypatch, db, [route])
    monkeypatch.setattr(route, "_mock", lambda: False)
    monkeypatch.setattr(route, "_db", lambda: db)
    events = []
    import services.audit_service as audit
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: events.append((a, k)))
    return events


def test_the_route_issues_the_challan_of_the_client_named_and_writes_the_audit_event(db, served):
    c = _draft(db, "JW/22")
    out = route.issue_challan(c["id"], client_id=itc.CLIENT, current_user=USER)
    assert out["success"] is True and out["data"]["status"] == "issued"
    assert _stored(db, c)["status"] == "issued"
    assert len(served) == 1 and served[0][0][1] == "delivery_challan_issue" and served[0][0][2] == c["id"]


def test_the_route_reads_the_client_as_the_consigner(db, served):
    c = _draft(db, "JW/23")
    db.rows("clients")[0].update({"legal_name": None, "trade_name": None, "client_name": None, "address_line1": None, "city": None})
    with pytest.raises(HTTPException) as caught:
        route.issue_challan(c["id"], client_id=itc.CLIENT, current_user=USER)
    assert caught.value.status_code == 422 and "55(1)(ii)" in str(caught.value.detail), "the consigner is the client, read from the client's own record"


def test_the_route_does_not_issue_another_clients_challan_by_naming_a_client_the_caller_may_reach(db, served):
    c = _draft(db, "JW/24")
    with pytest.raises(HTTPException) as caught:
        route.issue_challan(c["id"], client_id=itc.OTHER_CLIENT, current_user=USER)
    assert caught.value.status_code == 404
    assert _stored(db, c)["status"] == "draft" and served == []


def test_the_amendment_route_writes_the_audit_event_with_the_names_of_the_fields(db, served):
    """A cancel or a back day changes what is owed on a return, and the amendment door left no trace of either (the reviewer's point); the names of what was amended are recorded, never a consignee's value."""
    from models.sales_cycle import DeliveryChallanUpdateIn
    c = _draft(db, "JW/25")
    out = route.update_challan(c["id"], DeliveryChallanUpdateIn(notes="booked", consignee_name="Gamma Works"), client_id=itc.CLIENT, current_user=USER)
    assert out["success"] is True
    assert len(served) == 1 and served[0][0][1] == "delivery_challan_update" and served[0][0][2] == c["id"]
    data = served[0][1]["new_data"]
    assert data["fields"] == ["consignee_name", "notes"] and data["status"] == "draft" and "Gamma Works" not in str(served), served


# ── made as the screen makes it, then issued (the blind spot the independent read named: every other test seeds a complete challan) ─────────────────────────────────────
CUSTOMER = "cu000000-0000-0000-0000-0000000000c1"
JOB_WORKER = "ve000000-0000-0000-0000-0000000000a1"


@pytest.fixture
def parties(db):
    db.seed("customers", {"id": CUSTOMER, "firm_id": itc.FIRM, "client_id": itc.CLIENT, "name": "Precision Castings", "gstin": "27AAAAA0000A1Z5",
                          "address": "12 Industrial Estate", "city": "Pune", "state": "Maharashtra", "pincode": "411001"})
    db.seed("vendors", {"id": JOB_WORKER, "firm_id": itc.FIRM, "client_id": itc.CLIENT, "name": "Gamma Works", "gstin": None, "address": "4 Foundry Lane", "city": "Nashik",
                        "state": "Maharashtra", "pincode": None})
    return db


def _as_the_form_sends(**over):
    """What `SalesCycleTab.save` posts for a delivery challan when the person picks the consignee from the list and fills the number, the date and one line."""
    payload = {"client_id": itc.CLIENT, "customer_id": CUSTOMER, "document_no": "DC/26-27/0001", "document_date": "2026-10-01", "reason": dc.REASON_JOB_WORK, "goods_kind": "inputs",
               "consignee_name": None, "consignee_gstin": None, "consignee_address": None, "transporter_name": None, "vehicle_no": None, "is_inter_state": False, "notes": None,
               "lines": [{"description": "Steel bar", "hsn_sac": "7214", "quantity": 100, "unit": "KGS", "rate_paise": 10000, "gst_rate_percent": 18}]}
    payload.update(over)
    return payload


def test_a_challan_made_by_picking_the_customer_carries_the_customers_particulars_and_can_then_be_issued(parties):
    made = svc.create_challan(parties, itc.FIRM, _as_the_form_sends(), "u1")
    assert (made["consignee_name"], made["consignee_gstin"]) == ("Precision Castings", "27AAAAA0000A1Z5")
    assert made["consignee_address"] == "12 Industrial Estate, Pune, Maharashtra, 411001" and made["status"] == "draft"
    issued = svc.issue_challan(parties, itc.FIRM, made["id"], client_id=itc.CLIENT, consigner=CONSIGNER)
    assert issued["status"] == "issued"


def test_a_consignee_that_is_typed_stands_and_nothing_of_the_customer_is_mixed_into_it(parties):
    """A typed branch name beside the head office's GSTIN is a wrong document: if any of the three is typed, the customer is not read."""
    made = svc.create_challan(parties, itc.FIRM, _as_the_form_sends(consignee_name="Precision Castings, Nashik unit"), "u1")
    assert (made["consignee_name"], made["consignee_gstin"], made["consignee_address"]) == ("Precision Castings, Nashik unit", None, None)


def test_a_job_worker_named_as_the_consignee_fills_the_particulars_too(parties):
    made = svc.create_challan(parties, itc.FIRM, _as_the_form_sends(customer_id=None, vendor_id=JOB_WORKER, document_no="DC/26-27/0002"), "u1")
    assert (made["consignee_name"], made["consignee_gstin"], made["consignee_address"]) == ("Gamma Works", None, "4 Foundry Lane, Nashik, Maharashtra")


def test_no_party_and_no_typed_consignee_leaves_the_consignee_blank_and_the_issue_door_names_the_clause(parties):
    made = svc.create_challan(parties, itc.FIRM, _as_the_form_sends(customer_id=None), "u1")
    assert (made["consignee_name"], made["consignee_gstin"], made["consignee_address"]) == (None, None, None)
    with pytest.raises(HTTPException) as caught:
        svc.issue_challan(parties, itc.FIRM, made["id"], client_id=itc.CLIENT, consigner=CONSIGNER)
    assert caught.value.status_code == 422 and "55(1)(iii)" in str(caught.value.detail)


def test_a_challan_made_without_an_hsn_code_or_the_kind_of_goods_is_refused_at_issue_in_words_that_name_it(parties):
    blank_hsn = svc.create_challan(parties, itc.FIRM, _as_the_form_sends(document_no="DC/26-27/0003", lines=[
        {"description": "Steel bar", "hsn_sac": None, "quantity": 100, "unit": "KGS", "rate_paise": 10000, "gst_rate_percent": 18}]), "u1")
    with pytest.raises(HTTPException) as hsn:
        svc.issue_challan(parties, itc.FIRM, blank_hsn["id"], client_id=itc.CLIENT, consigner=CONSIGNER)
    assert hsn.value.status_code == 422 and "55(1)(iv)" in str(hsn.value.detail)
    no_kind = svc.create_challan(parties, itc.FIRM, _as_the_form_sends(document_no="DC/26-27/0004", goods_kind=None), "u1")
    with pytest.raises(HTTPException) as kind:
        svc.issue_challan(parties, itc.FIRM, no_kind["id"], client_id=itc.CLIENT, consigner=CONSIGNER)
    assert kind.value.status_code == 422 and "does not say what is sent" in str(kind.value.detail) and "Add " not in str(kind.value.detail), "a refusal tells the person to do what the screen cannot"
    assert {r["status"] for r in parties.rows("delivery_challans")} == {"draft"}, "a refused issue wrote"


# ── a status is written over the one that was judged (the reviewer's races) ─────────────────────────────────────────────────────────────
def test_an_issue_that_loses_to_another_issue_writes_nothing(db, monkeypatch):
    """The earlier race test flipped the challan to cancelled; two ISSUES are the case the compare-and-set exists for, and a filter that only refuses `cancelled` would let both win."""
    c = _draft(db, "JW/30")
    real = svc.challan_lines
    stamp = _stored(db, c).get("updated_at")

    def lines_then_another_issue_lands(*a, **k):
        out = real(*a, **k)
        _stored(db, c)["status"] = "issued"                       # the other request got in between the read and the write
        return out

    monkeypatch.setattr(svc, "challan_lines", lines_then_another_issue_lands)
    with pytest.raises(HTTPException) as caught:
        _issue(db, c)
    assert caught.value.status_code == 409 and "changed while it was being issued" in str(caught.value.detail)
    assert _stored(db, c).get("updated_at") == stamp, "the second issue wrote over the first"


def test_a_cancel_that_loses_to_an_issue_writes_nothing_and_says_so(db, monkeypatch):
    """The amendment door judged a DRAFT (cancelling it is allowed); an issue got in before the write. Cancelling the challan the goods have now left on is not what was judged."""
    c = _draft(db, "JW/31")
    real = svc._refuse_a_day_that_is_out_of_order

    def judged_then_an_issue_lands(*a, **k):
        real(*a, **k)
        _stored(db, c)["status"] = "issued"

    monkeypatch.setattr(svc, "_refuse_a_day_that_is_out_of_order", judged_then_an_issue_lands)
    with pytest.raises(HTTPException) as caught:
        svc.update_challan(db, itc.FIRM, c["id"], {"status": "cancelled"})
    assert caught.value.status_code == 409 and "changed while it was being amended" in str(caught.value.detail)
    assert _stored(db, c)["status"] == "issued", "a cancel judged on a draft was written over an issued challan"


def test_an_amendment_that_changes_no_status_is_not_held_to_the_status(db, monkeypatch):
    """A note or a transporter is a correction to what the document says; it does not fail because the status moved while it was typed."""
    c = _draft(db, "JW/32")
    real = svc._refuse_a_day_that_is_out_of_order

    def judged_then_an_issue_lands(*a, **k):
        real(*a, **k)
        _stored(db, c)["status"] = "issued"

    monkeypatch.setattr(svc, "_refuse_a_day_that_is_out_of_order", judged_then_an_issue_lands)
    svc.update_challan(db, itc.FIRM, c["id"], {"notes": "booked"})
    assert _stored(db, c)["notes"] == "booked" and _stored(db, c)["status"] == "issued"


def test_the_goods_back_stamp_is_not_written_over_a_challan_that_is_no_longer_issued(db, monkeypatch):
    """The lot door asked for `issued` before it recorded the lot; a cancel got in since. The stamp matches nothing, says the lot stands, and the cancel is not written over with received back."""
    c = _draft(db, "JW/33")
    _issue(db, c)
    issued_row = dict(_stored(db, c))
    _stored(db, c)["status"] = "cancelled"
    monkeypatch.setattr(svc, "_one", lambda *a, **k: issued_row)       # the read that was made before the cancel landed
    with pytest.raises(HTTPException) as caught:
        svc.record_goods_back(db, itc.FIRM, c["id"], "2026-10-01")
    assert caught.value.status_code == 409 and "What was recorded stands" in str(caught.value.detail)
    assert _stored(db, c)["status"] == "cancelled" and not _stored(db, c).get("received_back_on")


# ── the second independent read ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_consignee_typed_as_spaces_is_a_blank_and_nothing_is_mixed_into_what_is_typed(parties):
    """The screen sends `form.consignee_name || null`, so a space typed in a box is sent. It is a blank: the party is copied whole, and it is never stored beside the party's GSTIN and address."""
    made = svc.create_challan(parties, itc.FIRM, _as_the_form_sends(consignee_name="   ", consignee_gstin=" ", document_no="DC/26-27/0010"), "u1")
    assert (made["consignee_name"], made["consignee_gstin"], made["consignee_address"]) == ("Precision Castings", "27AAAAA0000A1Z5", "12 Industrial Estate, Pune, Maharashtra, 411001")
    typed = svc.create_challan(parties, itc.FIRM, _as_the_form_sends(consignee_name="  Branch Unit  ", document_no="DC/26-27/0011"), "u1")
    assert (typed["consignee_name"], typed["consignee_gstin"], typed["consignee_address"]) == ("Branch Unit", None, None), "a typed name is stored as typed, trimmed, and the party is not read"


def test_an_inter_state_challan_is_issued_with_the_place_of_supply_the_form_sends_and_refused_in_words_without_it(parties):
    """Rule 55(1)(viii) asks for the place of supply of an inter-State movement. The form has the box now (it had only the tick, so every inter-State challan made on the screen stayed a draft)."""
    with_place = svc.create_challan(parties, itc.FIRM, _as_the_form_sends(is_inter_state=True, place_of_supply="29", document_no="DC/26-27/0012"), "u1")
    assert with_place["place_of_supply"] == "29"
    assert svc.issue_challan(parties, itc.FIRM, with_place["id"], client_id=itc.CLIENT, consigner=CONSIGNER)["status"] == "issued"
    without = svc.create_challan(parties, itc.FIRM, _as_the_form_sends(is_inter_state=True, place_of_supply=None, document_no="DC/26-27/0013"), "u1")
    with pytest.raises(HTTPException) as caught:
        svc.issue_challan(parties, itc.FIRM, without["id"], client_id=itc.CLIENT, consigner=CONSIGNER)
    assert caught.value.status_code == 422 and "55(1)(viii)" in str(caught.value.detail)


# what an issued challan keeps. These patches go to the SERVICE as a dict: the request model reads "" as 'not sent' for the kind of goods, the place of supply and the GSTIN, so the last two rows
# are reached by a direct caller of the service and not by the route (`test_a_blank_kind_place_or_gstin_sent_to_the_amendment_route_is_no_change_…` holds that half).
@pytest.mark.parametrize("patch,words", [
    ({"consignee_name": "", "consignee_gstin": "", "consignee_address": ""}, "keeps a consignee"),
    ({"document_date": "2027-01-01"}, "which has not come"),
    ({"is_inter_state": True, "place_of_supply": ""}, "keeps a place of supply"),
    ({"goods_kind": ""}, "keeps what is sent"),
])
def test_an_issued_challan_is_not_amended_into_what_issuing_would_have_refused(db, patch, words):
    c = _draft(db, "JW/40")
    _issue(db, c)
    before = dict(_stored(db, c))
    with pytest.raises(HTTPException) as caught:
        _amend(db, c, patch)
    assert caught.value.status_code == 422 and words in str(caught.value.detail), caught.value.detail
    assert _stored(db, c) == before, "the refused amendment wrote"


def test_a_draft_may_be_amended_into_anything_and_an_issued_challan_may_still_be_corrected_in_what_issuing_does_not_ask(db):
    draft = _draft(db, "JW/41")
    assert _amend(db, draft, {"consignee_name": "", "consignee_gstin": "", "consignee_address": ""})["consignee_name"] == ""   # a draft is a draft
    issued = _draft(db, "JW/42")
    _issue(db, issued)
    assert _amend(db, issued, {"consignee_name": "Gamma Works"})["consignee_name"] == "Gamma Works"
    assert _amend(db, issued, {"document_date": "2026-05-20"})["document_date"] == "2026-05-20", "a date moved to a day that has come is still a correction (POST-A-383 judges it against the lots)"
    assert _amend(db, issued, {"goods_kind": dc.GOODS_KIND_CAPITAL_GOODS})["goods_kind"] == dc.GOODS_KIND_CAPITAL_GOODS
    assert _amend(db, issued, {"notes": "booked", "vehicle_no": "MH12AB1234", "extended_to": "2027-12-31"})["notes"] == "booked"


def test_an_edit_of_something_else_does_not_make_an_issued_row_stored_before_this_rule_unsaveable(db):
    c = _draft(db, "JW/43")
    _issue(db, c)
    _stored(db, c).update({"consignee_name": None, "consignee_gstin": None, "consignee_address": None})   # a row from before the rule
    assert _amend(db, c, {"notes": "still saves"})["notes"] == "still saves"


def test_the_pure_rule_of_what_an_issued_challan_keeps_asks_only_what_the_patch_touches():
    row = {"document_date": "2027-01-01", "consignee_name": "", "consignee_gstin": None, "consignee_address": " ", "is_inter_state": True, "place_of_supply": None,
           "reason": dc.REASON_JOB_WORK, "goods_kind": None}
    today = date(2026, 10, 9)
    ask = lambda *touched: dc.issued_challan_problem("X/1", row=row, today=today, touched=set(touched))        # noqa: E731
    assert ask("notes") is None and ask() is None, "an untouched row is not judged"
    assert "has not come" in ask("document_date") and "keeps a consignee" in ask("consignee_address") and "keeps a consignee" in ask("consignee_name", "consignee_gstin")
    assert "place of supply" in ask("is_inter_state") and "place of supply" in ask("place_of_supply") and "keeps what is sent" in ask("goods_kind")
    row_ok = {**row, "document_date": "2026-10-09", "consignee_name": "A", "place_of_supply": "27", "goods_kind": "inputs"}
    assert dc.issued_challan_problem("X/1", row=row_ok, today=today, touched={"document_date", "consignee_name", "place_of_supply", "goods_kind"}) is None
    assert dc.issued_challan_problem("X/1", row={**row_ok, "reason": dc.REASON_NOT_A_SUPPLY, "goods_kind": None}, today=today, touched={"goods_kind"}) is None, "only job work carries a kind"
    for field in ("document_date", "consignee_name", "place_of_supply", "goods_kind"):
        assert "has been issued" in ask(field), f"the sentence for {field} says 'is issued' of a challan the goods have left on, which may be received back"


def test_a_blank_kind_place_or_gstin_sent_to_the_amendment_route_is_no_change_so_it_cannot_blank_an_issued_challan(db, served):
    """The request model reads "" as 'not sent' for the kind of goods, the place of supply and the consignee's GSTIN, so the route can NEVER blank them: the `issued_challan_problem` rules for
    those two fields are reached by a direct caller of the service (the parametrised test above) and by nothing the browser can send."""
    from models.sales_cycle import DeliveryChallanUpdateIn
    patch = DeliveryChallanUpdateIn(goods_kind="", place_of_supply="", consignee_gstin="")
    assert (patch.goods_kind, patch.place_of_supply, patch.consignee_gstin) == (None, None, None)
    c = _draft(db, "JW/48", is_inter_state=True)
    _issue(db, c)
    kept = {k: _stored(db, c)[k] for k in ("goods_kind", "place_of_supply", "consignee_gstin", "is_inter_state")}
    assert kept["goods_kind"] == "inputs" and kept["place_of_supply"] == "29" and kept["consignee_gstin"] and kept["is_inter_state"] is True
    out = route.update_challan(c["id"], DeliveryChallanUpdateIn(goods_kind="", place_of_supply="", consignee_gstin="", notes="kept"), client_id=itc.CLIENT, current_user=USER)
    assert out["success"] is True
    assert {k: _stored(db, c)[k] for k in kept} == kept, "a blank sent through the route blanked a field of an issued challan"
    assert _stored(db, c)["notes"] == "kept"


def test_a_received_back_challan_keeps_what_issuing_asked_as_an_issued_one_does(db):
    """The goods have LEFT on a received-back challan too (`GOODS_HAVE_LEFT`), so the rules about what a challan keeps are asked of it, and the sentence is true of it ('has been issued')."""
    c = _draft(db, "JW/49")
    _issue(db, c)
    svc.record_goods_back(db, itc.FIRM, c["id"], "2026-09-01")
    assert _stored(db, c)["status"] == "received_back"
    before = dict(_stored(db, c))
    with pytest.raises(HTTPException) as caught:
        _amend(db, c, {"consignee_name": "", "consignee_gstin": "", "consignee_address": ""})
    assert caught.value.status_code == 422 and "has been issued, so it keeps a consignee" in str(caught.value.detail), caught.value.detail
    assert _stored(db, c) == before, "the refused amendment wrote"
    assert _amend(db, c, {"notes": "collected"})["notes"] == "collected", "an edit of something else is not made to answer for the rule"


def test_a_cancel_that_blanks_the_consignee_in_the_same_patch_is_allowed_because_a_cancelled_challan_has_no_goods_out(db):
    c = _draft(db, "JW/50")
    _issue(db, c)
    out = _amend(db, c, {"status": "cancelled", "consignee_name": "", "consignee_gstin": "", "consignee_address": ""})
    assert out["status"] == "cancelled" and out["consignee_name"] == ""


def test_the_lot_lookup_that_stops_a_cancel_is_the_clients_own(db):
    c = _draft(db, "JW/51")
    _issue(db, c)
    line = next(r for r in db.rows("delivery_challan_lines") if r["challan_id"] == c["id"])
    # a lot row under ANOTHER client that happens to name this challan's id (it cannot be written by the product, and a read that asked the firm alone would count it)
    db.seed("delivery_challan_returns", {"firm_id": itc.FIRM, "client_id": itc.OTHER_CLIENT, "challan_id": c["id"], "challan_line_id": line["id"], "returned_on": "2026-08-20",
                                         "quantity_returned": "1", "quantity_lost_or_wasted": "0"})
    assert svc._latest_lot_recorded_on(db, itc.FIRM, itc.CLIENT, c["id"]) is None
    assert svc._latest_lot_recorded_on(db, itc.FIRM, itc.OTHER_CLIENT, c["id"]) == date(2026, 8, 20)
    assert _amend(db, c, {"status": "cancelled"})["status"] == "cancelled", "another client's lot stopped this client's cancel"


def test_the_party_a_challan_copies_its_consignee_from_is_the_clients_own(parties):
    other = parties.seed("customers", {"id": "cu000000-0000-0000-0000-0000000000c2", "firm_id": itc.FIRM, "client_id": itc.OTHER_CLIENT, "name": "Someone Else's Customer",
                                       "gstin": "27AAAAA0000A1Z5", "address": "9 Other Road", "city": "Pune", "state": "Maharashtra", "pincode": "411002"})
    nothing = {"name": None, "gstin": None, "address": None}
    assert svc._consignee_of_party(parties, itc.FIRM, itc.CLIENT, other["id"], None) == nothing, "this client's challan read another client's customer"
    assert svc._consignee_of_party(parties, itc.FIRM, itc.OTHER_CLIENT, other["id"], None)["name"] == "Someone Else's Customer"
    other_vendor = parties.seed("vendors", {"id": "ve000000-0000-0000-0000-0000000000b2", "firm_id": itc.FIRM, "client_id": itc.OTHER_CLIENT, "name": "Someone Else's Job Worker",
                                            "address": "1 Lane"})
    assert svc._consignee_of_party(parties, itc.FIRM, itc.CLIENT, None, other_vendor["id"]) == nothing, "this client's challan read another client's job worker"


def test_the_statuses_that_list_a_job_work_challan_on_itc_04_are_the_ones_the_goods_have_left_on():
    from domain.gst import itc_04
    assert tuple(itc_04.SENT_STATUSES) == tuple(dc.GOODS_HAVE_LEFT), "FORM GST ITC-04 lists a job-work challan in a different set of statuses from the one that draws a period and counts as delivered"


def test_the_amendment_audit_event_records_the_fields_that_decide_a_period_as_they_were_and_are(db, served):
    from models.sales_cycle import DeliveryChallanUpdateIn
    c = _draft(db, "JW/44")
    _issue(db, c)
    served.clear()
    route.update_challan(c["id"], DeliveryChallanUpdateIn(goods_kind=dc.GOODS_KIND_CAPITAL_GOODS, consignee_name="Gamma Works"), client_id=itc.CLIENT, current_user=USER)
    kwargs = served[0][1]
    assert kwargs["old_data"] == {"status": "issued", "document_date": "2026-06-01", "received_back_on": None, "goods_kind": "inputs", "extended_to": None, "place_of_supply": "29"}
    assert kwargs["new_data"]["goods_kind"] == "capital_goods" and kwargs["new_data"]["fields"] == ["consignee_name", "goods_kind"] and "Gamma Works" not in str(served)


# a lot of waste alone is a lot
def test_a_lot_recorded_only_as_lost_or_wasted_stops_a_cancel_as_a_returned_lot_does(db):
    c = _draft(db, "JW/45")
    _issue(db, c)
    line = next(r for r in db.rows("delivery_challan_lines") if r["challan_id"] == c["id"])
    itc._came_back(db, c, line, "0", "2026-08-20", wasted="10")
    with pytest.raises(HTTPException) as caught:
        _amend(db, c, {"status": "cancelled"})
    assert caught.value.status_code == 409 and "has a lot recorded against it on 2026-08-20" in str(caught.value.detail) and "lost or wasted" in str(caught.value.detail)
    assert _stored(db, c)["status"] == "issued", "a challan with a lot of waste was cancelled and its balance dropped out of FORM GST ITC-04"
    listed, _ = _on_the_statement(db)
    assert listed == ["JW/45"]


def test_a_challan_with_no_lot_is_cancelled(db):
    c = _draft(db, "JW/46")
    _issue(db, c)
    assert _amend(db, c, {"status": "cancelled"})["status"] == "cancelled"


# the status table decides
def test_the_table_of_what_an_amendment_may_make_is_what_decides_for_every_pair():
    statuses = list(dc.AMENDMENT_MAY_MAKE)
    for cur in statuses:
        for want in statuses:
            allowed = cur == want or want in dc.AMENDMENT_MAY_MAKE[cur]
            assert (dc.status_change_problem("X/1", cur, want) is None) is allowed, (cur, want)


def test_a_row_of_the_table_that_is_changed_changes_the_answer(monkeypatch):
    assert dc.status_change_problem("X/1", "received_back", "cancelled")
    monkeypatch.setitem(dc.AMENDMENT_MAY_MAKE, "received_back", (dc.STATUS_CANCELLED,))
    assert dc.status_change_problem("X/1", "received_back", "cancelled") is None, "the table is read by the rule it states"


# the goods-back stamp
def test_the_goods_back_stamp_does_not_write_a_second_day_over_a_challan_that_is_already_received_back(db):
    c = _draft(db, "JW/47")
    _issue(db, c)
    svc.record_goods_back(db, itc.FIRM, c["id"], "2026-09-01")
    with pytest.raises(HTTPException) as caught:
        svc.record_goods_back(db, itc.FIRM, c["id"], "2026-09-15")
    assert caught.value.status_code == 409 and "by another request" in str(caught.value.detail)
    assert _stored(db, c)["received_back_on"] == "2026-09-01" and _stored(db, c)["status"] == "received_back"
