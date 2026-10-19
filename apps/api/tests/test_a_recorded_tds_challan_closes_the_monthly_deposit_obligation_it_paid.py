"""A TDS challan recorded in the TDS workspace closes the monthly deposit obligation of every month it paid in full (found by
opening the seeded demo firm's Deadlines and Compliance screens, which called every deposit overdue).

WHAT WAS WRONG
    A TDS engagement owes twelve monthly deposits (`TDS_NON_SALARY_DEPOSIT`, Rule 30(2)). The challan register is where a
    deposit is recorded, and recording one never touched the calendar: with every deduction of the year deposited by a
    recorded challan, the deposits still read overdue. The GST and ITR workspaces and the quarterly statements had this split
    (POST-A-264, POST-A-267); the monthly deposit was left because a month can carry several challans under several sections.

WHAT IS HELD
    * a month closes when the month's deposit worksheet has tax in it and NOTHING outstanding (every section covered, first in
      first out), the month is over, no covering challan is against a demand, no payment is in the future, and EVERY payment was
      made on or before the month's due date; a month fully and punctually deposited closes whichever recorded challan made it so
      (the catch-up of earlier challans), and a month left open is reported only when the recorded challan paid some of it;
    * it closes THROUGH `mark_filed` with the date of the last payment and the serial of the last challan paid that day, and says
      both in the answer; a deposit made in the month itself is not refused as filed before the period ended, a late challan
      closes nothing by itself (the register matches by order within the quarter, not by month, and a Filed obligation cannot be
      reopened), and the residual that two punctual challans can be swapped between two months is pinned;
    * a nil-tax month, an obligation already Filed or Completed, another client, firm, quarter and compliance type are not
      moved;
    * a section 192 challan closes nothing (payroll's deposit is a different obligation);
    * no obligations on the calendar, no compliance access and an unplaceable quarter are each said in one sentence (an answer
      about the whole call has no `month`), and a failure never fails the recording of the challan.
"""
from __future__ import annotations

import ast
import inspect
from datetime import date

import pytest

import routers.tds_workspace as tw
from mock_data import MOCK_COMPLIANCE_RECORDS
from repositories.compliance_records_repository import compliance_records_repo
from services import tds_deposit_closes_obligation as closes
from services import compliance_obligation_service as generator
from tests.e2e_harness import FakeDB

FIRM, CLIENT = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
OTHER_CLIENT, OTHER_FIRM = "33333333-3333-4333-8333-333333333333", "44444444-4444-4444-8444-444444444444"
FY = "2025-26"
PARTNER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "a1", "email": "ca@f.test", "role": "Partner"}


@pytest.fixture(autouse=True)
def world(monkeypatch):
    MOCK_COMPLIANCE_RECORDS.clear()
    import services.audit_service as au
    import services.timeline_service as ts
    monkeypatch.setattr(au, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    yield
    MOCK_COMPLIANCE_RECORDS.clear()


def obligation(year, mon, *, status="Not Started", client=CLIENT, firm=FIRM, kind=closes.OBLIGATION_TYPE, ctype="TDS"):
    last = (date(year + (mon == 12), mon % 12 + 1, 1) - date(year, mon, 1)).days
    return compliance_records_repo.create({
        "firm_id": firm, "client_id": client, "compliance_type": ctype, "obligation_type": kind,
        "period_label": f"{kind} {year}-{mon:02d}", "period_start": date(year, mon, 1).isoformat(),
        "period_end": date(year, mon, last).isoformat(), "due_date": date(year + (mon == 12), mon % 12 + 1, 7).isoformat(),
        "status": status})


def now(rec):
    return compliance_records_repo.find_by_id(rec["id"])


def deduction(db, on, tds=10_000_00, section="194C", client=CLIENT, firm=FIRM):
    return db.seed("tds_deductions", {"firm_id": firm, "client_id": client, "section": section, "transaction_date": on,
                                      "payment_amount_paise": tds * 50, "tds_paise": tds, "surcharge_paise": 0, "cess_paise": 0,
                                      "deductee_name": "Vendor"})


def challan(db, quarter, tds, *, section="194C", paid_on="2025-08-05", no="0001", client=CLIENT, firm=FIRM, fy=FY):
    return db.seed("tds_challans", {"firm_id": firm, "client_id": client, "section": section, "challan_no": no,
                                    "bsr_code": "0510001", "financial_year": fy, "quarter": quarter, "tds_paise": tds,
                                    "surcharge_paise": 0, "payment_date": paid_on})


def close(db, row, *, fy=FY, quarter="Q2", client=CLIENT, firm=FIRM, allowed=True, section=None):
    return closes.close_for_recorded_challan(
        db=db, firm_id=firm, client_id=client, financial_year=fy, quarter=quarter, challan_id=row["id"],
        section=section if section is not None else row["section"], actor=PARTNER, may_write_compliance=allowed)


def states(out):
    return {a.get("month"): a["state"] for a in out}


# ── the months of a quarter ──────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("quarter,expected", [
    ("Q1", [(2025, 4), (2025, 5), (2025, 6)]), ("Q2", [(2025, 7), (2025, 8), (2025, 9)]),
    ("Q3", [(2025, 10), (2025, 11), (2025, 12)]), ("Q4", [(2026, 1), (2026, 2), (2026, 3)])])
