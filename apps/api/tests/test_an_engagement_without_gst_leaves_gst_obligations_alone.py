"""An engagement that has no GST leg does not delete the client's GST obligations.

WHAT WAS WRONG
    `generate_for_engagement` reconciled the client's GSTR-1 / GSTR-3B / PMT-06 rows against the specs of the
    engagement it was running. That is right for the engagement that owns the GST leg: a filing-frequency switch
    (Rule 61A) leaves rows of the old shape that must go. It is wrong for any other engagement. An ITR, TDS or
    payroll engagement has no GST specs, so to it every GST row "matched no current spec" and every Not Started one
    was soft-deleted, including the rows the client's GST engagement had just generated.

    Measured on a migrated Postgres + PostgREST stack for a client with a GST and an ITR engagement: 26
    obligations; generate the ITR engagement and 2 remain (24 GST rows gone). `generate_due`, which the daily sweep
    calls, then deleted and recreated the 24 on every run ("generated 24, skipped 2", twice running), and which rows
    survived depended on the order the engagements happened to be read in.

THE RULE
    Only an engagement that names GST reconciles GST rows. `_reconcile_stale_gst_obligations` takes
    `owns_the_gst_leg` as a required keyword (no default, so a new caller has to decide), and when it is False
    reads and deletes nothing. A frequency switch still reconciles, through the engagement that owns the leg.
"""
from __future__ import annotations

import inspect

import pytest

import services.compliance_obligation_service as ob
from mock_data import (
    CLIENT_INDEX,
    ENGAGEMENT_INDEX,
    MOCK_CLIENTS,
    MOCK_COMPLIANCE_RECORDS,
    MOCK_ENGAGEMENTS,
)
from repositories.client_repository import client_repo
from repositories.compliance_records_repository import compliance_records_repo
from repositories.engagement_repository import engagement_repo

