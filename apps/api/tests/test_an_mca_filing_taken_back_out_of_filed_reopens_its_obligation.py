"""An MCA filing taken back out of Filed reopens the obligation it closed, and the calendar does not reopen one a filing still stands
behind (POST-A-267, item 3).

WHAT WAS WRONG
    An obligation with a filing record behind it could not be reopened at all: the calendar's reopen door accepted the statutory
    deposits only. For the MCA obligations (AOC-4, MGT-7, ADT-1) the record is a workspace filing that an approver CAN move back out
    of Filed, and doing so left the obligation Filed: the workspace said In progress and Deadlines said Filed. The other way round,
    an obligation marked filed from Compliance by mistake, with no workspace filing at all, could never be taken back.

WHAT IS HELD
    * moving a filing back out of Filed reopens the client's obligation for that form and year through the calendar's own reopen
      (audit row, note and reason), and nothing else on the calendar moves;
    * it does not, and says so, when the obligation is not filed, when another filing still records the form filed for the year,
      when a company of the client is still filed among several (the obligation reopens because it is no longer the client's whole
      story) or when the person may not approve compliance;
    * an event form answers as it always did, with no block;
    * the calendar's reopen door refuses an MCA obligation while a filing stands behind it, naming the workspace, and reopens one
      no filing stands behind;
    * the client screen offers the take-back only to someone who may approve MCA filings, and asks first.
"""
from __future__ import annotations

import pathlib

import pytest

import routers.mca_workspace as mw
from core.exceptions import ValidationError
from domain import compliance_record_service as crs
from mock_data import MOCK_COMPLIANCE_RECORDS
from repositories.compliance_records_repository import compliance_records_repo
from services import mca_filing_closes_obligation as closes
from tests.e2e_harness import FakeDB, wire_e2e

FIRM, CLIENT = "firm-1", "client-1"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}
FY = "2025-26"


@pytest.fixture
def world(monkeypatch):
    import services.audit_service as au
    import services.timeline_service as ts
    d = FakeDB()
    MOCK_COMPLIANCE_RECORDS.clear()
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    wire_e2e(monkeypatch, d, [mw])
    audited: list = []
    monkeypatch.setattr(au, "log_event", lambda *a, **k: audited.append((a, k)))
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(mw, "can_access_client", lambda user, client_id: True)
    d.audited = audited
    yield d
    MOCK_COMPLIANCE_RECORDS.clear()


_N = {"n": 0}


def _id(prefix):
    _N["n"] += 1
    return f"{prefix}-{_N['n']}"


def _obligation(otype="MCA_AOC4", start="2025-04-01", end="2026-03-31", status="Not Started", client=CLIENT, **extra):
    return compliance_records_repo.create({
        "firm_id": FIRM, "client_id": client, "compliance_type": "MCA", "obligation_type": otype,
        "period_label": f"{otype} FY {start[:4]}", "period_start": start, "period_end": end, "due_date": "2026-10-30",
        "status": status, **extra})


def _company(db, name):
    return db.seed("mca_companies", {"id": _id("co"), "firm_id": FIRM, "client_id": CLIENT,
                                     "cin": f"U00000MH2020PTC{_N['n']:06d}", "company_name": name, "is_active": True})


def _filing(db, *, form="AOC-4", fy=FY, company=None, client=CLIENT):
    return db.seed("mca_filings", {"id": _id("filing"), "firm_id": FIRM, "client_id": client,
                                   "company_id": (company or {}).get("id"), "form_type": form, "financial_year": fy,
                                   "status": "in_progress", "srn": None, "filed_date": None, "due_date": "2026-10-30"})


def _file(f, user=None):
    return mw.update_filing_status(f["id"], mw.UpdateFilingStatusRequest(
        status="filed", ca_approved=True, srn="T12345678", filing_date="2026-06-15"), current_user=user or USER)


def _take_back(f, user=None, status="in_progress"):
    return mw.update_filing_status(f["id"], mw.UpdateFilingStatusRequest(status=status, ca_approved=True),
                                   current_user=user or USER)


def _now(rec):
    return compliance_records_repo.find_by_id(rec["id"])


def _answer(out):
    return out["data"]["compliance_obligation"]


# ── the workspace's door reopens the obligation ─────────────────────────────

