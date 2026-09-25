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
from core.observability import capture_soft_failure
from core.authz import filter_by_client, assert_client_access, can_access_client, effective_client_ids
from services.timeline_service import timeline_service
from core.ist_clock import ist_today
from domain.health.scoring import DIMENSION_WEIGHTS_BP, DIMENSIONS, grade, weighted_score
from domain.health.overrides import apply_overrides, as_payload

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


# ─── Product Bible Chapter 16 — the weights, bands and composite ─────────────
# MOVED to domain/health/scoring.py on 25-09-2026 and RE-EXPORTED here, so
# every existing `from routers.health import DIMENSION_WEIGHTS_BP` still works.
# The move was forced by `domain/health/overrides.py`, which has to recompute
# the composite after a CA replaces a dimension's score: a domain module
# importing a router is the wrong direction and one refactor from a cycle —
# the reasoning `domain/fixed_assets/schedule_ii.py` records for Schedule II
# Part C. Nothing about the numbers changed; a test asserts the router's names
# ARE the domain module's objects rather than copies of them.
_grade = grade
_weighted_score = weighted_score


# The Product Bible scores this dimension on two tiers, "critical" and
# "warning". ai_insights.severity has five values, and `warning` is not one of
# them: CHECK (severity IN ('critical','high','medium','low','info')). The code
# filtered on the literal 'warning', which no row can ever hold, so the -10
# branch matched nothing even once the column bug below was fixed.
#
# `high` is the mapping: it is the only severity above `medium`, so in a
# two-tier reading it is what sits directly under critical. This is the single
# judgement call in this change — a wider reading (high AND medium) would score
# clients lower, and that is a product decision, not a bug fix.
_WARNING_SEVERITY = "high"

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
    today = ist_today()

    # 1. Government notice with response deadline missed. F5 fix: this read a
    # nonexistent "notices" table with invented column/status names — the real
    # table is government_notices (migration 052: status open/in_progress/
    # responded/closed, deadline column response_due_date).
    try:
        missed = db.table("government_notices").select("id").eq("firm_id", firm_id).eq("client_id", client_id).in_("status", ["open", "in_progress"]).lt("response_due_date", today.isoformat()).limit(1).execute().data or []
        if missed:
            return "notice_deadline_missed"
    except Exception as exc:
        capture_soft_failure(exc, operation="health.detect_hard_override_db.1", firm_id=firm_id, client_id=client_id)

    # 2. Advance tax missed 2+ consecutive instalments
    # Advance tax due dates per IT Act s.211: 15-Jun (15%), 15-Sep (45%), 15-Dec (75%), 15-Mar (100%)
    #
    # This read TWO columns that have never existed: `instalment_number` (the
    # real one is `installment_number` — the schema spells it the American way,
    # the code the British way) and `paid`, which is not a column at all. The
    # table records `paid_amount_paise` and `paid_date`, so whether an
    # instalment was missed has to be DERIVED, not read.
    #
    # PostgREST rejects an unknown column at parse time, so the whole select
    # errored on every call and the `except` below swallowed it. This override
    # has therefore never fired once, for any client, silently.
    try:
        rows = db.table("advance_tax_payments").select(
            "financial_year, installment_number, due_date, paid_amount_paise"
        ).eq("firm_id", firm_id).eq("client_id", client_id).execute().data or []

        # Missed = the statutory due date has passed and nothing was paid
        # against it. A part-paid instalment is a shortfall, not a miss — s.234C
        # charges interest on it, which is a different signal from "ignored".
        today_iso = today.isoformat()
        by_fy: dict[str, list[int]] = {}
        for r in rows:
            due = r.get("due_date") or ""
            if due and due < today_iso and not (r.get("paid_amount_paise") or 0):
                by_fy.setdefault(r.get("financial_year") or "", []).append(
                    int(r.get("installment_number") or 0))

        # Grouped by financial year on purpose: instalment numbers restart at 1
        # every year, so pooling them would read FY25-26 #1 and FY26-27 #2 as a
        # consecutive pair and flag a client who missed one instalment in each
        # of two different years.
        for nums in by_fy.values():
            ordered = sorted(set(nums))
            for i in range(len(ordered) - 1):
                if ordered[i + 1] == ordered[i] + 1:
                    return "advance_tax_2_consecutive"
    except Exception as exc:
        capture_soft_failure(exc, operation="health.detect_hard_override_db.2", firm_id=firm_id, client_id=client_id)

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
    except Exception as exc:
        capture_soft_failure(exc, operation="health.detect_hard_override_db.3", firm_id=firm_id, client_id=client_id)

    # 4. Income tax return overdue > 6 months (IT Act s.139). R3.13d: reads
    # compliance_records (System A) — compliance_tasks (System B, the table
    # this used to query) is being retired, and this query referenced a
    # task_type column and a "Pending" status value that never existed on it.
    try:
        six_months_ago = (today - timedelta(days=183)).isoformat()
        itr = (db.table("compliance_records").select("id")
               .eq("firm_id", firm_id).eq("client_id", client_id)
               .eq("obligation_type", "ITR")
               .not_.in_("status", ["Filed", "Completed"])
               .lt("due_date", six_months_ago).limit(1).execute().data or [])
        if itr:
            return "itr_overdue_6months"
    except Exception as exc:
        capture_soft_failure(exc, operation="health.detect_hard_override_db.4", firm_id=firm_id, client_id=client_id)

    # 5. Bank reconciliation not done > 6 months
    try:
        six_months_ago = (today - timedelta(days=183)).isoformat()
        unreconciled = db.table("bank_transactions").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("reconciled", False).lt("transaction_date", six_months_ago).limit(1).execute().data or []
        if unreconciled:
            return "bank_recon_6months"
    except Exception as exc:
        capture_soft_failure(exc, operation="health.detect_hard_override_db.5", firm_id=firm_id, client_id=client_id)

    # 6. Open critical AI insight unacknowledged > 14 days
    try:
        fourteen_days_ago = (today - timedelta(days=14)).isoformat()
        critical_insight = db.table("ai_insights").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("severity", "critical").eq("status", "open").lt("created_at", fourteen_days_ago).limit(1).execute().data or []
        if critical_insight:
            return "critical_ai_insight_14d"
    except Exception as exc:
        capture_soft_failure(exc, operation="health.detect_hard_override_db.6", firm_id=firm_id, client_id=client_id)

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

    # R3.13d: reads compliance_records (System A) — compliance_tasks (System
    # B) is being retired, and these queries referenced a "Pending" status
    # value and a filed_late column that never existed on it.
    try:
        overdue_returns = (db.table("compliance_records").select("id")
                           .eq("firm_id", firm_id).eq("client_id", client_id)
                           .not_.in_("status", ["Filed", "Completed"])
                           .lt("due_date", ist_today().isoformat()).execute().data or [])
        score -= len(overdue_returns) * 25
    except Exception as exc:
        capture_soft_failure(exc, operation="health.dim_compliance_health_db.1", firm_id=firm_id, client_id=client_id)

    try:
        filed = (db.table("compliance_records").select("due_date, filed_date")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .in_("status", ["Filed", "Completed"]).execute().data or [])
        late_filings = [
            r for r in filed
            if r.get("filed_date") and r.get("due_date") and r["filed_date"] > r["due_date"]
        ]
        score -= len(late_filings) * 8
    except Exception as exc:
        capture_soft_failure(exc, operation="health.dim_compliance_health_db.2", firm_id=firm_id, client_id=client_id)

    try:
        pending_notices = db.table("government_notices").select("id").eq("firm_id", firm_id).eq("client_id", client_id).in_("status", ["open", "in_progress"]).execute().data or []
        score -= len(pending_notices) * 20
    except Exception as exc:
        capture_soft_failure(exc, operation="health.dim_compliance_health_db.3", firm_id=firm_id, client_id=client_id)

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
    today = ist_today()

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
    except Exception as exc:
        capture_soft_failure(exc, operation="health.dim_accounting_quality_db", firm_id=firm_id, client_id=client_id)

    return max(0, score)


