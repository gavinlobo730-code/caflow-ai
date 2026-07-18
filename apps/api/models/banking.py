"""
Pydantic request models for banking & reconciliation endpoints.
All monetary amounts must be integer paise (CGST Act §2(59), never float).

Phase B.0: models use the canonical bank_transactions field names
(`transaction_date`, `account_id`) — not the legacy `txn_date`/`bank_account_id`
that never existed as columns.
"""
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional
from decimal import Decimal


class BankAccountIn(BaseModel):
    client_id: str
    bank_name: str
    account_no: str
    ifsc: Optional[str] = None
    account_type: str = "Current"
    opening_balance_paise: int = 0
    opening_balance_date: Optional[str] = None
    coa_account_id: Optional[str] = None
    # Multi-Currency Phase 5 — account denomination currency (default INR). A non-INR
    # currency is accepted only when multi-currency is active for the client (enforced
    # in the router); INR accounts behave exactly as before.
    currency: Optional[str] = None

    @field_validator("bank_name", "account_no")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field cannot be blank.")
        return v.strip()

    @field_validator("currency")
    @classmethod
    def upper_currency(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip().upper()
        if len(v) != 3 or not v.isalpha():
            raise ValueError("currency must be a 3-letter ISO 4217 code.")
        return v

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


class StatementImportRow(BaseModel):
    """One already-parsed bank-statement line. Parsing happens upstream (Phase B.1)."""
    transaction_date: str
    description: str = ""
    debit_paise: int = 0
    credit_paise: int = 0
    balance_paise: int = 0
    reference_no: Optional[str] = None

    @model_validator(mode="after")
    def validate_amounts(self) -> "StatementImportRow":
        if self.debit_paise < 0 or self.credit_paise < 0:
            raise ValueError("debit_paise and credit_paise must be non-negative.")
        return self


class StatementImportIn(BaseModel):
    client_id: str
    bank_name: str
    account_number: Optional[str] = None
    bank_account_id: Optional[str] = None
    rows: list[StatementImportRow]

    @field_validator("rows")
    @classmethod
    def at_least_one_row(cls, v: list) -> list:
        if not v:
            raise ValueError("No transactions provided.")
        return v


class TransactionAccountIn(BaseModel):
    """Map a bank transaction to a GL (chart_of_accounts) account."""
    account_id: str


class PostTransactionIn(BaseModel):
    """Post a bank transaction to the ledger. bank_account_id is the bank's GL
    (chart_of_accounts) account; account_id is the counter-account."""
    account_id: str
    bank_account_id: str


class PostBankTxnIn(BaseModel):
    """Banking B.3 post / preview. The category (set in B.2) drives counter
    resolution + settlement; accounts are supplied only where a GL account must be
    chosen explicitly (Expense/Salary/Loan/Capital/Interest/Other) or for a
    Transfer's destination. All optional — the service validates what each
    category requires."""
    bank_account_id: Optional[str] = None      # bank's GL account (else derived from the statement)
    account_id: Optional[str] = None           # explicitly-selected counter GL account
    to_bank_account_id: Optional[str] = None   # Transfer destination bank/cash account


class ReconcileMatchIn(BaseModel):
    bank_transaction_id: str
    journal_entry_id: str


class CategorizeIn(BaseModel):
    """Set a controlled category on a bank transaction (B.2.2)."""
    category: str


class MatchIn(BaseModel):
    """Manually match / accept a suggestion: link a transaction to a business
    entity (B.2.5). No journal is posted (that is Phase B.3)."""
    matched_entity_type: str
    matched_entity_id: str
    category: Optional[str] = None


class BankMatchAllocationIn(BaseModel):
    entity_id: str
    allocated_paise: int

    @field_validator("allocated_paise")
    @classmethod
    def positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("allocated_paise must be positive.")
        return v


class BankMatchMultiIn(BaseModel):
    """Match ONE bank transaction to MULTIPLE sales invoices (AR — a credit
    transaction) or purchase bills (AP — a debit transaction) in a single
    settlement (multi-invoice bank allocation). Creates a real receipt /
    purchase_payment record (with per-document allocations) sourced from this
    transaction, rather than a bare linkage — the bank transaction is matched
    to THAT record, so exactly one journal is posted (never a second,
    separate bank-side journal alongside the receipt/payment's own)."""
    entity_type: str  # "sales_invoice" | "purchase_bill"
    allocations: list[BankMatchAllocationIn]
    reference_no: Optional[str] = None
    notes: Optional[str] = None
    tds_paise: int = 0   # AR only — ignored when entity_type is purchase_bill
    # Multi-Currency — must match every allocated document's currency; amounts
    # are in that currency's minor units.
    currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = None

    @field_validator("entity_type")
    @classmethod
    def valid_entity_type(cls, v: str) -> str:
        if v not in ("sales_invoice", "purchase_bill"):
            raise ValueError("entity_type must be 'sales_invoice' or 'purchase_bill'.")
        return v

    @field_validator("allocations")
    @classmethod
    def at_least_one(cls, v: list) -> list:
        if not v:
            raise ValueError("Select at least one invoice/bill to allocate.")
        return v

    @field_validator("tds_paise")
    @classmethod
    def tds_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("tds_paise must be non-negative.")
        return v


class ReconciliationCreateIn(BaseModel):
    """Open a reconciliation session (B.4) for one bank account + statement period.
    Balances are integer paise; the period reuses the statement's start/end dates."""
    client_id: str
    bank_account_id: str
    statement_start_date: str
    statement_end_date: str
    opening_balance_paise: int = 0
    closing_balance_paise: int = 0

    @model_validator(mode="after")
    def validate_period(self) -> "ReconciliationCreateIn":
        if self.statement_end_date < self.statement_start_date:
            raise ValueError("statement_end_date must not precede statement_start_date.")
        return self


class ReconciliationUpdateIn(BaseModel):
    """Adjust an open/in-progress session's balances or documented adjustments.
    Rejected once the session is completed (immutable)."""
    opening_balance_paise: Optional[int] = None
    closing_balance_paise: Optional[int] = None
    adjustments_paise: Optional[int] = None


class ReconcileItemsIn(BaseModel):
    """Manually reconcile / unreconcile a set of posted transactions (B.4.2).
    No automatic reconciliation — this is the explicit human confirmation."""
    transaction_ids: list[str]

    @field_validator("transaction_ids")
    @classmethod
    def at_least_one(cls, v: list) -> list:
        if not v:
            raise ValueError("Select at least one transaction.")
        return v


class MatchingRuleIn(BaseModel):
    client_id: str
    rule_name: str
    description_pattern: Optional[str] = None
    amount_min_paise: Optional[int] = None
    amount_max_paise: Optional[int] = None
    txn_type: str = "any"            # debit | credit | any (matches table CHECK)
    suggested_account_id: Optional[str] = None
    suggested_category: Optional[str] = None
    suggested_narration: Optional[str] = None
    is_active: bool = True

    @field_validator("rule_name")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Rule name cannot be blank.")
        return v.strip()
