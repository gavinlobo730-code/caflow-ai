"""A delivery challan is written in one call, a lost race is a sentence, and a header that does not add up to its lines is not issued (ledger POST-A-419, the API's half; migration 585 is the database's).

WHAT THIS HOLDS (mock mode: the three functions are the in-memory double of `tests/challan_functions_double.py`, held to the real ones by `test_the_challan_double_and_the_challan_functions_agree_pg.py`)
    * `create_challan` makes ONE call, the create function, with the header and every line, and writes nothing else: no insert of the challan, no insert of a line.
    * `itc_04_service.record_return` makes ONE call, the lot function, and writes no lot and no stamp itself; a lot that brings every line back says so and the challan is received back.
    * `update_challan` with corrections to a draft's lines makes ONE call, the correction function, and updates neither the header nor a line itself; a patch with no lines is still the one statement.
    * a request that loses a race (the function refuses what the pre-check could not have: the challan was cancelled or marked back, another lot took the room, the draft was issued) is a 409 in a sentence that
      says nothing was written, and a second challan with a number another request just used is the 409 the duplicate check gives.
    * a cancel that a lot got in front of (the table's trigger) is the sentence the API's own check gives, naming the day.
    * the issue door asks that the header says what the lines come to, and the sentence names each figure that differs in rupees; and it stores the moment.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent))
import services.delivery_challan_writes as challan_writes
import services.itc_04_service as itc_service
import services.sales_cycle_service as svc
import test_itc_04_is_derived_from_the_challans_already_entered as itc
from domain.gst import delivery_challan as dc
from tests import challan_functions_double as functions
from tests.e2e_harness import FakeDB

CONSIGNER = {"legal_name": "Mfg Co Pvt Ltd", "gstin": None, "address": "1 Mill Road, Pune"}


class SpyDB(FakeDB):
    """The shared in-memory database, recording every call to the three functions and every write to the challan tables made by a statement."""

    def __init__(self):
        super().__init__()
        self.calls: list[tuple[str, dict]] = []
        self.writes: list[tuple[str, str]] = []
        self.refuse: dict[str, Exception] = {}

    def rpc(self, fn, params=None):
        self.calls.append((fn, params or {}))
        if fn in self.refuse:
            raise self.refuse[fn]
        return super().rpc(fn, params)

    def table(self, name):
        query = super().table(name)
        if name in ("delivery_challans", "delivery_challan_lines", "delivery_challan_returns"):
            for verb in ("insert", "update", "delete"):
                original = getattr(query, verb)

                def noted(*a, _name=name, _verb=verb, _original=original, **k):
                    self.writes.append((_name, _verb))
                    return _original(*a, **k)

                setattr(query, verb, noted)
        return query


@pytest.fixture
def db():
    x = SpyDB()
    x.seed("clients", {"id": itc.CLIENT, "firm_id": itc.FIRM, "client_name": "Mfg Co"})
    return x


def _payload(no="DC/1", reason=dc.REASON_JOB_WORK, **more):
    return {"client_id": itc.CLIENT, "document_no": no, "document_date": "2026-06-01", "reason": reason, "goods_kind": dc.GOODS_KIND_INPUTS if reason == dc.REASON_JOB_WORK else None,
            "consignee_name": "Precision Castings", "consignee_address": "Plot 4, Pune",
            "lines": [{"description": "Steel bar", "hsn_sac": "7214", "quantity": 10, "unit": "KGS", "rate_paise": 100000, "gst_rate_percent": 18},
                      {"description": "Steel plate", "hsn_sac": "7208", "quantity": 4, "unit": "KGS", "rate_paise": 50000, "gst_rate_percent": 18}], **more}


def _stored(db, challan_id):
    return next(c for c in db.rows("delivery_challans") if c["id"] == challan_id)


# ── the create ───────────────────────────────────────────────────────────────────────────────────

def test_a_challan_and_its_lines_are_one_call_and_nothing_else_writes_them(db):
    made = svc.create_challan(db, itc.FIRM, _payload())
    assert [name for name, _ in db.calls] == ["create_delivery_challan_atomic"]
    assert db.writes == [], f"a statement wrote the challan tables beside the function: {db.writes}"
    header, lines = db.calls[0][1]["p_header"], db.calls[0][1]["p_lines"]
    assert header["document_no"] == "DC/1" and header["status"] == "draft" and len(lines) == 2
    assert "id" not in header and not any(k in header for k in ("issued_at", "received_back_on")), "a challan is made as a draft with no id, no moment of issue and no day back"
    assert all("challan_id" not in ln for ln in lines), "the function sets the challan's own id on every line"
    assert made["status"] == "draft" and len(db.rows("delivery_challan_lines")) == 2
    assert header["taxable_paise"] == sum(ln["taxable_amount_paise"] for ln in lines)


def test_a_create_the_database_refuses_is_raised_and_leaves_no_challan_behind(db):
    db.refuse["create_delivery_challan_atomic"] = functions.Refusal("line_cannot_be_written", "23502")
    with pytest.raises(Exception) as caught:
        svc.create_challan(db, itc.FIRM, _payload())
    assert "line_cannot_be_written" in str(caught.value)
    assert db.rows("delivery_challans") == [] and db.rows("delivery_challan_lines") == []


def test_the_double_puts_back_what_a_failed_create_wrote(db):
    """The double is atomic as the function is: a line that is no object, after the header was appended, undoes the header."""
    with pytest.raises(functions.Refusal):
        functions.create(db._tables, lambda _t: "x", {"firm_id": itc.FIRM, "client_id": itc.CLIENT, "document_no": "DC/9"}, [{"description": "ok"}, "not an object"])
    assert db.rows("delivery_challans") == [] and db.rows("delivery_challan_lines") == []


def test_a_number_another_request_just_used_is_the_duplicate_sentence(db):
    db.refuse["create_delivery_challan_atomic"] = Exception("{'message': 'duplicate key value violates unique constraint', 'code': '23505'}")
    with pytest.raises(HTTPException) as caught:
        svc.create_challan(db, itc.FIRM, _payload("DC/7"))
    assert caught.value.status_code == 409 and "DC/7 is already used by another document for this client" in str(caught.value.detail)


# ── the lot and its stamp ─────────────────────────────────────────────────────────────────────────

def _issued_job_work_challan(db, no="JW/1", quantity="10"):
    challan = itc._challan(db, no, "2026-06-01")
    line = itc._line(db, challan, qty=quantity)
    return challan, line


def test_a_lot_is_one_call_and_the_stamp_is_the_function_s_not_the_services(db):
    challan, line = _issued_job_work_challan(db)
    first = itc_service.record_return(db, itc.FIRM, itc.CLIENT, challan["id"], itc._payload(line, quantity_returned=4.0), "u1")
    assert first["challan_marked_received_back"] is False and _stored(db, challan["id"])["status"] == "issued"
    last = itc_service.record_return(db, itc.FIRM, itc.CLIENT, challan["id"], itc._payload(line, quantity_returned=6.0, returned_on="2026-08-25"), "u1")
    assert last["challan_marked_received_back"] is True
    assert _stored(db, challan["id"])["status"] == "received_back" and _stored(db, challan["id"])["received_back_on"] == "2026-08-25"
    assert [name for name, _ in db.calls] == ["record_challan_lot_atomic", "record_challan_lot_atomic"]
    assert db.writes == [], f"a statement wrote a lot or a stamp beside the function: {db.writes}"
    assert db.calls[0][1]["p_lot"]["created_by"] == "u1" and db.calls[0][1]["p_lot"]["challan_line_id"] == line["id"]


def test_a_lot_that_marks_a_challan_back_has_the_order_derived_again_because_the_stamp_is_the_databases_now(db, monkeypatch):
    """The stamp is written inside the lot function, where nothing derives the order again, so the lot door asks for it after the call (POST-A-421): without it the order's list says it is partly delivered while its
    position says nothing is with the consignee. A lot that does not complete the challan asks for nothing. Run on the shared database, which honours a select's column list: the order the challan names reaches
    the call only if the lot door reads `order_id`."""
    challan = itc._challan(db, "JW/11", "2026-06-01", order_id="ORDER-1")
    line = itc._line(db, challan, qty="10")
    asked = []
    monkeypatch.setattr(svc, "order_follows_goods_back", lambda _db, firm, order: asked.append((firm, order)))
    assert itc_service.record_return(db, itc.FIRM, itc.CLIENT, challan["id"], itc._payload(line, quantity_returned=4.0), "u1")["challan_marked_received_back"] is False
    assert asked == []
    assert itc_service.record_return(db, itc.FIRM, itc.CLIENT, challan["id"], itc._payload(line, quantity_returned=6.0, returned_on="2026-08-25"), "u1")["challan_marked_received_back"] is True
    assert asked == [(itc.FIRM, "ORDER-1")]


@pytest.mark.parametrize("word, status, sentence", [
    ("challan_not_issued", 409, "is no longer an issued challan, so nothing was recorded"),
    ("lot_exceeds_line", 409, "there is no longer room for it, and nothing was recorded"),
    ("challan_not_job_work", 422, "Only goods sent for JOB WORK are returned on ITC-04"),
    ("challan_not_found", 404, "That challan line was not found for this client."),
    ("line_not_found", 404, "That challan line was not found for this client."),
])
def test_a_lot_that_loses_a_race_is_a_sentence_that_says_nothing_was_recorded(db, word, status, sentence):
    challan, line = _issued_job_work_challan(db)
    db.refuse["record_challan_lot_atomic"] = functions.Refusal(word)
    with pytest.raises(HTTPException) as caught:
        itc_service.record_return(db, itc.FIRM, itc.CLIENT, challan["id"], itc._payload(line), "u1")
    assert caught.value.status_code == status and sentence in str(caught.value.detail)
    assert db.rows("delivery_challan_returns") == [] and _stored(db, challan["id"])["status"] == "issued"


def test_a_failure_that_is_not_a_refusal_is_not_hidden_as_one(db):
    challan, line = _issued_job_work_challan(db)
    db.refuse["record_challan_lot_atomic"] = Exception("{'message': 'connection reset', 'code': '08006'}")
    with pytest.raises(Exception) as caught:
        itc_service.record_return(db, itc.FIRM, itc.CLIENT, challan["id"], itc._payload(line), "u1")
    assert not isinstance(caught.value, HTTPException) and "connection reset" in str(caught.value)


# ── a draft's corrections ─────────────────────────────────────────────────────────────────────────

def test_a_drafts_corrections_are_one_call_and_neither_the_header_nor_a_line_is_updated_by_a_statement(db):
    challan = itc._challan(db, "JW/2", "2026-06-01", status="draft")
    line = itc._line(db, challan)
    out = svc.update_challan(db, itc.FIRM, challan["id"], {"notes": "booked", "lines": [{"id": line["id"], "description": "Steel bar, cut", "hsn_sac": "7215"}]})
    assert [name for name, _ in db.calls] == ["correct_draft_challan_lines_atomic"] and db.writes == []
    params = db.calls[0][1]
    assert params["p_header"]["notes"] == "booked" and "status" not in params["p_header"]
    assert params["p_fixes"] == [{"id": line["id"], "description": "Steel bar, cut", "hsn_sac": "7215"}]
    stored_line = next(r for r in db.rows("delivery_challan_lines") if r["id"] == line["id"])
    assert stored_line["description"] == "Steel bar, cut" and stored_line["hsn_sac"] == "7215" and _stored(db, challan["id"])["notes"] == "booked"
    assert out["notes"] == "booked"


def test_a_patch_with_no_lines_is_still_the_one_statement_and_no_function(db):
    challan = itc._challan(db, "JW/3", "2026-06-01", status="draft")
    itc._line(db, challan)
    svc.update_challan(db, itc.FIRM, challan["id"], {"notes": "booked"})
    assert db.calls == [] and db.writes == [("delivery_challans", "update")]


@pytest.mark.parametrize("word", ["challan_not_draft", "line_not_found", "duplicate_fix"])
def test_a_correction_that_loses_a_race_is_the_amendment_door_s_sentence_and_writes_nothing(db, word):
    challan = itc._challan(db, "JW/4", "2026-06-01", status="draft")
    line = itc._line(db, challan)
    db.refuse["correct_draft_challan_lines_atomic"] = functions.Refusal(word)
    with pytest.raises(HTTPException) as caught:
        svc.update_challan(db, itc.FIRM, challan["id"], {"notes": "booked", "lines": [{"id": line["id"], "description": "x"}]})
    assert caught.value.status_code == 409 and caught.value.detail == "Challan JW/4 was changed while it was being amended. Reload it and look at its status."
    assert _stored(db, challan["id"]).get("notes") != "booked"


def test_a_correction_that_loses_to_a_delete_is_the_404_and_a_failure_that_is_not_a_refusal_is_not_hidden(db):
    challan = itc._challan(db, "JW/7", "2026-06-01", status="draft")
    line = itc._line(db, challan)
    body = {"notes": "booked", "lines": [{"id": line["id"], "description": "x"}]}
    db.refuse["correct_draft_challan_lines_atomic"] = functions.Refusal("challan_not_found", "P0002")
    with pytest.raises(HTTPException) as caught:
        svc.update_challan(db, itc.FIRM, challan["id"], body)
    assert caught.value.status_code == 404
    db.refuse["correct_draft_challan_lines_atomic"] = Exception("{'message': 'connection reset', 'code': '08006'}")
    with pytest.raises(Exception) as caught:
        svc.update_challan(db, itc.FIRM, challan["id"], body)
    assert not isinstance(caught.value, HTTPException) and "connection reset" in str(caught.value)


def test_a_statement_that_fails_for_another_reason_is_not_hidden_and_a_taken_number_is_the_duplicate_sentence(db):
    challan = itc._challan(db, "JW/8", "2026-06-01", status="draft")
    itc._line(db, challan)

    class Boom:
        def __init__(self, error):
            self.error = error

        def execute(self):
            raise self.error

    def lot_sentence():
        return HTTPException(status_code=409, detail="a lot")

    with pytest.raises(Exception) as caught:
        challan_writes.amend(Boom(Exception("{'message': 'connection reset', 'code': '08006'}")), when_a_lot_stops_it=lot_sentence)
    assert not isinstance(caught.value, HTTPException) and "connection reset" in str(caught.value)
    taken = Exception("{'message': 'duplicate key value violates unique constraint', 'code': '23505'}")
    with pytest.raises(HTTPException) as caught:
        challan_writes.amend(Boom(taken), when_a_lot_stops_it=lot_sentence, document_no="DC/77")
    assert caught.value.status_code == 409 and "DC/77 is already used by another document for this client" in str(caught.value.detail)
    db.refuse["correct_draft_challan_lines_atomic"] = taken
    with pytest.raises(HTTPException) as caught:
        challan_writes.correct_draft(db, itc.FIRM, itc.CLIENT, challan["id"], {"document_no": "DC/78"}, [], document_no="JW/8")
    assert caught.value.status_code == 409 and "DC/78 is already used" in str(caught.value.detail)


def test_a_row_id_that_happens_to_contain_the_digits_of_the_unique_violation_is_not_one():
    """The first version matched the substring 23505 in the whole error text, so a foreign-key failure whose details named a row id containing those digits was answered as a taken number."""
    class WithCode(Exception):
        code = "23503"

    other = WithCode("{'message': 'insert violates foreign key', 'code': '23503', 'details': 'Key (customer_id)=(11123505-aaaa-bbbb-cccc-000000000000) is not present'}")
    assert challan_writes._is_a_taken_number(other) is False
    assert challan_writes._is_a_taken_number(Exception("{'message': 'x', 'code': '23505'}")) is True


def test_the_corrections_header_carries_updated_at_to_the_function(db):
    challan = itc._challan(db, "JW/9", "2026-06-01", status="draft")
    line = itc._line(db, challan)
    svc.update_challan(db, itc.FIRM, challan["id"], {"lines": [{"id": line["id"], "description": "x"}]})
    assert db.calls[0][1]["p_header"].keys() == {"updated_at"}, "a correction made with no header field still moves the moment the challan was last amended"


def test_every_call_to_the_three_functions_is_made_as_the_privileged_client(db, monkeypatch):
    """The functions are executable by the API's privileged client alone (migration 585): a call on the signed-in client is a permission error in production that no in-memory double would show,
    so the door's use of `privileged_for` is asked here, once per function, with a marker in its place."""
    asked = []

    class Marker:
        def __init__(self, inner):
            self.inner = inner

        def rpc(self, fn, params=None):
            asked.append(fn)
            return self.inner.rpc(fn, params)

    monkeypatch.setattr(challan_writes, "privileged_for", lambda wrapped: Marker(wrapped))
    made = svc.create_challan(db, itc.FIRM, _payload("DC/11"))
    line = next(r for r in db.rows("delivery_challan_lines") if r["challan_id"] == made["id"])
    svc.update_challan(db, itc.FIRM, made["id"], {"lines": [{"id": line["id"], "description": "x"}]})
    challan = itc._challan(db, "JW/10", "2026-06-01")
    jw_line = itc._line(db, challan)
    itc_service.record_return(db, itc.FIRM, itc.CLIENT, challan["id"], itc._payload(jw_line, quantity_returned=1.0), "u1")
    assert asked == ["create_delivery_challan_atomic", "correct_draft_challan_lines_atomic", "record_challan_lot_atomic"]


