"""Request models for the purchase cycle BEFORE the bill (PUR-25).

Validated at BOTH doors — create and update — because a validator on one door
is one PATCH away from being none, which is the shape ACC-25 and GST-29 both
turned out to be.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from domain.gst.gstin import problem_with
from domain.gst.validator import VALID_STATE_CODES
from domain.purchases import order_cycle as oc
from domain.quantity import quantity_violation

#: A purchase order and a goods receipt are INTERNAL documents — neither is
#: issued to anybody outside the client's own business — so CGST Rule 46(b)'s
#: sixteen characters do not reach either. Thirty-two is the column, and the
#: model states the same limit so a CA gets a sentence rather than a 500.
MAX_DOCUMENT_NO = 32


def _document_no(v: str) -> str:
    v = (v or "").strip()
    if not v:
        raise ValueError("The document number cannot be blank.")
    if len(v) > MAX_DOCUMENT_NO:
        raise ValueError(
            f"A document number is at most {MAX_DOCUMENT_NO} characters.")
    return v


def _state(v):
    if v is None or v == "":
        return None
    code = str(v).strip()
    if code not in VALID_STATE_CODES:
        raise ValueError(
            f"{code!r} is not a state code. The place of supply is a two-digit "
            f"state code (CGST s.25 and the IGST Act's own list).")
    return code


def _gstin(v):
    """The VENDOR's GSTIN, check digit and all.

    GST-29's lesson on the purchase side: a valid-SHAPED wrong GSTIN is why a
    bill sits in "missing in 2B" for ever while the CA chases the wrong party.
    A purchase order's GSTIN becomes the bill's, so it is checked here.
    """
    if v is None or v == "":
        return None
    problem = problem_with(str(v).strip().upper())
    if problem:
        raise ValueError(problem)
    return str(v).strip().upper()


class PurchaseOrderLineIn(BaseModel):
    """One line of a purchase order.

    `itc_eligible`, `expense_account_id` and `tds_applicable` are here because
    they are decisions the CA makes ONCE — the same reasoning migration 379's
    recurring template records. Defaulting them when the order is billed would
    re-decide CGST s.17(5) every month.
    """
    model_config = ConfigDict(from_attributes=True)

    description: str
    hsn_sac: Optional[str] = None
    quantity: float = 1.0
    unit: Optional[str] = None
    rate_paise: int = 0
    gst_rate_percent: float = 18.0

    @field_validator("gst_rate_percent")
    @classmethod
    def _gst_rate_is_a_rate(cls, v: float) -> float:
        """Delegates to `domain/gst/rate_bounds` — one level of indirection, the
        shape `models/invoices._validate_quantity` already uses, so the rule
        lives once and a reader here is pointed at it."""
        from domain.gst.rate_bounds import rate_percent_violation
        problem = rate_percent_violation(v)
        if problem:
            raise ValueError(problem)
        return v
    is_service: bool = False
    service_catalogue_id: Optional[str] = None
    expense_account_id: Optional[str] = None
    itc_eligible: bool = True
    blocked_credit_reason: Optional[str] = None
    tds_applicable: bool = False
    cess_rate_bps: Optional[int] = None
    cess_specific_paise_per_unit: Optional[int] = None

    @field_validator("description")
    @classmethod
    def _described(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("Every line needs a description.")
        return v.strip()

    @field_validator("quantity")
    @classmethod
    def _qty(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("quantity must be positive.")
        problem = quantity_violation(v)
        if problem:
            raise ValueError(problem)
        return v

    @field_validator("rate_paise")
    @classmethod
    def _rate(cls, v: int) -> int:
        if v < 0:
            raise ValueError("rate_paise must be non-negative.")
        return v

    @field_validator("cess_rate_bps", "cess_specific_paise_per_unit")
    @classmethod
    def _non_negative(cls, v):
        if v is not None and v < 0:
            raise ValueError("A compensation cess rate cannot be negative.")
        return v


class GoodsReceiptLineIn(BaseModel):
    """One line of a goods receipt.

    `rejected_qty` is a SEPARATE figure rather than a smaller `quantity`,
    because CGST s.16(2)(b) asks what was RECEIVED and MSMED s.2(b) asks what
    was ACCEPTED, and one number cannot answer both.
    """
    model_config = ConfigDict(from_attributes=True)

    description: str
    hsn_sac: Optional[str] = None
    quantity: float = 1.0
    unit: Optional[str] = None
    rejected_qty: float = 0.0
    rejection_reason: Optional[str] = None
    service_catalogue_id: Optional[str] = None
    order_line_id: Optional[str] = None

    @field_validator("description")
    @classmethod
    def _described(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("Every line needs a description.")
        return v.strip()

    @field_validator("quantity")
    @classmethod
    def _qty(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("quantity must be positive.")
        problem = quantity_violation(v)
        if problem:
            raise ValueError(problem)
        return v

    @field_validator("rejected_qty")
    @classmethod
    def _rejected(cls, v: float) -> float:
        if v < 0:
            raise ValueError("rejected_qty cannot be negative.")
        problem = quantity_violation(v)
        if problem:
            raise ValueError(problem)
        return v

    @model_validator(mode="after")
    def _rejected_within_received(self):
        if self.rejected_qty > self.quantity:
            raise ValueError(
                f"{self.description}: more was rejected than arrived — "
                f"{self.rejected_qty} of {self.quantity}.")
        return self


class PurchaseOrderIn(BaseModel):
    """A commitment to buy. Posts no journal and moves no stock."""
    client_id: str
    vendor_id: str
    document_no: str
    document_date: str
    expected_date: Optional[str] = None
    vendor_name: Optional[str] = None
    vendor_gstin: Optional[str] = None
    place_of_supply: Optional[str] = None
    is_inter_state: bool = False
    currency: Optional[str] = None
    notes: Optional[str] = None
    lines: list = []

    @field_validator("document_no")
    @classmethod
    def _no(cls, v: str) -> str:
        return _document_no(v)

    @field_validator("place_of_supply")
    @classmethod
    def _pos(cls, v):
        return _state(v)

    @field_validator("vendor_gstin")
    @classmethod
    def _gst(cls, v):
        return _gstin(v)

    @model_validator(mode="after")
    def _has_lines(self):
        if not self.lines:
            raise ValueError("A purchase order needs at least one line.")
        return self


class PurchaseOrderUpdateIn(BaseModel):
    """Amend a purchase order. `None` means unchanged.

    `client_id`, `vendor_id` and `currency` are absent on purpose and recorded
    in the editability guard's immutable map with their reasons.
    """
    document_no: Optional[str] = None
    document_date: Optional[str] = None
    expected_date: Optional[str] = None
    status: Optional[str] = None
    vendor_name: Optional[str] = None
    vendor_gstin: Optional[str] = None
    place_of_supply: Optional[str] = None
    is_inter_state: Optional[bool] = None
    notes: Optional[str] = None
    lines: Optional[list] = None

    @field_validator("document_no")
    @classmethod
    def _no(cls, v):
        return _document_no(v) if v is not None else None

    @field_validator("place_of_supply")
    @classmethod
    def _pos(cls, v):
        return _state(v)

    @field_validator("vendor_gstin")
    @classmethod
    def _gst(cls, v):
        return _gstin(v)

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v is None:
            return None
        if v not in oc.ORDER_STATUSES:
            raise ValueError(f"status must be one of {', '.join(oc.ORDER_STATUSES)}.")
        return v


class GoodsReceiptIn(BaseModel):
    """When the goods arrived — the fact CGST s.16(2)(b) and MSMED s.2(b) turn
    on."""
    client_id: str
    vendor_id: str
    document_no: str
    received_on: str
    order_id: Optional[str] = None
    objection_raised_on: Optional[str] = None
    objection_removed_on: Optional[str] = None
    vendor_name: Optional[str] = None
    vendor_challan_no: Optional[str] = None
    vendor_challan_date: Optional[str] = None
    transporter_name: Optional[str] = None
    vehicle_no: Optional[str] = None
    notes: Optional[str] = None
    lines: list = []

    @field_validator("document_no")
    @classmethod
    def _no(cls, v: str) -> str:
        return _document_no(v)

    @model_validator(mode="after")
    def _shape(self):
        if not self.lines:
            raise ValueError("A goods receipt needs at least one line.")
        # The database CHECKs this too; refusing here gives the CA the
        # sentence instead of a constraint-violation 500, and states the rule
        # where a reader of the model can see it.
        if self.objection_removed_on and not self.objection_raised_on:
            raise ValueError(
                "MSMED s.2(b)'s Explanation runs the clock from the day an "
                "objection was REMOVED, so there has to be an objection. "
                "Record when it was raised.")
        if (self.objection_removed_on and self.objection_raised_on
                and self.objection_removed_on < self.objection_raised_on):
            raise ValueError(
                "An objection cannot be removed before it was raised.")
        return self


class GoodsReceiptUpdateIn(BaseModel):
    """Amend a goods receipt. `client_id`, `vendor_id` and `order_id` are
    absent on purpose — see the editability guard's immutable map."""
    document_no: Optional[str] = None
    received_on: Optional[str] = None
    status: Optional[str] = None
    objection_raised_on: Optional[str] = None
    objection_removed_on: Optional[str] = None
    vendor_name: Optional[str] = None
    vendor_challan_no: Optional[str] = None
    vendor_challan_date: Optional[str] = None
    transporter_name: Optional[str] = None
    vehicle_no: Optional[str] = None
    notes: Optional[str] = None
    lines: Optional[list] = None

    @field_validator("document_no")
    @classmethod
    def _no(cls, v):
        return _document_no(v) if v is not None else None

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v is None:
            return None
        if v not in oc.GRN_STATUSES:
            raise ValueError(f"status must be one of {', '.join(oc.GRN_STATUSES)}.")
        return v

    @model_validator(mode="after")
    def _objection_order(self):
        if (self.objection_removed_on and self.objection_raised_on
                and self.objection_removed_on < self.objection_raised_on):
            raise ValueError(
                "An objection cannot be removed before it was raised.")
        return self
