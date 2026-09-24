"""What a client owes when they sell a capital asset — CGST Act s.18(6).

WHAT WAS WRONG (FA-08b)
    `journal_for_asset_disposal` posted four lines — accumulated depreciation
    cleared, the whole proceeds to bank, the asset out at cost, and the gain or
    loss balancing — and no tax line of any kind. `DisposalIn` had no tax field
    to carry one. A sale of a capital asset is a SUPPLY, so the tax was never
    declared, never posted, and the CA had to remember to raise a separate
    sales invoice with nothing anywhere prompting them.

THE SECTION, AND WHY IT IS NOT SIMPLY "TAX ON THE SALE"
    s.18(6): "In case of supply of capital goods or plant and machinery, on
    which input tax credit has been taken, the registered person shall pay an
    amount equal to the input tax credit taken on the said capital goods or
    plant and machinery REDUCED BY SUCH PERCENTAGE POINTS AS MAY BE PRESCRIBED
    or the TAX ON THE TRANSACTION VALUE of such capital goods or plant and
    machinery determined under section 15, WHICHEVER IS HIGHER."

    So there are two limbs and the higher one is paid. An asset sold cheap
    early in its life pays back credit rather than tax on the price — which is
    the whole reason the section exists, and exactly the case a plain
    "tax on the sale" would under-declare.

    Where NO credit was taken the section does not reach the supply at all
    (its own words: "on which input tax credit has been taken"). The sale is
    still a supply and s.9 still charges tax on the transaction value; there is
    simply no reduced-credit limb to compare it against.

⚠️ TWO RULES PRESCRIBE THE REDUCTION AND THEY DO NOT AGREE. `[S]`-GRADED.
    Rule 40(2) reduces the input tax "at the rate of FIVE PERCENTAGE POINTS for
    every QUARTER OR PART THEREOF from the date of the issue of the invoice".
    Rule 44(6) sends the same question to Rule 44(1)(b), which computes the
    credit "involved in the REMAINING USEFUL LIFE IN MONTHS ... on pro-rata
    basis, taking the useful life as five years".

    Both are five-year straight line; they differ in granularity, and the
    difference is real money. Thirty-eight months after the invoice, Rule 40(2)
    has run thirteen quarters (twelve whole and a part) and leaves 35% of the
    credit; Rule 44(6) leaves 22/60 = 36.67%. Since the section pays the HIGHER
    of the two limbs, the reading changes what is owed whenever the reduced
    credit is the larger figure.

    This environment's proxy refuses every `.gov.in`, so neither rule could be
    read. BOTH READINGS ARE REPORTED and neither is chosen — the same shape as
    `interest_on_rule_37_reversal`, and for the same reason: this is a sum the
    CA pays over on the client's behalf, and picking one silently would
    over- or under-state it.

WHAT THIS MODULE DOES NOT DO
    It POSTS NOTHING. The tax on the transaction value goes on the disposal
    journal, because that is the tax the buyer actually paid and it is not in
    doubt. The EXCESS, where the reduced credit is the higher limb, is left for
    the CA to raise: it is a figure with two readings and no invoice behind it,
    and the same judgement `itc_register_service` records about Rule 37.

    It does not decide whether a disposal is a SUPPLY. Scrapping with no
    consideration, a transfer to a related party, a write-off — the answer
    turns on facts no ledger holds, so the caller states it and an unstated
    answer is NAMED rather than assumed.

    The proviso to s.18(6) — refractory bricks, moulds and dies, jigs and
    fixtures supplied AS SCRAP may pay on the transaction value alone — is an
    OPTION the taxable person exercises, on an asset class this register does
    not record. It is named in the caveats, never applied.

Integer paise throughout. Every rounding goes UP: this is a sum the taxpayer
OWES, and understating it leaves a residual demand with s.50(1) interest
running on it — the same direction ESI and the GST late-filing interest take,
and the opposite of the s.15(3)(a) discount, which floors because there
understating cannot under-declare tax.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from domain.banking.charge_gst import ALLOWED_RATES_BPS, split_inclusive_charge
from domain.money_text import rupees_paise

#: Rule 40(2). Five percentage points per quarter or part thereof.
RULE_40_2_POINTS_PER_QUARTER = 5

#: Rule 44(1)(b), reached through Rule 44(6). Useful life taken as five years.
RULE_44_1B_USEFUL_LIFE_MONTHS = 60

#: The two readings, named so a caller cannot mistype one.
BY_QUARTERS = "rule_40_2"
BY_MONTHS = "rule_44_6"


@dataclass(frozen=True)
class TaxHeads:
    """One amount split the way the return splits it."""
    cgst_paise: int = 0
    sgst_paise: int = 0
    igst_paise: int = 0

    @property
    def total_paise(self) -> int:
        return self.cgst_paise + self.sgst_paise + self.igst_paise

    def scaled_up(self, numerator: int, denominator: int) -> "TaxHeads":
        """Each head × numerator/denominator, rounded UP. See the module note
        on why every rounding here goes up."""
        if denominator <= 0:
            return TaxHeads()
        n = max(0, int(numerator))

        def up(v: int) -> int:
            return -((-int(v) * n) // denominator)

        return TaxHeads(up(self.cgst_paise), up(self.sgst_paise), up(self.igst_paise))


@dataclass(frozen=True)
class Limb:
    """One reading of the reduced-credit limb, with its working."""
    reading: str                 # BY_QUARTERS | BY_MONTHS
    elapsed: int                 # quarters, or months, depending on the reading
    remaining_fraction: str      # the working, as a person would write it
    reduced_credit: TaxHeads
    amount_payable: TaxHeads     # the HIGHER of the reduced credit and limb (b)
    basis: str                   # "reduced_credit" | "transaction_value"


@dataclass(frozen=True)
class Section186Result:
    applies: bool
    credit_taken: TaxHeads
    tax_on_transaction_value: TaxHeads
    readings: tuple[Limb, ...]
    caveats: tuple[str, ...] = field(default_factory=tuple)
    gaps: tuple[str, ...] = field(default_factory=tuple)

    @property
    def readings_agree(self) -> bool:
        """True when both readings demand the same amount — which they do
        whenever the transaction-value limb wins, and that is the common case
        on an asset sold at a sensible price."""
        amounts = {r.amount_payable.total_paise for r in self.readings}
        return len(amounts) <= 1


def _whole_months_between(start: date, end: date) -> int:
    """Complete months elapsed. A PART month does not count.

    That leaves the remaining useful life LARGER, so the reduced credit is
    larger and the amount payable can only be larger or equal — the direction
    that cannot leave a shortfall. Stated because it is a convention rather
    than something Rule 44(1)(b) spells out.
    """
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(0, months)


def _quarters_or_part(start: date, end: date) -> int:
    """Rule 40(2)'s count: quarters or PART thereof, from the invoice date.

    "Or part thereof" is the statute's own words, so any incomplete quarter
    counts as a whole one — and the PART DAYS count too, which is why this
    cannot be `ceil(whole_months / 3)`. Exactly three months after the invoice
    is one quarter; a single day more is two, because a second quarter has
    begun. Flooring to whole months first loses that day and under-charges the
    reduction by a whole quarter on every disposal that lands just past a
    quarter end.

    Zero elapsed time is still one quarter: an asset sold the day it was
    bought has had a quarter begin.
    """
    months = _whole_months_between(start, end)
    # Anything past the last whole month. `_whole_months_between` decrements
    # when the day-of-month has not come round, so re-adding the months it
    # counted and comparing dates is what detects the leftover days.
    anniversary_y, anniversary_m = divmod(start.month - 1 + months, 12)
    try:
        anniversary = start.replace(year=start.year + anniversary_y,
                                    month=anniversary_m + 1)
    except ValueError:
        # 31 January + 1 month has no 31 February; the month end is the
        # anniversary, and anything after it is a leftover day.
        import calendar as _cal
        last = _cal.monthrange(start.year + anniversary_y, anniversary_m + 1)[1]
        anniversary = date(start.year + anniversary_y, anniversary_m + 1, last)
    has_part_days = end > anniversary

    whole_quarters, leftover_months = divmod(months, 3)
    if leftover_months or has_part_days:
        whole_quarters += 1
    return max(1, whole_quarters)


def _higher(a: TaxHeads, b: TaxHeads) -> tuple[TaxHeads, str]:
    """s.18(6)'s "whichever is higher", compared on the TOTAL.

    The comparison in the section is of two amounts, singular; Rule 44(6)'s
    "determined separately for ... central tax, State tax ... and integrated
    tax" governs how limb (a) is WORKED OUT, not how the two limbs are ranked.
    Ranking head by head would let a sale pay the credit limb on one head and
    the value limb on another, which is not a figure the section describes.
    """
    if a.total_paise >= b.total_paise:
        return a, "reduced_credit"
    return b, "transaction_value"


def _rupees(paise: int) -> str:
    """A caveat is read by a person, so it says rupees."""
    return f"Rs {rupees_paise(paise)}"


def _iso(value) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


_HEAD_MISMATCH = (
    "The credit was taken as {took} and the sale is charged as {sells}. "
    "s.18(6) does not say which head the reduced-credit limb is paid in when "
    "they differ, so the working shows it in the head the credit was taken in "
    "— confirm the head before paying."
)

_PROVISO = (
    "The proviso to s.18(6) lets refractory bricks, moulds and dies, jigs and "
    "fixtures supplied AS SCRAP pay tax on the transaction value alone. It is "
    "the taxable person's option and this register does not record the asset "
    "class, so it is not applied here."
)

_TWO_RULES = (
    "Rule 40(2) reduces the credit by five percentage points a quarter or part "
    "quarter; Rule 44(6), through Rule 44(1)(b), pro-rates it over the "
    "remaining useful life in months out of sixty. Both readings are shown "
    "because they give different figures and neither could be read against the "
    "Rules from this environment."
)


def compute(*, credit_taken: TaxHeads, itc_was_taken: Optional[bool],
            invoice_date, disposal_date,
            proceeds_paise: int, rate_bps: Optional[int],
            is_interstate: bool = False,
            is_supply: Optional[bool] = None) -> Section186Result:
    """The s.18(6) working for one disposal.

    `proceeds_paise` is what the buyer paid and is TAX-INCLUSIVE — the same
    convention `domain/banking/charge_gst` uses for an amount that crossed the
    bank, and the same engine backs the tax out of it, so the split is exact
    and the journal balances without a plug.

    `itc_was_taken` is `fixed_assets.itc_eligible`: True where credit was
    claimed, False where CGST §17(5) blocked it (and the tax was capitalised
    instead), and **None where nothing was recorded** — a pre-343 asset. None
    is not False: it is refused and named, because assuming no credit was
    taken would drop the reduced-credit limb entirely and can only understate.
    """
    gaps: list[str] = []
    caveats: list[str] = [_PROVISO]

    if is_supply is False:
        return Section186Result(
            applies=False, credit_taken=credit_taken,
            tax_on_transaction_value=TaxHeads(), readings=(),
            caveats=("Recorded as not a supply, so no output tax is charged "
                     "and s.18(6) is not reached. s.18(6) still applies to a "
                     "supply of capital goods on which credit was taken — if "
                     "this disposal turns out to be one, re-record it.",),
            gaps=())
    if is_supply is None:
        gaps.append(
            "Nobody has said whether this disposal is a SUPPLY. A sale for "
            "consideration is; a scrapping for nothing, or a transfer whose "
            "treatment turns on Schedule I, may not be — and no ledger holds "
            "the facts that decide it.")

    # ── limb (b): the tax on the transaction value, s.15 ─────────────────────
    tax_on_value = TaxHeads()
    if rate_bps is None:
        gaps.append(
            "No GST rate is recorded for this disposal, so the tax on the "
            "transaction value cannot be computed and the s.18(6) comparison "
            "has only one side.")
    elif int(rate_bps) not in ALLOWED_RATES_BPS:
        gaps.append(f"GST rate {rate_bps} bps is not a rate this engine holds.")
        rate_bps = None
    elif proceeds_paise > 0 and int(rate_bps) > 0:
        sp = split_inclusive_charge(int(proceeds_paise), int(rate_bps),
                                    bool(is_interstate))
        tax_on_value = TaxHeads(sp.cgst_paise, sp.sgst_paise, sp.igst_paise)

    # ── limb (a): the credit taken, reduced ──────────────────────────────────
    inv = _iso(invoice_date)
    disp = _iso(disposal_date)
    if itc_was_taken is None:
        gaps.append(
            "The asset does not record whether input tax credit was taken on "
            "it (a pre-343 row), so the reduced-credit limb of s.18(6) cannot "
            "be worked out. It is not assumed to be nil: that would drop the "
            "limb that can be the higher one.")
    elif itc_was_taken is False:
        caveats.append(
            "No input tax credit was taken on this asset (CGST §17(5) blocked "
            "it and the tax was capitalised), so s.18(6) does not reach the "
            "supply — only the tax on the transaction value is payable.")
    elif credit_taken.total_paise <= 0:
        caveats.append(
            "No input tax is recorded against this asset, so there is no "
            "credit for s.18(6) to reduce — only the tax on the transaction "
            "value is payable.")
    elif inv is None or disp is None:
        gaps.append(
            "The reduced-credit limb runs from the acquisition invoice date to "
            "the disposal date, and one of them is missing.")

    # The heads can differ: a machine bought locally and sold across a state
    # border took CGST+SGST credit and charges IGST. Named rather than resolved.
    took_igst = credit_taken.igst_paise > 0 and not (
        credit_taken.cgst_paise or credit_taken.sgst_paise)
    sells_igst = bool(is_interstate)
    if credit_taken.total_paise > 0 and rate_bps and took_igst != sells_igst:
        caveats.append(_HEAD_MISMATCH.format(
            took="IGST" if took_igst else "CGST + SGST",
            sells="IGST" if sells_igst else "CGST + SGST"))

    readings: list[Limb] = []
    can_reduce = (itc_was_taken is True and credit_taken.total_paise > 0
                  and inv is not None and disp is not None)
    if can_reduce:
        caveats.append(_TWO_RULES)
        quarters = _quarters_or_part(inv, disp)
        left_pct = max(0, 100 - RULE_40_2_POINTS_PER_QUARTER * quarters)
        r40 = credit_taken.scaled_up(left_pct, 100)
        pay40, basis40 = _higher(r40, tax_on_value)
        readings.append(Limb(BY_QUARTERS, quarters,
                             f"{left_pct}% of the credit taken "
                             f"({quarters} quarter{'s' if quarters != 1 else ''} "
                             f"at {RULE_40_2_POINTS_PER_QUARTER} points)",
                             r40, pay40, basis40))

        months = _whole_months_between(inv, disp)
        remaining = max(0, RULE_44_1B_USEFUL_LIFE_MONTHS - months)
        r44 = credit_taken.scaled_up(remaining, RULE_44_1B_USEFUL_LIFE_MONTHS)
        pay44, basis44 = _higher(r44, tax_on_value)
        readings.append(Limb(BY_MONTHS, months,
                             f"{remaining} of {RULE_44_1B_USEFUL_LIFE_MONTHS} "
                             f"months of useful life remaining",
                             r44, pay44, basis44))
    elif tax_on_value.total_paise or rate_bps is not None:
        # No reduced-credit limb to compare against — the supply still carries
        # its own tax, and it is the whole of what is payable.
        readings.append(Limb("transaction_value_only", 0,
                             "s.18(6) not reached — tax on the transaction "
                             "value under s.15",
                             TaxHeads(), tax_on_value, "transaction_value"))

    return Section186Result(
        applies=bool(readings),
        credit_taken=credit_taken,
        tax_on_transaction_value=tax_on_value,
        readings=tuple(readings),
        caveats=tuple(caveats),
        gaps=tuple(gaps),
    )


# ── what a disposal puts on the RETURN ───────────────────────────────────────
#
# The same shape domain/gst/bank_charge_gst takes, and for the same reason: an
# asset disposal is not a sales invoice, so `gstr3b_from_books` — which
# assembles Table 3.1(a) out of invoices and the s.34 notes — could not see the
# output tax the disposal journal now posts. The tax would have sat in the GST
# Output ledger with no return declaring it, which is the books-vs-ledger
# difference BANK-24 closed on the bank side arriving from another door.
#
# The DOCUMENT is the fixed_assets row (migration 383 records the rate that was
# posted), not the journal. Reading the tax back out of journal_lines would make
# that slice of the reconciliation compare the ledger with itself.

_DISPOSAL_RULE_46 = (
    "Output tax of {tax} is declared from asset disposals that have no tax "
    "invoice behind them. GSTR-1 is built from invoices, so it will not carry "
    "these and the portal's GSTR-1 vs GSTR-3B comparison will differ by this "
    "amount until the invoices are raised (CGST Rule 46)."
)

_DISPOSAL_18_6_EXCESS = (
    "CGST Act s.18(6) may demand more than the tax on the transaction value on "
    "{n} disposal{s}: the credit taken on the asset, reduced for the time it "
    "was held, is the higher limb under at least one reading of the Rules. "
    "This return declares the tax actually charged; the excess is raised "
    "separately — open the disposal to see both readings and the working."
)


@dataclass(frozen=True)
class DisposalSupply:
    """One disposed asset's outward supply, as the return needs to see it."""
    asset_id: str
    asset_name: str
    disposal_date: str
    proceeds_paise: int          # what the buyer paid, tax included
    taxable_paise: int           # the transaction value under s.15
    tax: TaxHeads
    section_18_6_is_higher: bool  # under at least one reading