def _dim_work_progress_db(db, client_id: str, firm_id: str) -> int:
    """
    work_progress (15%) — Product Bible Chapter 16.
    Start 100, -15 per overdue work item, -10 per at-risk item (within 3 days of due).
    """
    score = 100
    today = ist_today()
    at_risk_cutoff = (today + timedelta(days=3)).isoformat()

    # F5 fix: "work_items" never existed — work lives in tasks (migration 002;
    # status vocabulary is lowercase: todo/in_progress/waiting_client/…).
    try:
        overdue = db.table("tasks").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "in_progress").lt("due_date", today.isoformat()).execute().data or []
        score -= len(overdue) * 15
    except Exception as exc:
        capture_soft_failure(exc, operation="health.dim_work_progress_db.1", firm_id=firm_id, client_id=client_id)

    try:
        at_risk = db.table("tasks").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "in_progress").gte("due_date", today.isoformat()).lte("due_date", at_risk_cutoff).execute().data or []
        score -= len(at_risk) * 10
    except Exception as exc:
        capture_soft_failure(exc, operation="health.dim_work_progress_db.2", firm_id=firm_id, client_id=client_id)

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
    except Exception as exc:
        capture_soft_failure(exc, operation="health.dim_document_health_db", firm_id=firm_id, client_id=client_id)

    return max(0, score)


