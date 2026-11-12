"""The lines of a DRAFT delivery challan are corrected in their description and HSN code, and nothing else of a line, and a draft is cancelled through the table that already allows it (POST-A-417).

WHAT WAS WRONG
    The amendment door (`PATCH /api/sales-cycle/challans/{id}`) took `lines` in its body and DROPPED it: an HSN code could never be added to a line, so a draft made without one (Rule 55(1)(iv) asks for it)
    could not be issued and could not be mended, and the person made the challan again under a new number while the draft kept its own. The door reported a success for a body whose lines it had thrown away.

WHAT IS HELD
    * a draft's lines are corrected by id, and only their `description` and `hsn_sac`; the write names the firm, the client, the challan and the line, and a line of another challan, client or firm is not touched;
    * everything else on a line (quantity, unit, rate, tax, an unknown key), a line that is not this challan's, a line named twice, a correction that changes nothing, a blank description and an HSN that is not
      digits are refused in a sentence and NOTHING is written (not the header, not the other lines);
    * a clear HSN box clears the code (it is then listed as still to be recorded), a description is trimmed;
    * a challan that is not a draft refuses `lines` (409), whatever else the patch gives, and its lines are untouched;
    * the header write is held to a draft by the same compare-and-set as a status, so a correction that lost a race to an issue writes nothing;
    * the corrected draft can then be issued (the point of the item), and a draft is cancelled by the status table `AMENDMENT_MAY_MAKE` with no lot recorded;
    * what was corrected is audited by line id, never by what the line now says.
"""
from __future__ import annotations

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
SOME_CONSIGNER = {"legal_name": "Mfg Co", "gstin": "27AAPFU0939F1ZV", "address": "1 Mill Road, Pune 411001"}


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


def _draft(db, no="JW/17", *, client=itc.CLIENT, firm=itc.FIRM, **extra):
    row = itc._challan(db, no, "2026-10-01", firm=firm, client=client, status="draft", **extra)
    return row


def _line(db, challan, desc="Steel bar", hsn="", order=0, **extra):
    ln = itc._line(db, challan, desc=desc, line_order=order, **extra)
    ln["hsn_sac"] = hsn or None
    return ln


def _stored_line(db, line):
    return next(r for r in db.rows("delivery_challan_lines") if r["id"] == line["id"])


def _fix(db, challan, fixes, **more):
    return svc.update_challan(db, itc.FIRM, challan["id"], {"lines": fixes, **more})


def _refused(db, challan, fixes, code, **more):
    with pytest.raises(HTTPException) as caught:
        _fix(db, challan, fixes, **more)
    assert caught.value.status_code == code, caught.value.detail
    return str(caught.value.detail)


# ── the correction ─────────────────────────────────────────────────────────────

def test_a_draft_line_is_given_an_hsn_code_and_a_better_description(db):
    ch = _draft(db)
    ln = _line(db, ch)
    _fix(db, ch, [{"id": ln["id"], "hsn_sac": " 7214 ", "description": "  Steel bar, 12 mm  "}])
    stored = _stored_line(db, ln)
    assert stored["hsn_sac"] == "7214" and stored["description"] == "Steel bar, 12 mm"


def test_one_field_alone_is_corrected_and_the_other_stands(db):
    ch = _draft(db)
    ln = _line(db, ch, desc="Steel bar", hsn="7214")
    _fix(db, ch, [{"id": ln["id"], "description": "Steel rod"}])
    assert _stored_line(db, ln)["hsn_sac"] == "7214" and _stored_line(db, ln)["description"] == "Steel rod"
    _fix(db, ch, [{"id": ln["id"], "hsn_sac": "7228"}])
    assert _stored_line(db, ln)["hsn_sac"] == "7228" and _stored_line(db, ln)["description"] == "Steel rod"


def test_a_cleared_hsn_box_clears_the_code(db):
    ch = _draft(db)
    ln = _line(db, ch, hsn="7214")
    _fix(db, ch, [{"id": ln["id"], "hsn_sac": "   "}])
    assert _stored_line(db, ln)["hsn_sac"] is None


def test_several_lines_are_corrected_in_one_request(db):
    ch = _draft(db)
    a, b = _line(db, ch, desc="A", order=0), _line(db, ch, desc="B", order=1)
    _fix(db, ch, [{"id": a["id"], "hsn_sac": "7214"}, {"id": b["id"], "hsn_sac": "7215"}])
    assert (_stored_line(db, a)["hsn_sac"], _stored_line(db, b)["hsn_sac"]) == ("7214", "7215")


