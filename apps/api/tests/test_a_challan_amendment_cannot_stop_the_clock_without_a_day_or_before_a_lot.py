"""The challan amendment door cannot stop the section 143 clock without naming a day, cannot do it on a cancelled challan, cannot leave a back day beside a status that says the goods have
not come back, and cannot give the whole challan a back day earlier than goods already returned (POST-A-383).

WHAT WAS WRONG
    `sales_cycle_service.update_challan` wrote `status: "received_back"` as it was sent. The status alone stops the s.143 job-work clock (`itc_04.balances` skips a challan in it), so one
    hand-made amendment stopped it for goods that never came back and named no day. (The challan LIST draws its clock from the day alone, so a status-only row shows as running there
    while ITC-04 skips it: the two readers disagreed, and a row written that way before this rule is still offered a day by the screen's "Mark a whole challan back at once".) The door also
    stamped a back day on a CANCELLED challan, which the FORM GST ITC-04 door refuses (409, "goods can only come back on a challan that has been issued"), and took a whole-challan back day
    earlier than goods already returned on ITC-04: the whole challan's day is the day its LAST goods came back, so it cannot be before any lot of goods returned. (The seventeenth slice
    made the day itself honest and compared the day the goods WENT OUT with the days recorded as back; this is the other end of the pair.)

WHAT IS HELD
    * the status "received back" is refused without a day, in the patch or already on the row (422, one sentence in the domain); for a JOB-WORK challan the sentence also names the
      lot-by-lot route, and for any other reason it does not, because the lot door refuses every reason but job work;
    * a patch that stops the clock on a CANCELLED challan, or leaves one cancelled with a back day, is refused (409) in the sentence the ITC-04 lot door says, which is ONE function
      (`delivery_challan.not_issued_sentence`). It is judged on the status the patch LEAVES and not only on the one stored, so `{"status": "cancelled", "received_back_on": D}` is
      refused too, and it is asked before the missing day (the unfixable refusal first);
    * a challan with a back day IS received back: a patch that leaves the day beside another status (`issued`, `draft`, `cancelled`) is refused (422), whether the day is in the patch
      or on the row, so the two-step route (`received_back_on`, then `status: "cancelled"`) is closed as well;
    * a whole-challan back day earlier than the latest lot of goods RETURNED against THIS challan (not another challan's, not another client's) is refused (422); the same day is
      allowed; a row that records only quantity lost or wasted is not goods returned and is not counted (migration 462: whether scrap counts as received back is not a judgement this
      product takes);
    * the day the goods went out is not amended once a challan is issued (POST-A-416), so it is no longer compared with the days already recorded as back;
    * a DRAFT is not refused, and that is a premise, not a preference: no SCREEN issues a challan (see the last tests; the amendment door accepts `issued` from a hand-made request,
      and the tests say so), so a draft is the state every challan made in the product is in and the whole-challan "Record goods back" is the one door that can end its clock. The
      premise is a test over the whole API tree, the migrations and the front end, and it fails when a door that issues a challan appears.
"""
from __future__ import annotations

import ast
import re
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).parent))

import services.itc_04_service
import services.sales_cycle_service as svc
import test_itc_04_is_derived_from_the_challans_already_entered as itc
from domain.gst import delivery_challan as dc
from tests.e2e_harness import FakeDB

INDIA_TODAY = date(2026, 10, 9)
API = Path(__file__).resolve().parent.parent
WEB = API.parent / "web"


@pytest.fixture(autouse=True)
def _india_today_is_fixed(monkeypatch):
    monkeypatch.setattr(svc, "ist_today", lambda: INDIA_TODAY)
    monkeypatch.setattr(services.itc_04_service, "ist_today", lambda: INDIA_TODAY)


@pytest.fixture
def db():
    x = FakeDB()
    x.seed("clients", {"id": itc.CLIENT, "firm_id": itc.FIRM, "client_name": "Mfg Co"})
    x.seed("clients", {"id": itc.OTHER_CLIENT, "firm_id": itc.FIRM, "client_name": "Other Co"})
    return x


def _amend(db, challan, patch):
    return svc.update_challan(db, itc.FIRM, challan["id"], patch)


def _stored(db, challan):
    return next(r for r in db.rows("delivery_challans") if r["id"] == challan["id"])


def _refused(db, challan, patch, code):
    with pytest.raises(HTTPException) as caught:
        _amend(db, challan, patch)
    assert caught.value.status_code == code, (patch, caught.value.status_code, caught.value.detail)
    return caught.value.detail


