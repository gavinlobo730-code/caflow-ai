"""CGST Rule 55 — moving goods without a tax invoice, and the clocks that start.

WHY THIS IS A STATUTORY MODULE AND THE OTHER THREE PRE-INVOICE DOCUMENTS ARE NOT
    A quotation, a proforma invoice and a sales order are commercial papers the
    Act does not know (`domain/sales/order_cycle.py`). A DELIVERY CHALLAN is
    prescribed: Rule 55(1) lets the consigner issue one "in lieu of invoice at
    the time of removal of goods for transportation" in four cases, and
    Rule 55(1)(i)-(ix) says what it must contain.

    It is also the only one that can cost the client tax by being forgotten,
    because TWO of the reasons for issuing one start a clock whose expiry is a
    DEEMED SUPPLY:

      * JOB WORK. CGST s.143(3): inputs not received back within ONE YEAR of
        being sent out "shall be deemed" to have been supplied to the job
        worker ON THE DAY THEY WERE SENT OUT — so the tax is due with interest
        from a date already in the past, and the return it should have been
        declared in is filed. s.143(4) is the same for capital goods at THREE
        years. Moulds, dies, jigs, fixtures and tools are outside both.
      * GOODS SENT ON APPROVAL. s.31(7): where goods sent or taken on approval
        for sale or return are removed before the supply takes place, the
        invoice is issued before or at the time of supply, or SIX MONTHS from
        the date of removal, whichever is EARLIER.

    Neither clock is visible anywhere in a ledger: the goods left, nothing was
    billed, and no journal moved. The challan is the only record, which is why
    computing the expiry off it is the point of this module rather than a
    convenience.

WHAT THIS MODULE REFUSES TO DECIDE
    * ITC-04's PERIODICITY. Rule 45(3) requires the job-work challans to be
      reported in FORM GST ITC-04, and the period depends on the principal's
      own aggregate turnover in the preceding financial year — half-yearly
      above the limit, annually at or below it. Both the limit and the due
      dates are `[S]`-graded here (this environment's proxy refuses every
      `.gov.in`), and no turnover figure is held against a client anyway, so
      `itc_04_period` REPORTS BOTH readings and picks neither. A wrong due
      date on a statutory return is worse than none.
    * THE COMMISSIONER'S EXTENSION. The proviso to s.143(1) allows the period
      to be extended — by a further year for inputs and two for capital goods
      on the readings available here. An extension is an order addressed to
      this taxpayer, so it is RECORDED (`extended_to`) and never assumed.
    * WHETHER THE GOODS CAME BACK. That is a fact about a receipt, not a
      derivation: `received_back_on` is a column, and a challan with none is
      reported as outstanding rather than as a supply.

⚠️ GRADING. Rule 55's own text, s.143's periods and s.31(7)'s six months are
`[S]` — written from knowledge, because every `.gov.in` is refused at this
environment's egress proxy. Each figure is pinned by a test so a later change
is deliberate, and the directions are stated: an expiry computed EARLY puts
the item in front of the CA sooner, which is the safe direction for a deemed
supply.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


def _iso(value) -> Optional[date]:
    """'YYYY-MM-DD' → date, or None. PostgREST hands a DATE back as a string.

    Local, like `section_18_6._iso`, rather than imported from another GST
    module: a date parser is not a statutory rule, and reaching into an
    unrelated module for one couples two engines that have nothing to say to
    each other.
    """
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


# ── Why a challan was issued ─────────────────────────────────────────────────
#
# The vocabulary IS Rule 55(1)'s four limbs plus the two later sub-rules that
# describe a movement of their own. Each value is the reason a CA would give,
# not a code: the reason decides which clock runs and what the document must
# say, so a free-text field here would make both underivable.

#: Rule 55(1)(a) — supply of liquid gas where the quantity at removal is not known.
REASON_LIQUID_GAS = "liquid_gas_quantity_unknown"
#: Rule 55(1)(b) — transportation of goods for job work. Rule 45 and s.143.
REASON_JOB_WORK = "job_work"
#: Rule 55(1)(c) — transportation for reasons OTHER THAN by way of supply.
REASON_NOT_A_SUPPLY = "other_than_supply"
#: Rule 55(1)(c) again, but the case s.31(7) puts a six-month clock on.
REASON_ON_APPROVAL = "sale_on_approval"
#: Rule 55(4) — a supply to the recipient whose tax invoice could not be
#: issued at removal. The invoice follows delivery.
REASON_INVOICE_TO_FOLLOW = "supply_invoice_to_follow"
#: Rule 55(5) — semi-knocked-down or completely-knocked-down goods, or a
#: supply in batches or lots. The COMPLETE invoice precedes the first
#: consignment and each later one travels on a challan citing it.
REASON_SKD_CKD_OR_LOTS = "skd_ckd_or_lots"

REASONS = (REASON_LIQUID_GAS, REASON_JOB_WORK, REASON_NOT_A_SUPPLY,
           REASON_ON_APPROVAL, REASON_INVOICE_TO_FOLLOW, REASON_SKD_CKD_OR_LOTS)

REASON_LABELS = {
    REASON_LIQUID_GAS: "Liquid gas — quantity not known at removal (Rule 55(1)(a))",
    REASON_JOB_WORK: "Job work (Rule 55(1)(b), Rule 45, s.143)",
    REASON_NOT_A_SUPPLY: "Reasons other than by way of supply (Rule 55(1)(c))",
    REASON_ON_APPROVAL: "Sent on approval for sale or return (s.31(7))",
    REASON_INVOICE_TO_FOLLOW: "Supply — tax invoice to follow delivery (Rule 55(4))",
    REASON_SKD_CKD_OR_LOTS: "SKD/CKD or supplied in batches or lots (Rule 55(5))",
}

#: Said once, here, because it is the reason a challan's lines come back with
#: no tax on them and a screen that paraphrased it would be a second statement
#: of Rule 55(1)(vii).
NO_TAX_ON_A_NON_SUPPLY = (
    "This movement is not a supply to the consignee, so CGST Rule 55(1)(vii) "
    "asks for no tax rate or amount on the challan and none is charged."
)

#: Which reasons describe a movement that IS a supply to the consignee. The
#: distinction is load-bearing twice over: Rule 55(1)(vii) requires the tax
#: rate and amount on the challan only "where the transportation is for supply
#: to the consignee", and a movement that is not a supply must never reach
#: GSTR-1.
REASONS_THAT_ARE_A_SUPPLY = (REASON_LIQUID_GAS, REASON_INVOICE_TO_FOLLOW,
                             REASON_SKD_CKD_OR_LOTS)


# ── The three copies, Rule 55(2) ─────────────────────────────────────────────
#
# Printed verbatim because the rule prescribes the WORDS, not merely that
# three copies exist. A challan whose copies are unmarked is a challan the
# officer at the check-post can object to.
COPIES = (
    ("original", "ORIGINAL FOR CONSIGNEE"),
    ("duplicate", "DUPLICATE FOR TRANSPORTER"),
    ("triplicate", "TRIPLICATE FOR CONSIGNER"),
)


# ── The particulars, Rule 55(1)(i)-(ix) ──────────────────────────────────────

@dataclass(frozen=True)
class Particular:
    clause: str
    label: str
    #: What the document holds for it, or None where nothing does.
    value: Optional[str] = None
    #: True where the rule requires it for THIS challan. Two of the nine are
    #: conditional and stating them as unconditional would report a gap on
    #: every domestic non-supply movement.
    required: bool = True

    def as_dict(self) -> dict:
        return {"clause": self.clause, "label": self.label,
                "value": self.value, "required": self.required}


def particulars(*, challan_no: str, challan_date: str,
                consigner_name: Optional[str], consigner_gstin: Optional[str],
                consigner_address: Optional[str],
                consignee_name: Optional[str], consignee_gstin: Optional[str],
                consignee_address: Optional[str],
                reason: str, is_inter_state: bool,
                place_of_supply: Optional[str],
                lines: Optional[list] = None) -> list[Particular]:
    """Rule 55(1)'s nine clauses against what this challan actually holds.

    TWO CLAUSES ARE CONDITIONAL AND THE CONDITIONS ARE DIFFERENT:
      * (vii) tax rate and amount — only "where the transportation is for
        supply to the consignee". A challan for job work carries no tax,
        because there is no supply to charge it on.
      * (viii) place of supply — only "in case of inter-State movement".

    The GSTIN clauses are qualified "IF REGISTERED", so an unregistered
    consignee is not a gap; and quantity may be PROVISIONAL, which is the
    whole reason Rule 55(1)(a) exists.
    """
    rows = list(lines or [])
    is_supply = reason in REASONS_THAT_ARE_A_SUPPLY
    return [
        Particular("55(1)(i)", "Date and number of the delivery challan",
                   f"{challan_no} dated {challan_date}"
                   if challan_no and challan_date else None),
        Particular("55(1)(ii)", "Name, address and GSTIN of the consigner, if registered",
                   _party(consigner_name, consigner_address, consigner_gstin)),
        Particular("55(1)(iii)",
                   "Name, address and GSTIN or UIN of the consignee, if registered",
                   _party(consignee_name, consignee_address, consignee_gstin)),
        Particular("55(1)(iv)", "HSN code and description of goods",
                   _hsn_summary(rows)),
        Particular("55(1)(v)",
                   "Quantity (provisional, where the exact quantity is not known)",
                   _qty_summary(rows)),
        Particular("55(1)(vi)", "Taxable value", _value_summary(rows)),
        Particular("55(1)(vii)",
                   "Tax rate and amount, where the transportation is for supply "
                   "to the consignee",
                   _tax_summary(rows) if is_supply else None,
                   required=is_supply),
        Particular("55(1)(viii)", "Place of supply, in case of inter-State movement",
                   (place_of_supply or None) if is_inter_state else None,
                   required=bool(is_inter_state)),
        # Signature is on the printed copy and cannot be a database column. It
        # is listed so the nine clauses are all present on the CA's checklist
        # rather than eight with one silently dropped.
        Particular("55(1)(ix)", "Signature", None),
    ]


def missing_particulars(rows: list) -> list[str]:
    """The required clauses this challan cannot fill in, in clause order."""
    return [f"{p.clause} {p.label}" for p in rows
            if p.required and not (p.value or "").strip()
            and p.clause != "55(1)(ix)"]


def _party(name, address, gstin) -> Optional[str]:
    bits = [b for b in (name, address, gstin) if (b or "").strip()]
    return ", ".join(str(b).strip() for b in bits) or None


def _hsn_summary(rows: list) -> Optional[str]:
    if not rows:
        return None
    codes = [str(r.get("hsn_sac") or "").strip() for r in rows]
    named = [c for c in codes if c]
    if len(named) < len(rows):
        # Rule 46(h)'s HSN is required on the challan too. A partial answer is
        # reported as absent rather than as present-for-some, because the
        # officer reads the document line by line.
        return None
    return ", ".join(sorted(set(named)))


def _qty_summary(rows: list) -> Optional[str]:
    if not rows:
        return None
    return f"{len(rows)} line(s)"


def _value_summary(rows: list) -> Optional[str]:
    if not rows:
        return None
    return str(sum(int(r.get("taxable_amount_paise") or 0) for r in rows))


def _tax_summary(rows: list) -> Optional[str]:
    if not rows:
        return None
    total = sum(int(r.get("cgst_paise") or 0) + int(r.get("sgst_paise") or 0)
                + int(r.get("igst_paise") or 0) + int(r.get("cess_paise") or 0)
                for r in rows)
    # A nil figure is a real answer here — a nil-rated or exempt supply moves
    # on a challan carrying no tax — so zero is returned as "0", not as None.
    return str(total)


# ── The clocks ───────────────────────────────────────────────────────────────

#: s.143(1): inputs back within ONE year. `[S]`.
JOB_WORK_INPUT_MONTHS = 12
#: s.143(1): capital goods within THREE years. `[S]`.
JOB_WORK_CAPITAL_GOODS_MONTHS = 36
#: s.31(7): six months from removal, for goods sent on approval. `[S]`.
ON_APPROVAL_MONTHS = 6

#: s.143(1)'s second proviso puts these outside both periods entirely. Named
#: rather than modelled as a period of `None`, because "no clock" and "a clock
#: nobody computed" must not look the same on a screen.
JOB_WORK_EXCLUDED = ("moulds", "dies", "jigs", "fixtures", "tools")
JOB_WORK_EXCLUSION = (
    "CGST Act s.143(1), second proviso: moulds and dies, jigs and fixtures, or "
    "tools sent to a job worker are outside the one-year and three-year "
    "periods, so no deemed supply arises on them however long they stay out."
)

#: What is sent out, because the two periods differ by a factor of three.
#: NULL is a real third state and is REFUSED rather than defaulted to inputs:
#: defaulting to the shorter period would report a deemed supply two years
#: before one arises, and defaulting to the longer would hide one for two
#: years. The CA says which.
GOODS_KIND_INPUTS = "inputs"
GOODS_KIND_CAPITAL_GOODS = "capital_goods"
GOODS_KIND_EXCLUDED = "moulds_dies_jigs_fixtures_tools"
GOODS_KINDS = (GOODS_KIND_INPUTS, GOODS_KIND_CAPITAL_GOODS, GOODS_KIND_EXCLUDED)


def _add_months(d: date, months: int) -> date:
    """The same calendar day, `months` later; the month's last day if short.

    31 March plus twelve months is 31 March. 31 August plus six is 28 or 29
    February, because there is no 31st — and taking the 1st of the next month
    instead would put the deadline a day LATE on a deemed supply.
    """
    y, m = divmod((d.month - 1) + months, 12)
    y, m = d.year + y, m + 1
    day = d.day
    while True:
        try:
            return date(y, m, day)
        except ValueError:
            day -= 1


@dataclass
class Clock:
    """What a challan's own reason puts on the calendar."""
    applies: bool = False
    statute: str = ""
    months: Optional[int] = None
    sent_on: Optional[str] = None
    due_back_by: Optional[str] = None
    #: True once the period has run and the goods are not back. None where the
    #: question cannot be answered — no date, or the kind of goods unrecorded.
    overdue: Optional[bool] = None
    days_remaining: Optional[int] = None
    consequence: str = ""
    gaps: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"applies": self.applies, "statute": self.statute,
                "months": self.months, "sent_on": self.sent_on,
                "due_back_by": self.due_back_by, "overdue": self.overdue,
                "days_remaining": self.days_remaining,
                "consequence": self.consequence, "gaps": list(self.gaps)}


