"""
Form 27Q in the compliance calendar, and why it is conditional.

Rule 31A(4) splits the quarterly TDS statement by the payee's residence: (a)
26Q for the non-salary payments to residents, (b) 27Q for the payments to
non-residents. They are separate returns filed separately, on the same due
dates — Rule 31A(2) sets one date per quarter regardless of form.

The calendar generated only 26Q, for every TDS engagement, because nothing in
the schema recorded whether a client paid a non-resident. Migration 308 records
it, so 27Q can now be generated for the clients that owe it AND ONLY THOSE.

Generating it unconditionally is the failure this guards against: four extra
deadlines a year in the calendar of every client that has never paid a foreign
supplier. services/compliance_obligation_service already applies that reasoning
to IFF ("an obligation nobody owes, appearing every month, is how a compliance
calendar stops being read"); this is the same rule for the same reason.
"""
from __future__ import annotations

import pytest

from services import compliance_obligation_service as ob

FY = "2025-26"


# ── What is generated ────────────────────────────────────────────────────────

def test_a_client_with_no_non_resident_vendor_gets_only_26q():
    """The unchanged case, which is nearly every Indian practice."""
    specs = ob._tds_obligations(FY, has_non_resident_vendors=False)
    assert [s["obligation_type"] for s in specs] == ["TDS26Q"] * 4


def test_the_default_is_no_27q():
    """Every existing caller keeps generating exactly what it generated before."""
    assert ob._tds_obligations(FY) == ob._tds_obligations(FY, has_non_resident_vendors=False)


def test_a_client_that_pays_a_non_resident_gets_both_statements():
    specs = ob._tds_obligations(FY, has_non_resident_vendors=True)
    assert len(specs) == 8
    assert sum(1 for s in specs if s["obligation_type"] == "TDS26Q") == 4
    assert sum(1 for s in specs if s["obligation_type"] == "TDS27Q") == 4


def test_27q_never_replaces_26q():
    """A client paying a non-resident still pays residents too. 27Q is an
    ADDITIONAL return, not a different one — unlike QRMP, where a quarterly
    filer owes a different set rather than the same set less often."""
    specs = ob._tds_obligations(FY, has_non_resident_vendors=True)
    assert sum(1 for s in specs if s["obligation_type"] == "TDS26Q") == 4


# ── The dates, which are the same and must stay the same ─────────────────────

def test_27q_shares_26q_s_due_date_quarter_by_quarter():
    """Rule 31A(2) gives one due date per quarter regardless of form. Two
    separate date computations would eventually drift; this pins them equal."""
    specs = ob._tds_obligations(FY, has_non_resident_vendors=True)
    by_period: dict[str, set] = {}
    for s in specs:
        by_period.setdefault(s["period_start"], set()).add(s["due_date"])
    assert len(by_period) == 4, "four quarters"
    for period, dues in by_period.items():
        assert len(dues) == 1, f"26Q and 27Q disagree on the due date for {period}"


def test_q4_is_31_may_for_27q_too():
    """The exception worth pinning: Q4 is NOT the end of the month following
    quarter end. services/compliance_engine.tds_return_due_date is the
    authority, and 27Q must inherit it rather than re-derive it."""
    specs = ob._tds_obligations(FY, has_non_resident_vendors=True)
    q4 = [s for s in specs if s["period_start"] == "2026-01-01"]
    assert {s["due_date"] for s in q4} == {"2026-05-31"}


def test_the_periods_are_the_same_four_quarters():
    specs = ob._tds_obligations(FY, has_non_resident_vendors=True)
    q27 = sorted(s["period_start"] for s in specs if s["obligation_type"] == "TDS27Q")
    q26 = sorted(s["period_start"] for s in specs if s["obligation_type"] == "TDS26Q")
    assert q27 == q26 == ["2025-04-01", "2025-07-01", "2025-10-01", "2026-01-01"]


def test_the_label_names_the_form_and_the_quarter():
    """The calendar shows this string. "TDS Q3" beside another "TDS Q3" is two
    rows a CA cannot tell apart."""
    specs = ob._tds_obligations(FY, has_non_resident_vendors=True)
    labels = {s["period_label"] for s in specs}
    assert "TDS 27Q Q3 FY 2025-26" in labels
    assert "TDS 26Q Q3 FY 2025-26" in labels


