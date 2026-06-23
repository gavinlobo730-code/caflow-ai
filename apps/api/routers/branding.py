"""
Firm Branding, Invoice Settings, Invoice Templates, and Email Templates.

All endpoints are firm-scoped (firm_id from JWT). Partner-only writes;
Manager+ reads. Audit-logged on every mutation.
"""
import os
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from core.permissions import rbac
from models.common import api_response
from repositories.branding_repository import branding_repo
from services.audit_service import log_event

_USE_MOCK = not os.environ.get("SUPABASE_URL")

router = APIRouter(prefix="/api/settings", tags=["branding"])

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_VALID_FONTS = {"Inter", "Roboto", "Poppins", "Lato", "Montserrat", "Open Sans", "Nunito"}
_VALID_TEMPLATE_TYPES = {"classic", "modern", "professional_ca", "corporate", "minimal"}
_VALID_EMAIL_TYPES = {"invoice", "engagement", "document_request", "reminder"}
_LOGO_BUCKET = "firm-assets"


# ── Schemas ───────────────────────────────────────────────────────────────────

class BrandingUpdate(BaseModel):
    logo_url: Optional[str] = None
    secondary_logo_url: Optional[str] = None
    tagline: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    accent_color: Optional[str] = None
    font_family: Optional[str] = None
    social_links: Optional[dict] = None


class InvoiceSettingsUpdate(BaseModel):
    prefix: Optional[str] = None
    include_financial_year: Optional[bool] = None
    sequence_length: Optional[int] = None
    starting_number: Optional[int] = None
    manual_override_allowed: Optional[bool] = None
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    account_holder: Optional[str] = None
    ifsc_code: Optional[str] = None
    upi_id: Optional[str] = None
    upi_qr_url: Optional[str] = None
    footer_text: Optional[str] = None


class InvoiceTemplateCreate(BaseModel):
    name: str
    template_type: str = "classic"
    logo_position: str = "left"
    header_style: str = "standard"
    footer_style: str = "standard"
    signature_placement: str = "right"
    is_active: bool = True
    is_default: bool = False


class InvoiceTemplateUpdate(BaseModel):
    name: Optional[str] = None
    template_type: Optional[str] = None
    logo_position: Optional[str] = None
    header_style: Optional[str] = None
    footer_style: Optional[str] = None
    signature_placement: Optional[str] = None
    is_active: Optional[bool] = None


class EmailTemplateUpsert(BaseModel):
    template_type: str
    subject: str
    body: str
    is_active: bool = True


