"""
Pydantic request models for the Firm HSN/SAC Library (HSN/SAC architecture
redesign, Phase 2).

The library is CA-owned and CA-curated. Caflow performs no classification —
these validators only check STRUCTURAL shape (non-blank, digits, plausible
length), never whether a code is "correct" for a given good/service. That
judgement stays with the CA, per the architecture decision that Caflow does
not decide or suggest HSN/SAC classifications.
"""
import re
from typing import Optional

from pydantic import BaseModel, field_validator

_CODE_RE = re.compile(r"^\d{2,8}$")


class FirmHsnLibraryIn(BaseModel):
    hsn_code: str
    description: str
    hsn_type: str                                # 'goods' | 'services'
    gst_rate_pct: Optional[float] = None          # CA-entered hint; never used in tax math
    uqc: Optional[str] = None
    notes: Optional[str] = None
    source: str = "manual"                        # 'manual' | 'import'

    @field_validator("hsn_code")
    @classmethod
    def code_shape(cls, v: str) -> str:
        v = (v or "").strip()
        if not _CODE_RE.match(v):
            raise ValueError("HSN/SAC code must be 2-8 digits.")
        return v

    @field_validator("description")
    @classmethod
    def description_not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Description cannot be blank.")
        return v

    @field_validator("hsn_type")
    @classmethod
    def type_valid(cls, v: str) -> str:
        if v not in ("goods", "services"):
            raise ValueError("hsn_type must be 'goods' or 'services'.")
        return v

    @field_validator("gst_rate_pct")
    @classmethod
    def rate_in_range(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        if v < 0 or v > 100:
            raise ValueError("GST rate must be between 0 and 100.")
        return v

    @field_validator("source")
    @classmethod
    def source_valid(cls, v: str) -> str:
        if v not in ("manual", "import"):
            raise ValueError("source must be 'manual' or 'import'.")
        return v


class FirmHsnLibraryUpdateIn(BaseModel):
    """Partial edit. Any field left None is untouched; `is_active` toggles
    retire (false) / restore (true). hsn_code and hsn_type are immutable
    after creation — retire the row and add a new one instead."""
    description: Optional[str] = None
    gst_rate_pct: Optional[float] = None
    uqc: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("description")
    @classmethod
    def description_not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Description cannot be blank.")
        return v

    @field_validator("gst_rate_pct")
    @classmethod
    def rate_in_range(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        if v < 0 or v > 100:
            raise ValueError("GST rate must be between 0 and 100.")
        return v