# ── the status alone ────────────────────────────────────────────────────────────────────────────────────────

def test_the_status_received_back_is_refused_without_a_day_and_nothing_is_written(db):
    c = itc._challan(db, "JW/1", "2026-06-01")
    detail = _refused(db, c, {"status": "received_back"}, 422)
    assert detail == dc.whole_challan_back_needs_a_day("job_work")
    assert "FORM GST ITC-04" in detail, "a job-work challan is told where else the goods can be recorded back"
    stored = _stored(db, c)
    assert stored["status"] == "issued" and not stored.get("received_back_on"), f"a refused amendment wrote: {stored}"


def test_a_challan_that_is_not_job_work_is_not_sent_to_a_door_that_refuses_it(db):
    """The lot door refuses every reason but job work (422, "Only goods sent for JOB WORK are returned on ITC-04"), so the advice must not name it."""
    c = itc._challan(db, "SA/1", "2026-06-01", reason=dc.REASON_ON_APPROVAL, goods_kind=None)
    detail = _refused(db, c, {"status": "received_back"}, 422)
    assert detail == dc.whole_challan_back_needs_a_day(dc.REASON_ON_APPROVAL)
    assert "ITC-04" not in detail and "lot" not in detail, f"the sentence points a sale-on-approval challan at a door that refuses it: {detail}"
    assert detail.startswith("A challan is marked received back with the day the goods came back. Give the day")


def test_the_status_received_back_is_taken_with_a_day_in_the_same_patch_or_one_already_on_the_row(db):
    c = itc._challan(db, "JW/2", "2026-06-01")
    out = _amend(db, c, {"status": "received_back", "received_back_on": "2026-06-20"})
    assert out["status"] == "received_back" and out["received_back_on"] == "2026-06-20"
    # Already back, with its day on the row: saying so again names a day that is there, so it is not refused.
    again = _amend(db, c, {"status": "received_back"})
    assert again["status"] == "received_back"
    # A day alone has always set the status, and still does.
    d = itc._challan(db, "JW/3", "2026-06-01")
    assert _amend(db, d, {"received_back_on": "2026-06-21"})["status"] == "received_back"


def test_an_amendment_that_does_not_stop_the_clock_is_unaffected(db):
    c = itc._challan(db, "JW/4", "2026-06-01")
    assert _amend(db, c, {"notes": "Collected by the transporter"})["notes"] == "Collected by the transporter"
    assert _amend(db, c, {"status": "issued"})["status"] == "issued", "the other statuses are not this rule's when there is no back day"
    draft = itc._challan(db, "JW/4D", "2026-06-01", status="draft")
    assert _amend(db, draft, {"notes": "n"})["notes"] == "n"


# ── a cancelled challan has no goods to come back ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("patch", [{"received_back_on": "2026-06-20"}, {"status": "received_back", "received_back_on": "2026-06-20"}])
def test_a_back_day_or_the_status_on_a_cancelled_challan_is_refused_in_the_lot_doors_sentence(db, patch):
    c = itc._challan(db, "JW/5", "2026-06-01", status="cancelled")
    detail = _refused(db, c, patch, 409)
    assert detail == "Challan JW/5 is cancelled: goods can only come back on a challan that has been issued."
    assert not _stored(db, c).get("received_back_on"), "a refused amendment wrote a day"
    # The ITC-04 lot door says the same words for the same challan.
    ln = itc._line(db, c, qty="10")
    with pytest.raises(HTTPException) as lot:
        services.itc_04_service.record_return(db, itc.FIRM, itc.CLIENT, c["id"], itc._payload(ln, returned_on="2026-06-20"), "u1")
    assert lot.value.status_code == 409 and lot.value.detail == detail, "the two doors no longer say one sentence"


def test_the_unfixable_refusal_comes_first_a_status_alone_on_a_cancelled_challan_is_the_409_not_an_ask_for_a_day(db):
    c = itc._challan(db, "JW/5A", "2026-06-01", status="cancelled")
    detail = _refused(db, c, {"status": "received_back"}, 409)
    assert "cancelled" in detail, "a challan that cannot come back at all was asked for a day it could not use"


