"""
TODO(compliance): docs/compliance/03-income-tax-and-tds.md
    THE KEYS IN THIS FILE ARE 1961-ACT SECTION NUMBERS AND ARE OBSOLETE FOR
    PERIODS FROM 01-04-2026. THE RATES ARE NOT. Verified 2026-09-04.

    The Income-tax Act 2025 consolidated ss. 192-196D and the whole 194-series
    into a table-driven architecture under ss. 392-402: salary is s. 392, the
    194-series collapsed into s. 393(1), and s. 195 became s. 393(2). TCS is
    s. 394. Returns and challans now carry numeric payment codes 1001-1067.

    Substantive rates and thresholds are UNCHANGED, so every number below is
    still right — it is the LABEL a payment is reported under that moved, and
    citing an old section code on a return draws a processing error and a
    correction statement.

    Do NOT rekey this file. Periods up to 31-03-2026 still report under these
    section numbers, indefinitely, including belated and revised returns.

    THE PERIOD-AWARE MAPPING NOW EXISTS ALONGSIDE: domain/tds/vocabulary.py.
    It takes a 1961-Act section — the keys below, which stay — and returns the
    label that period's statement must carry. Translation happens at the
    BOUNDARY, where a form or a return line is emitted; every rate lookup, every
    stored challan and every test in this codebase goes on using these keys, and
    a test pins that so a later rekeying is deliberate rather than tidy.
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

MOST OF THESE SECTIONS HAVE TWO LIMITS, NOT ONE. The proviso to s. 194J reads
"if such sum or, as the case may be, THE AGGREGATE OF THE SUMS credited or paid
... during the financial year does not exceed fifty thousand rupees", and
ss. 194A, 194D, 194G and 194H carry the same "aggregate of the sums" wording;
s. 194C(5) sets a separate and higher aggregate of its own. Until this table
gained aggregate_threshold_paise on those sections, only 194C had one, so the
second limb of tds_computer.resolve_tds()'s `applies` test was dead everywhere
else: a consultant billed ₹30,000 four times had NOTHING withheld against the
₹12,000 due on the ₹1,20,000 aggregate. Where the statute names one amount for
both limbs the aggregate here equals the single threshold, so single-payment
behaviour is unchanged; 194C stays the one section where the two differ
(₹30,000 single, ₹1,00,000 aggregate).

FOUR sections deliberately have NO aggregate, and this said "two" while four
more were merely unfinished — which is the worse mistake, because it reads as a
decision:

  * s. 194I — the limit is "fifty thousand rupees for a month or part of a
    month", a per-month test an FY aggregate would misstate;
  * s. 194B — FA 2025 made its ₹10,000 apply to a single transaction;
  * s. 192 — a sentinel only; salary is slab-based (statutory_rates.py);
  * s. 206C — reference data, read by no computation in this codebase.

Adding an FY aggregate to 194I or 194B would deduct where the statute does not
charge. ss. 193, 194, 194K and 194LA were in this paragraph by omission until
8 September and are now modelled: each carries the "or, as the case may be, the
aggregate of the amounts" limb in its own proviso, quoted beside its entry.

And one section is charged on a DIFFERENT BASE. s. 194Q(1) requires "a sum equal
to 0.1 per cent of such sum EXCEEDING fifty lakh rupees": the ₹50,00,000 is
carved out of the base, not merely a trigger. That is carried on the rule as
charge_on_excess_only, so the engine reads a property of the section rather
than testing its name. s. 194Q's ₹50,00,000 is ALSO an FY aggregate in the
statute — "purchase of goods of the value or aggregate of such value exceeding
fifty lakh rupees in any previous year" — and both limbs now carry it, so two
₹30,00,000 bills to one seller withhold ₹1,000 on the second (0.1% of the
₹10,00,000 by which the year exceeds ₹50,00,000) instead of nothing at all.
That became safe to model only once the purchase-bill path started crediting
what earlier bills withheld (fy_prior_tds_paise); before that, charging on a
running aggregate re-charged the whole year on every later bill.

What this module does NOT decide for 194Q is whether the section applies. The
first proviso binds only a buyer whose own turnover exceeded ₹10 crore in the
preceding FY, and no client turnover figure reaches this engine — the CA marks
the vendor, and the table answers "given 194Q applies, how much".
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
    # FY-aggregate alternative trigger — the statute's "or, as the case may be,
    # the aggregate of the sums ... during the financial year". TDS applies once
    # the payee's FY total under this section EXCEEDS this, even though no single
    # payment reached single_threshold_paise. See the module docstring for which
    # sections take one and which deliberately do not.
    aggregate_threshold_paise: int | None = None
    # IT Act s. 194Q(1) alone charges "a sum equal to 0.1 per cent of such sum
    # EXCEEDING fifty lakh rupees" — the threshold is carved OUT of the base
    # rather than only triggering it. Every other section here charges the whole
    # sum once its threshold is crossed. Held as a property of the rule so the
    # engine never has to special-case a section by name.
    charge_on_excess_only: bool = False


@dataclass(frozen=True)
class FYTDSRates:
    fy: str        # "2025-26"
    verified: bool  # False = carried forward pending confirmation, see module docstring
    sections: dict[str, TDSSectionRule]
    # IT Act Section 206AA — mandatory-PAN floor rate (20%). Long-settled
    # statutory structure, not an annually-revised threshold/rate the way
    # the section table above is — treated like statutory_rates.py's
    # 111A/112A rates (implemented directly, no "pending verification"
    # flag needed for the STRUCTURE itself). R3.10: previously hardcoded
    # identically in two places (domain/tds/tds_validator.py and inline in
    # tds_computer.py's 26Q validation) with no FY registry entry at all,
    # and — the more serious half of that finding — never actually applied
    # to the real computed tds_deducted_paise for a purchase bill, only
    # surfaced as a post-hoc validation warning. See tds_computer.py's
    # resolve_tds() for where it is now actually enforced.
    section_206aa_floor_rate_bps: int = 2000


# ── FY 2025-26 (Finance Act 2025 + Finance (No. 2) Act 2024) — VERIFIED ──────

_SECTIONS_2025_26: dict[str, TDSSectionRule] = {
    # Salary — slab-based (statutory_rates.py), sentinel so section lookups succeed.
    "192":   TDSSectionRule(0, 0, 0),
    # Interest on securities — FA 2025 introduced a ₹10,000 threshold, and its
    # proviso reads "where the amount of such interest ... or, as the case may
    # be, the AGGREGATE OF THE AMOUNTS of such interest credited or paid ...
    # during the financial year does not exceed ten thousand rupees" — one
    # amount, both limbs.
    "193":   TDSSectionRule(10_000_00, 1000, 1000, aggregate_threshold_paise=10_000_00),
    # Dividends — ₹5,000 → ₹10,000 (FA 2025). Second proviso: "where the amount
    # of such dividend or, as the case may be, the AGGREGATE OF THE AMOUNTS of
    # such dividend ... during the financial year does not exceed ten thousand
    # rupees" — one amount, both limbs.
    "194":   TDSSectionRule(10_000_00, 1000, 1000, aggregate_threshold_paise=10_000_00),
    # Interest other than securities — "any other payer" ₹10,000 (FA 2025); see
    # module docstring for the bank/senior-citizen simplification. s. 194A(3)(i)
    # sets the limit on "the amount or, as the case may be, the aggregate of the
    # amounts of such income credited or paid ... during the financial year", so
    # the same ₹10,000 is both limbs.
    "194A":  TDSSectionRule(10_000_00, 1000, 1000, aggregate_threshold_paise=10_000_00),
    # Lottery/crossword winnings — ₹10,000, now per single transaction (FA 2025).
    "194B":  TDSSectionRule(10_000_00, 3000, 3000),
    # Contractors — unchanged: ₹30,000 single OR ₹1,00,000 FY aggregate; 1%/2%.
    # The one section whose two limbs are different amounts (s. 194C(5)).
    "194C":  TDSSectionRule(30_000_00, 100, 200, aggregate_threshold_paise=1_00_000_00),
    # Insurance commission — ₹15,000 → ₹20,000 (FA 2025); 5% → 2% for
    # non-companies (F(No.2)A 2024, from 1 Apr 2025); companies stay 10%. The
    # s. 194D proviso reads on "the aggregate of the amounts of such income
    # credited or paid during the financial year", hence the same ₹20,000 twice.
    "194D":  TDSSectionRule(20_000_00, 200, 1000, aggregate_threshold_paise=20_000_00),
    # Lottery-ticket commission — ₹15,000 → ₹20,000; 5% → 2% (from 1 Oct 2024).
    # s. 194G(1) proviso: "the amount of such income or, as the case may be, the
    # aggregate of the amounts of such income ... during the financial year".
    "194G":  TDSSectionRule(20_000_00, 200, 200, aggregate_threshold_paise=20_000_00),
    # Commission/brokerage — ₹15,000 → ₹20,000; 5% → 2% (from 1 Oct 2024).
    # s. 194H proviso: "such income or, as the case may be, the aggregate of the
    # amounts of such income credited or paid ... during the financial year".
    "194H":  TDSSectionRule(20_000_00, 200, 200, aggregate_threshold_paise=20_000_00),
    # Rent — ₹2,40,000/yr → ₹50,000 per month or part (FA 2025); 10%. Modelled
    # per-payment (see module docstring).
    "194I":  TDSSectionRule(50_000_00, 1000, 1000),
    # Professional fees — ₹30,000 → ₹50,000 (FA 2025); 10% professional rate.
    # The s. 194J proviso: "if such sum or, as the case may be, the aggregate of
    # the sums credited or paid ... during the financial year does not exceed
    # fifty thousand rupees" — one amount, both limbs.
    "194J":  TDSSectionRule(50_000_00, 1000, 1000, aggregate_threshold_paise=50_000_00),
    # Mutual-fund income — ₹5,000 → ₹10,000 (FA 2025). Proviso: "where the
    # amount of such income or, as the case may be, the AGGREGATE OF THE
    # AMOUNTS of such income ... during the financial year does not exceed ten
    # thousand rupees" — one amount, both limbs.
    "194K":  TDSSectionRule(10_000_00, 1000, 1000, aggregate_threshold_paise=10_000_00),
    # Compulsory acquisition compensation — ₹2,50,000 → ₹5,00,000 (FA 2025).
    # Proviso: "where the amount of such payment or, as the case may be, the
    # AGGREGATE AMOUNT of such payments to a resident during the financial year
    # does not exceed five lakh rupees" — one amount, both limbs.
    "194LA": TDSSectionRule(5_00_000_00, 1000, 1000, aggregate_threshold_paise=5_00_000_00),
    # Purchase of goods — unchanged ₹50L, 0.1%, charged on the EXCESS: s. 194Q(1)
    # says "a sum equal to 0.1 per cent of such sum exceeding fifty lakh rupees",
    # so a ₹60,00,000 purchase bears ₹1,000 (0.1% of the ₹10,00,000 excess) and
    # not ₹6,000. The ₹50L is an FY AGGREGATE as well as a single-payment
    # trigger — s. 194Q(1) charges on "purchase of goods of the value OR
    # AGGREGATE OF SUCH VALUE exceeding fifty lakh rupees in any previous year"
    # — so both limbs carry the same figure. Without the aggregate limb two
    # ₹30,00,000 bills to one seller withheld nothing at all against ₹1,000 due
    # on the ₹60,00,000 year. NOT modelled here, and outside this module: the
    # section only binds a BUYER whose own turnover exceeded ₹10 crore in the
    # preceding FY (first proviso), and no client turnover figure reaches this
    # engine — so a vendor is put on 194Q by the CA marking them, and this table
    # answers only "given 194Q applies, how much".
    "194Q":  TDSSectionRule(50_00_000_00, 10, 10,
                            aggregate_threshold_paise=50_00_000_00,
                            charge_on_excess_only=True),
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
