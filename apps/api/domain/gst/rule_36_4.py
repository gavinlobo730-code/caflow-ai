"""§16(2)(aa) is asked PER DOCUMENT, and Rule 36(4) was applied in aggregate
(GST-19).

WHAT WAS WRONG

    `gstr3b_computer._apply_rule_36_4_cap` compares per-head SUMS: book IGST
    against 2B IGST, and trims one to the other. CGST §16(2)(aa) does not read
    that way. It allows the credit only where "the details of the invoice or
    debit note ... have been furnished by the supplier ... and such details
    have been communicated to the recipient of such invoice" — a condition on
    EACH DOCUMENT.

    So a month with one ₹18,000 bill the supplier never filed and another
    where 2B happens to carry ₹18,000 MORE than the books nets to zero, the
    cap never fires, and the return claims credit on an invoice nobody
    furnished. And when the cap DOES fire the CA is told one sentence —
    "credit was trimmed to the GSTR-2B figure" — with no list of which
    documents were disallowed, so they cross-reference the reconciliation tab
    by hand.

    The per-document answer was already computed and stored. The 2B
    reconciliation (migration 340) writes `purchase_bill_id`, `match_status`,
    `itc_available` and `itc_unavailable_reason_code` on every row it matches;
    nothing read them into the return.

WHAT THIS MODULE IS AND IS NOT

    It is the RULE. It decides, for one document, whether the credit is
    available this period and what to say when it is not. It matches nothing —
    `domain/gst/itc_matching.py` did that and this reads its answer, because a
    second matcher would disagree with the reconciliation the CA is looking at.

    It is deliberately NOT a rate, a threshold or a percentage. Rule 36(4)'s
    provisional buffer (20%, then 10%, then 5%) was withdrawn by Notification
    40/2021-Central Tax with effect from 1 January 2022, when §16(2)(aa) came
    in: there is no grace, and the question stopped being "how much more than
    2B" and became "which documents are in it".

THE FIVE ANSWERS, AND WHY NONE OF THEM COLLAPSES INTO ANOTHER

  * `allowed`               2B carries this document and says the credit is
                            available. The whole book figure stands.
  * `self_assessed`         Reverse charge. §16(2)(aa) is a condition on a
                            SUPPLIER's furnished invoice, and this tax was
                            self-assessed by the recipient and paid in cash —
                            2B structurally cannot carry it, so withholding it
                            takes back credit on tax already paid. Allowed in
                            full and NAMED, never silently allowed.
  * `not_in_2b`             The books hold it and no 2B document matched.
                            WITHHELD — and the CA's action is to chase the
                            SUPPLIER.
  * `blocked_by_2b`         Matched, and 2B's own `itcavl` says N. The portal
                            has already refused it: `rsn` "P" is the place of
                            supply, "C" a return furnished after §16(4)'s
                            cut-off. WITHHELD, and the CA's action is NOT to
                            chase anybody — it is to check the document.
                            Reading this as `not_in_2b` would send them to
                            phone a supplier who has done nothing wrong.
  * `more_than_2b`          Matched, and the books carry more tax under a head
                            than 2B communicated. Allowed TO THE 2B FIGURE and
                            the excess withheld, per head — which is the
                            aggregate cap's own arithmetic, applied where the
                            section actually applies it.
  * `not_assessed`          The bill was RECORDED AFTER the reconciliation for
                            its own period ran, so that reconciliation never
                            looked at it and its silence says nothing. Allowed
                            in full and NAMED, with the action to re-run the
                            reconciliation — see below, because this is the
                            answer that keeps the rest of them honest.

WHY A DOCUMENT NOBODY LOOKED AT IS NOT A DOCUMENT NOBODY FILED

    `gstr2a_records.purchase_bill_id` is written ONCE, when the CA uploads the
    period's GSTR-2B, by matching the file against the bills that existed AT
    THAT MOMENT (`gst_2b_reconciliation_service.read_book_bills`, which reads
    exactly that period's bills). It is a point-in-time artefact, and the
    return is built later.

    So a bill entered on the 20th, after the month's 2B was reconciled on the
    14th, carries no keyed row — and it is indistinguishable, by the map alone,
    from a bill the supplier never filed. Reading it as `not_in_2b` would
    withhold credit the client is entitled to, on a return they are about to
    file, with nothing on the screen to say why; and unlike every other verdict
    here, the CA cannot check it by phoning anybody, because the supplier HAS
    filed and the 2B DOES carry the document.

    The direction of the error is what decides this. Withholding wrongly costs
    the client real money and is invisible; allowing wrongly leaves the
    aggregate cap doing what it did before, with a sentence telling the CA to
    re-reconcile. So an unexamined document is allowed and named.

    The test is the bill's `created_at` against its period's own
    `reconciled_at`, and `created_at` DELIBERATELY rather than `updated_at`: a
    payment allocation, a TDS correction and a status change all move
    `updated_at` without touching anything §16(2)(aa) matches on, so using it
    would report most of a busy client's register as unexamined and make the
    whole pass inert. What `created_at` misses — a bill whose NUMBER or AMOUNT
    was edited after the reconciliation — fails in the safe direction: the
    stored row still keys to the bill's id, so it reads as matched, and the
    per-head `min(book, filed)` still catches an amount that grew.

WHAT IT REFUSES TO DECIDE

  * **An import of goods keeps the aggregate treatment.** 2B carries it in
    `impg` and it is not a purchase bill, so it has no `purchase_bill_id` to
    key on — the reconciliation's own row for it carries none either. It is
    NAMED as outside the per-document pass rather than quietly allowed, and
    the aggregate cap still reaches it.
  * **A document with no 2B AT ALL for the period is not withheld.** Where no
    reconciliation has been run there is nothing to compare against, and
    withholding every credit because nobody uploaded a file would refuse a
    return the client is entitled to file. `assess` says so on the answer.
  * **Nothing here decides §17(5).** Blocked credit is a per-line fact the
    bill already carries and is subtracted before a document reaches this
    module — a document whose whole tax is blocked has nothing left to
    withhold and is not reported twice.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

#: Withdrawn by Notification 40/2021-Central Tax w.e.f. 01-01-2022, when
#: §16(2)(aa) came into force. Recorded rather than implemented, because a
#: percentage here is exactly the thing that made the old cap aggregate: with
#: a buffer there is a total to compare, without one there is only a list of
#: documents.
PROVISIONAL_BUFFER_WITHDRAWN_FROM = "2022-01-01"

#: A document this pass cannot reach. Named on the answer.
IMPORT_IS_OUTSIDE_THE_PER_DOCUMENT_PASS = (
    "An import of goods is communicated in GSTR-2B's own `impg` section "
    "against a bill of entry, not a supplier's invoice, so it carries no "
    "purchase bill to match on. Its credit is compared in aggregate as "
    "before; nothing here withholds it."
)

NO_2B_ON_FILE = (
    "No GSTR-2B has been reconciled for this period, so no document could be "
    "checked against one. §16(2)(aa) is not applied here and the figures "
    "below are the books' own — upload the period's GSTR-2B and reconcile to "
    "see which documents the portal actually carries."
)

#: GSTR-2B's own `rsn` codes, spelled out. A code alone on a screen is not an
#: answer a CA can act on, and these two are what the portal emits.
ITC_UNAVAILABLE_REASONS = {
    "P": ("the place of supply and the supplier's State are the same while "
          "the recipient is in another State (CGST §16(2)(aa) with IGST §12)"),
    "C": ("the supplier furnished the return after the §16(4) cut-off for "
          "this credit"),
}

#: The five verdicts. Named rather than booleans because the CA's ACTION
#: differs per verdict, which is the whole reason they are not one flag.
ALLOWED = "allowed"
SELF_ASSESSED = "self_assessed"
NOT_IN_2B = "not_in_2b"
BLOCKED_BY_2B = "blocked_by_2b"
MORE_THAN_2B = "more_than_2b"
NOT_ASSESSED = "not_assessed"

_WITHHOLDING = (NOT_IN_2B, BLOCKED_BY_2B, MORE_THAN_2B)

NOT_ASSESSED_REASON = (
    "This bill was recorded after the GSTR-2B for its period was reconciled, "
    "so that reconciliation never examined it and its silence is not evidence "
    "the supplier failed to file. The credit is not withheld here — re-run the "
    "GSTR-2B reconciliation for this period to have §16(2)(aa) asked of it.")


@dataclass(frozen=True)
class BookDocument:
    """One inward document as the books hold it, net of §17(5).

    `document_id` is the `purchase_bills.id` the 2B reconciliation keys its
    match on. None means this document cannot be matched at all — a bank
    charge carrying GST (BANK-24), a note this product issued, an import —
    and such a document is passed through untouched and named.
    """
    document_id: Optional[str]
    label: str
    supplier: str
    igst_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    cess_paise: int = 0
    is_reverse_charge: bool = False
    #: Did the reconciliation this map came from actually LOOK at this bill?
    #: DEFAULTS TO TRUE, which is the withholding direction, because a caller
    #: that has built a 2B map at all has established the period was
    #: reconciled; it is the SERVICE that knows the bill was recorded after it,
    #: and `services/gst_return_service._documents_the_recon_never_saw`
    #: supplies the exception. A caller that cannot establish it gets today's
    #: answer rather than a silently inert pass.
    was_examined: bool = True


@dataclass(frozen=True)
class TwoBDocument:
    """What the reconciliation recorded about this bill's 2B counterpart."""
    matched: bool
    itc_available: str = ""
    reason_code: str = ""
    igst_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    cess_paise: int = 0


