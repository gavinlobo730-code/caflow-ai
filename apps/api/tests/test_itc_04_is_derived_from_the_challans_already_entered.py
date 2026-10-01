"""
GST-30 — FORM GST ITC-04 derived from the job-work challans already entered,
with goods that come back in lots.

WHAT WAS WRONG
    `delivery_challan.itc_04_period` returned a refusal and two sentences and
    stopped: a manufacturer client who sent material out for job work had the
    challans entered and the statement Rule 45(3) requires typed out again from
    them. Underneath that sat a second gap — a challan recorded ONE fact about
    the goods coming back, `received_back_on`, a single date for the whole
    challan, so "one challan sent, part returned" could not be recorded at all,
    although job work is routinely returned in lots and the form is built around
    exactly that (a row per return, against the original challan).

WHAT THIS ASSERTS
    * THE FINDING'S OWN VERIFY LINE: with one challan sent and one partly
      returned, Table 4 carries both, Table 5A carries the return against its
      ORIGINAL challan, and what is still out shows the s.143 date for the
      BALANCE — and that date is the challan's own, not the return's;
    * the cadence is not chosen: every reading is listed, each with its own due
      date, none is `chosen`, and the recorded turnover is context only;
    * a part return reduces what is left to be deemed supplied and never moves
      the day the goods left; lost or wasted quantity is recorded and is NEVER
      subtracted from the balance;
    * a return is refused, not clamped, when it exceeds what was sent, and every
      other refusal says why in its own words;
    * the last lot stops the s.143 clock through the ONE existing write;
    * the read is tenanted by firm AND client, scoped to the caller's client,
      and what it fetches is bounded by the answer;
    * what the statement cannot say is named on every answer, and every figure
      of the form is a pinned, `[S]`-graded constant.
"""
from __future__ import annotations

import ast
import inspect
from datetime import date

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import routers.sales_cycle as router
import services.itc_04_service as svc
from domain.gst import delivery_challan as dc
from domain.gst import itc_04 as itc
from models.sales_cycle import ChallanReturnIn
from tests.e2e_harness import FakeDB

FIRM = "FIRM-J"
OTHER_FIRM = "FIRM-OTHER"
CLIENT = "CLI-MFG"
OTHER_CLIENT = "CLI-OTHER"
TODAY = date(2026, 10, 1)
WORKER_GSTIN = "29BBBBB1111B1ZR"


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(svc, "ist_today", lambda: TODAY)


@pytest.fixture
def db():
    x = FakeDB()
    x.seed("clients", {"id": CLIENT, "firm_id": FIRM, "client_name": "Mfg Co"})
    x.seed("clients", {"id": OTHER_CLIENT, "firm_id": FIRM, "client_name": "Other Co"})
    return x


def _challan(db, no, sent_on, *, firm=FIRM, client=CLIENT, reason="job_work",
             status="issued", goods_kind="inputs", received_back_on=None,
             extended_to=None, gstin=WORKER_GSTIN, **extra):
    return db.seed("delivery_challans", {
        "firm_id": firm, "client_id": client, "document_no": no,
        "document_date": sent_on, "reason": reason, "status": status,
        "goods_kind": goods_kind, "received_back_on": received_back_on,
        "extended_to": extended_to, "consignee_name": "Precision Castings",
        "consignee_gstin": gstin, "place_of_supply": "29",
        "is_inter_state": False, **extra})


def _line(db, challan, *, qty="100", unit="KGS", taxable=10_00_000, desc="Steel bar",
          rate="18", **extra):
    return db.seed("delivery_challan_lines", {
        "firm_id": challan["firm_id"], "client_id": challan["client_id"],
        "challan_id": challan["id"], "line_order": 0, "description": desc,
        "hsn_sac": "7214", "quantity": qty, "unit": unit,
        "taxable_amount_paise": taxable, "gst_rate_percent": rate, **extra})


def _came_back(db, challan, line, qty, on, *, wasted="0", jw_no="JW/22",
               nature="Machining", jw_date="2026-08-21"):
    return db.seed("delivery_challan_returns", {
        "firm_id": challan["firm_id"], "client_id": challan["client_id"],
        "challan_id": challan["id"], "challan_line_id": line["id"],
        "returned_on": on, "quantity_returned": qty, "quantity_lost_or_wasted": wasted,
        "job_worker_challan_no": jw_no, "job_worker_challan_date": jw_date,
        "nature_of_job_work": nature})