def deemed_supply_clock(*, reason: str, challan_date: Optional[str],
                        as_at: str, goods_kind: Optional[str] = None,
                        received_back_on: Optional[str] = None,
                        extended_to: Optional[str] = None) -> Clock:
    """When this movement becomes a supply if the goods do not come back.

    THE CLOCK RUNS FROM THE DATE THE GOODS WERE SENT OUT, which is the challan
    date, and s.143(3) deems the supply to have been made ON THAT SAME DAY —
    not on the day the period expired. So the tax falls due in a return that
    has been filed, with s.50(1) interest from its own due date, and the
    difference between the two readings is a year of interest.
    """
    out = Clock()
    if reason == REASON_JOB_WORK:
        out.applies = True
        out.statute = "CGST Act s.143 with Rule 45"
        out.consequence = (
            "CGST Act s.143(3)/(4): goods not received back within the period "
            "are DEEMED to have been supplied to the job worker on the day "
            "they were sent out — so the tax is due on the challan date, in a "
            "return already filed, with s.50(1) interest running from that "
            "return's own due date.")
        if goods_kind == GOODS_KIND_EXCLUDED:
            out.applies = False
            out.months = None
            out.consequence = JOB_WORK_EXCLUSION
            return out
        if goods_kind == GOODS_KIND_INPUTS:
            out.months = JOB_WORK_INPUT_MONTHS
        elif goods_kind == GOODS_KIND_CAPITAL_GOODS:
            out.months = JOB_WORK_CAPITAL_GOODS_MONTHS
        else:
            out.gaps.append(
                "Whether these are inputs or capital goods is not recorded, "
                "and the periods differ by a factor of three (one year against "
                "three). Record it on the challan — defaulting to either one "
                "would report a deemed supply two years early or hide one for "
                "two years.")
            return out
    elif reason == REASON_ON_APPROVAL:
        out.applies = True
        out.statute = "CGST Act s.31(7)"
        out.months = ON_APPROVAL_MONTHS
        out.consequence = (
            "CGST Act s.31(7): where goods sent on approval are removed before "
            "the supply takes place, the tax invoice is issued before or at "
            "the time of supply, or six months from the date of removal, "
            "WHICHEVER IS EARLIER. Six months without a sale is itself the "
            "trigger.")
    else:
        return out

    sent = _iso(challan_date) if challan_date else None
    if sent is None:
        out.gaps.append("The challan carries no date, so the period cannot be run.")
        return out
    out.sent_on = sent.isoformat()

    due = _add_months(sent, int(out.months))
    # An extension is an ORDER addressed to this taxpayer. It is honoured only
    # where it is LATER than the statutory date: a recorded date earlier than
    # the Act's own would shorten a period the Commissioner has no power to
    # shorten, and is far more likely a typo.
    if extended_to:
        ext = _iso(extended_to)
        if ext and ext > due:
            due = ext
            out.statute += " (extended by order, proviso to s.143(1))"
    out.due_back_by = due.isoformat()

    if received_back_on:
        back = _iso(received_back_on)
        if back is not None:
            out.overdue = back > due
            out.days_remaining = 0
            return out

    today = _iso(as_at)
    if today is None:
        return out
    out.overdue = today > due
    out.days_remaining = (due - today).days
    return out


