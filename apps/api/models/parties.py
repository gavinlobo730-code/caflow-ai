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
from domain.tds.section_195_rates import ALL_PAYEE_CLASSES
from domain.tds.residency import (NON_RESIDENT, RESIDENTIAL_STATUSES,
                                  deduction_section_refusal, section_refusal)
from domain.tds.section_195_rates import (
    ALL_NATURES, NATURE_BUSINESS_PROFITS_NO_PE)


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

    # CGST Act s.31(3)(f). Normalised and validated HERE rather than in its own
    # helper for the reason this function exists: a create path that accepts
    # "Unregistered" and an update path that rejects it lets the value in by one
    # door and makes it uneditable through the other.
    status = getattr(model, "gst_registration_status", None)
    if status is not None:
        model.gst_registration_status = str(status).strip().lower()
        from domain.gst.rcm_documents import REGISTERED, UNREGISTERED, UNRECORDED
        if model.gst_registration_status not in (REGISTERED, UNREGISTERED):
            hint = (" `unrecorded` is the ABSENCE of a value, so leave it unset"
                    if model.gst_registration_status == UNRECORDED else
                    " Leave it unset if nobody has established which — that is a"
                    " different fact from either.")
            errors.append(
                f"gst_registration_status must be '{REGISTERED}' or "
                f"'{UNREGISTERED}' (got '{model.gst_registration_status}')."
                + hint)

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

    if model.non_resident_payee_class is not None:
        model.non_resident_payee_class = (
            model.non_resident_payee_class.strip().lower() or None)
        if (model.non_resident_payee_class is not None
                and model.non_resident_payee_class not in ALL_PAYEE_CLASSES):
            errors.append(
                "non_resident_payee_class must be one of: "
                + ", ".join(ALL_PAYEE_CLASSES)
                + f" (got '{model.non_resident_payee_class}'). It decides which "
                  "Part II First Schedule surcharge ladder a s.195 withholding "
                  "takes, and the ladders differ by a wide margin.")

    if model.tax_identification_number is not None:
        # No format check: a TIN's shape is whatever the payee's own country
        # says it is, and there are over ninety of them. Only whitespace is
        # normalised, so a trailing space cannot make two TINs look different.
        model.tax_identification_number = model.tax_identification_number.strip() or None

    if model.section_195_nature_of_income is not None:
        model.section_195_nature_of_income = (
            model.section_195_nature_of_income.strip().lower())
        if model.section_195_nature_of_income not in ALL_NATURES:
            errors.append(
                "section_195_nature_of_income must be one of: "
                + ", ".join(ALL_NATURES)
                + f" (got '{model.section_195_nature_of_income}'). The rate in "
                  "force under s.195 keys on the nature of the income, so an "
                  "unrecognised one has no rate.")

    if model.treaty_rate_bps is not None and not (0 <= model.treaty_rate_bps <= 10000):
        errors.append(
            "treaty_rate_bps is a rate in basis points, 0 to 10000 (10% is "
            f"1000). Got {model.treaty_rate_bps}.")

    # A nature that withholds NIL needs its evidence at the point somebody
    # chooses it, not only when a bill is booked — s.195 reaches a sum
    # "chargeable under the Act", and business profits without a permanent
    # establishment are not (GE India Technology Centre v. CIT).
    if (model.section_195_nature_of_income == NATURE_BUSINESS_PROFITS_NO_PE
            and model.no_pe_declaration_on_file is not True):
        errors.append(
            "Withholding nil on business profits rests on the payee having no "
            "permanent establishment in India, so no_pe_declaration_on_file "
            "must be set with this nature of income.")

    # CAN THE ENGINE ANSWER FOR THIS SECTION AT ALL — asked before the
    # payee-fit question below, because a section nothing can rate is wrong for
    # every payee and saying so first gives the CA the useful sentence.
    #
    # Caught HERE, where the section is recorded, rather than at the first
    # bill. tds_section is a bare string on the way in, so s.194IA, s.194R,
    # s.194T and s.194M all saved fine over the API and the bulk import and
    # then wedged every bill on `ValueError: Unknown TDS section '194IA'` — a
    # raw internal string, weeks later, with no statute and no next step. And
    # s.192 did not even wedge: the registry holds it as a sentinel, so
    # resolve_tds answered applies=True at 0%, the bill saved with nil
    # withholding, and the register wrote no row and no gap because nothing was
    # deducted. That silent nil is the more dangerous half of TDS-07.
    # Gated on the SECTION being supplied, not on tds_applicable. Two reasons,
    # and the second is a hole the obvious gate would leave: VendorUpdateIn is
    # PATCH-shaped, so tds_applicable is None whenever a request does not
    # mention it — a PATCH setting only tds_section would slip past
    # `if model.tds_applicable`. And a section recorded while TDS is off is not
    # harmless, it is a landmine: it wedges the first bill after somebody
    # switches TDS on, which is exactly the delayed failure this moves.
    if model.tds_section:
        unanswerable = deduction_section_refusal(model.tds_section)
        if unanswerable:
            errors.append(unanswerable)

    # s.194C and its neighbours charge, in their own words, sums paid "to a
    # resident", so the two facts contradict each other. This used to be caught
    # when a BILL was booked; catching it on the vendor is better, because the
    # bill now routes by residency and would silently ignore the stale section
    # rather than telling anyone the vendor record is wrong.
    if model.residential_status == NON_RESIDENT:
        contradiction = section_refusal(model.tds_section, NON_RESIDENT)
        if contradiction:
            errors.append(contradiction)

    if model.residential_status == NON_RESIDENT and not model.country_of_residence:
        errors.append(
            "A non-resident vendor needs a country_of_residence — Form 27Q "
            "reports it on every deductee row, and Rule 37BC's relief from the "
            "s.206AA 20% floor is conditional on holding it.")

    return errors


