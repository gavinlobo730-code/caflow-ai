"""
Pydantic request models for the Product & Service master (Sales-Invoice Batch
6; broadened to goods in the HSN/SAC architecture redesign, migration 180;
made client-owned in migration 182 — "Client B must never inherit Client A's
products"; given real stock/valuation tracking for kind='good' items in
migration 188 — see domain/inventory_service.py).

A billing preset for goods AND services. The catalogue stores the defaults
the invoice editor drops onto a line (all still CA-editable afterwards) PLUS,
for kind='good' items only, an opening stock balance and the current
moving-average cost. `hsn_sac`, when provided, must be a code from the
firm's own `firm_hsn_library` (the firm-wide shared library — a Product/
Service is client-owned, but the HSN/SAC it references still comes from the
one library shared across the firm's clients) — checked by the router (not
here), since that check needs a DB read.
"""
from pydantic import BaseModel, field_validator
from typing import Optional


class ServiceCatalogueIn(BaseModel):
    client_id: str
    name: str
    description: Optional[str] = None
    kind: str = "service"                       # 'good' | 'service'
    hsn_sac: Optional[str] = None                # must exist in the firm's firm_hsn_library
    gst_rate_bps: Optional[int] = 1800          # default 18%; hint only, never used in tax math
    default_rate_paise: int = 0                 # integer paise (money rule); 0 = no default price
    purchase_price_paise: Optional[int] = None   # optional; integer paise
    unit: Optional[str] = None                   # official CBIC UQC code — goods only
    category: Optional[str] = None
    notes: Optional[str] = None
    # Opening stock balance — goods only, meaningless for services. Seeds the
    # moving-average costing ledger (domain/inventory_service.seed_opening_balance).
    opening_qty_units: Optional[float] = None
    opening_cost_paise: Optional[int] = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Product/service name cannot be blank.")
        return v

    @field_validator("kind")
    @classmethod
    def kind_valid(cls, v: str) -> str:
        if v not in ("good", "service"):
            raise ValueError("kind must be 'good' or 'service'.")
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

    @field_validator("purchase_price_paise")
    @classmethod
    def purchase_price_non_negative(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("Purchase price cannot be negative.")
        return v

    @field_validator("unit")
    @classmethod
    def normalize_unit(cls, v: Optional[str]) -> Optional[str]:
        # Normalize only — do NOT reject values outside VALID_UQC_CODES. An
        # existing product/service may carry a pre-UQC-dropdown free-text
        # value; rejecting it would make the row un-editable for any
        # unrelated field change. The new UI's dropdown only offers valid
        # UQC codes, so new/changed unit values are compliant by construction.
        if v is None or v == "":
            return None
        return v.strip().upper()

    @field_validator("opening_qty_units")
    @classmethod
    def opening_qty_non_negative(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("Opening quantity cannot be negative.")
        return v

    @field_validator("opening_cost_paise")
    @classmethod
    def opening_cost_non_negative(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("Opening cost cannot be negative.")
        return v


class ServiceCatalogueUpdateIn(BaseModel):
    """Partial edit. Any field left None is untouched; `is_active` toggles
    archive (false) / restore (true). `kind` is immutable after creation —
    archive and re-create instead."""
    name: Optional[str] = None
    description: Optional[str] = None
    hsn_sac: Optional[str] = None
    gst_rate_bps: Optional[int] = None
    default_rate_paise: Optional[int] = None
    purchase_price_paise: Optional[int] = None
    unit: Optional[str] = None
    category: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None
    opening_qty_units: Optional[float] = None
    opening_cost_paise: Optional[int] = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Product/service name cannot be blank.")
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

    @field_validator("purchase_price_paise")
    @classmethod
    def purchase_price_non_negative(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("Purchase price cannot be negative.")
        return v

    @field_validator("unit")
    @classmethod
    def normalize_unit(cls, v: Optional[str]) -> Optional[str]:
        # Normalize only — do NOT reject values outside VALID_UQC_CODES. An
        # existing product/service may carry a pre-UQC-dropdown free-text
        # value; rejecting it would make the row un-editable for any
        # unrelated field change. The new UI's dropdown only offers valid
        # UQC codes, so new/changed unit values are compliant by construction.
        if v is None or v == "":
            return None
        return v.strip().upper()

    @field_validator("opening_qty_units")
    @classmethod
    def opening_qty_non_negative(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("Opening quantity cannot be negative.")
        return v

    @field_validator("opening_cost_paise")
    @classmethod
    def opening_cost_non_negative(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("Opening cost cannot be negative.")
        return v
