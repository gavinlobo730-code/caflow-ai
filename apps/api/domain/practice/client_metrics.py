"""What a client's year looked like, and what a benchmark may do with it.

WHAT WAS MISSING (STUCK.md §1; plan rows 3c-1, 3c-2, 3c-4 and the tax half of
3c-5; the column list decided as D30)

    `concentration.py` next door answers where a client sits in the firm's FEE
    distribution, because fee revenue and cost are already aggregated one read
    each. The TAX half — effective tax rate, ITC as a proportion of purchases,
    GST-to-turnover — is derived from a client's whole ledger, so computing it
    for every client so that one can be compared against them is CLAUDE.md's
    reporting rule broken twice over. Migration 417 stores the aggregates; this
    module says what each one MEANS, which source is allowed to answer it, and
    what a distribution may and may not do with the answer.

THIS MODULE READS NOTHING. `services/client_metrics_service.py` fetches and
writes; `routers/analytics.py` serves. Both decide nothing that is decided
here.

──────────────────────────────────────────────────────────────────────────────
NULL IS NOT NIL, AND IN A DISTRIBUTION THE DIFFERENCE IS NOT COSMETIC
──────────────────────────────────────────────────────────────────────────────
Every figure is optional. `None` means the run could not derive it — the client
is not registered for GST, no return was ever saved, the payroll module is not
in use — and 0 means the run derived it and it was nil.

A median or a mean counts what it is given. A `None` read as 0 drags the whole
distribution towards zero AND makes the client it belongs to read as the firm's
best performer on a ratio it has no figures for, which is the specific way a
benchmark tells somebody the opposite of the truth. So `None` is EXCLUDED from
every statistic here, `n` says how many clients actually answered, and the
answer names the ones that did not.

That is the same rule this codebase keeps having to restate — `table_4a_gaps`,
`_undeclarable_rows`, the firm hub's three kinds of nil — applied where a wrong
reading is arithmetic rather than a sentence.

──────────────────────────────────────────────────────────────────────────────
A RATIO NEEDS BOTH SIDES AND A NON-ZERO DENOMINATOR
──────────────────────────────────────────────────────────────────────────────
`ratio_bps` refuses rather than returning 0 where the denominator is nil or
either side is absent. A zero effective tax rate against a nil profit is not a
tax position; it is a division nobody can do, and putting 0 in the column says
the client paid no tax on profits they did not make.

Basis points, not a float: every proportion in this product is an integer, and
a percentage carried as a float through a median is how two clients with
identical figures come to rank differently.

──────────────────────────────────────────────────────────────────────────────
WHAT IS DELIBERATELY NOT HERE
──────────────────────────────────────────────────────────────────────────────
* **No threshold, no verdict, no "healthy" band.** The module reports where a
  client sits and never what that means. An effective tax rate above the firm's
  median is a fact; "high" is an opinion about a client's affairs that would be
  read as advice, and `concentration.py` refuses the ICAI fee-dependence
  percentage for the same reason.
* **No year-on-year growth rate.** A year of rows IS the trend and the screen
  can draw it; a stored growth figure would be a second derivation of two
  numbers already present, and it would be wrong for the first year of every
  client.
* **No industry or peer-group comparison.** Nothing in this product records
  what business a client is in, and a benchmark across a mixed book compares a
  manufacturer with a consultancy. The distribution is THE FIRM'S OWN and says
  so.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── The twelve figures (D30), and what each one IS ───────────────────────────
#
# The tuple is the vocabulary: the service writes these keys, the router serves
# them, and a test asserts the three agree — so a thirteenth figure cannot be
# half-added. The column list was fixed once because a column added later
# cannot be back-filled for a period whose books have since been locked.
FIGURES: tuple[str, ...] = (
    "turnover_paise",
    "profit_before_tax_paise",
    "tax_expense_paise",
    "purchases_paise",
    "output_tax_paise",
    "itc_availed_paise",
    "itc_reversed_paise",
    "gst_cash_paid_paise",
    "tds_deducted_paise",
    "tds_deposited_paise",
    "payroll_cost_paise",
    "employee_count",
)

#: What each figure is, in the words a CA would use, and WHICH source answers
#: it. The source half is load-bearing: two of these could plausibly be
#: derived twice — output tax off the ledger's GST Output account as well as
#: off the return, ITC off the purchase register as well as off the return —
#: and the two would disagree the moment a return was revised. The RETURN wins,
#: because a benchmark of tax positions compares what was FILED.
FIGURE_MEANING: dict[str, str] = {
    "turnover_paise":
        "Revenue from operations for the year, from the books — the Schedule "
        "III caption, not GST turnover. CGST §2(6) aggregate turnover is "
        "PAN-level and all-India and is a different figure (migration 401).",
    "profit_before_tax_paise":
        "Net profit for the year before tax expense, from the books.",
    "tax_expense_paise":
        "Tax expense charged in the profit and loss account. NOT tax paid, and "
        "not the computed liability — this is what the books carry.",
    "purchases_paise":
        "Cost of materials and purchases for the year, from the books.",
    "output_tax_paise":
        "GST output tax declared in the year's GSTR-3B returns, as filed.",
    "itc_availed_paise":
        "Input tax credit claimed in the year's GSTR-3B returns, as filed — "
        "Table 4(C), net of the reversals that return itself declared.",
    "itc_reversed_paise":
        "Credit reversed in the year, from `itc_reversal_register`, which is "
        "the only place the statutory GROUND is recorded.",
    "gst_cash_paid_paise":
        "Discharged from the electronic cash ledger — the challan figure, "
        "including reverse-charge tax, which §49(4) never lets credit pay.",
    "tds_deducted_paise":
        "Tax withheld by this client as deductor during the year.",
    "tds_deposited_paise":
        "Deposited by challan during the year. Deliberately a different figure "
        "from what was deducted: the gap between them is the point.",
    "payroll_cost_paise":
        "Gross pay (§17(1)) plus the employer's own PF, EDLI, administrative "
        "charge and ESI — PAY-25's two debits, summed. Released runs only "
        "(PAY-04). Net pay is not cost.",
    "employee_count":
        "Distinct employees paid in a released run during the year, not "
        "headcount at any date.",
}

#: Figures that are MONEY. `employee_count` is not, and a screen that formatted
#: it as rupees would show "₹12.00" for twelve people.
MONEY_FIGURES: tuple[str, ...] = tuple(f for f in FIGURES if f.endswith("_paise"))

THE_DISTRIBUTION_IS_THE_FIRMS_OWN = (
    "The comparison is against this firm's other clients, not an industry "
    "benchmark. Nothing here records what business a client is in, so a mixed "
    "book compares a manufacturer with a consultancy."
)

NULL_IS_NOT_NIL = (
    "A client with no figure is left out of the statistic rather than counted "
    "as nil — an absent figure read as zero moves every median it is in and "
    "makes the client it belongs to look like the firm's best performer on a "
    "ratio nobody computed for them."
)


@dataclass(frozen=True)
class MetricGap:
    """One figure a run could not derive, and why."""
    figure: str
    why: str

    def as_dict(self) -> dict:
        return {"figure": self.figure, "why": self.why}


@dataclass(frozen=True)
class ClientPeriod:
    """One stored row, as the benchmark reads it."""
    client_id: str
    client_name: str
    financial_year: str
    figures: dict[str, Optional[int]] = field(default_factory=dict)
    gaps: tuple[MetricGap, ...] = ()

    def get(self, figure: str) -> Optional[int]:
        return self.figures.get(figure)


def ratio_bps(numerator: Optional[int], denominator: Optional[int]) -> Optional[int]:
    """Numerator over denominator in basis points, or None.

    REFUSES rather than answering 0 where either side is absent or the
    denominator is nil. A nil denominator is a division nobody can do, and a
    zero in an effective-tax-rate column says the client paid no tax on profits
    they did not make.

    A NEGATIVE denominator is refused too, and that is not the same refusal:
    profit before tax can legitimately be a loss, and "tax as 40% of a loss" is
    not a rate a reader can use in either direction.
    """
    if numerator is None or denominator is None:
        return None
    if denominator <= 0:
        return None
    # Truncates toward zero. A benchmark position is not a sum that has to
    # foot, so there is nothing for a rounding rule to protect here; the
    # convention matches every other bps in the product.
    return int(numerator * 10_000 / denominator)


#: The ratios a benchmark screen shows, as (key, numerator, denominator). Held
#: here rather than in the router so the screen cannot invent a thirteenth.
RATIOS: tuple[tuple[str, str, str], ...] = (
    ("effective_tax_rate_bps", "tax_expense_paise", "profit_before_tax_paise"),
    ("gst_to_turnover_bps", "output_tax_paise", "turnover_paise"),
    ("itc_to_purchases_bps", "itc_availed_paise", "purchases_paise"),
    ("itc_reversal_rate_bps", "itc_reversed_paise", "itc_availed_paise"),
    ("tds_to_purchases_bps", "tds_deducted_paise", "purchases_paise"),
    ("payroll_to_turnover_bps", "payroll_cost_paise", "turnover_paise"),
)


def _median(values: list[int]) -> Optional[int]:
    """The middle value, or the mean of the middle two. None over nothing.

    Integer arithmetic throughout: `//` on the even case, so the median of two
    odd figures is a paisa below their true midpoint rather than a float that
    formats to something a reader cannot reproduce.
    """
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) // 2


@dataclass(frozen=True)
class Distribution:
    """Where the firm's clients sit on one figure or ratio."""
    key: str
    n: int
    median: Optional[int]
    lowest: Optional[int]
    highest: Optional[int]
    #: The clients that answered nothing for this key. NAMED rather than
    #: counted, because the CA's next action is to go and look at one of them.
    not_measured: tuple[str, ...] = ()