def _state_code_problem(value: Optional[str]) -> Optional[str]:
    """What is wrong with a party's recorded two-digit state code, or None.

    WHY THE DOOR AND NOT ONLY THE RESOLVER. A customer's `state_code` is the
    SECOND link of `domain/gst/place_of_supply.recipient_place_of_supply`, so
    what is typed here becomes the invoice's place of supply — and that decides
    CGST+SGST against IGST (IGST §§7 and 8) and is a Rule 46(n) particular of
    the document. The identical value typed into `SalesInvoiceIn.place_of_supply`
    or `ReceiptIn.place_of_supply` has been refused against this very list for
    months; typed onto the customer it was stored and then used, so the two
    doors to one figure disagreed about what a state is.

    THE PLACE-OF-SUPPLY LIST, DELIBERATELY — `domain/gst/validator`, which holds
    **96** (outside India). An export customer IS outside India and 96 is the
    place of supply GSTN requires on that invoice, so the GSTIN list would
    refuse exactly the party this field exists to describe. `core/validators`
    names all three lists and what each is for.

    Nothing NORMALISES here beyond stripping: a state code is two characters
    from a picker, so there is no case to fold and no spelling to canonicalise,
    and a value that is not one of them is a fact somebody has to correct rather
    than one this model can repair.
    """
    if value is None:
        return None
    code = str(value).strip()
    if not code:
        return None
    from domain.gst.validator import VALID_STATE_CODES
    if code not in VALID_STATE_CODES:
        return (f"'{code}' is not a GST state code. It is the two-digit code "
                f"(27 for Maharashtra, 96 for a recipient outside India), and "
                f"it becomes this party's place of supply on every invoice — "
                f"which decides CGST+SGST against IGST.")
    return None


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
        err = _state_code_problem(self.state_code)
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
        err = _state_code_problem(self.state_code)
        if err:
            errors.append(err)
        if errors:
            raise ValueError("; ".join(errors))
        return self


