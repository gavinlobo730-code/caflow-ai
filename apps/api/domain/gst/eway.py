"""Is an e-way bill required for this invoice? — CGST Rule 138.

THE THRESHOLD IS NOT MEASURED ON THE TAXABLE VALUE, and that was the defect
(SALES-17). Rule 138(1) requires an e-way bill for the movement of goods "of
consignment value exceeding fifty thousand rupees", and Explanation 2 to
Rule 138(1) defines consignment value as

    "the value, determined in accordance with the provisions of section 15,
     declared in an invoice, a bill of supply or a delivery challan, as the
     case may be, issued in respect of the said consignment and ALSO INCLUDES
     the central tax, State or Union territory tax, integrated tax and cess
     charged, if any, in the document, but shall exclude the value of exempt
     supply of goods where the invoice is issued in respect of both exempt and
     taxable supply of goods."

So the tax is part of the figure. A consignment of ₹48,000 taxable at 18% is
₹56,640 and needs an e-way bill; the browser compared ₹48,000 against ₹50,000
and told the CA one was "usually not required". Goods that move without one are
detained under §129 and the penalty is the tax plus an equal amount.

TWO MORE THINGS THE OLD TEST GOT WRONG, both in the same direction:

  * "EXCEEDING fifty thousand rupees" is a strict inequality. At exactly
    ₹50,000 no e-way bill is required, and `taxable < THRESHOLD` made the
    boundary itself "required".
  * Rule 138 governs the movement of GOODS. An invoice of pure services moves
    nothing, so the threshold never arises — it is not a small consignment.

WHAT THIS MODULE REFUSES TO DECIDE. Rule 138(14) lists fourteen cases where no
e-way bill is required whatever the value, including "goods specified in the
Annexure" — a schedule of some 150 entries this codebase does not hold and
which cannot be written from memory. A wholly exempt consignment is the one
that meets it often, so that case returns its value with a NAMED GAP rather
than a verdict. Naming it is the point: a silent "required" for goods the
Annexure exempts wastes the CA's time, and a silent "not required" for goods it
does not is a detention.

apps/web/lib/invoices/compliance.ts mirrors this, because the Compliance panel
recomputes on every keystroke and a round trip per keystroke is not a panel.
The two are pinned by shared/eway-parity-vectors.json, read by
tests/test_eway_parity.py here and scripts/eway-parity.test.ts there — the same
arrangement as the GST line maths, and for the same reason: two
implementations of a statutory rule drift.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

#: Rule 138(1). In integer paise — ₹50,000.
EWAY_THRESHOLD_PAISE: int = 50_000_00


@dataclass
class EwayLine:
    """One invoice line, as the consignment-value rule needs to see it."""
    #: EVERY FIELD IS SPELLED AS THE INVOICE LINE SPELLS IT. The browser mirror
    #: takes `ServerInvoiceLine` rows straight through with no renaming, and a
    #: mapping step is one more place for a field to be dropped silently — which
    #: is how the panel came to measure the wrong number in the first place.
    hsn_sac: Optional[str] = None
    taxable_amount_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    igst_paise: int = 0
    #: GST compensation cess. Explanation 2 includes it expressly. A sales line
    #: does not carry one today (SALES-20), so this is 0 on every real invoice
    #: — present because the rule names it, not because the column exists.
    cess_paise: int = 0
    #: Basis points, so 0 means a nil-rated line and 1800 means 18%.
    gst_rate_bps: int = 0


def is_service_code(hsn_sac: Optional[str]) -> bool:
    """A SAC — Chapter 99 of the tariff — is a service.

    Six digits beginning 99. The HSN of goods never starts 99, so this is the
    classification the invoice itself carries; nothing else on the line says
    goods or services.
    """
    code = (hsn_sac or "").strip()
    return len(code) >= 2 and code[:2] == "99" and code.isdigit()


def line_value_paise(line: EwayLine) -> int:
    """The line's share of the consignment value: §15 value plus the tax and
    cess charged in the document, per Explanation 2."""
    return (int(line.taxable_amount_paise) + int(line.cgst_paise) + int(line.sgst_paise)
            + int(line.igst_paise) + int(line.cess_paise))


@dataclass
class EwayAssessment:
    consignment_value_paise: int = 0
    threshold_paise: int = EWAY_THRESHOLD_PAISE
    exceeds_threshold: bool = False
    goods_lines: int = 0
    service_lines: int = 0
    unclassified_lines: int = 0
    #: What Explanation 2's closing limb took out, where it applied.
    excluded_exempt_paise: int = 0
    #: "required" | "not_required" | "undetermined"
    verdict: str = "undetermined"
    reason: str = ""
    gaps: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "consignment_value_paise": self.consignment_value_paise,
            "threshold_paise": self.threshold_paise,
            "exceeds_threshold": self.exceeds_threshold,
            "goods_lines": self.goods_lines,
            "service_lines": self.service_lines,
            "unclassified_lines": self.unclassified_lines,
            "excluded_exempt_paise": self.excluded_exempt_paise,
            "verdict": self.verdict,
            "reason": self.reason,
            "gaps": list(self.gaps),
        }


def assess(lines: list) -> EwayAssessment:
    """Rule 138(1) with Explanation 2, on one document's lines."""
    out = EwayAssessment()

    goods: list = []
    for raw in lines:
        line = raw if isinstance(raw, EwayLine) else EwayLine(**raw)
        if is_service_code(line.hsn_sac):
            out.service_lines += 1
            continue
        if not (line.hsn_sac or "").strip():
            # No code at all, so the document does not say whether this line is
            # goods or a service. Counted, then reported — never assumed either
            # way, because the two answers are "get an e-way bill" and "do not".
            out.unclassified_lines += 1
        else:
            out.goods_lines += 1
        goods.append(line)

    # Rule 138 is about the MOVEMENT OF GOODS. An invoice of pure services is
    # not a small consignment; the threshold never arises.
    if not goods:
        out.verdict = "not_required"
        out.reason = (
            "Every line is a service (SAC 99xxxx). Rule 138 governs the "
            "movement of goods, so no e-way bill arises."
        )
        return out

    taxable_goods = [ln for ln in goods if int(ln.gst_rate_bps) > 0]
    exempt_goods = [ln for ln in goods if int(ln.gst_rate_bps) <= 0]

    # Explanation 2's closing limb — "but shall exclude the value of exempt
    # supply of goods WHERE THE INVOICE IS ISSUED IN RESPECT OF BOTH exempt and
    # taxable supply of goods". The condition is part of the rule: on a wholly
    # exempt invoice the limb does not apply by its own terms, so the value is
    # the whole of it.
    mixed = bool(taxable_goods) and bool(exempt_goods)
    if mixed:
        out.excluded_exempt_paise = sum(line_value_paise(ln) for ln in exempt_goods)
        out.consignment_value_paise = sum(line_value_paise(ln) for ln in taxable_goods)
    else:
        out.consignment_value_paise = sum(line_value_paise(ln) for ln in goods)

    # "EXCEEDING fifty thousand rupees" — strict. At exactly ₹50,000 no e-way
    # bill is required, and the old `taxable < THRESHOLD` test made the
    # boundary itself required.
    out.exceeds_threshold = out.consignment_value_paise > EWAY_THRESHOLD_PAISE

    if out.unclassified_lines:
        out.gaps.append(
            f"{out.unclassified_lines} line(s) carry no HSN/SAC, so whether "
            f"they are goods cannot be read off the invoice. They are counted "
            f"in the consignment value, which is the direction that cannot "
            f"advise a missing e-way bill."
        )

    if exempt_goods and not taxable_goods:
        # The case Rule 138(14) most often reaches, and the one this module
        # will not decide.
        out.verdict = "undetermined"
        out.reason = (
            f"Every goods line is nil-rated or exempt. The consignment value "
            f"is {out.consignment_value_paise} paise, but Rule 138(14) lists "
            f"cases where no e-way bill is required whatever the value."
        )
        out.gaps.append(
            "Rule 138(14) — including the goods specified in the Annexure to "
            "Rule 138 — is not modelled here. Check the Annexure before "
            "deciding a wholly exempt consignment."
        )
        return out

    if out.exceeds_threshold:
        out.verdict = "required"
        out.reason = (
            f"Consignment value {out.consignment_value_paise} paise exceeds "
            f"the ₹50,000 limit in Rule 138(1). Explanation 2 to Rule 138(1) "
            f"measures it INCLUDING the tax and cess charged in the document, "
            f"not on the taxable value alone."
        )
    else:
        out.verdict = "not_required"
        out.reason = (
            f"Consignment value {out.consignment_value_paise} paise does not "
            f"exceed the ₹50,000 limit in Rule 138(1), measured including the "
            f"tax charged in the document (Explanation 2)."
        )
    return out
