"""
XBRL Generation Engine — MCA taxonomy mapping, validation, XML generation.
Companies Act 2013, Schedule III. MCA XBRL taxonomy MCA_2023.

# CA REVIEW REQUIRED — DO NOT AUTO-FILE XBRL to MCA portal
"""
from __future__ import annotations
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from core.permissions import rbac
from models.common import api_response
from services.timeline_service import timeline_service

router = APIRouter(prefix="/api/xbrl", tags=["xbrl_engine"])
_logger = logging.getLogger("caflow.xbrl.router")


class CreatePackageRequest(BaseModel):
    client_id: str
    financial_year: str
    taxonomy_version: str = "MCA_2023"
    year_end_engagement_id: Optional[str] = None


class UpdatePackageDataRequest(BaseModel):
    balance_sheet_json: Optional[dict] = None
    pnl_json: Optional[dict] = None
    notes_json: Optional[dict] = None


class GenerateXMLRequest(BaseModel):
    client_name: str
    cin: str  # Corporate Identification Number


@router.post("/packages")
def create_package(
    req: CreatePackageRequest,
    current_user: dict = Depends(rbac("year_end", "write")),
):
    """Create XBRL package for a client financial year."""
    from domain.income_tax.xbrl_service import create_xbrl_package
    try:
        pkg = create_xbrl_package(
            firm_id=current_user["firm_id"],
            client_id=req.client_id,
            financial_year=req.financial_year,
            created_by=current_user["id"],
            year_end_engagement_id=req.year_end_engagement_id,
            taxonomy_version=req.taxonomy_version,
        )
        return api_response(True, pkg)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/packages")
def list_packages(
    client_id: str,
    current_user: dict = Depends(rbac("year_end", "read")),
):
    from domain.income_tax.xbrl_service import list_xbrl_packages
    return api_response(True, list_xbrl_packages(current_user["firm_id"], client_id))


@router.put("/packages/{package_id}/data")
def update_package_data(
    package_id: str,
    req: UpdatePackageDataRequest,
    current_user: dict = Depends(rbac("year_end", "write")),
):
    """Update Schedule III data in XBRL package. Amounts must be in integer paise."""
    from domain.income_tax.xbrl_service import update_xbrl_data
    try:
        result = update_xbrl_data(
            firm_id=current_user["firm_id"],
            package_id=package_id,
            balance_sheet_json=req.balance_sheet_json,
            pnl_json=req.pnl_json,
            notes_json=req.notes_json,
        )
        return api_response(True, result)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.post("/packages/{package_id}/validate")
def validate_package(
    package_id: str,
    current_user: dict = Depends(rbac("year_end", "write")),
):
    """
    Validate XBRL package against MCA taxonomy.
    Checks mandatory tags, data types, and balancing equations.
    """
    from domain.income_tax.xbrl_service import validate_xbrl_package
    try:
        result = validate_xbrl_package(current_user["firm_id"], package_id)
        has_errors = bool(result.get("validation_errors") or result.get("missing_tags"))
        if not has_errors:
            timeline_service.log(
                client_id=result.get("client_id", ""),
                category="tax",
                action="xbrl_generated",
                description=f"XBRL package validated for FY {result.get('financial_year')}",
                severity="success",
                metadata={"package_id": package_id},
            )
        return api_response(True, result)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.post("/packages/{package_id}/generate-xml")
def generate_xml(
    package_id: str,
    req: GenerateXMLRequest,
    current_user: dict = Depends(rbac("year_end", "approve")),
):
    """
    Generate XBRL XML from validated package.
    # CA REVIEW REQUIRED — DO NOT AUTO-FILE to MCA portal
    """
    from domain.income_tax.xbrl_service import generate_xbrl_xml
    try:
        xml = generate_xbrl_xml(
            firm_id=current_user["firm_id"],
            package_id=package_id,
            client_name=req.client_name,
            cin=req.cin,
        )
        return api_response(True, {
            "xbrl_xml": xml,
            "ca_review_required": True,
            "warning": "CA REVIEW REQUIRED — DO NOT AUTO-FILE to MCA portal",
        })
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.post("/packages/{package_id}/review")
def review_package(
    package_id: str,
    current_user: dict = Depends(rbac("year_end", "approve")),
):
    """Mark XBRL package as CA-reviewed."""
    from domain.income_tax.xbrl_service import _supabase, _USE_MOCK, _MOCK_PACKAGES
    from datetime import datetime, timezone
    update = {
        "status": "reviewed",
        "reviewed_by": current_user["id"],
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if _USE_MOCK:
        if package_id in _MOCK_PACKAGES:
            _MOCK_PACKAGES[package_id].update(update)
        result = _MOCK_PACKAGES.get(package_id, {})
    else:
        sb = _supabase()
        res = sb.table("xbrl_packages").update(update).eq(
            "id", package_id
        ).eq("firm_id", current_user["firm_id"]).execute()
        result = res.data[0] if res.data else {}

    timeline_service.log(
        client_id=result.get("client_id", ""),
        category="tax",
        action="xbrl_reviewed",
        description="XBRL package reviewed by partner",
        severity="success",
        metadata={"package_id": package_id},
    )
    return api_response(True, result)


@router.get("/tag-mappings")
def get_tag_mappings(
    taxonomy_version: str = "MCA_2023",
    current_user: dict = Depends(rbac("year_end", "read")),
):
    """Get default Schedule III → XBRL tag mappings for the given taxonomy."""
    from domain.income_tax.xbrl_service import get_default_tag_mappings
    return api_response(True, {
        "taxonomy_version": taxonomy_version,
        "mappings": get_default_tag_mappings(taxonomy_version),
    })
