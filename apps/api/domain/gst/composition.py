"""CMP-08 — the composition dealer's quarterly self-assessed statement.

CGST Act s.10 lets an eligible small taxpayer pay tax as a flat PERCENTAGE of
turnover instead of the ordinary rate-per-line GST this product computes for
every other client, in exchange for giving up input tax credit and outward
inter-State supply (s.10(2)(c)) entirely. Rule 62 requires the statement
quarterly, on FORM GST CMP-08 — a payment challan-cum-statement, not a return
GSTR-1/GSTR-3B build anything: `domain/gst/registrations.FILES_GSTR1_AND_3B`
has excluded `COMPOSITION` since GST-20 for exactly this reason.

THE FOUR LINES ARE THE OFFLINE UTILITY'S OWN SHAPE, not this module's
invention. `docs/compliance/sources/gst-offline-utilities/gstr4-annual/
CMP08Mod.bas.txt` — the GSTR-4 Annual Offline Utility's own VBA, which loads a
filed CMP-08 back onto its worksheet — names the JSON exactly:
`cmpsmry.out_sup` / `in_sup` / `tax_pay` / `intr_pay`, each carrying
`tax_val`/`iamt`/`camt`/`samt`/`csamt`. This module computes the first two and
row 3 is their sum by construction; row 4 (interest) is not computed here —
see the note on `CmpStatement.interest_paise` below.

WHICH RATE APPLIES IS A FACT ABOUT THE DEALER, NEVER DERIVED FROM THE FIGURES.
s.10(1) charges a manufacturer or "any other supplier eligible for
composition" (the trader limb) at one rate; its first proviso charges a
supplier of food or drink for human consumption (not serving alcohol) at a
higher one; s.10(2A) charges a supplier of SERVICES (who cannot use s.10(1) at
all) at a third, capped at the ₹50 lakh turnover Notification 2/2019-Central
Tax introduced. Guessing a manufacturer from a trader would misprice the
turnover by the same amount whichever way the guess falls, so
`migration 420`'s `composition_category` is nullable with no default and this
module REFUSES rather than assumes — the `vendors.msme_status` discipline.

⚠️ EVERY RATE BELOW IS `[S]`-GRADED. Egress to every `.gov.in` is refused at
this environment's proxy, so these three figures are recorded from knowledge
of Rule 7 and Notification 2/2019-Central Tax rather than confirmed against
either document, and `VERIFIED` says so structurally rather than as a comment
that can go stale. Confirm against Rule 7's own table before this is relied on
to compute money a client pays over.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from domain.sales.line_tax import compute_line_gst

MANUFACTURER_TRADER = "manufacturer_trader"
RESTAURANT = "restaurant"
OTHER_SERVICES = "other_services"

COMPOSITION_CATEGORIES = (MANUFACTURER_TRADER, RESTAURANT, OTHER_SERVICES)

#: category -> total rate in basis points (CGST + SGST combined; s.10 always
#: splits a composition levy evenly between the two, there being no IGST limb
#: at all on the OUTWARD side — s.10(2)(c) bars inter-State outward supply
#: outright, so nothing here ever produces an IGST rupee on turnover).
#: [S]-graded — see the module docstring.
COMPOSITION_RATE_BPS = {
    MANUFACTURER_TRADER: 100,   # 1% — s.10(1), Rule 7's manufacturer/trader row
    RESTAURANT: 500,            # 5% — first proviso to s.10(1)
    OTHER_SERVICES: 600,        # 6% — s.10(2A)
}

VERIFIED = False

#: s.10(2A)'s own turnover ceiling for the services limb (Notification
#: 2/2019-Central Tax). Not enforced here — this module computes what a
#: statement DOES say, not whether the dealer is still eligible to file one —
#: but named so a caller can raise it as a separate warning.
S10_2A_TURNOVER_LIMIT_PAISE = 50_00_000_00


def rate_bps_for(category: Optional[str]) -> tuple[Optional[int], Optional[str]]:
    """The composition rate for a category, or a refusal naming why there is
    none. Never guessed — see the module docstring."""
    if not category:
        return None, ("No composition category is recorded for this "
                       "registration. Record whether it is a manufacturer/"
                       "trader, a restaurant or another service provider "
                       "before a CMP-08 figure can be computed — s.10 charges "
                       "each at a different rate on the same turnover.")
    if category not in COMPOSITION_CATEGORIES:
        return None, (f"{category!r} is not a composition category. One of: "
                      f"{', '.join(COMPOSITION_CATEGORIES)}.")
    return COMPOSITION_RATE_BPS[category], None


@dataclass(frozen=True)
class CmpLine:
    """One row of the four — taxable value plus the four tax heads, in
    integer paise. Matches the offline utility's own `tax_val`/`iamt`/`camt`/
    `samt`/`csamt` keys exactly (see the module docstring)."""
    taxable_value_paise: int
    igst_paise: int
    cgst_paise: int
    sgst_paise: int
    cess_paise: int

    @property
    def tax_paise(self) -> int:
        return self.igst_paise + self.cgst_paise + self.sgst_paise + self.cess_paise

    def add(self, other: "CmpLine") -> "CmpLine":
        return CmpLine(
            taxable_value_paise=self.taxable_value_paise + other.taxable_value_paise,
            igst_paise=self.igst_paise + other.igst_paise,
            cgst_paise=self.cgst_paise + other.cgst_paise,
            sgst_paise=self.sgst_paise + other.sgst_paise,
            cess_paise=self.cess_paise + other.cess_paise,
        )


_ZERO_LINE = CmpLine(0, 0, 0, 0, 0)


@dataclass(frozen=True)
class CmpStatement:
    """The four rows CMP-08 files, plus what could not be computed."""
    financial_year: str
    quarter: str
    category: Optional[str]
    rate_bps: Optional[int]
    outward_supplies: CmpLine   # row 1 — s.10 tax on the dealer's own turnover
    inward_rcm_supplies: CmpLine  # row 2 — s.9(3)/(4) RCM, including import of services
    tax_paid: CmpLine          # row 3 — rows 1 + 2, by construction (Rule 7)
    #: row 4. NOT COMPUTED: s.50(1) interest on a CMP-08 paid past its due
    #: date is a function of how late the payment actually was, which this
    #: module has no visibility into (it computes the STATEMENT, not the
    #: payment) — named zero rather than guessed, matching every other
    #: interest-bearing statement in this product that takes the figure from
    #: its caller (`domain/tds/interest.py`'s callers, `late_filing.py`'s).
    interest_paise: int
    gaps: list[str]


def compute_cmp08(*, financial_year: str, quarter: str,
                  category: Optional[str],
                  outward_taxable_paise: int,
                  inward_rcm_taxable_paise: int = 0,
                  inward_rcm_igst_paise: int = 0,
                  inward_rcm_cgst_paise: int = 0,
                  inward_rcm_sgst_paise: int = 0,
                  inward_rcm_cess_paise: int = 0,
                  interest_paise: int = 0) -> CmpStatement:
    """The quarterly statement for one composition registration.

    `outward_taxable_paise` IS THE WHOLE OF THE DEALER'S TURNOVER FOR THE
    QUARTER, taxable and exempt alike ("Outward supplies (including exempt
    supplies)" is the offline utility's own row 1 label) — s.10 charges the
    percentage on aggregate turnover, not on a taxable slice of it, which is
    the one thing that most tells a composition statement apart from an
    ordinary GSTR-3B. It is ALWAYS intra-State by construction (s.10(2)(c)
    bars inter-State outward supply outright — a composition dealer who makes
    one has left the scheme, which this module does not detect), so
    `compute_line_gst` is called with `is_interstate=False` unconditionally.

    The inward reverse-charge figures are the CALLER's — already summed and
    already split by head — because which of those bills are inter-State is a
    fact about each bill's own place of supply, a service-layer question this
    domain module has no database handle to answer (the same reason
    `resolve_tds` takes its FY-aggregate figures from its caller rather than
    reading the ledger itself).
    """
    rate_bps, gap = rate_bps_for(category)
    gaps = [gap] if gap else []

    if rate_bps is None:
        outward = CmpLine(outward_taxable_paise, 0, 0, 0, 0)
    else:
        cgst, sgst, igst = compute_line_gst(
            outward_taxable_paise, rate_bps, is_interstate=False)
        outward = CmpLine(outward_taxable_paise, igst, cgst, sgst, 0)

    inward = CmpLine(
        taxable_value_paise=inward_rcm_taxable_paise,
        igst_paise=inward_rcm_igst_paise,
        cgst_paise=inward_rcm_cgst_paise,
        sgst_paise=inward_rcm_sgst_paise,
        cess_paise=inward_rcm_cess_paise,
    )

    return CmpStatement(
        financial_year=financial_year,
        quarter=quarter,
        category=category,
        rate_bps=rate_bps,
        outward_supplies=outward,
        inward_rcm_supplies=inward,
        tax_paid=outward.add(inward),
        interest_paise=interest_paise,
        gaps=gaps,
    )
