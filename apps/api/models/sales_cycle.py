"""Request models for the sales cycle BEFORE the tax invoice (SALES-21).

Every one of these documents is validated at BOTH doors — create and update —
because a validator on one door is one PATCH away from being none, which is
the shape ACC-25 and GST-29 both turned out to be.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from domain.gst import delivery_challan as dc
from domain.gst.gstin import problem_with
from domain.gst.invoice_series import format_violation
from domain.gst.validator import VALID_STATE_CODES
from domain.quantity import quantity_violation
from domain.sales import order_cycle as oc


def _document_no(v: str) -> str:
    """Rule 46(b)'s shape, imposed on documents the rule does not reach.

    A quotation becomes an invoice, and a number that cannot be a tax-invoice
    number is a conversion that fails at the last step — after the customer
    has the quotation. Rule 55(1) puts the SAME sixteen-character limit on a
    delivery challan, where it is the rule itself rather than a convenience.
    """
    v = (v or "").strip()
    if not v:
        raise ValueError("The document number cannot be blank.")
    violation = format_violation(v)
    if violation:
        raise ValueError(violation)
    return v


def _state(v):
    if v is None or v == "":
        return None
    code = str(v).strip()
    if code not in VALID_STATE_CODES:
        raise ValueError(
            f"{code!r} is not a state code. The place of supply is a two-digit "
            f"state code (CGST s.25 and the IGST Act's own list).")
    return code


def _gstin(v):
    """The COUNTERPARTY's GSTIN, check digit and all.

    GST-29's lesson: a valid-SHAPED wrong GSTIN sends the credit to whoever it
    names, and on the sales side that is a stranger, correctable only by an
    amendment inside the s.37(3) window. A quotation's GSTIN becomes the
    invoice's, so it is checked here rather than at the end of the chain.
    """
    if v is None or v == "":
        return None
    problem = problem_with(str(v).strip().upper())
    if problem:
        raise ValueError(problem)
    return str(v).strip().upper()


class PreInvoiceLineIn(BaseModel):
    """One line of a quotation, proforma, order or challan."""
    model_config = ConfigDict(from_attributes=True)

    description: str
    hsn_sac: Optional[str] = None
    quantity: float = 1.0
    unit: Optional[str] = None
    rate_paise: int = 0
    gst_rate_percent: float = 18.0

    @field_validator("gst_rate_percent")
    @classmethod
    def _gst_rate_is_a_rate(cls, v: float) -> float:
        """Delegates to `domain/gst/rate_bounds` — one level of indirection, the
        shape `models/invoices._validate_quantity` already uses, so the rule
        lives once and a reader here is pointed at it."""
        from domain.gst.rate_bounds import rate_percent_violation
        problem = rate_percent_violation(v)
        if problem:
            raise ValueError(problem)
        return v
    is_service: bool = False
    service_catalogue_id: Optional[str] = None
    # CGST s.15(3)(a). Present here because a quotation that offered a discount
    # and an invoice that did not is the commonest complaint a customer makes.
    discount_percent_bps: Optional[int] = None
    discount_paise: Optional[int] = None
    # GST (Compensation to States) Act s.8(2), both limbs.
    cess_rate_bps: Optional[int] = None
    cess_specific_paise_per_unit: Optional[int] = None
    # Rule 55(1)(v), and only meaningful on a challan. Carried on the shared
    # line model because a quotation converted to a challan keeps its lines.
    quantity_is_provisional: bool = False
    # Which order line this delivers against, on a challan raised from an order.
    order_line_id: Optional[str] = None

    @field_validator("description")
    @classmethod
    def _described(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("Every line needs a description.")
        return v.strip()

    @field_validator("quantity")
    @classmethod
    def _qty(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("quantity must be positive.")
        problem = quantity_violation(v)
        if problem:
            raise ValueError(problem)
        return v

    @field_validator("rate_paise")
    @classmethod
    def _rate(cls, v: int) -> int:
        if v < 0:
            raise ValueError("rate_paise must be non-negative.")
        return v

    @field_validator("discount_percent_bps")
    @classmethod
    def _disc_pct(cls, v):
        if v is not None and (v < 0 or v > 10_000):
            raise ValueError("discount_percent_bps must be between 0 and 10000.")
        return v

    @field_validator("discount_paise", "cess_rate_bps",
                     "cess_specific_paise_per_unit")
    @classmethod
    def _non_negative(cls, v):
        if v is not None and v < 0:
            raise ValueError("This figure must be non-negative.")
        return v


class _PreInvoiceHeader(BaseModel):
    document_no: str
    document_date: str
    customer_name: Optional[str] = None
    customer_gstin: Optional[str] = None
    place_of_supply: Optional[str] = None
    supply_state_code: Optional[str] = None
    is_inter_state: bool = False
    currency: Optional[str] = None
    notes: Optional[str] = None
    # Document-level s.15(3)(a) discount, allocated pro-rata across the lines
    # before tax — the same treatment the invoice gives it, because GST is
    # charged per line at the line's own rate.
    discount_percent_bps: Optional[int] = None
    discount_paise: Optional[int] = None

    @field_validator("document_no")
    @classmethod
    def _no(cls, v: str) -> str:
        return _document_no(v)

    @field_validator("place_of_supply", "supply_state_code")
    @classmethod
    def _pos(cls, v):
        return _state(v)

    @field_validator("customer_gstin")
    @classmethod
    def _gst(cls, v):
        return _gstin(v)

    @model_validator(mode="after")
    def _states_agree(self):
        # SALES-31's rule, on the document that becomes the invoice. A request
        # whose two state fields disagree is refused rather than silently
        # resolved one way, because which one the caller meant is unknowable.
        a, b = self.place_of_supply, self.supply_state_code
        if a and b and a != b:
            raise ValueError(
                f"place_of_supply {a!r} and supply_state_code {b!r} disagree. "
                f"Send one, or send two that agree.")
        return self


class QuotationIn(_PreInvoiceHeader):
    """A quotation or a proforma invoice. NEITHER IS A TAX INVOICE."""
    client_id: str
    customer_id: str
    kind: str = oc.KIND_QUOTATION
    valid_until: Optional[str] = None
    lines: list = []

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        k = (v or "").strip().lower()
        if k not in oc.QUOTE_KINDS:
            raise ValueError(
                f"kind must be one of {', '.join(oc.QUOTE_KINDS)} — a quotation "
                f"is an offer and a proforma invoice is the same offer "
                f"formatted for a payment. Neither is a tax invoice.")
        return k

    @model_validator(mode="after")
    def _has_lines(self):
        if not self.lines:
            raise ValueError("A quotation needs at least one line.")
        return self


class QuotationUpdateIn(BaseModel):
    """Amend a quotation. Every field optional; `None` means unchanged."""
    document_no: Optional[str] = None
    document_date: Optional[str] = None
    valid_until: Optional[str] = None
    status: Optional[str] = None
    customer_name: Optional[str] = None
    customer_gstin: Optional[str] = None
    place_of_supply: Optional[str] = None
    supply_state_code: Optional[str] = None
    is_inter_state: Optional[bool] = None
    notes: Optional[str] = None
    discount_percent_bps: Optional[int] = None
    discount_paise: Optional[int] = None
    #: An empty list REPLACES the lines with none, which is refused by the
    #: service; `None` means leave them alone.
    lines: Optional[list] = None

    @field_validator("document_no")
    @classmethod
    def _no(cls, v):
        return _document_no(v) if v is not None else None

    @field_validator("place_of_supply", "supply_state_code")
    @classmethod
    def _pos(cls, v):
        return _state(v)

    @field_validator("customer_gstin")
    @classmethod
    def _gst(cls, v):
        return _gstin(v)

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v is None:
            return None
        if v not in oc.QUOTE_STATUSES:
            raise ValueError(f"status must be one of {', '.join(oc.QUOTE_STATUSES)}.")
        return v


class SalesOrderIn(_PreInvoiceHeader):
    """The customer's acceptance. CGST s.7 charges a supply; this is a promise."""
    client_id: str
    customer_id: str
    customer_po_no: Optional[str] = None
    customer_po_date: Optional[str] = None
    expected_delivery_date: Optional[str] = None
    quotation_id: Optional[str] = None
    lines: list = []

    @model_validator(mode="after")
    def _has_lines(self):
        if not self.lines:
            raise ValueError("A sales order needs at least one line.")
        return self