@dataclass
class DocumentVerdict:
    document_id: Optional[str]
    label: str
    supplier: str
    verdict: str
    reason: str
    allowed_igst_paise: int = 0
    allowed_cgst_paise: int = 0
    allowed_sgst_paise: int = 0
    allowed_cess_paise: int = 0
    withheld_igst_paise: int = 0
    withheld_cgst_paise: int = 0
    withheld_sgst_paise: int = 0
    withheld_cess_paise: int = 0

    @property
    def withheld_total_paise(self) -> int:
        return (self.withheld_igst_paise + self.withheld_cgst_paise
                + self.withheld_sgst_paise + self.withheld_cess_paise)

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "label": self.label,
            "supplier": self.supplier,
            "verdict": self.verdict,
            "reason": self.reason,
            "allowed_igst_paise": self.allowed_igst_paise,
            "allowed_cgst_paise": self.allowed_cgst_paise,
            "allowed_sgst_paise": self.allowed_sgst_paise,
            "allowed_cess_paise": self.allowed_cess_paise,
            "withheld_igst_paise": self.withheld_igst_paise,
            "withheld_cgst_paise": self.withheld_cgst_paise,
            "withheld_sgst_paise": self.withheld_sgst_paise,
            "withheld_cess_paise": self.withheld_cess_paise,
            "withheld_total_paise": self.withheld_total_paise,
        }


