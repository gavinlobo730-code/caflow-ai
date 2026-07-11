"""
Manual stock adjustment — physical count correction, damage, theft,
destruction, or free samples given away. The only inventory movement not
already driven by a sales invoice / purchase bill / credit note / debit
note (routers/inventory.py: POST /items/{id}/adjust).

CGST Act §17(5)(h): input tax credit must be reversed for goods lost,
stolen, destroyed, written off, or disposed of by way of gift or free
samples. That does NOT apply to a favourable physical-count surplus (stock
found, not lost) — reverse_itc is only meaningful when direction="decrease".
Whether a given write-off actually falls under §17(5)(h) is a judgment call
only the CA can make (e.g. damaged stock might still be sold at a discount
rather than written off) — this model never infers reverse_itc from reason;
the caller (the Inventory tab's adjustment form) suggests a default per
reason and always sends the CA-confirmed value explicitly.
"""
from pydantic import BaseModel, field_validator
from typing import Optional

ADJUSTMENT_REASONS = {
    "physical_count_shortage",
    "physical_count_surplus",
    "damage",
    "theft_loss",
    "destroyed",
    "free_sample",
    "other",
}


class StockAdjustmentIn(BaseModel):
    client_id: str
    adjustment_date: str  # YYYY-MM-DD
    quantity: float
    direction: str  # "increase" | "decrease"
    reason: str
    # CA-confirmed — only meaningful (and only ever applied) when
    # direction="decrease". CGST Act §17(5)(h).
    reverse_itc: bool = False
    reference_no: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("quantity")
    @classmethod
    def positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Adjustment quantity must be positive.")
        return v

    @field_validator("direction")
    @classmethod
    def valid_direction(cls, v: str) -> str:
        if v not in ("increase", "decrease"):
            raise ValueError("direction must be 'increase' or 'decrease'.")
        return v

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, v: str) -> str:
        if v not in ADJUSTMENT_REASONS:
            raise ValueError(f"reason must be one of {sorted(ADJUSTMENT_REASONS)}.")
        return v