def test_a_patch_that_cancels_the_challan_and_stops_its_clock_in_one_request_is_refused(db):
    """The refusal is judged on the status the patch LEAVES: cancelling and giving a back day in one request ends cancelled with a day."""
    c = itc._challan(db, "JW/5B", "2026-06-01")
    detail = _refused(db, c, {"status": "cancelled", "received_back_on": "2026-06-20"}, 409)
    assert detail == dc.not_issued_sentence("JW/5B", "cancelled")
    stored = _stored(db, c)
    assert stored["status"] == "issued" and not stored.get("received_back_on"), f"a refused amendment wrote: {stored}"


def test_the_two_step_route_to_a_cancelled_challan_with_a_back_day_is_closed(db):
    """Step one is an ordinary amendment; step two would end cancelled with the day from step one. A challan with a back day IS received back."""
    c = itc._challan(db, "JW/5C", "2026-06-01")
    assert _amend(db, c, {"received_back_on": "2026-06-20"})["status"] == "received_back"
    detail = _refused(db, c, {"status": "cancelled"}, 422)
    assert detail == dc.a_back_day_needs_a_status_that_says_so_problem("JW/5C", "2026-06-20", "cancelled")
    assert _stored(db, c)["status"] == "received_back"


@pytest.mark.parametrize("status", ["issued", "draft"])
def test_a_back_day_is_not_left_beside_a_status_that_says_the_goods_have_not_come_back(db, status):
    fresh = itc._challan(db, f"JW/5D-{status}", "2026-06-01")
    detail = _refused(db, fresh, {"status": status, "received_back_on": "2026-06-20"}, 422)
    assert detail == dc.a_back_day_needs_a_status_that_says_so_problem(f"JW/5D-{status}", "2026-06-20", status)
    stored = _stored(db, fresh)
    assert stored["status"] == "issued" and not stored.get("received_back_on"), f"a refused amendment wrote: {stored}"
    # ...and a challan that is already back cannot be re-marked as one that is not, by the status alone.
    back = itc._challan(db, f"JW/5E-{status}", "2026-06-01", status="received_back", received_back_on="2026-06-20")
    _refused(db, back, {"status": status}, 422)
    assert _stored(db, back)["status"] == "received_back"


def test_an_edit_of_something_else_on_a_cancelled_challan_or_a_received_back_one_is_not_refused(db):
    c = itc._challan(db, "JW/6", "2026-06-01", status="cancelled")
    assert _amend(db, c, {"notes": "Cancelled: wrong job worker"})["notes"] == "Cancelled: wrong job worker"
    back = itc._challan(db, "JW/6B", "2026-06-01", status="received_back", received_back_on="2026-06-20")
    assert _amend(db, back, {"notes": "Collected"})["notes"] == "Collected", "an unrelated edit of a row that is back is not made to answer for the rule"
    legacy = itc._challan(db, "JW/6C", "2026-06-01", status="received_back")
    assert _amend(db, legacy, {"notes": "Legacy row: the status without a day"})["notes"].startswith("Legacy row"), "a row stored from before the rule stays editable"


def test_the_sentence_is_one_function_in_the_domain():
    assert dc.not_issued_sentence("JW/9", "draft") == "Challan JW/9 is a draft: goods can only come back on a challan that has been issued."
    source = (API / "services" / "itc_04_service.py").read_text(encoding="utf-8")
    assert "dc.not_issued_sentence(" in source and "can only come back on a challan that has been issued" not in source, "the lot door spells the sentence itself again"
    assert "can only come back on a challan that has been issued" not in (API / "services" / "sales_cycle_service.py").read_text(encoding="utf-8")


def test_a_sentence_says_a_status_in_english_and_never_as_the_stored_word():
    """A person reads "Challan X is a draft", "is received back" and "cannot become a draft": the stored words (`received_back`, a bare `draft` after "is") are not printed."""
    assert dc.status_word("received_back") == "received back" and dc.status_word("draft") == "draft"
    assert dc.status_is("draft") == "a draft" and dc.status_is("received_back") == "received back" and dc.status_is("issued") == "issued"
    assert dc.status_word("something_new") == "something_new", "a status this module does not hold is said as stored, not hidden"
    sentences = []
    for cur in dc.AMENDMENT_MAY_MAKE:
        sentences.append(dc.only_a_draft_is_issued_sentence("X/1", cur))
        sentences.append(dc.not_issued_sentence("X/1", cur))
        sentences.append(dc.a_back_day_needs_a_status_that_says_so_problem("X/1", "2026-06-20", cur))
        for want in dc.AMENDMENT_MAY_MAKE:
            problem = dc.status_change_problem("X/1", cur, want)
            if problem:
                sentences.append(problem)
    assert len(sentences) >= 16, "the grid of statuses was not walked"
    for text in sentences:
        assert "received_back" not in text, f"a stored status word is printed: {text}"
        assert " is draft" not in text and "become draft" not in text and "marked a draft" not in text, f"a status is said in the wrong English: {text}"
    assert dc.status_change_problem("X/1", "received_back", "draft") == "Challan X/1 is received back: its goods are back, so it cannot become a draft."
    assert dc.status_change_problem("X/1", "issued", "draft") == "Challan X/1 is issued: a challan is not made a draft again."
    assert dc.only_a_draft_is_issued_sentence("X/1", "received_back") == "Challan X/1 is received back: only a draft is issued."
    assert dc.a_back_day_needs_a_status_that_says_so_problem("X/1", "2026-06-20", "draft") == (
        "Challan X/1 has its goods back on 2026-06-20, so it is received back and cannot be marked draft.")


