"""
Pydantic request models for sales invoices, purchase bills, receipts, and payments.
CGST Act §31: Tax invoice mandatory fields.
CGST §8: CGST+SGST (intra-state), IGST (inter-state).
All monetary values in integer paise.
"""
import re
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional, Any
from decimal import Decimal

# CGST Rule 46(b): a tax invoice's serial number must be a consecutive serial
# number not exceeding sixteen characters, using only alphabets, numerals, and
# the special characters '-' and '/'. Caflow leaves the numbering SCHEME
# entirely to the CA (Decision: sales invoice numbers are fully manual, never
# auto-generated) — this only enforces the structural shape the law requires.
# Per-client uniqueness is checked separately in routers/sales_invoices.py,
# which needs DB access this pure model layer doesn't have.
_INVOICE_NO_RE = re.compile(r"^[A-Za-z0-9\-/]{1,16}$")


def _validate_invoice_no_shape(v: str) -> str:
    v = (v or "").strip()
    if not v:
        raise ValueError("Invoice number is required.")
    if not _INVOICE_NO_RE.match(v):
        raise ValueError(
            "Invoice number must be 1-16 characters using only letters, digits, '-' or '/' (CGST Rule 46(b))."
        )
    return v


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
    # Which service_catalogue preset (if any) this line was picked from —
    # pure traceability for the Products & Services delete-guard (real
    # "is this used on any invoice" check, mirroring how customer deletion
    # already checks real linked records). Never read by any GST/journal
    # computation directly: the line's own description/hsn_sac/rate are
    # always the authoritative values, copied at pick time. Shared by Sales
    # Invoices, Credit Notes and Debit Notes (all reuse this model) — for
    # goods items it's also how domain/inventory_service.py identifies a
    # line as a stock movement for a specific product (migrations 184/188/189).
    service_catalogue_id: Optional[str] = None

    @field_validator("rate_paise")
    @classmethod
    def non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("rate_paise must be non-negative.")
        return v

    @field_validator("unit")
    @classmethod
    def normalize_unit(cls, v: Optional[str]) -> Optional[str]:
        # Normalize only — do NOT reject values outside the official UQC list
        # (VALID_UQC_CODES). This field predates the UQC dropdown and existing
        # lines/products may carry a pre-existing free-text value (e.g. "HRS"
        # for service hours); rejecting it here would make an old line
        # un-editable for any unrelated field change. The dropdown (new UI)
        # only offers valid UQC codes, so new data is compliant by construction —
        # this validator just normalizes case/whitespace for whatever comes in.
        if v is None or v == "":
            return None
        return v.strip().upper()

    # model_validator (not field_validator) — Pydantic v2 skips field_validator
    # on a field that was simply omitted (uses its `= None` default) unless
    # validate_default=True; model_validator(mode="after") always runs, so
    # this is the only reliable way to reject "field left out entirely",
    # not just "field explicitly sent blank". Every Product/Service catalogue
    # link is now mandatory (decision: every line — including pure-expense/
    # service lines — must reference a catalogue item), covering Sales
    # Invoices, Credit Notes and Debit Notes at once since all three share
    # this model.
    @model_validator(mode="after")
    def require_service_catalogue_id(self) -> "InvoiceLineIn":
        if not self.service_catalogue_id or not self.service_catalogue_id.strip():
            raise ValueError("Product/Service is required on every line item.")
        return self


class SalesInvoiceIn(BaseModel):
    """Create a new sales invoice. CGST Act §31."""
    client_id: str
    customer_id: str
    # Fully manual (Decision: no Caflow-generated numbering scheme) — the CA
    # types it, Caflow only enforces the CGST Rule 46(b) shape here and
    # per-client uniqueness in the router.
    invoice_no: str
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

    @field_validator("invoice_no")
    @classmethod
    def _invoice_no_shape(cls, v: str) -> str:
        return _validate_invoice_no_shape(v)

    @field_validator("lines")
    @classmethod
    def at_least_one_line(cls, v: list) -> list:
        if not v:
            raise ValueError("Invoice must have at least one line.")
        return v


