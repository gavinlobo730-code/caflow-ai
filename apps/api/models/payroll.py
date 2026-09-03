"""
Pydantic request models for payroll endpoints.
EPF Act §6: PF = 12% of (Basic + DA). ESI Act §2(9): employee 0.75%, employer 3.25%.
IT Act §192: TDS on salary (new regime slabs + 4% cess).
All monetary amounts in integer paise.
"""
from pydantic import BaseModel, field_validator
from typing import Optional
import re

from core.validators import validate_pan
from models.fy import FYLabel


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

    # task #229: payroll_employees.pan had a DB-level CHECK constraint
    # (migration 112) but no application-level validation — task #223 wired
    # validate_pan into CustomerIn/VendorIn/mca_workspace/tds_workspace but
    # missed this model, so a malformed PAN fell through to a raw, unformatted
    # Postgres constraint-violation error instead of a clean 422.
    @field_validator("pan")
    @classmethod
    def pan_format(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        v = v.strip().upper()
        err = validate_pan(v)
        if err:
            raise ValueError(err)
        return v

    @field_validator("basic_paise", "other_allowances_paise", "lta_paise",
                     "medical_paise", "special_allowance_paise")
    @classmethod
    def non_negative_paise(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Paise values must be non-negative.")
        return v

    # task #229: hra_percent/da_percent were the only salary-component fields
    # NOT covered by non_negative_paise (they're floats, not paise ints) —
    # a negative value directly subtracts from gross in _compute_slip
    # (routers/payroll.py), silently understating gross/net/TDS on every
    # slip for that employee, and posts wrong if the run is finalized.
    @field_validator("hra_percent", "da_percent")
    @classmethod
    def percent_in_range(cls, v: float) -> float:
        if v < 0 or v > 100:
            raise ValueError("Percent fields must be between 0 and 100.")
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

    # task #229: EmployeeUpdateIn had NO numeric validation at all — not even
    # the non-negative check EmployeeIn applies on create. A PATCH with a
    # negative basic_paise/hra_percent/etc. (typo, bad CSV re-import) would
    # corrupt every payslip _compute_slip computes off that employee from
    # then on, same failure mode as the create-time gap this mirrors.
    @field_validator("basic_paise", "other_allowances_paise", "lta_paise",
                     "medical_paise", "special_allowance_paise")
    @classmethod
    def non_negative_paise(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("Paise values must be non-negative.")
        return v

    @field_validator("hra_percent", "da_percent")
    @classmethod
    def percent_in_range(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < 0 or v > 100):
            raise ValueError("Percent fields must be between 0 and 100.")
        return v

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: Optional[str]) -> Optional[str]:
        # task #229: unlike EmployeeIn.name_not_empty (create-time), nothing
        # stopped PATCH {"name": ""} or {"name": "   "} from silently
        # blanking an employee's name on every future payslip/GL narration —
        # exclude_none in update_employee doesn't exclude an empty string.
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Employee name cannot be blank.")
        return v

    @field_validator("pan")
    @classmethod
    def pan_format(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        v = v.strip().upper()
        err = validate_pan(v)
        if err:
            raise ValueError(err)
        return v

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

    # task #229: unlike EmployeeIn's mirrored fields, these had zero numeric
    # validation — for consistency with the fields they mirror (no live
    # computation path reads salary_structures today, but a negative/absurd
    # percent stored here is still bad data quality).
    @field_validator("basic_percent", "hra_percent", "da_percent",
                     "lta_percent", "special_percent")
    @classmethod
    def percent_in_range(cls, v: float) -> float:
        if v < 0 or v > 100:
            raise ValueError("Percent fields must be between 0 and 100.")
        return v

    @field_validator("medical_paise")
    @classmethod
    def non_negative_paise(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Paise values must be non-negative.")
        return v


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


# ── Employee income-tax declarations (IT Act §192, Rule 26C / Form 12BB) ──────

class DeclarationItemIn(BaseModel):
    """One Chapter VI-A line on the employee's declaration."""
    section: str
    label: Optional[str] = ""
    amount_declared_paise: int = 0
    # Only a verifier sets these; an employee's own submission leaves them alone.
    amount_verified_paise: Optional[int] = None
    status: Optional[str] = None
    proof_reference: Optional[str] = ""


class DeclarationIn(BaseModel):
    """The employee's §192 declaration for one financial year.

    `regime` is the intimation to the EMPLOYER under CBDT Circular 04/2023 and
    governs withholding only — it is not the §115BAC(6) election, which is made
    in Form 10-IEA or in the return itself.
    """
    client_id: str
    employee_id: str
    fy: FYLabel
    regime: str = "new"

    rent_paid_declared_paise: int = 0
    landlord_name: Optional[str] = ""
    landlord_address: Optional[str] = ""
    landlord_pan: Optional[str] = ""
    rent_is_metro: bool = False

    lta_declared_paise: int = 0

    home_loan_interest_declared_paise: int = 0
    lender_name: Optional[str] = ""
    lender_pan: Optional[str] = ""

    other_income_declared_paise: int = 0
    house_property_loss_declared_paise: int = 0

    items: list[DeclarationItemIn] = []

    @field_validator("landlord_pan", "lender_pan")
    @classmethod
    def _pan_shape(cls, v):
        if not v:
            return ""
        s = str(v).strip().upper()
        if not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", s):
            raise ValueError("PAN must be in the form AAAAA9999A")
        return s


class DeclarationVerifyIn(BaseModel):
    """The CA's verdict after going through the proofs.

    Amounts here are what the PROOFS support, which may be less than was
    claimed and never more. Anything not named keeps its declared figure and
    stays unverified — so a partial verification cannot silently bless the
    lines nobody looked at.
    """
    client_id: str
    rent_paid_verified_paise: Optional[int] = None
    lta_verified_paise: Optional[int] = None
    home_loan_interest_verified_paise: Optional[int] = None
    items: list[DeclarationItemIn] = []
    # Set once every proof has been through. Until then the declared figures
    # keep working for the first three quarters and stop working in the fourth.
    proofs_verified: bool = False


class StatutoryIdentityIn(BaseModel):
    """The client's own establishment registrations (migration 325).

    Every field is Optional and PATCH-shaped: only what is sent is written, and
    an explicit empty string CLEARS the field. That distinction matters here —
    "leave the TAN alone" and "this client has no TAN" are different edits, and
    a form that always posts every field would silently do the second whenever
    a CA opened the screen to change something else.

    Validation is deliberately asymmetric and domain/payroll/identity.py says
    why: TAN has a settled format and is checked; the EPF, ESIC and LIN numbers
    vary by region and issuing office, so a pattern invented here would refuse
    valid registrations rather than catch typos.
    """
    client_id: str
    tan: Optional[str] = None
    epf_establishment_code: Optional[str] = None
    esic_employer_code: Optional[str] = None
    lin: Optional[str] = None
    note: Optional[str] = None


class PTRegistrationIn(BaseModel):
    """One state's professional-tax registration (migration 325).

    PTRC and PTEC are separate certificates and both are recorded, because
    they authorise different things: the Registration Certificate is the
    employer's authority to DEDUCT professional tax from employees and deposit
    it, and the Enrolment Certificate is the entity's own levy on itself. Only
    the PTRC covers what a payslip has already deducted.
    """
    client_id: str
    state: str
    ptrc_number: Optional[str] = None
    ptec_number: Optional[str] = None
    note: Optional[str] = None

    @field_validator("state")
    @classmethod
    def _state_code(cls, v):
        s = str(v or "").strip().upper()
        if not re.match(r"^[A-Z]{2}$", s):
            raise ValueError(
                "State must be the two-letter code payroll_employees.pt_state "
                'carries — "MH", "KA", "TN".')
        return s