def _dim_ai_risk_signals_db(db, client_id: str, firm_id: str) -> int:
    """
    ai_risk_signals (10%) — Product Bible Chapter 16.
    Start 100, -20 per open critical insight, -10 per open warning.
    """
    score = 100

    try:
        critical = db.table("ai_insights").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("severity", "critical").eq("status", "open").execute().data or []
        score -= len(critical) * 20
    except Exception as exc:
        capture_soft_failure(exc, operation="health.dim_ai_risk_signals_db.1", firm_id=firm_id, client_id=client_id)

    try:
        warnings = db.table("ai_insights").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("severity", _WARNING_SEVERITY).eq("status", "open").execute().data or []
        score -= len(warnings) * 10
    except Exception as exc:
        capture_soft_failure(exc, operation="health.dim_ai_risk_signals_db.2", firm_id=firm_id, client_id=client_id)

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
    today = ist_today()

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
    except Exception as exc:
        capture_soft_failure(exc, operation="health.dim_open_notices_db", firm_id=firm_id, client_id=client_id)

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
    today = ist_today()

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
    except Exception as exc:
        capture_soft_failure(exc, operation="health.dim_client_responsiveness_db.1", firm_id=firm_id, client_id=client_id)

    try:
        stale_cutoff = (today - timedelta(days=7)).isoformat()
        stale_requests = db.table("document_requests").select("id").eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "Pending").lt("created_at", stale_cutoff).execute().data or []
        score -= len(stale_requests) * 10
    except Exception as exc:
        capture_soft_failure(exc, operation="health.dim_client_responsiveness_db.2", firm_id=firm_id, client_id=client_id)

    return max(0, score)


# ─── Manual overrides: fetch, and what must never reach a write ──────────────

#: Keys `_calculate_scores_*` returns that are NOT columns of `health_scores`.
#: `dimensions` IS one (jsonb); these two are not, and the returned dict is
#: spread into an upsert at two call sites — so sending them raises PGRST204
#: against a real database and passes in mock mode, which is exactly the shape
#: migration 291 had to repair on `form_26as_reconciliations`.
_NOT_COLUMNS = ("overridden_dimensions", "ignored_overrides")


def _columns_only(scores: dict) -> dict:
    """The half of a computed score that `health_scores` can store."""
    return {k: v for k, v in scores.items() if k not in _NOT_COLUMNS}


def _overrides_mock(client_id: str) -> list[dict]:
    return [o for o in _MOCK_OVERRIDES
            if o.get("client_id") == client_id and o.get("is_active")]