class SalesOrderUpdateIn(BaseModel):
    document_no: Optional[str] = None
    document_date: Optional[str] = None
    customer_po_no: Optional[str] = None
    customer_po_date: Optional[str] = None
    expected_delivery_date: Optional[str] = None
    status: Optional[str] = None
    customer_name: Optional[str] = None
    customer_gstin: Optional[str] = None
    place_of_supply: Optional[str] = None
    supply_state_code: Optional[str] = None
    is_inter_state: Optional[bool] = None
    notes: Optional[str] = None
    discount_percent_bps: Optional[int] = None
    discount_paise: Optional[int] = None
    lines: Optional[list] = None

    @field_validator("document_no")
    @classmethod
    def _no(cls, v):
        return _document_no(v) if v is not None else None

    @field_validator("place_of_supply", "supply_state_code")
    @classmethod
    def _pos(cls, v):
        return _state(v)

    @field_validator("customer_gstin")
    @classmethod
    def _gst(cls, v):
        return _gstin(v)

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v is None:
            return None
        if v not in oc.ORDER_STATUSES:
            raise ValueError(f"status must be one of {', '.join(oc.ORDER_STATUSES)}.")
        return v


class DeliveryChallanIn(BaseModel):
    """CGST Rule 55 — goods moved without a tax invoice.

    DELIBERATELY NOT a subclass of `_PreInvoiceHeader`. A challan's
    counterparty is the CONSIGNEE, which Rule 55(1)(iii) names as its own
    particular and which is often not the customer at all — a job-work
    despatch goes to a vendor and a movement "other than by way of supply" may
    go to the client's own second premises. Inheriting `customer_name`,
    `customer_gstin` and the s.15(3)(a) document discount would put four
    fields on the model that Rule 55 has no place for, and a caller filling
    one in would have it silently dropped.
    """
    client_id: str
    #: NULLABLE on purpose, for the reason above.
    customer_id: Optional[str] = None
    vendor_id: Optional[str] = None
    document_no: str
    document_date: str
    reason: str
    goods_kind: Optional[str] = None
    extended_to: Optional[str] = None
    sales_invoice_id: Optional[str] = None
    order_id: Optional[str] = None
    consignee_name: Optional[str] = None
    consignee_gstin: Optional[str] = None
    consignee_address: Optional[str] = None
    transporter_name: Optional[str] = None
    transporter_id: Optional[str] = None
    vehicle_no: Optional[str] = None
    place_of_supply: Optional[str] = None
    is_inter_state: bool = False
    notes: Optional[str] = None
    lines: list = []

    @field_validator("document_no")
    @classmethod
    def _no(cls, v: str) -> str:
        return _document_no(v)

    @field_validator("place_of_supply")
    @classmethod
    def _pos(cls, v):
        return _state(v)

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        r = (v or "").strip().lower()
        if r not in dc.REASONS:
            raise ValueError(
                "A delivery challan states which of Rule 55's movements it "
                "covers: " + ", ".join(dc.REASONS) + ".")
        return r

    @field_validator("goods_kind")
    @classmethod
    def _goods_kind(cls, v):
        if v is None or v == "":
            return None
        k = str(v).strip().lower()
        if k not in dc.GOODS_KINDS:
            raise ValueError(
                "goods_kind is one of " + ", ".join(dc.GOODS_KINDS) + " — CGST "
                "s.143 runs one year for inputs and three for capital goods, "
                "and moulds, dies, jigs, fixtures and tools are outside both.")
        return k

    @field_validator("consignee_gstin")
    @classmethod
    def _consignee_gst(cls, v):
        return _gstin(v)

    @model_validator(mode="after")
    def _rule_55_shape(self):
        if not self.lines:
            raise ValueError("A delivery challan needs at least one line.")
        # The database CHECKs both of these too. They are refused HERE as well
        # so the CA gets the sentence rather than a constraint-violation 500 —
        # and so the rule is stated where a reader of the model can see it.
        if self.goods_kind and self.reason != dc.REASON_JOB_WORK:
            raise ValueError(
                "Only a job-work movement carries a kind of goods: CGST s.143 "
                "reaches goods sent to a job worker and nothing else, so "
                "recording one here would assert a clock that does not run.")
        if self.extended_to and self.reason != dc.REASON_JOB_WORK:
            raise ValueError(
                "An extension under the proviso to s.143(1) applies to a "
                "job-work movement only.")
        return self