def test_a_correction_moves_no_money_and_no_quantity(db):
    ch = _draft(db)
    ln = _line(db, ch, qty="100", taxable=10_00_000)
    before = {k: _stored_line(db, ln)[k] for k in ("quantity", "unit", "taxable_amount_paise", "gst_rate_percent")}
    _fix(db, ch, [{"id": ln["id"], "hsn_sac": "7214"}])
    assert {k: _stored_line(db, ln)[k] for k in before} == before


def test_the_header_fields_are_corrected_beside_the_lines_in_one_request(db):
    ch = _draft(db, consignee_name="Old Name")
    ln = _line(db, ch)
    svc.update_challan(db, itc.FIRM, ch["id"], {"consignee_name": "New Name", "lines": [{"id": ln["id"], "hsn_sac": "7214"}]})
    assert next(r for r in db.rows("delivery_challans") if r["id"] == ch["id"])["consignee_name"] == "New Name"
    assert _stored_line(db, ln)["hsn_sac"] == "7214"


# ── what is refused, in a sentence, with nothing written ───────────────────────────

@pytest.mark.parametrize("extra", [{"quantity": "5"}, {"unit": "NOS"}, {"rate_paise": 1}, {"gst_rate_percent": 5}, {"taxable_amount_paise": 1}, {"nonsense": 1}])
def test_anything_else_on_a_line_is_refused_and_not_dropped(db, extra):
    ch = _draft(db)
    ln = _line(db, ch, desc="Steel bar")
    said = _refused(db, ch, [{"id": ln["id"], "hsn_sac": "7214", **extra}], 422)
    assert list(extra)[0] in said and "made again" in said
    assert _stored_line(db, ln)["hsn_sac"] is None, "a line correction that was refused still wrote its HSN"


def test_a_line_of_another_challan_client_or_firm_is_not_this_challans_to_correct(db):
    ch, other = _draft(db, "JW/17"), _draft(db, "JW/18")
    mine, theirs = _line(db, ch), _line(db, other)
    other_client = _draft(db, "JW/19", client=itc.OTHER_CLIENT)
    their_client_line = itc._line(db, other_client)
    said = _refused(db, ch, [{"id": theirs["id"], "hsn_sac": "7214"}], 422)
    assert theirs["id"] in said and "not a line of challan JW/17" in said
    _refused(db, ch, [{"id": their_client_line["id"], "hsn_sac": "7214"}], 422)
    assert _stored_line(db, theirs)["hsn_sac"] is None and _stored_line(db, mine)["hsn_sac"] is None


def test_a_refused_request_writes_nothing_even_for_the_lines_that_were_fine(db):
    ch = _draft(db)
    good, also = _line(db, ch, order=0), _line(db, ch, order=1)
    _refused(db, ch, [{"id": good["id"], "hsn_sac": "7214"}, {"id": also["id"], "hsn_sac": "SAC-9983"}], 422)
    assert _stored_line(db, good)["hsn_sac"] is None, "the good line was written before the bad one was judged"
    assert next(r for r in db.rows("delivery_challans") if r["id"] == ch["id"]).get("updated_at") is None


def test_an_hsn_that_is_not_digits_a_blank_description_a_repeated_line_and_an_empty_correction_are_each_refused(db):
    ch = _draft(db)
    ln = _line(db, ch)
    assert "HSN 'SAC-9983' on line 1 is not a code" in _refused(db, ch, [{"id": ln["id"], "hsn_sac": "SAC-9983"}], 422)
    assert "Line 1 keeps a description" in _refused(db, ch, [{"id": ln["id"], "description": "   "}], 422)
    assert "Line 1 is corrected twice" in _refused(db, ch, [{"id": ln["id"], "hsn_sac": "7214"}, {"id": ln["id"], "hsn_sac": "7215"}], 422)
    assert "Line 1 gives nothing to change" in _refused(db, ch, [{"id": ln["id"]}], 422)
    assert "by its id" in _refused(db, ch, [{"hsn_sac": "7214"}], 422)
    assert "as a list" in _refused(db, ch, [], 422)
    assert "as a list" in _refused(db, ch, ["7214"], 422)


def test_a_sentence_names_the_line_by_the_number_the_screen_shows_and_not_by_its_id(db):
    ch = _draft(db)
    first, second = _line(db, ch, desc="A", order=0), _line(db, ch, desc="B", order=1)
    said = _refused(db, ch, [{"id": second["id"], "hsn_sac": "SAC-9983"}], 422)
    assert "line 2" in said and second["id"] not in said, said
    assert first["id"] not in said


