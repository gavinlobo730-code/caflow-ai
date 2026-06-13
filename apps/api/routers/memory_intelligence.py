"""
Phase 13 — AI Memory & Intelligence API Router
"""
from fastapi import APIRouter, Depends, Query
from typing import Optional
from core.permissions import rbac
from models.common import api_response

router = APIRouter(prefix="/api/memory", tags=["AI Memory Phase 13"])


def _get_pipeline():
    from domain.memory_pipeline import memory_pipeline
    return memory_pipeline

def _get_repo():
    from repositories.memory_repository import memory_repo
    return memory_repo


# ── Client Profiles ──────────────────────────────────────────────────────────

@router.get("/clients/{client_id}/profile")
def get_client_profile(
    client_id: str,
    current_user: dict = Depends(rbac("copilot", "read")),
):
    """Get current semantic memory profile for a client."""
    firm_id = current_user["firm_id"]
    profile = _get_repo().get_current_profile(firm_id, client_id)
    return api_response(data={"profile": profile})


@router.post("/clients/{client_id}/profile/compute")
def compute_client_profile(
    client_id: str,
    current_user: dict = Depends(rbac("copilot", "write")),
):
    """Trigger immediate profile recomputation for a client."""
    firm_id = current_user["firm_id"]
    profile = _get_pipeline().compute_client_profile(firm_id, client_id)
    return api_response(data={"profile": profile})


@router.get("/profiles")
def list_profiles(
    limit: int = Query(50, ge=1, le=100),
    current_user: dict = Depends(rbac("copilot", "read")),
):
    """List all current client profiles for the firm."""
    firm_id = current_user["firm_id"]
    profiles = _get_repo().list_profiles(firm_id, limit=limit)
    return api_response(data={"profiles": profiles, "count": len(profiles)})


# ── Firm Profile ─────────────────────────────────────────────────────────────

@router.get("/firm/profile")
def get_firm_profile(current_user: dict = Depends(rbac("copilot", "read"))):
    """Get firm-level intelligence profile."""
    firm_id = current_user["firm_id"]
    profile = _get_repo().get_firm_profile(firm_id)
    return api_response(data={"profile": profile})


@router.post("/firm/profile/compute")
def compute_firm_profile(current_user: dict = Depends(rbac("copilot", "write"))):
    """Recompute firm-level intelligence."""
    firm_id = current_user["firm_id"]
    profile = _get_pipeline().compute_firm_profile(firm_id)
    return api_response(data={"profile": profile})


# ── Memory Triggers ───────────────────────────────────────────────────────────

@router.get("/triggers")
def list_triggers(
    client_id: Optional[str] = Query(None),
    trigger_type: Optional[str] = Query(None),
    status: str = Query("active"),
    limit: int = Query(50, ge=1, le=100),
    current_user: dict = Depends(rbac("copilot", "read")),
):
    """List AI memory triggers (repeat issues, deadline risks, etc.)."""
    firm_id = current_user["firm_id"]
    triggers = _get_repo().list_triggers(
        firm_id, client_id=client_id, trigger_type=trigger_type, status=status, limit=limit
    )
    return api_response(data={"triggers": triggers, "count": len(triggers)})


@router.post("/triggers/{trigger_id}/acknowledge")
def acknowledge_trigger(
    trigger_id: str,
    current_user: dict = Depends(rbac("copilot", "write")),
):
    """Acknowledge a memory trigger."""
    firm_id = current_user["firm_id"]
    user_id = current_user["auth_user_id"]
    trigger = _get_repo().acknowledge_trigger(firm_id, trigger_id, user_id)
    return api_response(data={"trigger": trigger})


@router.post("/triggers/{trigger_id}/dismiss")
def dismiss_trigger(
    trigger_id: str,
    current_user: dict = Depends(rbac("copilot", "write")),
):
    firm_id = current_user["firm_id"]
    trigger = _get_repo().dismiss_trigger(firm_id, trigger_id)
    return api_response(data={"trigger": trigger})


# ── Client-specific trigger detection ────────────────────────────────────────

@router.post("/clients/{client_id}/detect")
def detect_client_triggers(
    client_id: str,
    current_user: dict = Depends(rbac("copilot", "write")),
):
    """Run all trigger detectors for a specific client immediately."""
    firm_id = current_user["firm_id"]
    pipeline = _get_pipeline()
    results = {
        "repeat_issues": pipeline.detect_repeat_issues(firm_id, client_id),
        "deadline_risks": pipeline.detect_deadline_at_risk(firm_id, client_id),
        "cash_flow_warnings": pipeline.detect_cash_flow_warnings(firm_id, client_id),
        "anomalies": pipeline.detect_pattern_anomalies(firm_id, client_id),
    }
    ye = pipeline.detect_year_end_readiness(firm_id, client_id)
    if ye:
        results["year_end_report"] = ye
    total = sum(len(v) if isinstance(v, list) else 1 for v in results.values() if v)
    return api_response(data={"detections": results, "total_triggered": total})


# ── Anomalies ─────────────────────────────────────────────────────────────────

@router.get("/anomalies")
def list_anomalies(
    client_id: Optional[str] = Query(None),
    status: str = Query("open"),
    limit: int = Query(50, ge=1, le=100),
    current_user: dict = Depends(rbac("copilot", "read")),
):
    firm_id = current_user["firm_id"]
    anomalies = _get_repo().list_anomalies(firm_id, client_id=client_id, status=status, limit=limit)
    return api_response(data={"anomalies": anomalies, "count": len(anomalies)})


@router.patch("/anomalies/{anomaly_id}/status")
def update_anomaly_status(
    anomaly_id: str,
    body: dict,
    current_user: dict = Depends(rbac("copilot", "write")),
):
    firm_id = current_user["firm_id"]
    status = body.get("status", "reviewed")
    anomaly = _get_repo().update_anomaly_status(firm_id, anomaly_id, status)
    return api_response(data={"anomaly": anomaly})


# ── Year-End Reports ──────────────────────────────────────────────────────────

@router.get("/year-end-reports")
def list_year_end_reports(
    limit: int = Query(20, ge=1, le=50),
    current_user: dict = Depends(rbac("copilot", "read")),
):
    firm_id = current_user["firm_id"]
    reports = _get_repo().list_year_end_reports(firm_id, limit=limit)
    return api_response(data={"reports": reports, "count": len(reports)})


@router.get("/year-end-reports/{client_id}/{financial_year}")
def get_year_end_report(
    client_id: str,
    financial_year: str,
    current_user: dict = Depends(rbac("copilot", "read")),
):
    firm_id = current_user["firm_id"]
    report = _get_repo().get_year_end_report(firm_id, client_id, financial_year)
    return api_response(data={"report": report})


# ── Full pipeline run ─────────────────────────────────────────────────────────

@router.post("/pipeline/run")
def run_pipeline(current_user: dict = Depends(rbac("copilot", "write"))):
    """Manually trigger full memory pipeline for the firm."""
    firm_id = current_user["firm_id"]
    result = _get_pipeline().run_full_pipeline(firm_id)
    return api_response(data=result)
