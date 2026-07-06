"""
Pydantic request models for sales invoices, purchase bills, receipts, and payments.
CGST Act §31: Tax invoice mandatory fields.
CGST §8: CGST+SGST (intra-state), IGST (inter-state).
All monetary values in integer paise.
"""
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional, Any
from decimal import Decimal


class InvoiceLineIn(BaseModel):
    """Single line on a sales invoice or purchase bill."""
    description: str
    hsn_sac: Optional[str] = None
    quantity: float = 1.0
    # Unit of measure (UQC), e.g. "NOS", "KGS", "HRS" — CGST Rule 46(h). The
    # client_sales_invoice_lines column and the create/update insert path
    # (routers/sales_invoices.py: `ln.get("unit", "NOS")`) already existed;
    # this field was the missing link — without it Pydantic silently dropped
    # any `unit` the frontend sent, so every line fell back to "NOS".
    unit: Optional[str] = None
    rate_paise: int
    gst_rate_percent: float = 18.0
    is_service: bool = False

    @field_validator("rate_paise")
    @classmethod
    def non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("rate_paise must be non-negative.")
        return v


class SalesInvoiceIn(BaseModel):
    """Create a new sales invoice. CGST Act §31."""
    client_id: str
    customer_id: str
    invoice_date: str  # YYYY-MM-DD
    due_date: Optional[str] = None
    # Optional override of the credit period (days). When neither due_date nor
    # credit_days is given, the customer's credit_days is used as the default and
    # the resulting due_date + credit_days are snapshotted onto the invoice.
    credit_days: Optional[int] = None
    lines: list[InvoiceLineIn]
    reference_no: Optional[str] = None
    notes: Optional[str] = None
    is_inter_state: bool = False
    # Optional display/override fields (CGST Rule 46 mandatory fields on tax invoice)
    customer_name: Optional[str] = None
    customer_gstin: Optional[str] = None
    place_of_supply: Optional[str] = None  # 2-digit state code
    supply_state_code: Optional[str] = None
    # Multi-Currency (Phase 3) — omit / 'INR' for a normal INR invoice. When a
    # foreign currency is given, line rate_paise are that currency's minor units;
    # exchange_rate is an optional manual override (else resolved via the service).
    currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = None

    @field_validator("lines")
    @classmethod
    def at_least_one_line(cls, v: list) -> list:
        if not v:
            raise ValueError("Invoice must have at least one line.")
        return v


class SalesInvoiceUpdateIn(BaseModel):
    """Partial update of a draft sales invoice."""
    customer_id: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    credit_days: Optional[int] = None
    supply_state_code: Optional[str] = None
    lines: Optional[list[InvoiceLineIn]] = None
    reference_no: Optional[str] = None
    notes: Optional[str] = None
    is_inter_state: Optional[bool] = None


class PurchaseBillLineIn(BaseModel):
    description: str
    hsn_sac: Optional[str] = None
    quantity: float = 1.0
    rate_paise: int
    gst_rate_percent: float = 18.0
    is_service: bool = False
    tds_applicable: bool = False
    expense_account_id: Optional[str] = None   # per-line expense classification (H10)

    @field_validator("rate_paise")
    @classmethod
    def non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("rate_paise must be non-negative.")
        return v


class PurchaseBillIn(BaseModel):
    """Create a purchase bill. IT Act §194C/194I/194J: TDS from vendor master."""
    client_id: str
    vendor_id: str
    bill_date: str  # YYYY-MM-DD
    due_date: Optional[str] = None
    bill_no: Optional[str] = None
    lines: list[PurchaseBillLineIn]
    notes: Optional[str] = None
    is_inter_state: bool = False
    is_reverse_charge: bool = False   # inward supply liable to RCM (CGST Act §9(3)/(4))
    # Multi-Currency (Phase 3) — omit / 'INR' for a normal INR bill. When a foreign
    # currency is given, line rate_paise are that currency's minor units.
    currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = None

    @field_validator("lines")
    @classmethod
    def at_least_one_line(cls, v: list) -> list:
        if not v:
            raise ValueError("Bill must have at least one line.")
        return v