def _overrides_db(db, client_id: str, firm_id: str) -> list[dict]:
    """The client's live overrides. Bounded by construction — a handful of rows
    per client — beside the seven dimension queries this calculation already
    makes, so it adds one round trip and no scan.

    Only `is_active` rows: a withdrawn override is history and the CA already
    saw it go. Expiry is NOT filtered here and is deliberately the domain
    module's job, because `expires_at` is a timestamptz and the question is
    which INDIAN day it is — a `lte` against a UTC now is wrong for five and a
    half hours of every day.
    """
    try:
        res = (db.table("health_overrides")
               .select("id, dimension, override_score, reason, expires_at, "
                       "is_active, override_at, created_at")
               .eq("firm_id", firm_id).eq("client_id", client_id)
               .eq("is_active", True).execute())
        return res.data or []
    except Exception as exc:
        capture_soft_failure(exc, operation="health.overrides_db",
                             firm_id=firm_id, client_id=client_id)
        return []


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

    # The CA's own corrections replace their dimensions FIRST, and the hard
    # override is applied AFTER — so a manual override can raise a score and
    # still not mask a Chapter 16 Critical condition, which the create_override
    # handler's own comment names as the thing to prevent.
    _applied = apply_overrides(dim_scores, _overrides_mock(client_id),
                               as_at=ist_today())
    dim_scores = _applied.scores
    overall_score = _applied.overall_score
    band = _grade(overall_score)
    hard_override = _detect_hard_override_mock(client_id)
    if hard_override:
        band = "Critical"
        overall_score = min(overall_score, 34)

    return {
        **as_payload(_applied),
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
        "grade":          band,
        "health_grade":   band,      # legacy alias
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

    # See the mock twin above: overrides first, hard override last.
    _applied = apply_overrides(dim_scores, _overrides_db(db, client_id, firm_id),
                               as_at=ist_today())
    dim_scores = _applied.scores
    overall_score = _applied.overall_score
    hard_override = _detect_hard_override_db(db, client_id, firm_id)
    band = _grade(overall_score)
    if hard_override:
        band = "Critical"
        overall_score = min(overall_score, 34)

    return {
        **as_payload(_applied),
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
        "grade":          band,
        "health_grade":   band,
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
    today = ist_today()
    factors: list[dict] = []

    if dimension == "compliance_health":
        # R3.13d: reads compliance_records (System A) — see _dim_compliance_health_db.
        try:
            overdue = (db.table("compliance_records").select("id, period_label, compliance_type, due_date")
                      .eq("firm_id", firm_id).eq("client_id", client_id)
                      .not_.in_("status", ["Filed", "Completed"])
                      .lt("due_date", today.isoformat()).execute().data or [])
            for t in overdue[:5]:
                label = t.get("period_label") or t.get("compliance_type") or "Return"
                factors.append({
                    "label": f"{label} overdue since {t.get('due_date', '')}",
                    "impact": -25,
                    "action_label": "File Now",
                    "action_url": f"/clients/{client_id}/compliance",
                })
        except Exception as exc:
            capture_soft_failure(exc, operation="health.dimension_detail_db.1", firm_id=firm_id, client_id=client_id)

        try:
            notices = db.table("government_notices").select("id, notice_type, issue_date").eq("firm_id", firm_id).eq("client_id", client_id).in_("status", ["open", "in_progress"]).execute().data or []
            for n in notices[:5]:
                factors.append({
                    "label": f"Pending notice: {n.get('notice_type', 'Government Notice')}",
                    "impact": -20,
                    "action_label": "Respond",
                    "action_url": f"/clients/{client_id}/notices",
                })
        except Exception as exc:
            capture_soft_failure(exc, operation="health.dimension_detail_db.2", firm_id=firm_id, client_id=client_id)

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
        except Exception as exc:
            capture_soft_failure(exc, operation="health.dimension_detail_db.3", firm_id=firm_id, client_id=client_id)

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
        except Exception as exc:
            capture_soft_failure(exc, operation="health.dimension_detail_db.4", firm_id=firm_id, client_id=client_id)

    elif dimension == "document_health":
        try:
            # Two bugs on one line. `document_name` is not a column — the real
            # one is `title` — and the status filter was "Pending" while the
            # CHECK constraint only permits lowercase ('pending','fulfilled'),
            # so even with the column fixed this matched nothing.
            outstanding = db.table("document_requests").select("id, title, created_at").eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "pending").execute().data or []
            for d in outstanding[:5]:
                factors.append({
                    "label": f"Outstanding request: {d.get('title', 'Document')}",
                    "impact": -15,
                    "action_label": "Send Reminder",
                    "action_url": f"/clients/{client_id}/documents",
                })
        except Exception as exc:
            capture_soft_failure(exc, operation="health.dimension_detail_db.5", firm_id=firm_id, client_id=client_id)

    elif dimension == "ai_risk_signals":
        try:
            critical = db.table("ai_insights").select("id, title, created_at").eq("firm_id", firm_id).eq("client_id", client_id).eq("severity", "critical").eq("status", "open").execute().data or []
            for i in critical[:5]:
                factors.append({
                    "label": i.get("title", "Critical AI insight"),
                    "impact": -20,
                    "action_label": "Acknowledge",
                    "action_url": f"/clients/{client_id}/insights",
                })
        except Exception as exc:
            capture_soft_failure(exc, operation="health.dimension_detail_db.6", firm_id=firm_id, client_id=client_id)

        try:
            warnings = db.table("ai_insights").select("id, title").eq("firm_id", firm_id).eq("client_id", client_id).eq("severity", _WARNING_SEVERITY).eq("status", "open").execute().data or []
            for i in warnings[:5]:
                factors.append({
                    "label": i.get("title", "AI warning"),
                    "impact": -10,
                    "action_label": "Review",
                    "action_url": f"/clients/{client_id}/insights",
                })
        except Exception as exc:
            capture_soft_failure(exc, operation="health.dimension_detail_db.7", firm_id=firm_id, client_id=client_id)

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
        except Exception as exc:
            capture_soft_failure(exc, operation="health.dimension_detail_db.8", firm_id=firm_id, client_id=client_id)

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
        except Exception as exc:
            capture_soft_failure(exc, operation="health.dimension_detail_db.9", firm_id=firm_id, client_id=client_id)

        try:
            stale_cutoff = (today - timedelta(days=7)).isoformat()
            # The same two bugs the outstanding-requests query above carried,
            # a second time: `document_name` is not a column (it is `title`)
            # and the CHECK permits only lowercase 'pending'/'fulfilled', so
            # "Pending" matched nothing even once the name was right. Fixed
            # there and missed here because a one-off sweep found one and
            # stopped — which is why the check now runs in CI.
            stale = db.table("document_requests").select("id, title").eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "pending").lt("created_at", stale_cutoff).execute().data or []
            for d in stale[:5]:
                factors.append({
                    "label": f"Document pending > 7 days: {d.get('title', 'Document')}",
                    "impact": -10,
                    "action_label": "Follow Up",
                    "action_url": f"/clients/{client_id}/documents",
                })
        except Exception as exc:
            capture_soft_failure(exc, operation="health.dimension_detail_db.10", firm_id=firm_id, client_id=client_id)

    return factors