def test_both_statements_are_filed_under_the_tds_compliance_type():
    specs = ob._tds_obligations(FY, has_non_resident_vendors=True)
    assert {s["compliance_type"] for s in specs} == {"TDS"}


# ── Routing through the service selector ─────────────────────────────────────

def test_a_tds_engagement_carries_the_flag_through():
    plain = ob.obligations_for_service("TDS Compliance", FY)
    assert [s["obligation_type"] for s in plain] == ["TDS26Q"] * 4

    with_nr = ob.obligations_for_service("TDS Compliance", FY,
                                         client_has_non_resident_vendors=True)
    assert sum(1 for s in with_nr if s["obligation_type"] == "TDS27Q") == 4


def test_a_non_tds_engagement_gets_no_27q_however_the_flag_is_set():
    """A GST-only engagement with a foreign supplier owes no TDS statement from
    this firm. The flag says the client PAYS a non-resident, not that this
    engagement covers TDS."""
    gst = ob.obligations_for_service("GST Compliance", FY,
                                     client_has_non_resident_vendors=True)
    assert not any(s["obligation_type"].startswith("TDS") for s in gst)


def test_the_no_engagement_fallback_generates_no_tds_at_all():
    """generate_default_for_client is GST-only by design — its docstring says
    ITR/TDS/MCA stay engagement-scoped. 27Q must not be the exception that
    quietly gives a client an obligation nobody engaged the firm for."""
    import inspect
    src = inspect.getsource(ob.generate_default_for_client)
    assert "_tds_obligations" not in src


# ── The lookup ───────────────────────────────────────────────────────────────

def test_an_unclassified_vendor_does_not_make_a_27q_obligation(monkeypatch):
    """NULL residential_status means nobody has established it — which is every
    vendor that predates migration 308. Counting those as non-resident would
    give 27Q to every client in every firm on the first run."""
    from routers import vendors as vr
    monkeypatch.setattr(vr, "MOCK_VENDORS", [
        {"id": "v1", "firm_id": "f1", "client_id": "c1", "name": "Legacy"},
        {"id": "v2", "firm_id": "f1", "client_id": "c1", "name": "R",
         "residential_status": "resident"},
    ])
    assert ob.has_non_resident_vendors("c1", "f1") is False


def test_one_non_resident_vendor_is_enough(monkeypatch):
    from routers import vendors as vr
    monkeypatch.setattr(vr, "MOCK_VENDORS", [
        {"id": "v1", "firm_id": "f1", "client_id": "c1", "residential_status": "resident"},
        {"id": "v2", "firm_id": "f1", "client_id": "c1", "residential_status": "non_resident"},
    ])
    assert ob.has_non_resident_vendors("c1", "f1") is True


def test_another_clients_non_resident_vendor_does_not_count(monkeypatch):
    """client is the accounting entity; the obligation is client-scoped."""
    from routers import vendors as vr
    monkeypatch.setattr(vr, "MOCK_VENDORS", [
        {"id": "v1", "firm_id": "f1", "client_id": "c2", "residential_status": "non_resident"},
    ])
    assert ob.has_non_resident_vendors("c1", "f1") is False


def test_another_firms_vendor_does_not_count(monkeypatch):
    """firm is the tenant. A vendor row reachable only because the id matched
    would leak one firm's data into another firm's calendar."""
    from routers import vendors as vr
    monkeypatch.setattr(vr, "MOCK_VENDORS", [
        {"id": "v1", "firm_id": "OTHER", "client_id": "c1", "residential_status": "non_resident"},
    ])
    assert ob.has_non_resident_vendors("c1", "f1") is False


def test_a_failed_vendor_read_generates_no_27q_rather_than_a_phantom_one(monkeypatch):
    """The opposite safe direction from gst_profile_for, deliberately. There an
    unknown frequency defaults to monthly because monthly is chased EARLIER and
    s.47 charges nothing for early. Here the choice is a missing reminder
    versus a phantom obligation on every client, and phantom deadlines are what
    make the real ones invisible."""
    import services.compliance_obligation_service as m

    class _Boom:
        def table(self, *a, **k):
            raise RuntimeError("vendors unreachable")

    monkeypatch.setattr(m, "_USE_MOCK", False)
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_supabase", lambda: _Boom())
    assert m.has_non_resident_vendors("c1", "f1") is False


def test_the_existence_check_does_not_read_a_row_per_vendor():
    """A calendar that reads every vendor of every client to answer a yes/no
    question is the reporting rule in CLAUDE.md turned upside down."""
    import inspect
    src = inspect.getsource(ob.has_non_resident_vendors)
    assert ".limit(1)" in src