def _statement(db, fy="2026-27", **kw):
    kw.setdefault("as_at", TODAY)
    return svc.statement(db, FIRM, CLIENT, fy, **kw)


def _payload(line, **kw):
    base = {"client_id": CLIENT, "challan_line_id": line["id"],
            "returned_on": "2026-08-20", "quantity_returned": 4.0,
            "quantity_lost_or_wasted": 0.0, "job_worker_challan_no": "JW/22",
            "job_worker_challan_date": None, "nature_of_job_work": "Machining",
            "notes": None}
    base.update(kw)
    return base


def _record(db, challan, line, **kw):
    return svc.record_return(db, FIRM, CLIENT, challan["id"], _payload(line, **kw), "u1")


# ── THE FINDING'S VERIFY LINE ────────────────────────────────────────────────

def test_one_challan_sent_and_one_partly_returned_give_the_rows_and_the_s143_date_for_the_balance(db):
    """The audit's own check. JW/001 went out untouched; JW/002 went out as
    capital goods and four of ten have come back."""
    c1 = _challan(db, "JW/001", "2026-05-10", goods_kind="inputs")
    _line(db, c1, qty="100", unit="KGS", taxable=10_00_000)
    c2 = _challan(db, "JW/002", "2026-06-05", goods_kind="capital_goods")
    l2 = _line(db, c2, qty="10", unit="NOS", taxable=50_00_000, desc="Die set")
    _came_back(db, c2, l2, "4", "2026-08-20")

    out = _statement(db, window="2026-27:H1")

    # Table 4 — both challans, one row per line.
    t4 = {r["challan_no"]: r for r in out["table_4"]["rows"]}
    assert set(t4) == {"JW/001", "JW/002"}
    assert t4["JW/001"]["type_of_goods"] == "Inputs"
    assert t4["JW/002"]["type_of_goods"] == "Capital goods"
    assert t4["JW/002"]["quantity"] == "10.000"
    assert t4["JW/002"]["taxable_value_paise"] == 50_00_000
    assert t4["JW/001"]["cgst_rate"] == "9" and t4["JW/001"]["sgst_rate"] == "9"
    assert t4["JW/001"]["igst_rate"] == "0"
    assert out["table_4"]["taxable_value_paise"] == 60_00_000

    # Table 5A — the return, against the ORIGINAL challan.
    t5 = out["table_5a"]["rows"]
    assert len(t5) == 1
    assert t5[0]["original_challan_no"] == "JW/002"
    assert t5[0]["quantity"] == "4.000"
    assert t5[0]["job_worker_challan_no"] == "JW/22"
    assert t5[0]["nature_of_job_work"] == "Machining"
    assert t5[0]["returned_on"] == "2026-08-20"

    # What is still out, and the s.143 date for it.
    owed = {o["challan_no"]: o for o in out["outstanding"]}
    assert set(owed) == {"JW/001", "JW/002"}
    part = owed["JW/002"]
    assert part["lines"][0]["sent"] == "10.000"
    assert part["lines"][0]["returned"] == "4.000"
    assert part["lines"][0]["outstanding"] == "6.000"
    # 6 of 10 of ₹50,00,000.00... of 50,00,000 paise.
    assert part["taxable_value_at_stake_paise"] == 30_00_000
    # CGST s.143(4): capital goods, three years, from the day they LEFT.
    assert part["clock"]["sent_on"] == "2026-06-05"
    assert part["clock"]["due_back_by"] == "2029-06-05"
    assert part["clock"]["overdue"] is False
    # s.143(3): one year for inputs.
    assert owed["JW/001"]["clock"]["due_back_by"] == "2027-05-10"
    assert owed["JW/001"]["clock"]["days_remaining"] == (date(2027, 5, 10) - TODAY).days


