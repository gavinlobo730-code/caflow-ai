"""
Pydantic request models for customer and vendor (party) endpoints.
CGST Act §25: GSTIN format validation.
IT Act §139A: PAN format validation.
IT Act §203A: TAN format validation — on CUSTOMERS only. A customer's TAN is
the number it quotes when IT deducts tax on what it pays the client, and Form
26AS names a deductor by TAN and nothing else. Vendors do not carry one: there
the client is the deductor, and its 26Q return reports the vendor's PAN.
"""
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional
from core.validators import (validate_gstin, validate_pan, validate_tan,
                             validate_phone, validate_email, validate_pincode)


class CustomerIn(BaseModel):
    client_id: str
    name: str
    gstin: Optional[str] = None
    pan: Optional[str] = None
    # IT Act §203A. Set when this customer DEDUCTS tax on what it pays the
    # client. Form 26AS names deductors by TAN and nothing else, so without it
    # the 26AS reconciliation can only match on company name and must ask a
    # human to confirm. A TAN cannot be derived from a PAN — it has to be typed.
    tan: Optional[str] = None
    state_code: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    opening_balance_paise: int = 0
    opening_balance_date: Optional[str] = None
    # Must match the customers.credit_days DB column default (migration 049) —
    # model_dump() always includes this field (Pydantic has no way to
    # distinguish "caller omitted it" from "caller sent the default"), so any
    # caller that omits credit_days writes this literal value, silently
    # overriding the DB's own DEFAULT. See VendorIn.credit_days for the
    # identical bug that left every existing vendor at 0 instead of 30.
    credit_days: int = 30

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Customer name cannot be blank.")
        return v

    @model_validator(mode="after")
    def validate_identifiers(self) -> "CustomerIn":
        errors = []
        if self.gstin:
            # CGST Act §25: GSTIN is canonically uppercase — normalize what's
            # stored to what's validated, so a lowercase-typed GSTIN doesn't
            # persist in a form that mismatches every other case-normalized
            # comparison/display of the same value.
            self.gstin = self.gstin.strip().upper()
            err = validate_gstin(self.gstin)
            if err:
                errors.append(err)
            elif self.state_code and self.gstin[:2] != self.state_code:
                errors.append(f"GSTIN state code '{self.gstin[:2]}' does not match state_code '{self.state_code}'.")
        if self.pan:
            # IT Act §139A: PAN is canonically uppercase — same normalization
            # as GSTIN above.
            self.pan = self.pan.strip().upper()
            err = validate_pan(self.pan)
            if err:
                errors.append(err)
        if self.tan:
            # IT Act §203A: TAN is canonically uppercase, same as the two above.
            self.tan = self.tan.strip().upper()
            err = validate_tan(self.tan)
            if err:
                errors.append(err)
        if self.email:
            err = validate_email(self.email)
            if err:
                errors.append(err)
        if self.phone:
            err = validate_phone(self.phone)
            if err:
                errors.append(err)
        if self.pincode:
            err = validate_pincode(self.pincode)
            if err:
                errors.append(err)
        if errors:
            raise ValueError("; ".join(errors))
        return self


class CustomerUpdateIn(BaseModel):
    name: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    tan: Optional[str] = None          # IT Act §203A — see CustomerIn.tan
    state_code: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    opening_balance_paise: Optional[int] = None
    opening_balance_date: Optional[str] = None
    credit_days: Optional[int] = None
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def validate_identifiers(self) -> "CustomerUpdateIn":
        errors = []
        if self.gstin:
            # CGST Act §25: GSTIN is canonically uppercase — normalize what's
            # stored to what's validated, so a lowercase-typed GSTIN doesn't
            # persist in a form that mismatches every other case-normalized
            # comparison/display of the same value.
            self.gstin = self.gstin.strip().upper()
            err = validate_gstin(self.gstin)
            if err:
                errors.append(err)
        if self.pan:
            # IT Act §139A: PAN is canonically uppercase — same normalization
            # as GSTIN above.
            self.pan = self.pan.strip().upper()
            err = validate_pan(self.pan)
            if err:
                errors.append(err)
        if self.tan:
            # IT Act §203A: TAN is canonically uppercase, same as the two above.
            self.tan = self.tan.strip().upper()
            err = validate_tan(self.tan)
            if err:
                errors.append(err)
        if self.email:
            err = validate_email(self.email)
            if err:
                errors.append(err)
        if self.phone:
            err = validate_phone(self.phone)
            if err:
                errors.append(err)
        if self.pincode:
            err = validate_pincode(self.pincode)
            if err:
                errors.append(err)
        if errors:
            raise ValueError("; ".join(errors))
        return self