class PurchaseBillUpdateIn(BaseModel):
    """Partial update of a draft purchase bill."""
    bill_date: Optional[str] = None
    due_date: Optional[str] = None
    bill_no: Optional[str] = None
    lines: Optional[list[PurchaseBillLineIn]] = None
    notes: Optional[str] = None
    is_inter_state: Optional[bool] = None


class BillFromDocumentIn(BaseModel):
    """Create a draft bill from AI-extracted document data. Always draft — CA must review."""
    client_id: str
    extracted_data: dict[str, Any] = {}


class ReceiptAllocationIn(BaseModel):
    sales_invoice_id: str
    allocated_paise: int

    @field_validator("allocated_paise")
    @classmethod
    def non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("allocated_paise must be non-negative.")
        return v


class ReceiptIn(BaseModel):
    """Create a customer receipt. Auto-creates journal Dr Bank (+ Dr TDS Receivable
    when tds_paise > 0) / Cr Trade Receivables. Settlement = amount_paise + tds_paise."""
    client_id: str
    customer_id: str
    receipt_date: str  # YYYY-MM-DD
    amount_paise: int
    tds_paise: int = 0          # TDS deducted by the client on the firm fee (IT Act §194J)
    # "bank_transfer" was never a valid value against the receipts.payment_mode
    # CHECK constraint (migration 050: bank/cash/cheque/upi/neft/rtgs/online,
    # widened by migration 161) — any caller relying on this default violated
    # it against a real database (R2.12 adversarial review). "bank" is correct.
    payment_mode: str = "bank"
    bank_account_id: Optional[str] = None
    reference_no: Optional[str] = None
    notes: Optional[str] = None
    allocations: list[ReceiptAllocationIn] = []
    # Multi-Currency (Phase 3) — must match the settled invoice's currency; amounts
    # are in that currency's minor units. Settlement uses the invoice's frozen rate.
    currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = None

    @field_validator("amount_paise")
    @classmethod
    def positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Receipt amount must be positive.")
        return v

    @field_validator("tds_paise")
    @classmethod
    def tds_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("tds_paise must be non-negative.")
        return v

    @model_validator(mode="after")
    def allocations_dont_exceed_settlement(self) -> "ReceiptIn":
        # Settlement capacity includes TDS deducted at source.
        total = sum(a.allocated_paise for a in self.allocations)
        settlement = self.amount_paise + self.tds_paise
        if total > settlement:
            raise ValueError(
                f"Total allocated ({total} paise) exceeds settlement value "
                f"({settlement} paise = amount {self.amount_paise} + TDS {self.tds_paise})."
            )
        return self


class ReceiptAllocationsUpdateIn(BaseModel):
    allocations: list[ReceiptAllocationIn]


class PurchasePaymentIn(BaseModel):
    """Record a vendor payment. TDS already deducted at bill stage — payment is net."""
    client_id: str
    vendor_id: str
    payment_date: str  # YYYY-MM-DD
    amount_paise: int
    purchase_bill_id: Optional[str] = None   # link to the bill being paid (AP sub-ledger)
    # "bank_transfer" was never a valid value against the purchase_payments.
    # payment_mode CHECK constraint (migration 050, widened by 161) — see the
    # identical fix on ReceiptIn.payment_mode above.
    payment_mode: str = "bank"
    bank_account_id: Optional[str] = None
    reference_no: Optional[str] = None
    notes: Optional[str] = None
    # Multi-Currency (Phase 3) — must match the settled bill's currency; amount is in
    # that currency's minor units. Settlement uses the bill's frozen rate.
    currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = None

    @field_validator("amount_paise")
    @classmethod
    def positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Payment amount must be positive.")
        return v