def test_a_part_return_does_not_move_the_day_the_goods_left(db):
    """s.143(3) deems the supply made on the day the goods were SENT OUT. A lot
    coming back reduces what is left to be deemed supplied; the clock is the
    challan's own. Restarting it from the return would push the deemed supply a
    year-and-a-bit out and hide the interest."""
    c = _challan(db, "JW/010", "2025-05-10", goods_kind="inputs")
    ln = _line(db, c, qty="50", unit="NOS", taxable=5_00_000)
    _came_back(db, c, ln, "20", "2025-09-15")
    _came_back(db, c, ln, "10", "2026-08-01")

    out = _statement(db)

    (row,) = out["outstanding"]
    assert row["lines"][0]["outstanding"] == "20.000"
    assert row["clock"]["sent_on"] == "2025-05-10"
    assert row["clock"]["due_back_by"] == "2026-05-10"
    assert row["clock"]["overdue"] is True, (
        "twenty units are still out five months after the year was up")
    # 20 of 50 of 5,00,000 paise.
    assert row["taxable_value_at_stake_paise"] == 2_00_000


def test_a_return_of_an_earlier_years_challan_is_reported_against_that_challan(db):
    c = _challan(db, "JW/011", "2025-11-03")
    ln = _line(db, c, qty="30", unit="NOS")
    _came_back(db, c, ln, "30", "2026-04-18")
    # Marked wholly back, as the record screen's last lot does.
    db.rows("delivery_challans")[0].update(received_back_on="2026-04-18",
                                           status="received_back")

    out = _statement(db, fy="2026-27", window="2026-27:Q1")

    assert out["table_4"]["rows"] == [], "the goods LEFT in the earlier year"
    (row,) = out["table_5a"]["rows"]
    assert row["original_challan_no"] == "JW/011"
    assert row["original_challan_date"] == "2025-11-03"
    assert out["outstanding"] == []


# ── the cadence is NOT chosen ────────────────────────────────────────────────

def test_every_reading_is_listed_and_none_is_chosen(db):
    out = _statement(db)

    assert [r["cadence"] for r in out["readings"]] == [
        itc.QUARTERLY, itc.HALF_YEARLY, itc.ANNUAL]
    assert all(r["chosen"] is False for r in out["readings"])
    assert out["period"]["decided"] is False
    assert out["selected_window"] is None
    assert out["table_4"] is None and out["table_5a"] is None, (
        "with no window named, no table is built — that would be choosing")


def test_the_windows_and_due_dates_are_pinned(db):
    """`[S]`: written from knowledge; a later correction must be deliberate."""
    w = itc.windows_for("2026-27")
    assert [(x.start, x.end, x.due_date) for x in w[itc.QUARTERLY]] == [
        ("2026-04-01", "2026-06-30", "2026-07-25"),
        ("2026-07-01", "2026-09-30", "2026-10-25"),
        ("2026-10-01", "2026-12-31", "2027-01-25"),
        ("2027-01-01", "2027-03-31", "2027-04-25")]
    assert [(x.start, x.end, x.due_date) for x in w[itc.HALF_YEARLY]] == [
        ("2026-04-01", "2026-09-30", "2026-10-25"),
        ("2026-10-01", "2027-03-31", "2027-04-25")]
    assert [(x.start, x.end, x.due_date) for x in w[itc.ANNUAL]] == [
        ("2026-04-01", "2027-03-31", "2027-04-25")]
    assert itc.VERIFIED is False


def test_the_window_counts_say_where_there_is_something_to_open(db):
    c = _challan(db, "JW/020", "2026-05-10")
    ln = _line(db, c, qty="10")
    _came_back(db, c, ln, "3", "2026-08-02")

    readings = {r["cadence"]: r for r in _statement(db)["readings"]}
    q = {w["key"]: w for w in readings[itc.QUARTERLY]["windows"]}
    assert (q["2026-27:Q1"]["table_4_rows"], q["2026-27:Q1"]["table_5a_rows"]) == (1, 0)
    assert (q["2026-27:Q2"]["table_4_rows"], q["2026-27:Q2"]["table_5a_rows"]) == (0, 1)
    h = {w["key"]: w for w in readings[itc.HALF_YEARLY]["windows"]}
    assert (h["2026-27:H1"]["table_4_rows"], h["2026-27:H1"]["table_5a_rows"]) == (1, 1)
    a = readings[itc.ANNUAL]["windows"][0]
    assert (a["table_4_rows"], a["table_5a_rows"]) == (1, 1)


def test_a_turnover_on_record_is_context_and_decides_nothing(db):
    db.seed("client_gst_turnover", {"firm_id": FIRM, "client_id": CLIENT,
                                    "financial_year": "2025-26",
                                    "aggregate_turnover_paise": 90_00_00_000_00})
    out = _statement(db)
    assert out["period"]["decided"] is False
    assert all(r["chosen"] is False for r in out["readings"])
    # The figure is shown beside the readings, never turned into one of them.
    # FY 2026-27's governing year is the PRECEDING one.
    assert out["period"]["preceding_year_aato_paise"] == 90_00_00_000_00