@dataclass
class Rule364Assessment:
    """Every document's verdict, the heads that survive, and what was held."""
    applied: bool = False
    verdicts: list = field(default_factory=list)
    allowed_igst_paise: int = 0
    allowed_cgst_paise: int = 0
    allowed_sgst_paise: int = 0
    allowed_cess_paise: int = 0
    withheld_igst_paise: int = 0
    withheld_cgst_paise: int = 0
    withheld_sgst_paise: int = 0
    withheld_cess_paise: int = 0
    notes: list = field(default_factory=list)

    @property
    def withheld(self) -> list:
        """The documents a CA has to do something about, largest first."""
        return sorted(
            (v for v in self.verdicts if v.verdict in _WITHHOLDING),
            key=lambda v: -v.withheld_total_paise)

    @property
    def not_assessed(self) -> list:
        """Documents the reconciliation never looked at. Allowed, and named.

        Kept apart from `withheld` because the CA's action is opposite: these
        are not a supplier's failure and not a document to check, they are a
        reconciliation to re-run. Folding them into the withheld list would
        show credit as held back that this pass has just allowed.
        """
        return [v for v in self.verdicts if v.verdict == NOT_ASSESSED]

    @property
    def withheld_total_paise(self) -> int:
        return (self.withheld_igst_paise + self.withheld_cgst_paise
                + self.withheld_sgst_paise + self.withheld_cess_paise)

    def to_dict(self) -> dict:
        return {
            "applied": self.applied,
            "allowed_igst_paise": self.allowed_igst_paise,
            "allowed_cgst_paise": self.allowed_cgst_paise,
            "allowed_sgst_paise": self.allowed_sgst_paise,
            "allowed_cess_paise": self.allowed_cess_paise,
            "withheld_igst_paise": self.withheld_igst_paise,
            "withheld_cgst_paise": self.withheld_cgst_paise,
            "withheld_sgst_paise": self.withheld_sgst_paise,
            "withheld_cess_paise": self.withheld_cess_paise,
            "withheld_total_paise": self.withheld_total_paise,
            # ONLY the withheld documents travel. A month's whole purchase
            # register on a return payload is a read proportional to
            # transaction volume for an answer that is a handful of rows —
            # and the allowed ones are already the figures in Table 4(A).
            "withheld": [v.to_dict() for v in self.withheld],
            # The same reasoning: only the rows a CA has to act on travel.
            "not_assessed": [v.to_dict() for v in self.not_assessed],
            "notes": list(self.notes),
        }