def test_the_double_puts_back_the_header_when_a_correction_names_a_line_the_challan_does_not_hold(db):
    challan = itc._challan(db, "JW/5", "2026-06-01", status="draft")
    line = itc._line(db, challan)
    with pytest.raises(functions.Refusal) as caught:
        functions.correct_draft(db._tables, itc.FIRM, itc.CLIENT, challan["id"], {"notes": "booked"}, [{"id": line["id"], "description": "ok"}, {"id": "nobody", "description": "x"}])
    assert "line_not_found" in str(caught.value)
    assert _stored(db, challan["id"]).get("notes") != "booked" and next(r for r in db.rows("delivery_challan_lines"))["description"] != "ok"


# ── a cancel a lot got in front of ────────────────────────────────────────────────────────────────

def test_a_cancel_that_a_lot_got_in_front_of_is_the_sentence_the_pre_check_gives_and_names_the_day(db):
    """The pre-check read no lot and the table's trigger found one a moment later (migration 585): the sentence is the same and the day is the lot's."""
    challan, line = _issued_job_work_challan(db, "JW/6")
    real_update = FakeDB.table

    class CancelRaces(SpyDB):
        def table(self, name):
            query = real_update(self, name)
            if name == "delivery_challans":
                original = query.execute

                def execute():
                    if getattr(query, "_op", None) == "update" and (query._payload or {}).get("status") == "cancelled":
                        self.seed("delivery_challan_returns", {"firm_id": itc.FIRM, "client_id": itc.CLIENT, "challan_id": challan["id"], "challan_line_id": line["id"],
                                                               "returned_on": "2026-08-20", "quantity_returned": "4", "quantity_lost_or_wasted": "0"})
                        raise Exception("{'message': 'challan_has_lots', 'code': 'P0001'}")
                    return original()

                query.execute = execute
            return query

    racing = CancelRaces()
    racing._tables = db._tables
    with pytest.raises(HTTPException) as caught:
        svc.update_challan(racing, itc.FIRM, challan["id"], {"status": "cancelled"})
    assert caught.value.status_code == 409 and caught.value.detail == dc.cancel_after_goods_came_back_sentence("JW/6", "2026-08-20")
    assert _stored(db, challan["id"])["status"] == "issued"


