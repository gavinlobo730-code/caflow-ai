"""A purchase return after the tax was already withheld (PUR-23 ≡ TDS-32).

WHAT HAPPENS TODAY. A ₹5,00,000 §194J bill is booked, ₹50,000 is withheld and
deposited, and the vendor then issues a credit note for ₹2,00,000 — a purchase
return, recorded here as a DEBIT note. `routers/debit_notes.py` and
`routers/purchase_credit_notes.py` contain no occurrence of "tds" in any case,
so nothing revisits `tds_deductions`, and the 26Q deductee row keeps saying
₹5,00,000 was credited to that PAN. The vendor's 26AS then shows credit on
income they did not earn, and the register will not tie to the purchase ledger
at year end.

WHY THIS MODULE REPORTS AND DOES NOT ADJUST. There are two lawful answers and
the statute does not pick between them:

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

Which applies turns on when the note was raised, whether the challan has gone,
and what the deductor and the vendor have agreed — facts no ledger holds. So
this module states the divergence in one sentence and changes no figure, the
same discipline the register already takes on a catch-up bill whose three
money columns do not multiply out.

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
) -> Optional[CreditMovement]:
    """One sentence where a note has moved a credit the tax was withheld on.

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

    sentence = (
        f"Bill {ref} credited {_rupees(credited)} with {_rupees(withheld)} withheld"
        f"{sec_phrase}, and {' and '.join(moved)}. The deductee row still reports "
        f"{_rupees(credited)} credited; what stands credited is {_rupees(net)}. "
        f"The section charges the aggregate of the sums credited or paid, while tax "
        f"already deducted and paid over is the deductee's under section 199 — so a "
        f"note in the same quarter and before the challan is normally taken as "
        f"reducing the deduction, and one after it as an excess deposit to set "
        f"against a later liability. Nothing here adjusts either figure: which "
        f"applies turns on when the challan went, which the books do not record."
    )
    return CreditMovement(
        bill_no=ref, section=sec, credited_paise=credited,
        returned_taxable_paise=returned, increased_taxable_paise=increased,
        net_credited_paise=net, tds_paise=withheld, sentence=sentence,
    )
