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

from . import hsn_digits


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


def sent_on(value) -> Optional[date]:
    """The day the goods went out, as the challan's date reads, or None where it reads as no date (PostgREST hands a DATE back as a string). Public because the issue door asks it (POST-A-398)."""
    return _iso(value)


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


def goods_back_problem(sent_on: Optional[date], back_on: date, today: date) -> Optional[str]:
    """The sentence for a day the goods cannot have come back on, or None (PRE-A-015, seventeenth slice).

    CGST Act s.143 and Rule 45 (FORM GST ITC-04): the day goods sent to a job worker come back is the day the s.143 clock stops (`deemed_supply_clock`) and the day Table 5A reports a return.
    It has happened by the time it is recorded, so it is not after `today` (India's: the caller's), and goods cannot have come back before they went out. Those are the plain order of events:
    no period, rate or other statutory reading is added here. It is the one rule of both doors that record it: a lot on FORM GST ITC-04 (`itc_04_service.record_return`) and the
    whole-challan "received back" (`sales_cycle_service.update_challan`; the day the goods went out cannot be amended once a challan is issued, POST-A-416, so the order is asked of a back day only), which differ only in whether
    the day the goods were sent is known where the date is first read (`sent_on` is None there, and the stored challan is compared later). Pure: no clock.
    """
    if sent_on is not None and back_on < sent_on:
        return (f"The goods cannot have come back on {back_on.isoformat()}, before "
                f"they were sent out on {sent_on.isoformat()}.")
    if back_on > today:
        return ("A return cannot be recorded for a date that has not happened. "
                "Record it when the goods are back.")
    return None


def whole_challan_back_needs_a_day(reason: object) -> str:
    """What the whole-challan door says when it is asked to mark a challan received back and is given no day anywhere (POST-A-383).

    The status alone stops the s.143 clock (`itc_04.balances` skips a challan in it), so it would stop on a figure nobody can read back. For a JOB-WORK challan the sentence also names
    the other way to end the clock, lot by lot on FORM GST ITC-04, where the last lot stamps the challan; the lot door refuses every other reason, so a challan sent on approval is not
    offered a way it cannot follow.
    """
    base = "A challan is marked received back with the day the goods came back. Give the day"
    if str(reason) == REASON_JOB_WORK:
        return base + ", or record the returns lot by lot on FORM GST ITC-04: the last lot stamps it."
    return base + "."


def whole_challan_back_before_a_lot_problem(document_no: str, back_on: date, latest_returned_on: Optional[date]) -> Optional[str]:
    """The sentence for a whole-challan back day that is EARLIER than a lot of goods already recorded as RETURNED on FORM GST ITC-04, or None (POST-A-383).

    The day the whole challan came back is the day its LAST goods did, so it cannot be before any lot of goods returned against it; `latest_returned_on` is the latest of those (or None
    when none is recorded). A row that records only quantity lost or wasted is not goods returned and is not counted: whether scrap counts as received back for s.143 is not a judgement
    this product takes (migration 462). The other direction, a lot or the day they went out before the day the goods were sent, is `goods_back_problem`'s. Equal days are allowed. Pure: no
    clock, no store.
    """
    if latest_returned_on is not None and back_on < latest_returned_on:
        return (f"Challan {document_no} has goods recorded as returned on {latest_returned_on.isoformat()} on FORM GST ITC-04, so the day the whole challan came back "
                f"cannot be {back_on.isoformat()}, before that.")
    return None


def a_back_day_needs_a_status_that_says_so_problem(document_no: object, day: object, status: object) -> str:
    """The sentence for a challan that would carry the day its goods came back and a status that says they have not (POST-A-383): a challan with a back day IS received back."""
    return f"Challan {document_no} has its goods back on {day}, so it is received back and cannot be marked {status_word(status)}."


def not_issued_sentence(document_no: object, status: object) -> str:
    """What the doors that record goods coming back say of a challan that is not in the state goods can come back on (`issued`): the FORM GST ITC-04 lot door for a draft or a cancelled
    challan, and the whole-challan amendment door for a draft or a cancelled one. One sentence, so the doors cannot drift (POST-A-383, POST-A-398). The status is said in English
    ("a draft", "cancelled"), never as the stored word."""
    return (f"Challan {document_no} is {status_is(status)}: goods can only come back on a challan that has been issued.")