def test_a_quarters_months_are_the_three_deduction_months_and_q4_crosses_the_year(quarter, expected):
    assert closes.months_of(FY, quarter) == expected


# ── the rule ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_challan_that_pays_the_months_tax_in_full_closes_the_months_obligation_with_its_own_date_and_serial():
    db = FakeDB()
    deduction(db, "2025-07-10")
    ob = obligation(2025, 7)
    c = challan(db, "Q2", 10_000_00, paid_on="2025-08-05", no="00099")
    out = close(db, c)
    assert states(out) == {"2025-07": "closed"} and out[0]["closed"] is True
    rec = now(ob)
    assert rec["status"] == "Filed" and str(rec["filed_date"])[:10] == "2025-08-05"
    assert rec["acknowledgement_no"] == "00099"
    assert out[0]["obligation_id"] == ob["id"] and "TDS deposit (non-salary) July 2025" in out[0]["message"]


def test_a_part_payment_leaves_the_obligation_open_and_says_how_much_is_not_covered():
    db = FakeDB()
    deduction(db, "2025-07-10")
    ob = obligation(2025, 7)
    out = close(db, challan(db, "Q2", 6_000_00))
    assert states(out) == {"2025-07": "not_closed"}
    assert "₹4,000.00" in out[0]["message"] and "July" in out[0]["message"]
    assert "payroll deposits" not in out[0]["message"] and "before the tax was deducted" not in out[0]["message"]
    assert "Record the challan that paid it" in out[0]["message"] and "marked filed from Compliance" not in out[0]["message"]
    assert now(ob)["status"] == "Not Started"


def test_every_section_of_the_month_has_to_be_covered_and_the_last_challan_closes_it_with_its_own_date():
    db = FakeDB()
    deduction(db, "2025-07-10", 10_000_00, "194C")
    deduction(db, "2025-07-12", 4_000_00, "194J")
    ob = obligation(2025, 7)
    first = challan(db, "Q2", 10_000_00, section="194C", paid_on="2025-08-04", no="Z1")
    out = close(db, first)
    assert states(out) == {"2025-07": "not_closed"} and now(ob)["status"] == "Not Started"
    assert "₹4,000.00" in out[0]["message"]
    second = challan(db, "Q2", 4_000_00, section="194J", paid_on="2025-08-06", no="A2")
    out = close(db, second)
    assert states(out) == {"2025-07": "closed"}
    rec = now(ob)
    assert str(rec["filed_date"])[:10] == "2025-08-06" and rec["acknowledgement_no"] == "A2"


def test_recording_the_last_of_three_punctual_challans_closes_all_three_months():
    """July's and August's challans were recorded before the calendar was asked; September's closes September and catches the
    other two up, each with its own date and serial."""
    db = FakeDB()
    for on in ("2025-07-10", "2025-08-10", "2025-09-10"):
        deduction(db, on, 1_000_00)
    obs = [obligation(2025, m) for m in (7, 8, 9)]
    challan(db, "Q2", 1_000_00, paid_on="2025-08-05", no="JUL")
    challan(db, "Q2", 1_000_00, paid_on="2025-09-05", no="AUG")
    out = close(db, challan(db, "Q2", 1_000_00, paid_on="2025-10-05", no="SEP"))
    assert states(out) == {"2025-07": "closed", "2025-08": "closed", "2025-09": "closed"}
    assert [str(now(o)["filed_date"])[:10] for o in obs] == ["2025-08-05", "2025-09-05", "2025-10-05"]
    assert [now(o)["acknowledgement_no"] for o in obs] == ["JUL", "AUG", "SEP"]


def test_first_in_first_out_a_short_challan_closes_the_earliest_month_and_reports_the_next():
    db = FakeDB()
    deduction(db, "2025-07-10", 1_000_00)
    deduction(db, "2025-08-02", 1_000_00)
    july, august = obligation(2025, 7), obligation(2025, 8)
    out = close(db, challan(db, "Q2", 1_500_00, paid_on="2025-08-05"))
    assert states(out) == {"2025-07": "closed", "2025-08": "not_closed"}
    assert now(july)["status"] == "Filed" and now(august)["status"] == "Not Started"
    assert "₹500.00" in [a for a in out if a["month"] == "2025-08"][0]["message"]


