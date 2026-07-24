"""
TDS filing pipeline — regression tests (H9).

update_return_status() (the PATCH /returns/{id}/status endpoint) previously
only ever persisted `status` — never the PRN/acknowledgement number/filing
date columns migration 037 added to tds_returns — so a CA could mark a
return "filed" with zero government proof-of-filing captured server-side.
Meanwhile the frontend never called this endpoint at all: lib/data/tds.ts's
approveTDSReturn()/markTDSFiled() wrote tds_returns directly from the
browser, bypassing RBAC, the audit log, and the timeline event this endpoint
already had.

The fix: this endpoint now requires and persists a PRN before allowing a
"filed" transition, guards against re-filing an already-filed return, and
the frontend now calls this endpoint instead of writing Supabase directly.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import routers.tds_workspace as tds_ws
from routers.tds_workspace import (
    CreateReturnRequest, UpdateReturnStatusRequest, create_return, update_return_status,
)

USER = {"firm_id": "firm-1", "id": "u1", "role": "partner"}
CLIENT_ID = "client-1"


@pytest.fixture(autouse=True)
def clear_mock_store():
    tds_ws._MOCK_RETURNS.clear()
    yield


def _create():
    result = create_return(
        CreateReturnRequest(client_id=CLIENT_ID, return_type="26Q", quarter="Q1", financial_year="2025-26"),
        USER,
    )
    return result["data"]["id"]


def test_successful_filing_persists_prn_ack_and_filed_at():
    return_id = _create()
    result = update_return_status(
        return_id,
        UpdateReturnStatusRequest(status="filed", ca_approved=True, prn="123456789012345", ack_number="ACK-001"),
        USER,
    )
    assert result["success"] is True
    rec = result["data"]
    assert rec["status"] == "filed"
    assert rec["prn"] == "123456789012345"
    assert rec["ack_number"] == "ACK-001"
    assert rec["filed_at"] is not None


def test_failed_filing_without_prn_is_rejected():
    return_id = _create()
    result = update_return_status(
        return_id,
        UpdateReturnStatusRequest(status="filed", ca_approved=True, prn=""),
        USER,
    )
    assert result["success"] is False
    assert tds_ws._MOCK_RETURNS[return_id]["status"] != "filed"


def test_failed_filing_without_ca_approved_is_rejected():
    return_id = _create()
    result = update_return_status(
        return_id,
        UpdateReturnStatusRequest(status="filed", ca_approved=False, prn="123456789012345"),
        USER,
    )
    assert result["success"] is False
    assert tds_ws._MOCK_RETURNS[return_id]["status"] != "filed"


def test_retry_after_failure_succeeds_cleanly():
    return_id = _create()
    failed = update_return_status(
        return_id, UpdateReturnStatusRequest(status="filed", ca_approved=True, prn=""), USER,
    )
    assert failed["success"] is False

    succeeded = update_return_status(
        return_id,
        UpdateReturnStatusRequest(status="filed", ca_approved=True, prn="123456789012345", ack_number="ACK-002"),
        USER,
    )
    assert succeeded["success"] is True
    assert succeeded["data"]["status"] == "filed"
    assert succeeded["data"]["prn"] == "123456789012345"


def test_duplicate_filing_prevention_never_overwrites_original_prn():
    return_id = _create()
    first = update_return_status(
        return_id,
        UpdateReturnStatusRequest(status="filed", ca_approved=True, prn="FIRST-PRN", ack_number="ACK-FIRST"),
        USER,
    )
    assert first["success"] is True

    second = update_return_status(
        return_id,
        UpdateReturnStatusRequest(status="filed", ca_approved=True, prn="SECOND-PRN", ack_number="ACK-SECOND"),
        USER,
    )
    assert second["success"] is False
    # The original filing's PRN must survive a duplicate/repeated attempt untouched.
    assert tds_ws._MOCK_RETURNS[return_id]["prn"] == "FIRST-PRN"
    assert tds_ws._MOCK_RETURNS[return_id]["ack_number"] == "ACK-FIRST"


def test_ca_approval_persists_approver_and_timestamp():
    return_id = _create()
    result = update_return_status(
        return_id, UpdateReturnStatusRequest(status="ca_approved", ca_approved=True), USER,
    )
    assert result["success"] is True
    assert result["data"]["ca_approved_by"] == USER["id"]
    assert result["data"]["ca_approved_at"] is not None
