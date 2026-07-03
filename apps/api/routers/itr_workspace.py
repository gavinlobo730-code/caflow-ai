"""
ITR Preparation Workspace — Filing workflow, computation snapshots, disallowances, deductions, losses.
IT Act 1961 — Sections 139, 140, 40A(3), 43B, 72, 74, 80C–80JJAA.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.permissions import rbac
from models.common import api_response
from services.timeline_service import timeline_service

router = APIRouter(prefix="/api/itr", tags=["itr_workspace"])
_logger = logging.getLogger("caflow.itr.router")


# ── Request Models ─────────────────────────────────────────────────────────────

class CreateFilingRequest(BaseModel):
    client_id: str
    financial_year: str
    assessment_year: str
    itr_form: str = Field(..., description="ITR-3, ITR-5, ITR-6, ITR-7")
    computation_snapshot_id: Optional[str] = None
    notes: Optional[str] = None


class TransitionFilingRequest(BaseModel):
    new_status: str = Field(..., description="draft|review|partner_review|ready_for_filing|filed")
    notes: Optional[str] = None


class SaveVersionRequest(BaseModel):
    json_payload: dict


class AcknowledgementRequest(BaseModel):
    acknowledgement_number: str
    filing_date: str  # YYYY-MM-DD


class SnapshotRequest(BaseModel):
    client_id: str
    financial_year: str
    assessment_year: str
    regime: str = Field(..., description="new|old")
    income: dict = Field(default_factory=dict)
    computation_result: dict = Field(default_factory=dict)
    notes: Optional[str] = None


class DisallowanceRequest(BaseModel):
    client_id: str
    financial_year: str
    section: str = Field(..., description="40A(3)|43B_pf|43B_gst|43B_bonus|other")
    description: str
    amount_paise: int = Field(..., ge=0)
    evidence_document_id: Optional[str] = None
    journal_entry_id: Optional[str] = None
    notes: Optional[str] = None


class DisallowanceStatusRequest(BaseModel):
    status: str = Field(..., description="pending|accepted|rejected")


class DeductionClaimRequest(BaseModel):
    client_id: str
    financial_year: str
    section: str
    claimed_amount_paise: int = Field(..., ge=0)
    sub_head: Optional[str] = None
    evidence_document_id: Optional[str] = None
    notes: Optional[str] = None


class BFLossRequest(BaseModel):
    client_id: str
    assessment_year: str
    loss_type: str
    original_amount_paise: int = Field(..., ge=0)
    expiry_assessment_year: str
    source_itr_ack: Optional[str] = None
    notes: Optional[str] = None


class UtilizeLossRequest(BaseModel):
    utilization_paise: int = Field(..., ge=0)


# ── Computation Snapshots ──────────────────────────────────────────────────────

@router.post("/snapshots")
def create_snapshot(
    req: SnapshotRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """
    Save immutable versioned tax computation snapshot.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    from domain.income_tax.computation_workspace import save_computation_snapshot
    try:
        snap = save_computation_snapshot(
            firm_id=current_user["firm_id"],
            client_id=req.client_id,
            financial_year=req.financial_year,
            assessment_year=req.assessment_year,
            regime=req.regime,
            income=req.income,
            computation_result=req.computation_result,
            created_by=current_user["id"],
            notes=req.notes,
        )
        timeline_service.log(
            client_id=req.client_id,
            category="tax",
            action="tax_computation_generated",
            description=f"Tax computation snapshot v{snap.get('version',1)} created for FY {req.financial_year}",
            severity="info",
            metadata={"snapshot_id": snap.get("id"), "regime": req.regime, "fy": req.financial_year},
        )
        return api_response(True, snap)
    except Exception as e:
        _logger.exception("Failed to save snapshot")
        raise HTTPException(500, detail=str(e))