def test_a_deposit_made_on_the_due_date_itself_closes_the_month_and_one_a_day_later_does_not():
    for paid_on, expected in (("2025-08-07", "closed"), ("2025-08-08", "not_closed")):
        db = FakeDB()
        deduction(db, "2025-07-10")
        ob = obligation(2025, 7)
        out = close(db, challan(db, "Q2", 10_000_00, paid_on=paid_on))
        assert states(out) == {"2025-07": expected}, paid_on
        assert (now(ob)["status"] == "Filed") is (expected == "closed")


def test_a_late_challan_closes_nothing_by_itself_and_says_why():
    db = FakeDB()
    deduction(db, "2025-07-10")
    ob = obligation(2025, 7)
    out = close(db, challan(db, "Q2", 10_000_00, paid_on="2025-08-20"))
    assert states(out) == {"2025-07": "not_closed"} and now(ob)["status"] == "Not Started"
    message = out[0]["message"]
    assert "2025-08-20" in message and "2025-08-07" in message and "by order within the quarter" in message
    assert "Mark it filed" in message


def test_a_challan_recorded_for_august_cannot_close_july_late_when_julys_tax_was_paid_outside_the_product():
    """The register matches by order within the quarter, and a challan carries a quarter and no month: with only August's
    challan recorded, first in first out gives it to July. July must NOT be closed on it (it would be dated late, and August,
    the month it was for, left open), and nothing about August is said, because the challan paid none of it."""
    db = FakeDB()
    deduction(db, "2025-07-10", 1_000_00)
    deduction(db, "2025-08-10", 1_000_00)
    july, august = obligation(2025, 7), obligation(2025, 8)
    out = close(db, challan(db, "Q2", 1_000_00, paid_on="2025-09-05"))
    assert states(out) == {"2025-07": "not_closed"}
    assert now(july)["status"] == "Not Started" and now(august)["status"] == "Not Started"


def test_a_deposit_made_in_the_month_itself_is_not_refused_as_filed_before_the_period_ended():
    db = FakeDB()
    deduction(db, "2025-07-10")
    ob = obligation(2025, 7)
    out = close(db, challan(db, "Q2", 10_000_00, paid_on="2025-07-12"))
    assert states(out) == {"2025-07": "closed"} and str(now(ob)["filed_date"])[:10] == "2025-07-12"


def test_the_last_day_of_the_month_is_not_yet_over_and_the_next_day_is(monkeypatch):
    for today, expected in ((date(2025, 7, 31), "not_closed"), (date(2025, 8, 1), "closed")):
        db = FakeDB()
        deduction(db, "2025-07-10")
        ob = obligation(2025, 7)
        monkeypatch.setattr(closes, "ist_today", lambda today=today: today)
        out = close(db, challan(db, "Q2", 10_000_00, paid_on="2025-07-12"))
        assert states(out) == {"2025-07": expected}, today
        assert (now(ob)["status"] == "Filed") is (expected == "closed")


def test_a_challan_against_a_demand_is_not_a_deposit_of_the_tax_deducted():
    db = FakeDB()
    deduction(db, "2025-07-10")
    ob = obligation(2025, 7)
    row = challan(db, "Q2", 10_000_00, paid_on="2025-08-05")
    row["minor_head"] = "400"
    out = close(db, row)
    assert states(out) == {"2025-07": "not_closed"} and "minor head 400" in out[0]["message"]
    assert now(ob)["status"] == "Not Started"


def test_a_payment_dated_in_the_future_leaves_the_month_open_with_a_sentence_about_the_challans_date():
    db = FakeDB()
    deduction(db, "2025-07-10")
    ob = obligation(2025, 7)
    out = close(db, challan(db, "Q2", 10_000_00, paid_on="2999-01-01"))
    assert states(out) == {"2025-07": "not_closed"}
    assert "has not happened yet" in out[0]["message"] and "Check the date on the challan" in out[0]["message"]
    assert "filed_date" not in out[0]["message"] and now(ob)["status"] == "Not Started"


def test_a_challan_short_by_fifty_paise_does_not_close_the_month():
    db = FakeDB()
    deduction(db, "2025-07-10", 10_000_00)
    ob = obligation(2025, 7)
    out = close(db, challan(db, "Q2", 10_000_00 - 50, paid_on="2025-08-05"))
    assert states(out) == {"2025-07": "not_closed"} and "₹0.50" in out[0]["message"]
    assert now(ob)["status"] == "Not Started"


def test_two_challans_on_the_last_day_carry_the_highest_serial():
    db = FakeDB()
    deduction(db, "2025-07-10", 3_000_00)
    ob = obligation(2025, 7)
    challan(db, "Q2", 1_000_00, paid_on="2025-08-05", no="A9")
    out = close(db, challan(db, "Q2", 2_000_00, paid_on="2025-08-05", no="B1"))
    assert states(out) == {"2025-07": "closed"} and now(ob)["acknowledgement_no"] == "B1"


