"""
Document-level currency resolution + validation for foreign business documents
(Multi-Currency Phase 3).

One backend place that turns a document's requested currency + optional manual
rate into a frozen, validated `DocumentCurrency`, enforcing every Task-6
validation. INR (or feature-off / inactive policy) resolves to the inert identity,
so existing INR documents are byte-for-byte unchanged. Currency-mismatch checks
for settlement (receipt/payment vs its document) live in those flows.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import HTTPException

from domain.currency.policy import BASE_CURRENCY, resolve_currency_policy
from domain.currency.rate_types import DEFAULT_RATE_TYPE
from domain.currency.conversion import to_base_minor, to_txn_minor
from domain.currency import currency_service


@dataclass(frozen=True)
class DocumentCurrency:
    """Frozen, validated currency context for one document."""
    is_foreign: bool
    currency: str
    rate: Decimal
    minor_unit: int
    rate_source: str
    rate_type: str
    rate_date: str
    rate_selected_by: Optional[str]
    rate_overridden: bool

    def to_base(self, txn_minor: int) -> int:
        """Convert a txn-currency minor-unit amount to base paise at the frozen rate."""
        return to_base_minor(int(txn_minor or 0), self.rate, self.minor_unit)

    def to_txn(self, base_minor: int) -> int:
        """Express a base-paise amount in txn minor units (memo only)."""
        return to_txn_minor(int(base_minor or 0), self.rate, self.minor_unit)


def identity_currency(rate_date: Optional[str] = None) -> DocumentCurrency:
    """The inert INR identity — used for every INR document and whenever the policy
    is inactive. rate 1, no conversion, no provenance."""
    return DocumentCurrency(
        is_foreign=False, currency=BASE_CURRENCY, rate=Decimal(1), minor_unit=2,
        rate_source="identity", rate_type=DEFAULT_RATE_TYPE,
        rate_date=rate_date or _date.today().isoformat(),
        rate_selected_by=None, rate_overridden=False,
    )


def document_currency_from_row(db, row: dict) -> DocumentCurrency:
    """Reconstruct the frozen DocumentCurrency from a stored document row (invoice,
    bill, receipt, payment). INR rows — and rows created before Phase 3 that lack the
    columns — resolve to the inert identity. Used by the journal services at posting
    time to stamp per-line foreign amounts; the rate is read back exactly, never
    recalculated (G3)."""
    ccy = (row.get("txn_currency") or BASE_CURRENCY).strip().upper()
    rate_date = (row.get("rate_date") or "") or None
    if ccy == BASE_CURRENCY:
        return identity_currency(str(rate_date)[:10] if rate_date else None)
    rate = row.get("exchange_rate")
    rate = Decimal(str(rate)) if rate is not None else Decimal(1)
    minor = 2
    cur = currency_service.get_currency(db, ccy)
    if cur and cur.get("minor_unit") is not None:
        minor = int(cur["minor_unit"])
    return DocumentCurrency(
        is_foreign=True, currency=ccy, rate=rate, minor_unit=minor,
        rate_source=row.get("rate_source") or "manual", rate_type=row.get("rate_type") or DEFAULT_RATE_TYPE,
        rate_date=(str(rate_date)[:10] if rate_date else _date.today().isoformat()),
        rate_selected_by=row.get("rate_selected_by"),
        rate_overridden=bool(row.get("rate_overridden")),
    )


def resolve_document_currency(
    db,
    firm: Optional[dict],
    client: Optional[dict],
    *,
    currency: Optional[str],
    exchange_rate=None,
    rate_date: Optional[str] = None,
    rate_selected_by: Optional[str] = None,
    rate_service=None,
) -> DocumentCurrency:
    """Resolve + validate the currency for a business document (Task 6). Returns the
    inert INR identity for INR / feature-off; otherwise validates and freezes a
    foreign rate. Raises HTTP 422 on any validation failure — all backend-side."""
    req = (currency or BASE_CURRENCY).strip().upper()
    r_date = (rate_date or _date.today().isoformat())[:10]

    # INR (or unspecified) → identity: existing behaviour, zero overhead.
    if req == BASE_CURRENCY:
        return identity_currency(r_date)

    # Gate (G2): a non-INR document requires env + firm entitlement + client enable.
    policy = resolve_currency_policy(firm, client)
    if not policy.active:
        raise HTTPException(status_code=422, detail=(
            "Multi-currency is not enabled for this client. Enable the platform flag, "
            "the firm entitlement and the client's multi-currency setting before "
            "creating a foreign-currency document."))

    # Currency must exist and be active in the ISO 4217 master.
    row = currency_service.get_currency(db, req)
    if not row:
        raise HTTPException(status_code=422, detail=f"Unsupported currency: {req}.")
    if not row.get("is_active", True):
        raise HTTPException(status_code=422, detail=f"Currency {req} is inactive.")
    minor_unit = int(row.get("minor_unit", 2))

    overridden = exchange_rate is not None
    if overridden:
        try:
            rate = Decimal(str(exchange_rate))
        except (InvalidOperation, ValueError, TypeError):
            raise HTTPException(status_code=422, detail="Invalid exchange rate.")
        source = "manual-override"
    else:
        svc = rate_service
        if svc is None:
            from services.phase2_journal_service import phase2_journal_service
            svc = phase2_journal_service.exchange_rate_service(db)
        from domain.currency import RateNotFound
        try:
            quote = svc.get_quote(req, BASE_CURRENCY, _date.fromisoformat(r_date), DEFAULT_RATE_TYPE)
        except RateNotFound:
            raise HTTPException(status_code=422, detail=(
                f"No exchange rate available for {req}->{BASE_CURRENCY} on {r_date}. "
                "Record the rate first or enter it manually."))
        rate = quote.rate
        source = quote.source

    if rate <= 0:
        raise HTTPException(status_code=422, detail="Exchange rate must be a positive number.")

    return DocumentCurrency(
        is_foreign=True, currency=req, rate=rate, minor_unit=minor_unit,
        rate_source=source, rate_type=DEFAULT_RATE_TYPE, rate_date=r_date,
        rate_selected_by=rate_selected_by, rate_overridden=overridden,
    )