# ── End to end through the generator ────────────────────────────────────────

@pytest.fixture()
def _clean(monkeypatch):
    """Same isolation as tests/test_compliance_engagement.py's fixture."""
    from mock_data import (MOCK_COMPLIANCE_RECORDS, MOCK_ENGAGEMENTS,
                           ENGAGEMENT_INDEX, MOCK_CLIENTS, CLIENT_INDEX)
    import services.audit_service as au
    import services.timeline_service as ts
    from routers import vendors as vr

    MOCK_COMPLIANCE_RECORDS.clear()
    MOCK_ENGAGEMENTS.clear()
    ENGAGEMENT_INDEX.clear()
    clients = list(MOCK_CLIENTS)
    monkeypatch.setattr(au, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(vr, "MOCK_VENDORS", [])
    yield
    MOCK_COMPLIANCE_RECORDS.clear()
    MOCK_ENGAGEMENTS.clear()
    ENGAGEMENT_INDEX.clear()
    MOCK_CLIENTS[:] = clients
    CLIENT_INDEX.clear()
    CLIENT_INDEX.update({c["id"]: c for c in MOCK_CLIENTS})


def _tds_engagement(client="CL-27Q"):
    from repositories.engagement_repository import engagement_repo
    return engagement_repo.create({
        "firm_id": "F1", "client_id": client, "service_type": "TDS Compliance",
        "status": "Active", "assigned_to": "prep-1", "reviewer_id": "rev-1",
        "partner_id": "ptr-1",
    })


def _generated_types(client="CL-27Q"):
    from repositories.compliance_records_repository import compliance_records_repo
    return sorted(r["obligation_type"]
                  for r in compliance_records_repo.find_all(firm_id="F1", client_id=client))


def test_a_tds_engagement_with_no_foreign_supplier_generates_four_records(_clean):
    ob.generate_for_engagement("F1", _tds_engagement(), FY)
    assert _generated_types() == ["TDS26Q"] * 4


def test_a_tds_engagement_with_a_foreign_supplier_generates_eight(_clean, monkeypatch):
    from routers import vendors as vr
    monkeypatch.setattr(vr, "MOCK_VENDORS", [
        {"id": "v1", "firm_id": "F1", "client_id": "CL-27Q",
         "name": "Helvetica Design AG", "residential_status": "non_resident",
         "country_of_residence": "CH"},
    ])
    ob.generate_for_engagement("F1", _tds_engagement(), FY)
    assert _generated_types() == ["TDS26Q"] * 4 + ["TDS27Q"] * 4


def test_generation_stays_idempotent_with_both_statements(_clean, monkeypatch):
    """The dedup key is (obligation_type, period_start). 26Q and 27Q share a
    period_start, so a key that did not include the type would generate one and
    skip the other — silently, and differently on every run."""
    from routers import vendors as vr
    monkeypatch.setattr(vr, "MOCK_VENDORS", [
        {"id": "v1", "firm_id": "F1", "client_id": "CL-27Q",
         "residential_status": "non_resident"},
    ])
    eng = _tds_engagement()
    first = ob.generate_for_engagement("F1", eng, FY)
    assert first["generated"] == 8 and first["skipped"] == 0
    again = ob.generate_for_engagement("F1", eng, FY)
    assert again["generated"] == 0 and again["skipped"] == 8
    assert len(_generated_types()) == 8


def test_marking_a_vendor_non_resident_later_adds_27q_on_the_next_run(_clean, monkeypatch):
    """The realistic sequence: the calendar is generated in April, and the
    foreign supplier is onboarded in August. generate_due runs again and the
    four 27Q rows appear without disturbing the 26Q ones already worked on."""
    from routers import vendors as vr
    eng = _tds_engagement()
    ob.generate_for_engagement("F1", eng, FY)
    assert _generated_types() == ["TDS26Q"] * 4

    monkeypatch.setattr(vr, "MOCK_VENDORS", [
        {"id": "v1", "firm_id": "F1", "client_id": "CL-27Q",
         "residential_status": "non_resident"},
    ])
    res = ob.generate_for_engagement("F1", eng, FY)
    assert res["generated"] == 4 and res["skipped"] == 4
    assert _generated_types() == ["TDS26Q"] * 4 + ["TDS27Q"] * 4