def test_a_month_that_is_not_over_is_left_open_because_more_tax_may_still_be_deducted_in_it(monkeypatch):
    db = FakeDB()
    deduction(db, "2025-07-10")
    ob = obligation(2025, 7)
    monkeypatch.setattr(closes, "ist_today", lambda: date(2025, 7, 20))
    out = close(db, challan(db, "Q2", 10_000_00, paid_on="2025-07-12"))
    assert states(out) == {"2025-07": "not_closed"} and "month is not over" in out[0]["message"]
    assert now(ob)["status"] == "Not Started"


def test_a_challan_dated_before_the_deduction_does_not_count_so_the_month_stays_open():
    db = FakeDB()
    deduction(db, "2025-07-20")
    ob = obligation(2025, 7)
    out = close(db, challan(db, "Q2", 10_000_00, paid_on="2025-07-05"))
    assert states(out) == {"2025-07": "not_closed"} and now(ob)["status"] == "Not Started"


def test_recording_a_challan_catches_up_an_earlier_month_that_was_already_fully_deposited():
    """July's challan was recorded before the calendar was asked (nothing closed it); August's challan closes August AND July,
    because a month fully deposited is closed whichever challan made it so."""
    db = FakeDB()
    deduction(db, "2025-07-10", 1_000_00)
    deduction(db, "2025-08-10", 2_000_00)
    july, august = obligation(2025, 7), obligation(2025, 8)
    challan(db, "Q2", 1_000_00, paid_on="2025-08-05", no="JUL")
    aug = challan(db, "Q2", 2_000_00, paid_on="2025-09-04", no="AUG")
    out = close(db, aug)
    assert states(out) == {"2025-07": "closed", "2025-08": "closed"}
    assert str(now(july)["filed_date"])[:10] == "2025-08-05" and now(july)["acknowledgement_no"] == "JUL"
    assert str(now(august)["filed_date"])[:10] == "2025-09-04" and now(august)["acknowledgement_no"] == "AUG"


def test_a_month_of_nil_tax_rows_is_not_closed_because_nothing_was_deposited_to_date_it_by():
    db = FakeDB()
    deduction(db, "2025-07-10", 0)
    ob = obligation(2025, 7)
    other = deduction(db, "2025-08-10", 1_000_00)
    aug = obligation(2025, 8)
    out = close(db, challan(db, "Q2", 1_000_00, paid_on="2025-09-02"))
    assert states(out) == {"2025-08": "closed"}
    assert now(ob)["status"] == "Not Started" and now(aug)["status"] == "Filed" and other


def test_a_month_not_yet_over_that_the_challan_did_not_touch_is_not_mentioned(monkeypatch):
    db = FakeDB()
    deduction(db, "2025-07-10", 1_000_00)
    deduction(db, "2025-09-10", 1_000_00)
    july, september = obligation(2025, 7), obligation(2025, 9)
    monkeypatch.setattr(closes, "ist_today", lambda: date(2025, 9, 20))
    out = close(db, challan(db, "Q2", 1_000_00, paid_on="2025-08-05"))
    assert states(out) == {"2025-07": "closed"}
    assert now(july)["status"] == "Filed" and now(september)["status"] == "Not Started"


# ── what the answer says, and what the rule cannot settle ──────────────────────────────────────────────────────────────

def test_a_closed_month_says_the_date_and_serial_it_recorded_so_that_they_can_be_checked():
    db = FakeDB()
    deduction(db, "2025-07-10")
    ob = obligation(2025, 7)
    out = close(db, challan(db, "Q2", 10_000_00, paid_on="2025-08-05", no="00099"))
    assert out[0]["filed_on"] == "2025-08-05" and out[0]["reference"] == "00099"
    assert "deposited on 2025-08-05, challan 00099" in out[0]["message"] and "check them against the challan" in out[0]["message"]
    assert now(ob)["status"] == "Filed"


def test_two_punctual_challans_can_still_be_swapped_between_two_months_and_the_answer_says_which_it_recorded():
    """THE RESIDUAL THE RULE CANNOT SETTLE, pinned so it is a decision and not a surprise: July's deposit was made late (20 August)
    and August's on 5 August; both are before September's due date, the register matches by order, so it gives the earlier challan
    to July and the later to August, and both months close as punctual. Payment dates cannot separate the two months (a rule that
    tried would also refuse the ordinary deposit on the 5th beside a bill booked on the 2nd); what is done instead is to say the
    date and serial each month was closed on."""
    db = FakeDB()
    deduction(db, "2025-07-10")
    deduction(db, "2025-08-02")
    july, august = obligation(2025, 7), obligation(2025, 8)
    challan(db, "Q2", 10_000_00, paid_on="2025-08-05", no="AUGOWN")
    out = close(db, challan(db, "Q2", 10_000_00, paid_on="2025-08-20", no="JULLATE"))
    assert states(out) == {"2025-07": "closed", "2025-08": "closed"}
    assert (now(july)["acknowledgement_no"], now(august)["acknowledgement_no"]) == ("AUGOWN", "JULLATE")
    assert [a["reference"] for a in out] == ["AUGOWN", "JULLATE"]
    assert all("check them against the challan" in a["message"] for a in out)


