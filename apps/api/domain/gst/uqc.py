"""
A UNIT QUANTITY CODE IS A CODE, NOT A WORD — and this is the one place that
knows which codes exist.

CBIC fixes the set of Unit Quantity Codes a GSTR-1 HSN summary (Table 12) and
an e-invoice may carry. "PIECES" is not one of them; "PCS" is. The portal
validates against this list, so a unit that is not on it is either rejected at
upload or — worse — accepted into a return that then says something untrue
about what was supplied.

WHY THE LIST MOVED HERE. It was `models/uqc.py`, whose own docstring named
every place it was meant to be used ("Product/Service catalogue,
firm_hsn_library, and (for goods lines only) sales invoice / purchase bill
line items") — and it had **zero importers**. Three validators cited
`VALID_UQC_CODES` in their COMMENTS and none imported it. The one authority in
the codebase for this question was unreachable from every place that asks it —
the same shape as the retired TDS rate master, a store whose name reads like
the authority and which nothing reads. (Not named here on purpose: a guard
reserves that table's name so that ANY occurrence of it in `apps/api` fails,
which is right, because a real read of it could be a raw SQL string no AST
walk would recognise. CLAUDE.md carries the cross-reference.)

`models/` is the API boundary — Pydantic request and response shapes — so a
domain module importing from it is the wrong direction and one refactor from a
cycle, the same reasoning that moved Schedule II Part C out of
`routers/fixed_assets.py`. The list therefore lives here with the RULE over
it, and `models/uqc.py` re-exports the old names so any import still resolves.

WHY NOTHING REFUSES. The two normalisers that DO exist record a reason that is
still right: a product or an invoice line may carry a pre-dropdown free-text
unit, and rejecting it at the API boundary would make that row un-editable for
any unrelated change. What was wrong was not the carve-out but the conclusion
drawn from it — "the dropdown only offers valid UQC codes, so new data is
compliant by construction" — which is a claim about every write door, and this
codebase has found that claim false twice (the supplier master wrote a table no
purchase path read; the GSTIN check digit was enforced on create and not on
bulk import or PATCH).

So the answer is GST-29's split, applied to a different identifier: the
document is never refused, and the RETURN reports. `problem_with` is shaped
like `domain/gst/gstin.problem_with` deliberately — one shape for "what is
wrong with this identifier", returning None when nothing is.

⚠️ `[S]`-graded. Every `.gov.in` is refused at this environment's egress proxy,
so the 44 codes below were not read off a CBIC page in this pass; they are the
list this repository already held, carried across verbatim rather than
retyped, and pinned by a test. `apps/web/lib/constants/uqc.ts` is the keystroke
mirror and `tests/test_a_uqc_is_a_code_not_a_word.py` holds the two identical —
the Schedule III caption lesson, where two copies of one vocabulary drifted in
BOTH directions at once and silently discarded the CA's own decisions. There is
deliberately NO endpoint serving this: it is a 44-entry constant that changes
by CBIC notification and effectively never, so an endpoint would be a
Singapore-to-Mumbai round trip for a static list, and a parity test already
prevents the drift an endpoint would prevent.
"""
from __future__ import annotations

from typing import Iterable, Optional

# (code, label) in CBIC's own order. Carried verbatim from the list this
# repository already held — see the [S] note above.
UQC_CODES: list[tuple[str, str]] = [
    ("BAG", "BAGS"),
    ("BAL", "BALE"),
    ("BDL", "BUNDLES"),
    ("BKL", "BUCKLES"),
    ("BOU", "BILLION OF UNITS"),
    ("BOX", "BOX"),
    ("BTL", "BOTTLES"),
    ("BUN", "BUNCHES"),
    ("CAN", "CANS"),
    ("CBM", "CUBIC METERS"),
    ("CCM", "CUBIC CENTIMETERS"),
    ("CMS", "CENTIMETERS"),
    ("CTN", "CARTONS"),
    ("DOZ", "DOZENS"),
    ("DRM", "DRUMS"),
    ("GGK", "GREAT GROSS"),
    ("GMS", "GRAMMES"),
    ("GRS", "GROSS"),
    ("GYD", "GROSS YARDS"),
    ("KGS", "KILOGRAMS"),
    ("KLR", "KILOLITRE"),
    ("KME", "KILOMETRE"),
    # LTR was MISSING until 18-09-2026 and it is the commonest liquid
    # unit in India — every dairy, paint, chemical, oil and beverage
    # client. The omission was a transcription slip between KME and
    # MLT, and it cost a FALSE gap on a valid code rather than a wrong
    # figure: Table 12 reported "LTR is not a UQC" on every such line
    # and `closest_code` offered MLT, which is a THOUSAND times
    # smaller. A CA who took the suggestion would have declared a
    # quantity three orders of magnitude out. Read off NIC's own
    # Master Codes list on the e-invoice portal.
    ("LTR", "LITRES"),
    ("MLT", "MILILITRE"),
    ("MTR", "METERS"),
    ("MTS", "METRIC TON"),
    ("NOS", "NUMBERS"),
    ("PAC", "PACKS"),
    ("PCS", "PIECES"),
    ("PRS", "PAIRS"),
    ("QTL", "QUINTAL"),
    ("ROL", "ROLLS"),
    ("SET", "SETS"),
    ("SQF", "SQUARE FEET"),
    ("SQM", "SQUARE METERS"),
    ("SQY", "SQUARE YARDS"),
    ("TBS", "TABLETS"),
    ("TGM", "TEN GROSS"),
    ("THD", "THOUSANDS"),
    ("TON", "TONNES"),
    ("TUB", "TUBES"),
    ("UGS", "US GALLONS"),
    ("UNT", "UNITS"),
    ("YDS", "YARDS"),
    ("OTH", "OTHERS"),
]

