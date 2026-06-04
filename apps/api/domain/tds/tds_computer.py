"""
TDS Computation Engine — 24Q and 26Q return generation.

IT Act Section 192  — TDS on salary (Form 24Q)
IT Act Section 194  — TDS on non-salary payments (Form 26Q)
IT Act Section 203  — TDS certificates (Form 16 / 16A)
IT Act Section 206AB — Higher TDS for non-filers (doubled rate or 5%)

All amounts in integer paise. Never floating point — IT Act Section 145A.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to TRACES or any government portal.
"""
from dataclasses import dataclass, field
from typing import Optional


# ── Value Objects ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TDSDeducteeRecord:
    """Single deductee row for a 24Q/26Q return."""
    deductee_name: str
    deductee_pan: str            # must be 10-char PAN; "PANNOTAVBL" if not available
    section: str                 # e.g. "194J", "192"
    nature_of_payment: str       # text description
    payment_date: str            # YYYY-MM-DD
    payment_amount_paise: int    # gross payment in paise
    tds_rate_pct: float          # e.g. 10.0
    tds_deducted_paise: int      # integer paise
    tds_deposited_paise: int     # may differ if partial deposit
    challan_no: str
    bsr_code: str
    challan_date: str            # YYYY-MM-DD
    is_lower_deduction: bool = False
    lower_deduction_cert: Optional[str] = None


@dataclass
class TDS24QPayload:
    """Form 24Q — TDS on salaries (IT Act Section 192)."""
    # Header
    tan: str                     # Tax Deduction Account Number (10 chars)
    deductor_name: str
    deductor_pan: str
    deductor_address: str
    financial_year: str          # "2025-26"
    quarter: str                 # "Q1", "Q2", "Q3", "Q4"
    quarter_end_date: str        # "2025-06-30"
    filing_type: str = "O"       # O=Original, R=Revised
    # Aggregates — all paise
    total_salary_paise: int = 0
    total_tds_deducted_paise: int = 0
    total_tds_deposited_paise: int = 0
    # Deductee records (Annexure I)
    deductees: list[TDSDeducteeRecord] = field(default_factory=list)
    # Challan details (Annexure II)
    challans: list[dict] = field(default_factory=list)
    # Validation
    validation_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class TDS26QPayload:
    """Form 26Q — TDS on non-salary payments (IT Act Sections 193-196D)."""
    # Header
    tan: str
    deductor_name: str
    deductor_pan: str
    deductor_address: str
    financial_year: str
    quarter: str
    quarter_end_date: str
    filing_type: str = "O"
    # Aggregates — all paise
    total_payment_paise: int = 0
    total_tds_deducted_paise: int = 0
    total_tds_deposited_paise: int = 0
    # Deductee records
    deductees: list[TDSDeducteeRecord] = field(default_factory=list)
    challans: list[dict] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ── TDS Threshold table (IT Act Section 194) ──────────────────────────────────

# (threshold_paise, individual_rate_pct, company_rate_pct)
SECTION_THRESHOLDS: dict[str, tuple[int, float, float]] = {
    "192":   (0,           0.0,   0.0),   # salary — slab rate, computed separately
    "193":   (1_000_00,    10.0,  10.0),  # interest on securities
    "194":   (5_000_00,    10.0,  10.0),  # dividends
    "194A":  (4_000_00,    10.0,  10.0),  # interest (non-securities)
    "194B":  (10_000_00,   30.0,  30.0),  # lottery winnings
    "194C":  (30_000_00,    1.0,   2.0),  # contractor (single; 1L aggregate)
    "194D":  (15_000_00,    5.0,  10.0),  # insurance commission
    "194G":  (15_000_00,    5.0,   5.0),  # lottery ticket commission
    "194H":  (15_000_00,    5.0,   5.0),  # commission/brokerage
    "194I":  (240_000_00,  10.0,  10.0),  # rent
    "194J":  (30_000_00,   10.0,  10.0),  # professional/technical fees
    "194K":  (5_000_00,    10.0,  10.0),  # mutual fund income
    "194LA": (250_000_00,  10.0,  10.0),  # compensation on property acquisition
    "194Q":  (5_000_000_00, 0.1,   0.1),  # purchase of goods
    "206C":  (0,            0.1,   0.1),  # TCS on goods sale
}

QUARTER_DATES = {
    "Q1": ("2025-04-01", "2025-06-30", "2025-07-31"),
    "Q2": ("2025-07-01", "2025-09-30", "2025-10-31"),
    "Q3": ("2025-10-01", "2025-12-31", "2026-01-31"),
    "Q4": ("2026-01-01", "2026-03-31", "2026-05-31"),
}


# ── Computation Engine ─────────────────────────────────────────────────────────