@pytest.mark.parametrize("form, otype", [("AOC-4", "MCA_AOC4"), ("MGT-7", "MCA_MGT7"), ("ADT-1", "MCA_ADT1")])
@pytest.mark.parametrize("to", ["in_progress", "not_started"])
def test_taking_a_filing_back_reopens_its_obligation_through_the_calendars_reopen(world, form, otype, to):
    obligation = _obligation(otype)
    f = _filing(world, form=form)
    _file(f)
    assert _now(obligation)["status"] == "Filed"
    world.audited.clear()

    out = _take_back(f, status=to)

    assert out["success"] is True and out["data"]["status"] == to, "the answer is still the filing"
    answer = _answer(out)
    assert answer["state"] == "reopened" and answer["reopened"] is True and answer["closed"] is False
    assert answer["obligation_id"] == obligation["id"]
    now = _now(obligation)
    assert now["status"] == "Ready To File" and now["filed_date"] is None and now["acknowledgement_no"] is None
    assert f"moved back to {to.replace('_', ' ')} in the MCA workspace" in now["notes"], "the reason kept is the door's sentence"
    reopened = [a for a, _k in world.audited if a[1:4] == ("compliance_record", obligation["id"], "reopened")]
    assert reopened, "the calendar's own reopen writes its audit row"


def test_a_reopened_obligation_is_closed_again_when_the_filing_is_recorded_again(world):
    obligation = _obligation()
    f = _filing(world)
    _file(f)
    _take_back(f)
    out = _file(f)
    assert out["data"]["compliance_obligation"]["state"] == "closed" and _now(obligation)["status"] == "Filed"


def test_nothing_else_on_the_calendar_moves(world):
    other_form = _obligation("MCA_MGT7", status="Filed")
    other_year = _obligation(start="2024-04-01", end="2025-03-31", status="Filed")
    other_client = _obligation(client="client-2", status="Filed")
    target = _obligation()
    f = _filing(world)
    _file(f)
    _take_back(f)
    assert _now(target)["status"] == "Ready To File"
    for untouched in (other_form, other_year, other_client):
        assert _now(untouched)["status"] == "Filed", untouched["period_label"]


# ── what does not reopen it ─────────────────────────────────────────────────

def test_an_obligation_that_is_not_filed_is_left_and_said(world):
    f = _filing(world)
    _file(f)                                     # no obligation yet, so nothing closed
    obligation = _obligation()
    out = _take_back(f)
    assert _answer(out)["state"] == "not_filed_on_the_calendar" and _now(obligation)["status"] == "Not Started"


def test_another_filing_still_filed_for_the_year_keeps_it_filed(world):
    obligation = _obligation()
    first, second = _filing(world), _filing(world)
    _file(first)
    _file(second)
    out = _take_back(first)
    assert _answer(out)["state"] == "still_filed_in_the_workspace" and _now(obligation)["status"] == "Filed"
    out = _take_back(second)
    assert _answer(out)["state"] == "reopened" and _now(obligation)["status"] == "Ready To File"


def test_with_two_companies_taking_one_back_reopens_the_clients_obligation(world):
    a, b = _company(world, "Alpha Pvt Ltd"), _company(world, "Beta Pvt Ltd")
    obligation = _obligation()
    fa, fb = _filing(world, company=a), _filing(world, company=b)
    _file(fa)
    _file(fb)
    assert _now(obligation)["status"] == "Filed"
    out = _take_back(fa)
    assert _answer(out)["state"] == "reopened" and _now(obligation)["status"] == "Ready To File"


def test_a_person_who_may_not_approve_compliance_is_told_and_nothing_moves(world, monkeypatch):
    obligation = _obligation()
    f = _filing(world)
    _file(f)
    real = mw.can_user
    monkeypatch.setattr(mw, "can_user", lambda u, r, a: False if (r, a) == ("compliance", "approve") else real(u, r, a))
    out = _take_back(f)
    assert out["success"] is True and out["data"]["status"] == "in_progress", "the filing still moves"
    answer = _answer(out)
    assert answer["state"] == "not_allowed" and "approval for Compliance" in answer["message"]
    assert _now(obligation)["status"] == "Filed"


@pytest.mark.parametrize("form", ["DIR-12", "MGT-7A"])
def test_a_form_with_no_obligation_answers_as_it_always_did(world, form):
    mgt7 = _obligation("MCA_MGT7")
    f = _filing(world, form=form)
    _file(f)
    out = _take_back(f)
    assert out["success"] is True and "compliance_obligation" not in out["data"]
    assert _now(mgt7)["status"] == "Not Started"


