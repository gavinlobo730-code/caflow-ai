"""
Pydantic request models for banking & reconciliation endpoints.
All monetary amounts must be integer paise (CGST Act §2(59), never float).
"""
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional


class BankAccountIn(BaseModel):
    client_id: str
    bank_name: str
    account_no: str
    ifsc: Optional[str] = None
    account_type: str = "Current"
    opening_balance_paise: int = 0
    opening_balance_date: Optional[str] = None
    coa_account_id: Optional[str] = None

    @field_validator("bank_name", "account_no")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field cannot be blank.")
        return v.strip()

    @field_validator("opening_balance_paise")
    @classmethod
    def non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Opening balance must be non-negative.")
        return v


class BankAccountUpdateIn(BaseModel):
    bank_name: Optional[str] = None
    ifsc: Optional[str] = None
    account_type: Optional[str] = None
    opening_balance_paise: Optional[int] = None
    opening_balance_date: Optional[str] = None
    coa_account_id: Optional[str] = None
    is_active: Optional[bool] = None


class BankTransactionRow(BaseModel):
    txn_date: str
    description: str
    debit_paise: int = 0
    credit_paise: int = 0
    balance_paise: int = 0

    @model_validator(mode="after")
    def validate_amounts(self) -> "BankTransactionRow":
        if self.debit_paise < 0 or self.credit_paise < 0:
            raise ValueError("debit_paise and credit_paise must be non-negative.")
        return self


class StatementImportIn(BaseModel):
    client_id: str
    bank_account_id: Optional[str] = None
    rows: list[BankTransactionRow]

    @field_validator("rows")
    @classmethod
    def at_least_one_row(cls, v: list) -> list:
        if not v:
            raise ValueError("No transactions provided.")
        return v


class ReconcileMatchIn(BaseModel):
    bank_transaction_id: str
    journal_entry_id: str


class MatchingRuleIn(BaseModel):
    client_id: str
    rule_name: str
    description_pattern: Optional[str] = None
    amount_min_paise: Optional[int] = None
    amount_max_paise: Optional[int] = None
    account_id: Optional[str] = None
    is_active: bool = True

    @field_validator("rule_name")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Rule name cannot be blank.")
        return v.strip()
