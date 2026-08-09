from fastapi import APIRouter, Depends
from models.common import api_response
from core.permissions import rbac
from core.authz import assert_client_access, can_access_client, filter_by_client
from domain.risk_engine import (
    get_all_risks,
    get_risk,
    get_risk_dashboard_stats,
    get_client_risk_summary,
    compute_firm_risk_score,
    update_risk,
)

router = APIRouter(prefix="/api/risks", tags=["risks"])


def _assert_risk_scope(current_user: dict, risk_id: str) -> dict | None:
    """Resolve risk_id to its row and verify the caller's client-assignment
    scope (document_risks.client_id is NOT NULL, migration 004). Returns None
    for both a missing row and an out-of-scope one — the caller renders one
    fixed "Risk not found" either way, so a wrong-client guess cannot be
    distinguished from a real 404."""
    row = get_risk(risk_id, firm_id=current_user.get("firm_id"))
    if row is None or not can_access_client(current_user, row.get("client_id")):
        return None
    return row


@router.get("")
def list_risks(severity: str = None, client_id: str = None, status: str = "open", current_user: dict = Depends(rbac("risk", "read"))):
    firm_id = current_user.get("firm_id")
    # M2: client_id was only ever narrowed INTO the firm-scoped query, never
    # checked; and with client_id omitted this returned every client's risks
    # in the firm. filter_by_client covers the omitted case too.
    if client_id:
        assert_client_access(current_user, client_id)
    risks = get_all_risks(firm_id=firm_id, severity=severity, client_id=client_id, status=status)
    return api_response(True, filter_by_client(current_user, risks))


@router.get("/stats")
def risk_stats(current_user: dict = Depends(rbac("risk", "read"))):
    firm_id = current_user.get("firm_id")
    stats = get_risk_dashboard_stats(firm_id=firm_id)
    return api_response(True, stats)


@router.get("/firm/score")
def firm_score(current_user: dict = Depends(rbac("risk", "read"))):
    firm_id = current_user.get("firm_id")
    score = compute_firm_risk_score(firm_id=firm_id)
    return api_response(True, {"score": score})


@router.get("/client/{client_id}")
def client_risks(client_id: str, current_user: dict = Depends(rbac("risk", "read"))):
    firm_id = current_user.get("firm_id")
    assert_client_access(current_user, client_id)
    summary = get_client_risk_summary(client_id, firm_id=firm_id)
    return api_response(True, summary)


@router.patch("/{risk_id}")
def update_risk_status(risk_id: str, resolution_status: str = "resolved", current_user: dict = Depends(rbac("risk", "write"))):
    firm_id = current_user.get("firm_id")
    # M2: update_risk scopes by firm_id only — an unassigned caller could
    # resolve/dismiss another staff member's client's risk by guessing an id.
    if _assert_risk_scope(current_user, risk_id) is None:
        return api_response(False, None, "Risk not found")
    risk = update_risk(risk_id, resolution_status, firm_id=firm_id)
    if risk is None:
        return api_response(False, None, "Risk not found")
    return api_response(True, risk)
