"""
Pydantic request models for accounting endpoints.
Double-entry: debit_paise == credit_paise enforced at validation level.
CGST Act §2(59): all money values stored as integer paise (never float).
"""
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional
from enum import Enum


class AccountType(str, Enum):
    ASSET = "Asset"
    LIABILITY = "Liability"
    EQUITY = "Equity"
    INCOME = "Income"
    EXPENSE = "Expense"


class AccountIn(BaseModel):
    name: str
    code: Optional[str] = None
    account_type: AccountType
    parent_id: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Account name cannot be blank.")
        return v.strip()


class AccountUpdateIn(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class JournalLineIn(BaseModel):
    account_id: str
    debit_paise: int = 0
    credit_paise: int = 0
    narration: Optional[str] = None

    @model_validator(mode="after")
    def exactly_one_side(self) -> "JournalLineIn":
        if self.debit_paise < 0 or self.credit_paise < 0:
            raise ValueError("debit_paise and credit_paise must be non-negative integers.")
        if self.debit_paise == 0 and self.credit_paise == 0:
            raise ValueError("Each journal line must have either a debit or credit amount.")
        if self.debit_paise > 0 and self.credit_paise > 0:
            raise ValueError("A journal line cannot have both debit and credit amounts.")
        return self


# Manual journals may only use the entry types the journal_entries CHECK
# constraint allows (Sales/Purchase/Payment/Receipt/Journal/Contra/Opening).
ALLOWED_JOURNAL_ENTRY_TYPES = {
    "Journal", "Contra", "Payment", "Receipt", "Sales", "Purchase", "Opening",
}


class JournalEntryUpdateIn(BaseModel):
    """A correction to an existing entry. Every field optional — a CA fixing a
    narration should not have to resend the lines.

    EXCEPT on a posted entry, where `lines` (if the amounts are changing at all)
    must be the COMPLETE set. edit_posted_journal replaces the lines wholesale
    so that the audit trigger records a clean before/after for every figure, and
    so the Dr = Cr check runs against what the entry will actually be rather
    than a fragment of it.

    client_id is absent on purpose: moving an entry between clients is not a
    correction, it is two entries.
    """
    entry_date: Optional[str] = None      # YYYY-MM-DD
    reference_no: Optional[str] = None
    narration: Optional[str] = None
    entry_type: Optional[str] = None
    lines: Optional[list[JournalLineIn]] = None

    @field_validator("entry_type")
    @classmethod
    def entry_type_allowed(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ALLOWED_JOURNAL_ENTRY_TYPES:
            raise ValueError(
                f"Invalid entry_type '{v}'. Allowed: {', '.join(sorted(ALLOWED_JOURNAL_ENTRY_TYPES))}."
            )
        return v


class JournalEntryIn(BaseModel):
    client_id: str
    entry_date: str  # YYYY-MM-DD
    reference_no: Optional[str] = None
    narration: Optional[str] = None
    entry_type: str = "Journal"
    status: str = "draft"            # "draft" (off-books) | "posted" (to the ledger)
    attachments: list[dict] = []     # supporting documents: [{"name","url"}, ...]
    lines: list[JournalLineIn]

    @field_validator("entry_type")
    @classmethod
    def entry_type_allowed(cls, v: str) -> str:
        if v not in ALLOWED_JOURNAL_ENTRY_TYPES:
            raise ValueError(
                f"Invalid entry_type '{v}'. Allowed: {', '.join(sorted(ALLOWED_JOURNAL_ENTRY_TYPES))}."
            )
        return v

    @field_validator("status")
    @classmethod
    def status_allowed(cls, v: str) -> str:
        if v not in ("draft", "posted"):
            raise ValueError("status must be 'draft' or 'posted'.")
        return v

    @field_validator("lines")
    @classmethod
    def min_two_lines(cls, v: list) -> list:
        if len(v) < 2:
            raise ValueError("A journal entry must have at least 2 lines.")
        return v

    @model_validator(mode="after")
    def balanced_entry(self) -> "JournalEntryIn":
        total_debit = sum(ln.debit_paise for ln in self.lines)
        total_credit = sum(ln.credit_paise for ln in self.lines)
        if total_debit != total_credit:
            raise ValueError(
                f"Journal entry is unbalanced: debits={total_debit} paise, credits={total_credit} paise."
            )
        return self


class JournalReversalIn(BaseModel):
    reversal_date: str  # YYYY-MM-DD
    narration: Optional[str] = None


class DepreciationMethod(str, Enum):
    SL = "SL"
    WDV = "WDV"


class FixedAssetIn(BaseModel):
    client_id: str
    asset_name: str
    asset_category: str = "Other"
    purchase_date: str  # YYYY-MM-DD
    purchase_cost_paise: int
    salvage_value_paise: int = 0
    useful_life_years: Optional[int] = None
    depreciation_method: DepreciationMethod = DepreciationMethod.WDV
    wdv_rate_percent: Optional[float] = None
    location: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("purchase_cost_paise", "salvage_value_paise")
    @classmethod
    def must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Cost/salvage values must be non-negative paise integers.")
        return v


class DepreciationIn(BaseModel):
    period: Optional[str] = None  # YYYY-MM; defaults to current month


class DisposalIn(BaseModel):
    disposal_type: str = "Sale"  # Sale | Scrapped | Written Off
    sale_proceeds_paise: int = 0
    disposal_date: Optional[str] = None  # YYYY-MM-DD; defaults to today
    notes: Optional[str] = None

    @field_validator("sale_proceeds_paise")
    @classmethod
    def must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("sale_proceeds_paise must be non-negative.")
        return v
