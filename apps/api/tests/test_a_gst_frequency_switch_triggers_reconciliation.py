"""
apex-overview-practice-01, part 2 — routers/clients.py::update_client wrote
clients.gst_filing_frequency straight through with no reconciliation of the
compliance_records already generated at the OLD frequency at all. Even with
_reconcile_stale_gst_obligations fixing the dedup itself
(test_a_gst_frequency_switch_reconciles_the_calendar.py), the calendar stayed
wrong until the NEXT unrelated obligation-generation sweep (the daily
scheduler, or a manual POST /api/compliance/obligations/generate) happened to
run — for Apex, the two events were seven weeks apart.

update_client now calls generate_due(firm_id, client_id=...) itself whenever
the PATCH actually CHANGES gst_filing_frequency, so the switch is reconciled
immediately.
"""
from unittest.mock import patch

import pytest

import routers.clients as clients_router
from models.client import ClientUpdate

FIRM = "firm-apex"
CLIENT_ID = "client-apex"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "email": "ca@f", "role": "Partner"}


def _client(freq="monthly"):
    return {"id": CLIENT_ID, "firm_id": FIRM, "client_name": "Apex Trading Solutions",
            "status": "active", "pan": "AAAAA1111A", "gst_filing_frequency": freq}


def _patch(body_kwargs):
    return clients_router.update_client(
        client_id=CLIENT_ID, body=ClientUpdate(**body_kwargs), current_user=USER)


def test_switching_the_frequency_triggers_regeneration():
    with patch("routers.clients.client_repo") as mock_repo, \
         patch("routers.clients.log_event"), \
         patch("services.compliance_obligation_service.generate_due") as mock_gen:
        mock_repo.find_by_id.return_value = _client(freq="monthly")
        mock_repo.update.return_value = _client(freq="quarterly")
        resp = _patch({"gst_filing_frequency": "quarterly"})

    assert resp["success"] is True
    mock_gen.assert_called_once_with(FIRM, client_id=CLIENT_ID, actor=USER)


def test_setting_the_frequency_to_what_it_already_was_does_not_regenerate():
    """The narrow trigger — 'actually changes' — matters: a PATCH that merely
    re-sends the current value (e.g. a form re-submitting unchanged fields)
    must not re-run the reconciliation and re-emit gaps for rows nothing
    about."""
    with patch("routers.clients.client_repo") as mock_repo, \
         patch("routers.clients.log_event"), \
         patch("services.compliance_obligation_service.generate_due") as mock_gen:
        mock_repo.find_by_id.return_value = _client(freq="monthly")
        mock_repo.update.return_value = _client(freq="monthly")
        _patch({"gst_filing_frequency": "monthly"})

    mock_gen.assert_not_called()


def test_a_patch_that_never_mentions_the_frequency_does_not_regenerate():
    with patch("routers.clients.client_repo") as mock_repo, \
         patch("routers.clients.log_event"), \
         patch("services.compliance_obligation_service.generate_due") as mock_gen:
        mock_repo.find_by_id.return_value = _client(freq="monthly")
        mock_repo.update.return_value = {**_client(freq="monthly"), "client_name": "New Name"}
        _patch({"client_name": "New Name"})

    mock_gen.assert_not_called()


def test_a_client_whose_frequency_was_never_recorded_defaults_to_monthly():
    """gst_profile_for treats an unset frequency as monthly (the safe
    default — see its own docstring); the PATCH trigger must agree, or a
    client's FIRST-EVER frequency choice of 'monthly' would look like a
    no-op change and skip reconciliation for a client whose obligations were
    never generated under any explicit frequency at all."""
    with patch("routers.clients.client_repo") as mock_repo, \
         patch("routers.clients.log_event"), \
         patch("services.compliance_obligation_service.generate_due") as mock_gen:
        mock_repo.find_by_id.return_value = {**_client(freq=None)}
        mock_repo.update.return_value = _client(freq="quarterly")
        _patch({"gst_filing_frequency": "quarterly"})

    mock_gen.assert_called_once_with(FIRM, client_id=CLIENT_ID, actor=USER)


def test_a_failed_regeneration_does_not_fail_the_client_update():
    """Best-effort, the same posture as the audit/timeline hooks beside it:
    the client's own field write must not be undone by a downstream
    compliance-calendar problem."""
    with patch("routers.clients.client_repo") as mock_repo, \
         patch("routers.clients.log_event"), \
         patch("services.compliance_obligation_service.generate_due",
               side_effect=RuntimeError("boom")):
        mock_repo.find_by_id.return_value = _client(freq="monthly")
        mock_repo.update.return_value = _client(freq="quarterly")
        resp = _patch({"gst_filing_frequency": "quarterly"})

    assert resp["success"] is True
    assert resp["data"]["client"]["gst_filing_frequency"] == "quarterly"


# ── End-to-end: the real generate_due, the real dedup fix, through the router ──

def test_end_to_end_the_router_actually_fixes_the_calendar(monkeypatch):
    """No mocking of generate_due here — this drives the real reconciliation
    logic (test_a_gst_frequency_switch_reconciles_the_calendar.py) through the
    router entry point a CA's own frequency change actually hits, reproducing
    the Apex sequence: obligations generated at the old frequency, then the
    PATCH that switches it."""
    from mock_data import MOCK_COMPLIANCE_RECORDS, MOCK_CLIENTS, CLIENT_INDEX
    from repositories.client_repository import client_repo
    from repositories.compliance_records_repository import compliance_records_repo
    import services.compliance_obligation_service as ob
    import services.audit_service as au
    import services.timeline_service as ts

    monkeypatch.setattr(au, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)

    clients_snapshot = list(MOCK_CLIENTS)
    MOCK_COMPLIANCE_RECORDS.clear()
    try:
        client_repo.create({
            "id": CLIENT_ID, "firm_id": FIRM, "client_name": "Apex Trading Solutions",
            "gstin": "27AAPFU0939F1ZV", "gst_filing_frequency": "monthly",
        })
        first = ob.generate_default_for_client(FIRM, CLIENT_ID, ob._current_fy())
        assert first["generated"] == 25

        with patch("routers.clients.log_event"):
            resp = clients_router.update_client(
                client_id=CLIENT_ID,
                body=ClientUpdate(gst_filing_frequency="quarterly"),
                current_user=USER,
            )
        assert resp["success"] is True

        recs = compliance_records_repo.find_all(firm_id=FIRM, client_id=CLIENT_ID)
        assert len(recs) == 17, "reconciled immediately, on the PATCH itself"
        types = {r["obligation_type"] for r in recs}
        assert types == {"GSTR1", "GSTR3B", "PMT06", "GSTR9"}
        gstr1 = [r for r in recs if r["obligation_type"] == "GSTR1"]
        assert len(gstr1) == 4
        assert all(r["due_date"][8:10] == "13" for r in gstr1)
    finally:
        MOCK_COMPLIANCE_RECORDS.clear()
        MOCK_CLIENTS[:] = clients_snapshot
        CLIENT_INDEX.clear()
        CLIENT_INDEX.update({c["id"]: c for c in MOCK_CLIENTS})