class DeliveryChallanUpdateIn(BaseModel):
    """Amend a challan. `None` means unchanged.

    `reason`, `order_id`, `customer_id` and `vendor_id` are absent on purpose
    and recorded in the editability guard's immutable map with their reasons.
    """
    document_no: Optional[str] = None
    document_date: Optional[str] = None
    status: Optional[str] = None
    goods_kind: Optional[str] = None
    #: When the goods came back. This is the field the whole s.143 clock turns
    #: off, so it is on the update door and never on create: a challan is
    #: raised when the goods LEAVE.
    received_back_on: Optional[str] = None
    extended_to: Optional[str] = None
    sales_invoice_id: Optional[str] = None
    consignee_name: Optional[str] = None
    consignee_gstin: Optional[str] = None
    consignee_address: Optional[str] = None
    transporter_name: Optional[str] = None
    transporter_id: Optional[str] = None
    vehicle_no: Optional[str] = None
    place_of_supply: Optional[str] = None
    is_inter_state: Optional[bool] = None
    notes: Optional[str] = None
    lines: Optional[list] = None

    @field_validator("document_no")
    @classmethod
    def _no(cls, v):
        return _document_no(v) if v is not None else None

    @field_validator("place_of_supply")
    @classmethod
    def _pos(cls, v):
        return _state(v)

    @field_validator("consignee_gstin")
    @classmethod
    def _gst(cls, v):
        return _gstin(v)

    @field_validator("goods_kind")
    @classmethod
    def _goods_kind(cls, v):
        if v is None or v == "":
            return None
        k = str(v).strip().lower()
        if k not in dc.GOODS_KINDS:
            raise ValueError("goods_kind is one of " + ", ".join(dc.GOODS_KINDS) + ".")
        return k

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v is None:
            return None
        if v not in oc.CHALLAN_STATUSES:
            raise ValueError(f"status must be one of {', '.join(oc.CHALLAN_STATUSES)}.")
        return v
