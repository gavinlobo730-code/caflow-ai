"""
FY-versioned TDS-on-payments section rates — single source of truth.

IT Act 1961, Chapter XVII-B: Sections 193/194/194A/194B/194C/194D/194G/194H/
194I/194J/194K/194LA/194Q (TDS on non-salary payments). Salary TDS (Section
192) is slab-based and lives in domain/income_tax/statutory_rates.py — the
"192" entry here is a sentinel only. Section 206C (TCS) has a rate entry
below for reference, but no computation anywhere in this codebase actually
reads it — see that entry's own comment before assuming TCS is supported.

Before this module, domain/tds/tds_computer.py hardcoded one flat, unversioned
SECTION_THRESHOLDS table (audit finding F17): several thresholds pre-dated the
Finance Act 2025 threshold rationalisation (which raised 193/194/194A/194B/
194D/194G/194H/194I/194J/194K/194LA from 1 April 2025), the 194D/194G/194H
rates pre-dated the Finance (No. 2) Act 2024 cuts (5% → 2%), and the quarter
date table was pinned to FY 2025-26's literal calendar dates. Rates here are
integer BASIS POINTS — never float (CLAUDE.md: integer paise arithmetic only).

VERIFICATION STATUS — same convention as statutory_rates.py, per explicit
product instruction: FY 2025-26 is the last financial year verified against a
training-confirmed Finance Act (Finance Act 2025 / Budget of February 2025,
plus the Finance (No. 2) Act 2024 mid-year rate cuts already in force).
Entries with verified=False are populated by CARRYING FORWARD the last
verified year's figures — the standard "no change announced" assumption — and
MUST be confirmed against the actual Finance Act / CBDT notifications for
that year before being relied on for real withholding. Updating them is a
pure data change, no code change.

MODELLING SIMPLIFICATIONS (single threshold + two rates per section — the
shape the existing engine and its consumers already commit to). Where the
statute is finer-grained, the CONSERVATIVE (lowest-threshold, i.e.
most-likely-to-flag) figure is used, so the tool over-flags rather than
silently under-deducts; the CA reviews every figure before filing anyway:
  * 194A: ₹10,000 is the "any other payer" threshold. Banks/co-op/post
    office: ₹50,000; senior-citizen payees: ₹1,00,000 (both Finance Act
    2025). Payer type isn't modelled, so the lowest applies.
  * 194I: the Finance Act 2025 limit is ₹50,000 per month or part thereof
    (was ₹2,40,000 per year). Modelled as a per-payment threshold, which
    matches the statute for the ordinary monthly-rent-bill case; a single
    bill covering many months may over-flag (never under-flags).
  * 194J: ₹50,000 threshold; 10% is the professional-fees rate. Fees for
    technical services / call centres are 2% — not separately modelled.
  * 194D: 2% individual rate (Finance (No. 2) Act 2024, from 1 April 2025);
    10% remains the rate for payments to domestic companies.
"""
from __future__ import annotations

from dataclasses import dataclass

# One FY-string resolver for the whole codebase — do not re-implement.
from domain.income_tax.statutory_rates import current_fy


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TDSSectionRule:
    """Threshold + rates for one TDS/TCS section. Rates in integer basis
    points (10% = 1000 bps) so every computation stays integer-only."""
    single_threshold_paise: int          # TDS applies when a payment EXCEEDS this
    individual_rate_bps: int             # payee is individual/HUF (PAN 4th char P/H)
    company_rate_bps: int                # any other payee
    aggregate_threshold_paise: int | None = None  # FY-aggregate alternative trigger (194C)


@dataclass(frozen=True)
class FYTDSRates:
    fy: str        # "2025-26"
    verified: bool  # False = carried forward pending confirmation, see module docstring
    sections: dict[str, TDSSectionRule]


# ── FY 2025-26 (Finance Act 2025 + Finance (No. 2) Act 2024) — VERIFIED ──────

