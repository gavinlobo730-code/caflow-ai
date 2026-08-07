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
    # A bank charge's amount is tax-INCLUSIVE. Supplying a rate splits it into
    # taxable value + input GST (CGST Act s.16); omitting it posts the gross, as
    # before. 0 is a real answer ("this charge carries no GST"), so the default
    # has to be None rather than 0.
    gst_rate_bps: Optional[int] = None
    # IGST Act s.12(12) — place of supply for banking services is the recipient's
    # location. Stated by the CA (a rule can prefill it); never inferred.
    is_interstate: bool = False

    @field_validator("gst_rate_bps")
    @classmethod
    def known_gst_rate(cls, v: Optional[int]) -> Optional[int]:
        return _validate_gst_rate_bps(v)


class BankBatchIn(BaseModel):
    """Apply one action to several bank transactions (Tier 1.7).

    NOT atomic across rows, deliberately: eight good rows should not be rolled
    back because the ninth was already posted. Each row comes back with its own
    outcome — a partial success reported as a success is how a transaction
    quietly stays uncoded until year end."""
    transaction_ids: list[str]

    @field_validator("transaction_ids")
    @classmethod
    def at_least_one(cls, v: list) -> list:
        if not v:
            raise ValueError("Select at least one transaction.")
        return v


class BankAttachmentIn(BaseModel):
    """A supporting document on a bank transaction (Tier 1.8).

    The link's scheme is validated in domain/banking/attachments — a stored
    javascript:/data: URL rendered as a link is stored XSS, so the vocabulary is
    closed to http/https rather than sanitised."""
    name: str
    url: str


class BankAttachmentRemoveIn(BaseModel):
    url: str