@pytest.mark.parametrize("fix", [
    {"description": {"a": 1}}, {"description": 7}, {"description": ["x"]}, {"hsn_sac": 7214}, {"hsn_sac": {"a": 1}}, {"hsn_sac": ["7214"]}, {"hsn_sac": True},
])
def test_a_value_that_is_not_text_is_refused_and_not_stored_as_its_spelling(db, fix):
    ch = _draft(db)
    ln = _line(db, ch, desc="Steel bar", hsn="7214")
    said = _refused(db, ch, [{"id": ln["id"], **fix}], 422)
    assert "is text" in said
    assert (_stored_line(db, ln)["description"], _stored_line(db, ln)["hsn_sac"]) == ("Steel bar", "7214")


def test_lines_given_beside_a_status_are_refused_so_a_cancel_does_not_write_lines_onto_a_cancelled_challan(db):
    ch = _draft(db)
    ln = _line(db, ch)
    said = _refused(db, ch, [{"id": ln["id"], "hsn_sac": "7214"}], 422, status="cancelled")
    assert said == dc.LINES_ARE_CORRECTED_ALONE
    assert next(r for r in db.rows("delivery_challans") if r["id"] == ch["id"])["status"] == "draft"
    assert _stored_line(db, ln)["hsn_sac"] is None


def test_a_challan_that_is_not_a_draft_refuses_lines_whatever_else_the_patch_gives(db):
    for status in ("issued", "received_back", "cancelled"):
        ch = _draft(db, f"JW/{status}")
        ch["status"] = status
        ln = _line(db, ch, hsn="7214")
        said = _refused(db, ch, [{"id": ln["id"], "hsn_sac": "7215"}], 409, transporter_name="Fast Freight")
        assert "only a draft's lines are corrected" in said
        assert _stored_line(db, ln)["hsn_sac"] == "7214"
        assert next(r for r in db.rows("delivery_challans") if r["id"] == ch["id"]).get("transporter_name") != "Fast Freight", "the header was written beside a refused correction"


def test_the_header_write_is_held_to_a_draft_so_a_correction_that_lost_a_race_writes_nothing(db, monkeypatch):
    ch = _draft(db)
    ln = _line(db, ch)
    real = svc.challan_lines

    def issued_in_between(*a, **k):
        out = real(*a, **k)
        next(r for r in db.rows("delivery_challans") if r["id"] == ch["id"])["status"] = "issued"     # the draft is issued after the request judged it
        return out

    monkeypatch.setattr(svc, "challan_lines", issued_in_between)
    with pytest.raises(HTTPException) as caught:
        _fix(db, ch, [{"id": ln["id"], "hsn_sac": "7214"}])
    assert caught.value.status_code == 409 and "was changed while it was being amended" in caught.value.detail
    assert _stored_line(db, ln)["hsn_sac"] is None


# ── the point of the item: the corrected draft is issued, and a draft is cancelled ───────────

def test_a_draft_made_without_an_hsn_code_cannot_be_issued_until_it_is_corrected_and_then_it_can(db):
    ch = _draft(db, consignee_name="Precision Castings", consignee_gstin=itc.WORKER_GSTIN, consignee_address="Plot 4, Pune")
    ln = _line(db, ch)
    with pytest.raises(HTTPException) as caught:
        svc.issue_challan(db, itc.FIRM, ch["id"], client_id=itc.CLIENT, consigner=SOME_CONSIGNER)
    assert caught.value.status_code == 422 and "HSN" in caught.value.detail
    _fix(db, ch, [{"id": ln["id"], "hsn_sac": "7214"}])
    out = svc.issue_challan(db, itc.FIRM, ch["id"], client_id=itc.CLIENT, consigner=SOME_CONSIGNER)
    assert out["status"] == "issued"


def test_a_draft_is_cancelled_by_the_status_table_and_keeps_its_number(db):
    ch = _draft(db, "JW/77")
    _line(db, ch)
    out = svc.update_challan(db, itc.FIRM, ch["id"], {"status": "cancelled"})
    assert out["status"] == "cancelled" and out["document_no"] == "JW/77"
    assert dc.AMENDMENT_MAY_MAKE[dc.STATUS_DRAFT] == (dc.STATUS_CANCELLED,)
    # and a cancelled draft is at its end: its lines are not corrected, it is not issued
    with pytest.raises(HTTPException):
        svc.issue_challan(db, itc.FIRM, ch["id"], client_id=itc.CLIENT, consigner=SOME_CONSIGNER)