# ── The life of a challan: draft → issued → received back, or cancelled (POST-A-398) ────────────────────────────────────────────────────────
#
# A challan is made as a DRAFT. It is ISSUED, by one door, when the goods leave on it: that records that they left on the challan's date, so any period under the Act (s.143 for job work,
# s.31(7) for goods on approval) is run from that date, a job-work challan becomes a row of FORM GST ITC-04, and goods can come back on it (only on an issued challan). Issuing does NOT
# move the day a period counts from: the clock runs from the challan's date, which is why a draft dated in the past is shown what issuing it would mean before it is issued.
# It becomes RECEIVED BACK when the goods have come back (the whole challan's day, or the last lot), and it is CANCELLED if the goods never left or were never going to. Received back
# and cancelled are the ends.

STATUS_DRAFT = "draft"
STATUS_ISSUED = "issued"
STATUS_RECEIVED_BACK = "received_back"
STATUS_CANCELLED = "cancelled"

#: How a status is SAID to a person. The stored word `received_back` carries an underscore a sentence must not print, and a sentence reads "Challan X is a draft", not "is draft".
_STATUS_WORD = {
    STATUS_DRAFT: "draft",
    STATUS_ISSUED: "issued",
    STATUS_RECEIVED_BACK: "received back",
    STATUS_CANCELLED: "cancelled",
}


def status_word(status: object) -> str:
    """The word a person reads for a stored status ("received back" for `received_back`). A status this module does not hold is said as it is stored. Pure."""
    return _STATUS_WORD.get(str(status), str(status))


def status_is(status: object) -> str:
    """What follows "is" when a sentence says what state a challan is in: "a draft", "issued", "received back" or "cancelled". Pure."""
    word = status_word(status)
    return f"a {word}" if str(status) == STATUS_DRAFT else word


#: What a patch may turn a challan into, by the status it has, and the ONLY thing that decides it (`status_change_problem` explains a refusal). `issued` is not here for any: there is ONE door
#: that issues (`sales_cycle_service.issue_challan`), so what issuing demands is asked in one place, and `received_back` is reached only from `issued`.
AMENDMENT_MAY_MAKE = {
    STATUS_DRAFT: (STATUS_CANCELLED,),
    STATUS_ISSUED: (STATUS_RECEIVED_BACK, STATUS_CANCELLED),
    STATUS_RECEIVED_BACK: (),
    STATUS_CANCELLED: (),
}

#: The statuses a challan is in once the goods have left on it, and so the only ones in which a period is run, a job-work challan is a row of FORM GST ITC-04, and goods can come back. A draft
#: is not recorded as issued; a cancelled challan is not a movement.
GOODS_HAVE_LEFT = (STATUS_ISSUED, STATUS_RECEIVED_BACK)

#: The statuses a challan's period runs in.
STATUSES_WITH_A_CLOCK = GOODS_HAVE_LEFT

#: The statuses in which a challan's goods are DELIVERED against the order it names (POST-A-421): they left and they are still with the consignee. A challan marked `received_back` delivered
#: nothing, so the order shows those goods as undelivered again and a new delivery of them is not refused as more than was ordered. That is the WHOLE challan: goods returned in part on a lot of
#: FORM GST ITC-04 leave it `issued` until the last lot brings every line back, and they count as delivered until then. It is deliberately a subset of
#: `GOODS_HAVE_LEFT`, which is the set in which a period runs and FORM GST ITC-04 lists a job-work challan; and a challan that came back still HANGS from its order line (the order's lines are not
#: re-priced or removed from under it), which `order_open_position(with_drafts=True)` asks.
STATUSES_THAT_DELIVER_AGAINST_AN_ORDER = (STATUS_ISSUED,)


