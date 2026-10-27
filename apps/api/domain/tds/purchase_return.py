"""A purchase return after the tax was already withheld (PUR-23 ≡ TDS-32).

WHAT HAPPENS TODAY. A ₹5,00,000 §194J bill is booked, ₹50,000 is withheld and
deposited, and the vendor then issues a credit note for ₹2,00,000 — a purchase
return, recorded here as a DEBIT note. `routers/debit_notes.py` and
`routers/purchase_credit_notes.py` contain no occurrence of "tds" in any case,
so nothing revisits `tds_deductions`, and the 26Q deductee row keeps saying
₹5,00,000 was credited to that PAN. The vendor's 26AS then shows credit on
income they did not earn, and the register will not tie to the purchase ledger
at year end.

WHICH OF THE TWO LAWFUL ANSWERS APPLIES IS DECIDED BY WHETHER THE TAX HAS BEEN
PAID OVER, AND THE CHALLAN REGISTER IS WHAT SAYS SO. This module used to end
every sentence with "which the books do not record". They do: a recorded
challan is the record. It first read `tds_deductions.challan_date` and its
`status` CHECK of `deducted | deposited | filed`, which have existed since
**migration 014** and which NOTHING WRITES (`POST /challans` records the challan
and never touches the deductions it paid), so a note on a bill whose tax had
gone was told it had not. The quarterly statement now hands each bill's
`DepositPosition` from the challan match it has already made (POST-A-271), and
that is the ONLY source: the two columns are no longer read here at all, and
`position` is a required argument with no default, because an absent fact used
to resolve to "not yet deposited" and a caller that forgot to pass one got the
recompute answer on money already with the department. Check the premise before
building to it: the first version of this finding assumed the columns were
written.

There are two lawful answers and the statute does not pick between them:

  • §194C(3), §194J(1) and their neighbours charge on "the aggregate of the
    amounts of such sums credited or paid". A return REVERSES part of the
    credit, so the aggregate that stands credited for the year is smaller than
    the deductee row reports. On that reading the deduction is recomputed —
    which is right where the note falls in the SAME quarter and before the tax
    has been deposited.
  • Once deposited, the tax is the deductee's: §199 gives them credit for tax
    deducted and paid on their behalf, and §200 required the deductor to pay
    it over. On that reading the deduction stands and the deductor carries an
    EXCESS DEPOSIT to set against a later liability.

ONLY ONE OF THOSE FACTS ACTUALLY DECIDES, AND IT IS NOT THE NOTE'S DATE. The
question is whether the tax has been PAID OVER. Until it has, the deductor can
still deposit the smaller figure the smaller aggregate calls for. Once it has,
§200 discharged the duty and §199 vested the credit in the deductee, and the
deductor's remedy is an excess deposit to set against a later liability — which
is what an OLTAS/TRACES carry-forward is for.

Whether the note PREDATES the challan is a hindsight observation about what the
deductor could have avoided, not a different legal answer: the money has gone
either way. So the state is binary, plus two honest others: only PART of the tax
has gone (the match is first in first out, so a short deposit leaves the last
deduction part-paid), and nothing here can tell (a challan was matched but is
dated before the tax was deducted, or the bill carries no date to compare).

THIS MODULE STILL ADJUSTS NOTHING, and that has not changed. Deciding the
BRANCH is the automation — it was impossible before and is what the finding
asked for. Writing a new figure into `tds_deductions` is a CA's act, and the
recompute branch in particular cannot be computed from this bill alone: a
return can take the YEAR'S aggregate back below the section's threshold, at
which point the whole deduction falls away rather than shrinking pro rata. The
sentence names that so nobody applies the rate to the net figure and calls it
the answer.

WHAT IS MEASURED. The TAXABLE value of the notes, never their totals. The
deductee row's `payment_amount_paise` excludes GST (CBDT Circular 23/2017), so
comparing it against a note total including GST would overstate the reduction
by the tax on it. The two note kinds move in OPPOSITE directions, and their
names on `purchase_bills` are the trap CLAUDE.md records: a DEBIT note is the
purchase return and REDUCES what is credited (`debited_paise`), while a
purchase CREDIT note is the supplier's §34(3) undercharge correction and
INCREASES it (`credit_note_paise`).

An INCREASE alone is reported too, and for the mirror reason: more has been
credited to the payee than the deductee row says, so the aggregate the section
charges on has grown and the deduction may be short — which is the §201(1A)
direction, and the expensive one.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

from domain.money_sentence import rupee_text, rupee_whole_text
# One gap vocabulary. The code and its generic sentence live with the rest of
# the register's in domain/tds/residency, where a test holds every code to
# having a message; this module writes the per-BILL sentence, which is the one
# with the figures in it.
from domain.tds.residency import GAP_CREDIT_MOVED_AFTER_DEDUCTION


def _rupees(paise: int) -> str:
    """₹ and Indian grouping — one grouping implementation, `domain/money_text`; paise are SHOWN when there are any.

    Python's own `f"{n:,}"` groups in threes and gives "5,00,000" as
    "500,000", which no Indian document uses; the browser formats the same
    figure with `Intl.NumberFormat("en-IN")` and gets it right, so a
    hand-rolled copy here would make the screen and the sentence disagree.

    WHOLE RUPEES ONLY WHEN THE FIGURE IS WHOLE. This used `amount_words.indian_rupees`, which truncates, so ₹72.80 of tax
    withheld read "₹72" in a sentence that compares it with what a challan paid; a part-paid deduction's two amounts then
    did not add up to its tax. Tax is stated to the paisa wherever it has one.
    """
    p = int(paise or 0)
    return rupee_text(p) if p % 100 else rupee_whole_text(p)


#: The tax has not gone, as far as the challan register shows. The deductor can
#: still deposit the smaller figure the smaller aggregate calls for — s.194J(1)
#: and its neighbours charge on "the aggregate of the amounts of such sums
#: credited or paid".
DEPOSIT_NOT_MADE = "not_deposited"
#: The tax has gone. s.200 discharged the duty and s.199 vested the credit in
#: the deductee, so the deduction stands and the deductor carries an excess
#: deposit to set against a later liability.
DEPOSIT_MADE = "deposited"
#: Nothing here can tell: a challan was matched to the deduction but is dated
#: before the tax was deducted (so it is not counted, and the deduction is not
#: shown as unpaid either), or the bill has no date to compare a challan's with.
#: NOT the same as `DEPOSIT_NOT_MADE`, and reading it that way would tell a CA
#: to reduce a deduction whose money may already be with the department.
DEPOSIT_UNRECORDED = "unrecorded"
#: Part of the tax has gone and part has not. Only the challan register can say
#: so, and it is a real situation: three monthly deposits are matched to a
#: quarter's deductions first in first out, so a short deposit leaves the LAST
#: deduction part-paid. Neither lawful answer is the whole story for it.
DEPOSIT_PARTLY = "partly_deposited"


@dataclass(frozen=True)
class DepositPosition:
    """What the CHALLAN REGISTER says about the tax withheld on ONE deduction.

    This is the real source of "has it gone". `tds_deductions.challan_date` and `.status` have been in the schema since
    migration 014 and NOTHING WRITES EITHER (`POST /challans` records the challan and never touches the deductions it
    paid), so a note on a bill whose tax HAD been deposited was told it had not and given the recompute answer on money
    already with the department. The register is asked instead, the way the quarterly statement and the deposit worksheet
    ask it (`domain/tds/challan_mapping`).

    `deposited_paise` is the part of `tax_paise` matched to challans that carry a date on or after the deduction;
    `last_paid_on` is the latest of those dates. `refused_before_deduction` says a challan WAS matched to it but is dated
    before the tax was deducted, which `challan_mapping.dated_parts` does not count (the match is by order, and tax cannot
    have been paid over before it existed). The statement's own deductee row counts such a challan as deposit; this does
    not, and says so."""
    tax_paise: int
    deposited_paise: int = 0
    last_paid_on: Optional[date] = None
    refused_before_deduction: bool = False


def deposit_position(tax_paise: int, parts: Iterable[tuple[int, date]], refused: bool = False) -> DepositPosition:
    """The position of one deduction from `challan_mapping.dated_parts`: [(paise, date paid)] and whether a challan was
    refused as dated before the deduction."""
    parts = list(parts)
    tax = max(0, int(tax_paise or 0))
    return DepositPosition(
        tax_paise=tax, deposited_paise=min(tax, sum(max(0, int(p)) for p, _ in parts)),
        last_paid_on=max((d for _, d in parts), default=None), refused_before_deduction=bool(refused))


def deposit_state(position: Optional[DepositPosition]) -> str:
    """Has the tax on this deduction been paid over, by what the challan register shows?

    `None` is "nothing here can tell" (no position could be made), never "not yet deposited": an unknown is not a value.
    All of the tax matched to dated challans is DEPOSIT_MADE, whatever else was refused. Otherwise a challan matched but
    dated before the deduction makes it UNRECORDED, whether or not some other part was paid, because the part the refused
    challan stood for is unknown and not "unpaid". Otherwise some of the tax matched is DEPOSIT_PARTLY, and none is
    DEPOSIT_NOT_MADE.
    """
    if position is None or position.tax_paise <= 0:
        return DEPOSIT_UNRECORDED
    if position.deposited_paise >= position.tax_paise:
        return DEPOSIT_MADE
    if position.refused_before_deduction:
        return DEPOSIT_UNRECORDED
    if position.deposited_paise > 0:
        return DEPOSIT_PARTLY
    return DEPOSIT_NOT_MADE


@dataclass(frozen=True)
class CreditMovement:
    """What a note did to a credit the tax was already withheld on."""
    bill_no: str
    section: str
    credited_paise: int            # what the deductee row reports
    returned_taxable_paise: int    # purchase returns — debit notes
    increased_taxable_paise: int   # §34(3) undercharge — purchase credit notes
    net_credited_paise: int        # what actually stands credited now
    tds_paise: int
    sentence: str
    #: DEPOSIT_NOT_MADE | DEPOSIT_MADE | DEPOSIT_PARTLY | DEPOSIT_UNRECORDED —
    #: which of the two lawful answers applies, that it is part of each, or that
    #: nothing here can tell.
    deposit_state: str = DEPOSIT_UNRECORDED

    @property
    def code(self) -> str:
        return GAP_CREDIT_MOVED_AFTER_DEDUCTION


def credit_has_moved(*, tds_paise: int, returned_taxable_paise: int = 0, increased_taxable_paise: int = 0) -> bool:
    """Whether a note has moved a credit the tax was withheld on: tax was withheld, and a purchase return or a supplier's
    undercharge note stands against the bill.

    THIS IS THE ONLY QUESTION THE REGISTER ASKS. `tds_register_service.sync_for_bill` records that a note moved the credit
    (the generic gap code) and nothing else: the sentence that says WHICH of the two lawful answers applies, which turns
    on whether the tax has gone, is written by the quarterly statement (`credit_moved_after_deduction`, with the challan
    register's answer). The register used to build that sentence too, from two columns nothing writes, and throw it away
    (POST-A-271); a bill that deducted nil has no deductee row to be wrong, so it is not this problem either."""
    withheld = int(tds_paise or 0)
    return withheld > 0 and (max(0, int(returned_taxable_paise or 0)) > 0 or max(0, int(increased_taxable_paise or 0)) > 0)


def credit_moved_after_deduction(
    *,
    bill_no: Optional[str],
    section: Optional[str],
    credited_paise: int,
    tds_paise: int,
    returned_taxable_paise: int = 0,
    increased_taxable_paise: int = 0,
    position: Optional[DepositPosition],
) -> Optional[CreditMovement]:
    """One sentence where a note has moved a credit the tax was withheld on,
    naming which answer applies.

    `position` is what the CHALLAN REGISTER says about this deduction (`DepositPosition`, built from
    `challan_mapping.dated_parts`) and is REQUIRED, with no default: the 26Q and 27Q builders pass it for each bill of the
    quarter from the statement's own challan match, and `None` means "no position could be made" (a bill with no date to
    compare a challan's with), which is its own answer and not "not yet deposited". A caller that cannot forget the
    argument cannot get the recompute answer on money already with the department by omission.

    WHICH WAY THE CREDIT MOVED DECIDES FIRST. A purchase return lowers what stands credited, and then the two lawful
    answers turn on whether the tax has gone. A supplier's undercharge note RAISES it, and then the deduction may be SHORT
    (the direction that carries section 201(1A) interest), whether or not the tax already withheld has been paid over.

    `None` where nothing moved, or where nothing was withheld — a bill that
    deducted nil has no deductee row to be wrong, so a note against it is an
    ordinary purchase return and not this problem.
    """
    returned = max(0, int(returned_taxable_paise or 0))
    increased = max(0, int(increased_taxable_paise or 0))
    withheld = int(tds_paise or 0)
    if not credit_has_moved(tds_paise=withheld, returned_taxable_paise=returned, increased_taxable_paise=increased):
        return None

    credited = int(credited_paise or 0)
    net = credited - returned + increased
    ref = (bill_no or "").strip() or "this bill"
    sec = (section or "").strip()
    sec_phrase = f" under section {sec}" if sec else ""

    moved: list[str] = []
    if returned:
        moved.append(f"{_rupees(returned)} has since been returned on a purchase return")
    if increased:
        moved.append(f"{_rupees(increased)} has since been added by a supplier credit note "
                     f"(CGST Act §34(3))")

    state = deposit_state(position)

    # The endings. They are NOT interchangeable and each tells the CA to do
    # something different, which is the whole point of deciding the branch: one
    # says go and reduce the challan, one says do not try and carry the excess
    # instead, one says the deduction may now be short, one says it is part of
    # each, and one says go and record the challan.
    if net > credited:
        outcome = (
            f"More now stands credited than the deductee row reports, so the deduction may be SHORT rather than in "
            f"excess: the section charges on {_rupees(net)}, and a short deduction is the direction that carries "
            f"interest under section 201(1A). Whether the tax already withheld has been paid over does not change "
            f"that. Re-check the year's aggregate and the rate before deducting the difference. "
            f"Nothing here adjusts the register."
        )
    elif state == DEPOSIT_NOT_MADE:
        outcome = (
            f"The books record no challan against this deduction, so — as far as they show — the tax has not been "
            f"paid over (if it went outside this product, record the challan and this changes), and the deduction may "
            f"still be RECOMPUTED on {_rupees(net)} before the challan goes, which is what the section "
            f"charges on. Re-check the year's aggregate rather than applying the "
            f"rate to that figure: a return can take the year back below the "
            f"section's threshold, and the deduction then falls away rather than "
            f"shrinking. Nothing here adjusts the register."
        )
    elif state == DEPOSIT_MADE:
        outcome = (
            f"The tax was paid over on {position.last_paid_on}, so section 200 discharged "
            f"the duty and section 199 gives the deductee credit for it. The "
            f"deduction STANDS and is not reduced; the deductor carries an excess "
            f"deposit of the tax on {_rupees(credited - net)} "
            f"to set against a later liability. Nothing here adjusts the register."
        )
    elif state == DEPOSIT_PARTLY:
        gone = position.deposited_paise
        outcome = (
            f"The tax is only partly paid over: {_rupees(gone)} of the {_rupees(withheld)} withheld went "
            f"by {position.last_paid_on} and {_rupees(withheld - gone)} has not. Neither answer fits the deduction as "
            f"a whole: for tax already paid over the deduction stands and the difference is an excess deposit, for tax "
            f"not yet paid over it may be recomputed on {_rupees(net)} before the challan goes, and this deduction is "
            f"part of each. How the two combine is a CA's decision and is not settled by the books. "
            f"Nothing here adjusts the register."
        )
    else:
        if position is None:
            why = "no challan could be compared with the date of this deduction"
        else:
            why = ("a challan recorded for this quarter was matched to it but is dated before the tax was deducted, "
                   "so it is not counted as having paid it")
        outcome = (
            f"Which answer applies cannot be told from the books — {why}. Record "
            f"the challan that paid it, with its date, in the challan register: before the tax was paid over "
            f"the deduction may be recomputed on {_rupees(net)}, after it the deduction stands and the "
            f"difference is an excess deposit. Nothing here adjusts the register."
        )

    sentence = (
        f"Bill {ref} credited {_rupees(credited)} with {_rupees(withheld)} withheld"
        f"{sec_phrase}, and {' and '.join(moved)}. The deductee row still reports "
        f"{_rupees(credited)} credited; what stands credited is {_rupees(net)}. "
        + outcome
    )
    return CreditMovement(
        bill_no=ref, section=sec, credited_paise=credited,
        returned_taxable_paise=returned, increased_taxable_paise=increased,
        net_credited_paise=net, tds_paise=withheld, sentence=sentence,
        deposit_state=state,
    )