# ── Rule 55(5): SKD/CKD and supplies in lots ─────────────────────────────────
#
# Four requirements in one sub-rule and they are easy to half-do. The invoice
# comes FIRST here, which inverts the usual order and is the part that catches
# people out.
RULE_55_5_STEPS = (
    "55(5)(a) The COMPLETE invoice is issued BEFORE dispatch of the first "
    "consignment.",
    "55(5)(b) A delivery challan is issued for each of the SUBSEQUENT "
    "consignments, giving a reference of the invoice.",
    "55(5)(c) Each consignment travels with copies of its own delivery challan "
    "and a duly certified copy of the invoice.",
    "55(5)(d) The ORIGINAL copy of the invoice is sent with the LAST "
    "consignment.",
)


def rule_55_5_gaps(*, reason: str, invoice_id: Optional[str],
                   is_first_consignment: Optional[bool]) -> list:
    """What a batches-and-lots challan is missing, in the rule's own terms."""
    if reason != REASON_SKD_CKD_OR_LOTS:
        return []
    gaps: list = []
    if not invoice_id:
        gaps.append(
            "Rule 55(5)(a)/(b): the complete tax invoice is issued before the "
            "FIRST consignment and every subsequent challan must reference it. "
            "No invoice is linked to this challan.")
    if is_first_consignment:
        gaps.append(
            "Rule 55(5)(b) puts a delivery challan on the SUBSEQUENT "
            "consignments. The first travels on the complete invoice itself.")
    return gaps


# ── FORM GST ITC-04, Rule 45(3) ──────────────────────────────────────────────
#
# REPORTED, NEVER CHOSEN. See the module docstring.
ITC_04_READINGS = (
    "Above the turnover limit in the preceding financial year: HALF-YEARLY — "
    "April to September due 25 October, October to March due 25 April.",
    "At or below it: ANNUALLY for the financial year, due 25 April.",
)
ITC_04_REFUSAL = (
    "Rule 45(3) requires the job-work challans of a period to be reported in "
    "FORM GST ITC-04, and which period applies turns on the principal's own "
    "aggregate turnover in the preceding financial year — a figure this "
    "product does not hold against a client. Both readings are shown; neither "
    "is chosen, because a wrong due date on a statutory return is worse than "
    "none. Confirm the current limit and dates against the notification in "
    "force."
)


def itc_04_period(_turnover_paise: Optional[int] = None) -> dict:
    """What a CA has to settle before an ITC-04 can be prepared.

    The parameter exists and is deliberately UNUSED: the moment a turnover
    figure is held against a client, the limit is the only thing still missing
    and this becomes a one-line change rather than a new signature.
    """
    return {"decided": False, "readings": list(ITC_04_READINGS),
            "refusal": ITC_04_REFUSAL}