def test_an_unrecorded_turnover_is_none_and_never_zero(db):
    out = _statement(db)
    assert out["period"]["preceding_year_aato_paise"] is None


def test_an_unknown_window_is_refused_not_guessed(db):
    with pytest.raises(ValueError):
        _statement(db, window="2026-27:H3")
    with pytest.raises(ValueError):
        _statement(db, window="2025-26:H1")        # another year's window


def test_the_router_turns_an_unknown_window_into_a_422(monkeypatch, db):
    monkeypatch.setattr(router, "_mock", lambda: False)
    monkeypatch.setattr(router, "_db", lambda: db)
    monkeypatch.setattr(router, "assert_client_access", lambda *_a, **_k: None)
    with pytest.raises(HTTPException) as e:
        router.itc_04_statement(client_id=CLIENT, financial_year="2026-27",
                                window="nonsense",
                                current_user={"firm_id": FIRM, "role": "Partner"})
    assert e.value.status_code == 422


# ── waste is recorded and never subtracted ───────────────────────────────────

def test_lost_or_wasted_quantity_is_shown_and_never_subtracted_from_the_balance(db):
    c = _challan(db, "JW/030", "2026-05-10")
    ln = _line(db, c, qty="10", unit="NOS", taxable=10_00_000)
    _came_back(db, c, ln, "4", "2026-08-20", wasted="2")

    out = _statement(db, window="2026-27:H1")

    line = out["outstanding"][0]["lines"][0]
    assert line["returned"] == "4.000"
    assert line["lost_or_wasted"] == "2.000"
    assert line["outstanding"] == "6.000", (
        "scrap is not 'received back'; subtracting it would shrink the s.143 "
        "exposure on a judgement the product does not take")
    assert out["table_5a"]["rows"][0]["lost_or_wasted_quantity"] == "2.000"
    assert itc.WASTE_IS_NOT_SUBTRACTED in out["gaps"]


def test_a_challan_with_waste_never_stamps_itself_received_back(db):
    c = _challan(db, "JW/031", "2026-05-10")
    ln = _line(db, c, qty="10", unit="NOS")

    _record(db, c, ln, quantity_returned=8.0, quantity_lost_or_wasted=2.0)

    row = db.rows("delivery_challans")[0]
    assert row["received_back_on"] is None and row["status"] == "issued", (
        "two units are lost: the challan is not wholly back, so the clock runs on")


# ── the balance is pro-rata and rounded UP ───────────────────────────────────

def test_the_figure_at_stake_is_the_balances_share_rounded_up():
    ch = {"id": "c", "document_no": "JW/9", "document_date": "2026-05-10",
          "reason": "job_work", "status": "issued", "goods_kind": "inputs",
          "consignee_gstin": WORKER_GSTIN}
    ln = {"id": "l", "challan_id": "c", "quantity": "3", "unit": "NOS",
          "taxable_amount_paise": 10_000, "description": "x", "line_order": 0}
    ret = {"id": "r", "challan_id": "c", "challan_line_id": "l",
           "returned_on": "2026-06-01", "quantity_returned": "2",
           "quantity_lost_or_wasted": "0"}
    (row,) = itc.balances([ch], [ln], [ret], "2026-10-01")
    # 1/3 of 10,000 paise is 3,333.33…, and the figure is shown rounded UP.
    assert row["lines"][0]["taxable_value_at_stake_paise"] == 3_334
    assert isinstance(row["taxable_value_at_stake_paise"], int)


def test_a_quantity_stays_text_with_three_decimals_never_a_float(db):
    c = _challan(db, "JW/032", "2026-05-10")
    ln = _line(db, c, qty="0.100")
    _came_back(db, c, ln, "0.100", "2026-06-01")
    # 0.1 + 0.2 style drift is what a float would put here.
    row = _statement(db, window="2026-27:Q1")["table_5a"]["rows"][0]
    assert row["quantity"] == "0.100" and isinstance(row["quantity"], str)


# ── what the statement cannot say is NAMED ───────────────────────────────────

