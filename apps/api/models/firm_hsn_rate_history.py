"""
Pydantic request models for the Firm HSN/SAC Rate History (Decision D:
per-firm-owned rate history — Caflow ships the mechanism, never an
authoritative rate; every row is CA-entered).
"""
from datetime import date
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator

_SUPPLY_TYPES = ("taxable", "exempt", "nil", "non_gst")


class FirmHsnRateHistoryIn(BaseModel):
    firm_hsn_library_id: str
    gst_rate_pct: float
    cess_rate_pct: Optional[float] = None
    cess_specific_paise_per_unit: Optional[int] = None
    supply_type: str = "taxable"
    effective_from: date
    effective_to: Optional[date] = None
    notes: Optional[str] = None

    @field_validator("gst_rate_pct", "cess_rate_pct")
    @classmethod
    def pct_in_range(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        if v < 0 or v > 100:
            raise ValueError("Rate must be between 0 and 100.")
        return v

    @field_validator("cess_specific_paise_per_unit")
    @classmethod
    def cess_specific_nonneg(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("Specific cess cannot be negative.")
        return v

    @field_validator("supply_type")
    @classmethod
    def supply_type_valid(cls, v: str) -> str:
        if v not in _SUPPLY_TYPES:
            raise ValueError(f"supply_type must be one of {_SUPPLY_TYPES}.")
        return v

    @model_validator(mode="after")
    def date_order(self) -> "FirmHsnRateHistoryIn":
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot be before effective_from.")
        return self