_SECTIONS_2025_26: dict[str, TDSSectionRule] = {
    # Salary — slab-based (statutory_rates.py), sentinel so section lookups succeed.
    "192":   TDSSectionRule(0, 0, 0),
    # Interest on securities — FA 2025 introduced a ₹10,000 threshold.
    "193":   TDSSectionRule(10_000_00, 1000, 1000),
    # Dividends — ₹5,000 → ₹10,000 (FA 2025).
    "194":   TDSSectionRule(10_000_00, 1000, 1000),
    # Interest other than securities — "any other payer" ₹10,000 (FA 2025); see
    # module docstring for the bank/senior-citizen simplification.
    "194A":  TDSSectionRule(10_000_00, 1000, 1000),
    # Lottery/crossword winnings — ₹10,000, now per single transaction (FA 2025).
    "194B":  TDSSectionRule(10_000_00, 3000, 3000),
    # Contractors — unchanged: ₹30,000 single OR ₹1,00,000 FY aggregate; 1%/2%.
    "194C":  TDSSectionRule(30_000_00, 100, 200, aggregate_threshold_paise=1_00_000_00),
    # Insurance commission — ₹15,000 → ₹20,000 (FA 2025); 5% → 2% for
    # non-companies (F(No.2)A 2024, from 1 Apr 2025); companies stay 10%.
    "194D":  TDSSectionRule(20_000_00, 200, 1000),
    # Lottery-ticket commission — ₹15,000 → ₹20,000; 5% → 2% (from 1 Oct 2024).
    "194G":  TDSSectionRule(20_000_00, 200, 200),
    # Commission/brokerage — ₹15,000 → ₹20,000; 5% → 2% (from 1 Oct 2024).
    "194H":  TDSSectionRule(20_000_00, 200, 200),
    # Rent — ₹2,40,000/yr → ₹50,000 per month or part (FA 2025); 10%. Modelled
    # per-payment (see module docstring).
    "194I":  TDSSectionRule(50_000_00, 1000, 1000),
    # Professional fees — ₹30,000 → ₹50,000 (FA 2025); 10% professional rate.
    "194J":  TDSSectionRule(50_000_00, 1000, 1000),
    # Mutual-fund income — ₹5,000 → ₹10,000 (FA 2025).
    "194K":  TDSSectionRule(10_000_00, 1000, 1000),
    # Compulsory acquisition compensation — ₹2,50,000 → ₹5,00,000 (FA 2025).
    "194LA": TDSSectionRule(5_00_000_00, 1000, 1000),
    # Purchase of goods — unchanged ₹50L, 0.1%.
    "194Q":  TDSSectionRule(50_00_000_00, 10, 10),
    # TCS on sale of goods, Section 206C(1H) — unchanged, 0.1%.
    # R3.1: NOT wired to any computation anywhere in this codebase — confirmed
    # zero readers (tds_computer.py has no 27EQ/TCS path at all, only 24Q/26Q
    # TDS). This entry is reference data only; do not assume TCS is an
    # implemented feature because a rate exists here. Building real TCS
    # support (a 27EQ return, collection tracking) is a distinct, unscoped
    # feature build, not a data-registry gap — see roadmap.
    "206C":  TDSSectionRule(0, 10, 10),
}

_FY_2025_26 = FYTDSRates(fy="2025-26", verified=True, sections=_SECTIONS_2025_26)

# ── FY 2026-27 — NOT YET VERIFIED (carried forward, see module docstring) ────

_FY_2026_27 = FYTDSRates(fy="2026-27", verified=False, sections=_SECTIONS_2025_26)

TDS_RATES_BY_FY: dict[str, FYTDSRates] = {
    "2025-26": _FY_2025_26,
    "2026-27": _FY_2026_27,
}

LATEST_VERIFIED_TDS_FY = "2025-26"


def tds_rates_for(fy: str | None = None) -> FYTDSRates:
    """Rates for the given FY ("2025-26"), defaulting to the current FY, falling
    back to the latest verified year for FYs not seeded yet."""
    fy = fy or current_fy()
    if fy in TDS_RATES_BY_FY:
        return TDS_RATES_BY_FY[fy]
    return TDS_RATES_BY_FY[LATEST_VERIFIED_TDS_FY]


# ── Quarterly return calendar (IT Rules, Rule 31A) ───────────────────────────

def quarter_dates(fy: str, quarter: str) -> tuple[str, str, str]:
    """(period_start, period_end, filing_due_date) for a 24Q/26Q quarter of the
    given FY — computed from the FY string, valid for ANY year (the previous
    table was pinned to FY 2025-26's literal dates, audit F17).

    Due dates per Rule 31A: Q1 → 31 Jul, Q2 → 31 Oct, Q3 → 31 Jan, Q4 → 31 May
    (NOT "31 April": the month following Q4's March end has 30 days, and the
    rule itself gives Q4 two extra months — the one place the simplified
    "31st of the month following the quarter" summary in CLAUDE.md cannot be
    taken literally, since it names a date that does not exist).
    """
    start_year = int(fy[:4])
    end_year = start_year + 1
    table = {
        "Q1": (f"{start_year}-04-01", f"{start_year}-06-30", f"{start_year}-07-31"),
        "Q2": (f"{start_year}-07-01", f"{start_year}-09-30", f"{start_year}-10-31"),
        "Q3": (f"{start_year}-10-01", f"{start_year}-12-31", f"{end_year}-01-31"),
        "Q4": (f"{end_year}-01-01", f"{end_year}-03-31", f"{end_year}-05-31"),
    }
    if quarter not in table:
        raise ValueError(f"Unknown TDS quarter '{quarter}' (expected Q1-Q4)")
    return table[quarter]