# ── the issue door asks whether the header adds up ────────────────────────────────────────────────

def _the_lines_come_to(**heads):
    return [{"taxable_amount_paise": heads.get("taxable", 0), "cgst_paise": heads.get("cgst", 0), "sgst_paise": heads.get("sgst", 0),
             "igst_paise": heads.get("igst", 0), "line_cess_paise": heads.get("cess", 0)}]


def test_a_header_that_says_what_its_lines_come_to_adds_up():
    header = {"taxable_paise": 100000, "cgst_paise": 9000, "sgst_paise": 9000, "igst_paise": 0, "cess_paise": 500, "total_paise": 118500}
    assert dc.header_does_not_add_up_sentence("DC/1", header, _the_lines_come_to(taxable=60000, cgst=9000, sgst=9000, cess=500) + _the_lines_come_to(taxable=40000)) is None


def test_the_sentence_names_each_figure_that_differs_in_rupees_and_not_in_paise():
    header = {"taxable_paise": 118000, "cgst_paise": 9000, "sgst_paise": 9000, "igst_paise": 0, "cess_paise": 0, "total_paise": 136000}
    said = dc.header_does_not_add_up_sentence("DC/2", header, _the_lines_come_to(taxable=100000, cgst=9000, sgst=9000))
    assert said.startswith("Challan DC/2 does not add up to its own lines: ")
    assert "taxable value ₹1,180.00 in the challan's totals against ₹1,000.00 on its lines" in said, "an amount in a sentence a person reads carries the rupee sign (money_sentence.rupee_text)"
    assert "CGST" not in said and "SGST" not in said and "IGST" not in said, "a head that agrees is not named"
    assert "total ₹" not in said, "a total that is its own heads added up is not named: the heads are what differ"


