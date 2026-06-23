import os
import uuid
from typing import Optional
from repositories.base import BaseRepository

_USE_MOCK = not os.environ.get("SUPABASE_URL")

# ── Mock stores ───────────────────────────────────────────────────────────────
if _USE_MOCK:
    _MOCK_BRANDING: dict[str, dict] = {}
    _MOCK_INVOICE_SETTINGS: dict[str, dict] = {}
    _MOCK_INVOICE_TEMPLATES: list[dict] = []
    _MOCK_EMAIL_TEMPLATES: list[dict] = []


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


def _svc():
    from core.supabase_client import get_service_supabase
    return get_service_supabase()


class BrandingRepository(BaseRepository[dict]):

    # ── firm_branding ─────────────────────────────────────────────────────────

    def get_branding(self, firm_id: str) -> Optional[dict]:
        if _USE_MOCK:
            return _MOCK_BRANDING.get(firm_id)
        r = _get_db().table("firm_branding").select("*").eq("firm_id", firm_id).maybe_single().execute()
        return r.data

    def upsert_branding(self, firm_id: str, data: dict) -> dict:
        if _USE_MOCK:
            existing = _MOCK_BRANDING.get(firm_id, {})
            record = {
                "id": existing.get("id", str(uuid.uuid4())),
                "firm_id": firm_id,
                "logo_url": None,
                "secondary_logo_url": None,
                "tagline": None,
                "primary_color": "#2563EB",
                "secondary_color": "#1E40AF",
                "accent_color": "#3B82F6",
                "font_family": "Inter",
                "social_links": {},
                **existing,
                **data,
                "updated_at": self.now_iso(),
            }
            if "created_at" not in record:
                record["created_at"] = self.now_iso()
            _MOCK_BRANDING[firm_id] = record
            return record
        payload = {**data, "firm_id": firm_id, "updated_at": self.now_iso()}
        r = _svc().table("firm_branding").upsert(payload, on_conflict="firm_id").execute()
        return r.data[0]

    # ── invoice_settings ──────────────────────────────────────────────────────

    def get_invoice_settings(self, firm_id: str) -> Optional[dict]:
        if _USE_MOCK:
            return _MOCK_INVOICE_SETTINGS.get(firm_id)
        r = _get_db().table("invoice_settings").select("*").eq("firm_id", firm_id).maybe_single().execute()
        return r.data

    def upsert_invoice_settings(self, firm_id: str, data: dict) -> dict:
        if _USE_MOCK:
            existing = _MOCK_INVOICE_SETTINGS.get(firm_id, {})
            record = {
                "id": existing.get("id", str(uuid.uuid4())),
                "firm_id": firm_id,
                "prefix": "INV",
                "include_financial_year": True,
                "sequence_length": 3,
                "starting_number": 1,
                "manual_override_allowed": False,
                "bank_name": None,
                "account_number": None,
                "account_holder": None,
                "ifsc_code": None,
                "upi_id": None,
                "upi_qr_url": None,
                "footer_text": None,
                **existing,
                **data,
                "updated_at": self.now_iso(),
            }
            if "created_at" not in record:
                record["created_at"] = self.now_iso()
            _MOCK_INVOICE_SETTINGS[firm_id] = record
            return record
        payload = {**data, "firm_id": firm_id, "updated_at": self.now_iso()}
        r = _svc().table("invoice_settings").upsert(payload, on_conflict="firm_id").execute()
        return r.data[0]

    # ── invoice_templates ─────────────────────────────────────────────────────

    def list_invoice_templates(self, firm_id: str) -> list[dict]:
        if _USE_MOCK:
            return [t for t in _MOCK_INVOICE_TEMPLATES if t["firm_id"] == firm_id]
        r = _get_db().table("invoice_templates").select("*").eq("firm_id", firm_id).order("created_at").execute()
        return r.data or []

    def get_invoice_template(self, template_id: str) -> Optional[dict]:
        if _USE_MOCK:
            return next((t for t in _MOCK_INVOICE_TEMPLATES if t["id"] == template_id), None)
        r = _get_db().table("invoice_templates").select("*").eq("id", template_id).maybe_single().execute()
        return r.data

    def create_invoice_template(self, data: dict) -> dict:
        if _USE_MOCK:
            record = {
                "id": str(uuid.uuid4()),
                "is_active": True,
                "is_default": False,
                **data,
                "created_at": self.now_iso(),
                "updated_at": self.now_iso(),
            }
            _MOCK_INVOICE_TEMPLATES.append(record)
            return record
        payload = {**data, "created_at": self.now_iso(), "updated_at": self.now_iso()}
        r = _svc().table("invoice_templates").insert(payload).execute()
        return r.data[0]

    def update_invoice_template(self, template_id: str, data: dict) -> Optional[dict]:
        if _USE_MOCK:
            t = next((t for t in _MOCK_INVOICE_TEMPLATES if t["id"] == template_id), None)
            if not t:
                return None
            t.update({**data, "updated_at": self.now_iso()})
            return t
        r = _svc().table("invoice_templates").update({**data, "updated_at": self.now_iso()}).eq("id", template_id).execute()
        return r.data[0] if r.data else None

    def set_default_template(self, firm_id: str, template_id: str) -> bool:
        if _USE_MOCK:
            for t in _MOCK_INVOICE_TEMPLATES:
                if t["firm_id"] == firm_id:
                    t["is_default"] = t["id"] == template_id
            return True
        # Clear current default, then set new one (two ops; partial failure safe since UNIQUE index prevents two defaults)
        _svc().table("invoice_templates").update({"is_default": False}).eq("firm_id", firm_id).eq("is_default", True).execute()
        r = _svc().table("invoice_templates").update({"is_default": True, "updated_at": self.now_iso()}).eq("id", template_id).eq("firm_id", firm_id).execute()
        return bool(r.data)

    def delete_invoice_template(self, template_id: str) -> bool:
        if _USE_MOCK:
            before = len(_MOCK_INVOICE_TEMPLATES)
            _MOCK_INVOICE_TEMPLATES[:] = [t for t in _MOCK_INVOICE_TEMPLATES if t["id"] != template_id]
            return len(_MOCK_INVOICE_TEMPLATES) < before
        _svc().table("invoice_templates").delete().eq("id", template_id).execute()
        return True

    # ── email_templates ───────────────────────────────────────────────────────

    def list_email_templates(self, firm_id: str) -> list[dict]:
        if _USE_MOCK:
            return [t for t in _MOCK_EMAIL_TEMPLATES if t["firm_id"] == firm_id]
        r = _get_db().table("email_templates").select("*").eq("firm_id", firm_id).order("template_type").execute()
        return r.data or []

    def get_email_template(self, template_id: str) -> Optional[dict]:
        if _USE_MOCK:
            return next((t for t in _MOCK_EMAIL_TEMPLATES if t["id"] == template_id), None)
        r = _get_db().table("email_templates").select("*").eq("id", template_id).maybe_single().execute()
        return r.data

    def upsert_email_template(self, firm_id: str, template_type: str, data: dict) -> dict:
        """Create or replace the active template for the given type."""
        if _USE_MOCK:
            existing = next(
                (t for t in _MOCK_EMAIL_TEMPLATES if t["firm_id"] == firm_id and t["template_type"] == template_type),
                None,
            )
            if existing:
                existing.update({**data, "updated_at": self.now_iso()})
                return existing
            record = {
                "id": str(uuid.uuid4()),
                "firm_id": firm_id,
                "template_type": template_type,
                "is_active": True,
                **data,
                "created_at": self.now_iso(),
                "updated_at": self.now_iso(),
            }
            _MOCK_EMAIL_TEMPLATES.append(record)
            return record
        # Upsert on (firm_id, template_type) — unique constraint exists when is_active=true
        # Use service role to bypass RLS for this write
        r = _svc().table("email_templates").upsert(
            {"firm_id": firm_id, "template_type": template_type, **data, "updated_at": self.now_iso()},
            on_conflict="firm_id,template_type",
        ).execute()
        return r.data[0]

    def update_email_template(self, template_id: str, data: dict) -> Optional[dict]:
        if _USE_MOCK:
            t = next((t for t in _MOCK_EMAIL_TEMPLATES if t["id"] == template_id), None)
            if not t:
                return None
            t.update({**data, "updated_at": self.now_iso()})
            return t
        r = _svc().table("email_templates").update({**data, "updated_at": self.now_iso()}).eq("id", template_id).execute()
        return r.data[0] if r.data else None

    def delete_email_template(self, template_id: str) -> bool:
        if _USE_MOCK:
            before = len(_MOCK_EMAIL_TEMPLATES)
            _MOCK_EMAIL_TEMPLATES[:] = [t for t in _MOCK_EMAIL_TEMPLATES if t["id"] != template_id]
            return len(_MOCK_EMAIL_TEMPLATES) < before
        _svc().table("email_templates").delete().eq("id", template_id).execute()
        return True


branding_repo = BrandingRepository()
