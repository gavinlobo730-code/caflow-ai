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

from domain.tds.section_rates import (
    LATEST_VERIFIED_TDS_FY, TDSSectionRule, quarter_dates, tds_rates_for,
)


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


# ── TDS threshold/rate data ───────────────────────────────────────────────────
# Lives in domain/tds/section_rates.py — FY-versioned, integer basis points,
# with per-FY verification flags (audit F17: the table that used to sit here
# was a single unversioned copy with pre-Finance-Act-2025 thresholds and
# pre-Finance-(No.2)-Act-2024 rates).
#
# SECTION_THRESHOLDS is a legacy VIEW of the latest verified FY's data in the
# old (threshold_paise, individual_rate_pct, company_rate_pct) float-tuple
# shape, kept only for read-only consumers (the /api/tds/sections listing and
# older tests). All COMPUTATION goes through resolve_tds()/compute_tds_amount(),
# which use integer basis points from the registry directly.

SECTION_THRESHOLDS: dict[str, tuple[int, float, float]] = {
    section: (rule.single_threshold_paise,
              rule.individual_rate_bps / 100,
              rule.company_rate_bps / 100)
    for section, rule in tds_rates_for(LATEST_VERIFIED_TDS_FY).sections.items()
}


@dataclass(frozen=True)
class TDSResolution:
    """Outcome of resolving TDS for a single bill through the central engine."""
    applies: bool
    section: str
    tds_paise: int
    rate_pct: float
    rate_bps: int            # persisted on the bill for 26Q reconciliation (IT Act §203)
    is_company_rate: bool
    reason: str              # 'applied' | 'below_threshold'


def has_pan(pan: Optional[str]) -> bool:
    """Whether a real PAN (not missing, not the PANNOTAVBL/PANAPPLIED
    sentinels) is on file — distinct from TDSValidator.validate_pan(), which
    treats those sentinels as a VALID FORMAT for return-filing purposes.
    Section 206AA's mandatory-PAN floor cares about the sentinel case too:
    no real PAN → floor applies regardless of format validity."""
    return bool(pan) and pan not in ("PANNOTAVBL", "PANAPPLIED")


def is_company_pan(pan: Optional[str]) -> bool:
    """Return True when the payee should be taxed at the non-individual rate.

    The 4th character of a PAN encodes the holder type: 'P' = individual,
    'H' = HUF; everything else (C company, F firm, A AOP, T trust, …) is a
    non-individual. IT Act §194C charges 1% to individuals/HUF and 2% to others.
    No PAN → non-individual (conservative higher rate; §206AA higher-rate risk).
    """
    if not pan or len(pan) < 4:
        return True
    return pan[3].upper() not in ("P", "H")


