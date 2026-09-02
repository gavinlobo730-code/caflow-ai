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
from domain.tds.residency import NON_RESIDENT, RESIDENTIAL_STATUSES


def _normalise_residency(model) -> list[str]:
    """Validate and canonicalise a vendor's residency fields IN PLACE.

    Shared by VendorIn and VendorUpdateIn, which validate the same three
    columns and must not drift: a create path that accepts "NonResident" and an
    update path that rejects it would let the value in by one door and make it
    uneditable through the other. Returns the errors it found, so each model
    keeps its own single "; ".join(errors) report.

    Requires the COUNTRY when a vendor is marked non-resident, and does not
    require the TIN. Both are on Form 27Q, but the country is knowable the
    moment you decide someone is a non-resident, and a 27Q cannot be filed
    without it; the TIN is only mandatory where the deductee has no PAN, and it
    is the sort of thing a CA chases the supplier for. So the country is a
    refusal here and the missing TIN is a gap reported later —
    domain/tds/residency.missing_27q_identifiers is what reports it.
    """
    errors: list[str] = []

    if model.residential_status is not None:
        model.residential_status = model.residential_status.strip().lower()
        if model.residential_status not in RESIDENTIAL_STATUSES:
            errors.append(
                "residential_status must be 'resident' or 'non_resident' "
                f"(got '{model.residential_status}'). Leave it unset if nobody "
                "has established which — that is a different fact from either.")

    if model.country_of_residence is not None:
        # ISO 3166-1 alpha-2, which is the code Form 27Q takes. Uppercased
        # here for the same reason GSTIN and PAN are: what is stored has to
        # match what was validated, and the DB CHECK is ^[A-Z]{2}$.
        model.country_of_residence = model.country_of_residence.strip().upper()
        if not (len(model.country_of_residence) == 2
                and model.country_of_residence.isalpha()):
            errors.append(
                "country_of_residence must be a 2-letter ISO 3166-1 alpha-2 "
                f"code such as AE, SG or US (got '{model.country_of_residence}').")

    if model.tax_identification_number is not None:
        # No format check: a TIN's shape is whatever the payee's own country
        # says it is, and there are over ninety of them. Only whitespace is
        # normalised, so a trailing space cannot make two TINs look different.
        model.tax_identification_number = model.tax_identification_number.strip() or None

    if model.residential_status == NON_RESIDENT and not model.country_of_residence:
        errors.append(
            "A non-resident vendor needs a country_of_residence — Form 27Q "
            "reports it on every deductee row, and Rule 37BC's relief from the "
            "s.206AA 20% floor is conditional on holding it.")

    return errors


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
    # IT Act residential status of the PAYEE. NULL is a real third state —
    # "nobody has said" — and is treated as resident for computation while
    # being reported as a gap. It decides the charging section as well as the
    # quarterly statement: s.194C and its neighbours charge only payments "to a
    # resident", so a non-resident payee falls under s.195 instead.
    # domain/tds/residency.py is the authority.
    residential_status: Optional[str] = None
    country_of_residence: Optional[str] = None
    tax_identification_number: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Vendor name cannot be blank.")
        return v

    @model_validator(mode="after")
    def validate_identifiers(self) -> "VendorIn":
        errors = _normalise_residency(self)
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
    residential_status: Optional[str] = None
    country_of_residence: Optional[str] = None
    tax_identification_number: Optional[str] = None
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def validate_identifiers(self) -> "VendorUpdateIn":
        errors = _normalise_residency(self)
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
