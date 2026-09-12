"""
TDS Computation Engine — 24Q and 26Q return generation.

IT Act Section 192  — TDS on salary (Form 24Q)
IT Act Section 194  — TDS on non-salary payments (Form 26Q)
IT Act Section 203  — TDS certificates (Form 16 / 16A)
IT Act Section 206AA — the 20% floor where no PAN is on file, which THIS
                       module applies (resolve_tds).

Section 206AB is NOT here, and the header advertised it for a long time. Two
things are wrong with that line: nothing in this module ever applied it — the
only implementation is `tds_validator.is_higher_rate_applicable`, which has no
production caller at all — and the Finance Act 2025 OMITTED the section with
effect from 01-04-2025, so it does not reach a payment made today. A header
naming a rule the module does not apply is how a reader concludes the
withholding already accounts for it.

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


@dataclass
class TDS27QDeducteeRecord:
    """Single deductee row for a Form 27Q return — a payment to a NON-RESIDENT.

    A SEPARATE RECORD FROM TDSDeducteeRecord, and not an optional extension of
    it, because 27Q's annexure asks for things 26Q has no column for and 26Q
    asks for things that are meaningless here.

      * TAX, SURCHARGE AND CESS ARE THREE COLUMNS. §195 charges "at the rates
        in force" under Part II of the First Schedule with §115A, and Part II
        carries its own surcharge ladders and a 4% cess that the resident
        series does not. `tds_rate_pct` is the BASE rate the tax was deducted
        at, so the three figures deliberately do not multiply out — the same
        asymmetry the register already carries from the bill.
      * COUNTRY AND TIN identify a payee with no Indian PAN. §206AA's 20% floor
        has a non-resident carve-out (§206AA(7) with Rule 37BC) that residents
        do not get, and the six Rule 37BC particulars are what earn it.
      * A NIL IS A ROW. An ordinary import from a supplier with no permanent
        establishment is business profits, not chargeable under §195 at all
        (*GE India Technology Centre*, 2010) — the right withholding is nil,
        and 27Q still reports the remittance with a REASON. 26Q has no such
        row: it reports deductions, and a resident payment below its threshold
        was not one. The asymmetry is the statute's.
    """
    deductee_name: str
    deductee_pan: str
    section: str                       # "195" in practice; "393(2)" from FY 2026-27
    nature_of_payment: str
    payment_date: str
    payment_amount_paise: int
    tds_rate_pct: float                # the BASE rate — surcharge and cess are below
    tds_deducted_paise: int            # base + surcharge + cess, as withheld
    tds_deposited_paise: int
    challan_no: str
    bsr_code: str
    challan_date: str
    country_of_residence: Optional[str] = None
    deductee_tin: Optional[str] = None
    surcharge_paise: int = 0
    cess_paise: int = 0
    #: Why nothing was withheld, where nothing was. The engine's own sentence,
    #: not an FVU remark code: those are a published list and guessing one would
    #: put a wrong code in a filed return (migration 312).
    non_deduction_reason: Optional[str] = None


@dataclass
class TDS27QPayload:
    """Form 27Q — TDS on payments to non-residents (IT Act §195, Rule 31A(4)(b))."""
    tan: str
    deductor_name: str
    deductor_pan: str
    deductor_address: str
    financial_year: str
    quarter: str
    quarter_end_date: str
    filing_type: str = "O"
    total_payment_paise: int = 0
    total_tds_deducted_paise: int = 0
    total_tds_deposited_paise: int = 0
    total_surcharge_paise: int = 0
    total_cess_paise: int = 0
    #: Remittances that withheld nothing. Counted separately because they are
    #: the rows an assessing officer asks about, and because a return whose
    #: deductee count and tax total disagree looks wrong without them.
    nil_deduction_count: int = 0
    deductees: list[TDS27QDeducteeRecord] = field(default_factory=list)
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
    #: IT Act §197 — the certified rate, where a live certificate reached part
    #: or all of the charge base, and how much of it that rate reached. The
    #: CALLER decides what to persist as "the rate deducted at", because where
    #: the ceiling is crossed mid-year two rates apply to one document and Form
    #: 26Q's annexure has one rate column. See domain/tds/lower_deduction.py.
    certificate_rate_bps: Optional[int] = None
    certified_base_paise: int = 0


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
        fy_prior_tds_paise: int = 0,
        is_company: bool = False,
        fy: Optional[str] = None,
        has_pan: bool = True,
        certified_base_paise: int = 0,
        certificate_rate_bps: Optional[int] = None,
    ) -> "TDSResolution":
        """Resolve TDS for a single purchase bill — the single source of TDS rules.

        Encodes the statutory logic the purchase-bill path must NOT re-implement:
          * unknown section  → ValueError (never silently deduct 0 — audit L6);
          * threshold + FY aggregation (single payment OR the section's own FY
            aggregate — H5), charged ON that aggregate, not on the marginal bill;
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
                                  in the same FY (for aggregate thresholds, and for
                                  the charge base — see below).
          fy_prior_tds_paise:     TDS ALREADY WITHHELD from this payee under this
                                  section in the same FY (IT Act §200 — tax already
                                  deducted and paid to the credit of the Central
                                  Government is not deducted twice). Since the charge
                                  is on the FY aggregate, the bill that crosses a
                                  threshold carries the whole year's tax and every
                                  bill after it must credit what came before, or the
                                  same aggregate is taxed again and again: three
                                  ₹1,00,000 §194J bills would withhold ₹10,000,
                                  ₹20,000 and ₹30,000 instead of ₹10,000 each.
                                  A CALLER THAT PASSES fy_prior_taxable_paise MUST
                                  PASS THIS TOO — the two are one figure about the
                                  year, and supplying half of it over-withholds.
                                  Defaults to 0, "nothing withheld yet", which is
                                  right for a first bill and for the single-payment
                                  calculator (routers/tds.py's /compute-amount), both
                                  of which pass neither.
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
          certified_base_paise:   IT Act §197 — how much of the CHARGE BASE a live
                                  lower-deduction certificate reaches. Rule 28AA(4)
                                  makes a certificate an AMOUNT as well as a rate, so
                                  a year that runs past the ceiling is charged at two
                                  rates: the certified slice at the certificate's, the
                                  rest at the section's. The caller computes the slice
                                  because only it knows which documents fell inside the
                                  validity period — see domain/tds/lower_deduction.py
                                  and services/vendor_tds.py.
          certificate_rate_bps:   the certified rate in basis points. 0 is real and
                                  common: §197(1) allows "no deduction of tax". None
                                  means no certificate, which is not the same as 0.
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

        # The base is the FY AGGREGATE, not this bill. IT Act §194C(5) charges the
        # deduction where "the aggregate of the amounts of such sums credited or
        # paid ... exceeds one lakh rupees", and §§194A/194D/194G/194H/194J carry
        # the same "aggregate of the sums" limb: crossing the limit does not make
        # the earlier payments exempt, it makes them due. Charging only the bill
        # that happened to cross withheld ₹500 across five ₹25,000 §194C bills
        # against ₹2,500 due on the ₹1,25,000 aggregate.
        charge_base = fy_total
        if rule.charge_on_excess_only:
            # IT Act §194Q(1): "a sum equal to 0.1 per cent of such sum exceeding
            # fifty lakh rupees" — the threshold is carved out of the base rather
            # than only triggering it, so a ₹60,00,000 purchase bears ₹1,000 and
            # not ₹6,000. Clamped at zero: `applies` can be reached on the single
            # limb, which for a section with no aggregate is the same comparison,
            # but the clamp keeps the base non-negative under any future rule.
            charge_base = max(0, fy_total - rule.single_threshold_paise)

        # Integer paise, floor — never over-deduct (IT Act §145A). Rate-bounded, so
        # tds can never exceed the section rate on the charge base (audit L1). It
        # CAN exceed this one bill's value on the bill that crosses a large
        # aggregate; that is the statute — the year's tax falls due on the payment
        # that crosses — and not the 100%-of-base case audit L1 was about.
        # IT Act §197 with Rule 28AA(4): a certificate lowers the rate up to a
        # certified AMOUNT, and the excess resumes at the section rate. Split
        # rather than substituted, because a certificate for ₹50,00,000 on a
        # vendor billed ₹60,00,000 does not certify the last ₹10,00,000 — and
        # substituting would under-deduct exactly where the AO stopped
        # certifying. §206AA's floor is untouched: it applies to `rate_bps`
        # above and never to the certified slice, because §206AA(4) bars a §197
        # certificate without a PAN in the first place, so the two cannot both
        # be live (lower_deduction.position_for refuses that combination).
        certified = max(0, min(int(certified_base_paise), charge_base))
        if certificate_rate_bps is not None and certified > 0:
            cumulative_tds = (certified * int(certificate_rate_bps) // 10000
                              + (charge_base - certified) * rate_bps // 10000)
        else:
            certified = 0
            cumulative_tds = charge_base * rate_bps // 10000
        # IT Act §200: what earlier bills already deducted and paid to the credit
        # of the Central Government is not deducted a second time. Floored at zero
        # because a credit note or a mid-year rate change can leave more withheld
        # than the fresh aggregate needs, and there is no such thing as a negative
        # withholding on a 26Q line.
        tds = max(0, cumulative_tds - fy_prior_tds_paise)
        return TDSResolution(
            True, section, tds, rate, rate_bps, is_company, "applied",
            certificate_rate_bps=(certificate_rate_bps if certified > 0 else None),
            certified_base_paise=certified,
        )

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

    def compute_27q(
        self,
        tan: str,
        deductor_name: str,
        deductor_pan: str,
        deductor_address: str,
        financial_year: str,
        quarter: str,
        deductees: list[TDS27QDeducteeRecord],
        challans: list[dict],
    ) -> TDS27QPayload:
        """Build the Form 27Q payload — IT Act §195, Rule 31A(4)(b).

        Deliberately does NOT filter by section the way compute_26q filters out
        §192. A payment to a non-resident is on 27Q whatever charging provision
        reaches it: §195 in almost every case, but §194E (non-resident
        sportsmen), §194LB/§194LC (interest to a non-resident) and §196D (FII
        income) all charge non-residents and all report here. Filtering by
        section would silently drop them; residency is what routes a row, and
        the CALLER decides it from the vendor master (migration 308).
        """
        payload = TDS27QPayload(
            tan=tan,
            deductor_name=deductor_name,
            deductor_pan=deductor_pan,
            deductor_address=deductor_address,
            financial_year=financial_year,
            quarter=quarter,
            quarter_end_date=self._quarter_end(financial_year, quarter),
        )
        payload.deductees = deductees
        payload.challans = challans

        payload.total_payment_paise = sum(d.payment_amount_paise for d in deductees)
        payload.total_tds_deducted_paise = sum(d.tds_deducted_paise for d in deductees)
        payload.total_tds_deposited_paise = sum(d.tds_deposited_paise for d in deductees)
        payload.total_surcharge_paise = sum(d.surcharge_paise for d in deductees)
        payload.total_cess_paise = sum(d.cess_paise for d in deductees)
        payload.nil_deduction_count = sum(1 for d in deductees if d.tds_deducted_paise == 0)

        payload.validation_errors = self._validate_27q(payload)
        payload.warnings = self._warnings_27q(payload)
        return payload

    def _validate_27q(self, payload: TDS27QPayload) -> list[str]:
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
            # THE §206AA FLOOR IS NOT ASSERTED HERE, and that is the difference
            # from 26Q. §206AA(7) with Rule 37BC lets a non-resident out of the
            # 20% floor on six particulars — name, email, phone, address,
            # country TIN and a tax residency certificate — which
            # domain/tds/section_195.py has already weighed by the time a rate
            # reaches this record. Re-asserting the floor here would reject the
            # very returns the carve-out exists for.
            #
            # What IS asserted is that the row can be filed at all: the FVU
            # requires a country and a TIN wherever there is no PAN, because
            # they are how the payee is identified.
            if not has_pan(d.deductee_pan):
                if not (d.country_of_residence or "").strip():
                    errors.append(
                        f"{d.deductee_name}: no PAN and no country of residence — "
                        f"Form 27Q identifies a non-PAN payee by country and TIN")
                if not (d.deductee_tin or "").strip():
                    errors.append(
                        f"{d.deductee_name}: no PAN and no tax identification number "
                        f"— required on Form 27Q where PAN is not available")
            # A NIL WITHOUT A REASON IS THE ONE THING THIS RETURN CANNOT SAY.
            # Rule 31A(4) reports a remittance that withheld nothing with the
            # reason it withheld nothing; a blank leaves the deductor an
            # assessee in default under §201(1) with no recorded basis.
            if d.tds_deducted_paise == 0 and not (d.non_deduction_reason or "").strip():
                errors.append(
                    f"{d.deductee_name}: nothing was withheld and no reason is "
                    f"recorded — Form 27Q reports a nil remittance with its basis")
        gap = payload.total_tds_deducted_paise - payload.total_tds_deposited_paise
        if gap > 0:
            errors.append(
                f"TDS deducted (₹{gap//100}) exceeds deposited — Challan 281 deposit required"
            )
        return errors

    def _warnings_27q(self, payload: TDS27QPayload) -> list[str]:
        warnings: list[str] = []
        # The §195 rate registry is reconciled against §115A and Part II of the
        # First Schedule and is NOT confirmed line by line against any Finance
        # Act — every year in it carries verified=False. Said on the return the
        # figures are going into, not only in the module that holds them.
        from domain.tds.section_195_rates import rates_are_verified
        if not rates_are_verified(payload.financial_year):
            warnings.append(
                f"FY {payload.financial_year} section 195 rates were reconciled "
                f"against s.115A and Part II of the First Schedule but have NOT "
                f"been confirmed line by line against the Finance Act — check "
                f"before filing (domain/tds/section_195_rates.py)")
        if not payload.deductees:
            warnings.append("No payments to a non-resident found for this quarter")
        if payload.nil_deduction_count:
            warnings.append(
                f"{payload.nil_deduction_count} remittance(s) withheld nothing. "
                f"Each is reported with its basis, and each rests on a claim — "
                f"no permanent establishment, or a treaty with no article for "
                f"this nature of income — that the assessing officer may test.")
        return warnings

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