def status_change_problem(document_no: object, current: object, wanted: object) -> Optional[str]:
    """The sentence for a status an amendment cannot give this challan, or None (POST-A-398). The same status again is not a change. Pure.

    `AMENDMENT_MAY_MAKE` is what decides. `issued` has its own door and is never given by an amendment (so a hand-made request cannot record the goods as left or list a challan on FORM GST
    ITC-04 without what issuing asks); a challan is not sent back to a draft; goods come back only on an issued challan (`not_issued_sentence`); and a challan whose goods are back, or that is
    cancelled, is at its end. The sentences below say WHY a status is not allowed; they are reached only for a status the table does not allow."""
    cur, want = str(current), str(wanted)
    if want == cur or want in AMENDMENT_MAY_MAKE.get(cur, ()):
        return None
    # the ends first: nothing is made of a challan whose goods are back or that is cancelled
    if cur == STATUS_RECEIVED_BACK:
        return f"Challan {document_no} is received back: its goods are back, so it cannot become {status_is(want)}."
    if cur == STATUS_CANCELLED:
        return f"Challan {document_no} is cancelled: it cannot become {status_is(want)}."
    if want == STATUS_ISSUED:                               # from a draft: the issue door is the one that issues
        return f"Challan {document_no} is not made issued by an amendment: Issue challan is the one step that records that the goods left, and it asks what a challan must hold when they do."
    if want == STATUS_DRAFT:
        return f"Challan {document_no} is {status_is(cur)}: a challan is not made a draft again."
    if want == STATUS_RECEIVED_BACK and cur != STATUS_ISSUED:
        return not_issued_sentence(document_no, cur)
    return f"Challan {document_no} is {status_is(cur)}: it cannot become {status_is(want)}."


def cancel_after_goods_came_back_sentence(document_no: object, recorded_on: object) -> str:
    """A challan with a lot already recorded against it on FORM GST ITC-04 is not cancelled (POST-A-398): the lots hang from it, and a cancelled challan has no goods out to come back. A lot is
    goods returned OR goods lost or wasted: a lot of waste alone is a lot too (the balance of a cancelled challan is not listed, and the waste is never subtracted from it)."""
    return (f"Challan {document_no} has a lot recorded against it on {recorded_on} on FORM GST ITC-04 (goods returned, or lost or wasted), so it cannot be cancelled. "
            "Cancel a challan whose goods did not leave; one whose goods are coming back is finished by recording the rest.")


def issued_challan_problem(document_no: object, *, row: dict, touched) -> Optional[str]:
    """The sentence for an amendment that would leave a challan the goods have left on (issued, or received back) without something issuing asked for, or None (POST-A-398). Pure. `row` is the
    challan AS THE PATCH WOULD LEAVE IT and `touched` the names of the fields the patch gives.

    Issuing asked that a job-work challan said what it sends and that an inter-State movement had a place of supply. The other particulars issuing asked for (the date, the consignee) cannot be
    changed after issue at all (`issued_challan_is_not_rewritten_problem`, POST-A-416), so they are not asked again here. Each question is asked of the row the patch would leave, and ONLY for
    the fields it touches: a row stored before this rule is not made unsaveable by an edit of something else. (What was amended is the audit event's.) The sentences say "has been issued", which
    is true of a received-back challan too."""
    if "place_of_supply" in touched:
        if row.get("is_inter_state") and not str(row.get("place_of_supply") or "").strip():
            return f"Challan {document_no} has been issued as an inter-State movement, so it keeps a place of supply: Rule 55(1)(viii) asks for one."
    if "goods_kind" in touched:
        if str(row.get("reason")) == REASON_JOB_WORK and not str(row.get("goods_kind") or "").strip():
            return f"Challan {document_no} is for job work and has been issued, so it keeps what is sent: the period under s.143 depends on it."
    return None


#: What a challan keeps once it has been issued or cancelled (POST-A-416): its number, the day it was made, who it was made out to and whether it was an inter-State movement. They are what the
#: document IS (the number is how it is found, the date is the day the goods are counted from, the consignee is who received them), so correcting one is a cancellation and a new challan and
#: not an edit. A cancelled challan keeps them as well: nothing records whether its goods ever left (there is no issued-at, POST-A-419(c)), and a cancel followed by a rewrite would otherwise
#: hide what was cancelled. A job-work challan's place of supply is NOT among them while the goods are out: it is the job worker's State, which FORM GST ITC-04 reads and which is recorded after
#: the goods have gone (`JobWorkerStateBox`). The rest of what the amendment door takes (the transport details, the notes, the extension under s.143(1), the kind of goods, the invoice a challan is
#: tied to, the day the goods came back) is left open on purpose: the screens write only the back day and the job worker's State after issue, and the others are the API's.
CLOSED_AFTER_ISSUE = ("document_no", "document_date", "consignee_name", "consignee_gstin", "consignee_address", "is_inter_state")
CLOSED_AFTER_ISSUE_EXCEPT_JOB_WORK = ("place_of_supply",)
#: The statuses of a challan that is not a draft: the goods have left on it, or it was cancelled.
KEEPS_ITS_PARTICULARS = (STATUS_ISSUED, STATUS_RECEIVED_BACK, STATUS_CANCELLED)