def distribution(key: str, rows: list[ClientPeriod],
                 value_of) -> Distribution:
    """Summarise one key over the clients that answered it.

    `value_of(row)` returns the figure or None. The callable rather than a key
    lookup is what lets a ratio and a raw figure share this function — two
    copies of "exclude the Nones, then take the median" is two chances to get
    the exclusion wrong, and the exclusion is the whole rule.
    """
    answered: list[int] = []
    silent: list[str] = []
    for r in rows:
        v = value_of(r)
        if v is None:
            silent.append(r.client_name)
        else:
            answered.append(v)
    return Distribution(
        key=key,
        n=len(answered),
        median=_median(answered),
        lowest=min(answered) if answered else None,
        highest=max(answered) if answered else None,
        not_measured=tuple(sorted(silent)),
    )


@dataclass(frozen=True)
class Position:
    """One client's place in one distribution."""
    key: str
    value: Optional[int]
    #: 1 is the LOWEST. Stated because "rank 1" reads as best, and on an
    #: effective tax rate the lowest is not obviously the best — which is
    #: exactly why this module ranks and never judges.
    rank: Optional[int]
    of: int


def position(key: str, value: Optional[int], others: list[int]) -> Position:
    """Where `value` sits among `others` (which INCLUDES it), lowest first."""
    if value is None:
        return Position(key=key, value=None, rank=None, of=len(others))
    s = sorted(others)
    return Position(key=key, value=value, rank=s.index(value) + 1, of=len(s))


