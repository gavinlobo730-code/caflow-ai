"""Does an extracted invoice add up? (PUR-21.)

WHAT WAS MISSING
    `routers/document_intelligence_v1._parse_extraction_json` coerced
    `taxable_amount_paise`, `cgst_paise`, `sgst_paise`, `igst_paise` and
    `total_paise` to integers and returned them. NOTHING CHECKED THAT THEY SUM.
    A model that misread one digit of the taxable value produced five numbers
    that looked entirely reasonable, and `_estimate_confidence` scored the
    result on FIELD PRESENCE alone — so a bill that did not add up could come
    back "high".

    The five figures are the model's reading of five printed numbers whose
    relationship the document itself asserts. Checking it costs nothing and is
    the only arithmetic evidence available about a reading nobody has verified.

WHY IT WARNS AND NEVER REFUSES
    Two legitimate reasons for a small difference:

      * The invoice's own ROUND OFF line. CGST Act §170 rounds tax to the
        nearest rupee, so a printed total can differ from the sum of its parts
        by up to 50 paise BEFORE anybody misreads anything.
      * Per-line paise. A supplier computing GST line by line and a reader
        adding the printed heads can differ by a paisa or two.

    So the tolerance is ONE RUPEE — comfortably above §170's 50 paise and the
    handful of paise a multi-line bill contributes, and far below the ten
    rupees a single transposed digit costs. A refusal here would stop a CA
    saving a correct bill; the answer is to show them the difference.

WHAT IS NOT CHECKED
    Whether the tax is at the RIGHT RATE, and whether CGST equals SGST. The
    first needs the rate, which the header does not carry; the second is true
    of an ordinary intra-state supply and false of several real ones (a bill
    mixing intra- and inter-state lines, a composite RCM bill), so asserting it
    would flag correct documents. `_compute_bill_lines_and_totals` recomputes
    all of it from the lines the moment the draft is created — this is about
    the READING, not the tax.
"""
from __future__ import annotations

# One rupee. See the module docstring: §170's round-off is 50 paise and the
# per-line remainder is a few, so a rupee absorbs both and still catches a
# misread digit, which costs ten rupees at the very least.
TOLERANCE_PAISE = 100


def check_totals(extracted: dict) -> dict:
    """`taxable + cgst + sgst + igst` against `total`, in integer paise.

    Returns a block the API can hand to the screen verbatim. `checked` is False
    where the extraction carries no total at all — an unread figure is not a
    disagreement, and reporting it as one would put a warning on every scan the
    model could not finish.
    """
    def _p(key: str) -> int:
        try:
            return int(extracted.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    taxable = _p("taxable_amount_paise")
    tax = _p("cgst_paise") + _p("sgst_paise") + _p("igst_paise")
    total = _p("total_paise")
    parts = taxable + tax

    if total <= 0 or parts <= 0:
        return {
            "checked": False,
            "sum_of_parts_paise": parts,
            "total_paise": total,
            "difference_paise": 0,
            "agrees": True,
            "tolerance_paise": TOLERANCE_PAISE,
            "note": ("The document's own total could not be read, so there is "
                     "nothing to check the parts against. Compare the figures "
                     "against the invoice before saving."),
        }

    diff = parts - total
    agrees = abs(diff) <= TOLERANCE_PAISE
    return {
        "checked": True,
        "sum_of_parts_paise": parts,
        "total_paise": total,
        "difference_paise": diff,
        "agrees": agrees,
        "tolerance_paise": TOLERANCE_PAISE,
        "note": None if agrees else (
            "The taxable value and tax read from this document do not add up "
            "to the total read from it. One of the four has been misread. "
            "Check every figure against the invoice — the bill is still saved "
            "from the LINES, which are recomputed, so a wrong header here "
            "means a wrong line somewhere too."),
    }