# ─── Client health endpoints (Product Bible Chapter 16 API shape) ─────────────

@router.get("/clients/{client_id}")
def get_client_health(
    client_id: str,
    current_user: dict = Depends(rbac("client", "read")),
):
    """
    GET /api/health/clients/{client_id}
    Returns Product Bible Chapter 16 health shape with 7 dimensions and hard override.
    """
    assert_client_access(current_user, client_id)
    db = _db()
    # firm scope always comes from the authenticated caller — never a query
    # param (a caller-supplied firm_id here would let any authenticated user
    # read another firm's client health data; the scope must never be
    # client-controllable).
    effective_firm = current_user.get("firm_id", "")

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
    dimension: str = Query(..., description="One of the 7 Product Bible dimensions"),
    current_user: dict = Depends(rbac("client", "read")),
):
    """
    GET /api/health/clients/{client_id}/dimension-detail?dimension=
    Returns list of factors dragging the given dimension down.
    Each factor: { label, impact, action_label, action_url }
    Powers the 'click to see detail' UI per Product Bible Chapter 16.
    """
    assert_client_access(current_user, client_id)
    valid_dims = set(DIMENSION_WEIGHTS_BP.keys())
    if dimension not in valid_dims:
        raise HTTPException(
            status_code=422,
            detail=f"dimension must be one of: {', '.join(sorted(valid_dims))}",
        )

    db = _db()
    # firm scope always comes from the authenticated caller — see get_client_health.
    effective_firm = current_user.get("firm_id", "")

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
        return api_response(True, filter_by_client(current_user, result))

    q = db.table("health_scores").select("*").eq("firm_id", current_user["firm_id"])
    if is_critical is not None:
        q = q.eq("is_critical", is_critical)
    if is_at_risk is not None:
        q = q.eq("is_at_risk", is_at_risk)
    res = q.order("overall_score").execute()  # worst first (ascending)
    return api_response(True, filter_by_client(current_user, res.data or []))