class VendorIn(BaseModel):
    client_id: str
    name: str
    gstin: Optional[str] = None
    pan: Optional[str] = None
    state_code: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    opening_balance_paise: int = 0
    opening_balance_date: Optional[str] = None
    # Optional — genuinely unset ("no payment terms confirmed for this
    # vendor yet") is a different fact from 0 ("Due on Receipt", a real
    # choice a CA can make). BUG FOUND LIVE (migration 202): this used to
    # default to 0 with a non-Optional int, and create_vendor/
    # create_vendors_bulk call model_dump() with no exclusion — Pydantic
    # always emits every field, so any caller that didn't explicitly set
    # credit_days silently wrote 0, which every existing vendor's row had
    # baked in despite the Payment Terms UI never having offered a way to
    # choose it. No default is assumed here or anywhere downstream
    # (PurchaseBillEditor only auto-fills Payment Terms/Due Date on vendor
    # pick when credit_days is not None; services/credit_terms.py still
    # falls back to 30 days ONLY at the point a bill is actually created
    # with no term specified anywhere, purely so the bill itself has a
    # trackable due date — that fallback does not get written back onto
    # the vendor).
    credit_days: Optional[int] = None
    tds_applicable: bool = False
    tds_section: Optional[str] = None
    tds_rate_bps: int = 0

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Vendor name cannot be blank.")
        return v

    @model_validator(mode="after")
    def validate_identifiers(self) -> "VendorIn":
        errors = []
        if self.gstin:
            # CGST Act §25: GSTIN is canonically uppercase — normalize what's
            # stored to what's validated, so a lowercase-typed GSTIN doesn't
            # persist in a form that mismatches every other case-normalized
            # comparison/display of the same value.
            self.gstin = self.gstin.strip().upper()
            err = validate_gstin(self.gstin)
            if err:
                errors.append(err)
            elif self.state_code and self.gstin[:2] != self.state_code:
                errors.append(f"GSTIN state code '{self.gstin[:2]}' does not match state_code '{self.state_code}'.")
        if self.pan:
            # IT Act §139A: PAN is canonically uppercase — same normalization
            # as GSTIN above.
            self.pan = self.pan.strip().upper()
            err = validate_pan(self.pan)
            if err:
                errors.append(err)
        if self.email:
            err = validate_email(self.email)
            if err:
                errors.append(err)
        if self.phone:
            err = validate_phone(self.phone)
            if err:
                errors.append(err)
        if self.pincode:
            err = validate_pincode(self.pincode)
            if err:
                errors.append(err)
        if errors:
            raise ValueError("; ".join(errors))
        return self


class VendorUpdateIn(BaseModel):
    name: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    state_code: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    opening_balance_paise: Optional[int] = None
    opening_balance_date: Optional[str] = None
    credit_days: Optional[int] = None
    tds_applicable: Optional[bool] = None
    tds_section: Optional[str] = None
    tds_rate_bps: Optional[int] = None
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def validate_identifiers(self) -> "VendorUpdateIn":
        errors = []
        if self.gstin:
            # CGST Act §25: GSTIN is canonically uppercase — normalize what's
            # stored to what's validated, so a lowercase-typed GSTIN doesn't
            # persist in a form that mismatches every other case-normalized
            # comparison/display of the same value.
            self.gstin = self.gstin.strip().upper()
            err = validate_gstin(self.gstin)
            if err:
                errors.append(err)
        if self.pan:
            # IT Act §139A: PAN is canonically uppercase — same normalization
            # as GSTIN above.
            self.pan = self.pan.strip().upper()
            err = validate_pan(self.pan)
            if err:
                errors.append(err)
        if self.email:
            err = validate_email(self.email)
            if err:
                errors.append(err)
        if self.phone:
            err = validate_phone(self.phone)
            if err:
                errors.append(err)
        if self.pincode:
            err = validate_pincode(self.pincode)
            if err:
                errors.append(err)
        if errors:
            raise ValueError("; ".join(errors))
        return self