def test_the_named_refusals_travel_on_every_answer(db):
    gaps = _statement(db)["gaps"]
    for must in (itc.FORM_NUMBERING, itc.TABLE_5B_NOT_DERIVED, itc.TABLE_5C_NOT_DERIVED,
                 itc.WASTE_IS_NOT_SUBTRACTED, itc.TAX_ON_DEEMED_SUPPLY_NOT_COMPUTED,
                 itc.NOTHING_IS_FILED):
        assert must in gaps
    out = _statement(db)
    assert out["table_5b"]["derived"] is False and out["table_5c"]["derived"] is False
    assert out["nothing_is_filed"] is True and out["ca_review_required"] is True
    assert out["verified"] is False


def test_a_missing_particular_is_named_not_printed_as_a_blank(db):
    c = _challan(db, "JW/040", "2026-05-10", goods_kind=None, gstin=None,
                 place_of_supply=None)
    ln = _line(db, c, qty="10", unit="PIECES")
    _came_back(db, c, ln, "10", "2026-06-20", jw_no=None, nature=None, jw_date=None)

    out = _statement(db, window="2026-27:Q1")

    kinds4 = {g["kind"] for g in out["table_4"]["gaps"]}
    assert {"job_worker_not_identified", "type_of_goods", "uqc"} <= kinds4
    kinds5 = {g["kind"] for g in out["table_5a"]["gaps"]}
    assert {"job_worker_challan", "nature_of_job_work"} <= kinds5
    assert out["table_4"]["rows"][0]["type_of_goods"] is None, (
        "an unrecorded kind of goods is never defaulted to inputs")


def test_moulds_and_dies_are_named_as_outside_both_periods(db):
    c = _challan(db, "JW/041", "2026-05-10", goods_kind="moulds_dies_jigs_fixtures_tools")
    _line(db, c, qty="2", unit="NOS", desc="Injection mould")

    out = _statement(db, window="2026-27:Q1")

    assert out["table_4"]["rows"][0]["type_of_goods"] is None
    assert any(g["reason"] == itc.MOULDS_NOT_NAMED_BY_THE_FORM for g in out["table_4"]["gaps"])
    (row,) = out["outstanding"]
    assert row["clock"]["applies"] is False, "no s.143 period runs on them"


def test_a_whole_challan_return_with_no_lines_is_reported_flagged_not_dropped(db):
    """The legacy path: the CA stamped `received_back_on` and itemised nothing."""
    c = _challan(db, "JW/042", "2026-05-10", received_back_on="2026-07-09",
                 status="received_back")
    _line(db, c, qty="12", unit="NOS")

    out = _statement(db, window="2026-27:Q2")

    (row,) = out["table_5a"]["rows"]
    assert row["derived_from_whole_challan_return"] is True
    assert row["quantity"] == "12.000"
    assert row["job_worker_challan_no"] is None
    assert any(g["kind"] == "whole_challan_return" for g in out["table_5a"]["gaps"])
    assert out["outstanding"] == []


def test_a_draft_or_cancelled_challan_has_sent_nothing(db):
    d = _challan(db, "JW/050", "2026-05-10", status="draft")
    _line(db, d)
    x = _challan(db, "JW/051", "2026-05-11", status="cancelled")
    _line(db, x)
    out = _statement(db, window="2026-27:H1")
    assert out["table_4"]["rows"] == [] and out["outstanding"] == []


def test_a_challan_for_another_reason_is_not_on_itc_04(db):
    c = _challan(db, "DC/001", "2026-05-10", reason="other_than_supply", goods_kind=None)
    _line(db, c)
    out = _statement(db, window="2026-27:H1")
    assert out["table_4"]["rows"] == [] and out["outstanding"] == []


# ── recording a return ───────────────────────────────────────────────────────

def test_a_return_larger_than_what_was_sent_is_refused_not_clamped(db):
    c = _challan(db, "JW/060", "2026-05-10")
    ln = _line(db, c, qty="10", unit="NOS")
    _record(db, c, ln, quantity_returned=4.0)

    with pytest.raises(HTTPException) as e:
        _record(db, c, ln, quantity_returned=7.0, returned_on="2026-09-01")

    assert e.value.status_code == 409
    assert "at most 6.000" in e.value.detail
    assert len(db.rows("delivery_challan_returns")) == 1, "nothing was written, trimmed or not"


