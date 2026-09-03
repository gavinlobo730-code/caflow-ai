"""Repository for Phase 13 AI Memory & Compounding Intelligence.

Dual-path: uses Supabase when SUPABASE_URL is set, otherwise falls back to
in-memory mock data so the dev server still works without credentials.

Tables used:
    client_profiles, client_profile_history,
    firm_profiles,
    ai_memory_triggers,
    pattern_anomalies,
    year_end_reports
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
from typing import Optional

from repositories.base import BaseRepository

_USE_MOCK = not os.environ.get("SUPABASE_URL")


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


def _now() -> str:
    return datetime.utcnow().isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


def _days_ago(days: int) -> str:
    return (datetime.utcnow() - timedelta(days=days)).isoformat()


class MemoryRepository(BaseRepository):
    """AI Memory & Compounding Intelligence — five-table repository."""

    # ── Client Profiles ───────────────────────────────────────────────────────

    def get_current_profile(
        self, firm_id: str, client_id: str
    ) -> Optional[dict]:
        """Return the active profile for a client, or None."""
        if _USE_MOCK:
            return next(
                (
                    p for p in MOCK_CLIENT_PROFILES
                    if p["firm_id"] == firm_id
                    and p["client_id"] == client_id
                    and p["is_current"]
                ),
                None,
            )

        result = (
            _get_db()
            .table("client_profiles")
            .select("*")
            .eq("firm_id", firm_id)
            .eq("client_id", client_id)
            .eq("is_current", True)
            .order("profile_version", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def upsert_profile(
        self, firm_id: str, client_id: str, profile_data: dict
    ) -> dict:
        """Retire the current profile, insert the new one, and snapshot the old."""
        now = _now()

        if _USE_MOCK:
            # Find and retire any existing current profile
            old_version = 0
            old_profile_id = None
            for p in MOCK_CLIENT_PROFILES:
                if (
                    p["firm_id"] == firm_id
                    and p["client_id"] == client_id
                    and p["is_current"]
                ):
                    p["is_current"] = False
                    p["updated_at"] = now
                    old_version = p["profile_version"]
                    old_profile_id = p["id"]
                    # Save history snapshot
                    MOCK_CLIENT_PROFILE_HISTORY.append({
                        "id": _uid(),
                        "firm_id": firm_id,
                        "client_id": client_id,
                        "profile_id": old_profile_id,
                        "profile_version": old_version,
                        "snapshot": dict(p),
                        "computed_at": now,
                    })
                    break

            new_profile = {
                "id": _uid(),
                "firm_id": firm_id,
                "client_id": client_id,
                "profile_version": old_version + 1,
                "doc_upload_reliability": 0,
                "portal_engagement": 0,
                "avg_response_time_days": None,
                "preferred_contact": "email",
                "avg_gst_delay_days": None,
                "avg_tds_delay_days": None,
                "missed_deadline_count": 0,
                "notice_count": 0,
                "compliance_score": 75,
                "seasonal_revenue_peak": None,
                "cash_flow_risk_months": [],
                "avg_debtor_days": None,
                "recurring_issues": [],
                "avg_year_end_duration_days": None,
                "common_provisions": [],
                "common_auditor_requests": [],
                "last_computed_at": now,
                "data_points_used": 0,
                "is_current": True,
                "created_at": now,
                "updated_at": now,
                **profile_data,
            }
            MOCK_CLIENT_PROFILES.append(new_profile)
            return new_profile

        # --- Supabase path ---
        db = _get_db()

        # Determine next version
        existing = (
            db.table("client_profiles")
            .select("id, profile_version")
            .eq("firm_id", firm_id)
            .eq("client_id", client_id)
            .eq("is_current", True)
            .limit(1)
            .execute()
        )
        old_version = existing.data[0]["profile_version"] if existing.data else 0
        old_profile_id = existing.data[0]["id"] if existing.data else None

        # Retire old profile and snapshot it
        if old_profile_id:
            db.table("client_profiles").update(
                {"is_current": False, "updated_at": now}
            ).eq("id", old_profile_id).execute()

            snapshot_result = (
                db.table("client_profiles")
                .select("*")
                .eq("id", old_profile_id)
                .maybe_single()
                .execute()
            )
            if snapshot_result.data:
                db.table("client_profile_history").insert({
                    "id": _uid(),
                    "firm_id": firm_id,
                    "client_id": client_id,
                    "profile_id": old_profile_id,
                    "profile_version": old_version,
                    "snapshot": snapshot_result.data,
                    "computed_at": now,
                }).execute()

        # Written inline rather than as `.insert(record)`. Every one of these
        # names is a column, and tests/test_backend_columns_exist_pg.py reads
        # them as TEXT out of the call — a payload built in a variable hides all
        # eighteen from it. That blind spot is why nobody noticed that the
        # migrations' client_profiles had NINE columns while production had
        # twenty-nine, so this table's writes could not have run on any
        # database built from the repository (migration 320).
        result = db.table("client_profiles").insert({
            "id": _uid(),
            "firm_id": firm_id,
            "client_id": client_id,
            "profile_version": old_version + 1,
            "preferred_contact": "email",
            "missed_deadline_count": 0,
            "notice_count": 0,
            "compliance_score": 75,
            "cash_flow_risk_months": [],
            "recurring_issues": [],
            "common_provisions": [],
            "common_auditor_requests": [],
            "last_computed_at": now,
            "data_points_used": 0,
            "is_current": True,
            "created_at": now,
            "updated_at": now,
            **profile_data,
        }).execute()
        return result.data[0]

    def list_profiles(self, firm_id: str, limit: int = 50) -> list[dict]:
        """Return all current client profiles for a firm."""
        if _USE_MOCK:
            profiles = [
                p for p in MOCK_CLIENT_PROFILES
                if p["firm_id"] == firm_id and p["is_current"]
            ]
            profiles.sort(key=lambda p: p["compliance_score"])
            return profiles[:limit]

        result = (
            _get_db()
            .table("client_profiles")
            .select("*")
            .eq("firm_id", firm_id)
            .eq("is_current", True)
            .order("compliance_score")
            .limit(limit)
            .execute()
        )
        return result.data or []

    # ── Firm Profiles ─────────────────────────────────────────────────────────

    def get_firm_profile(self, firm_id: str) -> Optional[dict]:
        """Return the current firm-level intelligence profile."""
        if _USE_MOCK:
            return next(
                (p for p in MOCK_FIRM_PROFILES if p["firm_id"] == firm_id),
                None,
            )

        result = (
            _get_db()
            .table("firm_profiles")
            .select("*")
            .eq("firm_id", firm_id)
            .eq("is_current", True)
            .maybe_single()
            .execute()
        )
        return result.data

    def upsert_firm_profile(self, firm_id: str, profile_data: dict) -> dict:
        """Create or replace the firm profile."""
        now = _now()

        if _USE_MOCK:
            for i, p in enumerate(MOCK_FIRM_PROFILES):
                if p["firm_id"] == firm_id:
                    MOCK_FIRM_PROFILES[i] = {
                        **p,
                        **profile_data,
                        "last_computed_at": now,
                        "updated_at": now,
                    }
                    return MOCK_FIRM_PROFILES[i]
            new_profile = {
                "id": _uid(),
                "firm_id": firm_id,
                "peak_workload_months": [],
                "avg_tasks_per_client": None,
                "common_bottleneck_types": [],
                "team_utilisation_trend": "stable",
                "portfolio_compliance_score": 75,
                "common_risk_categories": [],
                "portfolio_health_trend": "stable",
                "avg_revenue_per_client_paise": 0,
                "revenue_growth_trend": "stable",
                "billing_recovery_rate": 85,
                "deadline_concentration": {},
                "capacity_risk_months": [],
                "last_computed_at": now,
                "is_current": True,
                "created_at": now,
                "updated_at": now,
                **profile_data,
            }
            MOCK_FIRM_PROFILES.append(new_profile)
            return new_profile

        # Supabase: retire existing and insert fresh (UNIQUE constraint on firm_id
        # means we UPDATE if exists, else INSERT)
        db = _get_db()
        existing = (
            db.table("firm_profiles")
            .select("id")
            .eq("firm_id", firm_id)
            .maybe_single()
            .execute()
        )
        if existing.data:
            result = (
                db.table("firm_profiles")
                .update({**profile_data, "last_computed_at": now, "updated_at": now})
                .eq("firm_id", firm_id)
                .execute()
            )
            return result.data[0]

        record = {
            "id": _uid(),
            "firm_id": firm_id,
            "peak_workload_months": [],
            "avg_tasks_per_client": None,
            "common_bottleneck_types": [],
            "team_utilisation_trend": "stable",
            "portfolio_compliance_score": 75,
            "common_risk_categories": [],
            "portfolio_health_trend": "stable",
            "avg_revenue_per_client_paise": 0,
            "revenue_growth_trend": "stable",
            "billing_recovery_rate": 85,
            "deadline_concentration": {},
            "capacity_risk_months": [],
            "last_computed_at": now,
            "is_current": True,
            "created_at": now,
            "updated_at": now,
            **profile_data,
        }
        result = db.table("firm_profiles").insert(record).execute()
        return result.data[0]

    # ── AI Memory Triggers ────────────────────────────────────────────────────

    def create_trigger(
        self,
        firm_id: str,
        client_id: Optional[str],
        trigger_type: str,
        title: str,
        what_detected: str,
        evidence: list,
        why_it_matters: str,
        recommended_action: str,
        confidence: float,
        severity: str,
        source_data: Optional[dict] = None,
        profile_version: Optional[int] = None,
    ) -> dict:
        now = _now()
        record = {
            "id": _uid(),
            "firm_id": firm_id,
            "client_id": client_id,
            "trigger_type": trigger_type,
            "title": title,
            "what_detected": what_detected,
            "evidence": evidence,
            "why_it_matters": why_it_matters,
            "recommended_action": recommended_action,
            "confidence": confidence,
            "severity": severity,
            "status": "active",
            "acknowledged_by": None,
            "acknowledged_at": None,
            "resolved_at": None,
            "source_data": source_data or {},
            "profile_version": profile_version,
            "created_at": now,
            "updated_at": now,
        }
        if _USE_MOCK:
            MOCK_TRIGGERS.append(record)
            return record

        result = _get_db().table("ai_memory_triggers").insert(record).execute()
        return result.data[0]

    def list_triggers(
        self,
        firm_id: str,
        client_id: Optional[str] = None,
        trigger_type: Optional[str] = None,
        status: str = "active",
        limit: int = 50,
    ) -> list[dict]:
        if _USE_MOCK:
            items = [t for t in MOCK_TRIGGERS if t["firm_id"] == firm_id]
            if client_id:
                items = [t for t in items if t.get("client_id") == client_id]
            if trigger_type:
                items = [t for t in items if t["trigger_type"] == trigger_type]
            if status:
                items = [t for t in items if t["status"] == status]
            severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            items.sort(
                key=lambda t: (severity_order.get(t["severity"], 9), t["created_at"])
            )
            return items[:limit]

        query = (
            _get_db()
            .table("ai_memory_triggers")
            .select("*")
            .eq("firm_id", firm_id)
        )
        if client_id:
            query = query.eq("client_id", client_id)
        if trigger_type:
            query = query.eq("trigger_type", trigger_type)
        if status:
            query = query.eq("status", status)
        result = query.order("created_at", desc=True).limit(limit).execute()
        return result.data or []

    def get_trigger(self, firm_id: str, trigger_id: str) -> Optional[dict]:
        """One trigger, firm-scoped. Exists so the router can resolve its client
        BEFORE acknowledge/dismiss writes."""
        if _USE_MOCK:
            return next((t for t in MOCK_TRIGGERS
                         if t["id"] == trigger_id and t["firm_id"] == firm_id), None)
        rows = (_get_db().table("ai_memory_triggers").select("*")
                .eq("id", trigger_id).eq("firm_id", firm_id)
                .limit(1).execute().data) or []
        return rows[0] if rows else None

    def get_anomaly(self, firm_id: str, anomaly_id: str) -> Optional[dict]:
        """One anomaly, firm-scoped. Same reason as get_trigger."""
        if _USE_MOCK:
            return next((a for a in MOCK_ANOMALIES
                         if a["id"] == anomaly_id and a["firm_id"] == firm_id), None)
        rows = (_get_db().table("pattern_anomalies").select("*")
                .eq("id", anomaly_id).eq("firm_id", firm_id)
                .limit(1).execute().data) or []
        return rows[0] if rows else None

    def acknowledge_trigger(
        self, firm_id: str, trigger_id: str, user_id: str
    ) -> Optional[dict]:
        now = _now()
        updates = {
            "status": "acknowledged",
            "acknowledged_by": user_id,
            "acknowledged_at": now,
            "updated_at": now,
        }
        if _USE_MOCK:
            for t in MOCK_TRIGGERS:
                if t["id"] == trigger_id and t["firm_id"] == firm_id:
                    t.update(updates)
                    return t
            return None

        result = (
            _get_db()
            .table("ai_memory_triggers")
            .update(updates)
            .eq("id", trigger_id)
            .eq("firm_id", firm_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def resolve_trigger(self, firm_id: str, trigger_id: str) -> Optional[dict]:
        now = _now()
        updates = {
            "status": "resolved",
            "resolved_at": now,
            "updated_at": now,
        }
        if _USE_MOCK:
            for t in MOCK_TRIGGERS:
                if t["id"] == trigger_id and t["firm_id"] == firm_id:
                    t.update(updates)
                    return t
            return None

        result = (
            _get_db()
            .table("ai_memory_triggers")
            .update(updates)
            .eq("id", trigger_id)
            .eq("firm_id", firm_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def dismiss_trigger(self, firm_id: str, trigger_id: str) -> Optional[dict]:
        now = _now()
        updates = {"status": "dismissed", "updated_at": now}
        if _USE_MOCK:
            for t in MOCK_TRIGGERS:
                if t["id"] == trigger_id and t["firm_id"] == firm_id:
                    t.update(updates)
                    return t
            return None

        result = (
            _get_db()
            .table("ai_memory_triggers")
            .update(updates)
            .eq("id", trigger_id)
            .eq("firm_id", firm_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def get_recent_triggers(
        self,
        firm_id: str,
        client_id: str,
        trigger_type: str,
        days: int = 90,
    ) -> list[dict]:
        """Return recent triggers for deduplication — avoids re-raising known issues."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        if _USE_MOCK:
            return [
                t for t in MOCK_TRIGGERS
                if t["firm_id"] == firm_id
                and t.get("client_id") == client_id
                and t["trigger_type"] == trigger_type
                and t["created_at"] >= cutoff
            ]

        result = (
            _get_db()
            .table("ai_memory_triggers")
            .select("*")
            .eq("firm_id", firm_id)
            .eq("client_id", client_id)
            .eq("trigger_type", trigger_type)
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []

    # ── Pattern Anomalies ─────────────────────────────────────────────────────

    def create_anomaly(
        self,
        firm_id: str,
        client_id: Optional[str],
        anomaly_type: str,
        metric_name: str,
        baseline: Optional[float],
        actual: Optional[float],
        period: str,
        explanation: Optional[str] = None,
        evidence: Optional[list] = None,
    ) -> dict:
        deviation_pct = None
        deviation_score = None
        if baseline is not None and actual is not None and baseline != 0:
            deviation_pct = round(((actual - baseline) / abs(baseline)) * 100, 2)

        now = _now()
        record = {
            "id": _uid(),
            "firm_id": firm_id,
            "client_id": client_id,
            "anomaly_type": anomaly_type,
            "metric_name": metric_name,
            "baseline_value": baseline,
            "actual_value": actual,
            "deviation_pct": deviation_pct,
            "deviation_score": deviation_score,
            "period": period,
            "explanation": explanation,
            "evidence": evidence or [],
            "status": "open",
            "created_at": now,
        }
        if _USE_MOCK:
            MOCK_ANOMALIES.append(record)
            return record

        result = _get_db().table("pattern_anomalies").insert(record).execute()
        return result.data[0]

    def list_anomalies(
        self,
        firm_id: str,
        client_id: Optional[str] = None,
        status: str = "open",
        limit: int = 50,
    ) -> list[dict]:
        if _USE_MOCK:
            items = [a for a in MOCK_ANOMALIES if a["firm_id"] == firm_id]
            if client_id:
                items = [a for a in items if a.get("client_id") == client_id]
            if status:
                items = [a for a in items if a["status"] == status]
            items.sort(key=lambda a: a["created_at"], reverse=True)
            return items[:limit]

        query = (
            _get_db()
            .table("pattern_anomalies")
            .select("*")
            .eq("firm_id", firm_id)
        )
        if client_id:
            query = query.eq("client_id", client_id)
        if status:
            query = query.eq("status", status)
        result = query.order("created_at", desc=True).limit(limit).execute()
        return result.data or []

    def update_anomaly_status(
        self, firm_id: str, anomaly_id: str, status: str
    ) -> Optional[dict]:
        if _USE_MOCK:
            for a in MOCK_ANOMALIES:
                if a["id"] == anomaly_id and a["firm_id"] == firm_id:
                    a["status"] = status
                    return a
            return None

        result = (
            _get_db()
            .table("pattern_anomalies")
            .update({"status": status})
            .eq("id", anomaly_id)
            .eq("firm_id", firm_id)
            .execute()
        )
        return result.data[0] if result.data else None

    # ── Year-End Reports ──────────────────────────────────────────────────────

    def create_year_end_report(
        self,
        firm_id: str,
        client_id: str,
        financial_year: str,
        data: dict,
    ) -> dict:
        now = _now()
        record = {
            "id": _uid(),
            "firm_id": firm_id,
            "client_id": client_id,
            "financial_year": financial_year,
            "prior_year_lessons": [],
            "recurring_provisions": [],
            "auditor_requests": [],
            "historical_bottlenecks": [],
            "planning_recommendations": [],
            "ai_narrative": None,
            "generated_at": now,
            "status": "draft",
            **data,
        }
        if _USE_MOCK:
            MOCK_YEAR_END_REPORTS.append(record)
            return record

        result = _get_db().table("year_end_reports").insert(record).execute()
        return result.data[0]

    def get_year_end_report(
        self, firm_id: str, client_id: str, financial_year: str
    ) -> Optional[dict]:
        if _USE_MOCK:
            return next(
                (
                    r for r in MOCK_YEAR_END_REPORTS
                    if r["firm_id"] == firm_id
                    and r["client_id"] == client_id
                    and r["financial_year"] == financial_year
                ),
                None,
            )

        result = (
            _get_db()
            .table("year_end_reports")
            .select("*")
            .eq("firm_id", firm_id)
            .eq("client_id", client_id)
            .eq("financial_year", financial_year)
            .order("generated_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def list_year_end_reports(self, firm_id: str, limit: int = 20) -> list[dict]:
        if _USE_MOCK:
            reports = [r for r in MOCK_YEAR_END_REPORTS if r["firm_id"] == firm_id]
            reports.sort(key=lambda r: r["generated_at"], reverse=True)
            return reports[:limit]

        result = (
            _get_db()
            .table("year_end_reports")
            .select("*")
            .eq("firm_id", firm_id)
            .order("generated_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []


memory_repo = MemoryRepository()


# ── Mock data ─────────────────────────────────────────────────────────────────

MOCK_CLIENT_PROFILES: list[dict] = [
    {
        "id": "cp-001",
        "firm_id": "firm-001",
        "client_id": "c-001",
        "profile_version": 3,
        # Behavioural
        "doc_upload_reliability": 82.5,
        "portal_engagement": 74.0,
        "avg_response_time_days": 1.5,
        "preferred_contact": "whatsapp",
        # Compliance
        "avg_gst_delay_days": 2.3,
        "avg_tds_delay_days": 0.0,
        "missed_deadline_count": 1,
        "notice_count": 0,
        "compliance_score": 88.0,
        # Financial
        "seasonal_revenue_peak": "Q4",
        "cash_flow_risk_months": ["January", "February"],
        "avg_debtor_days": 42.0,
        # Recurring issues
        "recurring_issues": ["late_purchase_register", "missing_e_way_bills"],
        # Year-end
        "avg_year_end_duration_days": 18,
        "common_provisions": ["bonus_payable", "audit_fees"],
        "common_auditor_requests": ["bank_reconciliation", "fixed_asset_register"],
        # Meta
        "last_computed_at": _days_ago(1),
        "data_points_used": 156,
        "is_current": True,
        "created_at": _days_ago(90),
        "updated_at": _days_ago(1),
    },
    {
        "id": "cp-002",
        "firm_id": "firm-001",
        "client_id": "c-003",
        "profile_version": 5,
        # Behavioural
        "doc_upload_reliability": 41.0,
        "portal_engagement": 28.5,
        "avg_response_time_days": 6.2,
        "preferred_contact": "email",
        # Compliance
        "avg_gst_delay_days": 12.8,
        "avg_tds_delay_days": 8.5,
        "missed_deadline_count": 7,
        "notice_count": 2,
        "compliance_score": 42.0,
        # Financial
        "seasonal_revenue_peak": "Q1",
        "cash_flow_risk_months": ["October", "November", "March"],
        "avg_debtor_days": 91.0,
        # Recurring issues
        "recurring_issues": [
            "late_gstr1", "late_gstr3b", "tds_short_deduction", "missing_invoices"
        ],
        # Year-end
        "avg_year_end_duration_days": 35,
        "common_provisions": ["gratuity", "leave_encashment", "bad_debts"],
        "common_auditor_requests": [
            "debtors_confirmation", "creditors_list", "loan_statements"
        ],
        # Meta
        "last_computed_at": _days_ago(2),
        "data_points_used": 312,
        "is_current": True,
        "created_at": _days_ago(180),
        "updated_at": _days_ago(2),
    },
    {
        "id": "cp-003",
        "firm_id": "firm-001",
        "client_id": "c-005",
        "profile_version": 2,
        # Behavioural
        "doc_upload_reliability": 95.0,
        "portal_engagement": 91.0,
        "avg_response_time_days": 0.3,
        "preferred_contact": "portal",
        # Compliance
        "avg_gst_delay_days": 0.0,
        "avg_tds_delay_days": 0.0,
        "missed_deadline_count": 0,
        "notice_count": 0,
        "compliance_score": 98.5,
        # Financial
        "seasonal_revenue_peak": "Mar",
        "cash_flow_risk_months": [],
        "avg_debtor_days": 18.0,
        # Recurring issues
        "recurring_issues": [],
        # Year-end
        "avg_year_end_duration_days": 8,
        "common_provisions": ["directors_remuneration"],
        "common_auditor_requests": ["related_party_transactions"],
        # Meta
        "last_computed_at": _days_ago(3),
        "data_points_used": 89,
        "is_current": True,
        "created_at": _days_ago(60),
        "updated_at": _days_ago(3),
    },
]

MOCK_CLIENT_PROFILE_HISTORY: list[dict] = []

MOCK_FIRM_PROFILES: list[dict] = [
    {
        "id": "fp-001",
        "firm_id": "firm-001",
        # Operational
        "peak_workload_months": ["March", "July", "October"],
        "avg_tasks_per_client": 8.4,
        "common_bottleneck_types": [
            "missing_documents", "client_non_response", "portal_downtime"
        ],
        "team_utilisation_trend": "increasing",
        # Portfolio
        "portfolio_compliance_score": 72.5,
        "common_risk_categories": ["gst_late_filing", "tds_short_deduction"],
        "portfolio_health_trend": "stable",
        # Revenue
        "avg_revenue_per_client_paise": 4500000,   # ₹45,000
        "revenue_growth_trend": "increasing",
        "billing_recovery_rate": 91.2,
        # Seasonal
        "deadline_concentration": {
            "March": 42, "July": 31, "October": 28,
            "January": 18, "April": 15
        },
        "capacity_risk_months": ["March", "July"],
        # Meta
        "last_computed_at": _days_ago(1),
        "is_current": True,
        "created_at": _days_ago(365),
        "updated_at": _days_ago(1),
    }
]

MOCK_TRIGGERS: list[dict] = [
    {
        "id": "amt-001",
        "firm_id": "firm-001",
        "client_id": "c-003",
        "trigger_type": "repeat_issue",
        "title": "Repeat Late Filing — Mehta Textiles (4th occurrence)",
        "what_detected": (
            "GSTR-3B filed after due date for the 4th consecutive quarter. "
            "Pattern established over 12 months."
        ),
        "evidence": [
            {"period": "Q1 FY25", "delay_days": 9},
            {"period": "Q2 FY25", "delay_days": 14},
            {"period": "Q3 FY25", "delay_days": 11},
            {"period": "Q4 FY25", "delay_days": 18},
        ],
        "why_it_matters": (
            "Interest at 18% p.a. under Section 50 CGST Act is accumulating. "
            "3 late filings in 12 months can trigger scrutiny assessment."
        ),
        "recommended_action": (
            "Schedule a call with client to set up auto-reminder 10 days before due date. "
            "Consider pre-populating GSTR-3B from GSTR-1 data."
        ),
        "confidence": 96.0,
        "severity": "high",
        "status": "active",
        "acknowledged_by": None,
        "acknowledged_at": None,
        "resolved_at": None,
        "source_data": {"filing_type": "GSTR-3B", "occurrences": 4, "avg_delay_days": 13},
        "profile_version": 5,
        "created_at": _days_ago(2),
        "updated_at": _days_ago(2),
    },
    {
        "id": "amt-002",
        "firm_id": "firm-001",
        "client_id": "c-001",
        "trigger_type": "cash_flow_warning",
        "title": "Cash Flow Risk — January / February Crunch Predicted",
        "what_detected": (
            "Historical data shows negative cash flow in January and February "
            "for the past 3 financial years."
        ),
        "evidence": [
            {"year": "FY23", "months_in_stress": ["January", "February"], "min_balance_paise": 85000},
            {"year": "FY24", "months_in_stress": ["January", "February"], "min_balance_paise": 42000},
            {"year": "FY25", "months_in_stress": ["January"], "min_balance_paise": 120000},
        ],
        "why_it_matters": (
            "Advance tax instalment due 15 March requires healthy reserves. "
            "Cash stress in Jan-Feb may lead to interest under Section 234B/C IT Act."
        ),
        "recommended_action": (
            "Advise client to build a 60-day cash buffer by December. "
            "Review debtor collection strategy for Q3."
        ),
        "confidence": 81.0,
        "severity": "medium",
        "status": "active",
        "acknowledged_by": None,
        "acknowledged_at": None,
        "resolved_at": None,
        "source_data": {
            "risk_months": ["January", "February"],
            "avg_min_balance_paise": 82333,
        },
        "profile_version": 3,
        "created_at": _days_ago(5),
        "updated_at": _days_ago(5),
    },
]

MOCK_ANOMALIES: list[dict] = []

MOCK_YEAR_END_REPORTS: list[dict] = []