FIRM = "F-C05"
FY = "2025-26"
GSTIN = "27AAPFU0939F1ZV"  # real, check-digit-valid fixture GSTIN
GST_TYPES = {"GSTR1", "GSTR3B", "PMT06", "GSTR9"}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    MOCK_COMPLIANCE_RECORDS.clear()
    MOCK_ENGAGEMENTS.clear()
    ENGAGEMENT_INDEX.clear()
    clients_snapshot = list(MOCK_CLIENTS)
    import services.audit_service as au
    import services.timeline_service as ts
    monkeypatch.setattr(au, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    yield
    MOCK_COMPLIANCE_RECORDS.clear()
    MOCK_ENGAGEMENTS.clear()
    ENGAGEMENT_INDEX.clear()
    MOCK_CLIENTS[:] = clients_snapshot
    CLIENT_INDEX.clear()
    CLIENT_INDEX.update({c["id"]: c for c in MOCK_CLIENTS})


def _client(client_id="meher", freq="monthly"):
    return client_repo.create({
        "id": client_id, "firm_id": FIRM, "client_name": "Meher & Co",
        "gstin": GSTIN, "gst_filing_frequency": freq, "entity_type": "Proprietorship",
        "state_code": "27",
    })


def _engagement(client_id, service_type, billing_cycle="Monthly"):
    return engagement_repo.create({
        "firm_id": FIRM, "client_id": client_id, "service_type": service_type,
        "fee_paise": 500000, "billing_cycle": billing_cycle, "start_date": "2025-04-01",
        "status": "Active",
    })


def _records(client_id="meher"):
    return compliance_records_repo.find_all(firm_id=FIRM, client_id=client_id)


def _gst_rows(client_id="meher"):
    return sorted((r for r in _records(client_id) if r["obligation_type"] in GST_TYPES),
                  key=lambda r: (r["obligation_type"], r["period_start"], r["id"]))


def _gst_ids(client_id="meher"):
    return [r["id"] for r in _gst_rows(client_id)]


def test_generating_a_return_engagement_leaves_the_gst_engagements_rows_in_place():
    _client()
    gst = _engagement("meher", "GST Compliance")
    itr = _engagement("meher", "Income Tax Return", billing_cycle="Annually")

    first = ob.generate_for_engagement(FIRM, gst, FY)
    assert first["generated"] == 25                      # 12 GSTR-1 + 12 GSTR-3B + GSTR-9
    ids_before = _gst_ids()
    assert len(ids_before) == 25

    second = ob.generate_for_engagement(FIRM, itr, FY)
    assert second["generated"] >= 1, "the ITR engagement generates its own obligation"

    assert _gst_ids() == ids_before, "the ITR engagement deleted or replaced GST rows it does not own"
    assert all(r["engagement_id"] == gst["id"] for r in _gst_rows())


def test_the_order_the_engagements_run_in_makes_no_difference():
    _client()
    gst = _engagement("meher", "GST Compliance")
    itr = _engagement("meher", "Income Tax Return", billing_cycle="Annually")

    ob.generate_for_engagement(FIRM, itr, FY)
    ob.generate_for_engagement(FIRM, gst, FY)
    after_itr_then_gst = _gst_ids()

    assert len(after_itr_then_gst) == 25
    # And running them again, in the other order, neither adds nor removes a row.
    ob.generate_for_engagement(FIRM, gst, FY)
    ob.generate_for_engagement(FIRM, itr, FY)
    assert _gst_ids() == after_itr_then_gst


def test_the_daily_sweep_is_idempotent_for_a_client_with_a_gst_and_another_engagement():
    """`generate_due` is what the 06:00 IST job calls. It deleted and recreated the GST rows on every run."""
    _client()
    _engagement("meher", "GST Compliance")
    _engagement("meher", "Income Tax Return", billing_cycle="Annually")

    first = ob.generate_due(FIRM, client_id="meher", financial_year=FY)
    assert first["generated"] > 25
    ids = sorted(r["id"] for r in _records())

    second = ob.generate_due(FIRM, client_id="meher", financial_year=FY)
    third = ob.generate_due(FIRM, client_id="meher", financial_year=FY)
    assert second["generated"] == 0, second
    assert third["generated"] == 0, third
    assert sorted(r["id"] for r in _records()) == ids, "rows were deleted and recreated by a sweep"


def test_an_engagement_without_gst_does_not_touch_a_gst_row_a_ca_is_working_on():
    _client()
    gst = _engagement("meher", "GST Compliance")
    itr = _engagement("meher", "Income Tax Return", billing_cycle="Annually")
    ob.generate_for_engagement(FIRM, gst, FY)
    worked = next(r for r in _gst_rows() if r["obligation_type"] == "GSTR1")
    compliance_records_repo.update(worked["id"], {"status": "Awaiting Documents"})

    res = ob.generate_for_engagement(FIRM, itr, FY)

    assert compliance_records_repo.find_by_id(worked["id"])["status"] == "Awaiting Documents"
    assert not any("Awaiting Documents" in g for g in res.get("statutory_gaps", ())), (
        "a row belonging to the GST engagement was reported as stale by the ITR engagement")


def test_a_frequency_switch_still_reconciles_through_the_engagement_that_owns_the_leg():
    """The behaviour the reconciliation exists for, with a second engagement on the client."""
    _client(freq="monthly")
    gst = _engagement("meher", "GST Compliance")
    itr = _engagement("meher", "Income Tax Return", billing_cycle="Annually")
    ob.generate_for_engagement(FIRM, gst, FY)
    ob.generate_for_engagement(FIRM, itr, FY)
    itr_rows = [r["id"] for r in _records() if r["obligation_type"] not in GST_TYPES]
    assert itr_rows

    CLIENT_INDEX["meher"]["gst_filing_frequency"] = "quarterly"
    ob.generate_due(FIRM, client_id="meher", financial_year=FY)

    gstr1 = [r for r in _gst_rows() if r["obligation_type"] == "GSTR1"]
    assert len(gstr1) == 4, "one per quarter once the switch is reconciled"
    assert all(r["period_end"][5:7] in ("06", "09", "12", "03") for r in gstr1)
    assert [r["id"] for r in _records() if r["obligation_type"] not in GST_TYPES] == itr_rows, (
        "the switch must not disturb the other engagement's rows")


# ── The rule, not the one call site ─────────────────────────────────────────────────────────────

def test_the_reconciliation_makes_every_caller_say_whether_it_owns_the_gst_leg():
    sig = inspect.signature(ob._reconcile_stale_gst_obligations)
    param = sig.parameters["owns_the_gst_leg"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is inspect.Parameter.empty, "a default would let a caller forget to decide"


def test_a_caller_that_does_not_own_the_leg_reads_and_deletes_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(compliance_records_repo, "soft_delete", lambda rid: calls.append(rid))
    stale = {"id": "r1", "obligation_type": "GSTR1", "period_start": "2025-04-01",
             "period_end": "2025-04-30", "status": "Not Started"}
    out = ob._reconcile_stale_gst_obligations(FIRM, "meher", FY, [], [stale], owns_the_gst_leg=False)
    assert out == (set(), set(), [])
    assert calls == []
    # The same row IS reconciled for the engagement that owns the leg and implies no such spec.
    ob._reconcile_stale_gst_obligations(FIRM, "meher", FY, [], [stale], owns_the_gst_leg=True)
    assert calls == ["r1"]