# ── the whole challan's day is not before goods returned ───────────────────────────────────────────────────

def test_a_whole_challan_back_day_before_a_lot_already_recorded_is_refused_and_the_same_day_is_allowed(db):
    c = itc._challan(db, "JW/7", "2026-06-01")
    ln = itc._line(db, c, qty="10")
    itc._came_back(db, c, ln, "4", "2026-06-10")
    itc._came_back(db, c, ln, "3", "2026-06-25")
    detail = _refused(db, c, {"received_back_on": "2026-06-20"}, 422)
    assert detail == dc.whole_challan_back_before_a_lot_problem("JW/7", date(2026, 6, 20), date(2026, 6, 25))
    assert "2026-06-25" in detail and "2026-06-20" in detail and "FORM GST ITC-04" in detail
    assert not _stored(db, c).get("received_back_on"), "a refused amendment wrote a day"
    assert _amend(db, c, {"received_back_on": "2026-06-25"})["received_back_on"] == "2026-06-25", "the day of the latest lot is allowed"
    later = itc._challan(db, "JW/8", "2026-06-01")
    later_line = itc._line(db, later, qty="10")
    itc._came_back(db, later, later_line, "4", "2026-06-10")
    assert _amend(db, later, {"received_back_on": "2026-07-02"})["received_back_on"] == "2026-07-02", "a later day is allowed"


def test_a_lot_that_records_only_scrap_is_not_goods_returned(db):
    """Migration 462 allows a row with nothing returned and some quantity lost or wasted, and says whether scrap counts as received back for s.143 is not a judgement this product
    takes. So the refusal does not take it either: it asks the day of the latest lot of goods RETURNED, and the sentence says 'returned'."""
    c = itc._challan(db, "JW/W1", "2026-06-01")
    ln = itc._line(db, c, qty="10")
    itc._came_back(db, c, ln, "8", "2026-06-10")
    itc._came_back(db, c, ln, "0", "2026-06-25", wasted="2")
    assert _amend(db, c, {"received_back_on": "2026-06-10"})["received_back_on"] == "2026-06-10", "a scrap-only row pushed the CA to a later, wrong day"
    again = itc._challan(db, "JW/W2", "2026-06-01")
    again_line = itc._line(db, again, qty="10")
    itc._came_back(db, again, again_line, "8", "2026-06-10")
    itc._came_back(db, again, again_line, "0", "2026-06-25", wasted="2")
    detail = _refused(db, again, {"received_back_on": "2026-06-05"}, 422)
    assert "returned on 2026-06-10" in detail and "2026-06-25" not in detail, detail


def test_another_challans_lot_and_another_clients_do_not_count(db):
    c = itc._challan(db, "JW/10", "2026-06-01")
    other = itc._challan(db, "JW/11", "2026-06-01")
    other_ln = itc._line(db, other, qty="10")
    itc._came_back(db, other, other_ln, "4", "2026-08-30")
    strange = itc._challan(db, "JW/12", "2026-06-01", client=itc.OTHER_CLIENT)
    strange_ln = itc._line(db, strange, qty="10")
    itc._came_back(db, strange, strange_ln, "4", "2026-09-01")
    # A lot recorded against the same challan id under another client is not this client's row either.
    db.seed("delivery_challan_returns", {"firm_id": itc.FIRM, "client_id": itc.OTHER_CLIENT, "challan_id": c["id"], "challan_line_id": "x", "returned_on": "2026-09-15",
                                         "quantity_returned": "1", "quantity_lost_or_wasted": "0"})
    assert _amend(db, c, {"received_back_on": "2026-06-05"})["received_back_on"] == "2026-06-05"