def test_waste_counts_against_what_can_still_be_recorded(db):
    c = _challan(db, "JW/061", "2026-05-10")
    ln = _line(db, c, qty="10", unit="NOS")
    _record(db, c, ln, quantity_returned=4.0, quantity_lost_or_wasted=2.0)
    with pytest.raises(HTTPException) as e:
        _record(db, c, ln, quantity_returned=5.0, returned_on="2026-09-01")
    assert e.value.status_code == 409 and "at most 4.000" in e.value.detail


def test_the_last_lot_stops_the_s143_clock_through_the_one_existing_write(db):
    c = _challan(db, "JW/062", "2026-05-10")
    ln = _line(db, c, qty="10", unit="NOS")

    first = _record(db, c, ln, quantity_returned=4.0, returned_on="2026-08-20")
    assert first["challan_marked_received_back"] is False
    row = db.rows("delivery_challans")[0]
    assert row["received_back_on"] is None and row["status"] == "issued"

    last = _record(db, c, ln, quantity_returned=6.0, returned_on="2026-09-14")
    assert last["challan_marked_received_back"] is True
    row = db.rows("delivery_challans")[0]
    assert row["received_back_on"] == "2026-09-14"
    assert row["status"] == "received_back"
    assert _statement(db)["outstanding"] == []

    with pytest.raises(HTTPException) as e:
        _record(db, c, ln, quantity_returned=1.0, returned_on="2026-09-20")
    assert e.value.status_code == 409 and "wholly received back" in e.value.detail


def test_a_challan_is_not_stamped_until_every_line_is_back(db):
    c = _challan(db, "JW/063", "2026-05-10")
    l1 = _line(db, c, qty="10", unit="NOS", desc="Bar")
    _line(db, c, qty="5", unit="NOS", desc="Plate", line_order=1)

    out = _record(db, c, l1, quantity_returned=10.0)

    assert out["challan_marked_received_back"] is False
    assert db.rows("delivery_challans")[0]["received_back_on"] is None


@pytest.mark.parametrize("kw,status,words", [
    ({"returned_on": "2026-05-09"}, 422, "before they were sent"),
    ({"returned_on": "2026-10-02"}, 422, "has not happened"),
])
def test_a_date_the_goods_cannot_have_come_back_on_is_refused(db, kw, status, words):
    c = _challan(db, "JW/064", "2026-05-10")
    ln = _line(db, c, qty="10")
    with pytest.raises(HTTPException) as e:
        _record(db, c, ln, **kw)
    assert e.value.status_code == status and words in e.value.detail
    assert db.rows("delivery_challan_returns") == []


def test_only_an_issued_job_work_challan_takes_a_return(db):
    draft = _challan(db, "JW/065", "2026-05-10", status="draft")
    dl = _line(db, draft)
    with pytest.raises(HTTPException) as e:
        _record(db, draft, dl)
    assert e.value.status_code == 409 and "has been issued" in e.value.detail

    other = _challan(db, "DC/066", "2026-05-10", reason="other_than_supply", goods_kind=None)
    ol = _line(db, other)
    with pytest.raises(HTTPException) as e:
        _record(db, other, ol)
    assert e.value.status_code == 422 and "JOB WORK" in e.value.detail
    assert db.rows("delivery_challan_returns") == []


def test_a_line_of_another_client_or_firm_is_not_found_and_says_the_same_thing(db):
    mine = _challan(db, "JW/067", "2026-05-10")
    mine_line = _line(db, mine)
    theirs = _challan(db, "JW/068", "2026-05-10", client=OTHER_CLIENT)
    their_line = _line(db, theirs)
    foreign = _challan(db, "JW/069", "2026-05-10", firm=OTHER_FIRM, client="CLI-F")
    foreign_line = _line(db, foreign)

    seen = []
    for ch, ln in ((theirs, their_line), (foreign, foreign_line)):
        with pytest.raises(HTTPException) as e:
            svc.record_return(db, FIRM, CLIENT, ch["id"], _payload(ln), "u1")
        seen.append((e.value.status_code, e.value.detail))
    # A line that is not there at all answers the same, so the response is not an
    # oracle for whether another client's document exists.
    with pytest.raises(HTTPException) as e:
        svc.record_return(db, FIRM, CLIENT, "no-such", _payload({"id": "no-such"}), "u1")
    seen.append((e.value.status_code, e.value.detail))
    assert len(set(seen)) == 1 and seen[0][0] == 404
    assert db.rows("delivery_challan_returns") == []

    # And the path's challan must be the line's OWN.
    with pytest.raises(HTTPException) as e:
        svc.record_return(db, FIRM, CLIENT, theirs["id"], _payload(mine_line), "u1")
    assert e.value.status_code == 404