class EmailTemplateUpdate(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None
    is_active: Optional[bool] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _audit(firm_id, entity_id, action, current_user, *, old_data=None, new_data=None):
    try:
        log_event(
            firm_id, "branding", entity_id, action,
            actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            old_data=old_data,
            new_data=new_data,
        )
    except Exception:
        pass


def _validate_color(value: Optional[str], field: str) -> Optional[str]:
    if value is None:
        return None
    if not _HEX_COLOR.match(value):
        raise HTTPException(status_code=422, detail=f"{field} must be a valid hex color like #2563EB")
    return value.upper()


# ── Branding endpoints ────────────────────────────────────────────────────────

@router.get("/branding")
def get_branding(current_user: dict = Depends(rbac("branding", "read"))):
    firm_id = current_user["firm_id"]
    branding = branding_repo.get_branding(firm_id)
    return api_response(True, {"branding": branding or {}})


@router.put("/branding")
def upsert_branding(body: BrandingUpdate, current_user: dict = Depends(rbac("branding", "write"))):
    firm_id = current_user["firm_id"]
    existing = branding_repo.get_branding(firm_id)

    updates = body.model_dump(exclude_unset=True)

    for color_field in ("primary_color", "secondary_color", "accent_color"):
        if color_field in updates:
            updates[color_field] = _validate_color(updates[color_field], color_field)

    if "font_family" in updates and updates["font_family"] not in _VALID_FONTS:
        raise HTTPException(status_code=422, detail=f"font_family must be one of: {', '.join(sorted(_VALID_FONTS))}")

    saved = branding_repo.upsert_branding(firm_id, updates)
    _audit(firm_id, saved.get("id", firm_id), "update", current_user, old_data=existing, new_data=updates)
    return api_response(True, {"branding": saved})


@router.post("/branding/logo")
async def upload_logo(
    file: UploadFile = File(...),
    current_user: dict = Depends(rbac("branding", "write")),
):
    """Upload a firm logo to Supabase Storage and return the public URL."""
    firm_id = current_user["firm_id"]

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="Only image files are accepted (PNG, JPEG, SVG, WebP).")

    ext = (file.filename or "logo").rsplit(".", 1)[-1].lower()
    if ext not in {"png", "jpg", "jpeg", "svg", "webp"}:
        raise HTTPException(status_code=422, detail="Accepted formats: PNG, JPG, SVG, WebP.")

    if _USE_MOCK:
        return api_response(True, {"logo_url": f"https://example.com/logos/{firm_id}/logo.{ext}"})

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Logo file must be smaller than 5 MB.")

    try:
        from core.supabase_client import get_service_supabase
        svc = get_service_supabase()
        path = f"logos/{firm_id}/logo.{ext}"
        svc.storage.from_(_LOGO_BUCKET).upload(
            path,
            content,
            file_options={"content-type": file.content_type, "upsert": "true"},
        )
        logo_url = svc.storage.from_(_LOGO_BUCKET).get_public_url(path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Logo upload failed: {exc}") from exc

    saved = branding_repo.upsert_branding(firm_id, {"logo_url": logo_url})
    _audit(firm_id, saved.get("id", firm_id), "update", current_user, new_data={"logo_url": logo_url})
    return api_response(True, {"logo_url": logo_url})


# ── Invoice Settings endpoints ────────────────────────────────────────────────

@router.get("/invoice-settings")
def get_invoice_settings(current_user: dict = Depends(rbac("branding", "read"))):
    firm_id = current_user["firm_id"]
    settings = branding_repo.get_invoice_settings(firm_id)
    return api_response(True, {"invoice_settings": settings or {}})


@router.put("/invoice-settings")
def upsert_invoice_settings(body: InvoiceSettingsUpdate, current_user: dict = Depends(rbac("branding", "write"))):
    firm_id = current_user["firm_id"]
    existing = branding_repo.get_invoice_settings(firm_id)

    updates = body.model_dump(exclude_unset=True)

    if "prefix" in updates:
        prefix = (updates["prefix"] or "").strip().upper()
        if not prefix or len(prefix) > 10 or not re.match(r"^[A-Z0-9\-/]+$", prefix):
            raise HTTPException(status_code=422, detail="prefix must be 1–10 uppercase alphanumeric characters.")
        updates["prefix"] = prefix

    if "sequence_length" in updates and not (3 <= updates["sequence_length"] <= 6):
        raise HTTPException(status_code=422, detail="sequence_length must be between 3 and 6.")

    if "starting_number" in updates and updates["starting_number"] < 1:
        raise HTTPException(status_code=422, detail="starting_number must be at least 1.")

    if "ifsc_code" in updates and updates["ifsc_code"]:
        ifsc = updates["ifsc_code"].strip().upper()
        if not re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", ifsc):
            raise HTTPException(status_code=422, detail="ifsc_code must be valid RBI IFSC format (e.g. HDFC0001234).")
        updates["ifsc_code"] = ifsc

    saved = branding_repo.upsert_invoice_settings(firm_id, updates)

    # Seed invoice sequence when starting_number is set above current DB counter
    if "starting_number" in updates and not _USE_MOCK:
        new_start = updates["starting_number"]
        try:
            from core.supabase_client import get_service_supabase
            svc = get_service_supabase()
            seq = svc.table("invoice_sequences").select("last_number").eq("firm_id", firm_id).maybe_single().execute()
            current_seq = seq.data["last_number"] if seq.data else 0
            if current_seq < new_start - 1:
                svc.table("invoice_sequences").upsert(
                    {"firm_id": firm_id, "last_number": new_start - 1},
                    on_conflict="firm_id",
                ).execute()
        except Exception:
            pass  # Non-fatal; sequence seeding is best-effort

    _audit(firm_id, saved.get("id", firm_id), "update", current_user, old_data=existing, new_data=updates)
    return api_response(True, {"invoice_settings": saved})


# ── Invoice Templates endpoints ───────────────────────────────────────────────

@router.get("/invoice-templates")
def list_invoice_templates(current_user: dict = Depends(rbac("branding", "read"))):
    firm_id = current_user["firm_id"]
    templates = branding_repo.list_invoice_templates(firm_id)
    return api_response(True, {"templates": templates, "total": len(templates)})


@router.post("/invoice-templates")
def create_invoice_template(body: InvoiceTemplateCreate, current_user: dict = Depends(rbac("branding", "write"))):
    firm_id = current_user["firm_id"]

    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Template name is required.")

    if body.template_type not in _VALID_TEMPLATE_TYPES:
        raise HTTPException(status_code=422, detail=f"template_type must be one of: {', '.join(sorted(_VALID_TEMPLATE_TYPES))}")

    data = {
        "firm_id": firm_id,
        **body.model_dump(),
        "name": name,
    }
    # If this is marked as default, clear existing default first
    if body.is_default:
        branding_repo.set_default_template(firm_id, "__NONE__")  # clears all

    template = branding_repo.create_invoice_template(data)
    _audit(firm_id, template["id"], "create", current_user, new_data=data)
    return api_response(True, {"template": template})


@router.patch("/invoice-templates/{template_id}")
def update_invoice_template(
    template_id: str,
    body: InvoiceTemplateUpdate,
    current_user: dict = Depends(rbac("branding", "write")),
):
    firm_id = current_user["firm_id"]
    existing = branding_repo.get_invoice_template(template_id)
    if not existing or existing.get("firm_id") != firm_id:
        raise HTTPException(status_code=404, detail="Template not found")

    updates = body.model_dump(exclude_unset=True)
    if "template_type" in updates and updates["template_type"] not in _VALID_TEMPLATE_TYPES:
        raise HTTPException(status_code=422, detail=f"template_type must be one of: {', '.join(sorted(_VALID_TEMPLATE_TYPES))}")

    updated = branding_repo.update_invoice_template(template_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Template not found")

    _audit(firm_id, template_id, "update", current_user, old_data=existing, new_data=updates)
    return api_response(True, {"template": updated})


@router.post("/invoice-templates/{template_id}/set-default")
def set_default_template(template_id: str, current_user: dict = Depends(rbac("branding", "write"))):
    firm_id = current_user["firm_id"]
    existing = branding_repo.get_invoice_template(template_id)
    if not existing or existing.get("firm_id") != firm_id:
        raise HTTPException(status_code=404, detail="Template not found")

    ok = branding_repo.set_default_template(firm_id, template_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to set default template")

    _audit(firm_id, template_id, "update", current_user, new_data={"is_default": True})
    return api_response(True, {"template_id": template_id, "is_default": True})


@router.delete("/invoice-templates/{template_id}")
def delete_invoice_template(template_id: str, current_user: dict = Depends(rbac("branding", "write"))):
    firm_id = current_user["firm_id"]
    existing = branding_repo.get_invoice_template(template_id)
    if not existing or existing.get("firm_id") != firm_id:
        raise HTTPException(status_code=404, detail="Template not found")

    if existing.get("is_default"):
        raise HTTPException(status_code=409, detail="Cannot delete the default template. Set another template as default first.")

    branding_repo.delete_invoice_template(template_id)
    _audit(firm_id, template_id, "delete", current_user, old_data=existing)
    return api_response(True, {"deleted": True})


# ── Email Templates endpoints ─────────────────────────────────────────────────

@router.get("/email-templates")
def list_email_templates(current_user: dict = Depends(rbac("branding", "read"))):
    firm_id = current_user["firm_id"]
    templates = branding_repo.list_email_templates(firm_id)
    return api_response(True, {"templates": templates, "total": len(templates)})


@router.post("/email-templates")
def upsert_email_template(body: EmailTemplateUpsert, current_user: dict = Depends(rbac("branding", "write"))):
    firm_id = current_user["firm_id"]

    if body.template_type not in _VALID_EMAIL_TYPES:
        raise HTTPException(status_code=422, detail=f"template_type must be one of: {', '.join(sorted(_VALID_EMAIL_TYPES))}")
    if not body.subject.strip():
        raise HTTPException(status_code=422, detail="subject is required.")
    if not body.body.strip():
        raise HTTPException(status_code=422, detail="body is required.")

    data = {"subject": body.subject.strip(), "body": body.body.strip(), "is_active": body.is_active}
    saved = branding_repo.upsert_email_template(firm_id, body.template_type, data)
    _audit(firm_id, saved["id"], "update", current_user, new_data=data)
    return api_response(True, {"template": saved})


@router.patch("/email-templates/{template_id}")
def update_email_template(
    template_id: str,
    body: EmailTemplateUpdate,
    current_user: dict = Depends(rbac("branding", "write")),
):
    firm_id = current_user["firm_id"]
    existing = branding_repo.get_email_template(template_id)
    if not existing or existing.get("firm_id") != firm_id:
        raise HTTPException(status_code=404, detail="Email template not found")

    updates = body.model_dump(exclude_unset=True)
    if "subject" in updates and not updates["subject"].strip():
        raise HTTPException(status_code=422, detail="subject cannot be empty.")
    if "body" in updates and not updates["body"].strip():
        raise HTTPException(status_code=422, detail="body cannot be empty.")

    updated = branding_repo.update_email_template(template_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Email template not found")

    _audit(firm_id, template_id, "update", current_user, old_data=existing, new_data=updates)
    return api_response(True, {"template": updated})


@router.delete("/email-templates/{template_id}")
def delete_email_template(template_id: str, current_user: dict = Depends(rbac("branding", "write"))):
    firm_id = current_user["firm_id"]
    existing = branding_repo.get_email_template(template_id)
    if not existing or existing.get("firm_id") != firm_id:
        raise HTTPException(status_code=404, detail="Email template not found")

    branding_repo.delete_email_template(template_id)
    _audit(firm_id, template_id, "delete", current_user, old_data=existing)
    return api_response(True, {"deleted": True})
