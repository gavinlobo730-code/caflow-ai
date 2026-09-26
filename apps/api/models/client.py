import re
from pydantic import BaseModel, field_validator
from typing import Optional
from enum import Enum


class EntityType(str, Enum):
    PROPRIETORSHIP = "Proprietorship"
    PARTNERSHIP = "Partnership"
    LLP = "LLP"
    PRIVATE_LIMITED = "Private Limited"
    PUBLIC_LIMITED = "Public Limited"
    TRUST = "Trust"
    SOCIETY = "Society"
    INDIVIDUAL = "Individual"


class ClientStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class GSTFilingFrequency(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


# GST-25, migration 420: what the client's PRIMARY registration (clients.gstin)
# IS under s.25 — a composition dealer files CMP-08/GSTR-4, never GSTR-1/3B.
# domain/gst/registrations.py is the authority for the vocabulary and for what
# each type means; this mirrors its REGISTRATION_TYPES rather than declaring a
# second one, because a client model with its own list is exactly the kind of
# second vocabulary this codebase keeps having to retire.
def _registration_types() -> tuple[str, ...]:
    from domain.gst.registrations import REGISTRATION_TYPES
    return REGISTRATION_TYPES


def _composition_categories() -> tuple[str, ...]:
    from domain.gst.composition import COMPOSITION_CATEGORIES
    return COMPOSITION_CATEGORIES


def validate_gst_registration_type(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    value = v.strip().lower()
    types = _registration_types()
    if value not in types:
        raise ValueError(
            f"{v!r} is not a GST registration type. One of: {', '.join(types)}.")
    return value


def validate_composition_category(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    value = v.strip().lower()
    categories = _composition_categories()
    if value not in categories:
        raise ValueError(
            f"{v!r} is not a composition category. One of: "
            f"{', '.join(categories)}.")
    return value


# PAN: 5 uppercase letters + 4 digits + 1 uppercase letter (IT Act)
PAN_REGEX = re.compile(r'^[A-Z]{5}[0-9]{4}[A-Z]$')

# GSTIN: 2-digit state + PAN (10) + entity num + Z + check digit (CGST Act, Section 25)
GSTIN_REGEX = re.compile(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$')


def validate_pan(pan: str) -> str:
    if not PAN_REGEX.match(pan):
        raise ValueError(f"Invalid PAN format: {pan}. Expected format: AAAAA9999A")
    return pan


def validate_gstin(gstin: str) -> str:
    if not GSTIN_REGEX.match(gstin):
        raise ValueError(f"Invalid GSTIN format: {gstin}. Expected: 2-digit state + PAN + entity + Z + check")
    return gstin


class ClientCreate(BaseModel):
    client_name: str
    entity_type: EntityType
    pan: str
    gstin: Optional[str] = None
    mobile: Optional[str] = None
    email: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    state_code: Optional[str] = None
    gst_filing_frequency: Optional[GSTFilingFrequency] = GSTFilingFrequency.MONTHLY
    # What the PRIMARY registration (the gstin above) IS under s.25 — see
    # domain/gst/registrations.py. None means unrecorded, not "regular" — the
    # domain layer's own primary_of() supplies that default, so a bare column
    # left NULL here still resolves the way every client did before this field
    # existed.
    gst_registration_type: Optional[str] = None
    # Which s.10 rate a COMPOSITION primary pays — meaningless otherwise, and
    # None means unrecorded rather than any particular rate (domain/gst/
    # composition.py refuses rather than guessing one).
    composition_category: Optional[str] = None
    status: ClientStatus = ClientStatus.ACTIVE
    is_test: bool = False
    notes: Optional[str] = None

    @field_validator("pan")
    @classmethod
    def pan_must_be_valid(cls, v: str) -> str:
        return validate_pan(v.upper())

    @field_validator("gstin")
    @classmethod
    def gstin_must_be_valid(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return validate_gstin(v.upper())
        return v

    @field_validator("gst_registration_type")
    @classmethod
    def registration_type_must_be_valid(cls, v: Optional[str]) -> Optional[str]:
        return validate_gst_registration_type(v)

    @field_validator("composition_category")
    @classmethod
    def composition_category_must_be_valid(cls, v: Optional[str]) -> Optional[str]:
        return validate_composition_category(v)


class PracticeIdentityUpdate(BaseModel):
    """Partner-only maintenance of the firm's internal practice client identity
    (Phase 3.3A, Part B). Tax identifiers are immutable on the generic ClientUpdate;
    this model is the controlled path to set/correct them for the practice client."""
    pan: Optional[str] = None
    gstin: Optional[str] = None
    state: Optional[str] = None
    state_code: Optional[str] = None

    @field_validator("pan")
    @classmethod
    def pan_must_be_valid(cls, v: Optional[str]) -> Optional[str]:
        return validate_pan(v.upper()) if v else v

    @field_validator("gstin")
    @classmethod
    def gstin_must_be_valid(cls, v: Optional[str]) -> Optional[str]:
        return validate_gstin(v.upper()) if v else v


class ClientUpdate(BaseModel):
    client_name: Optional[str] = None
    entity_type: Optional[EntityType] = None
    mobile: Optional[str] = None
    email: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    gst_filing_frequency: Optional[GSTFilingFrequency] = None
    # See ClientCreate — same field, same meaning, same domain authority.
    gst_registration_type: Optional[str] = None
    composition_category: Optional[str] = None
    # Whether this client's ADVANCES bear tax — GSTR-1 Tables 11A and 11B.
    #
    # CGST s.13(2) charges an advance for SERVICES when it is received;
    # Notification 66/2017-Central Tax removed the charge for GOODS, where the
    # liability arises at the invoice (s.12(2) proviso). So it is a fact about
    # the client's business, not about their ledger, and two clients with
    # identical receipts can owe different tax.
    #
    # The column has existed since migration 286 and gst_advance_service has
    # read it since; NOTHING HAS EVER WRITTEN IT. Table 11 was therefore empty
    # for every client on the platform, and no screen said whether that meant
    # "no advances" or "not switched on".
    gst_advance_tax_applicable: Optional[bool] = None
    status: Optional[ClientStatus] = None
    is_test: Optional[bool] = None
    notes: Optional[str] = None