@router.get("/scores/{client_id}")
def get_score(
    client_id: str,
    current_user: dict = Depends(rbac("client", "read")),
):
    assert_client_access(current_user, client_id)
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
    # M2 audit finding: row-addressed by client_id with no guard at all — any
    # member of the firm could trigger a real write (health_scores upsert +
    # health_score_history insert + a timeline event) for a client they
    # aren't assigned to.
    assert_client_access(current_user, client_id)
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
            # Stripped here too although the mock store would take anything:
            # a mock row whose SHAPE differs from the production one is how a
            # slice comes to pass under test and fail against a database.
            **_columns_only(scores),
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
        # `_columns_only` — the computed score now carries the override
        # working, which `health_scores` has no column for. See _NOT_COLUMNS.
        **_columns_only(scores),
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
            "snapshot_data": {k: v for k, v in _columns_only(scores).items()
                              if not isinstance(v, dict)},
        }).execute()
    except Exception as exc:
        capture_soft_failure(exc, operation="health.calculate_score", client_id=client_id)

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
    assert_client_access(current_user, client_id)
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

def _assert_override_scope(current_user: dict, override_id: str) -> dict:
    """Resolve a health_overrides row and 404 unless it belongs to the
    caller's firm and the caller may access its client.
    health_overrides.client_id is NOT NULL (migration 059)."""
    db = _db()
    firm_id = current_user["firm_id"]
    if not db:
        row = next((o for o in _MOCK_OVERRIDES if o["id"] == override_id), None)
    else:
        rows = db.table("health_overrides").select("*").eq("id", override_id).limit(1).execute().data
        row = rows[0] if rows else None
    if (not row or row.get("firm_id") != firm_id
            or not can_access_client(current_user, row.get("client_id"))):
        raise HTTPException(status_code=404, detail="Override not found")
    return row


def _annotate_overrides(rows: list[dict], dimension_scores: dict[str, int]) -> list[dict]:
    """Say, per recorded override, whether it is in force and if not why.

    THE SCREEN MUST NOT WORK THIS OUT. Until 25-09-2026 both health screens
    read `health_overrides` straight over PostgREST and rendered every
    `is_active` row under "Active overrides" — so one that lapsed in March was
    still presented as in force in September, and one naming a dimension the
    model does not have looked identical to one that was replacing a score.
    Whether an override applies is the same rule the calculation uses, and
    there is one of it.
    """
    outcome = apply_overrides(dimension_scores, rows, as_at=ist_today())
    applied = {a.override_id: a for a in outcome.applied}
    ignored = {i.override_id: i for i in outcome.ignored}
    out: list[dict] = []
    for row in rows:
        oid = row.get("id")
        hit = applied.get(oid)
        miss = ignored.get(oid)
        out.append({
            **row,
            "in_force": hit is not None,
            # Always present, null where the override IS in force — an absent
            # key and a null key read the same to a screen and are different
            # bugs (`domain/accounting/journal_source`'s discipline).
            "not_in_force_because": None if hit else (miss.why if miss else None),
            "explanation": None if hit else (miss.explanation if miss else None),
            "computed_score": hit.computed_score if hit else None,
        })
    return out


@router.get("/overrides")
def list_overrides(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("client", "read")),
):
    """The client's recorded overrides, each saying whether it is in force.

    `is_active` still filters at the query, because a WITHDRAWN override is
    history and the CA already saw it go; what this adds is the lapsed, the
    unscored and the dimension this model does not have, all of which are
    `is_active` and none of which is replacing anything.
    """
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        rows = [o for o in _MOCK_OVERRIDES
                if o.get("client_id") == client_id and o.get("is_active")]
        scored = _MOCK_SCORES.get(client_id) or {}
        dims = {k: int(scored.get(f"{k}_score", 100) or 100) for k in DIMENSIONS}
        return api_response(True, _annotate_overrides(rows, dims))

    firm_id = current_user["firm_id"]
    res = (db.table("health_overrides").select("*")
           .eq("firm_id", firm_id).eq("client_id", client_id)
           .eq("is_active", True).order("created_at", desc=True).execute())
    rows = res.data or []

    # The stored dimension scores, so the screen can show "48 → 90" rather than
    # a bare override figure. One keyed read; absent (no score calculated yet)
    # falls back to the same 100 `weighted_score` uses for a missing dimension.
    dims = {k: 100 for k in DIMENSIONS}
    try:
        # Written out rather than joined from DIMENSIONS, although the join
        # would be shorter: `tests/test_backend_columns_exist_pg.py` reads
        # every `.select()` as a STRING, so a projection reached through a
        # name is invisible to it — the trap `domain/firm/identity` records,
        # and its budget for unreadable projections is exact with no headroom.
        scored = (db.table("health_scores")
                  .select("compliance_health_score, accounting_quality_score, "
                          "work_progress_score, document_health_score, "
                          "ai_risk_signals_score, open_notices_score, "
                          "client_responsiveness_score")
                  .eq("firm_id", firm_id).eq("client_id", client_id)
                  .limit(1).execute().data or [])
        if scored:
            dims = {k: int(scored[0].get(f"{k}_score") or 100) for k in DIMENSIONS}
    except Exception as exc:
        capture_soft_failure(exc, operation="health.list_overrides.scores",
                             firm_id=firm_id, client_id=client_id)

    return api_response(True, _annotate_overrides(rows, dims))


