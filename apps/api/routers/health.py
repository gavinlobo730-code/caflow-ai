"""
Health router — Client health scoring, overrides, alerts, and dashboard.

Phase 7: Unified Intelligence Layer — PracticeSync

Score dimensions (all integer arithmetic, never float):
  compliance_score, accounting_score, documents_score, responsiveness_score,
  relationship_risk_score, financial_risk_score, engagement_health_score

overall_score = sum(all 7 dimensions) // 7   (integer division)
Grade: A>=85, B>=70, C>=55, D>=40, F otherwise
is_critical = overall_score < 40
is_at_risk   = overall_score < 60

CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, date, timedelta
import uuid

from models.common import api_response
from core.permissions import rbac
from services.timeline_service import timeline_service

router = APIRouter(prefix="/api/health", tags=["health"])


# ─── In-memory mock stores ────────────────────────────────────────────────────

_MOCK_SCORES:    dict[str, dict] = {}   # client_id → score row
_MOCK_HISTORY:   list[dict]      = []
_MOCK_OVERRIDES: list[dict]      = []
_MOCK_ALERTS:    list[dict]      = []


def _db():
    import os
    if not os.environ.get("SUPABASE_URL"):
        return None
    from core.supabase_client import get_supabase
    return get_supabase()


# ─── Pydantic Models ──────────────────────────────────────────────────────────

class OverrideIn(BaseModel):
    dimension: Optional[str] = None       # e.g. "compliance_score" or None for overall
    override_score: int                   # integer 0–100
    reason: str
    expires_at: Optional[str] = None


class AlertResolveIn(BaseModel):
    resolution_notes: Optional[str] = None


# ─── Score calculation helpers ────────────────────────────────────────────────

def _grade(score: int) -> str:
    """Derive letter grade from integer score. No float arithmetic."""
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def _calculate_scores_mock(client_id: str) -> dict:
    """
    Mock calculation — uses default/dummy values since there's no DB.
    All values are integers (paise or score points).
    """
    compliance_score       = 80   # default — no real compliance_tasks in mock
    accounting_score       = 100  # no unreconciled txns in mock
    documents_score        = 80   # default per spec
    responsiveness_score   = 75   # default per spec
    relationship_risk_score = 100 # no confirmed cross_client_matches in mock
    financial_risk_score   = 75   # default per spec
    engagement_health_score = 60  # default: expired engagement letter

    # Equal-weight average using integer division — no float
    total = (
        compliance_score
        + accounting_score
        + documents_score
        + responsiveness_score
        + relationship_risk_score
        + financial_risk_score
        + engagement_health_score
    )
    overall_score = total // 7

    return {
        "compliance_score":        compliance_score,
        "accounting_score":        accounting_score,
        "documents_score":         documents_score,
        "responsiveness_score":    responsiveness_score,
        "relationship_risk_score": relationship_risk_score,
        "financial_risk_score":    financial_risk_score,
        "engagement_health_score": engagement_health_score,
        "overall_score":           overall_score,
        "health_grade":            _grade(overall_score),
        "is_critical":             overall_score < 40,
        "is_at_risk":              overall_score < 60,
    }


def _calculate_scores_db(db, client_id: str, firm_id: str) -> dict:
    """
    Real DB calculation. All arithmetic is integer — never float.

    Compliance score (CGST Act / IT Act — see compliance module for sections):
      Start 100, −20 per overdue compliance task.

    Accounting score:
      Start 100, −30 if any unreconciled bank transaction older than 30 days.

    Documents score: 80 (default — doc tracking not yet in scope)
    Responsiveness score: 75 (default)

    Relationship risk score:
      Start 100, −15 per confirmed cross_client_match.

    Financial risk score: 75 (default)

    Engagement health:
      100 = active engagement letter, 60 = expired, 40 = none.
    """
    today = date.today()

    # ── compliance_score ──
    compliance_score = 100
    try:
        overdue_tasks = db.table("compliance_tasks").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "Pending").lt("due_date", today.isoformat()).execute().data or []
        deduction = len(overdue_tasks) * 20
        compliance_score = max(0, 100 - deduction)
    except Exception:
        pass

    # ── accounting_score ──
    accounting_score = 100
    try:
        cutoff = (today - timedelta(days=30)).isoformat()
        unreconciled = db.table("bank_transactions").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("reconciled", False).lt("txn_date", cutoff).limit(1).execute().data or []
        if unreconciled:
            accounting_score = max(0, 100 - 30)
    except Exception:
        pass

    # ── documents_score ── (default per spec — no doc tracking yet)
    documents_score = 80

    # ── responsiveness_score ── (default per spec)
    responsiveness_score = 75

    # ── relationship_risk_score ──
    relationship_risk_score = 100
    try:
        confirmed_matches = db.table("cross_client_matches").select("id").eq("firm_id", firm_id).or_(f"client_id_a.eq.{client_id},client_id_b.eq.{client_id}").eq("is_confirmed", True).execute().data or []
        deduction = len(confirmed_matches) * 15
        relationship_risk_score = max(0, 100 - deduction)
    except Exception:
        pass

    # ── financial_risk_score ── (default per spec)
    financial_risk_score = 75

    # ── engagement_health_score ──
    engagement_health_score = 40  # default: none
    try:
        engagements = db.table("engagements").select("status, end_date").eq("firm_id", firm_id).eq("client_id", client_id).order("end_date", desc=True).limit(5).execute().data or []
        if engagements:
            active = [e for e in engagements if e.get("status") == "Active"]
            if active:
                engagement_health_score = 100
            else:
                # Check if any expired
                expired = [e for e in engagements if e.get("status") in ("Expired", "Completed")]
                if expired:
                    engagement_health_score = 60
    except Exception:
        pass

    # ── overall_score: equal-weight average, integer division — never float ──
    total = (
        compliance_score
        + accounting_score
        + documents_score
        + responsiveness_score
        + relationship_risk_score
        + financial_risk_score
        + engagement_health_score
    )
    overall_score = total // 7

    return {
        "compliance_score":        compliance_score,
        "accounting_score":        accounting_score,
        "documents_score":         documents_score,
        "responsiveness_score":    responsiveness_score,
        "relationship_risk_score": relationship_risk_score,
        "financial_risk_score":    financial_risk_score,
        "engagement_health_score": engagement_health_score,
        "overall_score":           overall_score,
        "health_grade":            _grade(overall_score),
        "is_critical":             overall_score < 40,
        "is_at_risk":              overall_score < 60,
    }


# ─── Scores ───────────────────────────────────────────────────────────────────

@router.get("/scores")
def list_scores(
    is_critical: Optional[bool] = Query(None),
    is_at_risk: Optional[bool] = Query(None),
    current_user: dict = Depends(rbac("clients", "read")),
):
    db = _db()
    if not db:
        result = list(_MOCK_SCORES.values())
        if is_critical is not None:
            result = [s for s in result if s.get("is_critical") == is_critical]
        if is_at_risk is not None:
            result = [s for s in result if s.get("is_at_risk") == is_at_risk]
        result.sort(key=lambda s: s.get("overall_score", 100))
        return api_response(True, result)

    q = db.table("health_scores").select("*").eq("firm_id", current_user["firm_id"])
    if is_critical is not None:
        q = q.eq("is_critical", is_critical)
    if is_at_risk is not None:
        q = q.eq("is_at_risk", is_at_risk)
    res = q.order("overall_score").execute()  # worst first (ascending)
    return api_response(True, res.data or [])


@router.get("/scores/{client_id}")
def get_score(
    client_id: str,
    current_user: dict = Depends(rbac("clients", "read")),
):
    db = _db()
    if not db:
        score = _MOCK_SCORES.get(client_id)
        if not score:
            raise HTTPException(status_code=404, detail="Health score not found — run /calculate first")
        return api_response(True, score)

    res = db.table("health_scores").select("*").eq("client_id", client_id).eq("firm_id", current_user["firm_id"]).single().execute().data
    if not res:
        raise HTTPException(status_code=404, detail="Health score not found — run /calculate first")
    return api_response(True, res)


@router.post("/scores/{client_id}/calculate")
def calculate_score(
    client_id: str,
    current_user: dict = Depends(rbac("clients", "write")),
):
    """
    Calculate (or recalculate) health score for a client.
    Saves to health_scores (upsert) and inserts a health_score_history row.
    Logs timeline event if score changed.
    """
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()

    if not db:
        scores = _calculate_scores_mock(client_id)
        old = _MOCK_SCORES.get(client_id)
        old_overall = old.get("overall_score") if old else None

        row = {
            "id":         str(uuid.uuid4()),
            "client_id":  client_id,
            "firm_id":    firm_id,
            "calculated_at": now,
            **scores,
        }
        _MOCK_SCORES[client_id] = row

        # Save history
        _MOCK_HISTORY.append({**row, "id": str(uuid.uuid4()), "score_id": row["id"]})

        if old_overall is not None and old_overall != scores["overall_score"]:
            timeline_service.log(
                client_id, "lifecycle", "Health Score Changed",
                f"Health score changed from {old_overall} to {scores['overall_score']} (grade {scores['health_grade']})",
                "warning" if scores["is_at_risk"] else "info",
                firm_id=firm_id,
            )

        return api_response(True, row)

    # Verify client belongs to firm
    client = db.table("clients").select("id, name").eq("id", client_id).eq("firm_id", firm_id).single().execute().data
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    scores = _calculate_scores_db(db, client_id, firm_id)

    # Fetch previous score for change detection
    old_row = db.table("health_scores").select("overall_score, id").eq("client_id", client_id).eq("firm_id", firm_id).limit(1).execute().data
    old_overall = (old_row[0]["overall_score"] if old_row else None)

    score_id = str(uuid.uuid4())
    upsert_payload = {
        "id":            score_id,
        "client_id":     client_id,
        "firm_id":       firm_id,
        "calculated_at": now,
        "client_name":   client.get("name", ""),
        **scores,
    }

    # Upsert using on_conflict on (client_id, firm_id)
    try:
        res = db.table("health_scores").upsert(upsert_payload, on_conflict="client_id,firm_id").execute()
        saved = (res.data or [upsert_payload])[0]
    except Exception:
        # Fallback: try insert then update
        try:
            res = db.table("health_scores").insert(upsert_payload).execute()
            saved = (res.data or [upsert_payload])[0]
        except Exception:
            res = db.table("health_scores").update({
                "calculated_at": now,
                **scores,
            }).eq("client_id", client_id).eq("firm_id", firm_id).execute()
            saved = (res.data or [upsert_payload])[0]

    # Insert history row
    try:
        db.table("health_score_history").insert({
            "id":            str(uuid.uuid4()),
            "firm_id":       firm_id,
            "client_id":     client_id,
            "calculated_at": now,
            **scores,
        }).execute()
    except Exception:
        pass  # Non-fatal

    # Log timeline event only if score changed
    if old_overall is not None and old_overall != scores["overall_score"]:
        timeline_service.log(
            client_id, "lifecycle", "Health Score Changed",
            f"Health score changed from {old_overall} to {scores['overall_score']} (grade {scores['health_grade']})",
            "warning" if scores["is_at_risk"] else "info",
            firm_id=firm_id,
            entity_type="health_score", entity_id=score_id,
            actor_id=current_user.get("auth_user_id"),
        )

    return api_response(True, saved)


# ─── Overrides ────────────────────────────────────────────────────────────────

@router.get("/scores/{client_id}/history")
def get_score_history(
    client_id: str,
    limit: int = Query(20),
    current_user: dict = Depends(rbac("clients", "read")),
):
    db = _db()
    if not db:
        result = [h for h in _MOCK_HISTORY if h.get("client_id") == client_id]
        result.sort(key=lambda h: h.get("calculated_at", ""), reverse=True)
        return api_response(True, result[:limit])

    res = db.table("health_score_history").select(
        "id, overall_score, health_grade, calculated_at, compliance_score, accounting_score, documents_score, responsiveness_score, relationship_risk_score, financial_risk_score, engagement_health_score"
    ).eq("client_id", client_id).eq("firm_id", current_user["firm_id"]).order("calculated_at", desc=True).limit(limit).execute()
    return api_response(True, res.data or [])


@router.get("/overrides")
def list_overrides(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("clients", "read")),
):
    db = _db()
    if not db:
        result = [o for o in _MOCK_OVERRIDES if o.get("client_id") == client_id and o.get("is_active")]
        return api_response(True, result)

    res = db.table("health_score_overrides").select("*").eq("firm_id", current_user["firm_id"]).eq("client_id", client_id).eq("is_active", True).order("created_at", desc=True).execute()
    return api_response(True, res.data or [])


@router.post("/recalculate-all")
def recalculate_all(
    current_user: dict = Depends(rbac("clients", "write")),
):
    """Recalculate health scores for all clients in the firm."""
    db = _db()
    firm_id = current_user["firm_id"]
    if not db:
        return api_response(True, {"updated": 0, "message": "No DB — mock mode"})

    clients_res = db.table("clients").select("id").eq("firm_id", firm_id).execute()
    clients = clients_res.data or []
    updated = 0
    now = datetime.now(timezone.utc).isoformat()
    for client in clients:
        try:
            scores = _calculate_scores_db(db, client["id"], firm_id)
            score_id = str(uuid.uuid4())
            upsert_payload = {
                "id": score_id, "client_id": client["id"], "firm_id": firm_id,
                "calculated_at": now, **scores,
            }
            db.table("health_scores").upsert(upsert_payload, on_conflict="client_id,firm_id").execute()
            db.table("health_score_history").insert({
                "id": str(uuid.uuid4()), "firm_id": firm_id, "client_id": client["id"],
                "calculated_at": now, **scores,
            }).execute()
            updated += 1
        except Exception:
            pass
    return api_response(True, {"updated": updated})


@router.post("/scores/{client_id}/override")
def create_override(
    client_id: str,
    data: OverrideIn,
    current_user: dict = Depends(rbac("clients", "write")),
):
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()

    row = {
        "id":             str(uuid.uuid4()),
        "firm_id":        firm_id,
        "client_id":      client_id,
        "dimension":      data.dimension,
        "override_score": data.override_score,
        "reason":         data.reason,
        "expires_at":     data.expires_at,
        "is_active":      True,
        "created_at":     now,
        "created_by":     current_user.get("auth_user_id"),
    }

    if not db:
        _MOCK_OVERRIDES.append(row)
        return api_response(True, row)

    res = db.table("health_score_overrides").insert(row).execute()
    return api_response(True, (res.data or [row])[0])


@router.delete("/overrides/{override_id}")
def deactivate_override(
    override_id: str,
    current_user: dict = Depends(rbac("clients", "write")),
):
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        for i, o in enumerate(_MOCK_OVERRIDES):
            if o["id"] == override_id:
                _MOCK_OVERRIDES[i]["is_active"] = False
                return api_response(True, {"override_id": override_id, "is_active": False})
        raise HTTPException(status_code=404, detail="Override not found")

    existing = db.table("health_score_overrides").select("id").eq("id", override_id).eq("firm_id", firm_id).single().execute().data
    if not existing:
        raise HTTPException(status_code=404, detail="Override not found")

    res = db.table("health_score_overrides").update({
        "is_active":      False,
        "deactivated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", override_id).eq("firm_id", firm_id).execute()

    return api_response(True, {"override_id": override_id, "is_active": False})


# ─── Alerts ───────────────────────────────────────────────────────────────────

@router.get("/alerts")
def list_alerts(
    client_id: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("clients", "read")),
):
    db = _db()
    if not db:
        result = [a for a in _MOCK_ALERTS if not a.get("is_resolved")]
        if client_id:
            result = [a for a in result if a.get("client_id") == client_id]
        if severity:
            result = [a for a in result if a.get("severity") == severity]
        return api_response(True, result)

    q = db.table("health_alerts").select("*").eq("firm_id", current_user["firm_id"]).eq("is_resolved", False)
    if client_id:
        q = q.eq("client_id", client_id)
    if severity:
        q = q.eq("severity", severity)
    res = q.order("created_at", desc=True).execute()
    return api_response(True, res.data or [])


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(
    alert_id: str,
    data: AlertResolveIn,
    current_user: dict = Depends(rbac("clients", "write")),
):
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()

    if not db:
        for i, a in enumerate(_MOCK_ALERTS):
            if a["id"] == alert_id:
                _MOCK_ALERTS[i]["is_resolved"] = True
                _MOCK_ALERTS[i]["resolved_at"] = now
                if data.resolution_notes:
                    _MOCK_ALERTS[i]["resolution_notes"] = data.resolution_notes
                return api_response(True, _MOCK_ALERTS[i])
        raise HTTPException(status_code=404, detail="Alert not found")

    existing = db.table("health_alerts").select("id").eq("id", alert_id).eq("firm_id", firm_id).single().execute().data
    if not existing:
        raise HTTPException(status_code=404, detail="Alert not found")

    update = {
        "is_resolved":  True,
        "resolved_at":  now,
        "resolved_by":  current_user.get("auth_user_id"),
    }
    if data.resolution_notes:
        update["resolution_notes"] = data.resolution_notes

    res = db.table("health_alerts").update(update).eq("id", alert_id).eq("firm_id", firm_id).execute()
    return api_response(True, (res.data or [{}])[0])


# ─── Dashboard ────────────────────────────────────────────────────────────────

@router.get("/dashboard")
def health_dashboard(
    current_user: dict = Depends(rbac("clients", "read")),
):
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        scores = list(_MOCK_SCORES.values())
        critical = [s for s in scores if s.get("is_critical")]
        at_risk  = [s for s in scores if s.get("is_at_risk") and not s.get("is_critical")]

        # Grade distribution — integer counts
        dist: dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
        for s in scores:
            g = s.get("health_grade", "F")
            dist[g] = dist.get(g, 0) + 1

        total_score = sum(s.get("overall_score", 0) for s in scores)
        avg_score = total_score // len(scores) if scores else 0

        top_alerts = [a for a in _MOCK_ALERTS if not a.get("is_resolved")][:10]

        return api_response(True, {
            "critical_clients":   critical,
            "at_risk_clients":    at_risk,
            "average_score":      avg_score,
            "score_distribution": dist,
            "top_alerts":         top_alerts,
        })

    # Critical clients (score < 40)
    critical_res = db.table("health_scores").select("client_id, overall_score, health_grade, is_critical, is_at_risk").eq("firm_id", firm_id).eq("is_critical", True).order("overall_score").execute()
    critical_clients = critical_res.data or []

    # At-risk clients (40 <= score < 60)
    at_risk_res = db.table("health_scores").select("client_id, overall_score, health_grade, is_critical, is_at_risk").eq("firm_id", firm_id).eq("is_at_risk", True).eq("is_critical", False).order("overall_score").execute()
    at_risk_clients = at_risk_res.data or []

    # All scores for distribution + average
    all_scores_res = db.table("health_scores").select("overall_score, health_grade").eq("firm_id", firm_id).execute()
    all_scores = all_scores_res.data or []

    dist: dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
    total = 0
    for s in all_scores:
        g = s.get("health_grade", "F")
        dist[g] = dist.get(g, 0) + 1
        total += int(s.get("overall_score") or 0)

    # Integer division for average — never float
    avg_score = total // len(all_scores) if all_scores else 0

    # Top unresolved alerts
    alerts_res = db.table("health_alerts").select("*").eq("firm_id", firm_id).eq("is_resolved", False).order("created_at", desc=True).limit(10).execute()
    top_alerts = alerts_res.data or []

    return api_response(True, {
        "critical_clients":   critical_clients,
        "at_risk_clients":    at_risk_clients,
        "average_score":      avg_score,
        "score_distribution": dist,
        "top_alerts":         top_alerts,
    })
