"""Does an extracted invoice add up? (PUR-21, ai-02.)

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

    THAT CHECK WAS TOO NARROW (ai-02). It tested the four header figures against
    the header total and nothing that stood behind them: a bill whose LINES did
    not sum to its taxable value, whose line rates did not produce its tax, or
    whose CGST was not its SGST, passed — because the two figures it compared
    could both be wrong together, by the same misread digit, and still agree.
    Two more checks run now, from figures the document ALSO states:

      * Σ (quantity × rate) over the lines against the header taxable value;
      * each line's tax at ITS OWN stated rate, summed, against the header tax
        heads — through `domain/sales/line_tax.compute_line_gst`, the one
        implementation of the split, so a line is taxed here exactly as the same
        line would be taxed on the bill it is about to become. For an intra-State
        bill that is per head (CGST against CGST, SGST against SGST), which is
        also what catches a CGST that is not its SGST.

WHY IT WARNS AND NEVER REFUSES, AND NEVER REWRITES
    Two legitimate reasons for a small difference:

      * The invoice's own ROUND OFF line. CGST Act §170 rounds tax to the
        nearest rupee, so a printed total can differ from the sum of its parts
        by up to 50 paise BEFORE anybody misreads anything.
      * Per-line paise. A supplier computing GST line by line and a reader
        adding the printed heads can differ by a paisa or two.

    So the tolerance is ONE RUPEE — comfortably above §170's 50 paise and the
    handful of paise a multi-line bill contributes, and far below the ten
    rupees a single transposed digit costs. A refusal here would stop a CA
    saving a correct bill; the answer is to show them the difference. And a
    legitimate bill can fail the lines check: a trade discount printed as its own
    line, freight or packing that is not a line, a quantity in one unit priced in
    another. The sentence says so rather than accusing the reading.

    NOTHING IN THE EXTRACTION IS CHANGED. A check reports; the figures stay
    exactly as the model read them, so the CA compares the screen to the paper
    and not to a corrected version of it.

WHAT IS STILL NOT CHECKED
    CGST equals SGST on the HEADER alone is not asserted: it is true of an
    ordinary intra-state supply and false of several real ones (a bill mixing
    intra- and inter-state lines, a composite RCM bill). The per-head comparison
    above is made only where the header itself is of one kind. A line with no
    quantity, rate or GST rate read cannot be checked and is NAMED as such in the
    check that could not run — an unread figure is not a disagreement
    (`domain/extraction_lines`), and reporting one as such would put a warning on
    every scan the model could not finish.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from domain.money_text import rupees_paise
from domain.sales.line_tax import compute_line_gst

# One rupee. See the module docstring: §170's round-off is 50 paise and the
# per-line remainder is a few, so a rupee absorbs both and still catches a
# misread digit, which costs ten rupees at the very least.
TOLERANCE_PAISE = 100

HEADER_SUM = "header_sum"
LINES_VS_TAXABLE = "lines_vs_taxable"
TAX_AT_LINE_RATES = "tax_at_line_rates"


def _rs(paise: int) -> str:
    return f"₹{rupees_paise(paise)}"


def _p(extracted: dict, key: str) -> int:
    try:
        return int(extracted.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _number(value) -> Optional[Decimal]:
    """A finite number as a Decimal, or None. A quantity is not money, but it is
    multiplied by money, so it is carried as the exact decimal it was printed as."""
    if value is None or isinstance(value, bool):
        return None
    try:
        d = Decimal(str(value).strip().replace(",", ""))
    except Exception:                                            # noqa: BLE001
        return None
    return d if d.is_finite() else None


def _sub(name: str, *, ran: bool, agrees: Optional[bool] = None,
         difference_paise: Optional[int] = None, reason: Optional[str] = None) -> dict:
    return {"name": name, "ran": ran, "agrees": agrees,
            "difference_paise": difference_paise, "reason": reason}


# ── the header against itself (PUR-21) ───────────────────────────────────────

def _header_check(extracted: dict) -> tuple[dict, dict]:
    """(the legacy block, the header's sub-check)."""
    taxable = _p(extracted, "taxable_amount_paise")
    tax = _p(extracted, "cgst_paise") + _p(extracted, "sgst_paise") + _p(extracted, "igst_paise")
    total = _p(extracted, "total_paise")
    parts = taxable + tax

    if total <= 0 or parts <= 0:
        note = ("The document's own total could not be read, so there is "
                "nothing to check the parts against. Compare the figures "
                "against the invoice before saving.")
        legacy = {
            "checked": False,
            "sum_of_parts_paise": parts,
            "total_paise": total,
            "difference_paise": 0,
            "agrees": True,
            "tolerance_paise": TOLERANCE_PAISE,
            "note": note,
        }
        return legacy, _sub(HEADER_SUM, ran=False, reason=note)

    diff = parts - total
    agrees = abs(diff) <= TOLERANCE_PAISE
    note = None if agrees else (
        "The taxable value and tax read from this document do not add up "
        "to the total read from it. One of the four has been misread. "
        "Check every figure against the invoice — the bill is still saved "
        "from the LINES, which are recomputed, so a wrong header here "
        "means a wrong line somewhere too.")
    legacy = {
        "checked": True,
        "sum_of_parts_paise": parts,
        "total_paise": total,
        "difference_paise": diff,
        "agrees": agrees,
        "tolerance_paise": TOLERANCE_PAISE,
        "note": note,
    }
    return legacy, _sub(HEADER_SUM, ran=True, agrees=agrees, difference_paise=diff,
                        reason=None if agrees else
                        f"The taxable value and tax read add up to {_rs(parts)} but the total "
                        f"read is {_rs(total)} — a difference of {_rs(abs(diff))}. One of the "
                        "figures has been misread.")


# ── the lines against the header (ai-02) ─────────────────────────────────────

def _read_lines(extracted: dict) -> tuple[list[dict], int, int, int]:
    """(lines with a figure each, total lines, lines missing quantity or rate,
    lines missing a GST rate). A line is judged on its VALUES, so the parser's
    own output and a body posted back are read the same way."""
    raw = extracted.get("line_items")
    items = [i for i in raw if isinstance(i, dict)] if isinstance(raw, list) else []
    out: list[dict] = []
    no_value = no_rate = 0
    for item in items:
        qty, rate = _number(item.get("quantity")), _number(item.get("rate_paise"))
        bps = _number(item.get("gst_rate_bps"))
        valued = qty is not None and qty > 0 and rate is not None and rate >= 0
        if not valued:
            no_value += 1
            continue
        taxable = int((qty * rate).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        rated = bps is not None and bps >= 0
        if not rated:
            no_rate += 1
        out.append({"taxable": taxable, "bps": int(bps) if rated else None})
    return out, len(items), no_value, no_rate


def _lines_vs_taxable(extracted: dict, lines: list[dict], n: int, no_value: int) -> dict:
    taxable = _p(extracted, "taxable_amount_paise")
    if n == 0:
        return _sub(LINES_VS_TAXABLE, ran=False,
                    reason="No line items were read, so the lines could not be added up.")
    if no_value:
        return _sub(LINES_VS_TAXABLE, ran=False, reason=(
            f"{no_value} of {n} lines have no quantity or rate read, so the lines could "
            "not be added up against the taxable value."))
    if taxable <= 0:
        return _sub(LINES_VS_TAXABLE, ran=False,
                    reason="The taxable value could not be read, so the lines have nothing "
                           "to be added up against.")
    total = sum(l["taxable"] for l in lines)
    diff = total - taxable
    agrees = abs(diff) <= TOLERANCE_PAISE
    return _sub(LINES_VS_TAXABLE, ran=True, agrees=agrees, difference_paise=diff,
                reason=None if agrees else (
                    f"The lines come to {_rs(total)} before tax (quantity × rate, added up) but "
                    f"the taxable value read from the document is {_rs(taxable)} — a difference of "
                    f"{_rs(abs(diff))}. A line may have been misread; or a discount, freight or "
                    "round-off may sit outside the lines, in which case this is not an error."))


def _tax_at_line_rates(extracted: dict, lines: list[dict], n: int,
                       no_value: int, no_rate: int) -> dict:
    if n == 0:
        return _sub(TAX_AT_LINE_RATES, ran=False,
                    reason="No line items were read, so tax could not be worked out from them.")
    if no_value or no_rate:
        parts = []
        if no_value:
            parts.append(f"{no_value} with no quantity or rate")
        if no_rate:
            parts.append(f"{no_rate} with no GST rate")
        return _sub(TAX_AT_LINE_RATES, ran=False, reason=(
            f"Of {n} lines, {' and '.join(parts)} read, so tax at the lines' own rates could "
            "not be worked out."))

    cgst_h, sgst_h, igst_h = (_p(extracted, "cgst_paise"), _p(extracted, "sgst_paise"),
                              _p(extracted, "igst_paise"))
    intra_h, inter_h = cgst_h + sgst_h, igst_h
    # The header's own kind decides which split the lines are taxed under; where
    # it is both (a mixed bill) or neither, only the TOTAL is compared.
    single_kind: Optional[bool] = None            # True = inter-State
    if inter_h > 0 and intra_h == 0:
        single_kind = True
    elif intra_h > 0 and inter_h == 0:
        single_kind = False

    cgst_e = sgst_e = igst_e = 0
    for l in lines:
        c, s, i = compute_line_gst(l["taxable"], l["bps"], bool(single_kind))
        cgst_e, sgst_e, igst_e = cgst_e + c, sgst_e + s, igst_e + i
    expected = cgst_e + sgst_e + igst_e
    header_tax = intra_h + inter_h
    diff = header_tax - expected
    problems: list[str] = []

    if abs(diff) > TOLERANCE_PAISE:
        problems.append(
            f"Tax at the lines' own rates comes to {_rs(expected)} but the tax read from the "
            f"document is {_rs(header_tax)} — a difference of {_rs(abs(diff))}. A rate, a "
            "quantity or a tax figure has been misread.")
    elif single_kind is False:
        # Total agrees; the two heads of an intra-State bill must each agree too,
        # which is what a CGST that is not its SGST breaks.
        if abs(cgst_h - cgst_e) > TOLERANCE_PAISE or abs(sgst_h - sgst_e) > TOLERANCE_PAISE:
            problems.append(
                f"CGST ({_rs(cgst_h)}) and SGST ({_rs(sgst_h)}) read from the document are not "
                f"the equal halves the lines' rates give ({_rs(cgst_e)} and {_rs(sgst_e)}). "
                "One of the two has been misread.")
    elif single_kind is True and abs(igst_h - igst_e) > TOLERANCE_PAISE:
        problems.append(
            f"IGST read from the document ({_rs(igst_h)}) is not what the lines' rates give "
            f"({_rs(igst_e)}).")
    return _sub(TAX_AT_LINE_RATES, ran=True, agrees=not problems,
                difference_paise=diff, reason=" ".join(problems) or None)


def check_totals(extracted: dict) -> dict:
    """Does the reading add up — the header against itself, and against its lines.

    Returns a block the API can hand to the screen verbatim. The first six keys
    are the header check, unchanged from PUR-21: `checked` is False where the
    extraction carries no total at all — an unread figure is not a disagreement,
    and reporting it as one would put a warning on every scan the model could not
    finish. `agrees` is the verdict of EVERY check that ran; `checks` lists the
    three with their own differences and reasons (a check that could not run says
    why, and does not count against `agrees`); `failures` is the reasons of the
    ones that ran and disagreed, written to be shown as they are.
    """
    legacy, header = _header_check(extracted)
    lines, n, no_value, no_rate = _read_lines(extracted)
    line_checks = [
        _lines_vs_taxable(extracted, lines, n, no_value),
        _tax_at_line_rates(extracted, lines, n, no_value, no_rate),
    ]
    checks = [header, *line_checks]
    failures = [c["reason"] for c in checks if c["ran"] and c["agrees"] is False and c["reason"]]
    agrees = all(c["agrees"] is not False for c in checks)
    out = dict(legacy)
    out["agrees"] = agrees
    out["checks"] = checks
    out["failures"] = failures
    if not agrees:
        # The header's own sentence stays what it always was; the line checks add
        # theirs after it, so `note` still reads as a whole in an older screen.
        extra = [f for f in failures if f != header.get("reason")]
        out["note"] = " ".join([legacy["note"], *extra]) if legacy["note"] else " ".join(extra)
    return out
