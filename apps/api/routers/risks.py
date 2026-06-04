from fastapi import APIRouter, Depends
from models.common import api_response
from core.auth import get_current_user
from domain.risk_engine import (
    get_all_risks,
    get_risk_dashboard_stats,
    get_client_risk_summary,
    compute_firm_risk_score,
    update_risk,
)

router = APIRouter(prefix="/api/risks", tags=["risks"])


@router.get("")
def list_risks(severity: str = None, client_id: str = None, status: str = "open", current_user: dict = Depends(get_current_user)):
    risks = get_all_risks(severity=severity, client_id=client_id, status=status)
    return api_response(True, risks)


@router.get("/stats")
def risk_stats(current_user: dict = Depends(get_current_user)):
    stats = get_risk_dashboard_stats()
    return api_response(True, stats)


@router.get("/firm/score")
def firm_score(current_user: dict = Depends(get_current_user)):
    score = compute_firm_risk_score()
    return api_response(True, {"score": score})


@router.get("/client/{client_id}")
def client_risks(client_id: str, current_user: dict = Depends(get_current_user)):
    summary = get_client_risk_summary(client_id)
    return api_response(True, summary)


@router.patch("/{risk_id}")
def update_risk_status(risk_id: str, resolution_status: str = "resolved", current_user: dict = Depends(get_current_user)):
    risk = update_risk(risk_id, resolution_status)
    if risk is None:
        return api_response(False, None, "Risk not found")
    return api_response(True, risk)