def touches_what_an_issued_challan_keeps(patch: dict) -> bool:
    """True when an amendment gives any field the rule below closes, so the write can be held to the status that was judged (POST-A-416)."""
    return bool(set(patch) & {*CLOSED_AFTER_ISSUE, *CLOSED_AFTER_ISSUE_EXCEPT_JOB_WORK})


def _same(name: str, stored: object, wanted: object) -> bool:
    """A field given the value it already holds is not a change (a client that sends the whole form back is not refused): text is compared trimmed, a day as its first ten characters, a GSTIN
    in capitals, a flag as a flag."""
    if isinstance(stored, bool) or isinstance(wanted, bool):
        return bool(stored) == bool(wanted)
    a, b = (str(v if v is not None else "").strip() for v in (stored, wanted))
    if name == "document_date":
        return a[:10] == b[:10]
    if name == "consignee_gstin":
        return a.upper() == b.upper()
    return a == b


def _what_to_do_instead(status: object) -> str:
    if str(status) == STATUS_ISSUED:
        return "Cancel it if its goods did not leave, and make a new challan; the day the goods came back can still be recorded."
    if str(status) == STATUS_RECEIVED_BACK:
        return "Its goods are back, so it stays as it was issued."
    return "It is cancelled, so it stays as it was; make a new challan."


def issued_challan_is_not_rewritten_problem(document_no: object, *, row: dict, patch: dict) -> Optional[str]:
    """The sentence for an amendment that would CHANGE what a challan that has been issued, or cancelled, says of itself, or None (POST-A-416). Pure. `row` is the challan as stored and `patch` the
    fields the amendment gives (a field it does not give is not in it).

    It judges a challan that is issued, received back or cancelled (`KEEPS_ITS_PARTICULARS`) and only a CHANGE: a field given the value it already holds, or given where the challan holds nothing yet
    (a consignee's GSTIN found later, a place of supply on a challan that was not an inter-State movement), completes the document and contradicts nothing that was issued. A draft is
    corrected freely. The sentence names every field it refuses and says what to do instead for the status the challan is in."""
    status = row.get("status")
    if str(status) not in KEEPS_ITS_PARTICULARS:
        return None
    closed = list(CLOSED_AFTER_ISSUE)
    if str(row.get("reason")) != REASON_JOB_WORK or str(status) == STATUS_CANCELLED:
        closed += list(CLOSED_AFTER_ISSUE_EXCEPT_JOB_WORK)
    changed = []
    for name in closed:
        if name not in patch or _same(name, row.get(name), patch[name]):
            continue
        if name not in ("document_no", "document_date", "is_inter_state") and not str(row.get(name) or "").strip():
            continue                                        # filling in what the challan did not say completes it
        changed.append(name)
    if not changed:
        return None
    words = [FIELD_WORDS.get(n, n) for n in changed]
    names = words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]
    was = "is cancelled" if str(status) == STATUS_CANCELLED else "has been issued"
    return f"Challan {document_no} {was}, so its {names} cannot be changed: it stays as it was made. {_what_to_do_instead(status)}"


#: The words a person reads for a closed field.
FIELD_WORDS = {
    "document_no": "number", "document_date": "date", "consignee_name": "consignee's name", "consignee_gstin": "consignee's GSTIN",
    "consignee_address": "consignee's address", "is_inter_state": "inter-State flag", "place_of_supply": "place of supply",
}


def only_a_draft_is_issued_sentence(document_no: object, status: object) -> str:
    """What the issue door says of a challan that is not a draft (POST-A-398): it was issued already, it is at its end, or it was cancelled."""
    return f"Challan {document_no} is {status_is(status)}: only a draft is issued."


def an_empty_challan_is_not_issued_sentence(document_no: object) -> str:
    """A challan with no goods on it is not a document that goods can leave on (POST-A-398)."""
    return f"Challan {document_no} has no lines, so there are no goods to send on it."


#: What a correction to a DRAFT's lines may change (POST-A-417): the words and the HSN code. Quantity, unit, rate and tax are what the header's totals and an order's delivered quantity are made
#: from, so changing one is a new challan, not a correction.
DRAFT_LINE_FIELDS = ("description", "hsn_sac")


