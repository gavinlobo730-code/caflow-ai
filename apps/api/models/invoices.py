"""
Pydantic request models for sales invoices, purchase bills, receipts, and payments.
CGST Act §31: Tax invoice mandatory fields.
CGST §8: CGST+SGST (intra-state), IGST (inter-state).
All monetary values in integer paise.
"""
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional, Any


class InvoiceLineIn(BaseModel):
    """Single line on a sales invoice or purchase bill."""
    description: str
    hsn_sac: Optional[str] = None
    quantity: float = 1.0
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
    lines: list[InvoiceLineIn]
    reference_no: Optional[str] = None
    notes: Optional[str] = None
    is_inter_state: bool = False

    @field_validator("lines")
    @classmethod
    def at_least_one_line(cls, v: list) -> list:
        if not v:
            raise ValueError("Invoice must have at least one line.")
        return v


class SalesInvoiceUpdateIn(BaseModel):
    """Partial update of a draft sales invoice."""
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
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
    """Create a customer receipt. Auto-creates journal Dr Bank / Cr Trade Receivables."""
    client_id: str
    customer_id: str
    receipt_date: str  # YYYY-MM-DD
    amount_paise: int
    payment_mode: str = "bank_transfer"
    bank_account_id: Optional[str] = None
    reference_no: Optional[str] = None
    notes: Optional[str] = None
    allocations: list[ReceiptAllocationIn] = []

    @field_validator("amount_paise")
    @classmethod
    def positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Receipt amount must be positive.")
        return v

    @model_validator(mode="after")
    def allocations_dont_exceed_amount(self) -> "ReceiptIn":
        total = sum(a.allocated_paise for a in self.allocations)
        if total > self.amount_paise:
            raise ValueError(
                f"Total allocated ({total} paise) exceeds receipt amount ({self.amount_paise} paise)."
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
    payment_mode: str = "bank_transfer"
    bank_account_id: Optional[str] = None
    reference_no: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("amount_paise")
    @classmethod
    def positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Payment amount must be positive.")
        return v