@router.post("/recalculate-all")
def recalculate_all(
    current_user: dict = Depends(rbac("client", "write")),
):
    """Recalculate health scores for all clients in the firm — or, for an
    assignment-scoped caller (rbac("client","write") admits Manager, who is
    assignment-scoped under M3, not just Partner), every client they are
    actually assigned to. M2 audit finding: this write previously touched
    every client in the firm regardless of the caller's own assignment."""
    db = _db()
    firm_id = current_user["firm_id"]
    if not db:
        return api_response(True, {"updated": 0, "message": "No DB — mock mode"})

    # Guardrail G2: the internal practice client is never health-scored / triaged.
    clients_res = db.table("clients").select("id").eq("firm_id", firm_id).eq("is_internal", False).execute()
    clients = clients_res.data or []
    eff = effective_client_ids(current_user)
    if eff is not None:
        clients = [c for c in clients if str(c["id"]) in eff]
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
                "last_calculated_at": now, **_columns_only(scores),
            }
            db.table("health_scores").upsert(upsert_payload, on_conflict="client_id,firm_id").execute()
            db.table("health_score_history").insert({
                "id": str(uuid.uuid4()), "firm_id": firm_id, "client_id": client["id"],
                "overall_score": scores["overall_score"],
                "health_grade":  scores["health_grade"],
                "recorded_at":   now,
                "snapshot_data": {k: v for k, v in _columns_only(scores).items()
                                  if not isinstance(v, dict)},
            }).execute()
            updated += 1
        except Exception as exc:
            capture_soft_failure(exc, operation="health.recalculate_all")
    return api_response(True, {"updated": updated})


