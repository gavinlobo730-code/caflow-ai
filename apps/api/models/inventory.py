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
    # WHICH HEADS the reversed credit was taken under. A write-off is not a
    # supply, so nothing about it says whether the original purchase was IGST
    # or CGST+SGST — that is a fact about the PURCHASE, and stock of one item
    # can have come from both. Defaults to intra-state, which is the ordinary
    # case for stock a client holds; the total reversed is the same either way
    # and only the split on GSTR-3B Table 4(B)(1) differs. The register row
    # records which way it went, so a CA sees it rather than finding it at the
    # portal.
    itc_reversal_is_interstate: bool = False
    reference_no: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("quantity")
    @classmethod
    def positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Adjustment quantity must be positive.")
        # Three decimals, because that is what NUMERIC(10,3) keeps and the money
        # is computed from what was TYPED — see domain/quantity.py (INV-09).
        from domain.quantity import quantity_violation
        problem = quantity_violation(v)
        if problem:
            raise ValueError(problem)
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


class NrvWritedownIn(BaseModel):
    """Write inventory down to net realisable value (routers/inventory.py:
    POST /items/{id}/writedown). AS-2 / Ind AS 2 / ICDS-II require
    inventory to be carried at the LOWER of cost or net realisable value —
    a value-only correction, quantity never changes. A no-op if the
    supplied NRV is already >= the current moving-average cost (inventory
    stays at cost, the normal case)."""
    client_id: str
    writedown_date: str  # YYYY-MM-DD
    nrv_per_unit_paise: int
    reference_no: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("nrv_per_unit_paise")
    @classmethod
    def non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("nrv_per_unit_paise must be non-negative.")
        return v