VALID_UQC_CODES = frozenset(code for code, _ in UQC_CODES)

# The three answers this module gives, named so a caller cannot spell one
# differently from the test that pins it.
GAP_UQC_NOT_RECORDED = "gstr1_hsn_uqc_not_recorded"
GAP_UQC_NOT_A_CODE = "gstr1_hsn_uqc_not_a_code"
GAP_UQC_MIXED_FOR_ONE_HSN = "gstr1_hsn_uqc_mixed_for_one_hsn"


def normalise(unit: Optional[str]) -> Optional[str]:
    """Case and whitespace only — never a substitution.

    Called on STORED data as well as on a request, so it cannot assume the
    Pydantic normalisers have already run: rows predate them.
    """
    if unit is None:
        return None
    cleaned = unit.strip().upper()
    return cleaned or None


def is_valid(unit: Optional[str]) -> bool:
    return normalise(unit) in VALID_UQC_CODES


def problem_with(unit: Optional[str]) -> Optional[str]:
    """What is wrong with this unit, or None when nothing is.

    Shaped like `domain/gst/gstin.problem_with`. The two cases are DIFFERENT
    and are worded differently, because what the CA has to go and do differs:
    an absent unit needs recording, and a wrong one needs correcting to the
    code that means what they already wrote.
    """
    cleaned = normalise(unit)
    if cleaned is None:
        return ("No unit of measure is recorded. CGST Rule 46(h) requires the "
                "quantity and its unit on a tax invoice for goods, and GSTR-1 "
                "Table 12 reports it as a Unit Quantity Code.")
    if cleaned in VALID_UQC_CODES:
        return None
    suggestion = closest_code(cleaned)
    tail = f" Did you mean {suggestion}?" if suggestion else ""
    return (f"{cleaned!r} is not a Unit Quantity Code. GSTR-1 Table 12 and the "
            f"e-invoice schema accept only CBIC's fixed list.{tail}")


def closest_code(unit: str) -> Optional[str]:
    """A suggestion, never a substitution.

    Deliberately a PREFIX/containment match on the LABEL rather than an edit
    distance: 'PIECES' is the label of 'PCS' and 'CARTONS' of 'CTN', so the
    word a CA actually typed is usually the label itself. An edit distance
    would confidently pair 'TON' with 'TUB' (distance 2) and say so.
    """
    cleaned = normalise(unit)
    if not cleaned:
        return None
    for code, label in UQC_CODES:
        if cleaned == label:
            return code
    for code, label in UQC_CODES:
        if cleaned.startswith(label) or label.startswith(cleaned):
            return code
    return None


def one_unit_for(units: Iterable[Optional[str]]) -> Optional[list[str]]:
    """The DISTINCT recorded units in a group, when there is more than one.

    Table 12 carries ONE uqc per row, so a group of lines sharing an HSN whose
    units differ cannot be declared without either losing a unit or adding a
    row. None means the group is consistent and there is nothing to report;
    a list means it is not, and the caller names them.

    An UNRECORDED unit is not counted as a distinct value here — it is its own
    gap (`GAP_UQC_NOT_RECORDED`), reported per line, and folding it in would
    report one defect twice under two names.
    """
    distinct = sorted({u for u in (normalise(x) for x in units) if u})
    return distinct if len(distinct) > 1 else None