def test_a_move_between_two_unfiled_states_asks_nothing(world):
    obligation = _obligation(status="Filed", filed_date="2026-06-15")
    f = _filing(world)
    out = _take_back(f, status="not_started")
    assert "compliance_obligation" not in out["data"] and _now(obligation)["status"] == "Filed"


def test_a_failure_reopening_never_fails_the_change_and_is_said(world, monkeypatch):
    obligation = _obligation()
    f = _filing(world)
    _file(f)

    def boom(**_k):
        raise RuntimeError("database away")
    monkeypatch.setattr(closes, "reopen_for_unfiled_filing", boom)
    out = _take_back(f)
    assert out["success"] is True and out["data"]["status"] == "in_progress"
    assert _answer(out)["reopened"] is False and "Reopen it from Compliance" in _answer(out)["message"]
    assert _now(obligation)["status"] == "Filed"


# ── the calendar's own reopen door ──────────────────────────────────────────

def test_the_calendar_refuses_an_mca_obligation_while_its_filing_stands_and_names_the_workspace(world):
    obligation = _obligation()
    f = _filing(world)
    _file(f)
    with pytest.raises(ValidationError) as refusal:
        crs.compliance_record_service.reopen_record(obligation["id"], "wrong year", firm_id=FIRM, actor=USER)
    assert "MCA workspace" in refusal.value.message and "AOC-4 for FY 2025-26" in refusal.value.message
    assert _now(obligation)["status"] == "Filed"


def test_the_calendar_reopens_an_mca_obligation_no_filing_stands_behind(world):
    obligation = _obligation(status="Filed", filed_date="2026-06-15", acknowledgement_no="T1")
    out = crs.compliance_record_service.reopen_record(obligation["id"], "marked by mistake", firm_id=FIRM, actor=USER)
    assert out["status"] == "Ready To File" and _now(obligation)["acknowledgement_no"] is None


def test_an_obligation_whose_window_is_not_a_year_has_no_filing_behind_it(world):
    _file(_filing(world))
    odd = _obligation(start="2025-04-01", end="2025-09-30", status="Filed", filed_date="2026-06-15")
    assert crs.compliance_record_service.reopen_record(odd["id"], "wrong", firm_id=FIRM, actor=USER)["status"] == "Ready To File"


def test_every_mca_obligation_type_names_its_form_and_says_what_happens_after():
    assert set(closes.FORM_FOR_OBLIGATION) == crs.REOPENABLE_WHEN_NO_FILING_STANDS
    assert crs.REOPENABLE_WHEN_NO_FILING_STANDS <= set(crs.REOPEN_AFTERMATH)
    assert not crs.REOPENABLE_WHEN_NO_FILING_STANDS & crs.REOPENABLE_OBLIGATION_TYPES


def test_the_mock_deployment_reads_the_routers_own_store(monkeypatch):
    """With no database configured the MCA router keeps filings in its own dictionaries, and the stand check reads them there."""
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setattr(mw, "_MOCK_COMPANIES", {})
    monkeypatch.setattr(mw, "_MOCK_FILINGS", {"x": {"id": "x", "firm_id": FIRM, "client_id": CLIENT, "form_type": "AOC-4",
                                                     "financial_year": FY, "status": "filed"}})
    assert closes.filing_record_stands(FIRM, CLIENT, "MCA_AOC4", FY) is True
    assert closes.filing_record_stands(FIRM, CLIENT, "MCA_MGT7", FY) is False
    assert closes.filing_record_stands("firm-2", CLIENT, "MCA_AOC4", FY) is False


# ── the client screen ───────────────────────────────────────────────────────

def test_the_client_screen_offers_the_take_back_to_an_mca_approver_only_and_asks_first():
    page = (pathlib.Path(__file__).resolve().parents[2] / "web/app/clients/[id]/compliance/mca/page.tsx").read_text()
    offer = page.split('r.status === "filed" && ', 1)
    assert len(offer) == 2 and offer[1].lstrip().startswith("mayApprove"), "offered only to a person who may approve MCA filings"
    body = page.split("async function takeBack", 1)[1].split("\n  }\n", 1)[0]
    assert "await confirmDialog(" in body and body.index("confirmDialog") < body.index("apiFetch(")
    assert "compliance_obligation" in body, "the server's sentence about the obligation is shown"
