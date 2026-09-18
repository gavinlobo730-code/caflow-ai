"""
How many digits of HSN a GSTR-1 Table 12 row must carry — and who has to say.

WHAT WAS WRONG (GST-17)

    `gstr1_builder._required_hsn_digits` returned 6 above ₹5 crore, 4 above
    ₹1.5 crore and 0 below — a HYBRID that existed in no notification. The
    ₹1.5 crore rung is the PRE-2021 table's, and the digit counts beside it are
    the POST-2021 table's. Two things followed.

    A client with ₹1 crore of turnover was told HSN was optional. Notification
    78/2020-Central Tax requires FOUR digits on every B2B supply however small
    the turnover; only B2C is optional there.

    And the requirement was never ENFORCED or even reported. Its one consumer
    was

        code = (line.hsn_sac_code or "")[:max(required, len(line.hsn_sac_code or ""))]

    a slice whose length is the larger of the requirement and the code's own
    length — so it can never shorten anything. A 2-digit HSN at ₹10 crore of
    turnover came back as '99', was filed as '99', and appeared in no gap list.

AND THE COUNT WAS A CHARACTER COUNT

    The requirement was then reported against `len(code)` with no numeric test
    anywhere in the module, so 'SAC998' satisfied a six-digit requirement and
    'ABCD' a four-digit one — a gap list that was silent about exactly the
    codes the portal refuses. `is_a_code` is the rule and `problem_with` asks
    it first; see the comment above `_DIGITS_ONLY` for the two primary sources.

THE TWO TABLES, AND WHY BOTH ARE KEPT

    Notification 78/2020-Central Tax (15-10-2020), in force from 01-04-2021,
    substituted the table in Notification 12/2017-Central Tax:

        AATO above ₹5 crore        6 digits, every supply
        AATO up to ₹5 crore        4 digits on B2B; optional on B2C

    Before that date the original table applied:

        AATO above ₹5 crore        4 digits
        AATO ₹1.5 crore to ₹5 cr   2 digits
        AATO up to ₹1.5 crore      optional

    A belated GSTR-1 for a 2019 period is filed under the rule in force for
    THAT period, so both are held and the PERIOD decides — the same "fork, not
    migration" shape as `domain/tds/vocabulary` and the 23-07-2024 capital-gains
    fork. `COMMENCEMENT` is the boundary and is named rather than inlined.

⚠️  BOTH TABLES ARE [S]-GRADED. Every `.gov.in` is refused at this
    environment's egress proxy, so the thresholds and digit counts are written
    from knowledge and pinned exactly by
    `tests/test_how_many_hsn_digits_a_return_must_carry.py`. The error
    direction is benign in one place and not the other, which is why nothing
    here truncates: reporting a requirement a CA does not owe costs them a
    glance, while filing a code the portal rejects costs them the return.

AGGREGATE TURNOVER IS THE PRECEDING YEAR'S, AND NOBODY HERE HOLDS IT

    The notification reads on "aggregate turnover in the preceding Financial
    Year", which is CGST §2(6): all-India, on the PAN, including exempt
    supplies, exports and inter-State supplies between distinct persons. It is
    NOT this product's own outward turnover for the period, it is not
    `tax_audits.turnover_paise` (that is §44AB turnover for the year under
    audit — a different figure in a different year), and it cannot be derived
    from one client's books, because a second registration's supplies count
    toward it.

    So it is RECORDED by the CA, per financial year, and **NONE IS A THIRD
    STATE**. Until this module existed the API defaulted it to `0`, which is a
    real turnover figure meaning "below every threshold" — so an unrecorded
    client was silently told HSN was optional, which is the confidently wrong
    answer this file exists to stop. Zero still means zero; `None` means nobody
    has said, and is NAMED rather than assumed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

#: Notification 78/2020-Central Tax, dated 15-10-2020, in force from this date.
COMMENCEMENT = "2021-04-01"

#: ₹5 crore, in paise. Both tables use it; they disagree about what it means.
AATO_5CR_PAISE = 5_00_00_000_00
#: ₹1.5 crore, in paise. The PRE-2021 table's lower rung, abolished from
#: 01-04-2021 — kept because a belated return for an earlier period needs it,
#: and NOT because it still governs anything current.
AATO_1_5CR_PAISE = 1_50_00_000_00

#: Everything in this module is written from knowledge rather than read off the
#: notification, because egress is refused here. A test pins each number.
VERIFIED = False


@dataclass(frozen=True)
class DigitRequirement:
    """How many digits this supply owes, and where that comes from."""

    digits: int                  #: 0 means HSN is optional for this supply
    citation: str
    #: True when the answer rests on an aggregate turnover nobody recorded, in
    #: which case `digits` is the SAFE reading and the caller must say so.
    turnover_unknown: bool = False


def _pre_2021(aato_paise: int) -> int:
    if aato_paise > AATO_5CR_PAISE:
        return 4
    if aato_paise > AATO_1_5CR_PAISE:
        return 2
    return 0


def _from_2021(aato_paise: int, *, is_b2b: bool) -> int:
    if aato_paise > AATO_5CR_PAISE:
        return 6
    # The lower band is where the old code was wrong: four digits are required
    # on a B2B supply at ANY turnover, and only B2C is optional.
    return 4 if is_b2b else 0


def required_digits(aato_paise: Optional[int], *, is_b2b: bool,
                    period_start: str) -> DigitRequirement:
    """The minimum HSN digits for one supply.

    `period_start` is the first day of the return's own tax period, ISO
    YYYY-MM-DD — the fork is by PERIOD, not by when the return is prepared, so
    a belated 2019 GSTR-1 filed today still takes the earlier table.

    `aato_paise` of None means nobody has recorded the client's preceding-year
    aggregate turnover. The answer is then the STRICTEST of the band, because
    under-reporting a requirement is what files a rejected return — and it is
    flagged, so the caller reports it as a gap rather than presenting it as
    settled.
    """
    from_2021 = period_start >= COMMENCEMENT
    if aato_paise is None:
        # Strictest reading: 6 digits from 2021, 4 before it. Flagged, never
        # silently presented as the client's own requirement.
        return DigitRequirement(
            digits=6 if from_2021 else 4,
            citation=("Notification 78/2020-Central Tax" if from_2021
                      else "Notification 12/2017-Central Tax (pre-01-04-2021)"),
            turnover_unknown=True,
        )
    if from_2021:
        return DigitRequirement(
            digits=_from_2021(aato_paise, is_b2b=is_b2b),
            citation="Notification 78/2020-Central Tax",
        )
    return DigitRequirement(
        digits=_pre_2021(aato_paise),
        citation="Notification 12/2017-Central Tax (pre-01-04-2021)",
    )


#: AN HSN CODE IS A NUMBER, AND THE DIGIT COUNT IS NOT THE CHARACTER COUNT.
#:
#: `problem_with` used to answer `len(clean)` to a question about DIGITS, and
#: there was no numeric test anywhere in the module — so 'SAC998', '99-313'
#: and 'abcdef' all satisfied a six-digit requirement and 'ABCD' a four-digit
#: one, silently, on the one figure this module exists to report.
#:
#: The rule is the field's own, from two primary sources committed under
#: `docs/compliance/sources/e-invoice/`: the IRP states it as
#: `HSN_Code  ^[0-9]*$` (field regular expressions, A.1.2.2) and refuses a code
#: that fails it as error **2176** "HSN code(s)-{0} is invalid / Wrong HSN code
#: is being passed". The Act is behind that: CGST Rule 46(g) requires the "HSN
#: code" of the goods or services, and the headings it reads on are the Customs
#: Tariff's, which are numeric.
#:
#: ASCII, deliberately — Python would call '2' (superscript two) and the
#: fullwidth digits digits, neither of which is what `^[0-9]*$` admits, so a
#: `str.isdigit` test would accept a code the portal rejects.
_DIGITS_ONLY = re.compile(r"^[0-9]+$")


def is_a_code(code: Optional[str]) -> bool:
    """True where this is a well-formed HSN or SAC code: digits, at least one.

    Says nothing about whether it is LONG enough — that is the notification's
    question and `problem_with` answers it — and nothing about whether the code
    exists in the GST master, which this product does not hold (the IRP checks
    it and returns 2176).

    Exported because the gap KIND and the gap SENTENCE are two different
    answers and the builder needs both. Same shape as `uqc.normalise(u) is
    None`, which `gstr1_builder` already re-asks to tell an unrecorded unit
    from a wrong one.
    """
    return bool(_DIGITS_ONLY.match((code or "").strip()))


def problem_with(code: Optional[str], requirement: DigitRequirement) -> Optional[str]:
    """What is wrong with this HSN code, or None.

    Shaped like `gstin.problem_with` and `uqc.problem_with` deliberately — one
    shape for "what is wrong with this identifier", so a reader who has met one
    has met all three.

    NOTHING IS TRUNCATED AND NOTHING IS REFUSED. A code LONGER than the minimum
    is correct (the notification sets a floor, and an 8-digit code is a valid
    6-digit one), and a code shorter than it is the CA's to fix on the document
    — refusing the build would refuse the whole return for one line, which is
    how a CA learns to skip the validator. Nothing refuses at the API DOOR
    either, for the reason `uqc` records: a line or a product may carry a code
    somebody typed before there was anything to check it, and a 422 there makes
    that row un-editable for any unrelated change. GST-29's split is the same
    one — the client's OWN GSTIN is a hard refusal because the return is filed
    under it, while a fact ON A LINE is reported beside the return.

    THE NUMERIC TEST IS ASKED FIRST AND IS ASKED WHATEVER THE REQUIREMENT IS.
    First, because a code that is not a number cannot be counted, and reporting
    'SAC-9983' as "has 8 digits, 6 are required" would be a sentence that is
    both false and satisfied. Whatever the requirement, because a nil
    requirement makes the code OPTIONAL and does not make a wrong one
    acceptable: Table 12 files what is recorded, so a junk code on a B2C line
    below Rs 5 crore still goes to the portal and still comes back as 2176. An
    ABSENT code under a nil requirement is exactly what the notification
    permits and is the one thing that stays silent.
    """
    clean = (code or "").strip()
    if clean and not is_a_code(clean):
        return (f"HSN '{clean}' is not a code — an HSN or SAC is digits only "
                f"(the e-invoice field rule is ^[0-9]*$, and the portal refuses "
                f"anything else as error 2176)")
    if requirement.digits == 0:
        return None
    if not clean:
        return ("no HSN or SAC code — "
                f"{requirement.digits} digits are required ({requirement.citation})")
    # `clean` is all digits by the branch above, so its LENGTH is its digit
    # count. That equivalence is what the numeric test buys, and it is why
    # nothing here counts digits a second way.
    if len(clean) < requirement.digits:
        return (f"HSN '{clean}' has {len(clean)} digits; "
                f"{requirement.digits} are required ({requirement.citation})")
    return None


#: The one sentence to show when the requirement rests on a turnover nobody
#: recorded. Held here rather than written at each call site so the two screens
#: that render it cannot say different things.
TURNOVER_NOT_RECORDED = (
    "The client's aggregate turnover for the preceding financial year is not "
    "recorded, so the strictest HSN requirement is shown. CGST §2(6) aggregate "
    "turnover is all-India on the PAN and includes exempt supplies and exports, "
    "so it cannot be derived from one client's books — record it on the client's "
    "GST settings."
)


def governing_financial_year(period_start: str) -> str:
    """Which financial year's aggregate turnover governs a return for this period.

    Notification 78/2020 reads on the turnover "in the preceding Financial
    Year", so a GSTR-1 for any period inside FY 2026-27 is governed by FY
    2025-26's figure. The hop lives HERE rather than in the stored row, so a
    figure cannot be filed under the year it GOVERNS instead of the year it
    MEASURES — `client_gst_turnover.financial_year` is always the year the
    turnover happened in, and migration 401's column comment says so.

    `period_start` is ISO YYYY-MM-DD. India's financial year runs 1 April to
    31 March, so January to March belong to the year that STARTED in the
    previous April — which is exactly what `ist_fy_label` already knows, and
    why this delegates rather than doing the month arithmetic again.
    """
    from datetime import date

    from core.ist_clock import ist_fy_label, preceding_fy

    y, m, d = (int(x) for x in period_start.split("-"))
    return preceding_fy(ist_fy_label(date(y, m, d)))