def test_the_pure_rule_asks_only_the_order_of_the_two_days():
    assert dc.whole_challan_back_before_a_lot_problem("JW/1", date(2026, 6, 25), date(2026, 6, 25)) is None
    assert dc.whole_challan_back_before_a_lot_problem("JW/1", date(2026, 6, 26), date(2026, 6, 25)) is None
    assert dc.whole_challan_back_before_a_lot_problem("JW/1", date(2026, 6, 1), None) is None, "no lot recorded, nothing to be before"
    assert dc.whole_challan_back_before_a_lot_problem("JW/1", date(2026, 6, 24), date(2026, 6, 25)) is not None


def test_the_last_lot_stamps_a_day_that_this_rule_allows(db):
    """The ITC-04 door stamps the LARGEST lot day when every line is back, so the two doors cannot disagree about a challan the lots finished."""
    c = itc._challan(db, "JW/13", "2026-06-01")
    ln = itc._line(db, c, qty="10")
    itc._came_back(db, c, ln, "6", "2026-06-10")
    out = itc._record(db, c, ln, returned_on="2026-06-05", quantity_returned=4.0)
    assert out["challan_marked_received_back"] is True
    stamped = _stored(db, c)["received_back_on"]
    assert stamped == "2026-06-10", "the stamp is the latest lot's day, whatever order the lots were keyed in"
    assert _amend(db, c, {"received_back_on": stamped})["received_back_on"] == stamped


# ── the day the goods went out, amended together with the day they came back ─────────────────────────────────

def test_the_day_they_went_out_is_not_amended_so_a_lot_is_never_left_before_it(db):
    """POST-A-416: the day an issued challan went out is closed, so the pair (the day they went out, a lot) cannot be left the wrong way round by moving it. This was compared with the lots
    before; it is refused before any comparison, alone or beside a back day, and nothing is written."""
    c = itc._challan(db, "JW/14", "2026-06-01")
    ln = itc._line(db, c, qty="10")
    itc._came_back(db, c, ln, "4", "2026-06-10")
    before = dict(_stored(db, c))
    for patch in ({"document_date": "2026-06-20"},
                  {"document_date": "2026-06-20", "received_back_on": "2026-06-25"},
                  {"document_date": "2026-06-10", "received_back_on": "2026-06-25"}):
        assert "so its date cannot be changed" in _refused(db, c, patch, 409), patch
    assert _stored(db, c) == before, "a refused amendment wrote"
    # the date it already holds, beside a back day, is no change, and the back day is judged as it always was
    assert _amend(db, c, {"document_date": "2026-06-01", "received_back_on": "2026-06-25"})["received_back_on"] == "2026-06-25"


# ── the one door that issues a challan (POST-A-398) ───────────────────────────────────────────────────────
#
# Until POST-A-398 "no SCREEN issues a challan" is what let a draft be left alone: the product made a challan as a draft and had no button that issued it, so a draft was the state every
# challan made in the product stayed in. There is now ONE door that issues (`sales_cycle_service.issue_challan`), a draft is refused a back day, and the tests below read the WHOLE API tree
# (recursively, in any quote style, through a handle variable too), the migrations and the whole front end, and fail when a SECOND door that writes a challan's status appears.

_API_SKIP = {"tests", "scripts", "migrations", "__pycache__", ".venv", "venv", "node_modules"}
#: The only functions that write the table, and the verb each is allowed.
_WRITERS = {("services/sales_cycle_service.py", "_write_an_amendment"): {"update"}, ("services/sales_cycle_service.py", "issue_challan"): {"update"}}
#: The three database functions of migration 585 (POST-A-419) and the one module that may call them (`tests/test_the_challan_writes_go_through_the_database_functions.py` holds the rest): they write a
#: challan's header and lines, a job-work lot with its stamp, and a draft's corrections, each in one transaction, and none of them writes the status `issued` (the migration's own tests say so), so the
#: service holds no insert of the table and no stamp of the lot door's own. Any other module naming a function with "challan" in it is a second door.
_CHALLAN_FUNCTIONS = {"services/delivery_challan_writes.py": {"create_delivery_challan_atomic", "record_challan_lot_atomic", "correct_draft_challan_lines_atomic"}}
#: Helpers that take the table's name to READ it.
_READ_HELPERS = {"_one", "_refuse_duplicate", "row_of_client"}
#: Modules that list the table's name as data (the tables a delete counts), never as a client.
_DATA_LISTS = {"routers/service_catalogue.py", "routers/firm_hsn_library.py"}


