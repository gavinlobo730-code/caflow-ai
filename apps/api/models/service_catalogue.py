"""
Pydantic request models for the Service Catalogue (Sales-Invoice Batch 6).

A services-only billing preset — NOT an inventory item. There are deliberately
no stock/valuation/quantity fields; the catalogue only stores the defaults the
invoice editor drops onto a line (all still CA-editable afterwards).
"""
from pydantic import BaseModel, field_validator
from typing import Optional


class ServiceCatalogueIn(BaseModel):
    name: str
    description: Optional[str] = None
    hsn_sac: Optional[str] = None
    gst_rate_bps: Optional[int] = 1800          # default 18%; hint only, never used in tax math
    default_rate_paise: int = 0                 # integer paise (money rule); 0 = no default price
    unit: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Service name cannot be blank.")
        return v

    @field_validator("gst_rate_bps")
    @classmethod
    def gst_rate_in_range(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if v < 0 or v > 10000:
            raise ValueError("GST rate must be between 0% and 100% (0–10000 bps).")
        return v

    @field_validator("default_rate_paise")
    @classmethod
    def rate_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Default rate cannot be negative.")
        return v


class ServiceCatalogueUpdateIn(BaseModel):
    """Partial edit. Any field left None is untouched; `is_active` toggles
    archive (false) / restore (true)."""
    name: Optional[str] = None
    description: Optional[str] = None
    hsn_sac: Optional[str] = None
    gst_rate_bps: Optional[int] = None
    default_rate_paise: Optional[int] = None
    unit: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Service name cannot be blank.")
        return v

    @field_validator("gst_rate_bps")
    @classmethod
    def gst_rate_in_range(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if v < 0 or v > 10000:
            raise ValueError("GST rate must be between 0% and 100% (0–10000 bps).")
        return v

    @field_validator("default_rate_paise")
    @classmethod
    def rate_non_negative(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("Default rate cannot be negative.")
        return v