# ── the pure rule, and the route's audit ───────────────────────────────────────────────

def test_the_pure_rule_names_the_challan_and_judges_a_status_before_a_line():
    assert "JW/1" in dc.draft_line_corrections_problem("JW/1", "issued", [{"id": "x"}], ["x"])
    assert dc.draft_line_corrections_problem("JW/1", "draft", [{"id": "x", "hsn_sac": "7214"}], ["x"]) is None
    assert dc.draft_line_changes({"id": "x", "hsn_sac": "", "description": " d "}) == {"hsn_sac": None, "description": "d"}
    assert dc.DRAFT_LINE_FIELDS == ("description", "hsn_sac")


def test_the_route_audits_the_lines_corrected_by_id_and_not_by_what_they_now_say(db, monkeypatch):
    import routers.sales_cycle as route
    from models.sales_cycle import DeliveryChallanUpdateIn
    import services.audit_service as audit

    ch = _draft(db)
    ln = _line(db, ch)
    events = []
    monkeypatch.setattr(route, "_mock", lambda: False)
    monkeypatch.setattr(route, "_db", lambda: db)
    monkeypatch.setattr(route, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: events.append((a, k)))
    user = {"firm_id": itc.FIRM, "id": "u-1", "auth_user_id": "auth-1", "email": "ca@x.test", "role": "Partner"}
    out = route.update_challan(ch["id"], DeliveryChallanUpdateIn(lines=[{"id": ln["id"], "hsn_sac": "7214", "description": "Steel rod"}]), client_id=itc.CLIENT, current_user=user)
    assert out["success"] is True
    assert len(events) == 1
    new_data = events[0][0][5] if len(events[0][0]) > 5 else events[0][1]["new_data"]
    assert new_data["lines_corrected"] == [ln["id"]]
    # by id only: neither the code nor the words it now says are written to the log
    assert "7214" not in str(new_data) and "Steel rod" not in str(new_data)
    assert "lines" not in new_data["fields"]


def test_a_correction_names_the_line_by_challan_client_and_firm_so_a_line_with_the_same_id_elsewhere_is_not_touched(db):
    ch = _draft(db, "JW/17")
    mine = _line(db, ch)
    # another challan of the same client, and another client's challan, each holding a line that carries THIS line's id
    other_challan = _draft(db, "JW/18")
    other_client = _draft(db, "JW/19", client=itc.OTHER_CLIENT)
    clone_a = itc._line(db, other_challan, desc="Same id, another challan")
    clone_b = itc._line(db, other_client, desc="Same id, another client")
    clone_a["id"] = clone_b["id"] = mine["id"]
    clone_a["hsn_sac"] = clone_b["hsn_sac"] = None
    _fix(db, ch, [{"id": mine["id"], "hsn_sac": "7214"}])
    by_challan = {(r["challan_id"], r["client_id"]): r["hsn_sac"] for r in db.rows("delivery_challan_lines") if r["id"] == mine["id"]}
    assert by_challan[(ch["id"], itc.CLIENT)] == "7214"
    assert by_challan[(other_challan["id"], itc.CLIENT)] is None, "a line of another challan with the same id was written"
    assert by_challan[(other_client["id"], itc.OTHER_CLIENT)] is None, "a line of another client with the same id was written"
    # and a row that carries this challan's id and this line's id under ANOTHER CLIENT (a row that should not exist is the one a missing client filter would reach)
    stray = db.seed("delivery_challan_lines", {"id": mine["id"], "firm_id": itc.FIRM, "client_id": itc.OTHER_CLIENT, "challan_id": ch["id"], "line_order": 0,
                                               "description": "Stray", "hsn_sac": None, "quantity": "1", "unit": "NOS", "taxable_amount_paise": 0, "gst_rate_percent": 0})
    other_firm = db.seed("delivery_challan_lines", {"id": mine["id"], "firm_id": "FIRM-ELSEWHERE", "client_id": itc.CLIENT, "challan_id": ch["id"], "line_order": 0,
                                                    "description": "Another firm", "hsn_sac": None, "quantity": "1", "unit": "NOS", "taxable_amount_paise": 0, "gst_rate_percent": 0})
    _fix(db, ch, [{"id": mine["id"], "hsn_sac": "7215"}])
    assert stray["hsn_sac"] is None, "a row of another client was written because the write did not name the client"
    assert other_firm["hsn_sac"] is None, "a row of another firm was written because the write did not name the firm"