#: Lines are corrected in a request of their own (POST-A-417): a status given beside them would cancel the challan and then write the lines onto it.
LINES_ARE_CORRECTED_ALONE = "A draft's lines are corrected in a request of their own: give no status beside them. Cancel the challan, or correct its lines, not both at once."


def draft_line_corrections_problem(document_no: object, status: object, fixes: object, line_ids: object) -> Optional[str]:
    """The sentence for a correction to a challan's lines that cannot be made, or None (POST-A-417). Pure. `fixes` is what the amendment gave as `lines`, `line_ids` the ids of the challan's own lines IN THE ORDER THE
    SCREEN SHOWS THEM, so a sentence can say "line 2" and not an id the person never sees.

    ONLY A DRAFT'S LINES ARE CORRECTED, AND ONLY THEIR WORDS AND THEIR HSN CODE. Once the goods have left, the lines are the issued document's. Rule 55(1)(iv) asks for the HSN code of the goods, and a draft made
    without one could not be issued and had no way to be mended, so the person made the challan again under a new number while the draft kept its own. Anything else a line carries is refused in a sentence and
    never dropped: the amendment door used to drop `lines` whole and report a success. The words are text and the HSN code is text or nothing (a number or an object is not stored as its spelling). A blank HSN is
    allowed (it clears the box and the challan then lists it as still to be recorded); a code that is not digits is not (`hsn_digits.is_a_code`: the module's own test, which says nothing about how long a code must
    be, because that is a notification's question and not this door's)."""
    if str(status) != STATUS_DRAFT:
        return (f"Challan {document_no} is {status_is(status)}: only a draft's lines are corrected. Once the goods have left, the lines are the issued document's.")
    if not isinstance(fixes, list) or not fixes or not all(isinstance(f, dict) for f in fixes):
        return "Lines are corrected as a list, each naming the line it corrects by its id and giving its description, its HSN code or both."
    order = [str(i) for i in (line_ids or ())]
    seen: set = set()
    for fx in fixes:
        line_id = str(fx.get("id") or "").strip()
        if not line_id:
            return "A line correction must name the line it corrects by its id."
        if line_id not in order:
            return f"{line_id} is not a line of challan {document_no}."
        n = order.index(line_id) + 1
        if line_id in seen:
            return f"Line {n} is corrected twice in one request: give each line once."
        seen.add(line_id)
        other = sorted(k for k in fx if k != "id" and k not in DRAFT_LINE_FIELDS)
        if other:
            return (f"A draft's lines are corrected in their description and HSN code only ({', '.join(other)} cannot be changed here): the quantity, unit, rate and tax are what the challan's totals are made from, "
                    "so a challan with different ones is made again.")
        if not any(k in fx for k in DRAFT_LINE_FIELDS):
            return f"Line {n} gives nothing to change: give its description, its HSN code or both."
        if "description" in fx:
            if not isinstance(fx["description"], str):
                return f"The description of line {n} is text."
            if not fx["description"].strip():
                return f"Line {n} keeps a description: a challan line says what the goods are."
        if "hsn_sac" in fx:
            if fx["hsn_sac"] is not None and not isinstance(fx["hsn_sac"], str):
                return f"The HSN code of line {n} is text of digits."
            code = str(fx["hsn_sac"] or "").strip()
            if code and not hsn_digits.is_a_code(code):
                return f"HSN '{code}' on line {n} is not a code: an HSN or SAC is digits only."
    return None


def draft_line_changes(fix: dict) -> dict:
    """The columns one accepted line correction writes: the description trimmed, the HSN code trimmed and None where it was cleared (POST-A-417). Pure; the correction has been judged."""
    changes: dict = {}
    if "description" in fix:
        changes["description"] = str(fix["description"]).strip()
    if "hsn_sac" in fix:
        changes["hsn_sac"] = str(fix["hsn_sac"] or "").strip() or None
    return changes


def issue_needs_the_particulars_sentence(document_no: object, missing: list) -> str:
    """What the issue door says when Rule 55(1) asks for a particular the challan does not hold (POST-A-398): the clauses, in clause order, as `missing_particulars` names them."""
    return f"Challan {document_no} cannot be issued yet: Rule 55(1) asks for " + "; ".join(str(m) for m in missing) + "."