@router.get("/snapshots")
def list_snapshots(
    client_id: str,
    financial_year: str,
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    from domain.income_tax.computation_workspace import list_snapshots as _list
    return api_response(True, _list(current_user["firm_id"], client_id, financial_year))


@router.post("/snapshots/{snapshot_id}/review")
def review_snapshot(
    snapshot_id: str,
    current_user: dict = Depends(rbac("income_tax", "approve")),
):
    """
    Mark computation snapshot as CA-reviewed.
    # CA REVIEW REQUIRED
    """
    from domain.income_tax.computation_workspace import review_snapshot as _review
    try:
        result = _review(current_user["firm_id"], snapshot_id, current_user["id"])
        timeline_service.log(
            client_id=result.get("client_id", ""),
            category="tax",
            action="tax_computation_reviewed",
            description=f"Tax computation snapshot {snapshot_id} reviewed",
            severity="success",
            metadata={"snapshot_id": snapshot_id},
        )
        return api_response(True, result)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# ── ITR Filings ───────────────────────────────────────────────────────────────

@router.post("/filings")
def create_filing(
    req: CreateFilingRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Create ITR filing in draft state."""
    from domain.income_tax.itr_workflow import create_itr_filing
    try:
        filing = create_itr_filing(
            firm_id=current_user["firm_id"],
            client_id=req.client_id,
            financial_year=req.financial_year,
            assessment_year=req.assessment_year,
            itr_form=req.itr_form,
            created_by=current_user["id"],
            computation_snapshot_id=req.computation_snapshot_id,
            notes=req.notes,
        )
        timeline_service.log(
            client_id=req.client_id,
            category="tax",
            action="itr_prepared",
            description=f"{req.itr_form} filing created for FY {req.financial_year}",
            severity="info",
            metadata={"filing_id": filing.get("id"), "form": req.itr_form},
        )
        return api_response(True, filing)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/filings")
def list_filings(
    client_id: str,
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    from domain.income_tax.itr_workflow import list_itr_filings
    return api_response(True, list_itr_filings(current_user["firm_id"], client_id))


@router.post("/filings/{filing_id}/transition")
def transition_filing(
    filing_id: str,
    req: TransitionFilingRequest,
    current_user: dict = Depends(rbac("income_tax", "approve")),
):
    """
    Advance ITR filing through workflow.
    # CA REVIEW REQUIRED — Partner review required before ready_for_filing.
    """
    from domain.income_tax.itr_workflow import transition_itr_status
    try:
        result = transition_itr_status(
            firm_id=current_user["firm_id"],
            filing_id=filing_id,
            new_status=req.new_status,
            actor_id=current_user["id"],
            notes=req.notes,
        )
        event_map = {
            "ready_for_filing": ("itr_ready_for_filing", "ITR ready for filing", "warning"),
            "filed": ("itr_filed", "ITR filed", "success"),
        }
        if req.new_status in event_map:
            action, desc, sev = event_map[req.new_status]
            timeline_service.log(
                client_id=result.get("client_id", ""),
                category="tax",
                action=action,
                description=desc,
                severity=sev,
                metadata={"filing_id": filing_id, "status": req.new_status},
            )
        return api_response(True, result)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.post("/filings/{filing_id}/versions")
def save_version(
    filing_id: str,
    req: SaveVersionRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    from domain.income_tax.itr_workflow import save_itr_version
    try:
        ver = save_itr_version(
            firm_id=current_user["firm_id"],
            filing_id=filing_id,
            json_payload=req.json_payload,
            created_by=current_user["id"],
        )
        return api_response(True, ver)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.post("/filings/{filing_id}/acknowledge")
def record_acknowledgement(
    filing_id: str,
    req: AcknowledgementRequest,
    current_user: dict = Depends(rbac("income_tax", "approve")),
):
    """
    Record ITR acknowledgement after CA files on Income Tax Portal.
    # CA REVIEW REQUIRED — CA must manually file on portal before calling this
    """
    from domain.income_tax.itr_workflow import record_filing_acknowledgement
    try:
        result = record_filing_acknowledgement(
            firm_id=current_user["firm_id"],
            filing_id=filing_id,
            acknowledgement_number=req.acknowledgement_number,
            filing_date=req.filing_date,
            actor_id=current_user["id"],
        )
        timeline_service.log(
            client_id=result.get("client_id", ""),
            category="tax",
            action="itr_filed",
            description=f"ITR filed — Ack: {req.acknowledgement_number}",
            severity="success",
            metadata={"filing_id": filing_id, "ack": req.acknowledgement_number},
        )
        return api_response(True, result)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# ── Disallowances ─────────────────────────────────────────────────────────────

@router.post("/disallowances")
def create_disallowance(
    req: DisallowanceRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """
    Record tax disallowance (IT Act 40A(3), 43B etc.) with evidence.
    All amounts in paise — never float.
    """
    from domain.income_tax.computation_workspace import create_disallowance as _create
    try:
        result = _create(
            firm_id=current_user["firm_id"],
            client_id=req.client_id,
            financial_year=req.financial_year,
            section=req.section,
            description=req.description,
            amount_paise=req.amount_paise,
            created_by=current_user["id"],
            evidence_document_id=req.evidence_document_id,
            journal_entry_id=req.journal_entry_id,
            notes=req.notes,
        )
        return api_response(True, result)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/disallowances")
def list_disallowances(
    client_id: str,
    financial_year: str,
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    from domain.income_tax.computation_workspace import list_disallowances as _list
    return api_response(True, _list(current_user["firm_id"], client_id, financial_year))


@router.patch("/disallowances/{disallowance_id}/status")
def update_disallowance_status(
    disallowance_id: str,
    req: DisallowanceStatusRequest,
    current_user: dict = Depends(rbac("income_tax", "approve")),
):
    from domain.income_tax.computation_workspace import update_disallowance_status as _update
    result = _update(current_user["firm_id"], disallowance_id, req.status)
    return api_response(True, result)


@router.post("/disallowances/auto-detect-40a3")
def auto_detect_40a3(
    client_id: str,
    financial_year: str,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """
    Auto-detect Section 40A(3) cash payments >₹10,000 from ledger.
    IT Act Section 40A(3) — Disallowance of cash payments exceeding ₹10,000.
    """
    from domain.income_tax.computation_workspace import auto_detect_40a3 as _detect
    detected = _detect(current_user["firm_id"], client_id, financial_year, current_user["id"])
    return api_response(True, {"detected": len(detected), "items": detected})


# ── Deduction Claims ──────────────────────────────────────────────────────────

@router.post("/deductions")
def create_deduction(
    req: DeductionClaimRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    from domain.income_tax.computation_workspace import create_deduction_claim
    try:
        result = create_deduction_claim(
            firm_id=current_user["firm_id"],
            client_id=req.client_id,
            financial_year=req.financial_year,
            section=req.section,
            claimed_amount_paise=req.claimed_amount_paise,
            created_by=current_user["id"],
            sub_head=req.sub_head,
            evidence_document_id=req.evidence_document_id,
            notes=req.notes,
        )
        return api_response(True, result)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/deductions")
def list_deductions(
    client_id: str,
    financial_year: str,
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    from domain.income_tax.computation_workspace import list_deduction_claims
    return api_response(True, list_deduction_claims(current_user["firm_id"], client_id, financial_year))


# ── Brought Forward Losses ────────────────────────────────────────────────────

@router.post("/bf-losses")
def create_bf_loss(
    req: BFLossRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """
    Record brought-forward loss.
    IT Act Section 72 (business loss, 8 years), Section 74 (capital loss, 8 years).
    """
    from domain.income_tax.computation_workspace import create_bf_loss as _create
    try:
        result = _create(
            firm_id=current_user["firm_id"],
            client_id=req.client_id,
            assessment_year=req.assessment_year,
            loss_type=req.loss_type,
            original_amount_paise=req.original_amount_paise,
            expiry_assessment_year=req.expiry_assessment_year,
            created_by=current_user["id"],
            source_itr_ack=req.source_itr_ack,
            notes=req.notes,
        )
        return api_response(True, result)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/bf-losses")
def list_bf_losses(
    client_id: str,
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    from domain.income_tax.computation_workspace import list_bf_losses as _list
    return api_response(True, _list(current_user["firm_id"], client_id))


@router.post("/bf-losses/{loss_id}/utilize")
def utilize_loss(
    loss_id: str,
    req: UtilizeLossRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    from domain.income_tax.computation_workspace import utilize_bf_loss
    try:
        result = utilize_bf_loss(current_user["firm_id"], loss_id, req.utilization_paise)
        return api_response(True, result)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
