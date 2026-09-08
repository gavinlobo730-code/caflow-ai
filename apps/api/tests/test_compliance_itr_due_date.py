"""The ITR due date is decided on the backend, from Explanation 2 to §139(1).

WHAT WAS WRONG
    Three implementations of one statutory date, and all three said 31 July.

    routers/compliance.py's seeder and compliance_obligation_service's ITR
    obligation both called `ce.itr_due_date(fye)` with is_audit defaulting to
    False, so every auto-generated ITR obligation in the product was 31 July
    whatever the client was.

    apps/web/app/income-tax/page.tsx had the only attempt at an answer, and it
    was broken in exactly the place it mattered:

        const AUDIT_ENTITY_TYPES = new Set(["private_limited","public_limited",
                                            "llp","partnership","trust", ...]);
        isAuditCase(t) -> AUDIT_ENTITY_TYPES.has(t?.toLowerCase() ?? "")

    Migration 001's CHECK constraint and ClientFormModal.tsx both store title
    case with a SPACE — 'Private Limited'. toLowerCase() gives
    'private limited', which is not 'private_limited'. So the test failed on
    precisely the two multi-word values, which are precisely the companies;
    'LLP', 'Partnership' and 'Trust' matched by luck. Four of the seven clients
    on this deployment are Private Limited, and Explanation 2(a)(i) to §139(1)
    gives a company 31 October unconditionally.

    It was also wrong in the other direction, and that half is the expensive
    one: the same table asserted that every LLP, partnership firm and trust is
    an audit case. §44AB turns on the year's turnover, an LLP's audit on LLP
    Act 2008 §34(4) with Rule 24(8), a trust's on §12A(1)(b) — none of which
    the product holds. Telling a small firm 31 October when it was due 31 July
    costs §234A interest at 1% a month, a §234F fee of up to ₹5,000, and the
    §80 carry-forward of its losses.

WHAT IS ASSERTED
    That a company is decided and is 31 October; that an audit engagement
    decides it under clause (a)(ii); that everything else is REFUSED — the
    earlier date, `decided` false, and a named gap — rather than guessed; and
    that the entity-type comparison cannot drift from the schema again.

NEGATIVE CONTROL (each of these fails against the previous code)
    * test_a_private_limited_client_is_an_october_case
    * test_the_frontends_underscored_key_is_the_bug_and_both_spellings_now_work
    * test_the_generated_itr_obligation_uses_the_clients_own_date
    * test_the_seeder_stops_giving_every_company_31_july
    * test_an_llp_is_no_longer_asserted_to_be_an_audit_case
    * test_an_undecided_client_is_told_so
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from services import compliance_obligation_service as ob

API_ROOT = Path(__file__).resolve().parents[1]
FY = "2025-26"
FYE = 2026


# ── The comparison key cannot drift from the schema ──────────────────────────

def _entity_types_from_the_check_constraint() -> list[str]:
    """Read clients.entity_type's allowed values straight out of migration 001.

    Parsed rather than restated, because a list written down twice is the bug
    this whole file is about.
    """
    sql = (API_ROOT / "migrations" / "001_initial_schema.sql").read_text(encoding="utf-8")
    m = re.search(r"entity_type TEXT NOT NULL CHECK \(entity_type IN \((.*?)\)\)",
                  sql, re.S)
    assert m, "could not find the entity_type CHECK constraint in migration 001"
    return re.findall(r"'([^']+)'", m.group(1))


def test_the_check_constraints_values_are_the_ones_the_backend_knows():
    """Every spelling the database can hold is a spelling this module has
    classified. A value added to the CHECK without being classified here would
    silently fall to 31 July — which is exactly how a Private Limited client
    came to have a July deadline."""
    assert sorted(_entity_types_from_the_check_constraint()) \
        == sorted(ob.CLIENT_ENTITY_TYPES)


@pytest.mark.parametrize("entity_type", _entity_types_from_the_check_constraint())
def test_every_stored_entity_type_survives_the_round_trip(entity_type):
    """normalise_entity_type must not mangle a value the database can hold, and
    the company test must give the same answer for the stored spelling as for
    the underscored and upper-cased ones."""
    key = ob.normalise_entity_type(entity_type)
    assert key == entity_type.lower()
    assert ob.is_companies_act_company(entity_type) \
        == ob.is_companies_act_company(entity_type.upper()) \
        == ob.is_companies_act_company(entity_type.replace(" ", "_"))


def test_the_frontends_underscored_key_is_the_bug_and_both_spellings_now_work():
    """The whole defect in one assertion. 'Private Limited' is what the CHECK
    constraint and the client form store; 'private_limited' is what the browser
    compared against. Both are the same company now."""
    for spelling in ("Private Limited", "private_limited", "PRIVATE LIMITED",
                     "  private  limited  ", "Public Limited", "public_limited"):
        assert ob.is_companies_act_company(spelling), spelling

    # And the ones that are NOT companies stay not companies — the other half
    # of the old table, which asserted an audit for all of them.
    for spelling in ("LLP", "Partnership", "Trust", "Society",
                     "Proprietorship", "Individual", "", None):
        assert not ob.is_companies_act_company(spelling), spelling


def test_a_company_the_check_does_not_hold_yet_is_still_a_company():
    """One Person Company and Section 8 are companies under the Companies Act
    2013 and are not in migration 001's CHECK. Recognising them here means
    adding either to the schema cannot quietly drop a real company back to
    31 July — the failure this file exists to prevent, arriving by a new
    route."""
    for spelling in ("One Person Company", "one_person_company", "OPC",
                     "Section 8", "section 8 company"):
        assert ob.is_companies_act_company(spelling), spelling


# ── Explanation 2 to §139(1) ─────────────────────────────────────────────────

def test_a_private_limited_client_is_an_october_case():
    """Explanation 2(a)(i): a COMPANY is 31 October, whatever its turnover."""
    r = ob.itr_due_date_for_client(FY, "Private Limited")
    assert r["due_date"] == "2026-10-31"
    assert r["is_audit"] is True and r["decided"] is True
    assert r["statutory_gaps"] == []
    assert "2(a)(i)" in r["basis"]


def test_a_public_limited_client_is_an_october_case():
    r = ob.itr_due_date_for_client(FY, "Public Limited")
    assert r["due_date"] == "2026-10-31" and r["decided"] is True


def test_an_audit_engagement_decides_it_for_a_non_company():
    """Explanation 2(a)(ii): accounts required to be audited under this Act or
    any other law. A firm that holds an audit engagement for the client has
    said so."""
    r = ob.itr_due_date_for_client(FY, "Partnership", has_tax_audit_engagement=True)
    assert r["due_date"] == "2026-10-31"
    assert r["decided"] is True and r["statutory_gaps"] == []
    assert "2(a)(ii)" in r["basis"]


def test_a_transfer_pricing_report_outranks_both():
    """Explanation 2(aa): 30 November, and it beats the company date — a
    company with a §92E report is 30 November, not 31 October."""
    r = ob.itr_due_date_for_client(FY, "Private Limited",
                                   has_transfer_pricing_report=True)
    assert r["due_date"] == "2026-11-30" and r["decided"] is True
    assert "2(aa)" in r["basis"]


def test_an_llp_is_no_longer_asserted_to_be_an_audit_case():
    """The old table said every LLP is audited. An LLP's audit is LLP Act 2008
    §34(4) with Rule 24(8) — turnover above ₹40 lakh or contribution above
    ₹25 lakh — and neither figure is held against a client."""
    r = ob.itr_due_date_for_client(FY, "LLP")
    assert r["is_audit"] is False and r["decided"] is False
    assert r["due_date"] == "2026-07-31"


@pytest.mark.parametrize("entity_type", ["LLP", "Partnership", "Trust",
                                         "Society", "Proprietorship", "Individual"])
def test_an_undecided_client_is_told_so(entity_type):
    """Refused, not guessed. The date is the EARLIER of the two — being chased
    early costs nothing, being told a date that has passed costs §234A interest,
    a §234F fee and the §80 carry-forward — and the gap names what would settle
    it."""
    r = ob.itr_due_date_for_client(FY, entity_type)
    assert r["due_date"] == "2026-07-31"
    assert r["decided"] is False
    assert len(r["statutory_gaps"]) == 1
    gap = r["statutory_gaps"][0]
    assert entity_type in gap
    assert "44AB" in gap and "31 October" in gap


def test_an_unrecorded_entity_type_is_a_different_gap_from_a_known_one():
    """A client whose entity type nobody filled in and a partnership firm are
    both undecided, and they are undecided for different reasons. A zero and
    'we do not know' must not read the same."""
    r = ob.itr_due_date_for_client(FY, None)
    assert r["due_date"] == "2026-07-31" and r["decided"] is False
    assert "entity type is not recorded" in r["statutory_gaps"][0]
    assert r["statutory_gaps"] != ob.itr_due_date_for_client(FY, "Partnership")["statutory_gaps"]


def test_the_fy_boundary_is_the_return_year_not_the_period_year():
    """FY 2025-26 ends 31 March 2026, so its return is due in 2026 — the
    assessment year — not 2025."""
    assert ob.itr_due_date_for_client("2025-26", "Private Limited")["due_date"] == "2026-10-31"
    assert ob.itr_due_date_for_client("2026-27", "Private Limited")["due_date"] == "2027-10-31"
    assert ob.itr_due_date_for_client("2026-27", "Individual")["due_date"] == "2027-07-31"


# ── The obligation the generator writes ──────────────────────────────────────

def test_the_generated_itr_obligation_uses_the_clients_own_date():
    company = ob.obligations_for_service("Income Tax Return", FY,
                                         entity_type="Private Limited")
    assert len(company) == 1
    assert company[0]["obligation_type"] == "ITR"
    assert company[0]["due_date"] == "2026-10-31"
    assert "statutory_gaps" not in company[0]

    firm = ob.obligations_for_service("Income Tax Return", FY,
                                      entity_type="Partnership")
    assert firm[0]["due_date"] == "2026-07-31"
    assert firm[0]["statutory_gaps"], "an assumed date must carry its gap"


def test_an_engagement_that_names_an_audit_answers_its_own_question():
    """One engagement called 'Income Tax Return and Tax Audit' establishes the
    audit itself; it must not need a second engagement to be found first."""
    specs = ob.obligations_for_service("Income Tax Return and Tax Audit", FY,
                                       entity_type="Partnership")
    itr = next(s for s in specs if s["obligation_type"] == "ITR")
    assert itr["due_date"] == "2026-10-31"
    assert "statutory_gaps" not in itr


def test_the_defaults_still_reproduce_the_previous_behaviour():
    """Every existing caller that names no entity type keeps generating exactly
    what it generated before — 31 July — but now says it is assumed."""
    specs = ob.obligations_for_service("Income Tax Return", FY)
    assert specs[0]["due_date"] == "2026-07-31"
    assert specs[0]["statutory_gaps"]


def test_itr_obligation_refuses_a_positional_boolean():
    """The parameter that used to sit here was `is_audit: bool`. A positional
    True would now be read as an entity type named 'True' and silently give
    31 July, so the signature is keyword-only."""
    with pytest.raises(TypeError):
        ob._itr_obligation(FY, True)          # type: ignore[misc]


# ── End to end, through the API ──────────────────────────────────────────────

FIRM = "F-ITR-1"
PARTNER = {"id": "u1", "firm_id": FIRM, "role": "Partner",
           "email": "ca@f", "auth_user_id": "au1"}


@pytest.fixture()
def api(monkeypatch):
    """A TestClient over the compliance router alone, with the caller stubbed —
    the dominant convention in this suite (38 of 43 TestClient modules)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.auth import get_current_user
    from routers.compliance import router as compliance_router
    import services.audit_service as au
    import services.timeline_service as ts

    monkeypatch.setattr(au, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)

    app = FastAPI()
    app.include_router(compliance_router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def a_client():
    """One client of a chosen entity type, in the mock store, cleaned up after."""
    from repositories.client_repository import client_repo
    from mock_data import MOCK_CLIENTS, CLIENT_INDEX
    snapshot = list(MOCK_CLIENTS)
    made: list[str] = []

    def make(entity_type: str) -> str:
        row = client_repo.create({"firm_id": FIRM, "client_name": "Test Co",
                                  "entity_type": entity_type})
        made.append(row["id"])
        return row["id"]

    yield make
    MOCK_CLIENTS[:] = snapshot
    CLIENT_INDEX.clear()
    CLIENT_INDEX.update({c["id"]: c for c in MOCK_CLIENTS})


@pytest.fixture(autouse=True)
def _no_seeded_tasks_leak():
    from mock_data import MOCK_COMPLIANCE_TASKS
    snapshot = list(MOCK_COMPLIANCE_TASKS)
    yield
    MOCK_COMPLIANCE_TASKS[:] = snapshot


def test_the_endpoint_answers_for_a_named_client(api, a_client):
    cid = a_client("Private Limited")
    r = api.get("/api/compliance/itr-due-date",
                params={"client_id": cid, "financial_year": FY})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["data"]["due_date"] == "2026-10-31"
    assert body["data"]["decided"] is True
    assert body["data"]["entity_type"] == "Private Limited"
    assert body["data"]["statutory_gaps"] == []


def test_the_endpoint_refuses_a_year_that_is_not_a_financial_year(api, a_client):
    """FYLabel must actually be applied — `fy: FYLabel = Query(...)` validates
    NOTHING (CLAUDE.md), so this is the check that it was written as
    Annotated[FYLabel, Query(...)]. '2025-99' passes a ^\\d{4}-\\d{2}$ shape
    regex and then silently means 2025-26."""
    cid = a_client("Private Limited")
    r = api.get("/api/compliance/itr-due-date",
                params={"client_id": cid, "financial_year": "2025-99"})
    assert r.status_code == 422

    # And the long spelling is accepted and canonicalised, not rejected.
    ok = api.get("/api/compliance/itr-due-date",
                 params={"client_id": cid, "financial_year": "2025-2026"})
    assert ok.status_code == 200
    assert ok.json()["data"]["financial_year"] == "2025-26"


def test_the_endpoint_reports_the_gap_rather_than_a_confident_date(api, a_client):
    cid = a_client("Partnership")
    body = api.get("/api/compliance/itr-due-date",
                   params={"client_id": cid, "financial_year": FY}).json()["data"]
    assert body["due_date"] == "2026-07-31"
    assert body["decided"] is False
    assert body["statutory_gaps"]


def test_the_client_read_is_firm_scoped(api, a_client):
    """The endpoint guards with assert_client_access (which is a no-op in mock
    mode, so it cannot be exercised here), and itr_profile_for reads the client
    FIRM-SCOPED underneath it. So even with the guard stubbed out, another
    firm's entity type does not leak into the answer: the read misses and the
    date comes back undecided rather than as that firm's 31 October."""
    from repositories.client_repository import client_repo
    other = client_repo.create({"firm_id": "SOME-OTHER-FIRM",
                                "client_name": "Not mine",
                                "entity_type": "Private Limited"})
    assert ob.itr_profile_for(other["id"], FIRM) == (None, False)

    body = api.get("/api/compliance/itr-due-date",
                   params={"client_id": other["id"], "financial_year": FY}).json()["data"]
    assert body["entity_type"] is None
    assert body["decided"] is False

    import inspect
    from routers import compliance as compliance_router_module
    src = inspect.getsource(compliance_router_module.itr_due_date_for_one_client)
    assert "assert_client_access" in src, (
        "the endpoint takes a client_id, so it must go through the shared "
        "assignment/firm guard rather than a bespoke check")


def test_the_seeder_stops_giving_every_company_31_july(api, a_client):
    """routers/compliance.py's /seed wrote itr_due_date(fy_end) — 31 July — for
    every client it ever seeded, companies included."""
    cid = a_client("Private Limited")
    r = api.post("/api/compliance/seed",
                 params={"client_id": cid, "financial_year": FY})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    itr = [t for t in data["tasks"] if t["compliance_type"] == "ITR"]
    assert len(itr) == 1
    assert itr[0]["due_date"] == "2026-10-31"
    assert "statutory_gaps" not in data
    assert "2(a)(i)" in data["itr_due_date_basis"]


def test_the_seeder_reports_an_assumed_date(api, a_client):
    cid = a_client("Proprietorship")
    data = api.post("/api/compliance/seed",
                    params={"client_id": cid, "financial_year": FY}).json()["data"]
    itr = [t for t in data["tasks"] if t["compliance_type"] == "ITR"]
    assert itr[0]["due_date"] == "2026-07-31"
    assert data["statutory_gaps"], "an assumed date must be reported, not seeded silently"


def test_the_period_calculator_no_longer_states_an_itr_date_as_fact(api):
    """It names no assessee at all, so Explanation 2 cannot be applied to it.
    It used to return itr_due_date(fy_end) with no qualification."""
    body = api.get("/api/compliance/due-dates/calculate",
                   params={"year": 2025, "month": 5}).json()["data"]
    assert body["itr_due_date"] == "2026-07-31"
    assert body["itr_due_date_decided"] is False
    assert body["itr_statutory_gaps"]


# ── The generator surfaces it too ────────────────────────────────────────────

def test_generate_for_engagement_reports_an_assumed_itr_date(monkeypatch):
    """The daily scheduler runs this. A gap that only reaches a log is the
    failure this shape was invented to fix."""
    from repositories.client_repository import client_repo
    from repositories.compliance_records_repository import compliance_records_repo
    from mock_data import MOCK_COMPLIANCE_RECORDS
    import services.audit_service as au
    import services.timeline_service as ts

    monkeypatch.setattr(au, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    MOCK_COMPLIANCE_RECORDS.clear()

    firm = "F-ITR-GEN"
    company = client_repo.create({"firm_id": firm, "client_name": "Co",
                                  "entity_type": "Private Limited"})
    firm_client = client_repo.create({"firm_id": firm, "client_name": "Firm",
                                      "entity_type": "Partnership"})

    res = ob.generate_for_engagement(
        firm, {"id": "e1", "client_id": company["id"],
               "service_type": "Income Tax Return"}, FY)
    assert "statutory_gaps" not in res
    rec = [r for r in MOCK_COMPLIANCE_RECORDS if r["obligation_type"] == "ITR"][0]
    assert rec["due_date"] == "2026-10-31"

    MOCK_COMPLIANCE_RECORDS.clear()
    res2 = ob.generate_for_engagement(
        firm, {"id": "e2", "client_id": firm_client["id"],
               "service_type": "Income Tax Return"}, FY)
    assert res2["statutory_gaps"], "an assumed date must be reported"
    rec2 = [r for r in MOCK_COMPLIANCE_RECORDS if r["obligation_type"] == "ITR"][0]
    assert rec2["due_date"] == "2026-07-31"
    MOCK_COMPLIANCE_RECORDS.clear()


def test_the_gap_is_still_reported_on_the_second_run(monkeypatch):
    """Generation is idempotent, so the second run SKIPS the ITR row. The date
    on that row is still assumed, so the gap must still be reported — a warning
    that disappears once the row exists is a warning nobody ever sees."""
    from repositories.client_repository import client_repo
    from mock_data import MOCK_COMPLIANCE_RECORDS
    import services.audit_service as au
    import services.timeline_service as ts

    monkeypatch.setattr(au, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    MOCK_COMPLIANCE_RECORDS.clear()

    firm = "F-ITR-IDEM"
    c = client_repo.create({"firm_id": firm, "client_name": "Firm",
                            "entity_type": "LLP"})
    eng = {"id": "e1", "client_id": c["id"], "service_type": "Income Tax Return"}
    first = ob.generate_for_engagement(firm, eng, FY)
    second = ob.generate_for_engagement(firm, eng, FY)
    assert second["generated"] == 0 and second["skipped"] == first["generated"]
    assert second["statutory_gaps"] == first["statutory_gaps"]
    MOCK_COMPLIANCE_RECORDS.clear()


# ── The s.44AB specified date is not the return's date ──────────────────────

def test_the_audit_report_is_due_a_month_before_the_return():
    """IT Act s.44AB, Explanation (ii), as substituted by the Finance Act 2020
    with effect from AY 2020-21: the "specified date" is "date one month prior
    to the due date for furnishing the return of income under sub-section (1)
    of section 139".

    The generator dated the report at the RETURN's 31 October, so every audit
    client's calendar showed it a month late — on the obligation whose lateness
    carries s.271B, 0.5% of turnover capped at Rs 1,50,000. It is also the
    wrong sequence: s.139(1)'s own date assumes the report is already on
    record.
    """
    from services import compliance_engine as ce

    for fye in (2026, 2027, 2028):
        report = ce.tax_audit_report_due_date(fye)
        assert report == date(fye, 9, 30)
        assert report < ce.itr_due_date(fye, is_audit=True)


def test_the_report_date_is_derived_from_the_return_date_not_stated():
    """Explanation (ii) defines this date BY REFERENCE to s.139(1). If a CBDT
    notification moves the return, the report has to move with it — which a
    literal 30 September would not."""
    from datetime import date as _date

    from services import compliance_engine as ce

    real = ce.itr_due_date
    try:
        ce.itr_due_date = lambda fye, **kw: _date(fye, 12, 31)   # a hypothetical extension
        assert ce.tax_audit_report_due_date(2027) == _date(2027, 11, 30)
    finally:
        ce.itr_due_date = real


def test_one_month_before_clamps_to_the_shorter_month():
    """31 October has no counterpart on 31 September, and the statute says a
    DATE one month prior rather than "thirty days"."""
    from datetime import date as _date

    from services.compliance_engine import _one_month_before

    assert _one_month_before(_date(2026, 10, 31)) == _date(2026, 9, 30)
    assert _one_month_before(_date(2026, 3, 31)) == _date(2026, 2, 28)
    assert _one_month_before(_date(2028, 3, 31)) == _date(2028, 2, 29)   # leap
    assert _one_month_before(_date(2026, 1, 15)) == _date(2025, 12, 15)  # year boundary


def test_the_generated_obligation_carries_the_specified_date():
    """The engine being right is not enough — the calendar row is what a CA
    reads."""
    from services import compliance_obligation_service as ob

    audit = ob.obligations_for_service("Statutory Audit", "2025-26")
    assert [s["obligation_type"] for s in audit] == ["TAX_AUDIT"]
    assert audit[0]["due_date"] == "2026-09-30"