def test_a_challan_dated_today_is_not_in_the_future(monkeypatch):
    db = FakeDB()
    deduction(db, "2025-07-10")
    ob = obligation(2025, 7)
    monkeypatch.setattr(closes, "ist_today", lambda: date(2025, 8, 5))
    out = close(db, challan(db, "Q2", 10_000_00, paid_on="2025-08-05"))
    assert states(out) == {"2025-07": "closed"} and now(ob)["status"] == "Filed"


def test_a_month_with_one_ordinary_challan_and_one_against_a_demand_is_left_open():
    db = FakeDB()
    deduction(db, "2025-07-10", 10_000_00)
    ob = obligation(2025, 7)
    challan(db, "Q2", 4_000_00, paid_on="2025-08-04", no="OK")
    demand = challan(db, "Q2", 6_000_00, paid_on="2025-08-05", no="DEMAND")
    demand["minor_head"] = " 400 "
    out = close(db, demand)
    assert states(out) == {"2025-07": "not_closed"} and "minor head 400" in out[0]["message"]
    assert now(ob)["status"] == "Not Started"


def test_a_challan_against_a_demand_for_one_month_does_not_block_another_month():
    db = FakeDB()
    deduction(db, "2025-07-10", 1_000_00, "194C")
    deduction(db, "2025-08-02", 1_000_00, "194J")
    july, august = obligation(2025, 7), obligation(2025, 8)
    challan(db, "Q2", 1_000_00, section="194C", paid_on="2025-08-04", no="C")
    demand = challan(db, "Q2", 1_000_00, section="194J", paid_on="2025-08-05", no="D")
    demand["minor_head"] = "400"
    out = close(db, demand)
    assert states(out) == {"2025-07": "closed", "2025-08": "not_closed"}
    assert now(july)["status"] == "Filed" and now(august)["status"] == "Not Started"


def test_a_month_covered_late_by_an_older_challan_is_not_mentioned_when_this_challan_did_not_touch_it():
    """July was covered late by an earlier challan; a new 194J challan for August says nothing about July."""
    db = FakeDB()
    deduction(db, "2025-07-10", 1_000_00, "194C")
    deduction(db, "2025-08-02", 1_000_00, "194J")
    july, august = obligation(2025, 7), obligation(2025, 8)
    challan(db, "Q2", 1_000_00, section="194C", paid_on="2025-08-20", no="LATE")
    out = close(db, challan(db, "Q2", 1_000_00, section="194J", paid_on="2025-08-05", no="J"))
    assert states(out) == {"2025-08": "closed"}
    assert now(july)["status"] == "Not Started" and now(august)["status"] == "Filed"


def test_the_other_untouched_open_months_stay_silent_for_a_future_dated_and_a_demand_challan_too():
    db = FakeDB()
    deduction(db, "2025-07-10", 1_000_00, "194C")
    deduction(db, "2025-08-02", 1_000_00, "194J")
    future = challan(db, "Q2", 1_000_00, section="194C", paid_on="2999-01-01", no="FUT")
    demand = challan(db, "Q2", 1_000_00, section="194J", paid_on="2025-08-05", no="DEM")
    demand["minor_head"] = "400"
    obligation(2025, 7), obligation(2025, 8)
    out = close(db, challan(db, "Q2", 5_00, section="194H", paid_on="2025-08-05", no="H"))
    assert out == [] and future and demand


def test_a_hand_set_challan_date_before_the_deduction_is_not_a_date_the_tax_went_over_on():
    """A row with `challan_date` 1 June on a July deduction would otherwise close July as deposited on 1 June, before the period
    began, on the strength of an unrelated challan, and the date could not be corrected."""
    db = FakeDB()
    row = deduction(db, "2025-07-10", 1_000_00, "194C")
    row["challan_date"] = "2025-06-01"
    obligation(2025, 7)
    out = close(db, challan(db, "Q2", 5_00, section="194J", paid_on="2025-08-05", no="J"))
    assert out == []


def test_a_zero_tax_row_with_a_stray_hand_set_date_does_not_make_a_month_late():
    db = FakeDB()
    deduction(db, "2025-07-10", 1_000_00, "194C")
    stray = deduction(db, "2025-07-11", 0, "194J")
    stray["challan_date"] = "2025-09-30"
    ob = obligation(2025, 7)
    out = close(db, challan(db, "Q2", 1_000_00, section="194C", paid_on="2025-08-05", no="C"))
    assert states(out) == {"2025-07": "closed"} and str(now(ob)["filed_date"])[:10] == "2025-08-05"