def test_a_total_that_is_not_its_own_figures_added_up_is_named_apart_from_the_heads():
    header = {"taxable_paise": 100000, "cgst_paise": 9000, "sgst_paise": 9000, "igst_paise": 0, "cess_paise": 0, "total_paise": 999999}
    said = dc.header_does_not_add_up_sentence("DC/3", header, _the_lines_come_to(taxable=100000, cgst=9000, sgst=9000))
    assert "total ₹9,999.99 in the challan's totals against ₹1,180.00, which its own figures add up to" in said and "taxable" not in said


def test_a_header_with_figures_and_no_lines_does_not_add_up():
    header = {"taxable_paise": 100000, "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 0, "cess_paise": 0, "total_paise": 100000}
    assert "taxable value ₹1,000.00 in the challan's totals against ₹0.00 on its lines" in dc.header_does_not_add_up_sentence("DC/4", header, [])


def test_each_head_is_compared_apart_and_a_head_that_differs_is_named_by_its_own_word():
    """IGST and compensation cess are compared against their own line columns, as the other three are: an inter-State challan, or one with cess, must add up and must be refused when it does not."""
    header = {"taxable_paise": 100000, "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 18000, "cess_paise": 1200, "total_paise": 119200}
    matching = _the_lines_come_to(taxable=100000, igst=18000, cess=1200)
    assert dc.header_does_not_add_up_sentence("DC/6", header, matching) is None
    said = dc.header_does_not_add_up_sentence("DC/6", header, _the_lines_come_to(taxable=100000, igst=17000, cess=1200))
    assert "IGST ₹180.00 in the challan's totals against ₹170.00 on its lines" in said and "CGST" not in said and "cess" not in said
    said = dc.header_does_not_add_up_sentence("DC/6", header, _the_lines_come_to(taxable=100000, igst=18000, cess=0))
    assert "compensation cess ₹12.00 in the challan's totals against ₹0.00 on its lines" in said and "IGST" not in said


def test_a_header_with_nothing_on_it_and_no_lines_adds_up_to_nothing():
    assert dc.header_does_not_add_up_sentence("DC/5", {}, []) is None


def test_the_issue_door_refuses_a_header_that_does_not_add_up_and_writes_nothing(db):
    made = svc.create_challan(db, itc.FIRM, _payload("DC/8"))
    _stored(db, made["id"])["taxable_paise"] += 100          # a line that failed to save would have left exactly this
    _stored(db, made["id"])["total_paise"] += 100
    before = dict(_stored(db, made["id"]))
    with pytest.raises(HTTPException) as caught:
        svc.issue_challan(db, itc.FIRM, made["id"], client_id=itc.CLIENT, consigner=CONSIGNER)
    assert caught.value.status_code == 422 and "Challan DC/8 does not add up to its own lines" in str(caught.value.detail) and "taxable value" in str(caught.value.detail)
    assert _stored(db, made["id"]) == before, "a refused issue wrote something"


@pytest.mark.parametrize("name, more", [
    ("inter-State", {"reason": dc.REASON_INVOICE_TO_FOLLOW, "goods_kind": None, "is_inter_state": True, "place_of_supply": "29"}),
    ("with compensation cess", {"reason": dc.REASON_INVOICE_TO_FOLLOW, "goods_kind": None, "lines": [{"description": "Aerated water", "hsn_sac": "2202", "quantity": 100, "unit": "NOS", "rate_paise": 2000, "gst_rate_percent": 28, "cess_rate_bps": 1200}]}),
])
def test_a_challan_with_igst_or_cess_made_by_the_service_adds_up_and_is_issued(db, name, more):
    """The tie-out reads IGST and cess from the header and the lines: a challan the service makes carries them on both sides, and the issue door must not refuse it."""
    made = svc.create_challan(db, itc.FIRM, {**_payload("DC/10"), **more})
    stored = _stored(db, made["id"])
    assert (stored["igst_paise"] > 0) if name == "inter-State" else (stored["cess_paise"] > 0), "the scenario carries the head it is about"
    out = svc.issue_challan(db, itc.FIRM, made["id"], client_id=itc.CLIENT, consigner=CONSIGNER)
    assert out["status"] == "issued"


def test_a_challan_made_by_the_service_adds_up_and_is_issued_with_its_moment_stored(db):
    made = svc.create_challan(db, itc.FIRM, _payload("DC/9"))
    out = svc.issue_challan(db, itc.FIRM, made["id"], client_id=itc.CLIENT, consigner=CONSIGNER)
    stored = _stored(db, made["id"])
    assert stored["status"] == "issued" and stored["issued_at"] == out["issued_at"] == stored["updated_at"]
    assert stored["issued_at"] is not None
