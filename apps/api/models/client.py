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
    status: Optional[ClientStatus] = None
    is_test: Optional[bool] = None
    notes: Optional[str] = None
