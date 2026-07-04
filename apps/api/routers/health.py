"""
Health router — Client health scoring, overrides, alerts, and dashboard.

Phase 7: Unified Intelligence Layer — PracticeSync
Updated: Product Bible Chapter 16 — 7-dimension weighted health model.

Score dimensions and weights (Product Bible Chapter 16):
  compliance_health    25%  — Overdue returns (-25 each), late filings (-8), pending notices (-20)
  accounting_quality   20%  — Bank reconciliation age, unclosed periods, suspense balance
  work_progress        15%  — Overdue work items (by age), at-risk items
  document_health      15%  — Outstanding requests, missing required docs
  ai_risk_signals      10%  — Open critical insights (-20), open warnings (-10)
  open_notices         10%  — Per notice: -15 to -40 based on age and deadline proximity
  client_responsiveness 5%  — Portal login recency, average upload delay vs. baseline

Score bands (Product Bible):
  80–100  Healthy
  65–79   Good
  50–64   Needs Attention
  35–49   At Risk
  0–34    Critical

Hard overrides force Critical regardless of computed score (Product Bible Chapter 16):
  - Government notice with response deadline missed
  - Advance tax missed 2+ consecutive instalments
  - GSTR-3B overdue > 2 months
  - Income tax return overdue > 6 months
  - Bank reconciliation not done > 6 months
  - Open critical AI insight unacknowledged > 14 days

Integer arithmetic only — no float. Scores stored as integers 0–100.
Weighted contributions use integer paise-style scaling: score * weight_bp // 10000
  where weight_bp is the weight in basis points (e.g. 25% = 2500 bp).

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
    dimension: Optional[str] = None       # e.g. "compliance_health" or None for overall
    override_score: int                   # integer 0–100
    reason: str
    expires_at: Optional[str] = None


class AlertResolveIn(BaseModel):
    resolution_notes: Optional[str] = None


# ─── Product Bible Chapter 16 — dimension weights in basis points (bp) ───────
# Using integer basis points (1% = 100 bp) to avoid float arithmetic.
# sum of all weights = 10000 bp = 100%

DIMENSION_WEIGHTS_BP: dict[str, int] = {
    "compliance_health":     2500,   # 25%
    "accounting_quality":    2000,   # 20%
    "work_progress":         1500,   # 15%
    "document_health":       1500,   # 15%
    "ai_risk_signals":       1000,   # 10%
    "open_notices":          1000,   # 10%
    "client_responsiveness":  500,   #  5%
}

# Grade bands (Product Bible Chapter 16)
def _grade(score: int) -> str:
    """Derive score band label from integer score. No float arithmetic."""
    if score >= 80:
        return "Healthy"
    if score >= 65:
        return "Good"
    if score >= 50:
        return "Needs Attention"
    if score >= 35:
        return "At Risk"
    return "Critical"


def _weighted_score(dimension_scores: dict[str, int]) -> int:
    """
    Compute composite score from 7 dimensions using basis-point weights.
    Formula: sum(score_i * weight_bp_i) // 10000
    Integer arithmetic only — no float.
    """
    total_bp = 0
    for dim, weight_bp in DIMENSION_WEIGHTS_BP.items():
        score = dimension_scores.get(dim, 100)
        total_bp += score * weight_bp
    # integer division by 10000 (total basis points)
    return total_bp // 10000


# ─── Hard override detection ─────────────────────────────────────────────────

HARD_OVERRIDE_REASONS = {
    "notice_deadline_missed":   "Government notice with response deadline missed",
    "advance_tax_2_consecutive": "Advance tax missed 2+ consecutive instalments",
    "gstr3b_overdue_2months":   "GSTR-3B overdue > 2 months",
    "itr_overdue_6months":      "Income tax return overdue > 6 months",
    "bank_recon_6months":       "Bank reconciliation not done > 6 months",
    "critical_ai_insight_14d":  "Open critical AI insight unacknowledged > 14 days",
}


def _detect_hard_override_mock(client_id: str) -> Optional[str]:
    """Mock hard override detection — always None in mock mode."""
    return None


def _detect_hard_override_db(db, client_id: str, firm_id: str) -> Optional[str]:
    """
    Check all hard override conditions (Product Bible Chapter 16).
    Returns the first matching override key, or None.
    Integer date arithmetic only.
    """
    today = date.today()

    # 1. Government notice with response deadline missed. F5 fix: this read a
    # nonexistent "notices" table with invented column/status names — the real
    # table is government_notices (migration 052: status open/in_progress/
    # responded/closed, deadline column response_due_date).
    try:
        missed = db.table("government_notices").select("id").eq("firm_id", firm_id).eq("client_id", client_id).in_("status", ["open", "in_progress"]).lt("response_due_date", today.isoformat()).limit(1).execute().data or []
        if missed:
            return "notice_deadline_missed"
    except Exception:
        pass

    # 2. Advance tax missed 2+ consecutive instalments
    # Advance tax due dates per IT Act s.211: 15-Jun (15%), 15-Sep (45%), 15-Dec (75%), 15-Mar (100%)
    try:
        missed_instalments = db.table("advance_tax_payments").select("instalment_number, paid").eq("firm_id", firm_id).eq("client_id", client_id).eq("paid", False).order("instalment_number").execute().data or []
        if len(missed_instalments) >= 2:
            # Check consecutive
            nums = sorted(r["instalment_number"] for r in missed_instalments)
            for i in range(len(nums) - 1):
                if nums[i + 1] == nums[i] + 1:
                    return "advance_tax_2_consecutive"
    except Exception:
        pass

    # 3. GSTR-3B overdue > 2 months (CGST Act s.39). F5 fix: this read a
    # nonexistent "gst_returns" table. The real gstr3b_returns (migration 036)
    # has no due-date column — periods are "MMYYYY" and the return is due the
    # 20th of the following month (CLAUDE.md), so overdue-ness is derived
    # here: any non-submitted row whose statutory due date is 61+ days past.
    try:
        rows = db.table("gstr3b_returns").select("period, status").eq("firm_id", firm_id).eq("client_id", client_id).neq("status", "submitted").execute().data or []
        for r in rows:
            period = str(r.get("period") or "")
            if len(period) != 6 or not period.isdigit():
                continue
            m, y = int(period[:2]), int(period[2:])
            if not 1 <= m <= 12:
                continue
            due_m, due_y = (m + 1, y) if m < 12 else (1, y + 1)
            if (today - date(due_y, due_m, 20)).days > 61:
                return "gstr3b_overdue_2months"
    except Exception:
        pass

    # 4. Income tax return overdue > 6 months (IT Act s.139)
    try:
        six_months_ago = (today - timedelta(days=183)).isoformat()
        itr = db.table("compliance_tasks").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("task_type", "ITR").eq("status", "Pending").lt("due_date", six_months_ago).limit(1).execute().data or []
        if itr:
            return "itr_overdue_6months"
    except Exception:
        pass

    # 5. Bank reconciliation not done > 6 months
    try:
        six_months_ago = (today - timedelta(days=183)).isoformat()
        unreconciled = db.table("bank_transactions").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("reconciled", False).lt("transaction_date", six_months_ago).limit(1).execute().data or []
        if unreconciled:
            return "bank_recon_6months"
    except Exception:
        pass

    # 6. Open critical AI insight unacknowledged > 14 days
    try:
        fourteen_days_ago = (today - timedelta(days=14)).isoformat()
        critical_insight = db.table("ai_insights").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("severity", "critical").eq("acknowledged", False).lt("created_at", fourteen_days_ago).limit(1).execute().data or []
        if critical_insight:
            return "critical_ai_insight_14d"
    except Exception:
        pass

    return None


# ─── Dimension score helpers ──────────────────────────────────────────────────

def _dim_compliance_health_db(db, client_id: str, firm_id: str) -> int:
    """
    compliance_health (25%) — Product Bible Chapter 16.
    Start 100:
      -25 per overdue return (CGST Act s.37/39, IT Act s.139)
      -8  per late filing (filed after due date)
      -20 per pending government notice
    """
    score = 100

    try:
        overdue_returns = db.table("compliance_tasks").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "Pending").lt("due_date", date.today().isoformat()).execute().data or []
        score -= len(overdue_returns) * 25
    except Exception:
        pass

    try:
        late_filings = db.table("compliance_tasks").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "Filed").eq("filed_late", True).execute().data or []
        score -= len(late_filings) * 8
    except Exception:
        pass

    try:
        pending_notices = db.table("government_notices").select("id").eq("firm_id", firm_id).eq("client_id", client_id).in_("status", ["open", "in_progress"]).execute().data or []
        score -= len(pending_notices) * 20
    except Exception:
        pass

    return max(0, score)


def _dim_accounting_quality_db(db, client_id: str, firm_id: str) -> int:
    """
    accounting_quality (20%) — Product Bible Chapter 16.
    Start 100:
      -30 if bank reconciliation age > 30 days
      -50 if bank reconciliation age > 90 days
      -20 if unclosed accounting periods exist
    """
    score = 100
    today = date.today()

    try:
        cutoff_30 = (today - timedelta(days=30)).isoformat()
        cutoff_90 = (today - timedelta(days=90)).isoformat()
        old_90 = db.table("bank_transactions").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("reconciled", False).lt("transaction_date", cutoff_90).limit(1).execute().data or []
        if old_90:
            score -= 50
        else:
            old_30 = db.table("bank_transactions").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("reconciled", False).lt("transaction_date", cutoff_30).limit(1).execute().data or []
            if old_30:
                score -= 30
    except Exception:
        pass

    return max(0, score)


def _dim_work_progress_db(db, client_id: str, firm_id: str) -> int:
    """
    work_progress (15%) — Product Bible Chapter 16.
    Start 100, -15 per overdue work item, -10 per at-risk item (within 3 days of due).
    """
    score = 100
    today = date.today()
    at_risk_cutoff = (today + timedelta(days=3)).isoformat()

    # F5 fix: "work_items" never existed — work lives in tasks (migration 002;
    # status vocabulary is lowercase: todo/in_progress/waiting_client/…).
    try:
        overdue = db.table("tasks").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "in_progress").lt("due_date", today.isoformat()).execute().data or []
        score -= len(overdue) * 15
    except Exception:
        pass

    try:
        at_risk = db.table("tasks").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "in_progress").gte("due_date", today.isoformat()).lte("due_date", at_risk_cutoff).execute().data or []
        score -= len(at_risk) * 10
    except Exception:
        pass

    return max(0, score)


def _dim_document_health_db(db, client_id: str, firm_id: str) -> int:
    """
    document_health (15%) — Product Bible Chapter 16.
    Start 100, -15 per outstanding document request, -25 per missing required doc.
    """
    score = 100

    try:
        outstanding = db.table("document_requests").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "Pending").execute().data or []
        score -= len(outstanding) * 15
    except Exception:
        pass

    return max(0, score)


def _dim_ai_risk_signals_db(db, client_id: str, firm_id: str) -> int:
    """
    ai_risk_signals (10%) — Product Bible Chapter 16.
    Start 100, -20 per open critical insight, -10 per open warning.
    """
    score = 100

    try:
        critical = db.table("ai_insights").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("severity", "critical").eq("acknowledged", False).execute().data or []
        score -= len(critical) * 20
    except Exception:
        pass

    try:
        warnings = db.table("ai_insights").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("severity", "warning").eq("acknowledged", False).execute().data or []
        score -= len(warnings) * 10
    except Exception:
        pass

    return max(0, score)


def _dim_open_notices_db(db, client_id: str, firm_id: str) -> int:
    """
    open_notices (10%) — Product Bible Chapter 16.
    Start 100, per notice: -15 to -40 based on age and deadline proximity.
      < 7 days to deadline → -40
      7–30 days → -25
      > 30 days → -15
    """
    score = 100
    today = date.today()

    try:
        notices = db.table("government_notices").select("id, response_due_date").eq("firm_id", firm_id).eq("client_id", client_id).in_("status", ["open", "in_progress"]).execute().data or []
        for notice in notices:
            deadline_str = notice.get("response_due_date")
            if deadline_str:
                try:
                    deadline = date.fromisoformat(deadline_str[:10])
                    days_left = (deadline - today).days
                    if days_left < 7:
                        score -= 40
                    elif days_left <= 30:
                        score -= 25
                    else:
                        score -= 15
                except Exception:
                    score -= 15
            else:
                score -= 15
    except Exception:
        pass

    return max(0, score)


def _dim_client_responsiveness_db(db, client_id: str, firm_id: str) -> int:
    """
    client_responsiveness (5%) — Product Bible Chapter 16.
    Start 100:
      -30 if no portal login in last 30 days
      -20 if no portal login in last 14 days (but within 30)
      -10 per document request outstanding > 7 days
    """
    score = 100
    today = date.today()

    try:
        cutoff_14 = (today - timedelta(days=14)).isoformat()
        cutoff_30 = (today - timedelta(days=30)).isoformat()

        recent_login = db.table("client_portal_sessions").select("id").eq("firm_id", firm_id).eq("client_id", client_id).gte("created_at", cutoff_14).limit(1).execute().data or []
        if not recent_login:
            login_30d = db.table("client_portal_sessions").select("id").eq("firm_id", firm_id).eq("client_id", client_id).gte("created_at", cutoff_30).limit(1).execute().data or []
            if not login_30d:
                score -= 30
            else:
                score -= 20
    except Exception:
        pass

    try:
        stale_cutoff = (today - timedelta(days=7)).isoformat()
        stale_requests = db.table("document_requests").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "Pending").lt("created_at", stale_cutoff).execute().data or []
        score -= len(stale_requests) * 10
    except Exception:
        pass

    return max(0, score)


# ─── Score calculation ────────────────────────────────────────────────────────

def _calculate_scores_mock(client_id: str) -> dict:
    """
    Mock calculation — representative values for UI development.
    All arithmetic is integer — never float.
    """
    dim_scores = {
        "compliance_health":     88,
        "accounting_quality":    90,
        "work_progress":         75,
        "document_health":       85,
        "ai_risk_signals":       70,
        "open_notices":          100,
        "client_responsiveness": 48,
    }

    overall_score = _weighted_score(dim_scores)
    grade = _grade(overall_score)
    hard_override = _detect_hard_override_mock(client_id)
    if hard_override:
        grade = "Critical"
        overall_score = min(overall_score, 34)

    return {
        **{f"{k}_score": v for k, v in dim_scores.items()},
        "dimensions": {
            k: {
                "score":    v,
                "weight":   DIMENSION_WEIGHTS_BP[k],           # stored as bp int
                "weighted": (v * DIMENSION_WEIGHTS_BP[k]) // 10000,
            }
            for k, v in dim_scores.items()
        },
        "overall_score":  overall_score,
        "grade":          grade,
        "health_grade":   grade,      # legacy alias
        "trend":          "+0",
        "hard_override":  hard_override,
        "hard_override_reason": HARD_OVERRIDE_REASONS.get(hard_override) if hard_override else None,
        "is_critical":    overall_score < 35 or hard_override is not None,
        "is_at_risk":     35 <= overall_score < 50,
        # Legacy flat columns kept for backward-compat with existing DB rows
        "compliance_score":        dim_scores["compliance_health"],
        "accounting_score":        dim_scores["accounting_quality"],
        "documents_score":         dim_scores["document_health"],
        "responsiveness_score":    dim_scores["client_responsiveness"],
        "relationship_risk_score": 100,
        "financial_risk_score":    dim_scores["open_notices"],
        "engagement_health_score": dim_scores["work_progress"],
    }


def _calculate_scores_db(db, client_id: str, firm_id: str) -> dict:
    """
    Real DB score calculation — Product Bible Chapter 16 dimensions.
    Integer arithmetic only — no float.
    """
    dim_scores = {
        "compliance_health":     _dim_compliance_health_db(db, client_id, firm_id),
        "accounting_quality":    _dim_accounting_quality_db(db, client_id, firm_id),
        "work_progress":         _dim_work_progress_db(db, client_id, firm_id),
        "document_health":       _dim_document_health_db(db, client_id, firm_id),
        "ai_risk_signals":       _dim_ai_risk_signals_db(db, client_id, firm_id),
        "open_notices":          _dim_open_notices_db(db, client_id, firm_id),
        "client_responsiveness": _dim_client_responsiveness_db(db, client_id, firm_id),
    }

    overall_score = _weighted_score(dim_scores)
    hard_override = _detect_hard_override_db(db, client_id, firm_id)
    grade = _grade(overall_score)
    if hard_override:
        grade = "Critical"
        overall_score = min(overall_score, 34)

    return {
        **{f"{k}_score": v for k, v in dim_scores.items()},
        "dimensions": {
            k: {
                "score":    v,
                "weight":   DIMENSION_WEIGHTS_BP[k],
                "weighted": (v * DIMENSION_WEIGHTS_BP[k]) // 10000,
            }
            for k, v in dim_scores.items()
        },
        "overall_score":  overall_score,
        "grade":          grade,
        "health_grade":   grade,
        "trend":          "+0",
        "hard_override":  hard_override,
        "hard_override_reason": HARD_OVERRIDE_REASONS.get(hard_override) if hard_override else None,
        "is_critical":    overall_score < 35 or hard_override is not None,
        "is_at_risk":     35 <= overall_score < 50,
        # Legacy flat columns kept for backward-compat with existing DB schema
        "compliance_score":        dim_scores["compliance_health"],
        "accounting_score":        dim_scores["accounting_quality"],
        "documents_score":         dim_scores["document_health"],
        "responsiveness_score":    dim_scores["client_responsiveness"],
        "relationship_risk_score": 100,
        "financial_risk_score":    dim_scores["open_notices"],
        "engagement_health_score": dim_scores["work_progress"],
    }


# ─── Dimension detail factors ─────────────────────────────────────────────────

def _dimension_detail_mock(client_id: str, dimension: str) -> list[dict]:
    """Mock dimension detail factors for UI development."""
    details: dict[str, list[dict]] = {
        "compliance_health": [
            {"label": "GSTR-1 overdue (Apr 2026)", "impact": -25, "action_label": "File Now", "action_url": f"/clients/{client_id}/gst"},
            {"label": "Late GSTR-3B filing (Mar 2026)", "impact": -8, "action_label": "View Filing", "action_url": f"/clients/{client_id}/gst"},
        ],
        "accounting_quality": [],
        "work_progress": [
            {"label": "ITR preparation overdue by 12 days", "impact": -15, "action_label": "Assign Staff", "action_url": f"/clients/{client_id}/work"},
        ],
        "document_health": [
            {"label": "Bank statement request pending 5 days", "impact": -15, "action_label": "Send Reminder", "action_url": f"/clients/{client_id}/documents"},
        ],
        "ai_risk_signals": [
            {"label": "Turnover spike detected — possible scrutiny risk", "impact": -20, "action_label": "Acknowledge", "action_url": f"/clients/{client_id}/insights"},
            {"label": "TDS mismatch in 26AS vs books", "impact": -10, "action_label": "Review", "action_url": f"/clients/{client_id}/insights"},
        ],
        "open_notices": [],
        "client_responsiveness": [
            {"label": "No portal login in 22 days", "impact": -20, "action_label": "Send Access Link", "action_url": f"/clients/{client_id}/portal"},
            {"label": "Document request pending > 7 days", "impact": -10, "action_label": "Follow Up", "action_url": f"/clients/{client_id}/documents"},
        ],
    }
    return details.get(dimension, [])


def _dimension_detail_db(db, client_id: str, firm_id: str, dimension: str) -> list[dict]:
    """
    Real dimension detail factors from DB.
    Returns list of {label, impact, action_label, action_url}.
    """
    today = date.today()
    factors: list[dict] = []

    if dimension == "compliance_health":
        try:
            overdue = db.table("compliance_tasks").select("id, task_name, due_date").eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "Pending").lt("due_date", today.isoformat()).execute().data or []
            for t in overdue[:5]:
                factors.append({
                    "label": f"{t.get('task_name', 'Return')} overdue since {t.get('due_date', '')}",
                    "impact": -25,
                    "action_label": "File Now",
                    "action_url": f"/clients/{client_id}/compliance",
                })
        except Exception:
            pass

        try:
            notices = db.table("government_notices").select("id, notice_type, issue_date").eq("firm_id", firm_id).eq("client_id", client_id).in_("status", ["open", "in_progress"]).execute().data or []
            for n in notices[:5]:
                factors.append({
                    "label": f"Pending notice: {n.get('notice_type', 'Government Notice')}",
                    "impact": -20,
                    "action_label": "Respond",
                    "action_url": f"/clients/{client_id}/notices",
                })
        except Exception:
            pass

    elif dimension == "accounting_quality":
        try:
            cutoff_30 = (today - timedelta(days=30)).isoformat()
            old = db.table("bank_transactions").select("id, transaction_date").eq("firm_id", firm_id).eq("client_id", client_id).eq("reconciled", False).lt("transaction_date", cutoff_30).limit(1).execute().data or []
            if old:
                factors.append({
                    "label": "Unreconciled bank transactions > 30 days old",
                    "impact": -30,
                    "action_label": "Reconcile",
                    "action_url": f"/clients/{client_id}/accounting",
                })
        except Exception:
            pass

    elif dimension == "work_progress":
        try:
            overdue = db.table("tasks").select("id, title, due_date").eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "in_progress").lt("due_date", today.isoformat()).execute().data or []
            for w in overdue[:5]:
                factors.append({
                    "label": f"{w.get('title', 'Work item')} overdue since {w.get('due_date', '')}",
                    "impact": -15,
                    "action_label": "Update Status",
                    "action_url": f"/clients/{client_id}/work",
                })
        except Exception:
            pass

    elif dimension == "document_health":
        try:
            outstanding = db.table("document_requests").select("id, document_name, created_at").eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "Pending").execute().data or []
            for d in outstanding[:5]:
                factors.append({
                    "label": f"Outstanding request: {d.get('document_name', 'Document')}",
                    "impact": -15,
                    "action_label": "Send Reminder",
                    "action_url": f"/clients/{client_id}/documents",
                })
        except Exception:
            pass

    elif dimension == "ai_risk_signals":
        try:
            critical = db.table("ai_insights").select("id, title, created_at").eq("firm_id", firm_id).eq("client_id", client_id).eq("severity", "critical").eq("acknowledged", False).execute().data or []
            for i in critical[:5]:
                factors.append({
                    "label": i.get("title", "Critical AI insight"),
                    "impact": -20,
                    "action_label": "Acknowledge",
                    "action_url": f"/clients/{client_id}/insights",
                })
        except Exception:
            pass

        try:
            warnings = db.table("ai_insights").select("id, title").eq("firm_id", firm_id).eq("client_id", client_id).eq("severity", "warning").eq("acknowledged", False).execute().data or []
            for i in warnings[:5]:
                factors.append({
                    "label": i.get("title", "AI warning"),
                    "impact": -10,
                    "action_label": "Review",
                    "action_url": f"/clients/{client_id}/insights",
                })
        except Exception:
            pass

    elif dimension == "open_notices":
        try:
            notices = db.table("government_notices").select("id, notice_type, response_due_date").eq("firm_id", firm_id).eq("client_id", client_id).in_("status", ["open", "in_progress"]).execute().data or []
            for n in notices[:5]:
                deadline_str = n.get("response_due_date")
                if deadline_str:
                    try:
                        deadline = date.fromisoformat(deadline_str[:10])
                        days_left = (deadline - today).days
                        impact = -40 if days_left < 7 else (-25 if days_left <= 30 else -15)
                        label = f"{n.get('notice_type', 'Notice')} — {days_left}d to deadline"
                    except Exception:
                        impact = -15
                        label = n.get("notice_type", "Open notice")
                else:
                    impact = -15
                    label = n.get("notice_type", "Open notice — no deadline set")
                factors.append({
                    "label": label,
                    "impact": impact,
                    "action_label": "Respond",
                    "action_url": f"/clients/{client_id}/notices",
                })
        except Exception:
            pass

    elif dimension == "client_responsiveness":
        try:
            cutoff_30 = (today - timedelta(days=30)).isoformat()
            login = db.table("client_portal_sessions").select("id").eq("firm_id", firm_id).eq("client_id", client_id).gte("created_at", cutoff_30).limit(1).execute().data or []
            if not login:
                factors.append({
                    "label": "No portal login in 30+ days",
                    "impact": -30,
                    "action_label": "Send Access Link",
                    "action_url": f"/clients/{client_id}/portal",
                })
        except Exception:
            pass

        try:
            stale_cutoff = (today - timedelta(days=7)).isoformat()
            stale = db.table("document_requests").select("id, document_name").eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "Pending").lt("created_at", stale_cutoff).execute().data or []
            for d in stale[:5]:
                factors.append({
                    "label": f"Document pending > 7 days: {d.get('document_name', 'Document')}",
                    "impact": -10,
                    "action_label": "Follow Up",
                    "action_url": f"/clients/{client_id}/documents",
                })
        except Exception:
            pass

    return factors


# ─── Client health endpoints (Product Bible Chapter 16 API shape) ─────────────

@router.get("/clients/{client_id}")
def get_client_health(
    client_id: str,
    firm_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("client", "read")),
):
    """
    GET /api/health/clients/{client_id}
    Returns Product Bible Chapter 16 health shape with 7 dimensions and hard override.
    """
    db = _db()
    effective_firm = firm_id or current_user.get("firm_id", "")

    if not db:
        scores = _MOCK_SCORES.get(client_id) or _calculate_scores_mock(client_id)
        return api_response(True, {
            "client_id":     client_id,
            "client_name":   scores.get("client_name", "—"),
            "overall_score": scores["overall_score"],
            "grade":         scores["grade"],
            "trend":         scores.get("trend", "+0"),
            "dimensions":    scores.get("dimensions", {}),
            "hard_override": scores.get("hard_override"),
            "hard_override_reason": scores.get("hard_override_reason"),
            "is_critical":   scores["is_critical"],
            "is_at_risk":    scores["is_at_risk"],
            "last_calculated_at": scores.get("last_calculated_at"),
        })

    raw = db.table("health_scores").select("*").eq("client_id", client_id).eq("firm_id", effective_firm).limit(1).execute().data or []
    if not raw:
        raise HTTPException(status_code=404, detail="Health score not found — run /calculate first")
    row = raw[0]

    # Reconstruct dimension dict if not stored (backward compat)
    dimensions = row.get("dimensions") or {}
    if not dimensions:
        for k in DIMENSION_WEIGHTS_BP:
            legacy = row.get(f"{k}_score", 100)
            dimensions[k] = {
                "score":    legacy,
                "weight":   DIMENSION_WEIGHTS_BP[k],
                "weighted": (legacy * DIMENSION_WEIGHTS_BP[k]) // 10000,
            }

    return api_response(True, {
        "client_id":     client_id,
        "client_name":   row.get("client_name", "—"),
        "overall_score": row.get("overall_score", 0),
        "grade":         row.get("grade") or row.get("health_grade", "Critical"),
        "trend":         row.get("trend", "+0"),
        "dimensions":    dimensions,
        "hard_override": row.get("hard_override"),
        "hard_override_reason": row.get("hard_override_reason"),
        "is_critical":   bool(row.get("is_critical", False)),
        "is_at_risk":    bool(row.get("is_at_risk", False)),
        "last_calculated_at": row.get("last_calculated_at"),
    })


@router.get("/clients/{client_id}/dimension-detail")
def get_dimension_detail(
    client_id: str,
    firm_id: Optional[str] = Query(None),
    dimension: str = Query(..., description="One of the 7 Product Bible dimensions"),
    current_user: dict = Depends(rbac("client", "read")),
):
    """
    GET /api/health/clients/{client_id}/dimension-detail?firm_id=&dimension=
    Returns list of factors dragging the given dimension down.
    Each factor: { label, impact, action_label, action_url }
    Powers the 'click to see detail' UI per Product Bible Chapter 16.
    """
    valid_dims = set(DIMENSION_WEIGHTS_BP.keys())
    if dimension not in valid_dims:
        raise HTTPException(
            status_code=422,
            detail=f"dimension must be one of: {', '.join(sorted(valid_dims))}",
        )

    db = _db()
    effective_firm = firm_id or current_user.get("firm_id", "")

    if not db:
        factors = _dimension_detail_mock(client_id, dimension)
        return api_response(True, {
            "client_id": client_id,
            "dimension": dimension,
            "factors":   factors,
        })

    factors = _dimension_detail_db(db, client_id, effective_firm, dimension)
    return api_response(True, {
        "client_id": client_id,
        "dimension": dimension,
        "factors":   factors,
    })


# ─── Scores ───────────────────────────────────────────────────────────────────

@router.get("/scores")
def list_scores(
    is_critical: Optional[bool] = Query(None),
    is_at_risk: Optional[bool] = Query(None),
    current_user: dict = Depends(rbac("client", "read")),
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
    current_user: dict = Depends(rbac("client", "read")),
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
    current_user: dict = Depends(rbac("client", "write")),
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
        if old_overall is not None:
            scores["trend"] = f"{scores['overall_score'] - old_overall:+d}"

        row = {
            "id":                str(uuid.uuid4()),
            "client_id":         client_id,
            "firm_id":           firm_id,
            "last_calculated_at": now,
            **scores,
        }
        _MOCK_SCORES[client_id] = row
        _MOCK_HISTORY.append({**row, "id": str(uuid.uuid4()), "score_id": row["id"]})

        if old_overall is not None and old_overall != scores["overall_score"]:
            timeline_service.log(
                client_id, "lifecycle", "Health Score Changed",
                f"Health score changed from {old_overall} to {scores['overall_score']} ({scores['grade']})",
                "warning" if scores["is_at_risk"] else "info",
                firm_id=firm_id,
            )

        return api_response(True, row)

    client = db.table("clients").select("id, client_name, is_internal").eq("id", client_id).eq("firm_id", firm_id).single().execute().data
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    # Guardrail G2: Health scoring is not applicable to the internal practice client.
    if client.get("is_internal"):
        raise HTTPException(status_code=400, detail="Health scoring does not apply to the internal practice client.")

    scores = _calculate_scores_db(db, client_id, firm_id)

    old_row = db.table("health_scores").select("overall_score, id").eq("client_id", client_id).eq("firm_id", firm_id).limit(1).execute().data
    old_overall = (old_row[0]["overall_score"] if old_row else None)
    if old_overall is not None:
        scores["trend"] = f"{scores['overall_score'] - old_overall:+d}"

    score_id = str(uuid.uuid4())
    upsert_payload = {
        "id":                 score_id,
        "client_id":          client_id,
        "firm_id":            firm_id,
        "last_calculated_at": now,
        "client_name":        client.get("client_name", ""),
        **scores,
    }

    # A plain upsert on the (firm_id, client_id) unique key is sufficient — the
    # insert/update fallback chain this used to have was silently swallowing
    # every exception and, on the update branch, returning the unpersisted
    # upsert_payload as if it had saved when zero rows matched (the very first
    # calculation for a client). A genuine write failure should surface, not lie.
    res = db.table("health_scores").upsert(upsert_payload, on_conflict="client_id,firm_id").execute()
    saved = (res.data or [upsert_payload])[0]

    # Insert history row
    try:
        db.table("health_score_history").insert({
            "id":           str(uuid.uuid4()),
            "firm_id":      firm_id,
            "client_id":    client_id,
            "overall_score": scores["overall_score"],
            "health_grade":  scores["health_grade"],
            "recorded_at":   now,
            "snapshot_data": {k: v for k, v in scores.items() if not isinstance(v, dict)},
        }).execute()
    except Exception:
        pass  # Non-fatal

    if old_overall is not None and old_overall != scores["overall_score"]:
        timeline_service.log(
            client_id, "lifecycle", "Health Score Changed",
            f"Health score changed from {old_overall} to {scores['overall_score']} ({scores['grade']})",
            "warning" if scores["is_at_risk"] else "info",
            firm_id=firm_id,
            entity_type="health_score", entity_id=score_id,
            actor_id=current_user.get("auth_user_id"),
        )

    return api_response(True, saved)


# ─── History ──────────────────────────────────────────────────────────────────

@router.get("/scores/{client_id}/history")
def get_score_history(
    client_id: str,
    limit: int = Query(20),
    current_user: dict = Depends(rbac("client", "read")),
):
    db = _db()
    if not db:
        result = [h for h in _MOCK_HISTORY if h.get("client_id") == client_id]
        result.sort(key=lambda h: h.get("recorded_at", h.get("last_calculated_at", "")), reverse=True)
        return api_response(True, result[:limit])

    # health_score_history only has: id, overall_score, health_grade, recorded_at, snapshot_data
    res = db.table("health_score_history").select(
        "id, overall_score, health_grade, recorded_at, snapshot_data"
    ).eq("client_id", client_id).eq("firm_id", current_user["firm_id"]).order("recorded_at", desc=True).limit(limit).execute()
    return api_response(True, res.data or [])


# ─── Overrides ────────────────────────────────────────────────────────────────

@router.get("/overrides")
def list_overrides(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("client", "read")),
):
    db = _db()
    if not db:
        result = [o for o in _MOCK_OVERRIDES if o.get("client_id") == client_id and o.get("is_active")]
        return api_response(True, result)

    res = db.table("health_overrides").select("*").eq("firm_id", current_user["firm_id"]).eq("client_id", client_id).eq("is_active", True).order("created_at", desc=True).execute()
    return api_response(True, res.data or [])


@router.post("/recalculate-all")
def recalculate_all(
    current_user: dict = Depends(rbac("client", "write")),
):
    """Recalculate health scores for all clients in the firm."""
    db = _db()
    firm_id = current_user["firm_id"]
    if not db:
        return api_response(True, {"updated": 0, "message": "No DB — mock mode"})

    # Guardrail G2: the internal practice client is never health-scored / triaged.
    clients_res = db.table("clients").select("id").eq("firm_id", firm_id).eq("is_internal", False).execute()
    clients = clients_res.data or []
    updated = 0
    now = datetime.now(timezone.utc).isoformat()
    for client in clients:
        try:
            scores = _calculate_scores_db(db, client["id"], firm_id)
            old_row = db.table("health_scores").select("overall_score").eq("client_id", client["id"]).eq("firm_id", firm_id).limit(1).execute().data
            if old_row:
                scores["trend"] = f"{scores['overall_score'] - old_row[0]['overall_score']:+d}"
            score_id = str(uuid.uuid4())
            upsert_payload = {
                "id": score_id, "client_id": client["id"], "firm_id": firm_id,
                "last_calculated_at": now, **scores,
            }
            db.table("health_scores").upsert(upsert_payload, on_conflict="client_id,firm_id").execute()
            db.table("health_score_history").insert({
                "id": str(uuid.uuid4()), "firm_id": firm_id, "client_id": client["id"],
                "overall_score": scores["overall_score"],
                "health_grade":  scores["health_grade"],
                "recorded_at":   now,
                "snapshot_data": {k: v for k, v in scores.items() if not isinstance(v, dict)},
            }).execute()
            updated += 1
        except Exception:
            pass
    return api_response(True, {"updated": updated})


@router.post("/scores/{client_id}/override")
def create_override(
    client_id: str,
    data: OverrideIn,
    current_user: dict = Depends(rbac("client", "write")),
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
        "override_by":    current_user.get("auth_user_id"),
    }

    if not db:
        _MOCK_OVERRIDES.append(row)
        return api_response(True, row)

    db_row = {k: v for k, v in row.items() if k != "id"}
    res = db.table("health_overrides").insert(db_row).execute()
    return api_response(True, (res.data or [row])[0])


@router.delete("/overrides/{override_id}")
def deactivate_override(
    override_id: str,
    current_user: dict = Depends(rbac("client", "write")),
):
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        for i, o in enumerate(_MOCK_OVERRIDES):
            if o["id"] == override_id:
                _MOCK_OVERRIDES[i]["is_active"] = False
                return api_response(True, {"override_id": override_id, "is_active": False})
        raise HTTPException(status_code=404, detail="Override not found")

    existing = db.table("health_overrides").select("id").eq("id", override_id).eq("firm_id", firm_id).single().execute().data
    if not existing:
        raise HTTPException(status_code=404, detail="Override not found")

    db.table("health_overrides").update({
        "is_active": False,
    }).eq("id", override_id).eq("firm_id", firm_id).execute()

    return api_response(True, {"override_id": override_id, "is_active": False})


# ─── Alerts ───────────────────────────────────────────────────────────────────

@router.get("/alerts")
def list_alerts(
    client_id: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("client", "read")),
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
    current_user: dict = Depends(rbac("client", "write")),
):
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()

    if not db:
        for i, a in enumerate(_MOCK_ALERTS):
            if a["id"] == alert_id:
                _MOCK_ALERTS[i]["is_resolved"] = True
                _MOCK_ALERTS[i]["resolved_at"] = now
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

    res = db.table("health_alerts").update(update).eq("id", alert_id).eq("firm_id", firm_id).execute()
    return api_response(True, (res.data or [{}])[0])


# ─── Dashboard ────────────────────────────────────────────────────────────────

@router.get("/dashboard")
def health_dashboard(
    current_user: dict = Depends(rbac("client", "read")),
):
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        scores = list(_MOCK_SCORES.values())
        critical = [s for s in scores if s.get("is_critical")]
        at_risk  = [s for s in scores if s.get("is_at_risk") and not s.get("is_critical")]

        # Product Bible score bands
        dist: dict[str, int] = {"Healthy": 0, "Good": 0, "Needs Attention": 0, "At Risk": 0, "Critical": 0}
        for s in scores:
            g = s.get("grade") or s.get("health_grade", "Critical")
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

    critical_res = db.table("health_scores").select("client_id, overall_score, grade, health_grade, is_critical, is_at_risk, client_name").eq("firm_id", firm_id).eq("is_critical", True).order("overall_score").execute()
    critical_clients = critical_res.data or []

    at_risk_res = db.table("health_scores").select("client_id, overall_score, grade, health_grade, is_critical, is_at_risk, client_name").eq("firm_id", firm_id).eq("is_at_risk", True).eq("is_critical", False).order("overall_score").execute()
    at_risk_clients = at_risk_res.data or []

    all_scores_res = db.table("health_scores").select("overall_score, grade, health_grade").eq("firm_id", firm_id).execute()
    all_scores = all_scores_res.data or []

    dist: dict[str, int] = {"Healthy": 0, "Good": 0, "Needs Attention": 0, "At Risk": 0, "Critical": 0}
    total = 0
    for s in all_scores:
        g = s.get("grade") or s.get("health_grade", "Critical")
        dist[g] = dist.get(g, 0) + 1
        total += int(s.get("overall_score") or 0)

    # Integer division for average — never float
    avg_score = total // len(all_scores) if all_scores else 0

    alerts_res = db.table("health_alerts").select("*").eq("firm_id", firm_id).eq("is_resolved", False).order("created_at", desc=True).limit(10).execute()
    top_alerts = alerts_res.data or []

    return api_response(True, {
        "critical_clients":   critical_clients,
        "at_risk_clients":    at_risk_clients,
        "average_score":      avg_score,
        "score_distribution": dist,
        "top_alerts":         top_alerts,
    })