def _api_python():
    for path in sorted(API.rglob("*.py")):
        rel = path.relative_to(API)
        if any(part in _API_SKIP for part in rel.parts):
            continue
        yield rel.as_posix(), path.read_text(encoding="utf-8")


def _enclosing_function(node, parents):
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
    return "<module>"


def uses_of_the_challans_table(rel: str, source: str) -> list[str]:
    """Every use of the name "delivery_challans" in `source` that is not a read or one of the four named writers, and every database function with 'challan' in its name, as a sentence."""
    tree = ast.parse(source)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "rpc" and node.args:
            first = node.args[0]
            if (isinstance(first, ast.Constant) and isinstance(first.value, str) and "challan" in first.value.lower()
                    and first.value not in _CHALLAN_FUNCTIONS.get(rel, set())):
                problems.append(f"{rel}:{node.lineno} calls the database function {first.value!r}")
        if not (isinstance(node, ast.Constant) and node.value == "delivery_challans"):
            continue
        parent = parents.get(node)
        fn = _enclosing_function(node, parents)
        if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute) and parent.func.attr == "table":
            verb_node = parents.get(parent)
            if isinstance(verb_node, ast.Attribute) and verb_node.attr == "select":
                continue
            if isinstance(verb_node, ast.Attribute) and verb_node.attr in {"insert", "update", "upsert", "delete"}:
                if verb_node.attr not in _WRITERS.get((rel, fn), set()):
                    problems.append(f"{rel}:{node.lineno} {fn}() writes the table ({verb_node.attr})")
                continue
            problems.append(f"{rel}:{node.lineno} {fn}() holds the table in a variable or passes it on: a write through it cannot be seen")
            continue
        if isinstance(parent, ast.Call) and isinstance(parent.func, (ast.Name, ast.Attribute)):
            callee = parent.func.id if isinstance(parent.func, ast.Name) else parent.func.attr
            if callee in _READ_HELPERS:
                continue
        if rel in _DATA_LISTS and isinstance(parent, (ast.Tuple, ast.List)):
            continue
        problems.append(f"{rel}:{node.lineno} {fn}() names the table in a way the rule does not know")
    return problems


def test_the_model_lets_a_request_say_issued_and_the_service_refuses_it(db):
    """The honest form of the rule: the request model accepts any of the four statuses, so what keeps an amendment from issuing a challan is the service, in a sentence, before anything is
    written. Issuing has its own door (`issue_challan`), which asks what a challan must hold when the goods leave."""
    from models.sales_cycle import DeliveryChallanUpdateIn
    assert DeliveryChallanUpdateIn(status="issued").status == "issued"
    challan = itc._challan(db, "JW/9", "2026-06-01", status="draft")
    detail = _refused(db, challan, {"status": "issued"}, 409)
    assert "Issue challan" in detail and _stored(db, challan)["status"] == "draft", f"an amendment issued the challan or did not say where to: {detail}"


def test_the_issue_door_is_the_only_writer_of_a_challan_that_is_issued():
    """`create_challan` makes a draft, `issue_challan` makes it issued, `update_challan` and the lot door never write `issued`. Read from the service's own code, the whole API tree and the
    migrations: a second door that issues a challan would list it on FORM GST ITC-04 and record the goods as left without asking what the first asks."""
    problems = []
    for rel, text in _api_python():
        if "challan" not in text.lower():
            continue
        problems += uses_of_the_challans_table(rel, text)
    assert not problems, "the rule does not recognise a use of the challans table:\n  " + "\n  ".join(problems)
    # The two writers exist, so the rule cannot go vacuous.
    source = (API / "services" / "sales_cycle_service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    census: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "delivery_challans":
            parent, fn = parents.get(node), _enclosing_function(node, parents)
            verb = parents.get(parent) if isinstance(parent, ast.Call) else None
            if isinstance(verb, ast.Attribute) and verb.attr in {"insert", "update", "upsert", "delete"}:
                census[verb.attr] = census.get(verb.attr, 0) + 1
                assert verb.attr in _WRITERS[("services/sales_cycle_service.py", fn)]
    # no insert (create_challan writes through the function of migration 585); update 2: issue_challan and the amendment's one statement (`_write_an_amendment`, called by update_challan: a status is written over the one the patch judged)
    assert census == {"update": 2}, f"the writers of delivery_challans in the sales cycle service changed: {census}"
    made = source[source.index("def create_challan("):source.index("def _refuse_over_delivery(")]
    assert '"status": "draft"' in made and 'challan_writes.create(' in made, "a challan is no longer made as a draft, or no longer through the one transaction"
    migration = next(p for p in sorted((API / "migrations").glob("585_*.sql")) if not p.name.endswith("_rollback.sql")).read_text(encoding="utf-8")
    assert "SET status = 'received_back', received_back_on = v_last" in migration, "the lot function no longer stamps the challan received back"
    # the status `issued` is WRITTEN in ONE function (a filter on it, such as the stamp's `.eq("status", STATUS_ISSUED)`, writes nothing)
    issuing = [fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef) and _writes_issued(fn)]
    assert issuing == ["issue_challan"], f"the status issued is written by {issuing}"