def _reason_for_block(code: str) -> str:
    spelled = ITC_UNAVAILABLE_REASONS.get((code or "").strip().upper())
    if spelled:
        return (f"GSTR-2B marks this document ITC-unavailable (reason "
                f"{code.strip().upper()}): {spelled}.")
    # A code the portal emits and this module does not hold is REPORTED as
    # itself rather than translated into one of the two above — guessing which
    # it meant would tell a CA to fix the wrong thing.
    if (code or "").strip():
        return (f"GSTR-2B marks this document ITC-unavailable with reason "
                f"code {code.strip()}, which is not one this product spells "
                f"out. Read it on the portal before claiming the credit.")
    return ("GSTR-2B marks this document ITC-unavailable and gives no reason "
            "code.")


def assess(documents, two_b_by_document: Optional[dict],
           have_2b: bool) -> Rule364Assessment:
    """§16(2)(aa) per document, with the heads that survive it.

    `two_b_by_document` is `{purchase_bill_id: TwoBDocument}` from the
    reconciliation. `None` — or `have_2b` false — means no 2B was reconciled
    for the period, and NOTHING is withheld: the answer says so and the caller
    keeps whatever it did before.

    A document with no `document_id` is passed through allowed and named. It is
    not a hole in the rule: a bank charge carrying GST has no supplier document
    to furnish (BANK-24 says so on its own answer), a note this product issued
    adjusts a bill already assessed, and an import is `impg`.
    """
    out = Rule364Assessment()
    if not have_2b or two_b_by_document is None:
        out.notes.append(NO_2B_ON_FILE)
        for d in documents:
            out.allowed_igst_paise += d.igst_paise
            out.allowed_cgst_paise += d.cgst_paise
            out.allowed_sgst_paise += d.sgst_paise
            out.allowed_cess_paise += d.cess_paise
        return out

    out.applied = True
    unkeyed = 0
    for d in documents:
        verdict = _assess_one(d, two_b_by_document.get(d.document_id or ""))
        if d.document_id is None and not d.is_reverse_charge:
            unkeyed += 1
        out.verdicts.append(verdict)
        out.allowed_igst_paise += verdict.allowed_igst_paise
        out.allowed_cgst_paise += verdict.allowed_cgst_paise
        out.allowed_sgst_paise += verdict.allowed_sgst_paise
        out.allowed_cess_paise += verdict.allowed_cess_paise
        out.withheld_igst_paise += verdict.withheld_igst_paise
        out.withheld_cgst_paise += verdict.withheld_cgst_paise
        out.withheld_sgst_paise += verdict.withheld_sgst_paise
        out.withheld_cess_paise += verdict.withheld_cess_paise
    unexamined = len(out.not_assessed)
    if unexamined:
        out.notes.append(
            f"{unexamined} bill(s) were recorded after the GSTR-2B for their "
            f"period was reconciled, so §16(2)(aa) has not been asked of them "
            f"and their credit stands. Re-run the GSTR-2B reconciliation for "
            f"this period to include them.")
    if unkeyed:
        out.notes.append(
            f"{unkeyed} document(s) carry no purchase bill to match a GSTR-2B "
            f"row against — a bank charge marked as carrying GST, or an "
            f"import of goods, which 2B communicates in its own `impg` "
            f"section. Their credit is not withheld here.")
    return out


