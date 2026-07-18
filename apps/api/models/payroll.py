"""
Pydantic request models for payroll endpoints.
EPF Act: PF = 12% of basic. ESI Act §2(9): employee 0.75%, employer 3.25%.
IT Act §192: TDS on salary (new regime slabs + 4% cess).
All monetary amounts in integer paise.
"""
from pydantic import BaseModel, field_validator
from typing import Optional
import re


def _normalize_gender(v: Optional[str]) -> Optional[str]:
    """Normalize free-text gender to a canonical 'male'/'female'/'other'/None.
    Used for Maharashtra Professional Tax, where women earning ≤ ₹25,000/month
    are exempt (w.e.f. 01-Apr-2023). An unset gender stays None and is treated
    as non-exempt by the PT engine (we never grant an exemption we can't
    substantiate)."""
    if v is None:
        return None
    s = v.strip().lower()
    if not s:
        return None
    if s in {"m", "male", "man"}:
        return "male"
    if s in {"f", "female", "woman", "women", "w"}:
        return "female"
    return "other"


class EmployeeIn(BaseModel):
    client_id: str
    name: str
    pan: Optional[str] = None
    # Privacy-by-design: we store ONLY the last 4 digits of Aadhaar, never the full
    # number (UIDAI norms). The full value must never reach the backend.
    aadhaar_last4: Optional[str] = None
    gender: Optional[str] = None
    designation: Optional[str] = None
    department: Optional[str] = None
    joining_date: Optional[str] = None
    basic_paise: int = 0
    hra_percent: float = 0.0
    da_percent: float = 0.0
    other_allowances_paise: int = 0
    lta_paise: int = 0
    medical_paise: int = 0
    special_allowance_paise: int = 0
    pf_applicable: bool = True
    esi_applicable: bool = True
    pt_applicable: bool = False
    pt_state: Optional[str] = None
    uan: Optional[str] = None
    esi_number: Optional[str] = None
    bank_account_no: Optional[str] = None
    bank_ifsc: Optional[str] = None
    bank_name: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Employee name cannot be blank.")
        return v.strip()

    @field_validator("aadhaar_last4")
    @classmethod
    def aadhaar_last4_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        # Reject anything other than exactly 4 digits so a full Aadhaar can never
        # be stored even if a caller mistakenly sends one.
        if not re.fullmatch(r"\d{4}", v):
            raise ValueError("aadhaar_last4 must be exactly the last 4 digits.")
        return v

    @field_validator("basic_paise", "other_allowances_paise", "lta_paise",
                     "medical_paise", "special_allowance_paise")
    @classmethod
    def non_negative_paise(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Paise values must be non-negative.")
        return v

    @field_validator("gender")
    @classmethod
    def normalize_gender(cls, v: Optional[str]) -> Optional[str]:
        return _normalize_gender(v)


class EmployeeUpdateIn(BaseModel):
    name: Optional[str] = None
    pan: Optional[str] = None
    aadhaar_last4: Optional[str] = None
    gender: Optional[str] = None
    designation: Optional[str] = None
    department: Optional[str] = None
    basic_paise: Optional[int] = None
    hra_percent: Optional[float] = None
    da_percent: Optional[float] = None
    other_allowances_paise: Optional[int] = None
    lta_paise: Optional[int] = None
    medical_paise: Optional[int] = None
    special_allowance_paise: Optional[int] = None
    pf_applicable: Optional[bool] = None
    esi_applicable: Optional[bool] = None
    pt_applicable: Optional[bool] = None
    pt_state: Optional[str] = None
    bank_account_no: Optional[str] = None
    bank_ifsc: Optional[str] = None
    bank_name: Optional[str] = None
    uan: Optional[str] = None
    esi_number: Optional[str] = None
    status: Optional[str] = None

    @field_validator("gender")
    @classmethod
    def normalize_gender(cls, v: Optional[str]) -> Optional[str]:
        return _normalize_gender(v)

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: Optional[str]) -> Optional[str]:
        # Mirrors the payroll_employees.status CHECK; reject bad values up front
        # rather than letting them hit the DB constraint as an opaque 500.
        if v is None:
            return v
        s = v.strip().lower()
        if s not in ("active", "resigned", "terminated"):
            raise ValueError("status must be one of: active, resigned, terminated.")
        return s

    @field_validator("aadhaar_last4")
    @classmethod
    def aadhaar_last4_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        if not re.fullmatch(r"\d{4}", v):
            raise ValueError("aadhaar_last4 must be exactly the last 4 digits.")
        return v


class SalaryStructureIn(BaseModel):
    client_id: str
    name: str
    basic_percent: float = 40.0
    hra_percent: float = 20.0
    da_percent: float = 0.0
    lta_percent: float = 5.0
    medical_paise: int = 125000  # ₹1,250/month
    special_percent: float = 0.0
    pf_applicable: bool = True
    esi_applicable: bool = True
    pt_applicable: bool = False
    pt_state: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Structure name cannot be blank.")
        return v.strip()


class PayrollRunIn(BaseModel):
    client_id: str
    month: str  # YYYY-MM

    @field_validator("month")
    @classmethod
    def valid_month_format(cls, v: str) -> str:
        import re
        if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", v):
            raise ValueError("month must be in YYYY-MM format (e.g. 2026-06).")
        return v


class RunStatusIn(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str) -> str:
        if v not in ("draft", "review"):
            raise ValueError("status must be 'draft' or 'review'. Use /finalize to finalize.")
        return v


class PayrollDisburseIn(BaseModel):
    """Mark a finalized payroll run as paid — records the net-salary payout from a
    bank account. bank_account_id is a bank_accounts row (must be linked to a
    ledger account); payment_date defaults to today if omitted."""
    bank_account_id: str
    payment_date: Optional[str] = None
    payment_reference: Optional[str] = None

    @field_validator("payment_date")
    @classmethod
    def valid_payment_date(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        import re
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v.strip()):
            raise ValueError("payment_date must be YYYY-MM-DD.")
        return v.strip()