class BankTransferPairIn(BaseModel):
    """Confirm two bank lines are one transfer (Tier 1.5). The path transaction
    is the PRIMARY (outflow) side; this names the counterpart."""
    counterpart_id: str

    @field_validator("counterpart_id")
    @classmethod
    def required(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("The counterpart transaction is required.")
        return v.strip()


class BankPayeeIn(BaseModel):
    """Name the other side of a bank line (Tier 1.3).

    An EMPTY name clears the payee entirely, link included — a wrong association
    must not be able to survive as a dangling id with no name beside it."""
    payee_name: Optional[str] = None
    payee_type: Optional[str] = None      # customer | vendor | other
    payee_id: Optional[str] = None

    @field_validator("payee_type")
    @classmethod
    def known_type(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not str(v).strip():
            return None
        value = str(v).strip().lower()
        if value not in ("customer", "vendor", "other"):
            raise ValueError("payee_type must be one of: customer, vendor, other.")
        return value


class BankSplitLineIn(BaseModel):
    """One leg of a split bank line (Tier 1.2). Always a POSITIVE amount —
    direction comes from the bank transaction, not the split."""
    account_id: str
    amount_paise: int
    narration: Optional[str] = None

    @field_validator("account_id")
    @classmethod
    def account_required(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("Each split needs a GL account.")
        return v.strip()

    @field_validator("amount_paise")
    @classmethod
    def positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(
                "Each split must be a positive amount — they all move in the same "
                "direction as the bank line.")
        return v


class BankSplitsIn(BaseModel):
    """Replace a transaction's splits. An EMPTY list clears them and returns the
    transaction to an ordinary single-account posting — that is a legitimate
    operation, so it is not rejected here.

    The sum-to-the-amount rule is NOT checked here: this model does not know the
    transaction. domain/banking/splits validates it (with a message naming the
    shortfall) and the replace RPC enforces it atomically."""
    splits: list[BankSplitLineIn]


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


class ReconciliationReopenIn(BaseModel):
    """Undo a completed reconciliation (Tier 2.5). Partner-gated in the router.

    The reason is mandatory and substantive — this reverses a certification, and
    an unexplained reversal in the audit trail is barely better than no trail.
    The same minimum is enforced by a DB CHECK (migration 253), so no code path
    can reopen anonymously."""
    reason: str

    @field_validator("reason")
    @classmethod
    def substantive(cls, v: str) -> str:
        cleaned = (v or "").strip()
        if len(cleaned) < 10:
            raise ValueError(
                "Give a reason of at least 10 characters for reopening a completed "
                "reconciliation.")
        return cleaned


class ReconciliationCreateIn(BaseModel):
    """Open a reconciliation session (B.4) for one bank account + statement period.
    Balances are integer paise; the period reuses the statement's start/end dates."""
    client_id: str
    bank_account_id: str
    statement_start_date: str
    statement_end_date: str
    # None (omitted) means "carry forward" — the service fills it from the last
    # completed reconciliation's closing balance. It used to default to 0, which
    # is only correct for a brand-new account and silently wrong for every other
    # period. An explicit 0 is still honoured.
    opening_balance_paise: Optional[int] = None
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
    # Migration 254 — the GST treatment of a charge from this bank. Constant per
    # bank, not derivable from the statement, so it is stated once here.
    suggested_gst_rate_bps: Optional[int] = None
    suggested_is_interstate: bool = False
    is_active: bool = True

    @field_validator("rule_name")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Rule name cannot be blank.")
        return v.strip()

    @field_validator("suggested_category")
    @classmethod
    def known_category(cls, v: Optional[str]) -> Optional[str]:
        return _validate_category(v)

    @field_validator("suggested_gst_rate_bps")
    @classmethod
    def known_gst_rate(cls, v: Optional[int]) -> Optional[int]:
        return _validate_gst_rate_bps(v)

    @field_validator("txn_type")
    @classmethod
    def known_txn_type(cls, v: str) -> str:
        return _validate_txn_type(v)

    @model_validator(mode="after")
    def coherent(self):
        return _validate_rule_shape(self)


class MatchingRuleUpdateIn(BaseModel):
    """Partial edit of an existing rule. Every field is optional; only the ones
    supplied are written. `client_id` is deliberately absent — see the router."""
    rule_name: Optional[str] = None
    description_pattern: Optional[str] = None
    amount_min_paise: Optional[int] = None
    amount_max_paise: Optional[int] = None
    txn_type: Optional[str] = None
    suggested_account_id: Optional[str] = None
    suggested_category: Optional[str] = None
    suggested_narration: Optional[str] = None
    suggested_gst_rate_bps: Optional[int] = None
    suggested_is_interstate: Optional[bool] = None
    is_active: Optional[bool] = None

    @field_validator("rule_name")
    @classmethod
    def not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Rule name cannot be blank.")
        return v.strip() if v is not None else None

    @field_validator("suggested_category")
    @classmethod
    def known_category(cls, v: Optional[str]) -> Optional[str]:
        return _validate_category(v)

    @field_validator("suggested_gst_rate_bps")
    @classmethod
    def known_gst_rate(cls, v: Optional[int]) -> Optional[int]:
        return _validate_gst_rate_bps(v)

    @field_validator("txn_type")
    @classmethod
    def known_txn_type(cls, v: Optional[str]) -> Optional[str]:
        return _validate_txn_type(v) if v is not None else None

    @model_validator(mode="after")
    def coherent(self):
        # Only checks the fields actually supplied; a partial edit that omits one
        # side of the amount range is legitimate (the stored value stands).
        if (self.amount_min_paise is not None and self.amount_max_paise is not None
                and self.amount_min_paise > self.amount_max_paise):
            raise ValueError("Minimum amount cannot exceed the maximum amount.")
        return self


# ── Shared matching-rule validation ─────────────────────────────────────────
# A rule's suggested_category lands on bank_transactions.category, which carries
# a DB CHECK against the controlled vocabulary (domain.banking.categories). An
# unvalidated rule therefore stored fine and then failed at the moment the CA
# tried to accept it — validate at the point the rule is written instead.

_RULE_TXN_TYPES = frozenset({"debit", "credit", "any"})


def _validate_category(v: Optional[str]) -> Optional[str]:
    if v is None or not str(v).strip():
        return None
    from domain.banking import CATEGORIES, is_valid_category
    value = str(v).strip()
    if not is_valid_category(value):
        raise ValueError(f"Invalid category. Allowed: {', '.join(CATEGORIES)}")
    return value


def _validate_txn_type(v: str) -> str:
    value = (v or "any").strip().lower()
    if value not in _RULE_TXN_TYPES:
        raise ValueError("txn_type must be one of: debit, credit, any.")
    return value


def _validate_gst_rate_bps(v: Optional[int]) -> Optional[int]:
    """A closed vocabulary, matching migration 254's CHECK and charge_gst's
    ALLOWED_RATES_BPS. None means "no GST split"; 0 means "this charge carries no
    GST", which is a different statement and stays distinguishable. A typo in a
    tax head becomes a wrong GSTR-3B, so an arbitrary integer is not accepted."""
    if v is None:
        return None
    from domain.banking import CHARGE_GST_RATES_BPS
    value = int(v)
    if value not in CHARGE_GST_RATES_BPS:
        raise ValueError(
            "Invalid GST rate. Allowed (basis points): "
            + ", ".join(str(r) for r in CHARGE_GST_RATES_BPS))
    return value


def _validate_rule_shape(rule) -> object:
    lo, hi = rule.amount_min_paise, rule.amount_max_paise
    if lo is not None and hi is not None and lo > hi:
        raise ValueError("Minimum amount cannot exceed the maximum amount.")
    if not any([rule.description_pattern, lo is not None, hi is not None,
                (rule.txn_type or "any") != "any"]):
        # A rule with no conditions fires on EVERY transaction, which is never
        # what anyone means and would mask every rule created after it.
        raise ValueError(
            "A rule needs at least one condition — a description pattern, an "
            "amount range, or a debit/credit restriction.")
    if not any([rule.suggested_category, rule.suggested_account_id, rule.suggested_narration]):
        raise ValueError(
            "A rule needs at least one suggestion — a category, an account, or a narration.")
    if rule.suggested_gst_rate_bps is not None and not rule.suggested_account_id:
        # The GST split books the EX-TAX amount to the counter account, so
        # without one there is nowhere for it to go and the post would fail at
        # the last step. Migration 254 carries the same CHECK; catching it here
        # gives the CA the error while they still have the rule form open.
        raise ValueError(
            "A GST rate needs an expense account to code the charge to — "
            "the split books the ex-tax amount there.")
    if rule.suggested_gst_rate_bps is not None and (rule.txn_type or "any") == "credit":
        # Money ARRIVING is not a bank charge. A credit-only rule carrying a GST
        # rate can never fire on anything the posting engine would split.
        raise ValueError(
            "A GST rate applies to bank charges — money leaving the account. "
            "Set the rule to debit (or any), not credit.")
    return rule
