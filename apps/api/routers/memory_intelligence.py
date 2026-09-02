"""
Phase 13 — AI Memory & Intelligence API Router
"""
from fastapi import APIRouter, Depends, Query
from typing import Optional
from fastapi import HTTPException
from core.authz import (
    assert_client_access, filter_by_client, is_firmwide, firmwide_roles_label,
)
from core.permissions import rbac
from models.common import api_response
from models.fy import FYLabel

router = APIRouter(prefix="/api/memory", tags=["AI Memory Phase 13"])


def _get_pipeline():
    from domain.memory_pipeline import memory_pipeline
    return memory_pipeline

def _get_repo():
    from repositories.memory_repository import memory_repo
    return memory_repo



# ── Client-assignment scope (M2) ──────────────────────────────────────────────
# `core.authz` makes only the **Partner** firm-wide (`_FIRMWIDE_ROLES`); a
# Manager, Executive or Reviewer sees only the clients in
# `user_client_assignments`. This router did not import core.authz at all, so an
# AI profile of any client — the firm's accumulated knowledge about how that
# client behaves — was readable by anyone in the firm.
#
#   * `client_profiles` and `year_end_reports` — client_id NOT NULL.
#   * `ai_memory_triggers` and `pattern_anomalies` — client_id NULLABLE: a
#     trigger can be firm-level ("three clients missed the same deadline"), so a
#     NULL is a firm-level row and not something to 404.
#   * `firm_profiles` — firm_id only. Exempt, with the reason in
#     tests/test_router_client_scope.py.

def _assert_trigger_scope(current_user: dict, trigger_id: str) -> Optional[str]:
    """404 unless the caller may act on this trigger's client.

    404 rather than 403, and the same 404 as "no such trigger" — otherwise the
    status code becomes an oracle for which trigger ids are real.
    """
    t = _get_repo().get_trigger(current_user["firm_id"], trigger_id)
    if not t:
        raise HTTPException(status_code=404, detail="Trigger not found")
    assert_client_access(current_user, t.get("client_id"))
    return t.get("client_id")


def _assert_anomaly_scope(current_user: dict, anomaly_id: str) -> Optional[str]:
    a = _get_repo().get_anomaly(current_user["firm_id"], anomaly_id)
    if not a:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    assert_client_access(current_user, a.get("client_id"))
    return a.get("client_id")


def _assert_firmwide(current_user: dict, what: str, instead: str) -> None:
    """Refuse a firm-WIDE computation to a caller who is not firm-wide.

    403, not 404: nothing is being hidden. The operation itself spans every
    client in the firm, and there is no partial version of it that would be
    honest — running it for a subset and reporting it as "the firm pipeline"
    would be worse than refusing. The message names the per-client endpoint so
    the caller is not left guessing what they CAN do.
    """
    if not is_firmwide(current_user):
        raise HTTPException(
            status_code=403,
            detail=f"{what} runs across every client in the firm and is limited "
                   f"to {firmwide_roles_label()}. Use {instead} for a client you "
                   f"are assigned to.")


# ── Client Profiles ──────────────────────────────────────────────────────────

@router.get("/clients/{client_id}/profile")
def get_client_profile(
    client_id: str,
    current_user: dict = Depends(rbac("copilot", "read")),
):
    """Get current semantic memory profile for a client."""
    assert_client_access(current_user, client_id)
    firm_id = current_user["firm_id"]
    profile = _get_repo().get_current_profile(firm_id, client_id)
    return api_response(True, data={"profile": profile})


@router.post("/clients/{client_id}/profile/compute")
def compute_client_profile(
    client_id: str,
    current_user: dict = Depends(rbac("copilot", "write")),
):
    """Trigger immediate profile recomputation for a client."""
    assert_client_access(current_user, client_id)
    firm_id = current_user["firm_id"]
    profile = _get_pipeline().compute_client_profile(firm_id, client_id)
    return api_response(True, data={"profile": profile})


@router.get("/profiles")
def list_profiles(
    limit: int = Query(50, ge=1, le=100),
    current_user: dict = Depends(rbac("copilot", "read")),
):
    """List all current client profiles for the firm."""
    firm_id = current_user["firm_id"]
    # client_profiles.client_id is NOT NULL, so narrowing drops every profile
    # outside the caller's book rather than merely reordering the page.
    profiles = filter_by_client(current_user, _get_repo().list_profiles(firm_id, limit=limit))
    return api_response(True, data={"profiles": profiles, "count": len(profiles)})


# ── Firm Profile ─────────────────────────────────────────────────────────────

@router.get("/firm/profile")
def get_firm_profile(current_user: dict = Depends(rbac("copilot", "read"))):
    """Get firm-level intelligence profile."""
    firm_id = current_user["firm_id"]
    profile = _get_repo().get_firm_profile(firm_id)
    return api_response(True, data={"profile": profile})


