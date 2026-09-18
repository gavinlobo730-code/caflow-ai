"""A purchase return after the tax was already withheld (PUR-23 ≡ TDS-32).

WHAT HAPPENS TODAY. A ₹5,00,000 §194J bill is booked, ₹50,000 is withheld and
deposited, and the vendor then issues a credit note for ₹2,00,000 — a purchase
return, recorded here as a DEBIT note. `routers/debit_notes.py` and
`routers/purchase_credit_notes.py` contain no occurrence of "tds" in any case,
so nothing revisits `tds_deductions`, and the 26Q deductee row keeps saying
₹5,00,000 was credited to that PAN. The vendor's 26AS then shows credit on
income they did not earn, and the register will not tie to the purchase ledger
at year end.

WHICH OF THE TWO LAWFUL ANSWERS APPLIES IS NOW DECIDED, AND THE FACT THAT
DECIDES IT WAS ALREADY IN THE SCHEMA. This module used to end every sentence
with "which the books do not record", and that was wrong:
`tds_deductions.challan_date` and its `status` CHECK of
`deducted | deposited | filed` have existed since **migration 014**, and the
recorded plan to close this finding called for a migration to add them. No
migration was needed — the columns were there and nothing read them. Check the
premise before building to it.

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
either way. So the state is binary, plus the honest third where the row says
deposited and no date was recorded.

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
from typing import Optional

from domain.reporting.amount_words import indian_rupees
# One gap vocabulary. The code and its generic sentence live with the rest of
# the register's in domain/tds/residency, where a test holds every code to
# having a message; this module writes the per-BILL sentence, which is the one
# with the figures in it.
from domain.tds.residency import GAP_CREDIT_MOVED_AFTER_DEDUCTION


def _rupees(paise: int) -> str:
    """₹ and Indian grouping — one formatter, `amount_words.indian_rupees`.

    Python's own `f"{n:,}"` groups in threes and gives "5,00,000" as
    "500,000", which no Indian document uses; the browser formats the same
    figure with `Intl.NumberFormat("en-IN")` and gets it right, so a
    hand-rolled copy here would make the screen and the sentence disagree.
    """
    return f"₹{indian_rupees(paise)}"


#: The tax has not gone. The deductor can still deposit the smaller figure the
#: smaller aggregate calls for — s.194J(1) and its neighbours charge on "the
#: aggregate of the amounts of such sums credited or paid".
DEPOSIT_NOT_MADE = "not_deposited"
#: The tax has gone. s.200 discharged the duty and s.199 vested the credit in
#: the deductee, so the deduction stands and the deductor carries an excess
#: deposit to set against a later liability.
DEPOSIT_MADE = "deposited"
#: The row says deposited and no date was recorded, so nothing here can tell
#: which. NOT the same as `DEPOSIT_NOT_MADE`, and reading it that way would
#: tell a CA to reduce a deduction whose money may already be with the
#: department.
DEPOSIT_UNRECORDED = "unrecorded"

#: `tds_deductions.status` values that mean the challan has gone. `filed` is
#: stronger than `deposited` — the quarterly statement has also been delivered
#: — and both land in the same branch, because what decides is the payment.
_STATUS_MEANS_PAID = frozenset({"deposited", "filed"})


def deposit_state(*, challan_date=None, status: Optional[str] = None,
                  facts_known: bool = True) -> str:
    """Has the tax on this deduction been paid over?

    Reads `tds_deductions.challan_date` and `status`, which have both existed
    since **migration 014** and which nothing read until this finding was
    closed — the recorded plan called for a migration to add them.

    A DATE IS PROOF AND A STATUS ALONE IS NOT. A recorded `challan_date` settles
    it whatever the status says, because somebody wrote down the day the money
    went. A status of `deposited` with no date is the third answer: it is
    somebody's assertion with nothing behind it, and treating it as paid would
    tell a CA their remedy is an excess deposit when the challan may still be
    theirs to reduce, while treating it as unpaid would tell them to reduce a
    deduction already with the department. Both are wrong, so it says so.

    `deducted` with no date is the clean unpaid case and is the DEFAULT the
    column carries, so a register nobody has reconciled answers "not yet
    deposited" — which is true of it.

    `facts_known=False` says the CALLER could not read the row at all, which is
    a fourth situation and resolves to UNRECORDED. It is NOT the same as an
    absent row: a bill being synced for the first time genuinely has no
    deduction and therefore no challan, and "not yet deposited" is true of it,
    while a read that broke tells us nothing and must not be read as an answer.
    """
    if not facts_known:
        return DEPOSIT_UNRECORDED
    if challan_date:
        return DEPOSIT_MADE
    if (status or "").strip().lower() in _STATUS_MEANS_PAID:
        return DEPOSIT_UNRECORDED
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
    #: DEPOSIT_NOT_MADE | DEPOSIT_MADE | DEPOSIT_UNRECORDED — which of the two
    #: lawful answers applies, or that nothing here can tell.
    deposit_state: str = DEPOSIT_UNRECORDED

    @property
    def code(self) -> str:
        return GAP_CREDIT_MOVED_AFTER_DEDUCTION


def credit_moved_after_deduction(
    *,
    bill_no: Optional[str],
    section: Optional[str],
    credited_paise: int,
    tds_paise: int,
    returned_taxable_paise: int = 0,
    increased_taxable_paise: int = 0,
    challan_date=None,
    deduction_status: Optional[str] = None,
    deposit_facts_known: bool = True,
) -> Optional[CreditMovement]:
    """One sentence where a note has moved a credit the tax was withheld on,
    naming which of the two lawful answers applies.

    `challan_date` and `deduction_status` are the register row's own — see
    `deposit_state`. Both default to None, which resolves to "not yet
    deposited": that is what the column's own default says and it is the
    honest reading of a register nobody has reconciled, but a CALLER that
    simply forgets to pass them gets the recompute branch on a bill whose tax
    may have gone. The caller is `tds_register_service.sync_for_bill`, which
    reads the existing row, and a test pins that it passes both.

    `None` where nothing moved, or where nothing was withheld — a bill that
    deducted nil has no deductee row to be wrong, so a note against it is an
    ordinary purchase return and not this problem.
    """
    returned = max(0, int(returned_taxable_paise or 0))
    increased = max(0, int(increased_taxable_paise or 0))
    withheld = int(tds_paise or 0)
    if withheld <= 0 or (returned == 0 and increased == 0):
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

    state = deposit_state(challan_date=challan_date, status=deduction_status,
                          facts_known=deposit_facts_known)

    # The three endings. They are NOT interchangeable and each tells the CA to
    # do something different, which is the whole point of deciding the branch:
    # one says go and reduce the challan, one says do not try and carry the
    # excess instead, and one says go and record when the money went.
    if state == DEPOSIT_NOT_MADE:
        outcome = (
            f"The tax has not been paid over — no challan date is recorded against "
            f"this deduction — so the deduction may still be RECOMPUTED on "
            f"{_rupees(net)} before the challan goes, which is what the section "
            f"charges on. Re-check the year's aggregate rather than applying the "
            f"rate to that figure: a return can take the year back below the "
            f"section's threshold, and the deduction then falls away rather than "
            f"shrinking. Nothing here adjusts the register."
        )
    elif state == DEPOSIT_MADE:
        outcome = (
            f"The tax was paid over on {challan_date}, so section 200 discharged "
            f"the duty and section 199 gives the deductee credit for it. The "
            f"deduction STANDS and is not reduced; the deductor carries an excess "
            f"deposit of the tax on {_rupees(credited - net) if credited > net else _rupees(0)} "
            f"to set against a later liability. Nothing here adjusts the register."
        )
    else:
        why = (
            f"this deduction is marked '{(deduction_status or '').strip()}' and no "
            f"challan date is recorded"
            if deposit_facts_known else
            "the deduction's own challan details could not be read"
        )
        outcome = (
            f"Which answer applies cannot be told from the books — {why}. Record "
            f"the challan date on the deduction: before it the deduction may be "
            f"recomputed on {_rupees(net)}, after it the deduction stands and the "
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