# Quarter period/due dates are FY-derived — see section_rates.quarter_dates()
# (the dict that used to live here was pinned to FY 2025-26's literal dates,
# so any other FY's 24Q/26Q got the wrong quarter-end and due dates).


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
            quarter_end_date=self._quarter_end(financial_year, quarter),
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
            quarter_end_date=self._quarter_end(financial_year, quarter),
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
        fy: Optional[str] = None,
    ) -> int:
        """
        Compute TDS for a single payment (calculator convenience — no FY
        aggregation; use resolve_tds for bill posting). Returns integer paise;
        0 for unknown sections. F17 fix: previously did `amount * float_rate`
        (float arithmetic on paise, violating IT Act §145A / CLAUDE.md) against
        an unversioned threshold table — now integer basis points from the
        FY-versioned registry.
        """
        try:
            resolution = self.resolve_tds(
                section, payment_amount_paise, is_company=is_company, fy=fy)
        except ValueError:
            return 0
        return resolution.tds_paise

    def resolve_tds(
        self,
        section: str,
        taxable_paise: int,
        fy_prior_taxable_paise: int = 0,
        is_company: bool = False,
        fy: Optional[str] = None,
        has_pan: bool = True,
    ) -> "TDSResolution":
        """Resolve TDS for a single purchase bill — the single source of TDS rules.

        Encodes the statutory logic the purchase-bill path must NOT re-implement:
          * unknown section  → ValueError (never silently deduct 0 — audit L6);
          * threshold + FY aggregation (single-payment OR §194C ₹1L aggregate — H5);
          * section- and payee-type-specific rate (individual/HUF vs other — H6);
          * rate-based amount so TDS can never exceed the section rate (audit L1);
          * IT Act §206AA — no real PAN on file floors the rate at 20% (R3.10:
            previously computed here with zero awareness of PAN availability at
            all, so a no-PAN vendor's bill silently under-deducted at the
            section's normal rate; §206AA only ever appeared as a post-hoc
            validation warning on the 26Q return, never as an actual correction
            to the withheld amount).

        Args:
          section:                e.g. '194C', '194J'.
          taxable_paise:          this bill's taxable value (TDS base — excludes GST).
          fy_prior_taxable_paise: sum of this payee's prior taxable under this section
                                  in the same FY (for aggregate thresholds).
          is_company:             non-individual payee → higher rate where applicable.
          fy:                     financial year of the PAYMENT (e.g. "2025-26") so a
                                  bill dated in an earlier FY resolves that year's
                                  thresholds; defaults to today's FY. See
                                  section_rates.py for per-FY verification status.
          has_pan:                False when the payee has no real PAN on file (see
                                  has_pan() above for what counts) — floors the rate
                                  at Section 206AA's threshold. Defaults to True so
                                  callers that don't yet track PAN availability keep
                                  their prior (pre-R3.10) behaviour unchanged.
        """
        section = (section or "").upper().strip()
        rates = tds_rates_for(fy)
        rule: Optional[TDSSectionRule] = rates.sections.get(section)
        if rule is None:
            raise ValueError(f"Unknown TDS section '{section}'")
        fy_total = fy_prior_taxable_paise + taxable_paise

        applies = taxable_paise > rule.single_threshold_paise or (
            rule.aggregate_threshold_paise is not None
            and fy_total > rule.aggregate_threshold_paise
        )
        rate_bps = rule.company_rate_bps if is_company else rule.individual_rate_bps
        if not has_pan:
            rate_bps = max(rate_bps, rates.section_206aa_floor_rate_bps)
        rate = rate_bps / 100  # display only — computation stays in integer bps
        if not applies:
            return TDSResolution(False, section, 0, rate, rate_bps, is_company, "below_threshold")

        # Integer paise, floor — never over-deduct (IT Act §145A). Rate-bounded, so
        # tds can never reach 100% of the base (audit L1).
        tds = taxable_paise * rate_bps // 10000
        return TDSResolution(True, section, tds, rate, rate_bps, is_company, "applied")

    @staticmethod
    def _quarter_end(financial_year: str, quarter: str) -> str:
        """Quarter-end date for the payload header; empty string on bad input
        (validation reports the real error, matching the old table's .get())."""
        try:
            return quarter_dates(financial_year, quarter)[1]
        except (ValueError, IndexError):
            return ""

    def _validate_26q(self, payload: TDS26QPayload) -> list[str]:
        errors: list[str] = []
        if not payload.tan or len(payload.tan) != 10:
            errors.append("TAN must be 10 characters")
        if not payload.deductor_pan or len(payload.deductor_pan) != 10:
            errors.append("Deductor PAN must be 10 characters")
        floor_rate_pct = tds_rates_for(payload.financial_year).section_206aa_floor_rate_bps / 100
        for d in payload.deductees:
            if d.deductee_pan not in ("PANNOTAVBL", "PANAPPLIED") and len(d.deductee_pan) != 10:
                errors.append(f"Invalid PAN for {d.deductee_name}: {d.deductee_pan}")
            if d.tds_deducted_paise < 0:
                errors.append(f"Negative TDS for {d.deductee_name}")
            # IT Act Section 206AA — floor rate if PAN not available
            if d.deductee_pan == "PANNOTAVBL" and d.tds_rate_pct < floor_rate_pct:
                errors.append(
                    f"{d.deductee_name}: PAN not available — rate must be ≥{floor_rate_pct:.0f}% "
                    f"per IT Act Section 206AA"
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
        rates = tds_rates_for(payload.financial_year)
        if not rates.verified:
            warnings.append(
                f"FY {rates.fy} TDS thresholds/rates are carried forward from FY "
                f"{LATEST_VERIFIED_TDS_FY}, pending verification against that year's "
                f"Finance Act — confirm before filing (see domain/tds/section_rates.py)"
            )
        for d in payload.deductees:
            rule = rates.sections.get(d.section)
            threshold = rule.single_threshold_paise if rule else 0
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