@router.post("/firm/profile/compute")
def compute_firm_profile(current_user: dict = Depends(rbac("copilot", "write"))):
    """Recompute firm-level intelligence."""
    _assert_firmwide(current_user, "Recomputing the firm profile",
                     "POST /api/memory/clients/{client_id}/profile/compute")
    firm_id = current_user["firm_id"]
    profile = _get_pipeline().compute_firm_profile(firm_id)
    return api_response(True, data={"profile": profile})


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
    if client_id:
        assert_client_access(current_user, client_id)
    firm_id = current_user["firm_id"]
    triggers = _get_repo().list_triggers(
        firm_id, client_id=client_id, trigger_type=trigger_type, status=status, limit=limit
    )
    if not client_id:
        # filter_by_client keeps rows with no client_id, so a FIRM-level trigger
        # ("three clients missed the same deadline") survives the narrowing —
        # it belongs to everyone in the firm, not to one client's book.
        triggers = filter_by_client(current_user, triggers)
    return api_response(True, data={"triggers": triggers, "count": len(triggers)})


@router.post("/triggers/{trigger_id}/acknowledge")
def acknowledge_trigger(
    trigger_id: str,
    current_user: dict = Depends(rbac("copilot", "write")),
):
    """Acknowledge a memory trigger."""
    _assert_trigger_scope(current_user, trigger_id)
    firm_id = current_user["firm_id"]
    user_id = current_user["auth_user_id"]
    trigger = _get_repo().acknowledge_trigger(firm_id, trigger_id, user_id)
    return api_response(True, data={"trigger": trigger})


@router.post("/triggers/{trigger_id}/dismiss")
def dismiss_trigger(
    trigger_id: str,
    current_user: dict = Depends(rbac("copilot", "write")),
):
    _assert_trigger_scope(current_user, trigger_id)
    firm_id = current_user["firm_id"]
    trigger = _get_repo().dismiss_trigger(firm_id, trigger_id)
    return api_response(True, data={"trigger": trigger})


# ── Client-specific trigger detection ────────────────────────────────────────

@router.post("/clients/{client_id}/detect")
def detect_client_triggers(
    client_id: str,
    current_user: dict = Depends(rbac("copilot", "write")),
):
    """Run all trigger detectors for a specific client immediately."""
    assert_client_access(current_user, client_id)
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
    return api_response(True, data={"detections": results, "total_triggered": total})


# ── Anomalies ─────────────────────────────────────────────────────────────────

@router.get("/anomalies")
def list_anomalies(
    client_id: Optional[str] = Query(None),
    status: str = Query("open"),
    limit: int = Query(50, ge=1, le=100),
    current_user: dict = Depends(rbac("copilot", "read")),
):
    if client_id:
        assert_client_access(current_user, client_id)
    firm_id = current_user["firm_id"]
    anomalies = _get_repo().list_anomalies(firm_id, client_id=client_id, status=status, limit=limit)
    if not client_id:
        anomalies = filter_by_client(current_user, anomalies)
    return api_response(True, data={"anomalies": anomalies, "count": len(anomalies)})


@router.patch("/anomalies/{anomaly_id}/status")
def update_anomaly_status(
    anomaly_id: str,
    body: dict,
    current_user: dict = Depends(rbac("copilot", "write")),
):
    _assert_anomaly_scope(current_user, anomaly_id)
    firm_id = current_user["firm_id"]
    status = body.get("status", "reviewed")
    anomaly = _get_repo().update_anomaly_status(firm_id, anomaly_id, status)
    return api_response(True, data={"anomaly": anomaly})


# ── Year-End Reports ──────────────────────────────────────────────────────────

@router.get("/year-end-reports")
def list_year_end_reports(
    limit: int = Query(20, ge=1, le=50),
    current_user: dict = Depends(rbac("copilot", "read")),
):
    firm_id = current_user["firm_id"]
    reports = filter_by_client(current_user, _get_repo().list_year_end_reports(firm_id, limit=limit))
    return api_response(True, data={"reports": reports, "count": len(reports)})


@router.get("/year-end-reports/{client_id}/{financial_year}")
def get_year_end_report(
    client_id: str,
    financial_year: FYLabel,
    current_user: dict = Depends(rbac("copilot", "read")),
):
    assert_client_access(current_user, client_id)
    firm_id = current_user["firm_id"]
    report = _get_repo().get_year_end_report(firm_id, client_id, financial_year)
    return api_response(True, data={"report": report})


# ── Full pipeline run ─────────────────────────────────────────────────────────

@router.post("/pipeline/run")
def run_pipeline(current_user: dict = Depends(rbac("copilot", "write"))):
    """Manually trigger full memory pipeline for the firm."""
    _assert_firmwide(current_user, "The full memory pipeline",
                     "POST /api/memory/clients/{client_id}/detect")
    firm_id = current_user["firm_id"]
    result = _get_pipeline().run_full_pipeline(firm_id)
    return api_response(True, data=result)
