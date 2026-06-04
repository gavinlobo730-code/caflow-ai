"""GST payload validator — enforces GSTN filing rules.

CGST Act Section 25: GSTIN format and uniqueness.
CGST Rule 46: Mandatory fields on tax invoice.
CGST Act Section 37(3): Amendment window (invoice date within return period or previous month).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

# CGST Act Section 25 — GSTIN format: 2-digit state + PAN + entity + Z + checksum
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

# Valid Indian state/UT codes (GSTN uses 01–38 with some gaps)
VALID_STATE_CODES = {
    "01", "02", "03", "04", "05", "06", "07", "08", "09", "10",
    "11", "12", "13", "14", "15", "16", "17", "18", "19", "20",
    "21", "22", "23", "24", "25", "26", "27", "28", "29", "30",
    "31", "32", "33", "34", "35", "36", "37", "38",
    "96",  # outside India (export)
    "97",  # other territory
}

# GSTN period format: MMYYYY
PERIOD_RE = re.compile(r"^(0[1-9]|1[0-2])\d{4}$")

# Tax tolerance — GSTN accepts ±1 paise rounding difference per line
TAX_TOLERANCE_PAISE = 1


@dataclass
class ValidationError:
    field: str
    message: str
    invoice_ref: str | None = None
    severity: str = "error"  # "error" | "warning"

    def as_dict(self) -> dict:
        return {
            "field": self.field,
            "message": self.message,
            "invoice_ref": self.invoice_ref,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class InvoiceToValidate:
    """Minimal fields needed for GSTR-1 validation."""
    reference_no: str
    transaction_date: str       # YYYY-MM-DD
    party_gstin: str | None
    place_of_supply: str | None
    taxable_amount_paise: int
    cgst_paise: int
    sgst_paise: int
    igst_paise: int
    is_interstate: bool
    gst_rate: float | None      # overall header rate if available


class GSTValidator:
    """Validates GSTN data before payload generation."""

    def validate_gstin(self, gstin: str) -> list[ValidationError]:
        """Validate GSTIN format — CGST Act Section 25."""
        if not gstin:
            return [ValidationError("gstin", "GSTIN is required")]
        if not GSTIN_RE.match(gstin):
            return [ValidationError("gstin", f"Invalid GSTIN format: {gstin}. "
                                    "Expected: 2-digit state code + PAN + entity number + Z + checksum")]
        return []

    def validate_period(self, period: str) -> list[ValidationError]:
        """Validate filing period format MMYYYY."""
        if not PERIOD_RE.match(period):
            return [ValidationError("period", f"Invalid period format: {period}. Expected MMYYYY e.g. 052025")]
        return []

    def validate_invoice(self, inv: InvoiceToValidate, period: str) -> list[ValidationError]:
        """Validate a single invoice for GSTR-1 compliance."""
        errors: list[ValidationError] = []
        ref = inv.reference_no

        # Invoice number must be present
        if not ref or not ref.strip():
            errors.append(ValidationError("reference_no", "Invoice number is required", ref))

        # Place of supply must be valid state code
        pos = inv.place_of_supply or ""
        if pos not in VALID_STATE_CODES:
            errors.append(ValidationError(
                "place_of_supply",
                f"Invalid place of supply code: '{pos}'. Must be a valid 2-digit state code.",
                ref,
            ))

        # Party GSTIN format if provided
        if inv.party_gstin and not GSTIN_RE.match(inv.party_gstin):
            errors.append(ValidationError(
                "party_gstin",
                f"Invalid receiver GSTIN: {inv.party_gstin}",
                ref,
            ))

        # CGST must equal SGST for intra-state supplies
        if not inv.is_interstate and inv.cgst_paise != inv.sgst_paise:
            errors.append(ValidationError(
                "cgst_sgst",
                f"CGST ({inv.cgst_paise}p) must equal SGST ({inv.sgst_paise}p) for intra-state supply",
                ref,
            ))

        # IGST must be zero for intra-state, non-zero for inter-state (if taxable)
        if not inv.is_interstate and inv.igst_paise > 0:
            errors.append(ValidationError(
                "igst",
                f"IGST must be 0 for intra-state supply. Found {inv.igst_paise}p",
                ref,
            ))
        if inv.is_interstate and (inv.cgst_paise > 0 or inv.sgst_paise > 0):
            errors.append(ValidationError(
                "cgst_sgst",
                "CGST and SGST must be 0 for inter-state supply",
                ref,
            ))

        # Tax arithmetic check — CGST Act Section 15 (value of supply)
        if inv.gst_rate is not None and inv.gst_rate > 0 and inv.taxable_amount_paise > 0:
            expected_total_tax = round(inv.taxable_amount_paise * inv.gst_rate / 100)
            actual_total_tax = inv.cgst_paise + inv.sgst_paise + inv.igst_paise
            if abs(actual_total_tax - expected_total_tax) > TAX_TOLERANCE_PAISE:
                errors.append(ValidationError(
                    "tax_amount",
                    f"Tax amount mismatch: computed ₹{expected_total_tax/100:.2f} at {inv.gst_rate}%, "
                    f"stored ₹{actual_total_tax/100:.2f}. Difference: {abs(actual_total_tax - expected_total_tax)}p",
                    ref,
                    severity="warning",
                ))

        # Invoice date should be within filing period or previous month (amendment window)
        if inv.transaction_date and period and PERIOD_RE.match(period):
            mm = int(period[:2])
            yyyy = int(period[2:])
            inv_date = inv.transaction_date
            inv_yyyy = int(inv_date[:4])
            inv_mm = int(inv_date[5:7])
            # Allow current period and one month prior (CGST Section 37(3) amendment)
            prev_mm = mm - 1 if mm > 1 else 12
            prev_yyyy = yyyy if mm > 1 else yyyy - 1
            valid = (
                (inv_yyyy == yyyy and inv_mm == mm) or
                (inv_yyyy == prev_yyyy and inv_mm == prev_mm)
            )
            if not valid:
                errors.append(ValidationError(
                    "invoice_date",
                    f"Invoice date {inv.transaction_date} is outside filing period {period} and its amendment window",
                    ref,
                    severity="warning",
                ))

        return errors

    def validate_no_duplicates(
        self, invoices: Sequence[InvoiceToValidate]
    ) -> list[ValidationError]:
        """Detect duplicate invoice numbers within the return period."""
        seen: dict[str, str] = {}  # reference_no → first occurrence
        errors = []
        for inv in invoices:
            key = (inv.reference_no or "").strip().upper()
            if key in seen:
                errors.append(ValidationError(
                    "reference_no",
                    f"Duplicate invoice number '{inv.reference_no}'",
                    inv.reference_no,
                ))
            else:
                seen[key] = inv.reference_no
        return errors

    def validate_gstr1(
        self,
        gstin: str,
        period: str,
        invoices: Sequence[InvoiceToValidate],
    ) -> list[ValidationError]:
        """Full GSTR-1 validation — runs all rules.

        Returns list of ValidationError (empty = valid).
        """
        errors: list[ValidationError] = []
        errors.extend(self.validate_gstin(gstin))
        errors.extend(self.validate_period(period))
        errors.extend(self.validate_no_duplicates(invoices))
        for inv in invoices:
            errors.extend(self.validate_invoice(inv, period))
        return errors

    def validate_gstr3b(
        self,
        gstin: str,
        period: str,
        output_igst: int,
        output_cgst: int,
        output_sgst: int,
        itc_igst: int,
        itc_cgst: int,
        itc_sgst: int,
    ) -> list[ValidationError]:
        """Validate GSTR-3B figures for internal consistency."""
        errors: list[ValidationError] = []
        errors.extend(self.validate_gstin(gstin))
        errors.extend(self.validate_period(period))

        # ITC cannot exceed output tax by more than carried-forward credits
        # Warn if ITC > output tax (possible but unusual — may indicate data error)
        total_output = output_igst + output_cgst + output_sgst
        total_itc = itc_igst + itc_cgst + itc_sgst
        if total_itc > total_output * 3:
            errors.append(ValidationError(
                "itc",
                f"ITC (₹{total_itc/100:.2f}) is more than 3x the output tax (₹{total_output/100:.2f}). "
                "Verify purchase invoice data.",
                severity="warning",
            ))

        return errors