def outward_supplies(rows: "list[dict]") -> tuple[tuple[DisposalSupply, ...],
                                                  tuple[str, ...]]:
    """Every disposal in the period that declares output tax, plus its caveats.

    A row is read only if it is DISPOSED and carries a non-zero recorded rate.
    A recorded ZERO declares nothing, for the reason the bank side records: it
    posts identically to a disposal with no rate, so nothing in the books says
    whether the supply is nil-rated, exempt, outside the levy — or, on a
    scrapping, not a supply at all. `disposal_is_supply = false` is an explicit
    "no" and is skipped for the same reason.
    """
    out: list[DisposalSupply] = []
    for row in rows:
        if not row.get("is_disposed"):
            continue
        if row.get("disposal_is_supply") is False:
            continue
        rate = row.get("disposal_gst_rate_bps")
        if rate is None or int(rate) == 0:
            continue
        proceeds = int(row.get("disposal_value_paise") or 0)
        if proceeds <= 0:
            continue
        result = compute(
            credit_taken=TaxHeads(int(row.get("cgst_paise") or 0),
                                  int(row.get("sgst_paise") or 0),
                                  int(row.get("igst_paise") or 0)),
            itc_was_taken=row.get("itc_eligible"),
            invoice_date=row.get("purchase_date"),
            disposal_date=row.get("disposal_date"),
            proceeds_paise=proceeds,
            rate_bps=int(rate),
            is_interstate=bool(row.get("disposal_is_interstate")),
            is_supply=row.get("disposal_is_supply"),
        )
        tv = result.tax_on_transaction_value
        out.append(DisposalSupply(
            asset_id=str(row.get("id") or ""),
            asset_name=str(row.get("asset_name") or ""),
            disposal_date=str(row.get("disposal_date") or "")[:10],
            proceeds_paise=proceeds,
            taxable_paise=proceeds - tv.total_paise,
            tax=tv,
            section_18_6_is_higher=any(r.basis == "reduced_credit"
                                       for r in result.readings),
        ))

    caveats: list[str] = []
    total = sum(d.tax.total_paise for d in out)
    if total:
        caveats.append(_DISPOSAL_RULE_46.format(tax=_rupees(total)))
    higher = sum(1 for d in out if d.section_18_6_is_higher)
    if higher:
        caveats.append(_DISPOSAL_18_6_EXCESS.format(
            n=higher, s="" if higher == 1 else "s"))
    return tuple(out), tuple(caveats)