def issue_needs_the_kind_of_goods_sentence(document_no: object) -> str:
    """A job-work challan is not issued without saying what is sent (POST-A-398): the period differs by a factor of three between inputs and capital goods, and is none for moulds, dies, jigs,
    fixtures and tools, so a challan issued without the answer would run no clock (`deemed_supply_clock` names the gap) while FORM GST ITC-04 lists it."""
    return (f"Challan {document_no} is for job work and does not say what is sent (inputs, capital goods, or moulds, dies, jigs, fixtures or tools). "
            "The period under s.143 depends on the answer, so it cannot be issued without it.")


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


#: What a draft's clock says before it says what issuing would mean (POST-A-398). A statement about the PRODUCT's record, never about the goods: whether they have left is not known here.
DRAFT_RUNS_NO_PERIOD = "This challan is a draft: it is not recorded as issued, so no period is running on it here."

#: The gap a challan carries when its status says the goods are back and no day is recorded for it (a row written before POST-A-383 refused that). Named, not guessed.
RECEIVED_BACK_WITHOUT_A_DAY = ("This challan is recorded as received back with no day, so whether the goods came back within the period cannot be said. "
                               "Record the day they came back.")


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


def _clock_of_a_challan_the_goods_are_not_recorded_as_leaving_on(*, reason: str, challan_date: Optional[str], as_at: str, goods_kind: Optional[str],
                                                                  extended_to: Optional[str], status: Optional[str]) -> Optional[Clock]:
    """The clock of a job-work or on-approval challan that is a draft or cancelled, or None for any other (POST-A-398). A draft says what issuing it would mean (the period it would run is worked out
    as for an issued challan, and shown as a sentence, never as a running period); a cancelled challan is not a movement and says nothing of the goods."""
    if status is None or str(status) in STATUSES_WITH_A_CLOCK or reason not in (REASON_JOB_WORK, REASON_ON_APPROVAL):
        return None
    out = Clock()
    if str(status) == STATUS_DRAFT:
        would = deemed_supply_clock(reason=reason, challan_date=challan_date, as_at=as_at, goods_kind=goods_kind, extended_to=extended_to)
        out.consequence = DRAFT_RUNS_NO_PERIOD
        if would.applies and would.sent_on and would.due_back_by:
            out.consequence += (f" If the goods left on the challan's date, {would.sent_on}, the period under {would.statute} would end on {would.due_back_by}"
                                + (", which is already past." if would.overdue else "."))
    else:
        out.consequence = "This challan is cancelled, so no period is run on it here."
    return out


def deemed_supply_clock(*, reason: str, challan_date: Optional[str],
                        as_at: str, goods_kind: Optional[str] = None,
                        received_back_on: Optional[str] = None,
                        extended_to: Optional[str] = None,
                        status: Optional[str] = None) -> Clock:
    """When this movement becomes a supply if the goods do not come back.

    THE CLOCK RUNS FROM THE DATE THE GOODS WERE SENT OUT, which is the challan
    date, and s.143(3) deems the supply to have been made ON THAT SAME DAY —
    not on the day the period expired. So the tax falls due in a return that
    has been filed, with s.50(1) interest from its own due date, and the
    difference between the two readings is a year of interest.

    A PERIOD IS RUN ON A CHALLAN THAT IS RECORDED AS HAVING LEFT, AND ON NO OTHER (POST-A-398). `status` is the challan's. A DRAFT is not recorded as issued, and the product cannot know that
    the goods have not left: it runs no period on a draft, and SAYS WHAT ISSUING IT WOULD MEAN instead (that, if the goods left on the challan's own date, the period would end on a day it names, and
    whether that day is already past), because issuing does not move the day a period counts from and a draft dated long ago is one click from a period already over. A CANCELLED challan is not a
    movement, so none is run and nothing is said of the goods. A challan whose status says the goods are BACK and which records no day cannot be judged either way: it is neither overdue nor
    clear, and the gap says what to record. A caller that does not know the status passes none and gets the answer it always got.
    """
    out = Clock()
    stood_down = _clock_of_a_challan_the_goods_are_not_recorded_as_leaving_on(
        reason=reason, challan_date=challan_date, as_at=as_at, goods_kind=goods_kind, extended_to=extended_to, status=status)
    if stood_down is not None:
        return stood_down
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

    if status is not None and str(status) == STATUS_RECEIVED_BACK:
        # The status says the goods are back and no day is recorded (a row from before POST-A-383 asked for one): when they came back is unknown, so whether it was within the period is too.
        out.gaps.append(RECEIVED_BACK_WITHOUT_A_DAY)
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