def _reject_negative_credit_limit(value):
    """The DB CHECK (migration 378) refuses a negative credit limit; mock mode
    has no CHECK, so without this the two disagree about what is acceptable and
    a test written in mock mode passes against a request production rejects."""
    if value is not None and value < 0:
        raise ValueError("Credit limit cannot be negative. Leave it blank for "
                         "no recorded limit; 0 means no credit at all.")
    return value


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
    # Migration 378. Optional for the same reason credit_days is: "no limit
    # recorded" and "the limit is zero" are different facts, and zero is a real
    # thing a CA may record (no credit at all). RECORDED, NOT ENFORCED —
    # nothing blocks or warns on a bill that would exceed it.
    credit_limit_paise: Optional[int] = None
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
    # CGST Act s.31(3)(f) asks whether the SUPPLIER is registered, because a
    # self-invoice is due only on a reverse-charge supply received from one who
    # is not. A GSTIN above IS the registration and answers it; this answers it
    # where there is no GSTIN. NULL is a real third state — nobody has recorded
    # it — and domain/gst/rcm_documents.py names that gap rather than guessing,
    # because one guess mints a document the Act does not ask for and the other
    # withholds the one the input credit rests on. Migration 388.
    gst_registration_status: Optional[str] = None
    country_of_residence: Optional[str] = None
    tax_identification_number: Optional[str] = None
    # Part II First Schedule payee class — which SURCHARGE ladder a s.195
    # withholding takes. A foreign company's tops at 5%, an individual's at
    # 37%, and this used to be inferred from the PAN's 4th character, which
    # answers nothing for the many non-resident payees who have no Indian PAN.
    # NULL is a real third state: the engine refuses rather than defaulting.
    # Migration 348; domain/tds/section_195.py is the authority.
    non_resident_payee_class: Optional[str] = None
    # s.195 withholding — see domain/tds/section_195.py. All optional: a
    # non-resident vendor can be recorded before anyone has decided how it will
    # be taxed, and the bill path refuses at deduction time rather than making
    # the vendor master unsaveable.
    section_195_nature_of_income: Optional[str] = None
    trc_on_file: bool = False
    form_10f_on_file: bool = False
    no_pe_declaration_on_file: bool = False
    # Who obtained the declaration and when — s.201(1)/(1A) put the consequence
    # of a wrong nil on the DEDUCTOR, so an undated one is a claim with no
    # evidence behind it and the register reports it (migration 311).
    no_pe_declaration_on: Optional[str] = None
    no_pe_declaration_ref: Optional[str] = None
    treaty_rate_bps: Optional[int] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Vendor name cannot be blank.")
        return v

    @field_validator("credit_limit_paise")
    @classmethod
    def _credit_limit_not_negative(cls, v):
        return _reject_negative_credit_limit(v)

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
        err = _state_code_problem(self.state_code)
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
    credit_limit_paise: Optional[int] = None
    tds_applicable: Optional[bool] = None
    tds_section: Optional[str] = None
    tds_rate_bps: Optional[int] = None
    residential_status: Optional[str] = None
    # CGST Act s.31(3)(f) asks whether the SUPPLIER is registered, because a
    # self-invoice is due only on a reverse-charge supply received from one who
    # is not. A GSTIN above IS the registration and answers it; this answers it
    # where there is no GSTIN. NULL is a real third state — nobody has recorded
    # it — and domain/gst/rcm_documents.py names that gap rather than guessing,
    # because one guess mints a document the Act does not ask for and the other
    # withholds the one the input credit rests on. Migration 388.
    gst_registration_status: Optional[str] = None
    country_of_residence: Optional[str] = None
    tax_identification_number: Optional[str] = None
    # Part II First Schedule payee class — which SURCHARGE ladder a s.195
    # withholding takes. A foreign company's tops at 5%, an individual's at
    # 37%, and this used to be inferred from the PAN's 4th character, which
    # answers nothing for the many non-resident payees who have no Indian PAN.
    # NULL is a real third state: the engine refuses rather than defaulting.
    # Migration 348; domain/tds/section_195.py is the authority.
    non_resident_payee_class: Optional[str] = None
    section_195_nature_of_income: Optional[str] = None
    trc_on_file: Optional[bool] = None
    form_10f_on_file: Optional[bool] = None
    no_pe_declaration_on_file: Optional[bool] = None
    no_pe_declaration_on: Optional[str] = None
    no_pe_declaration_ref: Optional[str] = None
    treaty_rate_bps: Optional[int] = None
    is_active: Optional[bool] = None

    @field_validator("credit_limit_paise")
    @classmethod
    def _credit_limit_not_negative(cls, v):
        return _reject_negative_credit_limit(v)

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
        err = _state_code_problem(self.state_code)
        if err:
            errors.append(err)
        if errors:
            raise ValueError("; ".join(errors))
        return self