def test_a_challan_dated_before_the_deduction_says_so_beside_the_uncovered_amount():
    db = FakeDB()
    deduction(db, "2025-07-20")
    obligation(2025, 7)
    out = close(db, challan(db, "Q2", 10_000_00, paid_on="2025-07-05"))
    assert "before the tax was deducted" in out[0]["message"] and "check its date" in out[0]["message"]


def test_a_month_not_over_and_a_future_date_each_carry_their_own_remedy():
    db = FakeDB()
    deduction(db, "2025-07-10")
    obligation(2025, 7)
    out = close(db, challan(db, "Q2", 10_000_00, paid_on="2999-01-01"))
    assert "Check the date on the challan" in out[0]["message"]
    assert "marked filed from Compliance" not in out[0]["message"]


# ── what is not moved ────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_month_with_no_tax_is_not_closed_and_a_month_the_challan_did_not_pay_is_not_reported():
    db = FakeDB()
    deduction(db, "2025-07-10")
    july, august, september = obligation(2025, 7), obligation(2025, 8), obligation(2025, 9)
    out = close(db, challan(db, "Q2", 10_000_00))
    assert states(out) == {"2025-07": "closed"}
    assert now(july)["status"] == "Filed"
    assert now(august)["status"] == "Not Started" and now(september)["status"] == "Not Started"


def test_an_obligation_already_filed_keeps_its_own_date_and_is_not_answered():
    db = FakeDB()
    deduction(db, "2025-07-10")
    ob = obligation(2025, 7, status="Filed", )
    compliance_records_repo.update(ob["id"], {"filed_date": "2025-08-01", "acknowledgement_no": "MINE"})
    assert close(db, challan(db, "Q2", 10_000_00)) == []
    rec = now(ob)
    assert str(rec["filed_date"])[:10] == "2025-08-01" and rec["acknowledgement_no"] == "MINE"


def test_nothing_of_another_client_firm_quarter_or_compliance_type_moves():
    db = FakeDB()
    deduction(db, "2025-07-10")
    deduction(db, "2025-10-10")                       # Q3: another quarter
    mine = obligation(2025, 7)
    others = [obligation(2025, 7, client=OTHER_CLIENT), obligation(2025, 7, firm=OTHER_FIRM),
              obligation(2025, 10), obligation(2025, 7, ctype="Payroll", kind="TDS_SALARY_DEPOSIT"),
              obligation(2025, 7, kind="TDS26Q")]
    close(db, challan(db, "Q2", 10_000_00))
    assert now(mine)["status"] == "Filed"
    assert all(now(o)["status"] == "Not Started" for o in others)


def test_another_clients_challan_and_another_quarters_challan_pay_nothing_of_this_month():
    db = FakeDB()
    deduction(db, "2025-07-10")
    ob = obligation(2025, 7)
    stray = [challan(db, "Q2", 10_000_00, client=OTHER_CLIENT), challan(db, "Q3", 10_000_00, no="Q3"),
             challan(db, "Q2", 10_000_00, fy="2024-25", no="OLD"), challan(db, "Q2", 10_000_00, firm=OTHER_FIRM, no="F")]
    for row in stray:
        assert close(db, row) == [] or close(db, row)[0]["state"] != "closed"
    assert now(ob)["status"] == "Not Started"


def test_a_section_192_challan_closes_nothing_and_is_not_answered():
    db = FakeDB()
    deduction(db, "2025-07-10")
    ob = obligation(2025, 7)
    assert close(db, challan(db, "Q2", 10_000_00, section="192")) == []
    assert now(ob)["status"] == "Not Started"


def test_a_section_192_challan_does_not_catch_up_a_month_a_non_salary_challan_already_paid():
    """The catch-up is for a recorded non-salary challan: salary is payroll's, so recording a 192 challan reconciles nothing."""
    db = FakeDB()
    deduction(db, "2025-07-10")
    ob = obligation(2025, 7)
    challan(db, "Q2", 10_000_00, paid_on="2025-08-05", no="EARLIER")
    assert close(db, challan(db, "Q2", 5_00, section="192", no="SAL")) == []
    assert now(ob)["status"] == "Not Started"


def test_a_hand_marked_row_is_dated_by_its_own_challan_date_when_the_register_does_not_cover_it():
    """A row carrying its own `challan_date` and covered by no recorded challan is paid by the worksheet's own reading; the
    month's deposit date is the latest date any row was paid on (here the hand-marked row's, a few days later than the recorded challan's and still on time),
    and no recorded challan was paid on that date, so there is no serial to carry."""
    db = FakeDB()
    marked = deduction(db, "2025-07-10", 2_000_00)
    marked["challan_date"] = "2025-08-06"
    deduction(db, "2025-07-20", 1_000_00, "194J")
    ob = obligation(2025, 7)
    assert states(close(db, challan(db, "Q2", 1_000_00, section="194J", paid_on="2025-08-04", no="J1"))) == {"2025-07": "closed"}
    rec = now(ob)
    assert str(rec["filed_date"])[:10] == "2025-08-06" and not rec.get("acknowledgement_no")


