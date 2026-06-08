from fastapi import APIRouter, Depends
from models.common import api_response
from core.permissions import rbac
from domain.risk_engine import (
    get_all_risks,
    get_risk_dashboard_stats,
    get_client_risk_summary,
    compute_firm_risk_score,
    update_risk,
)

router = APIRouter(prefix="/api/risks", tags=["risks"])


@router.get("")
def list_risks(severity: str = None, client_id: str = None, status: str = "open", current_user: dict = Depends(rbac("risk", "read"))):
    firm_id = current_user.get("firm_id")
    risks = get_all_risks(firm_id=firm_id, severity=severity, client_id=client_id, status=status)
    return api_response(True, risks)


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
    summary = get_client_risk_summary(client_id, firm_id=firm_id)
    return api_response(True, summary)


@router.patch("/{risk_id}")
def update_risk_status(risk_id: str, resolution_status: str = "resolved", current_user: dict = Depends(rbac("risk", "write"))):
    firm_id = current_user.get("firm_id")
    risk = update_risk(risk_id, resolution_status, firm_id=firm_id)
    if risk is None:
        return api_response(False, None, "Risk not found")
    return api_response(True, risk)
