"""
Batch 2 (Amendment v1.1) — application-layer guardrail unit tests.

These run in mock mode (no DB) and cover the *effective* enforcement layer
(service-role bypasses RLS), complementing the RLS verification in
test_batch2_guardrails_migration.py:

  G1  assert_can_view_client / assert_partner_for_internal_id (Partner-only).
  G2  client_repo.find_all / count exclude the internal client by default.
  G4  assert_not_internal_for_payroll blocks payroll for the internal client.
"""
import pytest
from fastapi import HTTPException

import services.internal_client_service as ics
from repositories.client_repository import client_repo
from mock_data import MOCK_CLIENTS

PARTNER = {"firm_id": "F1", "role": "Partner"}
STAFF = {"firm_id": "F1", "role": "Executive"}
OWNER = {"firm_id": "F1", "role": "owner"}


def test_is_partner_mapping():
    assert ics.is_partner(PARTNER) is True
    assert ics.is_partner(OWNER) is True          # Owner-equivalent
    assert ics.is_partner(STAFF) is False
    assert ics.is_partner({"role": "Manager"}) is False


def test_is_internal_client(monkeypatch):
    monkeypatch.setattr(ics, "get_internal_client_id", lambda firm_id: "INT")
    assert ics.is_internal_client("INT", "F1") is True
    assert ics.is_internal_client("EXT", "F1") is False
    assert ics.is_internal_client(None, "F1") is False


def test_g1_assert_can_view_client(monkeypatch):
    # External client: visible to everyone.
    ics.assert_can_view_client({"is_internal": False}, STAFF)
    # Internal client: hidden from staff (404), visible to partner.
    with pytest.raises(HTTPException) as ei:
        ics.assert_can_view_client({"is_internal": True}, STAFF)
    assert ei.value.status_code == 404
    ics.assert_can_view_client({"is_internal": True}, PARTNER)  # no raise


def test_g1_assert_partner_for_internal_id(monkeypatch):
    monkeypatch.setattr(ics, "get_internal_client_id", lambda firm_id: "INT")
    with pytest.raises(HTTPException) as ei:
        ics.assert_partner_for_internal_id("INT", STAFF)
    assert ei.value.status_code == 404
    ics.assert_partner_for_internal_id("INT", PARTNER)   # partner ok
    ics.assert_partner_for_internal_id("EXT", STAFF)     # external ok for staff


def test_g4_payroll_blocked_for_internal(monkeypatch):
    monkeypatch.setattr(ics, "get_internal_client_id", lambda firm_id: "INT")
    with pytest.raises(HTTPException) as ei:
        ics.assert_not_internal_for_payroll("INT", "F1")
    assert ei.value.status_code == 403
    ics.assert_not_internal_for_payroll("EXT", "F1")     # external ok


def test_g2_repo_excludes_internal_by_default():
    marker = {"id": "__int_test__", "client_name": "Z Internal",
              "is_internal": True, "status": "active"}
    MOCK_CLIENTS.append(marker)
    try:
        default_ids = [c["id"] for c in client_repo.find_all()]
        assert "__int_test__" not in default_ids, "internal client must be excluded by default (G2)"
        incl_ids = [c["id"] for c in client_repo.find_all(include_internal=True)]
        assert "__int_test__" in incl_ids, "internal client must be retrievable with include_internal=True"
        # count() excludes internal by default
        base = client_repo.count()
        assert base == len(default_ids)
    finally:
        MOCK_CLIENTS.remove(marker)