class SalesInvoiceUpdateIn(BaseModel):
    """Partial update of a sales invoice.

    Draft invoices: every field below is editable. Once issued, the router
    (routers/sales_invoices.py: update_invoice) only accepts reference_no,
    notes, due_date/credit_days and line_units — CGST Rule 46 tax-invoice
    content (invoice_no, dates, customer, line qty/rate/HSN/GST,
    is_inter_state) is locked post-issue; a correction to those must go
    through a Credit Note (CGST Act §34), not a silent edit.
    """
    customer_id: Optional[str] = None
    # Editable only while the invoice is a draft (enforced by the router,
    # which already blocks any update once issued) — same manual, CA-owned
    # numbering as SalesInvoiceIn.invoice_no.
    invoice_no: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    credit_days: Optional[int] = None
    supply_state_code: Optional[str] = None
    lines: Optional[list[InvoiceLineIn]] = None
    reference_no: Optional[str] = None
    notes: Optional[str] = None
    is_inter_state: Optional[bool] = None
    # {line_id: new unit} — unit alone never affects rate/quantity/amount/GST,
    # so it's allowed on an issued invoice unlike the rest of `lines` above
    # (a full line replace, draft-only). Handled separately in the router,
    # independent of every other field here.
    line_units: Optional[dict[str, str]] = None

    @field_validator("invoice_no")
    @classmethod
    def _invoice_no_shape(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _validate_invoice_no_shape(v)

    @field_validator("line_units")
    @classmethod
    def _normalize_line_units(cls, v: Optional[dict[str, str]]) -> Optional[dict[str, str]]:
        # Same lenient normalize-only rule as InvoiceLineIn.unit above — see
        # that validator's comment for why values are never rejected.
        if v is None:
            return None
        return {k: (val.strip().upper() if val else val) for k, val in v.items()}


class PurchaseBillLineIn(BaseModel):
    description: str
    hsn_sac: Optional[str] = None
    quantity: float = 1.0
    # Unit of measure (UQC), e.g. "NOS", "KGS" — migration 190. purchase_bill_lines
    # had no unit column at all until now, unlike client_sales_invoice_lines/
    # credit_note_lines/debit_note_lines, which all share InvoiceLineIn.unit.
    unit: Optional[str] = None
    rate_paise: int
    gst_rate_percent: float = 18.0
    is_service: bool = False
    tds_applicable: bool = False
    expense_account_id: Optional[str] = None   # per-line expense classification (H10)
    # Which service_catalogue preset (if any) this line restocks — required so
    # a received bill line can be identified as a stock-in movement for a
    # specific item (domain/inventory_service.apply_purchase_to_inventory).
    # Pure traceability like InvoiceLineIn's own field: never read by any
    # GST/journal computation, only by the inventory costing engine.
    service_catalogue_id: Optional[str] = None

    @field_validator("rate_paise")
    @classmethod
    def non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("rate_paise must be non-negative.")
        return v

    @field_validator("unit")
    @classmethod
    def normalize_unit(cls, v: Optional[str]) -> Optional[str]:
        # Same lenient normalize-only rule as InvoiceLineIn.unit — see that
        # validator's comment for why values are never rejected.
        if v is None or v == "":
            return None
        return v.strip().upper()

    # See InvoiceLineIn.require_service_catalogue_id — model_validator, not
    # field_validator, for the same "must fire even when the field is
    # omitted, not just sent blank" reason.
    @model_validator(mode="after")
    def require_service_catalogue_id(self) -> "PurchaseBillLineIn":
        if not self.service_catalogue_id or not self.service_catalogue_id.strip():
            raise ValueError("Product/Service is required on every line item.")
        return self


class PurchaseBillIn(BaseModel):
    """Create a purchase bill. IT Act §194C/194I/194J: TDS from vendor master."""
    client_id: str
    vendor_id: str
    bill_date: str  # YYYY-MM-DD
    due_date: Optional[str] = None
    # Optional override of the credit period (days). When neither due_date nor
    # credit_days is given, the vendor's credit_days is used as the default and
    # the resulting due_date + credit_days are snapshotted onto the bill.
    # Mirrors SalesInvoiceIn.credit_days.
    credit_days: Optional[int] = None
    bill_no: Optional[str] = None
    # The firm's OWN internal reference/tracking number for this bill —
    # distinct from bill_no (the vendor's own document number). Optional,
    # firm-set, never validated against anything external.
    our_reference: Optional[str] = None
    lines: list[PurchaseBillLineIn]
    notes: Optional[str] = None
    is_inter_state: bool = False
    is_reverse_charge: bool = False   # inward supply liable to RCM (CGST Act §9(3)/(4))
    # Multi-Currency (Phase 3) — omit / 'INR' for a normal INR bill. When a foreign
    # currency is given, line rate_paise are that currency's minor units.
    currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = None
    # Supabase Storage PATH (not a signed URL — those expire) of the original
    # uploaded invoice, set by document-intelligence-v1's extract-invoice
    # response. Retained as ITC/audit evidence — CGST Rule 36(1) conditions
    # ITC on possession of the vendor's tax invoice.
    document_url: Optional[str] = None

    @field_validator("lines")
    @classmethod
    def at_least_one_line(cls, v: list) -> list:
        if not v:
            raise ValueError("Bill must have at least one line.")
        return v


class PurchaseBillUpdateIn(BaseModel):
    """Partial update of a purchase bill.

    Draft bills: every field below is editable. Once received (or later),
    the router (routers/purchase_bills.py: update_purchase_bill) only
    accepts our_reference, notes, due_date, credit_days, document_url and
    line_units — bill_no, bill_date, lines and is_inter_state are locked
    post-receipt, matching the same rule applied to sales invoices
    (routers/sales_invoices.py).
    """
    bill_date: Optional[str] = None
    due_date: Optional[str] = None
    credit_days: Optional[int] = None
    bill_no: Optional[str] = None
    our_reference: Optional[str] = None
    lines: Optional[list[PurchaseBillLineIn]] = None
    notes: Optional[str] = None
    is_inter_state: Optional[bool] = None
    # Attach (or replace) the original invoice after the bill was already
    # created — e.g. the CA scans a paper copy later. See PurchaseBillIn.
    document_url: Optional[str] = None
    # {line_id: new unit} — always allowed regardless of status, same
    # rationale as SalesInvoiceUpdateIn.line_units above.
    line_units: Optional[dict[str, str]] = None

    @field_validator("line_units")
    @classmethod
    def _normalize_line_units(cls, v: Optional[dict[str, str]]) -> Optional[dict[str, str]]:
        if v is None:
            return None
        return {k: (val.strip().upper() if val else val) for k, val in v.items()}


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