def test_closing_twice_is_the_same_as_closing_once():
    db = FakeDB()
    deduction(db, "2025-07-10")
    ob = obligation(2025, 7)
    c = challan(db, "Q2", 10_000_00, paid_on="2025-08-05")
    assert states(close(db, c)) == {"2025-07": "closed"}
    assert close(db, c) == []
    assert str(now(ob)["filed_date"])[:10] == "2025-08-05"


# ── what is said when it cannot be looked at ─────────────────────────────────────────────────────────────────────────

def test_no_monthly_deposit_obligations_on_the_calendar_is_said_in_one_sentence():
    db = FakeDB()
    deduction(db, "2025-07-10")
    out = close(db, challan(db, "Q2", 10_000_00))
    assert [a["state"] for a in out] == ["not_on_the_calendar"] and "no monthly TDS deposit obligations" in out[0]["message"]


def test_a_caller_without_compliance_access_leaves_the_obligations_open_and_says_so():
    db = FakeDB()
    deduction(db, "2025-07-10")
    ob = obligation(2025, 7)
    out = close(db, challan(db, "Q2", 10_000_00), allowed=False)
    assert [a["state"] for a in out] == ["not_allowed"] and "Compliance" in out[0]["message"]
    assert now(ob)["status"] == "Not Started"


@pytest.mark.parametrize("fy,quarter", [("2025-26", "Q9"), ("", "Q2"), ("2025-26", ""), (None, None)])
def test_a_period_that_cannot_be_placed_is_said_and_nothing_is_closed(fy, quarter):
    db = FakeDB()
    ob = obligation(2025, 7)
    row = challan(db, "Q2", 1_00)
    out = close(db, row, fy=fy, quarter=quarter)
    assert [a["state"] for a in out] == ["not_closed"] and "Compliance" in out[0]["message"]
    assert now(ob)["status"] == "Not Started"


def test_a_challan_with_no_client_is_said_not_matched():
    out = closes.close_for_recorded_challan(db=FakeDB(), firm_id=FIRM, client_id="", financial_year=FY, quarter="Q2",
                                            challan_id="x", section="194C", actor=PARTNER, may_write_compliance=True)
    assert [a["state"] for a in out] == ["not_closed"]


# ── the door ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_helper_the_door_calls_passes_the_challan_and_the_persons_compliance_access(monkeypatch):
    seen = {}
    monkeypatch.setattr(tw, "_USE_MOCK", False)
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_supabase", lambda: "DB")
    monkeypatch.setattr(closes, "close_for_recorded_challan", lambda **kw: seen.update(kw) or [{"state": "closed"}])
    monkeypatch.setattr(tw, "can_user", lambda user, resource, action: (resource, action) == ("compliance", "write"))
    row = {"id": "c1", "client_id": CLIENT, "financial_year": FY, "quarter": "Q2", "section": "194C"}
    assert tw._close_the_deposit_obligations(PARTNER, row) == [{"state": "closed"}]
    assert seen == {"db": "DB", "firm_id": FIRM, "client_id": CLIENT, "financial_year": FY, "quarter": "Q2", "challan_id": "c1",
                    "section": "194C", "actor": PARTNER, "may_write_compliance": True}
    monkeypatch.setattr(tw, "can_user", lambda user, resource, action: False)
    tw._close_the_deposit_obligations(PARTNER, row)
    assert seen["may_write_compliance"] is False


def test_a_failure_closing_an_obligation_never_fails_the_recording_and_is_reported(monkeypatch):
    monkeypatch.setattr(tw, "_USE_MOCK", False)
    import core.observability as obs
    import core.supabase_client as sc
    reported = []
    monkeypatch.setattr(sc, "get_supabase", lambda: "DB")
    monkeypatch.setattr(obs, "capture_soft_failure", lambda exc, **kw: reported.append((str(exc), kw["operation"])))

    def boom(**kw):
        raise RuntimeError("the calendar is down")
    monkeypatch.setattr(closes, "close_for_recorded_challan", boom)
    out = tw._close_the_deposit_obligations(PARTNER, {"id": "c1", "client_id": CLIENT})
    assert [a["state"] for a in out] == ["not_closed"] and "recorded" in out[0]["message"]
    assert reported == [("the calendar is down", "tds_workspace.close_the_deposit_obligations")]


def test_in_memory_mock_mode_has_no_calendar_and_answers_nothing():
    assert tw._USE_MOCK and tw._close_the_deposit_obligations(PARTNER, {"id": "c1", "client_id": CLIENT}) == []