def test_the_moment_of_issue_is_written_by_the_issue_door_alone():
    """`issued_at` is written once, by the statement that makes the challan issued: the table's trigger allows a NULL to be given a value once, so a second writer (a backfill, an amendment field) would be
    allowed by the database and is stopped here. Every module that names the challan tables is read; a dict key `issued_at` or an assignment to one may appear in `issue_challan` only."""
    found = set()
    for rel, text in _api_python():
        if "delivery_challan" not in text:
            continue
        tree = ast.parse(text)
        parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
        for node in ast.walk(tree):
            is_a_key = isinstance(node, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "issued_at" for k in node.keys)
            is_an_assignment = isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and node.slice.value == "issued_at" and isinstance(node.ctx, ast.Store)
            if is_a_key or is_an_assignment:
                found.add((rel, _enclosing_function(node, parents)))
    assert found == {("services/sales_cycle_service.py", "issue_challan")}, f"issued_at is written by {sorted(found)}"


def _says_issued(value) -> bool:
    return (isinstance(value, ast.Attribute) and value.attr == "STATUS_ISSUED") or (isinstance(value, ast.Constant) and value.value == "issued")


def _writes_issued(fn) -> bool:
    """True if the function puts the status issued INTO a row: a dict with a "status" key that says it, or an assignment to a "status" key. A comparison or a filter that names it is not a write."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Dict):
            for key, value in zip(n.keys, n.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == "status" and _says_issued(value):
                    return True
        if isinstance(n, ast.Assign):
            for target in n.targets:
                if (isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant) and target.slice.value == "status"
                        and _says_issued(n.value)):
                    return True
    return False


def test_the_writer_detector_sees_a_write_of_issued_and_not_a_filter_on_it():
    def writes(src: str) -> bool:
        return _writes_issued(ast.parse(src).body[0])

    assert writes('def f(db, dc):\n    db.table("t").update({"status": dc.STATUS_ISSUED}).execute()\n'), "a dict value named by the constant"
    assert writes('def f(db):\n    db.table("t").update({"status": "issued", "x": 1}).execute()\n'), "a dict value spelled out"
    assert writes('def f(fields):\n    fields["status"] = "issued"\n'), "an assignment to the key"
    assert writes('def f(fields, dc):\n    fields["status"] = dc.STATUS_ISSUED\n'), "an assignment of the constant"
    assert not writes('def f(db, dc):\n    db.table("t").update({"status": dc.STATUS_RECEIVED_BACK}).eq("status", dc.STATUS_ISSUED).execute()\n'), "a filter on issued writes nothing"
    assert not writes('def f(row, dc):\n    return str(row.get("status")) == dc.STATUS_ISSUED\n'), "a comparison writes nothing"


def test_the_detector_sees_what_the_first_regex_did_not():
    def flagged(src: str) -> list[str]:
        return uses_of_the_challans_table("services/x.py", src)

    assert flagged('def f(db):\n    t = db.table("delivery_challans")\n    t.update({"status": "issued"}).execute()\n'), "a write through a handle variable"
    assert flagged("def f(db):\n    db.table('delivery_challans').update({'status': 'issued'}).execute()\n"), "a single-quoted name"
    assert flagged('def f(db):\n    db.rpc("issue_delivery_challan", {}).execute()\n'), "a database function that issues one"
    assert flagged('def f(db):\n    db.table("delivery_challans").delete().eq("id", 1).execute()\n'), "a delete"
    assert flagged('def f(db):\n    (db.table("delivery_challans")\n     .upsert({}).execute())\n'), "an upsert"
    assert not flagged('def f(db):\n    return db.table("delivery_challans").select("id").execute()\n'), "a read is left alone"


def test_no_migration_other_than_the_three_that_made_or_wrote_the_table_touches_it():
    """A database function or trigger that issues a challan would be in a migration. Today the table is named only by 392 (it made it), 462 (the lots) and 585 (the atomic writes and the moment of issue) and their
    rollbacks; 585 issues nothing, which the next test reads."""
    named = {p.name for p in (API / "migrations").glob("*.sql") if "delivery_challans" in p.read_text(encoding="utf-8")}
    allowed = {"392_the_sales_cycle_before_the_tax_invoice.sql", "392_the_sales_cycle_before_the_tax_invoice_rollback.sql",
               "462_job_work_comes_back_in_lots_and_itc_04_reports_each_return.sql", "462_job_work_comes_back_in_lots_and_itc_04_reports_each_return_rollback.sql",
               "585_a_delivery_challan_is_written_in_one_transaction_and_says_when_it_was_issued.sql",
               "585_a_delivery_challan_is_written_in_one_transaction_and_says_when_it_was_issued_rollback.sql"}
    assert named <= allowed, f"a migration touches delivery_challans: {sorted(named - allowed)}. Read it: if it issues a challan, a draft is no longer the state the product makes."


def test_migration_585_names_the_table_and_issues_no_challan():
    """The one door that issues a challan is `sales_cycle_service.issue_challan`. The functions of migration 585 make a DRAFT (and refuse any other status), stamp an issued challan received back, and correct a DRAFT, and its triggers
    only refuse; none of them sets a status of `issued`, in a SET clause or in a row it inserts."""
    text = (API / "migrations" / "585_a_delivery_challan_is_written_in_one_transaction_and_says_when_it_was_issued.sql").read_text(encoding="utf-8")
    code = re.sub(r"--[^\n]*", "", text)
    # a SET clause that assigns the status 'issued' (a WHERE clause may compare it, which is a read)
    assert not re.search(r"\bSET\b(?:(?!\bWHERE\b)[^;])*?\bstatus\s*=\s*'issued'", code, flags=re.I | re.S), "a function of migration 585 sets a challan's status to issued"
    assert "coalesce(p_header ->> 'status', 'draft') <> 'draft'" in code, "the create no longer refuses a header that names a status other than draft"
    assert "IF v_status IS DISTINCT FROM 'draft' THEN" in code, "the correction no longer refuses a challan that is not a draft"
    assert not re.search(r"\bINSERT\s+INTO\s+public\.delivery_challans\b[^;]*'issued'", code, flags=re.I | re.S), "a function of migration 585 inserts an issued challan"


def _balanced_call_arguments(text: str, name: str):
    """The argument text of every `name(` call in `text`, read with its brackets balanced (a regex stops at the first closing bracket)."""
    for m in re.finditer(re.escape(name) + r"\(", text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        yield text[m.end():i - 1]


def test_the_balanced_reader_sees_past_the_first_closing_bracket():
    args = list(_balanced_call_arguments("api.updateChallan(c.id, clientId, { ...base(), status: 'issued' }); other(1)", "updateChallan"))
    assert args == ["c.id, clientId, { ...base(), status: 'issued' }"]


def test_the_front_end_never_asks_the_amendment_door_for_a_status():
    sent = []
    for folder in ("app", "components", "lib"):
        for path in sorted((WEB / folder).rglob("*.ts*")):
            if path.suffix not in {".ts", ".tsx"} or ".test." in path.name:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            rel = path.relative_to(WEB).as_posix()
            for args in _balanced_call_arguments(text, "updateChallan"):
                if re.search(r"\bstatus\b", args):
                    sent.append(f"{rel}: updateChallan({args[:100]})")
            # Any other PATCH to the door, whatever the wrapper is called.
            if rel != "lib/api/index.ts":
                for m in re.finditer(r"sales-cycle/challans/", text):
                    if "PATCH" in text[m.end():m.end() + 220]:
                        sent.append(f"{rel}: a PATCH to the challan door outside the one wrapper")
    wrapper = (WEB / "lib" / "api" / "index.ts").read_text(encoding="utf-8")
    start = wrapper.index("updateChallan:")
    assert "status" not in wrapper[start:start + 400], "the API wrapper adds a status to the challan amendment"
    assert not sent, "the screen asks the challan amendment door for a status, which is a door that can issue a challan:\n  " + "\n  ".join(sent)