def test_the_statement_never_reads_another_firms_or_clients_challans(db):
    mine = _challan(db, "JW/070", "2026-05-10")
    _line(db, mine)
    for firm, client, no in ((FIRM, OTHER_CLIENT, "JW/071"),
                             (OTHER_FIRM, CLIENT, "JW/072")):
        c = _challan(db, no, "2026-05-11", firm=firm, client=client)
        l = _line(db, c)
        _came_back(db, c, l, "1", "2026-06-01")

    out = _statement(db, window="2026-27:H1")
    assert [r["challan_no"] for r in out["table_4"]["rows"]] == ["JW/070"]
    assert out["table_5a"]["rows"] == []
    assert [o["challan_no"] for o in out["outstanding"]] == ["JW/070"]


# ── the request body ─────────────────────────────────────────────────────────

def _body(**kw):
    base = dict(client_id=CLIENT, challan_line_id="L1", returned_on="2026-08-20",
                quantity_returned=1.0)
    base.update(kw)
    return base


def test_a_return_that_returns_and_wastes_nothing_is_refused():
    with pytest.raises(ValidationError):
        ChallanReturnIn(**_body(quantity_returned=0.0))


def test_a_fourth_decimal_is_refused_because_the_column_holds_three():
    with pytest.raises(ValidationError):
        ChallanReturnIn(**_body(quantity_returned=1.2345))
    with pytest.raises(ValidationError):
        ChallanReturnIn(**_body(quantity_lost_or_wasted=0.0001))


def test_a_negative_quantity_and_a_bad_date_are_refused():
    with pytest.raises(ValidationError):
        ChallanReturnIn(**_body(quantity_returned=-1.0))
    with pytest.raises(ValidationError):
        ChallanReturnIn(**_body(returned_on="20/08/2026"))
    with pytest.raises(ValidationError):
        ChallanReturnIn(**_body(job_worker_challan_date="soon"))


def test_the_job_workers_challan_number_is_not_held_to_rule_55s_sixteen_characters():
    """It is somebody else's document; refusing a series this product never
    generated would make the return unrecordable for the clients who need it."""
    m = ChallanReturnIn(**_body(job_worker_challan_no="JW/2026-27/OUTWARD/00000022"))
    assert m.job_worker_challan_no == "JW/2026-27/OUTWARD/00000022"


# ── the router: scoped, audited, and refusing before it reads ────────────────

def test_the_statement_endpoint_refuses_an_unassigned_client_before_it_reads(monkeypatch, db):
    def refuse(*_a, **_k):
        raise HTTPException(status_code=404, detail="Not found")
    monkeypatch.setattr(router, "_mock", lambda: False)
    monkeypatch.setattr(router, "assert_client_access", refuse)
    monkeypatch.setattr(router, "_db", lambda: pytest.fail("the database was touched"))
    with pytest.raises(HTTPException) as e:
        router.itc_04_statement(client_id=CLIENT, financial_year="2026-27", window=None,
                                current_user={"firm_id": FIRM, "role": "Manager"})
    assert e.value.status_code == 404


def test_recording_a_return_asserts_the_body_clients_access_and_audits(monkeypatch, db):
    c = _challan(db, "JW/080", "2026-05-10")
    ln = _line(db, c, qty="10")
    seen = {}
    monkeypatch.setattr(router, "_mock", lambda: False)
    monkeypatch.setattr(router, "_db", lambda: db)
    monkeypatch.setattr(router, "assert_client_access",
                        lambda user, cid: seen.setdefault("client", cid))
    import services.audit_service as audit
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: seen.update(audit=(a, k)))

    out = router.record_challan_return(
        c["id"], ChallanReturnIn(**_body(challan_line_id=ln["id"], quantity_returned=4.0)),
        {"firm_id": FIRM, "id": "internal-1", "auth_user_id": "auth-1",
         "email": "ca@x.test", "role": "Partner"})

    assert seen["client"] == CLIENT
    assert out["success"] is True
    args, kw = seen["audit"]
    assert args[1] == "delivery_challan_return" and args[3] == "create"
    # audit_log.actor_id takes the AUTH id, not the internal one.
    assert kw["actor_id"] == "auth-1"


