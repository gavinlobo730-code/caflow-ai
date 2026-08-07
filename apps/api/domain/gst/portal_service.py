"""
GST Portal Read-Only Integration — Provider abstraction for GST portal data.
CGST Act 2017 — GST compliance data retrieval.

READ-ONLY ONLY. No filing, no submission.
# CA REVIEW REQUIRED — Portal data must be reviewed before acting on it.
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from uuid import uuid4

_logger = logging.getLogger("caflow.gst.portal")
_USE_MOCK = not os.environ.get("SUPABASE_URL")

_MOCK_SNAPSHOTS: dict[str, dict] = {}
_MOCK_SYNC_JOBS: dict[str, dict] = {}

SNAPSHOT_TYPES = (
    "profile", "filing_status", "return_history",
    "liability_summary", "gstr1_status", "gstr3b_status"
)


class GSTPortalProvider(ABC):
    """Abstract interface for GST portal data providers."""

    @abstractmethod
    def fetch_profile(self, gstin: str) -> dict: ...

    @abstractmethod
    def fetch_filing_status(self, gstin: str, financial_year: str) -> dict: ...

    @abstractmethod
    def fetch_return_history(self, gstin: str, financial_year: str) -> list[dict]: ...

    @abstractmethod
    def fetch_liability_summary(self, gstin: str, period: str) -> dict: ...

    @abstractmethod
    def fetch_gstr1_status(self, gstin: str, period: str) -> dict: ...

    @abstractmethod
    def fetch_gstr3b_status(self, gstin: str, period: str) -> dict: ...


class ManualGSTProvider(GSTPortalProvider):
    """Manual provider — CA downloads data from GST portal and uploads here."""

    def fetch_profile(self, gstin: str) -> dict:
        return {"gstin": gstin, "status": "manual", "message": "Upload data manually"}

    def fetch_filing_status(self, gstin: str, financial_year: str) -> dict:
        return {"gstin": gstin, "financial_year": financial_year, "status": "manual"}

    def fetch_return_history(self, gstin: str, financial_year: str) -> list[dict]:
        return []

    def fetch_liability_summary(self, gstin: str, period: str) -> dict:
        return {"gstin": gstin, "period": period, "status": "manual"}

    def fetch_gstr1_status(self, gstin: str, period: str) -> dict:
        return {"gstin": gstin, "period": period, "status": "manual"}

    def fetch_gstr3b_status(self, gstin: str, period: str) -> dict:
        return {"gstin": gstin, "period": period, "status": "manual"}


def get_provider(provider_name: str = "manual") -> GSTPortalProvider:
    return ManualGSTProvider()


def _supabase():
    from core.supabase_client import get_supabase
    return get_supabase()


# ── Sync Jobs ──────────────────────────────────────────────────────────────────

def create_sync_job(
    firm_id: str,
    client_id: str,
    gstin: str,
    triggered_by: str,
    scope: list[str] | None = None,
    sync_type: str = "manual",
) -> dict:
    scope = scope or list(SNAPSHOT_TYPES)

    if _USE_MOCK:
        job = {
            "id": str(uuid4()),
            "firm_id": firm_id,
            "client_id": client_id,
            "gstin": gstin,
            "sync_type": sync_type,
            "scope": scope,
            "status": "pending",
            "snapshots_created": 0,
            "triggered_by": triggered_by,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _MOCK_SYNC_JOBS[job["id"]] = job
        return job

    sb = _supabase()
    row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "gstin": gstin,
        "sync_type": sync_type,
        "scope": scope,
        "status": "pending",
        "triggered_by": triggered_by,
    }
    res = sb.table("gst_sync_jobs").insert(row).execute()
    return res.data[0] if res.data else row


def run_sync_job(
    firm_id: str,
    job_id: str,
    provider_name: str = "manual",
) -> dict:
    """
    Execute GST portal sync — read-only, no filing.
    # CA REVIEW REQUIRED — Data is pulled from portal, not submitted.
    """
    if _USE_MOCK:
        job = _MOCK_SYNC_JOBS.get(job_id, {})
        job["status"] = "completed"
        job["snapshots_created"] = 0
        job["completed_at"] = datetime.now(timezone.utc).isoformat()
        return job

    sb = _supabase()
    job_res = sb.table("gst_sync_jobs").select("*").eq("id", job_id).eq(
        "firm_id", firm_id
    ).single().execute()
    if not job_res.data:
        raise ValueError("Sync job not found")

    job = job_res.data
    sb.table("gst_sync_jobs").update({
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", job_id).execute()

    provider = get_provider(provider_name)
    gstin = job["gstin"]
    client_id = job["client_id"]
    scope = job.get("scope", list(SNAPSHOT_TYPES))
    snapshots_created = 0

    failed: list[dict] = []
    try:
        for snap_type in scope:
            if snap_type not in SNAPSHOT_TYPES:
                continue
            try:
                data = _fetch_snapshot_data(provider, snap_type, gstin)
                _save_snapshot(sb, firm_id, client_id, gstin, snap_type, data, job_id)
                snapshots_created += 1
            except Exception as e:
                _logger.warning("Failed to fetch %s for %s: %s", snap_type, gstin, e)
                failed.append({"snap_type": snap_type, "error": str(e)})

        # A per-snap_type fetch failure must not be silently swallowed into a
        # blanket "completed" — the CA needs to know some (or all) of the
        # requested portal data was not actually refreshed.
        if not failed:
            status = "completed"
        elif snapshots_created == 0:
            status = "error"
        else:
            status = "partial_failure"

        update_payload = {
            "status": status,
            "snapshots_created": snapshots_created,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        if failed:
            update_payload["error_message"] = "; ".join(
                f"{f['snap_type']}: {f['error']}" for f in failed)
        sb.table("gst_sync_jobs").update(update_payload).eq("id", job_id).execute()

    except Exception as e:
        sb.table("gst_sync_jobs").update({
            "status": "error",
            "error_message": str(e),
        }).eq("id", job_id).execute()
        raise

    return {"status": status, "snapshots_created": snapshots_created, "failed": failed}


def _fetch_snapshot_data(provider: GSTPortalProvider, snap_type: str, gstin: str) -> dict:
    if snap_type == "profile":
        return provider.fetch_profile(gstin)
    if snap_type == "filing_status":
        return provider.fetch_filing_status(gstin, "2024-25")
    if snap_type == "return_history":
        return {"records": provider.fetch_return_history(gstin, "2024-25")}
    if snap_type == "liability_summary":
        return provider.fetch_liability_summary(gstin, "042025")
    if snap_type == "gstr1_status":
        return provider.fetch_gstr1_status(gstin, "042025")
    if snap_type == "gstr3b_status":
        return provider.fetch_gstr3b_status(gstin, "042025")
    return {}


def _save_snapshot(
    sb: object,
    firm_id: str,
    client_id: str,
    gstin: str,
    snapshot_type: str,
    data: dict,
    sync_job_id: str,
) -> None:
    row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "gstin": gstin,
        "snapshot_type": snapshot_type,
        "data": data,
        "sync_job_id": sync_job_id,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
    sb.table("gst_portal_snapshots").insert(row).execute()  # type: ignore


def save_manual_snapshot(
    firm_id: str,
    client_id: str,
    gstin: str,
    snapshot_type: str,
    data: dict,
    financial_year: str | None = None,
    period: str | None = None,
) -> dict:
    """Save manually uploaded GST portal data."""
    if _USE_MOCK:
        snap = {
            "id": str(uuid4()),
            "firm_id": firm_id,
            "client_id": client_id,
            "gstin": gstin,
            "snapshot_type": snapshot_type,
            "financial_year": financial_year,
            "period": period,
            "data": data,
            "provider": "manual",
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _MOCK_SNAPSHOTS[snap["id"]] = snap
        return snap

    sb = _supabase()
    row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "gstin": gstin,
        "snapshot_type": snapshot_type,
        "financial_year": financial_year,
        "period": period,
        "data": data,
        "provider": "manual",
    }
    res = sb.table("gst_portal_snapshots").insert(row).execute()
    return res.data[0] if res.data else row


def list_snapshots(
    firm_id: str,
    client_id: str,
    snapshot_type: str | None = None,
) -> list[dict]:
    if _USE_MOCK:
        snaps = [s for s in _MOCK_SNAPSHOTS.values()
                 if s["firm_id"] == firm_id and s["client_id"] == client_id]
        if snapshot_type:
            snaps = [s for s in snaps if s["snapshot_type"] == snapshot_type]
        return snaps

    sb = _supabase()
    q = sb.table("gst_portal_snapshots").select("*").eq("firm_id", firm_id).eq("client_id", client_id)
    if snapshot_type:
        q = q.eq("snapshot_type", snapshot_type)
    res = q.order("synced_at", desc=True).execute()
    return res.data or []


def get_sync_job(firm_id: str, job_id: str) -> dict | None:
    """One sync job, scoped to the firm — or None.

    Added so the router can resolve a job's CLIENT before running it.
    `run_sync_job` reads job["client_id"] itself, but only after it has already
    flipped the job to "running" and started writing snapshots, which is too
    late to refuse. The firm filter is on the query, not applied afterwards, so
    another firm's job is never in hand at all.
    """
    if _USE_MOCK:
        job = _MOCK_SYNC_JOBS.get(job_id)
        return job if job and job.get("firm_id") == firm_id else None

    res = (
        _supabase().table("gst_sync_jobs").select("*")
        .eq("id", job_id).eq("firm_id", firm_id).limit(1).execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def list_sync_jobs(firm_id: str, client_id: str) -> list[dict]:
    if _USE_MOCK:
        return [j for j in _MOCK_SYNC_JOBS.values()
                if j["firm_id"] == firm_id and j["client_id"] == client_id]

    sb = _supabase()
    res = sb.table("gst_sync_jobs").select("*").eq("firm_id", firm_id).eq(
        "client_id", client_id
    ).order("created_at", desc=True).execute()
    return res.data or []