@dataclass(frozen=True)
class Benchmark:
    financial_year: str
    clients: int
    figures: tuple[Distribution, ...]
    ratios: tuple[Distribution, ...]
    #: Present only when the caller asked about one client.
    subject_client_id: Optional[str] = None
    subject_positions: tuple[Position, ...] = ()
    notes: tuple[str, ...] = ()


def benchmark(rows: list[ClientPeriod], financial_year: str,
              subject_client_id: Optional[str] = None) -> Benchmark:
    """The firm's own distribution over one financial year.

    Every figure and every ratio, over the clients that answered each — so a
    client missing payroll still counts towards the GST distribution, which is
    the whole reason the exclusion is PER KEY rather than per row.
    """
    figure_dists = tuple(
        distribution(f, rows, lambda r, f=f: r.get(f)) for f in FIGURES
    )
    ratio_dists = tuple(
        distribution(key, rows, lambda r, n=num, d=den: ratio_bps(r.get(n), r.get(d)))
        for key, num, den in RATIOS
    )

    positions: tuple[Position, ...] = ()
    if subject_client_id is not None:
        subject = next((r for r in rows if r.client_id == subject_client_id), None)
        if subject is not None:
            pos: list[Position] = []
            for f in FIGURES:
                vals = [v for v in (r.get(f) for r in rows) if v is not None]
                pos.append(position(f, subject.get(f), vals))
            for key, num, den in RATIOS:
                vals = [
                    v for v in (ratio_bps(r.get(num), r.get(den)) for r in rows)
                    if v is not None
                ]
                pos.append(position(key, ratio_bps(subject.get(num), subject.get(den)), vals))
            positions = tuple(pos)

    return Benchmark(
        financial_year=financial_year,
        clients=len(rows),
        figures=figure_dists,
        ratios=ratio_dists,
        subject_client_id=subject_client_id,
        subject_positions=positions,
        notes=(THE_DISTRIBUTION_IS_THE_FIRMS_OWN, NULL_IS_NOT_NIL),
    )