def _assess_one(d: BookDocument, two_b: Optional[TwoBDocument]) -> DocumentVerdict:
    allow = DocumentVerdict(
        document_id=d.document_id, label=d.label, supplier=d.supplier,
        verdict=ALLOWED, reason="",
        allowed_igst_paise=d.igst_paise, allowed_cgst_paise=d.cgst_paise,
        allowed_sgst_paise=d.sgst_paise, allowed_cess_paise=d.cess_paise)

    # REVERSE CHARGE IS ASKED FIRST, and before the key, because a §9(3)/(4)
    # supply from an unregistered supplier has no 2B row by construction and
    # falling through would withhold credit on tax the client paid in cash.
    if d.is_reverse_charge:
        allow.verdict = SELF_ASSESSED
        allow.reason = (
            "Reverse charge. §16(2)(aa) conditions the credit on a SUPPLIER's "
            "furnished invoice; this tax is self-assessed by the recipient and "
            "discharged in cash under §49(4) with §2(82), so GSTR-2B cannot "
            "carry it and Rule 36(4) does not reach it.")
        return allow

    # NO CREDIT LEFT TO AVAIL, so the section has nothing to say about it.
    # §16(2)(aa) conditions the AVAILABILITY of input tax credit, and a bill
    # whose whole tax §17(5) blocks carries none — it was subtracted before the
    # document reached here. Without this branch such a bill reads as
    # `not_in_2b` and appears in the CA's "documents withheld" list with ₹0
    # against it: a row they can do nothing about, on the one screen whose
    # value is that every row needs an action.
    if not (d.igst_paise or d.cgst_paise or d.sgst_paise or d.cess_paise):
        return allow

    # A document with no bill to key on. Named by the caller in one sentence
    # rather than once per row.
    if not d.document_id:
        return allow

    # ASKED BEFORE THE MAP, because the map cannot tell "the supplier did not
    # file this" from "the reconciliation ran before this bill existed".
    if not d.was_examined:
        allow.verdict = NOT_ASSESSED
        allow.reason = NOT_ASSESSED_REASON
        return allow

    if two_b is None or not two_b.matched:
        return DocumentVerdict(
            document_id=d.document_id, label=d.label, supplier=d.supplier,
            verdict=NOT_IN_2B,
            reason=("No GSTR-2B document matched this bill, so the supplier "
                    "has not furnished it under §37 or it was not communicated "
                    "for this period. §16(2)(aa) withholds the credit until "
                    "they do."),
            withheld_igst_paise=d.igst_paise, withheld_cgst_paise=d.cgst_paise,
            withheld_sgst_paise=d.sgst_paise, withheld_cess_paise=d.cess_paise)

    if (two_b.itc_available or "").strip().upper() == "N":
        return DocumentVerdict(
            document_id=d.document_id, label=d.label, supplier=d.supplier,
            verdict=BLOCKED_BY_2B,
            reason=_reason_for_block(two_b.reason_code),
            withheld_igst_paise=d.igst_paise, withheld_cgst_paise=d.cgst_paise,
            withheld_sgst_paise=d.sgst_paise, withheld_cess_paise=d.cess_paise)

    # Matched and available. The credit stands TO THE 2B FIGURE, per head —
    # the aggregate cap's own arithmetic, applied where the section applies it.
    #
    # PER HEAD and never on the total: a bill booked as IGST that the supplier
    # filed as CGST+SGST is not a matching total, it is two wrong heads, and
    # netting them would claim IGST credit 2B does not communicate.
    heads = (("igst", d.igst_paise, two_b.igst_paise),
             ("cgst", d.cgst_paise, two_b.cgst_paise),
             ("sgst", d.sgst_paise, two_b.sgst_paise),
             ("cess", d.cess_paise, two_b.cess_paise))
    over = {}
    for name, book, filed in heads:
        # A NEGATIVE book figure is a note reducing credit and is never capped
        # UP to a larger 2B figure: the cap withholds, it never grants.
        allowed = book if book <= filed else filed
        setattr(allow, f"allowed_{name}_paise", allowed)
        withheld = book - allowed
        setattr(allow, f"withheld_{name}_paise", withheld)
        if withheld:
            over[name] = withheld
    if over:
        allow.verdict = MORE_THAN_2B
        allow.reason = (
            "The books carry more tax on this document than GSTR-2B "
            "communicated ("
            + ", ".join(f"{n.upper()} {v} paise" for n, v in over.items())
            + "). §16(2)(aa) allows the credit to the figure furnished; the "
              "excess is withheld until the supplier amends it.")
    return allow