def test_the_challan_door_returns_the_challan_and_what_became_of_the_obligations(monkeypatch):
    """Through the handler: the recorded challan's own fields are still there, and `compliance_obligations` beside them."""
    monkeypatch.setattr(tw, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(tw.timeline_service, "log_timeline_event", lambda *a, **k: None)
    monkeypatch.setattr(tw, "_close_the_deposit_obligations", lambda user, row: [{"state": "closed", "month": "2025-07"}])
    out = tw.create_challan(tw.CreateChallanRequest(
        client_id=CLIENT, bsr_code="0510001", challan_date="2025-08-05", amount_paise=10_000_00, challan_no="0001",
        section="194C", financial_year=FY, quarter="Q2"), PARTNER)
    assert out["success"] is True
    assert out["data"]["challan_no"] == "0001" and out["data"]["tds_paise"] == 10_000_00
    assert out["data"]["compliance_obligations"] == [{"state": "closed", "month": "2025-07"}]


def test_a_month_of_nil_tax_rows_with_a_hand_set_challan_date_is_not_closed_either():
    db = FakeDB()
    row = deduction(db, "2025-07-10", 0)
    row["challan_date"] = "2025-08-01"
    ob = obligation(2025, 7)
    deduction(db, "2025-08-05", 1_000_00)
    aug = obligation(2025, 8)
    out = close(db, challan(db, "Q2", 1_000_00, paid_on="2025-08-20"))
    assert states(out) == {"2025-08": "closed"}
    assert now(ob)["status"] == "Not Started" and now(aug)["status"] == "Filed"


@pytest.mark.parametrize("touched", [True, False])
def test_the_rule_itself_never_closes_a_month_that_has_no_tax_in_it_whatever_dates_it_is_handed(touched):
    """The caller's worksheet gives a nil-tax month no payment dates, so the guard cannot be reached through the door; the
    rule is a pure function that a second caller can hand any dates, and it must still not date a deposit that was never due."""
    decision = closes.decide_month(
        today=date(2025, 10, 1), due=date(2025, 8, 7), month_end=date(2025, 7, 31), what="July 2025 deposit",
        month_name="July 2025", tax_paise=0, outstanding_paise=0, salary_rows=False,
        paid_dates=[date(2025, 8, 1)], challans=[], touched=touched)
    assert decision.filed_on is None and decision.reference is None and decision.sentence is None


def test_a_month_this_challan_did_not_touch_that_stays_open_is_not_mentioned():
    """July's 194J tax is unpaid and over; August's 194C is paid by a 194C challan. The answer is about August alone."""
    db = FakeDB()
    deduction(db, "2025-07-10", 1_000_00, "194J")
    deduction(db, "2025-08-02", 1_000_00, "194C")
    july, august = obligation(2025, 7), obligation(2025, 8)
    out = close(db, challan(db, "Q2", 1_000_00, section="194C", paid_on="2025-08-05"))
    assert states(out) == {"2025-08": "closed"} and now(july)["status"] == "Not Started" and now(august)["status"] == "Filed"


def test_a_completed_obligation_keeps_its_own_acknowledgement():
    db = FakeDB()
    deduction(db, "2025-07-10")
    ob = obligation(2025, 7, status="Completed")
    compliance_records_repo.update(ob["id"], {"acknowledgement_no": "MINE"})
    assert close(db, challan(db, "Q2", 10_000_00, paid_on="2025-08-05")) == []
    assert now(ob)["acknowledgement_no"] == "MINE"


def test_a_hand_keyed_salary_row_that_can_never_be_covered_says_so_instead_of_blaming_the_challans():
    db = FakeDB()
    deduction(db, "2025-07-10", 1_000_00, "194C")
    deduction(db, "2025-07-11", 500_00, "192")
    ob = obligation(2025, 7)
    out = close(db, challan(db, "Q2", 1_000_00, paid_on="2025-08-05"))
    assert states(out) == {"2025-07": "not_closed"} and "payroll deposits salary tax" in out[0]["message"]
    assert now(ob)["status"] == "Not Started"


# ── the closer is tied to the generator, and goes through the one walk ─────────────────────────────────────────────

def test_the_obligation_it_closes_is_the_one_the_generator_emits_for_a_month():
    specs = generator._tds_obligations(FY, False) if hasattr(generator, "_tds_obligations") else []
    deposits = [s for s in specs if s["obligation_type"] == closes.OBLIGATION_TYPE]
    assert len(deposits) == 12
    july = next(s for s in deposits if s["period_start"] == "2025-07-01")
    assert july["compliance_type"] == closes.COMPLIANCE_TYPE and july["period_end"] == "2025-07-31"
    assert july["due_date"] == "2025-08-07"


def test_it_closes_only_through_mark_filed_and_never_writes_a_record_itself():
    tree = ast.parse(inspect.getsource(closes))
    called = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
              for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "mark_filed_and_answer" in called
    assert not called & {"update", "update_record", "create", "insert"}, called & {"update", "update_record", "create", "insert"}