@router.post("/scores/{client_id}/override")
def create_override(
    client_id: str,
    data: OverrideIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    # M2 audit finding: row-addressed by client_id with no guard at all — an
    # override can force a client's grade to anything (including masking a
    # real Critical status), and nothing checked the caller was assigned to
    # this client.
    assert_client_access(current_user, client_id)
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
    # M2 audit finding: row-addressed by override_id, firm-scoped only in
    # live mode and not even that in mock mode — health_overrides.client_id
    # was never checked before deactivating.
    _assert_override_scope(current_user, override_id)
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        for i, o in enumerate(_MOCK_OVERRIDES):
            if o["id"] == override_id:
                _MOCK_OVERRIDES[i]["is_active"] = False
                return api_response(True, {"override_id": override_id, "is_active": False})
        raise HTTPException(status_code=404, detail="Override not found")

    db.table("health_overrides").update({
        "is_active": False,
    }).eq("id", override_id).eq("firm_id", firm_id).execute()

    return api_response(True, {"override_id": override_id, "is_active": False})


# ─── Alerts ───────────────────────────────────────────────────────────────────

def _assert_alert_scope(current_user: dict, alert_id: str) -> dict:
    """Resolve a health_alerts row and 404 unless it belongs to the caller's
    firm and the caller may access its client.
    health_alerts.client_id is NOT NULL (migration 059)."""
    db = _db()
    firm_id = current_user["firm_id"]
    if not db:
        row = next((a for a in _MOCK_ALERTS if a["id"] == alert_id), None)
    else:
        rows = db.table("health_alerts").select("*").eq("id", alert_id).limit(1).execute().data
        row = rows[0] if rows else None
    if (not row or row.get("firm_id") != firm_id
            or not can_access_client(current_user, row.get("client_id"))):
        raise HTTPException(status_code=404, detail="Alert not found")
    return row


@router.get("/alerts")
def list_alerts(
    client_id: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("client", "read")),
):
    if client_id:
        assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        result = [a for a in _MOCK_ALERTS if not a.get("is_resolved")]
        if client_id:
            result = [a for a in result if a.get("client_id") == client_id]
        if severity:
            result = [a for a in result if a.get("severity") == severity]
        return api_response(True, filter_by_client(current_user, result))

    q = db.table("health_alerts").select("*").eq("firm_id", current_user["firm_id"]).eq("is_resolved", False)
    if client_id:
        q = q.eq("client_id", client_id)
    if severity:
        q = q.eq("severity", severity)
    res = q.order("created_at", desc=True).execute()
    return api_response(True, filter_by_client(current_user, res.data or []))


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(
    alert_id: str,
    data: AlertResolveIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    # M2 audit finding: row-addressed by alert_id, firm-scoped only in live
    # mode and not even that in mock mode — health_alerts.client_id was
    # never checked before resolving.
    _assert_alert_scope(current_user, alert_id)
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
    # M2 audit finding: unlike list_scores/list_alerts (both already narrowed
    # via filter_by_client), this returned NAMED critical/at-risk client rows
    # and alerts for the WHOLE firm, unfiltered by assignment — a bigger leak
    # than a count, since client_name/client_id are in the response.
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        # Also a pre-existing firm-boundary gap in mock mode: _MOCK_SCORES is
        # one process-wide store with no firm filter applied here at all.
        scores = [s for s in _MOCK_SCORES.values() if s.get("firm_id") == firm_id]
        scores = filter_by_client(current_user, scores)
        critical = [s for s in scores if s.get("is_critical")]
        at_risk  = [s for s in scores if s.get("is_at_risk") and not s.get("is_critical")]

        # Product Bible score bands
        dist: dict[str, int] = {"Healthy": 0, "Good": 0, "Needs Attention": 0, "At Risk": 0, "Critical": 0}
        for s in scores:
            g = s.get("grade") or s.get("health_grade", "Critical")
            dist[g] = dist.get(g, 0) + 1

        total_score = sum(s.get("overall_score", 0) for s in scores)
        avg_score = total_score // len(scores) if scores else 0

        top_alerts = [a for a in _MOCK_ALERTS
                      if not a.get("is_resolved") and a.get("firm_id") == firm_id]
        top_alerts = filter_by_client(current_user, top_alerts)[:10]

        return api_response(True, {
            "critical_clients":   critical,
            "at_risk_clients":    at_risk,
            "average_score":      avg_score,
            "score_distribution": dist,
            "top_alerts":         top_alerts,
        })

    critical_res = db.table("health_scores").select("client_id, overall_score, grade, health_grade, is_critical, is_at_risk, client_name").eq("firm_id", firm_id).eq("is_critical", True).order("overall_score").execute()
    critical_clients = filter_by_client(current_user, critical_res.data or [])

    at_risk_res = db.table("health_scores").select("client_id, overall_score, grade, health_grade, is_critical, is_at_risk, client_name").eq("firm_id", firm_id).eq("is_at_risk", True).eq("is_critical", False).order("overall_score").execute()
    at_risk_clients = filter_by_client(current_user, at_risk_res.data or [])

    all_scores_res = db.table("health_scores").select("client_id, overall_score, grade, health_grade").eq("firm_id", firm_id).execute()
    all_scores = filter_by_client(current_user, all_scores_res.data or [])

    dist: dict[str, int] = {"Healthy": 0, "Good": 0, "Needs Attention": 0, "At Risk": 0, "Critical": 0}
    total = 0
    for s in all_scores:
        g = s.get("grade") or s.get("health_grade", "Critical")
        dist[g] = dist.get(g, 0) + 1
        total += int(s.get("overall_score") or 0)

    # Integer division for average — never float
    avg_score = total // len(all_scores) if all_scores else 0

    # Fetch more than the final 10 before filtering — otherwise an
    # assignment-scoped caller could see fewer than 10 alerts even when more
    # of their OWN clients' alerts exist further down the firm-wide order.
    alerts_res = db.table("health_alerts").select("*").eq("firm_id", firm_id).eq("is_resolved", False).order("created_at", desc=True).limit(50).execute()
    top_alerts = filter_by_client(current_user, alerts_res.data or [])[:10]

    return api_response(True, {
        "critical_clients":   critical_clients,
        "at_risk_clients":    at_risk_clients,
        "average_score":      avg_score,
        "score_distribution": dist,
        "top_alerts":         top_alerts,
    })