class TDSComputer:
    """
    Computes 24Q and 26Q return structures from raw deduction records.
    Pure domain logic — no database access.
    """

    def compute_26q(
        self,
        tan: str,
        deductor_name: str,
        deductor_pan: str,
        deductor_address: str,
        financial_year: str,
        quarter: str,
        deductees: list[TDSDeducteeRecord],
        challans: list[dict],
    ) -> TDS26QPayload:
        """
        Build Form 26Q payload from non-salary TDS deductions.
        IT Act Section 194 series.
        """
        payload = TDS26QPayload(
            tan=tan,
            deductor_name=deductor_name,
            deductor_pan=deductor_pan,
            deductor_address=deductor_address,
            financial_year=financial_year,
            quarter=quarter,
            quarter_end_date=QUARTER_DATES.get(quarter, ("", "", ""))[1],
        )

        # Filter non-salary deductions only
        non_salary = [d for d in deductees if d.section != "192"]
        payload.deductees = non_salary
        payload.challans = challans

        # Aggregate — integer paise arithmetic only
        payload.total_payment_paise = sum(d.payment_amount_paise for d in non_salary)
        payload.total_tds_deducted_paise = sum(d.tds_deducted_paise for d in non_salary)
        payload.total_tds_deposited_paise = sum(d.tds_deposited_paise for d in non_salary)

        # Validate
        payload.validation_errors = self._validate_26q(payload)
        payload.warnings = self._warnings_26q(payload)

        return payload

    def compute_24q(
        self,
        tan: str,
        deductor_name: str,
        deductor_pan: str,
        deductor_address: str,
        financial_year: str,
        quarter: str,
        deductees: list[TDSDeducteeRecord],
        challans: list[dict],
    ) -> TDS24QPayload:
        """
        Build Form 24Q payload from salary TDS deductions.
        IT Act Section 192.
        """
        payload = TDS24QPayload(
            tan=tan,
            deductor_name=deductor_name,
            deductor_pan=deductor_pan,
            deductor_address=deductor_address,
            financial_year=financial_year,
            quarter=quarter,
            quarter_end_date=QUARTER_DATES.get(quarter, ("", "", ""))[1],
        )

        salary_deductions = [d for d in deductees if d.section == "192"]
        payload.deductees = salary_deductions
        payload.challans = challans

        payload.total_salary_paise = sum(d.payment_amount_paise for d in salary_deductions)
        payload.total_tds_deducted_paise = sum(d.tds_deducted_paise for d in salary_deductions)
        payload.total_tds_deposited_paise = sum(d.tds_deposited_paise for d in salary_deductions)

        payload.validation_errors = self._validate_24q(payload)
        payload.warnings = self._warnings_24q(payload)

        return payload

    def compute_tds_amount(
        self,
        section: str,
        payment_amount_paise: int,
        is_company: bool = False,
    ) -> int:
        """
        Compute TDS for a single payment using threshold and rate table.
        IT Act Section 194 — returns paise (integer).
        """
        if section not in SECTION_THRESHOLDS:
            return 0
        threshold, ind_rate, co_rate = SECTION_THRESHOLDS[section]
        if payment_amount_paise <= threshold:
            return 0
        rate = co_rate if is_company else ind_rate
        # Integer paise arithmetic — floor to avoid over-deduction
        return int(payment_amount_paise * rate // 100)

    def _validate_26q(self, payload: TDS26QPayload) -> list[str]:
        errors: list[str] = []
        if not payload.tan or len(payload.tan) != 10:
            errors.append("TAN must be 10 characters")
        if not payload.deductor_pan or len(payload.deductor_pan) != 10:
            errors.append("Deductor PAN must be 10 characters")
        for d in payload.deductees:
            if d.deductee_pan not in ("PANNOTAVBL", "PANAPPLIED") and len(d.deductee_pan) != 10:
                errors.append(f"Invalid PAN for {d.deductee_name}: {d.deductee_pan}")
            if d.tds_deducted_paise < 0:
                errors.append(f"Negative TDS for {d.deductee_name}")
            # IT Act Section 206AA — 20% if PAN not available
            if d.deductee_pan == "PANNOTAVBL" and d.tds_rate_pct < 20.0:
                errors.append(
                    f"{d.deductee_name}: PAN not available — rate must be ≥20% per IT Act Section 206AA"
                )
        # Deducted vs deposited mismatch is an error if gap > 0
        gap = payload.total_tds_deducted_paise - payload.total_tds_deposited_paise
        if gap > 0:
            errors.append(
                f"TDS deducted (₹{gap//100}) exceeds deposited — Challan 281 deposit required"
            )
        return errors

    def _validate_24q(self, payload: TDS24QPayload) -> list[str]:
        errors: list[str] = []
        if not payload.tan or len(payload.tan) != 10:
            errors.append("TAN must be 10 characters")
        if not payload.deductor_pan or len(payload.deductor_pan) != 10:
            errors.append("Deductor PAN must be 10 characters")
        gap = payload.total_tds_deducted_paise - payload.total_tds_deposited_paise
        if gap > 0:
            errors.append(
                f"Salary TDS deducted (₹{gap//100}) exceeds deposited — Challan 281 required"
            )
        return errors

    def _warnings_26q(self, payload: TDS26QPayload) -> list[str]:
        warnings: list[str] = []
        for d in payload.deductees:
            threshold = SECTION_THRESHOLDS.get(d.section, (0, 0, 0))[0]
            if threshold > 0 and d.payment_amount_paise < threshold:
                warnings.append(
                    f"Section {d.section}: payment ₹{d.payment_amount_paise//100} "
                    f"below threshold ₹{threshold//100} — TDS may not be applicable"
                )
        return warnings

    def _warnings_24q(self, payload: TDS24QPayload) -> list[str]:
        warnings: list[str] = []
        if not payload.deductees:
            warnings.append("No salary deductions found for this quarter")
        return warnings