def test_both_endpoints_carry_the_permission_the_work_needs():
    src = inspect.getsource(router)
    stmt = inspect.getsource(router.itc_04_statement)
    rec = inspect.getsource(router.record_challan_return)
    assert 'rbac("gst", "read")' in stmt
    assert 'rbac("invoice", "write")' in rec
    assert "assert_client_access" in stmt and "assert_client_access" in rec
    assert "FYLabel" in stmt, "a financial-year label is a type, not a str"
    assert src.count("itc_04_service") >= 2


# ── the read is tenanted, paged and bounded ──────────────────────────────────

def _service_calls():
    tree = ast.parse(inspect.getsource(svc))
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)]


def test_every_read_and_write_in_the_service_carries_the_firm_filter():
    src = inspect.getsource(svc)
    tables = src.count('db.table("')
    firm_filters = src.count('.eq("firm_id", firm_id)')
    # One filter per query; the insert carries the firm in its payload instead.
    assert firm_filters >= tables - 1, (
        f"{tables} queries but only {firm_filters} firm filters — the service role "
        "bypasses RLS, so that filter is the isolation control")
    assert src.count('.eq("client_id", client_id)') >= firm_filters - 1


def test_nothing_is_paged_by_hand_and_the_selects_are_literal():
    src = inspect.getsource(svc)
    assert "fetch_all(" in src and "fetch_all_in(" in src
    assert ".range(" not in src and "_paginate_all" not in src
    # The backend column guard resolves no variable: a select reached through a
    # name is one it cannot check, on a brand-new table most of all.
    for call in _service_calls():
        f = call.func
        if isinstance(f, ast.Attribute) and f.attr == "select" and call.args:
            assert isinstance(call.args[0], (ast.Constant, ast.JoinedStr, ast.BinOp)), (
                f"a select list passed through a name at line {call.lineno}")


def test_what_is_still_out_is_read_through_the_one_indexed_predicate(db):
    src = inspect.getsource(svc.statement)
    # Migration 392's partial index is exactly this predicate.
    assert '.eq("status", "issued")' in src and '.is_("received_back_on", "null")' in src


# ── nothing is posted, nothing is filed, nothing is chosen ───────────────────

def test_the_module_posts_nothing_and_reaches_no_portal():
    for mod in (itc, svc):
        src = inspect.getsource(mod)
        for forbidden in ("_create_journal", "post_journal", "journal_entries",
                          "requests.", "httpx", "gstn", "inventory_stock_ledger"):
            assert forbidden not in src, f"{mod.__name__} mentions {forbidden}"
    assert "CA REVIEW REQUIRED" in inspect.getsource(svc)
    assert "DO NOT AUTO-SUBMIT" in inspect.getsource(router.itc_04_statement)


def test_no_cadence_is_chosen_in_the_domain_module(db):
    """The module lays out every reading; it never marks one as the answer and
    never reads a turnover to pick between them."""
    src = inspect.getsource(itc)
    assert '"chosen": True' not in src and "'chosen': True" not in src
    assert "turnover" not in inspect.getsource(itc.window_counts)
    assert "turnover" not in inspect.getsource(itc.windows_for)
    # The three readings exist as named windows...
    keys = {w.cadence for ws in itc.windows_for("2026-27").values() for w in ws}
    assert keys == {itc.QUARTERLY, itc.HALF_YEARLY, itc.ANNUAL}
    # ...and a statement built for ANY recorded turnover lists all three.
    for aato in (None, 1_00_00_000, 500_00_00_000_00):
        if aato is not None:
            db.seed("client_gst_turnover", {"firm_id": FIRM, "client_id": CLIENT,
                                            "financial_year": "2025-26",
                                            "aggregate_turnover_paise": aato})
        readings = _statement(db)["readings"]
        assert [r["cadence"] for r in readings] == [
            itc.QUARTERLY, itc.HALF_YEARLY, itc.ANNUAL]
        assert not any(r["chosen"] for r in readings)


def test_the_form_is_graded_unverified_and_says_so_on_every_answer(db):
    assert itc.VERIFIED is False
    out = _statement(db)
    assert out["period"]["verified"] is False and out["verified"] is False
